"""
Cognitive Mirror API。
"""

from fastapi import APIRouter, Depends

from app.core.response import ok
from app.models.notification import NotificationCreate
from app.routers.auth_db import get_current_user
from app.services.notifications_service import get_notifications_service
from app.services.thesis_service import thesis_service

router = APIRouter(prefix="/cognitive-snapshots", tags=["cognitive-snapshots"])


@router.get("/", response_model=dict)
async def list_cognitive_snapshots(current_user: dict = Depends(get_current_user)):
    items = await thesis_service.list_cognitive_snapshots(current_user["id"])
    return ok(items)


@router.post("/generate", response_model=dict)
async def generate_cognitive_snapshot(current_user: dict = Depends(get_current_user)):
    snapshot = await thesis_service.generate_cognitive_snapshot(current_user["id"])
    await get_notifications_service().create_and_publish(
        NotificationCreate(
            user_id=current_user["id"],
            type="cognitive_snapshot",
            title="Cognitive Mirror 已更新",
            content="新的认知快照已经生成",
            link="/cognitive-mirror",
            severity="info",
            metadata={"generated_at": snapshot.get("generated_at")},
        )
    )
    return ok(snapshot, "生成成功")
