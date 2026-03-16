"""
InvestMind v3 Thesis 服务。
"""

from __future__ import annotations

import csv
import io
import logging
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app.core.database import get_mongo_db
from app.models.thesis import (
    ActivateThesisRequest,
    AssumptionStatus,
    CloseThesisRequest,
    CreateThesisRequest,
    ThesisDocument,
    ThesisOverview,
    ThesisStatus,
    ThesisVersionDocument,
    TradeImportPreview,
    UpdateThesisRequest,
)
from app.utils.timezone import now_tz

logger = logging.getLogger("app.services.thesis_service")


STATUS_SCORES = {
    AssumptionStatus.INTACT.value: 1.0,
    AssumptionStatus.WEAKENING.value: 0.5,
    AssumptionStatus.BROKEN.value: 0.0,
}


class ThesisService:
    def __init__(self) -> None:
        self.db = None
        self.thesis_collection = "theses"
        self.version_collection = "thesis_versions"
        self.edge_collection = "edge_profiles"
        self.cognitive_collection = "cognitive_snapshots"
        self.debate_collection = "debate_records"
        self.signal_collection = "signal_snapshots"
        self.trade_journal_collection = "trade_journal_entries"

    async def _get_db(self):
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    async def ensure_indexes(self) -> None:
        db = await self._get_db()
        await db[self.thesis_collection].create_index([("user_id", 1), ("symbol", 1), ("status", 1)])
        await db[self.thesis_collection].create_index([("user_id", 1), ("updated_at", -1)])
        await db[self.version_collection].create_index([("thesis_id", 1), ("version", -1)])
        await db[self.edge_collection].create_index([("user_id", 1), ("generated_at", -1)])
        await db[self.cognitive_collection].create_index([("user_id", 1), ("generated_at", -1)])
        await db[self.trade_journal_collection].create_index([("user_id", 1), ("timestamp", -1)])
        await db[self.signal_collection].create_index([("symbol", 1), ("date", -1)])
        await db[self.debate_collection].create_index([("user_id", 1), ("symbol", 1), ("created_at", -1)])

    def _serialize_doc(self, doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not doc:
            return None
        data = deepcopy(doc)
        if "_id" in data:
            data["_id"] = str(data["_id"])
        for field in ("created_at", "updated_at", "activated_at", "closed_at", "date", "generated_at", "timestamp"):
            if isinstance(data.get(field), datetime):
                data[field] = data[field].isoformat()
        for assumption in data.get("core_assumptions", []):
            if isinstance(assumption.get("last_checked"), datetime):
                assumption["last_checked"] = assumption["last_checked"].isoformat()
        return data

    def _build_thesis_id_query(self, thesis_id: str) -> Dict[str, Any]:
        candidates: List[Any] = [thesis_id]
        if ObjectId.is_valid(thesis_id):
            candidates.append(ObjectId(thesis_id))
        return {"$in": candidates}

    def compute_health_score(self, thesis_doc: Dict[str, Any]) -> float:
        assumptions = thesis_doc.get("core_assumptions", []) or []
        if not assumptions:
            return 1.0
        total_weight = sum(float(item.get("weight", 1.0) or 1.0) for item in assumptions)
        if total_weight <= 0:
            total_weight = float(len(assumptions))
        base = 0.0
        broken = False
        for item in assumptions:
            weight = float(item.get("weight", 1.0) or 1.0)
            status = item.get("status", AssumptionStatus.INTACT.value)
            score = STATUS_SCORES.get(status, 1.0)
            broken = broken or status == AssumptionStatus.BROKEN.value
            base += weight * score
        result = round(base / total_weight, 4)
        return min(result, 0.35) if broken else result

    def derive_health_label(self, health_score: float) -> str:
        if health_score < 0.4:
            return AssumptionStatus.BROKEN.value
        if health_score < 0.7:
            return AssumptionStatus.WEAKENING.value
        return AssumptionStatus.INTACT.value

    async def _record_version(
        self,
        user_id: str,
        thesis_doc: Dict[str, Any],
        change_description: str,
        triggered_by: str,
        previous_health: Optional[float] = None,
    ) -> None:
        db = await self._get_db()
        health_delta = None
        if previous_health is not None:
            health_delta = round(float(thesis_doc.get("health_score", 1.0)) - previous_health, 4)
        version_doc = ThesisVersionDocument(
            thesis_id=str(thesis_doc["_id"]),
            user_id=user_id,
            version=int(thesis_doc.get("version", 1)),
            snapshot=self._serialize_doc(thesis_doc) or {},
            change_description=change_description,
            health_delta=health_delta,
            triggered_by=triggered_by,
        )
        await db[self.version_collection].insert_one(version_doc.model_dump(by_alias=True))

    def _normalize_create_payload(self, payload: CreateThesisRequest) -> Dict[str, Any]:
        data = payload.model_dump()
        if not data.get("thesis_title"):
            data["thesis_title"] = f"{payload.symbol} Thesis"
        if not data.get("thesis_summary"):
            data["thesis_summary"] = f"{payload.symbol} 的结构化投资 Thesis"
        if not data.get("core_assumptions"):
            data["core_assumptions"] = [
                {
                    "id": "A1",
                    "statement": f"{payload.symbol} 的基本面持续改善",
                    "evidence_at_creation": "待补充",
                    "signal_tags": ["fundamentals"],
                    "weight": 0.4,
                    "status": AssumptionStatus.INTACT.value,
                    "health_score": 1.0,
                    "invalidation_threshold": 0.3,
                    "history": [],
                },
                {
                    "id": "A2",
                    "statement": f"{payload.symbol} 的行业趋势维持正向",
                    "evidence_at_creation": "待补充",
                    "signal_tags": ["news", "macro"],
                    "weight": 0.3,
                    "status": AssumptionStatus.INTACT.value,
                    "health_score": 1.0,
                    "invalidation_threshold": 0.3,
                    "history": [],
                },
                {
                    "id": "A3",
                    "statement": f"{payload.symbol} 的风险回报比依旧可接受",
                    "evidence_at_creation": "待补充",
                    "signal_tags": ["technical", "risk"],
                    "weight": 0.3,
                    "status": AssumptionStatus.INTACT.value,
                    "health_score": 1.0,
                    "invalidation_threshold": 0.3,
                    "history": [],
                },
            ]
        data["health_score"] = self.compute_health_score(data)
        data["thesis_health"] = self.derive_health_label(data["health_score"])
        return data

    async def create_thesis(self, user_id: str, payload: CreateThesisRequest) -> Dict[str, Any]:
        await self.ensure_indexes()
        db = await self._get_db()
        now = now_tz()
        data = self._normalize_create_payload(payload)
        doc = ThesisDocument(
            user_id=user_id,
            **data,
            created_at=now,
            updated_at=now,
        ).model_dump(by_alias=True)
        result = await db[self.thesis_collection].insert_one(doc)
        stored = await db[self.thesis_collection].find_one({"_id": result.inserted_id})
        if stored:
            await self._record_version(
                user_id=user_id,
                thesis_doc=stored,
                change_description="初始建立",
                triggered_by="user",
            )
        if payload.create_watchlist_entry:
            await db.user_favorites.update_many(
                {"user_id": user_id, "favorites.stock_code": payload.symbol},
                {
                    "$set": {
                        "favorites.$.linked_thesis_id": str(result.inserted_id),
                        "favorites.$.watch_reason": payload.watch_reason or "手动加入 Thesis 观察池",
                        "favorites.$.signal_confidence": payload.signal_confidence,
                        "updated_at": now,
                    }
                },
            )
        return self._serialize_doc(stored) or {"_id": str(result.inserted_id)}

    async def list_theses(
        self,
        user_id: str,
        *,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        await self.ensure_indexes()
        db = await self._get_db()
        query: Dict[str, Any] = {"user_id": user_id}
        if status:
            query["status"] = status
        if symbol:
            query["symbol"] = symbol
        cursor = db[self.thesis_collection].find(query).sort("updated_at", -1)
        items = await cursor.to_list(length=None)
        return [self._serialize_doc(item) for item in items]

    async def get_thesis(self, user_id: str, thesis_id: str) -> Optional[Dict[str, Any]]:
        db = await self._get_db()
        doc = await db[self.thesis_collection].find_one(
            {"_id": self._build_thesis_id_query(thesis_id), "user_id": user_id}
        )
        return self._serialize_doc(doc)

    async def get_active_thesis_for_symbol(self, user_id: str, symbol: str) -> Optional[Dict[str, Any]]:
        db = await self._get_db()
        doc = await db[self.thesis_collection].find_one(
            {"user_id": user_id, "symbol": symbol, "status": ThesisStatus.ACTIVE.value},
            sort=[("updated_at", -1)],
        )
        return self._serialize_doc(doc)

    async def update_thesis(self, user_id: str, thesis_id: str, payload: UpdateThesisRequest) -> Optional[Dict[str, Any]]:
        db = await self._get_db()
        id_query = self._build_thesis_id_query(thesis_id)
        current = await db[self.thesis_collection].find_one({"_id": id_query, "user_id": user_id})
        if not current:
            return None
        previous_health = float(current.get("health_score", 1.0))
        update_data = payload.model_dump(exclude_none=True)
        change_description = update_data.pop("change_description", None) or "更新 Thesis"
        triggered_by = update_data.pop("triggered_by", "user")
        if "core_assumptions" in update_data:
            merged_state = current | update_data
            update_data["health_score"] = self.compute_health_score(merged_state)
            update_data["thesis_health"] = self.derive_health_label(update_data["health_score"])
        update_data["updated_at"] = now_tz()
        if update_data.get("status") == ThesisStatus.ACTIVE.value and not current.get("activated_at"):
            update_data["activated_at"] = now_tz()
        if update_data.get("status") == ThesisStatus.CLOSED.value:
            update_data["closed_at"] = now_tz()
        await db[self.thesis_collection].update_one(
            {"_id": id_query, "user_id": user_id},
            {"$set": update_data, "$inc": {"version": 1}},
        )
        stored = await db[self.thesis_collection].find_one({"_id": id_query, "user_id": user_id})
        if stored:
            await self._record_version(user_id, stored, change_description, triggered_by, previous_health)
        return self._serialize_doc(stored)

    async def activate_thesis(self, user_id: str, thesis_id: str, payload: ActivateThesisRequest) -> Optional[Dict[str, Any]]:
        result = await self.update_thesis(
            user_id,
            thesis_id,
            UpdateThesisRequest(
                status=ThesisStatus.ACTIVE,
                triggered_by="activation",
                change_description="激活 Thesis",
            ),
        )
        if result and payload.position_id:
            db = await self._get_db()
            try:
                position_oid = ObjectId(payload.position_id)
            except Exception:
                position_oid = None
            if position_oid is not None:
                await db.paper_positions.update_one(
                    {"_id": position_oid, "user_id": user_id},
                    {"$set": {"thesis_id": thesis_id, "updated_at": now_tz().isoformat()}},
                )
        return result

    async def close_thesis(self, user_id: str, thesis_id: str, payload: CloseThesisRequest) -> Optional[Dict[str, Any]]:
        result = await self.update_thesis(
            user_id,
            thesis_id,
            UpdateThesisRequest(
                status=ThesisStatus.CLOSED,
                triggered_by="close",
                change_description=payload.reason,
            ),
        )
        if result and payload.close_position:
            db = await self._get_db()
            await db.paper_positions.update_many(
                {"user_id": user_id, "thesis_id": thesis_id},
                {"$set": {"status": "closed", "close_reason": payload.reason, "updated_at": now_tz().isoformat()}},
            )
        return result

    async def get_versions(self, user_id: str, thesis_id: str) -> List[Dict[str, Any]]:
        db = await self._get_db()
        cursor = db[self.version_collection].find({"user_id": user_id, "thesis_id": thesis_id}).sort("version", -1)
        items = await cursor.to_list(length=None)
        return [self._serialize_doc(item) for item in items]

    async def get_overview(self, user_id: str) -> ThesisOverview:
        items = await self.list_theses(user_id)
        active = [item for item in items if item.get("status") == ThesisStatus.ACTIVE.value]
        watchlist = [item for item in items if item.get("status") in {ThesisStatus.WATCHLIST.value, ThesisStatus.DRAFT.value}]
        closed = [item for item in items if item.get("status") == ThesisStatus.CLOSED.value]
        broken = [item for item in items if float(item.get("health_score", 1.0) or 1.0) < 0.4]
        weakest = min(items, key=lambda item: float(item.get("health_score", 1.0) or 1.0), default=None)
        return ThesisOverview(
            active_count=len(active),
            watchlist_count=len(watchlist),
            closed_count=len(closed),
            broken_count=len(broken),
            weakest_symbol=(weakest or {}).get("symbol"),
            weakest_health=(weakest or {}).get("health_score"),
            items=items[:10],
        )

    async def validate_signal_bundle(
        self,
        user_id: str,
        symbol: str,
        signal_bundle: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        db = await self._get_db()
        thesis = await db[self.thesis_collection].find_one(
            {"user_id": user_id, "symbol": symbol, "status": ThesisStatus.ACTIVE.value},
            sort=[("updated_at", -1)],
        )
        if not thesis:
            return None
        previous_health = float(thesis.get("health_score", 1.0))
        assumptions = thesis.get("core_assumptions", []) or []
        signal_tags = set(signal_bundle.get("signal_tags", []))
        bearish_tags = set(signal_bundle.get("bearish_tags", []))
        for assumption in assumptions:
            tags = set(assumption.get("signal_tags", []))
            if tags & bearish_tags:
                assumption["status"] = AssumptionStatus.BROKEN.value
                assumption["health_score"] = 0.0
                assumption["weakening_evidence"] = "检测到与 Thesis 证伪标签重叠的负面信号"
            elif tags & signal_tags:
                assumption["status"] = AssumptionStatus.INTACT.value
                assumption["health_score"] = 1.0
                assumption["weakening_evidence"] = None
            else:
                assumption["status"] = AssumptionStatus.WEAKENING.value
                assumption["health_score"] = min(float(assumption.get("health_score", 1.0)), 0.6)
            assumption["last_checked"] = now_tz()
            assumption.setdefault("history", []).append(
                {
                    "checked_at": now_tz().isoformat(),
                    "signal_tags": sorted(signal_tags),
                    "bearish_tags": sorted(bearish_tags),
                    "status": assumption["status"],
                }
            )
        thesis["core_assumptions"] = assumptions
        thesis["health_score"] = self.compute_health_score(thesis)
        thesis["thesis_health"] = self.derive_health_label(thesis["health_score"])
        thesis["updated_at"] = now_tz()
        thesis["version"] = int(thesis.get("version", 1)) + 1
        thesis["latest_verdict"] = signal_bundle.get("debate_verdict")
        thesis["latest_exit_decision"] = signal_bundle.get("exit_decision")
        await db[self.thesis_collection].update_one(
            {"_id": thesis["_id"]},
            {
                "$set": {
                    "core_assumptions": thesis["core_assumptions"],
                    "health_score": thesis["health_score"],
                    "thesis_health": thesis["thesis_health"],
                    "updated_at": thesis["updated_at"],
                    "latest_verdict": thesis.get("latest_verdict"),
                    "latest_exit_decision": thesis.get("latest_exit_decision"),
                },
                "$inc": {"version": 1},
            },
        )
        stored = await db[self.thesis_collection].find_one({"_id": thesis["_id"]})
        if stored:
            await self._record_version(
                user_id=user_id,
                thesis_doc=stored,
                change_description="daily_signal_scan",
                triggered_by="monitor_agent",
                previous_health=previous_health,
            )
        return self._serialize_doc(stored)

    async def create_watchlist_thesis(
        self,
        user_id: str,
        symbol: str,
        symbol_name: Optional[str],
        signal_confidence: float,
        reason: str,
    ) -> Dict[str, Any]:
        payload = CreateThesisRequest(
            symbol=symbol,
            symbol_name=symbol_name,
            status=ThesisStatus.WATCHLIST,
            watch_reason=reason,
            signal_confidence=signal_confidence,
            create_watchlist_entry=True,
        )
        return await self.create_thesis(user_id, payload)

    async def build_edge_profile(self, user_id: str) -> Dict[str, Any]:
        await self.ensure_indexes()
        db = await self._get_db()
        trades = await db[self.trade_journal_collection].find({"user_id": user_id}).to_list(length=None)
        closed_positions = await db.paper_positions.find({"user_id": user_id, "status": "closed"}).to_list(length=None)
        total_closed = len(closed_positions)
        win_count = 0
        total_profit = 0.0
        total_loss = 0.0
        for pos in closed_positions:
            pnl = float(pos.get("realized_pnl", 0.0) or 0.0)
            if pnl >= 0:
                win_count += 1
                total_profit += pnl
            else:
                total_loss += abs(pnl)
        win_rate = round(win_count / total_closed, 4) if total_closed else 0.0
        profit_loss_ratio = round(total_profit / total_loss, 4) if total_loss else (1.0 if total_profit else 0.0)
        edge_score = round(win_rate * profit_loss_ratio, 4) if total_closed else 0.0
        signal_weight_config = {
            "fundamentals": 0.4,
            "news": 0.3,
            "sentiment": 0.2,
            "technical": 0.1,
        }
        profile = {
            "user_id": user_id,
            "generated_at": now_tz(),
            "data_period_start": min((item.get("timestamp") for item in trades if item.get("timestamp")), default=None),
            "data_period_end": max((item.get("timestamp") for item in trades if item.get("timestamp")), default=None),
            "total_closed_trades": total_closed,
            "decision_type_analysis": [
                {
                    "type": "thesis_linked_positions",
                    "trade_count": total_closed,
                    "win_rate": win_rate,
                    "profit_loss_ratio": profit_loss_ratio,
                    "edge_score": edge_score,
                }
            ],
            "signal_attribution_scores": {
                "fundamentals": 1.0 if total_closed else 0.4,
                "news": 0.8 if total_closed else 0.3,
                "sentiment": 0.6 if total_closed else 0.2,
                "technical": 0.4 if total_closed else 0.1,
            },
            "key_findings": [
                f"已关闭持仓 {total_closed} 笔",
                f"胜率 {win_rate:.2%}",
                f"盈亏比 {profit_loss_ratio:.2f}",
            ],
            "recommendations": [
                {"action": "优先补齐 Thesis 关联", "reason": "让后续 Edge Discovery 有稳定样本"},
            ],
            "signal_weight_config": signal_weight_config,
            "orchestrator_config": {"workflow_mode": "investmind_v3"},
        }
        await db[self.edge_collection].insert_one(profile)
        return self._serialize_doc(profile) or {}

    async def list_edge_profiles(self, user_id: str) -> List[Dict[str, Any]]:
        db = await self._get_db()
        items = await db[self.edge_collection].find({"user_id": user_id}).sort("generated_at", -1).to_list(length=None)
        return [self._serialize_doc(item) for item in items]

    async def generate_cognitive_snapshot(self, user_id: str) -> Dict[str, Any]:
        db = await self._get_db()
        theses = await self.list_theses(user_id)
        snapshot = {
            "user_id": user_id,
            "generated_at": now_tz(),
            "strengths": ["开始使用结构化 Thesis 管理投资决策"],
            "blind_spots": ["仍需积累更多已闭环交易样本以完善 Edge 画像"],
            "improvement_vs_last": [f"当前累计 Thesis 数量 {len(theses)}"],
            "maturity_dimensions": {
                "宏观政策框架": 3,
                "行业分析": 3,
                "个股研究": 2,
                "风险管理": 3,
                "情绪管理": 2,
                "卖出纪律": 2,
            },
        }
        await db[self.cognitive_collection].insert_one(snapshot)
        return self._serialize_doc(snapshot) or {}

    async def list_cognitive_snapshots(self, user_id: str) -> List[Dict[str, Any]]:
        db = await self._get_db()
        items = await db[self.cognitive_collection].find({"user_id": user_id}).sort("generated_at", -1).to_list(length=None)
        return [self._serialize_doc(item) for item in items]

    async def record_debate_record(
        self,
        user_id: str,
        *,
        symbol: str,
        thesis_id: Optional[str],
        debate_verdict: Dict[str, Any],
        bull_case: List[str],
        bear_case: List[str],
        signal_bundle: Dict[str, Any],
        exit_decision: Optional[Dict[str, Any]] = None,
        macro_assessment: Optional[Dict[str, Any]] = None,
        sector_rotation: Optional[Dict[str, Any]] = None,
        workflow_mode: str = "investmind_v3",
    ) -> Dict[str, Any]:
        db = await self._get_db()
        record = {
            "user_id": user_id,
            "symbol": symbol,
            "thesis_id": thesis_id,
            "workflow_mode": workflow_mode,
            "bull_case": bull_case,
            "bear_case": bear_case,
            "debate_verdict": debate_verdict,
            "signal_bundle": signal_bundle,
            "exit_decision": exit_decision or {},
            "macro_assessment": macro_assessment or {},
            "sector_rotation": sector_rotation or {},
            "created_at": now_tz(),
        }
        result = await db[self.debate_collection].insert_one(record)
        stored = await db[self.debate_collection].find_one({"_id": result.inserted_id})
        return self._serialize_doc(stored) or {"_id": str(result.inserted_id)}

    async def list_debate_records(
        self,
        user_id: str,
        *,
        thesis_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        db = await self._get_db()
        query: Dict[str, Any] = {"user_id": user_id}
        if thesis_id:
            query["thesis_id"] = thesis_id
        if symbol:
            query["symbol"] = symbol
        items = await db[self.debate_collection].find(query).sort("created_at", -1).to_list(length=limit)
        return [self._serialize_doc(item) for item in items]

    def preview_trade_import(self, content: bytes) -> TradeImportPreview:
        decoded = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(decoded))
        rows = list(reader)
        columns = reader.fieldnames or []
        lower_columns = {column.lower(): column for column in columns}
        return TradeImportPreview(
            columns=columns,
            rows=rows,
            sample_rows=rows[:5],
            detected_symbol_field=lower_columns.get("symbol") or lower_columns.get("code"),
            detected_side_field=lower_columns.get("side") or lower_columns.get("direction"),
            row_count=len(rows),
        )

    async def import_trade_journal(
        self,
        user_id: str,
        rows: List[Dict[str, Any]],
        *,
        source: str = "csv_import",
    ) -> Dict[str, Any]:
        db = await self._get_db()
        now = now_tz()
        docs = []
        for row in rows:
            doc = {
                "user_id": user_id,
                "symbol": row.get("symbol") or row.get("code") or row.get("stock_code"),
                "side": row.get("side") or row.get("direction"),
                "price": row.get("price"),
                "quantity": row.get("quantity"),
                "timestamp": row.get("timestamp") or row.get("date") or now.isoformat(),
                "source": source,
                "is_reconstructed": True,
                "raw": row,
                "created_at": now,
            }
            if doc["symbol"]:
                docs.append(doc)
        if docs:
            await db[self.trade_journal_collection].insert_many(docs)
            imported_symbols = sorted({doc["symbol"] for doc in docs if doc.get("symbol")})
            for symbol in imported_symbols:
                existing = await db[self.thesis_collection].find_one({"user_id": user_id, "symbol": symbol})
                if existing:
                    continue
                payload = CreateThesisRequest(
                    symbol=symbol,
                    status=ThesisStatus.DRAFT,
                    thesis_title=f"{symbol} 重建 Thesis",
                    thesis_summary=f"基于历史导入交易为 {symbol} 自动重建的 Thesis 草稿",
                    watch_reason="历史交易导入回溯",
                    metadata={"source": source, "imported_from_journal": True},
                    is_reconstructed=True,
                )
                await self.create_thesis(user_id, payload)
        return {"inserted_count": len(docs)}


thesis_service = ThesisService()
