from __future__ import annotations

from pydantic import BaseModel, Field


class SupplierIn(BaseModel):
    code: str = Field(min_length=3, max_length=40, pattern=r"^SUP-[0-9]{3,6}$")
    name: str = Field(min_length=2, max_length=120)
    alias: str | None = Field(default=None, max_length=200)
    contact: str | None = Field(default=None, max_length=80)
    tolerance_amount_cents: int = Field(default=2, ge=0, le=100000)
    tolerance_qty_pct: float = Field(default=1.0, ge=0, le=100)
    note: str | None = Field(default=None, max_length=1000)


class SupplierPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    alias: str | None = Field(default=None, max_length=200)
    contact: str | None = Field(default=None, max_length=80)
    tolerance_amount_cents: int | None = Field(default=None, ge=0, le=100000)
    tolerance_qty_pct: float | None = Field(default=None, ge=0, le=100)
    note: str | None = Field(default=None, max_length=1000)
    enabled: bool | None = None
