"""算法 B｜三单匹配（纯函数，无 DB 依赖，可单测）。

口径（与 README 一致）：
- 应付金额 = 已收货数量 × 订单单价 × (1 + 订单税率)，金额单位「分」；
- 数量容差：|收货量 − 订单量| ≤ 订单量 × tolerance_qty_pct% 视为一致（默认 ±1%）；
- 金额容差：|发票金额 − 应付金额| ≤ tolerance_amount_cents（默认 2 分 = 0.02 元）；
- 税率必须完全一致（basis point 相等）；
- 判定顺序：duplicate → missing_po → tax_diff → qty_diff → price_diff → matched；
- 差异额 = 发票金额 − 应付金额（分，带符号）；
- 建议：tax_diff → 改税率；qty_diff 少收 → 补收，多收 → 红冲；
  price_diff → 退票重开；duplicate → 退票重开；missing_po → 补挂订单。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from src.constants.enums import (
    DIFF_STATUSES,
    MATCH_DIFF_TYPE,
    MATCH_STATUS_ORDER,
    CaseStatus,
    DiffType,
    MatchStatus,
    Suggestion,
)
from src.services.normalization_service import gross_from_net_cents

DEFAULT_TOLERANCE_AMOUNT_CENTS = 2
DEFAULT_TOLERANCE_QTY_PCT = Decimal("1.00")


@dataclass(frozen=True)
class OrderView:
    po_no: str
    supplier_id: int
    material_code: str
    qty: int
    unit_price_cents: int
    tax_rate_bp: int


@dataclass(frozen=True)
class ReceiptView:
    po_no: str
    qty: int


@dataclass(frozen=True)
class InvoiceView:
    case_key: str
    invoice_no: str
    import_batch: str
    supplier_id: int | None
    supplier_name: str
    po_no: str | None
    material_code: str | None
    amount_cents: int
    tax_rate_bp: int
    is_red: bool = False


@dataclass(frozen=True)
class Tolerance:
    amount_cents: int = DEFAULT_TOLERANCE_AMOUNT_CENTS
    qty_pct: Decimal = DEFAULT_TOLERANCE_QTY_PCT


@dataclass
class MatchOutcome:
    matched: int = 0
    diffs: int = 0
    total_diff_cents: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)
    by_suggestion: dict[str, int] = field(default_factory=dict)
    cases: list[dict] = field(default_factory=list)

    def metrics(self) -> dict:
        return {
            "invoices": len(self.cases),
            "matched": self.matched,
            "diffs": self.diffs,
            "total_diff_cents": self.total_diff_cents,
            "by_status": {key: self.by_status.get(key, 0) for key in MATCH_STATUS_ORDER},
            "by_type": {key: self.by_type.get(key, 0) for key in MATCH_DIFF_TYPE.values()},
            "by_suggestion": dict(sorted(self.by_suggestion.items())),
        }


def qty_out_of_tolerance(received: int, ordered: int, qty_pct: Decimal | float | int) -> bool:
    """数量容差判定：绝对偏差超过「订单量 × pct%」即算量差。"""
    if ordered <= 0:
        return received > 0
    allowed = Decimal(int(ordered)) * Decimal(str(qty_pct)) / Decimal(100)
    return abs(Decimal(int(received)) - Decimal(int(ordered))) > allowed


def payable_cents(received_qty: int, unit_price_cents: int, tax_rate_bp: int) -> int:
    return gross_from_net_cents(int(received_qty) * int(unit_price_cents), int(tax_rate_bp))


def suggest_for(status: str, *, diff_cents: int, received: int, ordered: int) -> str:
    if status == MatchStatus.MATCHED.value:
        return Suggestion.NONE.value
    if status == MatchStatus.TAX_DIFF.value:
        return Suggestion.FIX_TAX.value
    if status == MatchStatus.QTY_DIFF.value:
        if received < ordered and diff_cents > 0:
            return Suggestion.RECEIVE_MORE.value
        return Suggestion.RED_REVERSE.value
    if status == MatchStatus.PRICE_DIFF.value:
        return Suggestion.RETURN_REISSUE.value if diff_cents > 0 else Suggestion.RED_REVERSE.value
    if status == MatchStatus.DUPLICATE.value:
        return Suggestion.RETURN_REISSUE.value
    return Suggestion.SUPPLEMENT_PO.value


def classify(
    invoice: InvoiceView,
    *,
    order: OrderView | None,
    received_qty: int,
    tolerance: Tolerance,
) -> dict:
    """单张发票判定：返回 match_status / diff_type / diff / payable / suggestion。"""
    if order is None:
        return {
            "match_status": MatchStatus.MISSING_PO.value,
            "diff_type": DiffType.MISSING.value,
            "payable_cents": 0,
            "diff_cents": invoice.amount_cents,
            "suggestion": Suggestion.SUPPLEMENT_PO.value,
            "unit_price_cents": 0,
            "qty_ordered": 0,
            "qty_received": int(received_qty),
        }

    payable = payable_cents(received_qty, order.unit_price_cents, order.tax_rate_bp)
    diff = int(invoice.amount_cents) - payable

    if int(invoice.tax_rate_bp) != int(order.tax_rate_bp):
        status = MatchStatus.TAX_DIFF.value
    elif qty_out_of_tolerance(received_qty, order.qty, tolerance.qty_pct):
        status = MatchStatus.QTY_DIFF.value
    elif abs(diff) > int(tolerance.amount_cents):
        status = MatchStatus.PRICE_DIFF.value
    else:
        status = MatchStatus.MATCHED.value

    return {
        "match_status": status,
        "diff_type": MATCH_DIFF_TYPE.get(status, DiffType.NONE.value),
        "payable_cents": payable,
        "diff_cents": diff,
        "suggestion": suggest_for(
            status, diff_cents=diff, received=int(received_qty), ordered=int(order.qty)
        ),
        "unit_price_cents": order.unit_price_cents,
        "qty_ordered": order.qty,
        "qty_received": int(received_qty),
    }


def run_match(
    invoices: list[InvoiceView],
    orders: list[OrderView],
    receipts: list[ReceiptView],
    tolerances: dict[int, Tolerance] | None = None,
    default_tolerance: Tolerance | None = None,
) -> MatchOutcome:
    """对一批已归一发票执行三单匹配；输入顺序决定「哪一张算重复」。"""
    orders_by_po = {order.po_no: order for order in orders}
    received_by_po: dict[str, int] = defaultdict(int)
    for receipt in receipts:
        received_by_po[receipt.po_no] += int(receipt.qty)
    tolerance_map = tolerances or {}
    fallback = default_tolerance or Tolerance()

    outcome = MatchOutcome()
    outcome.by_status = {key: 0 for key in MATCH_STATUS_ORDER}
    outcome.by_type = {value: 0 for value in MATCH_DIFF_TYPE.values()}
    seen_invoice_nos: set[str] = set()

    for invoice in invoices:
        if invoice.invoice_no in seen_invoice_nos:
            payable = 0
            unit_price = 0
            ordered = 0
            received = 0
            status = MatchStatus.DUPLICATE.value
            diff = int(invoice.amount_cents)
            suggestion = Suggestion.RETURN_REISSUE.value
            diff_type = DiffType.DUPLICATE.value
        else:
            seen_invoice_nos.add(invoice.invoice_no)
            order = orders_by_po.get((invoice.po_no or "").strip().upper())
            received = received_by_po.get(order.po_no, 0) if order else 0
            tolerance = tolerance_map.get(order.supplier_id, fallback) if order else fallback
            result = classify(invoice, order=order, received_qty=received, tolerance=tolerance)
            status = result["match_status"]
            diff_type = result["diff_type"]
            payable = result["payable_cents"]
            diff = result["diff_cents"]
            suggestion = result["suggestion"]
            unit_price = result["unit_price_cents"]
            ordered = result["qty_ordered"]

        is_diff = status in DIFF_STATUSES
        outcome.by_status[status] = outcome.by_status.get(status, 0) + 1
        outcome.by_type[diff_type] = outcome.by_type.get(diff_type, 0) + 1
        outcome.by_suggestion[suggestion] = outcome.by_suggestion.get(suggestion, 0) + 1
        outcome.total_diff_cents += diff
        if is_diff:
            outcome.diffs += 1
        else:
            outcome.matched += 1
        outcome.cases.append(
            {
                "case_key": invoice.case_key,
                "invoice_no": invoice.invoice_no,
                "import_batch": invoice.import_batch,
                "po_no": invoice.po_no,
                "supplier_id": invoice.supplier_id,
                "supplier_name": invoice.supplier_name,
                "material_code": invoice.material_code,
                "match_status": status,
                "diff_type": diff_type,
                "diff_amount_cents": diff,
                "invoice_amount_cents": invoice.amount_cents,
                "payable_cents": payable,
                "unit_price_cents": unit_price,
                "qty_ordered": ordered,
                "qty_received": received,
                "suggestion": suggestion,
                "status": CaseStatus.PENDING.value,
                "payload": {
                    "tax_rate_bp": invoice.tax_rate_bp,
                    "is_red": invoice.is_red,
                    "po_tax_rate_bp": None,
                },
            }
        )
    return outcome
