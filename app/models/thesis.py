"""
InvestMind v3 Thesis 相关模型。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models.user import PyObjectId
from app.utils.timezone import now_tz


class ThesisStatus(str, Enum):
    WATCHLIST = "watchlist"
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class AssumptionStatus(str, Enum):
    INTACT = "完好"
    WEAKENING = "弱化"
    BROKEN = "破裂"


class WatchlistStatus(str, Enum):
    WATCH = "watch"
    BUILD = "build"
    ACTIVE = "active"


class ThesisAssumption(BaseModel):
    id: str
    statement: str
    evidence_at_creation: str = ""
    signal_tags: List[str] = Field(default_factory=list)
    weight: float = 1.0
    status: AssumptionStatus = AssumptionStatus.INTACT
    health_score: float = 1.0
    invalidation_threshold: float = 0.3
    last_checked: Optional[datetime] = None
    weakening_evidence: Optional[str] = None
    history: List[Dict[str, Any]] = Field(default_factory=list)

    @field_serializer("last_checked")
    def serialize_last_checked(self, value: Optional[datetime], _info) -> Optional[str]:
        return value.isoformat() if value else None


class ThesisBase(BaseModel):
    symbol: str
    symbol_name: Optional[str] = None
    market: str = "A股"
    status: ThesisStatus = ThesisStatus.DRAFT
    thesis_title: Optional[str] = None
    thesis_summary: Optional[str] = None
    core_assumptions: List[ThesisAssumption] = Field(default_factory=list)
    invalidation_signals: List[str] = Field(default_factory=list)
    entry_price: Optional[float] = None
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    current_position_pct: Optional[float] = None
    expected_hold_period: Optional[str] = None
    min_hold_days: Optional[int] = None
    emotion_at_entry: Optional[str] = None
    primary_signal_driver: Optional[str] = None
    thesis_health: str = "完好"
    health_score: float = 1.0
    version: int = 1
    is_reconstructed: bool = False
    reconstruction_confidence: Optional[float] = None
    watch_reason: Optional[str] = None
    signal_confidence: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ThesisDocument(ThesisBase):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    user_id: str
    created_at: datetime = Field(default_factory=now_tz)
    updated_at: datetime = Field(default_factory=now_tz)
    activated_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    latest_verdict: Optional[Dict[str, Any]] = None
    latest_exit_decision: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    @field_serializer("created_at", "updated_at", "activated_at", "closed_at")
    def serialize_datetimes(self, value: Optional[datetime], _info) -> Optional[str]:
        return value.isoformat() if value else None


class ThesisVersionDocument(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=PyObjectId, alias="_id")
    thesis_id: str
    user_id: str
    version: int
    snapshot: Dict[str, Any]
    change_description: str
    health_delta: Optional[float] = None
    triggered_by: str = "user"
    created_at: datetime = Field(default_factory=now_tz)

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime, _info) -> str:
        return value.isoformat()


class CreateThesisRequest(ThesisBase):
    linked_position_id: Optional[str] = None
    create_watchlist_entry: bool = False


class UpdateThesisRequest(BaseModel):
    thesis_title: Optional[str] = None
    thesis_summary: Optional[str] = None
    status: Optional[ThesisStatus] = None
    core_assumptions: Optional[List[ThesisAssumption]] = None
    invalidation_signals: Optional[List[str]] = None
    entry_price: Optional[float] = None
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    current_position_pct: Optional[float] = None
    expected_hold_period: Optional[str] = None
    min_hold_days: Optional[int] = None
    emotion_at_entry: Optional[str] = None
    primary_signal_driver: Optional[str] = None
    thesis_health: Optional[str] = None
    health_score: Optional[float] = None
    watch_reason: Optional[str] = None
    signal_confidence: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    latest_verdict: Optional[Dict[str, Any]] = None
    latest_exit_decision: Optional[Dict[str, Any]] = None
    triggered_by: str = "user"
    change_description: Optional[str] = None


class ActivateThesisRequest(BaseModel):
    position_id: Optional[str] = None


class CloseThesisRequest(BaseModel):
    reason: str
    close_position: bool = False


class ThesisOverview(BaseModel):
    active_count: int = 0
    watchlist_count: int = 0
    closed_count: int = 0
    broken_count: int = 0
    weakest_symbol: Optional[str] = None
    weakest_health: Optional[float] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)


class TradeImportPreview(BaseModel):
    columns: List[str]
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    sample_rows: List[Dict[str, Any]]
    detected_symbol_field: Optional[str] = None
    detected_side_field: Optional[str] = None
    row_count: int = 0
