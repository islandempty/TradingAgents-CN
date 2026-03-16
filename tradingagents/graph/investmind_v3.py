"""
InvestMind v3 workflow helper.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Dict, Optional, Tuple

from bson import ObjectId

from tradingagents.utils.logging_manager import get_logger

logger = get_logger("agents.investmind_v3")


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _emit_progress(progress_callback, message: str) -> None:
    if progress_callback:
        try:
            progress_callback(message)
        except Exception as exc:
            logger.warning(f"InvestMind v3 进度回调失败: {exc}")


def _load_market_snapshot(db, symbol: str) -> Dict[str, Any]:
    quote = db["market_quotes"].find_one(
        {"$or": [{"code": symbol}, {"symbol": symbol}]},
        sort=[("_id", -1)],
    ) or {}
    basic = db["stock_basic_info"].find_one(
        {"$or": [{"code": symbol}, {"symbol": symbol}]},
        {"name": 1, "industry": 1, "market": 1, "sse": 1, "current_price": 1},
    ) or {}

    price = quote.get("close")
    if price is None:
        price = basic.get("current_price")
    try:
        price = float(price) if price is not None else None
    except Exception:
        price = None

    try:
        pct_chg = float(quote.get("pct_chg", 0.0) or 0.0)
    except Exception:
        pct_chg = 0.0

    return {
        "price": price,
        "pct_chg": pct_chg,
        "name": basic.get("name") or symbol,
        "industry": basic.get("industry") or basic.get("market") or "未知行业",
        "exchange": basic.get("sse") or "未知交易所",
    }


def _load_position(db, user_id: Optional[str], symbol: str, position_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not user_id:
        return None

    if position_id:
        try:
            position = db["paper_positions"].find_one({"_id": ObjectId(position_id), "user_id": user_id})
            if position:
                return position
        except Exception:
            pass

    return db["paper_positions"].find_one(
        {
            "user_id": user_id,
            "code": symbol,
            "$or": [
                {"status": {"$exists": False}},
                {"status": {"$ne": "closed"}},
                {"quantity": {"$gt": 0}},
            ],
        }
    )


def _risk_regime(pct_chg: float) -> Dict[str, Any]:
    if pct_chg >= 1.5:
        regime = "risk_on"
        exposure = 0.8
    elif pct_chg <= -1.5:
        regime = "risk_off"
        exposure = 0.4
    else:
        regime = "neutral"
        exposure = 0.6
    return {
        "regime": regime,
        "score": round(0.5 + max(min(pct_chg / 10.0, 0.35), -0.35), 4),
        "recommended_total_exposure_pct": exposure,
        "position_cap_pct": 0.05,
        "sector_cap_pct": 0.30,
    }


def _sector_rotation(industry: str, pct_chg: float) -> Dict[str, Any]:
    if pct_chg >= 2:
        signal = "overweight"
    elif pct_chg <= -2:
        signal = "underweight"
    else:
        signal = "neutral"
    return {
        "sector": industry,
        "signal": signal,
        "evidence": f"近端价格变化 {pct_chg:.2f}%",
    }


def run_investmind_v3_workflow(
    trading_graph,
    company_name: str,
    trade_date: str,
    progress_callback=None,
    task_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    del task_id

    from app.core.database import get_mongo_db_sync
    from app.models.thesis import CreateThesisRequest, ThesisStatus
    from app.services.thesis_service import thesis_service

    started_at = time.time()
    user_id = trading_graph.config.get("user_id")
    thesis_id = trading_graph.config.get("thesis_id")
    position_id = trading_graph.config.get("position_id")
    symbol = company_name.strip().upper()

    _emit_progress(progress_callback, "🔍 变化检测")
    db = get_mongo_db_sync()
    snapshot = _load_market_snapshot(db, symbol)
    position = _load_position(db, user_id, symbol, position_id)
    previous_signal = db["signal_snapshots"].find_one({"symbol": symbol}, sort=[("_id", -1)]) or {}

    price = snapshot.get("price")
    pct_chg = float(snapshot.get("pct_chg", 0.0) or 0.0)
    signal_tags = []
    bearish_tags = []
    if pct_chg >= 2:
        signal_tags.extend(["technical", "momentum"])
    elif pct_chg >= 0.5:
        signal_tags.append("technical")
    if pct_chg <= -2:
        bearish_tags.extend(["technical", "risk"])

    change_mode = "FULL"
    if previous_signal:
        delta = abs(pct_chg - float(previous_signal.get("pct_chg", 0.0) or 0.0))
        if delta < 0.8:
            change_mode = "CACHED"
        elif delta < 2.5:
            change_mode = "LIGHT"

    macro_assessment = _risk_regime(pct_chg)
    sector_rotation = _sector_rotation(snapshot.get("industry", "未知行业"), pct_chg)
    signal_bundle = {
        "mode": change_mode,
        "signal_tags": sorted(set(signal_tags)),
        "bearish_tags": sorted(set(bearish_tags)),
        "pct_chg": pct_chg,
        "price": price,
    }

    existing_thesis = None
    if user_id and thesis_id:
        existing_thesis = _run_async(thesis_service.get_thesis(user_id, thesis_id))
    if user_id and not existing_thesis:
        existing_thesis = _run_async(thesis_service.get_active_thesis_for_symbol(user_id, symbol))
    if not existing_thesis and position and position.get("thesis_id") and user_id:
        existing_thesis = _run_async(thesis_service.get_thesis(user_id, position["thesis_id"]))

    thesis_context = existing_thesis
    if existing_thesis and user_id:
        _emit_progress(progress_callback, "🧠 Thesis 验证")
        thesis_context = _run_async(thesis_service.validate_signal_bundle(user_id, symbol, signal_bundle)) or existing_thesis

    created_thesis = None
    if not thesis_context and user_id:
        confidence_seed = min(max(abs(pct_chg) / 5.0, 0.2), 0.9)
        if pct_chg >= 2:
            created_thesis = _run_async(
                thesis_service.create_thesis(
                    user_id,
                    CreateThesisRequest(
                        symbol=symbol,
                        symbol_name=snapshot.get("name"),
                        status=ThesisStatus.DRAFT,
                        thesis_title=f"{symbol} Thesis 草稿",
                        thesis_summary=f"基于价格变化与结构化信号为 {symbol} 自动生成的 Thesis 草稿",
                        signal_confidence=round(confidence_seed, 2),
                        watch_reason="强信号触发 Thesis Builder",
                        metadata={"created_by": "investmind_v3", "change_mode": change_mode},
                    ),
                )
            )
        else:
            created_thesis = _run_async(
                thesis_service.create_watchlist_thesis(
                    user_id,
                    symbol,
                    snapshot.get("name"),
                    round(confidence_seed, 2),
                    "弱信号进入观察池",
                )
            )
        thesis_context = created_thesis

    health_score = float((thesis_context or {}).get("health_score", 1.0) or 1.0)
    thesis_health = {
        "status": (thesis_context or {}).get("thesis_health", "完好"),
        "score": round(health_score, 4),
        "thesis_id": (thesis_context or {}).get("_id"),
    }

    _emit_progress(progress_callback, "⚖️ 结构化辩论")
    bull_case = [
        f"价格变化 {pct_chg:.2f}% 反映短期资金正在重新评估 {symbol}",
        f"宏观环境判定为 {macro_assessment['regime']}",
        f"行业方向当前为 {sector_rotation['signal']}",
    ]
    bear_case = [
        "若 Thesis 健康度下降，应优先执行纪律而不是继续加仓",
        "观察到的信号仍偏单一，需要更多基本面验证",
    ]
    if bearish_tags:
        bear_case.append(f"检测到负向标签: {', '.join(bearish_tags)}")
    if thesis_context and health_score < 0.7:
        bear_case.append(f"Thesis 健康度仅 {health_score:.2f}")

    strong_positive_signal = pct_chg >= 2 and not bearish_tags
    skip_debate = bool(thesis_context and health_score >= 0.75 and not bearish_tags)
    arbiter_action = "hold"
    arbiter_reason = "Thesis 健康且未出现新的证伪信号"
    if not thesis_context:
        arbiter_action = "build" if strong_positive_signal else "watch"
        arbiter_reason = "暂无 Thesis，先进入 Builder 或观察池"
    elif health_score < 0.4:
        arbiter_action = "exit"
        arbiter_reason = "核心假设已破裂"
    elif health_score < 0.7 or bearish_tags:
        arbiter_action = "reduce"
        arbiter_reason = "信号开始弱化，需要降仓与复核"

    debate_verdict = {
        "path": "skip_debate" if skip_debate else "bull_bear_arbiter",
        "bull_case": bull_case,
        "bear_case": bear_case,
        "winner": arbiter_action,
        "confidence": round(min(max(health_score, 0.35), 0.92), 2),
        "reason": arbiter_reason,
        "blind_spots": ["缺少更长周期的宏观与行业共振验证"],
    }

    _emit_progress(progress_callback, "🛡️ 风险校验")
    stop_loss = (position or {}).get("stop_loss") or (thesis_context or {}).get("stop_loss")
    target_price = (position or {}).get("target_price") or (thesis_context or {}).get("target_price")
    position_pct = float((thesis_context or {}).get("current_position_pct") or 0.0)

    exit_action = "HOLD"
    exit_priority = "none"
    exit_reason = "继续观察 Thesis 健康度"
    if health_score < 0.4:
        exit_action = "EXIT"
        exit_priority = "thesis_break"
        exit_reason = "核心假设破裂"
    elif stop_loss and price is not None and price <= float(stop_loss):
        exit_action = "EXIT"
        exit_priority = "stop_loss"
        exit_reason = f"价格触发止损位 {stop_loss}"
    elif target_price and price is not None and price >= float(target_price):
        exit_action = "REDUCE"
        exit_priority = "target_price"
        exit_reason = f"价格达到目标位 {target_price}"
    elif macro_assessment["regime"] == "risk_off" and position_pct > 0.05:
        exit_action = "REDUCE"
        exit_priority = "macro_exposure"
        exit_reason = "宏观环境转弱，建议下调总仓位"
    elif health_score < 0.7:
        exit_action = "REDUCE"
        exit_priority = "weakening"
        exit_reason = "Thesis 弱化，需要降低暴露"

    exit_decision = {
        "action": exit_action,
        "priority": exit_priority,
        "reason": exit_reason,
        "position_cap_pct": 0.05,
        "sector_cap_pct": 0.30,
        "total_exposure_cap_pct": macro_assessment["recommended_total_exposure_pct"],
    }

    cognitive_mirror = {
        "bias_flags": ["短期价格信号占比偏高"] if not thesis_context else [],
        "discipline_note": "先验证 Thesis，再决定是否加仓或退出",
        "trace": [
            f"change_detector={change_mode}",
            f"thesis_health={thesis_health['score']:.2f}",
            f"arbiter={debate_verdict['winner']}",
            f"exit={exit_decision['action']}",
        ],
    }

    action = exit_action if thesis_context else ("BUILD" if strong_positive_signal else "WATCH")
    confidence = round(min(max((health_score + min(abs(pct_chg) / 5.0, 0.25)), 0.3), 0.93), 2)
    risk_score = round(1 - min(max(health_score, 0.0), 1.0), 2)
    reasoning = f"{arbiter_reason}；{exit_reason}。宏观环境 {macro_assessment['regime']}，行业信号 {sector_rotation['signal']}。"
    key_points = [
        f"变化检测模式: {change_mode}",
        f"Thesis 健康度: {thesis_health['score']:.2f}",
        f"仲裁结果: {debate_verdict['winner']}",
        f"退出决策: {exit_decision['action']}",
    ]

    market_report = (
        f"# 市场变化检测\n\n"
        f"- 标的: {symbol}\n"
        f"- 最新价格: {price if price is not None else 'N/A'}\n"
        f"- 涨跌幅: {pct_chg:.2f}%\n"
        f"- 变化模式: {change_mode}\n"
        f"- 宏观状态: {macro_assessment['regime']}\n"
    )
    fundamentals_report = (
        f"# Thesis 验证\n\n"
        f"- Thesis ID: {(thesis_context or {}).get('_id', '未建立')}\n"
        f"- 健康度: {thesis_health['score']:.2f}\n"
        f"- 状态: {thesis_health['status']}\n"
        f"- 行业: {snapshot.get('industry')}\n"
    )
    news_report = (
        f"# 结构化辩论\n\n"
        f"- 多头观点: {'；'.join(bull_case)}\n"
        f"- 空头观点: {'；'.join(bear_case)}\n"
        f"- 仲裁: {debate_verdict['winner']} ({debate_verdict['reason']})\n"
    )
    sentiment_report = (
        f"# Risk Agent\n\n"
        f"- 当前动作: {exit_decision['action']}\n"
        f"- 执行优先级: {exit_decision['priority']}\n"
        f"- 仓位上限: 单票 5%, 行业 30%\n"
        f"- 总仓位上限: {macro_assessment['recommended_total_exposure_pct']:.0%}\n"
    )
    investment_plan = (
        f"# InvestMind v3 投资计划\n\n"
        f"建议动作: {action}\n\n"
        f"1. 变化检测模式为 {change_mode}\n"
        f"2. Thesis 健康度为 {thesis_health['score']:.2f}\n"
        f"3. 风险动作建议为 {exit_decision['action']}\n"
    )
    final_trade_decision = (
        f"# 最终交易决策\n\n"
        f"- 标的: {symbol}\n"
        f"- 建议: {action}\n"
        f"- 置信度: {confidence:.2f}\n"
        f"- 核心理由: {reasoning}\n"
        f"- Thesis 健康度: {thesis_health['score']:.2f}\n"
        f"- Exit Machine: {exit_decision['action']} ({exit_decision['priority']})\n"
    )

    thesis_record_id = (thesis_context or {}).get("_id") or (created_thesis or {}).get("_id")
    if user_id and thesis_record_id:
        try:
            _run_async(
                thesis_service.record_debate_record(
                    user_id,
                    symbol=symbol,
                    thesis_id=thesis_record_id,
                    debate_verdict=debate_verdict,
                    bull_case=bull_case,
                    bear_case=bear_case,
                    signal_bundle=signal_bundle,
                    exit_decision=exit_decision,
                    macro_assessment=macro_assessment,
                    sector_rotation=sector_rotation,
                    workflow_mode="investmind_v3",
                )
            )
        except Exception as exc:
            logger.warning(f"InvestMind v3 辩论记录写入失败: {exc}")

    db["signal_snapshots"].insert_one(
        {
            "symbol": symbol,
            "date": trade_date,
            "pct_chg": pct_chg,
            "price": price,
            "signal_tags": signal_bundle["signal_tags"],
            "bearish_tags": signal_bundle["bearish_tags"],
            "workflow_mode": "investmind_v3",
            "created_at": trade_date,
        }
    )

    final_state = {
        "messages": [],
        "company_of_interest": symbol,
        "trade_date": trade_date,
        "sender": "InvestMind v3",
        "market_report": market_report,
        "sentiment_report": sentiment_report,
        "news_report": news_report,
        "fundamentals_report": fundamentals_report,
        "market_tool_call_count": 0,
        "news_tool_call_count": 0,
        "sentiment_tool_call_count": 0,
        "fundamentals_tool_call_count": 0,
        "investment_debate_state": {
            "bull_history": " | ".join(bull_case),
            "bear_history": " | ".join(bear_case),
            "history": " | ".join(bull_case + bear_case),
            "current_response": debate_verdict["reason"],
            "judge_decision": debate_verdict["winner"],
            "count": 1,
        },
        "investment_plan": investment_plan,
        "trader_investment_plan": investment_plan,
        "risk_debate_state": {
            "risky_history": f"偏进攻观点: {bull_case[0]}",
            "safe_history": f"偏防守观点: {bear_case[0]}",
            "neutral_history": f"中性观点: {exit_reason}",
            "history": exit_reason,
            "latest_speaker": "Risk Judge",
            "current_risky_response": bull_case[0],
            "current_safe_response": bear_case[0],
            "current_neutral_response": exit_reason,
            "judge_decision": exit_action,
            "count": 1,
        },
        "final_trade_decision": final_trade_decision,
        "workflow_mode": "investmind_v3",
        "signal_bundle": signal_bundle,
        "thesis_context": thesis_context,
        "debate_verdict": debate_verdict,
        "exit_decision": exit_decision,
        "macro_assessment": macro_assessment,
        "sector_rotation": sector_rotation,
        "cognitive_trace": cognitive_mirror,
        "performance_metrics": {
            "total_time": round(time.time() - started_at, 2),
            "workflow_mode": "investmind_v3",
        },
    }

    trading_graph.curr_state = final_state
    trading_graph.ticker = symbol
    trading_graph.log_states_dict[str(trade_date)] = final_state

    decision = {
        "action": action,
        "confidence": confidence,
        "risk_score": risk_score,
        "target_price": target_price,
        "reasoning": reasoning,
        "summary": final_trade_decision.replace("#", "").strip(),
        "recommendation": f"{action}，并执行 {exit_decision['action']} 风险动作",
        "risk_level": "高" if risk_score >= 0.6 else "中" if risk_score >= 0.3 else "低",
        "key_points": key_points,
        "tokens_used": 0,
        "thesis": thesis_context,
        "thesis_health": thesis_health,
        "debate_verdict": debate_verdict,
        "exit_decision": exit_decision,
        "macro_assessment": macro_assessment,
        "sector_rotation": sector_rotation,
        "cognitive_mirror": cognitive_mirror,
        "workflow_mode": "investmind_v3",
    }

    if created_thesis:
        decision["thesis"] = created_thesis
        decision["recommendation"] = f"{decision['recommendation']}；已自动创建 Thesis"

    return final_state, decision
