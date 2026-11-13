from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from src.constants.enums import TAX_RATE_BPS


class OrderIn(BaseModel):
    po_no: str = Field(min_length=6, max_length=40, pattern=r"^PO-[0-9]{4}-[0-9]{4}$")
    supplier_id: int = Field(ge=1)
    material_code: str = Field(min_length=3, max_length=40)
    material_name: str = Field(default="", max_length=120)
    qty: int = Field(ge=1, le=1000000)
    unit_price_cents: int = Field(ge=1, le=100000000)
    tax_rate_bp: int = 1300
    ordered_on: date

    def normalized_bp(self) -> int:
        if self.tax_rate_bp not in TAX_RATE_BPS:
            raise ValueError("税率必须是 13/9/6/3/1% 之一")
        return self.tax_rate_bp


class ReceiptIn(BaseModel):
    grn_no: str = Field(min_length=6, max_length=40, pattern=r"^GRN-[0-9]{4}-[0-9]{4}$")
    po_no: str = Field(min_length=6, max_length=40)
    qty: int = Field(ge=0, le=1000000)
    received_on: date
    batch: str = Field(default="B01", max_length=40)


class InvoiceIn(BaseModel):
    """发票录入：原始字段先过算法 A 归一，失败进 rejected 而不是 500。"""

    invoice_no: str = Field(min_length=6, max_length=40)
    import_batch: str = Field(default="SRM-2026-10", max_length=60)
    supplier_name: str = Field(min_length=2, max_length=160)
    po_no: str | None = Field(default=None, max_length=40)
    material_code: str | None = Field(default=None, max_length=40)
    amount: str | float = Field(description="含税金额，元；支持 '1,234.56' 文本")
    tax_rate: str | float = Field(default="13%", description="13% / 0.13 / 13 均可")
    issued_on: date
    is_red: bool = False
