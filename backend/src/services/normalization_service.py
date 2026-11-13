"""算法 A｜字段归一与匹配键（纯函数，无 DB 依赖，可单测）。

口径：
- 供应商名：全角转半角 → 去内部空白 → 统一括号 → 查别名表 → 循环去企业后缀（有限公司 / 股份有限公司 / 集团 / 厂 …）；
- 金额：一律用「分」（int）参与比较，`parse_amount_cents` 接受 `1,234.56`、`￥1234.56`、`1234.56元`；
- 含税/不含税：`net_from_gross_cents` / `gross_from_net_cents`，四舍五入到分；
- 税率：标准化为 basis point（1300 = 13%），只接受 13/9/6/3/1%；
- 匹配键：`match_key = (supplier_norm, po_no, material_code)`；
- 异常行：抛出 `NormalizationError`，由上层收进 `rejected` 列表，不进匹配池。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from src.constants.enums import TAX_RATE_BPS

# 企业名后缀，按长度倒序匹配，避免「有限公司」先被「公司」吃掉
SUPPLIER_SUFFIXES: tuple[str, ...] = (
    "股份有限公司",
    "有限责任公司",
    "有限公司",
    "分公司",
    "集团",
    "公司",
    "制造厂",
    "厂",
    "商行",
    "经营部",
    "部",
    "(中国)",
)

_SPACES = re.compile(r"\s+")
_AMOUNT_NOISE = re.compile(r"[,\s￥¥元]")
_QTY_NOISE = re.compile(r"[,\s]")


class NormalizationError(ValueError):
    """归一失败：字段 + 人话原因，交给 rejected 清单。"""

    def __init__(self, field: str, reason: str):
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


def to_halfwidth(text: str) -> str:
    out: list[str] = []
    for ch in str(text):
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def basic_name(text: str) -> str:
    value = to_halfwidth(text).strip().lower()
    value = value.replace("（", "(").replace("）", ")")
    return _SPACES.sub("", value)


def strip_supplier_suffix(normalized: str) -> str:
    value = normalized
    changed = True
    while changed:
        changed = False
        for suffix in SUPPLIER_SUFFIXES:
            if value.endswith(suffix) and len(value) > len(suffix):
                value = value[: -len(suffix)]
                changed = True
                break
    return value


def normalize_supplier_name(raw: str, aliases: dict[str, str] | None = None) -> str:
    """供应商名归一：别名先查，再逐层去后缀。空名抛 NormalizationError。"""
    if raw is None or not str(raw).strip():
        raise NormalizationError("supplier_name", "供应商名称为空")
    base = basic_name(raw)
    if aliases:
        for alias, canonical in aliases.items():
            if basic_name(alias) == base:
                return strip_supplier_suffix(basic_name(canonical)) or base
    result = strip_supplier_suffix(base)
    if not result:
        raise NormalizationError("supplier_name", "供应商名归一后为空")
    return result


def parse_amount_cents(raw: object, field: str = "amount") -> int:
    """金额文本 -> 分。支持千分位、货币符号、「元」后缀与负号。"""
    text = _AMOUNT_NOISE.sub("", str(raw if raw is not None else "").strip())
    if not text:
        raise NormalizationError(field, "金额为空")
    try:
        dec = Decimal(text)
    except InvalidOperation as exc:  # noqa: F841
        raise NormalizationError(field, f"金额不是数字：{raw}") from None
    cents = (dec * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def yuan_from_cents(cents: int | None) -> float:
    return round((int(cents or 0)) / 100.0, 2)


def parse_tax_rate_bp(raw: object) -> int:
    """13% / 0.13 / 13 / 13.0 一律归一成 1300bp；不在标准税率集合内则拒绝。"""
    text = str(raw if raw is not None else "").strip().replace("%", "").replace(" ", "")
    if not text:
        raise NormalizationError("tax_rate", "税率为空")
    try:
        dec = Decimal(text)
    except InvalidOperation:
        raise NormalizationError("tax_rate", f"税率不是数字：{raw}") from None
    bp = int((dec * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if dec >= 1 else int(
        (dec * 10000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    if bp not in TAX_RATE_BPS:
        raise NormalizationError("tax_rate", f"税率 {raw} 不在 13/9/6/3/1% 标准集合内")
    return bp


def net_from_gross_cents(gross_cents: int, tax_rate_bp: int) -> int:
    rate = Decimal(int(tax_rate_bp)) / Decimal(10000)
    net = Decimal(int(gross_cents)) / (Decimal(1) + rate)
    return int(net.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def gross_from_net_cents(net_cents: int, tax_rate_bp: int) -> int:
    rate = Decimal(int(tax_rate_bp)) / Decimal(10000)
    gross = Decimal(int(net_cents)) * (Decimal(1) + rate)
    return int(gross.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def build_match_key(supplier_norm: str, po_no: str | None, material_code: str | None) -> str:
    return f"{supplier_norm}|{(po_no or '').strip().upper()}|{(material_code or '').strip().upper()}"


@dataclass(frozen=True)
class NormalizedInvoice:
    invoice_no: str
    import_batch: str
    supplier_id: int | None
    supplier_name_raw: str
    supplier_norm: str
    match_key: str
    po_no: str | None
    material_code: str | None
    amount_cents: int
    tax_cents: int
    tax_rate_bp: int
    issued_on: date
    is_red: bool


def normalize_invoice_row(
    raw: dict,
    *,
    aliases: dict[str, str] | None = None,
    supplier_index: dict[str, int] | None = None,
    default_batch: str = "SRM-2026-10",
) -> NormalizedInvoice:
    """一行原始发票 -> NormInvoice；任何一步失败抛 NormalizationError。"""
    invoice_no = str(raw.get("invoice_no") or "").strip().upper()
    if not invoice_no:
        raise NormalizationError("invoice_no", "发票号为空")
    if len(invoice_no) < 6:
        raise NormalizationError("invoice_no", f"发票号过短：{invoice_no}")

    supplier_raw = str(raw.get("supplier_name") or raw.get("supplier") or "").strip()
    supplier_norm = normalize_supplier_name(supplier_raw, aliases)
    supplier_id = (supplier_index or {}).get(supplier_norm)

    amount_cents = parse_amount_cents(raw.get("amount"), "amount")
    if amount_cents == 0:
        raise NormalizationError("amount", "金额不能为 0")
    tax_rate_bp = parse_tax_rate_bp(raw.get("tax_rate"))
    is_red = bool(raw.get("is_red")) or str(raw.get("is_red", "")).lower() in {"1", "true", "是", "红字"}
    if is_red:
        amount_cents = -abs(amount_cents)

    tax_cents = raw.get("tax_amount")
    tax_cents = parse_amount_cents(tax_cents, "tax_amount") if tax_cents not in (None, "") else (
        amount_cents - net_from_gross_cents(amount_cents, tax_rate_bp)
    )

    issued_on = raw.get("issued_on")
    if isinstance(issued_on, date):
        parsed_date = issued_on
    else:
        text = str(issued_on or "").strip().replace("/", "-")[:10]
        try:
            parsed_date = date.fromisoformat(text)
        except ValueError:
            raise NormalizationError("issued_on", f"开票日期非法：{issued_on}") from None

    po_no = str(raw.get("po_no") or "").strip().upper() or None
    material_code = str(raw.get("material_code") or "").strip().upper() or None
    return NormalizedInvoice(
        invoice_no=invoice_no,
        import_batch=str(raw.get("import_batch") or default_batch),
        supplier_id=supplier_id,
        supplier_name_raw=supplier_raw,
        supplier_norm=supplier_norm,
        match_key=build_match_key(supplier_norm, po_no, material_code),
        po_no=po_no,
        material_code=material_code,
        amount_cents=amount_cents,
        tax_cents=int(tax_cents),
        tax_rate_bp=tax_rate_bp,
        issued_on=parsed_date,
        is_red=is_red,
    )


def normalize_invoice_rows(
    rows: list[dict],
    *,
    aliases: dict[str, str] | None = None,
    supplier_index: dict[str, int] | None = None,
    default_batch: str = "SRM-2026-10",
) -> dict:
    """批量归一：accepted 进匹配池，rejected 只留痕（不阻塞整批导入）。"""
    accepted: list[NormalizedInvoice] = []
    rejected: list[dict] = []
    for index, row in enumerate(rows):
        try:
            accepted.append(
                normalize_invoice_row(
                    row, aliases=aliases, supplier_index=supplier_index, default_batch=default_batch
                )
            )
        except NormalizationError as exc:
            rejected.append(
                {
                    "row": index + 1,
                    "invoice_no": str(row.get("invoice_no") or ""),
                    "field": exc.field,
                    "reason": exc.reason,
                }
            )
    return {"accepted": accepted, "rejected": rejected}
