"""匹配运行：一次「本期全部发票 × 订单 × 收货」的判定快照。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class MatchRun(Base):
    __tablename__ = "match_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    period: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM 账期
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    operator_email: Mapped[str] = mapped_column(String(160), default="system")
    # 归属批次 / 版本；历史遗留运行两列为空
    batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    version_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 本次运行取数的来源水位（sha256 指纹前 64 位）
    watermark: Mapped[str] = mapped_column(String(64), default="")
    invoice_raw_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    diff_count: Mapped[int] = mapped_column(Integer, default=0)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    log_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    seed_key: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
