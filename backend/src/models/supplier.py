"""供应商档案：容差按供应商配置（金额元 -> 分存储；数量容差为百分比）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    # 归一后的供应商名（算法 A：去后缀 + 别名表），用于 match_key
    name_norm: Mapped[str] = mapped_column(String(120), index=True, default="")
    alias: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 金额容差：单位「分」，默认 2 分 = 0.02 元
    tolerance_amount_cents: Mapped[int] = mapped_column(Integer, default=2)
    # 数量容差：百分比，默认 1.00 = ±1%
    tolerance_qty_pct: Mapped[float] = mapped_column(Numeric(6, 2), default=1.00)
    contact: Mapped[str | None] = mapped_column(String(80), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
