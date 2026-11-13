"""差异工单：由匹配运行算出，人工处理（退回重开 / 挂账 / 接受）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class MatchCase(Base):
    __tablename__ = "match_cases"
    __table_args__ = (UniqueConstraint("run_id", "case_key", name="uq_cases_run_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("match_runs.id", ondelete="CASCADE"), index=True)
    case_key: Mapped[str] = mapped_column(String(160))  # invoice_no#import_batch
    invoice_no: Mapped[str] = mapped_column(String(40), index=True)
    import_batch: Mapped[str] = mapped_column(String(60), default="")
    po_no: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    supplier_name: Mapped[str] = mapped_column(String(160), default="")
    material_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    match_status: Mapped[str] = mapped_column(String(20), index=True)
    diff_type: Mapped[str] = mapped_column(String(16), default="none", index=True)
    # 差异额 = 发票金额 − 应付金额（分，带符号）
    diff_amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    invoice_amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    payable_cents: Mapped[int] = mapped_column(Integer, default=0)
    unit_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    qty_ordered: Mapped[int] = mapped_column(Integer, default=0)
    qty_received: Mapped[int] = mapped_column(Integer, default=0)
    suggestion: Mapped[str] = mapped_column(String(24), default="none")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    reviewer: Mapped[str | None] = mapped_column(String(160), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
