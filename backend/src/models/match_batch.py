"""账期批次：一组账期处理的唯一载体，版本（version）承载每次重算结果。

一个批次（period + batch_key）只属于一个账期；重复推送 / 重试命中同一个批次，
不会新建批次、运行或单据。批次下最多一个 staging 版本（待切换）和一个 official
版本（正式版）；迟到发票到达后生成新版本，旧版本作为 superseded 留档。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class MatchBatch(Base):
    __tablename__ = "match_batches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    # 幂等键：同一批次的重复推送必须带同一个 key（缺省 = period:<账期>）
    batch_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    period: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    # 水位 = 来源单据指纹（供应商容差 / 订单 / 收货 / 发票），"同一水位"核对以它为准
    watermark: Mapped[str] = mapped_column(String(64), default="")
    source_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    official_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    staging_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(160), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    @property
    def watermark_label(self) -> str:
        return watermark_label(self.period, self.watermark)


class MatchBatchVersion(Base):
    __tablename__ = "match_batch_versions"
    __table_args__ = (UniqueConstraint("batch_id", "version_no", name="uq_batch_versions_no"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("match_batches.id", ondelete="CASCADE"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("match_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # staging -> official -> superseded / rolled_back；切换失败 -> failed
    status: Mapped[str] = mapped_column(String(20), default="staging", index=True)
    watermark: Mapped[str] = mapped_column(String(64), default="")
    watermark_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    change_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    verify_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(160), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @property
    def watermark_label(self) -> str:
        return watermark_label("", self.watermark)


def watermark_label(period: str, fingerprint: str) -> str:
    """人读水位号：WM-202610-1a2b3c4d5e6f。"""
    if not fingerprint:
        return "—"
    prefix = f"WM-{period.replace('-', '')}" if period else "WM"
    return f"{prefix}-{fingerprint[:12]}"
