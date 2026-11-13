"""收货单 GRN：按 po_no 关联订单，允许分批收货（同一 PO 多张 GRN）。"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    grn_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    po_no: Mapped[str] = mapped_column(String(40), index=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    received_on: Mapped[date] = mapped_column(Date)
    batch: Mapped[str] = mapped_column(String(40), default="B01")
    warehouse: Mapped[str] = mapped_column(String(80), default="联纬 · 华东中心仓")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
