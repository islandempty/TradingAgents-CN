"""
Edge Discovery API。
"""

from fastapi import APIRouter, Depends

from app.core.response import ok
from app.models.notification import NotificationCreate
from app.routers.auth_db import get_current_user
from app.services.notifications_service import get_notifications_service
from app.services.thesis_service import thesis_service

router = APIRouter(prefix="/edge-profiles", tags=["edge-profiles"])


@router.get("/", response_model=dict)
async def list_edge_profiles(current_user: dict = Depends(get_current_user)):
    items = await thesis_service.list_edge_profiles(current_user["id"])
    return ok(items)


@router.post("/generate", response_model=dict)
async def generate_edge_profile(current_user: dict = Depends(get_current_user)):
    profile = await thesis_service.build_edge_profile(current_user["id"])
    await get_notifications_service().create_and_publish(
        NotificationCreate(
            user_id=current_user["id"],
            type="edge_report",
            title="Edge Discovery 已更新",
            content="新的交易边际画像已生成",
            link="/edge-discovery",
            severity="success",
            metadata={"generated_at": profile.get("generated_at")},
        )
    )
    return ok(profile, "生成成功")
