"""发票 INV：来自 SRM / 发票平台两个采集批次，因此 (invoice_no, import_batch) 才是自然键。

重复发票正是「同一发票号被两个批次各导入一次」，算法 B 按发票号聚合判定 duplicate。
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("invoice_no", "import_batch", name="uq_invoices_no_batch"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_no: Mapped[str] = mapped_column(String(40), index=True)
    import_batch: Mapped[str] = mapped_column(String(60), default="SRM-2026-10")
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    supplier_name_raw: Mapped[str] = mapped_column(String(160), default="")
    po_no: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    material_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    tax_cents: Mapped[int] = mapped_column(Integer, default=0)
    tax_rate_bp: Mapped[int] = mapped_column(Integer, default=1300)
    issued_on: Mapped[date] = mapped_column(Date)
    is_red: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="valid", index=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
