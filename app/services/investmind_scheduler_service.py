"""
InvestMind v3 scheduler jobs.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.core.database import get_mongo_db
from app.models.notification import NotificationCreate
from app.services.notifications_service import get_notifications_service
from app.services.thesis_service import thesis_service

logger = logging.getLogger("app.services.investmind_scheduler")


def _build_signal_bundle(quote: Dict[str, Any]) -> Dict[str, Any]:
    try:
        pct_chg = float(quote.get("pct_chg", 0.0) or 0.0)
    except Exception:
        pct_chg = 0.0

    signal_tags = []
    bearish_tags = []
    if pct_chg >= 2:
        signal_tags.extend(["technical", "momentum"])
    elif pct_chg >= 0.5:
        signal_tags.append("technical")
    if pct_chg <= -2:
        bearish_tags.extend(["technical", "risk"])

    return {
        "signal_tags": signal_tags,
        "bearish_tags": bearish_tags,
        "pct_chg": pct_chg,
        "price": quote.get("close"),
    }


async def run_thesis_monitor_scan() -> None:
    db = get_mongo_db()
    items = await db["theses"].find({"status": "active"}).to_list(length=None)
    notifications = get_notifications_service()

    for thesis in items:
        symbol = thesis.get("symbol")
        user_id = thesis.get("user_id")
        if not symbol or not user_id:
            continue

        quote = await db["market_quotes"].find_one({"$or": [{"code": symbol}, {"symbol": symbol}]}, sort=[("_id", -1)])
        if not quote:
            continue

        updated = await thesis_service.validate_signal_bundle(user_id, symbol, _build_signal_bundle(quote))
        if not updated:
            continue

        health_score = float(updated.get("health_score", 1.0) or 1.0)
        if health_score < 0.4:
            await notifications.create_and_publish(
                NotificationCreate(
                    user_id=user_id,
                    type="thesis_alert",
                    title=f"{symbol} Thesis 监控告警",
                    content=f"15 分钟监控检测到 Thesis 健康度降至 {health_score:.2f}",
                    link="/thesis",
                    severity="warning",
                    metadata={"symbol": symbol, "thesis_id": updated.get("_id")},
                )
            )


async def run_daily_investmind_digest() -> None:
    db = get_mongo_db()
    user_ids = await db["theses"].distinct("user_id")
    notifications = get_notifications_service()

    for user_id in user_ids:
        overview = await thesis_service.get_overview(user_id)
        await notifications.create_and_publish(
            NotificationCreate(
                user_id=user_id,
                type="thesis_alert",
                title="InvestMind 每日简报",
                content=(
                    f"激活 {overview.active_count} 条，观察池 {overview.watchlist_count} 条，"
                    f"破裂预警 {overview.broken_count} 条。"
                ),
                link="/thesis",
                severity="info",
                metadata=overview.model_dump(),
            )
        )


async def run_edge_refresh() -> None:
    db = get_mongo_db()
    user_ids = sorted(set(await db["trade_journal_entries"].distinct("user_id")) | set(await db["theses"].distinct("user_id")))
    notifications = get_notifications_service()

    for user_id in user_ids:
        profile = await thesis_service.build_edge_profile(user_id)
        await thesis_service.generate_cognitive_snapshot(user_id)
        await notifications.create_and_publish(
            NotificationCreate(
                user_id=user_id,
                type="edge_report",
                title="InvestMind 周期画像已刷新",
                content="Edge Discovery 与 Cognitive Mirror 已完成周期刷新",
                link="/edge-discovery",
                severity="success",
                metadata={"generated_at": profile.get("generated_at")},
            )
        )
