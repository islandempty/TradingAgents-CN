"""
InvestMind v3 Thesis API。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.response import ok
from app.models.notification import NotificationCreate
from app.models.thesis import (
    ActivateThesisRequest,
    CloseThesisRequest,
    CreateThesisRequest,
    UpdateThesisRequest,
)
from app.routers.auth_db import get_current_user
from app.services.notifications_service import get_notifications_service
from app.services.thesis_service import thesis_service

router = APIRouter(prefix="/theses", tags=["theses"])


@router.get("/", response_model=dict)
async def list_theses(
    status: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    items = await thesis_service.list_theses(current_user["id"], status=status, symbol=symbol)
    return ok(items)


@router.get("/overview", response_model=dict)
async def get_thesis_overview(current_user: dict = Depends(get_current_user)):
    overview = await thesis_service.get_overview(current_user["id"])
    return ok(overview.model_dump())


@router.get("/active/{symbol}", response_model=dict)
async def get_active_thesis(symbol: str, current_user: dict = Depends(get_current_user)):
    thesis = await thesis_service.get_active_thesis_for_symbol(current_user["id"], symbol)
    if not thesis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到激活中的 Thesis")
    return ok(thesis)


@router.post("/", response_model=dict)
async def create_thesis(request: CreateThesisRequest, current_user: dict = Depends(get_current_user)):
    thesis = await thesis_service.create_thesis(current_user["id"], request)
    return ok(thesis, "创建成功")


@router.post("/watchlist", response_model=dict)
async def create_watchlist_thesis(
    request: CreateThesisRequest,
    current_user: dict = Depends(get_current_user),
):
    thesis = await thesis_service.create_watchlist_thesis(
        current_user["id"],
        request.symbol,
        request.symbol_name,
        request.signal_confidence or 0.0,
        request.watch_reason or "手动加入观察池",
    )
    return ok(thesis, "观察池 Thesis 已创建")


@router.get("/{thesis_id}", response_model=dict)
async def get_thesis(thesis_id: str, current_user: dict = Depends(get_current_user)):
    thesis = await thesis_service.get_thesis(current_user["id"], thesis_id)
    if not thesis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thesis 不存在")
    return ok(thesis)


@router.put("/{thesis_id}", response_model=dict)
async def update_thesis(
    thesis_id: str,
    request: UpdateThesisRequest,
    current_user: dict = Depends(get_current_user),
):
    thesis = await thesis_service.update_thesis(current_user["id"], thesis_id, request)
    if not thesis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thesis 不存在")

    if float(thesis.get("health_score", 1.0) or 1.0) < 0.4:
        await get_notifications_service().create_and_publish(
            NotificationCreate(
                user_id=current_user["id"],
                type="thesis_alert",
                title=f"{thesis.get('symbol')} Thesis 健康度告警",
                content=f"当前健康度已降至 {thesis.get('health_score')}",
                link=f"/thesis?thesisId={thesis_id}",
                severity="warning",
                metadata={"thesis_id": thesis_id},
            )
        )
    return ok(thesis, "更新成功")


@router.post("/{thesis_id}/activate", response_model=dict)
async def activate_thesis(
    thesis_id: str,
    request: ActivateThesisRequest,
    current_user: dict = Depends(get_current_user),
):
    thesis = await thesis_service.activate_thesis(current_user["id"], thesis_id, request)
    if not thesis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thesis 不存在")
    return ok(thesis, "激活成功")


@router.post("/{thesis_id}/close", response_model=dict)
async def close_thesis(
    thesis_id: str,
    request: CloseThesisRequest,
    current_user: dict = Depends(get_current_user),
):
    thesis = await thesis_service.close_thesis(current_user["id"], thesis_id, request)
    if not thesis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thesis 不存在")

    await get_notifications_service().create_and_publish(
        NotificationCreate(
            user_id=current_user["id"],
            type="thesis_alert",
            title=f"{thesis.get('symbol')} Thesis 已关闭",
            content=request.reason,
            link=f"/thesis?thesisId={thesis_id}",
            severity="info",
            metadata={"thesis_id": thesis_id, "reason": request.reason},
        )
    )
    return ok(thesis, "关闭成功")


@router.get("/{thesis_id}/versions", response_model=dict)
async def get_thesis_versions(thesis_id: str, current_user: dict = Depends(get_current_user)):
    items = await thesis_service.get_versions(current_user["id"], thesis_id)
    return ok(items)


@router.get("/{thesis_id}/debates", response_model=dict)
async def get_thesis_debates(
    thesis_id: str,
    limit: int = Query(10, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    items = await thesis_service.list_debate_records(
        current_user["id"],
        thesis_id=thesis_id,
        limit=limit,
    )
    return ok(items)
