"""采购订单 PO：三单匹配的数量与单价来源。金额一律「分」存储。"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    po_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True)
    material_code: Mapped[str] = mapped_column(String(40), index=True)
    material_name: Mapped[str] = mapped_column(String(120), default="")
    qty: Mapped[int] = mapped_column(Integer, default=0)
    unit_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    tax_rate_bp: Mapped[int] = mapped_column(Integer, default=1300)
    ordered_on: Mapped[date] = mapped_column(Date)
    buyer: Mapped[str] = mapped_column(String(80), default="联纬汽车零部件 · 采购部")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
