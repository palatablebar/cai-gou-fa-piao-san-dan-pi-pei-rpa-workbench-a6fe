"""算法 A（字段归一与匹配键）单测：正常 + 边界 + 拒绝分支 + 确定性。"""
from __future__ import annotations

from datetime import date

from src.services import normalization_service as norm


def test_supplier_suffix_and_alias_normalization():
    aliases = {"华翔": "宁波华翔汽车部件股份有限公司"}
    assert norm.normalize_supplier_name("宁波华翔汽车部件股份有限公司") == "宁波华翔汽车部件"
    assert norm.normalize_supplier_name("  宁波华翔汽车部件有限公司 ") == "宁波华翔汽车部件"
    # 别名表优先于后缀剥离
    assert norm.normalize_supplier_name("华翔", aliases) == "宁波华翔汽车部件"
    assert norm.normalize_supplier_name("（杭州）富阳冲压件厂") == "(杭州)富阳冲压件"


def test_amount_cents_and_tax_rate_basis_points():
    assert norm.parse_amount_cents("1,234.56") == 123456
    assert norm.parse_amount_cents("￥123.4元") == 12340
    assert norm.parse_amount_cents(99.999) == 10000  # 四舍五入到分
    assert norm.parse_tax_rate_bp("13%") == 1300
    assert norm.parse_tax_rate_bp(0.09) == 900
    assert norm.parse_tax_rate_bp("6") == 600


def test_tax_rate_outside_standard_set_is_rejected():
    for bad in ("7%", "0.11", "17", ""):
        try:
            norm.parse_tax_rate_bp(bad)
        except norm.NormalizationError as exc:
            assert exc.field == "tax_rate"
        else:  # pragma: no cover
            raise AssertionError(f"{bad} 应被拒绝")


def test_gross_net_roundtrip_and_match_key():
    gross = norm.gross_from_net_cents(100000, 1300)
    assert gross == 113000
    assert norm.net_from_gross_cents(gross, 1300) == 100000
    assert norm.net_from_gross_cents(113000, 0) == 113000
    assert norm.build_match_key("宁波华翔", "po-2026-0001", "mat-1001") == "宁波华翔|PO-2026-0001|MAT-1001"


def test_normalize_rows_collects_rejected_instead_of_raising():
    rows = [
        {
            "invoice_no": "INV-2026-0001",
            "supplier_name": "宁波华翔汽车部件有限公司",
            "po_no": "PO-2026-0001",
            "material_code": "MAT-1001",
            "amount": "1,130.00",
            "tax_rate": "13%",
            "issued_on": date(2026, 10, 8),
        },
        {"invoice_no": "INV-2026-0002", "supplier_name": "宁波华翔", "amount": "N/A", "tax_rate": "13%",
         "issued_on": date(2026, 10, 9)},
        {"invoice_no": "INV-2026-0003", "supplier_name": "宁波华翔", "amount": "100.00", "tax_rate": "7%",
         "issued_on": date(2026, 10, 9)},
    ]
    result = norm.normalize_invoice_rows(
        rows, aliases={"宁波华翔": "宁波华翔汽车部件有限公司"}, supplier_index={"宁波华翔汽车部件": 7}
    )
    assert len(result["accepted"]) == 1
    accepted = result["accepted"][0]
    assert accepted.amount_cents == 113000
    assert accepted.supplier_id == 7
    assert accepted.match_key == "宁波华翔汽车部件|PO-2026-0001|MAT-1001"
    assert [item["field"] for item in result["rejected"]] == ["amount", "tax_rate"]


def test_red_invoice_is_negative_and_deterministic():
    row = {
        "invoice_no": "INV-2026-0009",
        "supplier_name": "苏州汇川精密制造有限公司",
        "amount": "500.00",
        "tax_rate": "13%",
        "issued_on": "2026-10-31",
        "is_red": True,
    }
    first = norm.normalize_invoice_row(row)
    second = norm.normalize_invoice_row(row)
    assert first.amount_cents == -50000
    assert first == second
    assert first.tax_cents == -50000 - norm.net_from_gross_cents(-50000, 1300)
