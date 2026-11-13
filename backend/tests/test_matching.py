"""算法 B（三单匹配）单测：判定顺序 / 容差边界 / 差异额 / 建议 / 确定性。"""
from __future__ import annotations

from decimal import Decimal

from src.services import matching_service as ms


def _order(**over):
    base = dict(
        po_no="PO-2026-0001",
        supplier_id=1,
        material_code="MAT-1001",
        qty=100,
        unit_price_cents=1000,
        tax_rate_bp=1300,
    )
    base.update(over)
    return ms.OrderView(**base)


def _invoice(**over):
    base = dict(
        case_key="INV-2026-0001#SRM",
        invoice_no="INV-2026-0001",
        import_batch="SRM",
        supplier_id=1,
        supplier_name="宁波华翔",
        po_no="PO-2026-0001",
        material_code="MAT-1001",
        amount_cents=113000,
        tax_rate_bp=1300,
    )
    base.update(over)
    return ms.InvoiceView(**base)


def test_matched_when_three_way_agree():
    outcome = ms.run_match([_invoice()], [_order()], [ms.ReceiptView("PO-2026-0001", 100)])
    assert outcome.matched == 1 and outcome.diffs == 0
    case = outcome.cases[0]
    assert case["match_status"] == "matched"
    assert case["diff_amount_cents"] == 0
    assert case["suggestion"] == "none"
    assert case["payload"]["tax_rate_bp"] == 1300


def test_quantity_tolerance_boundary_is_inclusive():
    # 订单 100，容差 ±1%，收到 99 → 容差内；收到 98 → 量差
    within = ms.run_match([_invoice(amount_cents=111870)], [_order()], [ms.ReceiptView("PO-2026-0001", 99)],
                          tolerances={1: ms.Tolerance(2, Decimal("1.0"))})
    assert within.cases[0]["match_status"] == "matched"
    outside = ms.run_match([_invoice(amount_cents=113000)], [_order()], [ms.ReceiptView("PO-2026-0001", 98)],
                           tolerances={1: ms.Tolerance(2, Decimal("1.0"))})
    assert outside.cases[0]["match_status"] == "qty_diff"
    assert outside.cases[0]["suggestion"] == "receive_more"


def test_amount_tolerance_two_cents_and_price_diff_suggestion():
    ok = ms.run_match([_invoice(amount_cents=113002)], [_order()], [ms.ReceiptView("PO-2026-0001", 100)])
    assert ok.cases[0]["match_status"] == "matched"
    bad = ms.run_match([_invoice(amount_cents=113003)], [_order()], [ms.ReceiptView("PO-2026-0001", 100)])
    assert bad.cases[0]["match_status"] == "price_diff"
    assert bad.cases[0]["diff_amount_cents"] == 3
    assert bad.cases[0]["suggestion"] == "return_reissue"


def test_tax_rate_must_match_even_if_amount_matches():
    outcome = ms.run_match(
        [_invoice(amount_cents=113000, tax_rate_bp=900)],
        [_order()],
        [ms.ReceiptView("PO-2026-0001", 100)],
    )
    case = outcome.cases[0]
    assert case["match_status"] == "tax_diff"
    assert case["diff_type"] == "tax"
    assert case["suggestion"] == "fix_tax"


def test_duplicate_and_missing_po_judgements():
    invoices = [
        _invoice(),
        _invoice(case_key="INV-2026-0001#PLATFORM", import_batch="PLATFORM"),
        _invoice(case_key="INV-2026-0142#SRM", invoice_no="INV-2026-0142", po_no="PO-2026-9999",
                 amount_cents=500000),
    ]
    outcome = ms.run_match(invoices, [_order()], [ms.ReceiptView("PO-2026-0001", 100)])
    statuses = [case["match_status"] for case in outcome.cases]
    assert statuses == ["matched", "duplicate", "missing_po"]
    assert outcome.cases[1]["suggestion"] == "return_reissue"
    assert outcome.cases[1]["payable_cents"] == 0
    assert outcome.cases[1]["diff_amount_cents"] == 113000
    assert outcome.matched == 1 and outcome.diffs == 2


def test_metrics_and_determinism():
    invoices = [_invoice(), _invoice(invoice_no="INV-2026-0002", case_key="INV-2026-0002#SRM",
                                     amount_cents=200000)]
    args = (invoices, [_order()], [ms.ReceiptView("PO-2026-0001", 100)])
    first = ms.run_match(*args)
    second = ms.run_match(*args)
    assert first.metrics() == second.metrics()
    metrics = first.metrics()
    assert metrics["invoices"] == 2
    assert metrics["matched"] == 1 and metrics["diffs"] == 1
    assert metrics["by_status"]["price_diff"] == 1
    assert metrics["total_diff_cents"] == 87000


def test_empty_input_and_qty_out_of_tolerance_helper():
    outcome = ms.run_match([], [], [])
    assert outcome.metrics()["invoices"] == 0
    assert outcome.matched == 0 and outcome.diffs == 0
    assert ms.qty_out_of_tolerance(100, 100, 1) is False
    assert ms.qty_out_of_tolerance(101, 100, 2) is False  # 2% 容差内
    assert ms.qty_out_of_tolerance(102, 100, 1) is True  # 1% 容差边界含等号，2 个单位才越界
