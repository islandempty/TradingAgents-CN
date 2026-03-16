#!/usr/bin/env python3
"""
初始化 InvestMind v3 集合、索引和历史持仓回填。

用法:
    python3 scripts/migrations/init_investmind_v3.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.core.config import settings
from app.models.thesis import CreateThesisRequest, ThesisStatus
from app.services.thesis_service import thesis_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("scripts.init_investmind_v3")


async def main() -> int:
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB]
    thesis_service.db = db

    logger.info("开始初始化 InvestMind v3 索引")
    await thesis_service.ensure_indexes()

    logger.info("开始回填 active paper positions -> reconstructed theses")
    cursor = db["paper_positions"].find(
        {
            "$and": [
                {
                    "$or": [
                        {"status": {"$exists": False}},
                        {"status": {"$ne": "closed"}},
                        {"quantity": {"$gt": 0}},
                    ]
                },
                {
                    "$or": [
                        {"thesis_id": {"$exists": False}},
                        {"thesis_id": None},
                        {"thesis_id": ""},
                    ]
                },
            ],
        }
    )

    count = 0
    async for position in cursor:
        user_id = position.get("user_id")
        symbol = position.get("code")
        if not user_id or not symbol:
            continue

        existing = await db["theses"].find_one({"user_id": user_id, "symbol": symbol})
        if existing:
            await db["paper_positions"].update_one(
                {"_id": position["_id"]},
                {"$set": {"thesis_id": str(existing["_id"])}},
            )
            continue

        thesis = await thesis_service.create_thesis(
            user_id,
            CreateThesisRequest(
                symbol=symbol,
                status=ThesisStatus.DRAFT,
                thesis_title=f"{symbol} 重建 Thesis",
                thesis_summary=f"基于历史持仓为 {symbol} 回填的重建 Thesis 草稿",
                entry_price=position.get("avg_cost"),
                target_price=position.get("target_price"),
                stop_loss=position.get("stop_loss"),
                min_hold_days=position.get("min_hold_days"),
                watch_reason="active_position_backfill",
                is_reconstructed=True,
                metadata={"source": "migration", "position_id": str(position["_id"])},
            ),
        )
        await db["paper_positions"].update_one(
            {"_id": position["_id"]},
            {
                "$set": {
                    "thesis_id": thesis.get("_id"),
                    "current_health": thesis.get("thesis_health"),
                }
            },
        )
        count += 1

    logger.info(f"回填完成，新建重建 Thesis {count} 条")
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
