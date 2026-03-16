"""
InvestMind v3 历史交易导入 API。
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.thesis_service import thesis_service

router = APIRouter(prefix="/imports/trades", tags=["trade-imports"])


class TradeImportCommitRequest(BaseModel):
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    source: str = "csv_import"


@router.post("/preview", response_model=dict)
async def preview_trade_import(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    del current_user
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")
    preview = thesis_service.preview_trade_import(content)
    return ok(preview.model_dump())


@router.post("/commit", response_model=dict)
async def commit_trade_import(
    request: TradeImportCommitRequest,
    current_user: dict = Depends(get_current_user),
):
    result = await thesis_service.import_trade_journal(
        current_user["id"],
        request.rows,
        source=request.source,
    )
    return ok(result, "导入成功")
