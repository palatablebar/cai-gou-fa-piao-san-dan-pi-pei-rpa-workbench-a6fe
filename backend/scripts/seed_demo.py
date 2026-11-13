"""幂等 seed：3 账号 / 46 供应商 / 180 PO / 210 GRN / 190 有效发票（+5 条归一失败样本）/ 1 次匹配运行。

自然键 upsert：
  users.email
  suppliers.code
  purchase_orders.po_no
  goods_receipts.grn_no
  invoices(invoice_no, import_batch)
  match_runs.seed_key
  match_cases(run_id, case_key)
  audit_logs.seed_key

重复执行不新增、不覆盖人工处理过的差异状态；SEED_SUMMARY 逐字一致。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from src.config.database import session_scope
from src.constants.enums import DIFF_STATUSES, InvoiceStatus
from src.models.audit import AuditLog
from src.models.goods_receipt import GoodsReceipt
from src.models.invoice import Invoice
from src.models.match_case import MatchCase
from src.models.match_run import MatchRun
from src.models.purchase_order import PurchaseOrder
from src.models.supplier import Supplier
from src.models.user import User
from src.services import batch_service, normalization_service as norm, supplier_service
from src.utils.security import hash_password

from scripts.demo_config import (
    DEMO_PASSWORD,
    DEMO_USERS,
    ORG,
    SEED_RUN,
    build_invoice_rows,
    build_orders,
    build_receipts,
    build_rejected_rows,
    build_suppliers,
    tax_breakdown,
)


def ensure_users(db) -> int:
    for email, display_name, role in DEMO_USERS:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            db.add(
                User(
                    email=email,
                    password_hash=hash_password(DEMO_PASSWORD),
                    display_name=display_name,
                    role=role,
                    org=ORG,
                )
            )
    db.flush()
    return db.scalar(select(func.count()).select_from(User)) or 0


def ensure_suppliers(db, specs: list[dict]) -> int:
    for spec in specs:
        supplier = db.scalar(select(Supplier).where(Supplier.code == spec["code"]))
        if supplier is None:
            db.add(
                Supplier(
                    code=spec["code"],
                    name=spec["name"],
                    name_norm=supplier_service.normalize_supplier_name(spec["name"]),
                    alias=spec.get("alias"),
                    contact=spec.get("contact"),
                    tolerance_amount_cents=spec["tolerance_amount_cents"],
                    tolerance_qty_pct=spec["tolerance_qty_pct"],
                    note=spec.get("note"),
                    enabled=True,
                )
            )
    db.flush()
    return db.scalar(select(func.count()).select_from(Supplier)) or 0


def ensure_orders(db, specs: list[dict]) -> int:
    suppliers = {supplier.code: supplier for supplier in db.scalars(select(Supplier)).all()}
    for spec in specs:
        if db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_no == spec["po_no"])) is not None:
            continue
        supplier = suppliers[spec["supplier_code"]]
        db.add(
            PurchaseOrder(
                po_no=spec["po_no"],
                supplier_id=supplier.id,
                material_code=spec["material_code"],
                material_name=spec["material_name"],
                qty=spec["qty"],
                unit_price_cents=spec["unit_price_cents"],
                tax_rate_bp=spec["tax_rate_bp"],
                ordered_on=spec["ordered_on"],
            )
        )
    db.flush()
    return db.scalar(select(func.count()).select_from(PurchaseOrder)) or 0


def ensure_receipts(db, specs: list[dict]) -> int:
    for spec in specs:
        if db.scalar(select(GoodsReceipt).where(GoodsReceipt.grn_no == spec["grn_no"])) is not None:
            continue
        db.add(
            GoodsReceipt(
                grn_no=spec["grn_no"],
                po_no=spec["po_no"],
                qty=spec["qty"],
                received_on=spec["received_on"],
                batch=spec["batch"],
            )
        )
    db.flush()
    return db.scalar(select(func.count()).select_from(GoodsReceipt)) or 0


def ensure_invoices(db, raw_rows: list[dict], rejected_rows: list[dict]) -> tuple[int, int]:
    aliases = supplier_service.alias_map(db)
    index = supplier_service.supplier_index(db)
    result = norm.normalize_invoice_rows(raw_rows + rejected_rows, aliases=aliases, supplier_index=index)
    for item in result["accepted"]:
        exists = db.scalar(
            select(Invoice).where(
                Invoice.invoice_no == item.invoice_no, Invoice.import_batch == item.import_batch
            )
        )
        if exists is not None:
            continue
        db.add(
            Invoice(
                invoice_no=item.invoice_no,
                import_batch=item.import_batch,
                supplier_id=item.supplier_id,
                supplier_name_raw=item.supplier_name_raw,
                po_no=item.po_no,
                material_code=item.material_code,
                amount_cents=item.amount_cents,
                tax_cents=item.tax_cents,
                tax_rate_bp=item.tax_rate_bp,
                issued_on=item.issued_on,
                is_red=item.is_red,
                status=InvoiceStatus.VALID.value,
            )
        )
    for reject in result["rejected"]:
        raw = rejected_rows[reject["row"] - len(raw_rows) - 1]
        invoice_no = str(raw.get("invoice_no") or f"INV-BAD-{reject['row']:04d}")
        exists = db.scalar(
            select(Invoice).where(Invoice.invoice_no == invoice_no, Invoice.import_batch == raw["import_batch"])
        )
        if exists is not None:
            continue
        amount_text = str(raw.get("amount") or "0")
        try:
            amount_cents = norm.parse_amount_cents(amount_text)
        except norm.NormalizationError:
            amount_cents = 0
        tax_rate = 1300
        try:
            tax_rate = norm.parse_tax_rate_bp(raw.get("tax_rate"))
        except norm.NormalizationError:
            tax_rate = 0
        issued_on = raw.get("issued_on")
        db.add(
            Invoice(
                invoice_no=invoice_no,
                import_batch=raw["import_batch"],
                supplier_id=None,
                supplier_name_raw=str(raw.get("supplier_name") or ""),
                po_no=raw.get("po_no"),
                material_code=None,
                amount_cents=abs(amount_cents),
                tax_cents=tax_breakdown(abs(amount_cents), tax_rate) if tax_rate else 0,
                tax_rate_bp=tax_rate,
                issued_on=issued_on if hasattr(issued_on, "year") else date(2026, 10, 1),
                is_red=False,
                status=InvoiceStatus.REJECTED.value,
                reject_reason=f"{reject['field']}: {reject['reason']}",
            )
        )
    db.flush()
    valid = (
        db.scalar(select(func.count()).select_from(Invoice).where(Invoice.status == InvoiceStatus.VALID.value)) or 0
    )
    rejected = (
        db.scalar(select(func.count()).select_from(Invoice).where(Invoice.status == InvoiceStatus.REJECTED.value))
        or 0
    )
    return valid, rejected


def ensure_run(db) -> MatchRun:
    """初始化批次：seed_key 即批次幂等键；重复执行复用正式版，不新增运行/工单。"""
    return batch_service.ensure_seed_batch(
        db,
        period=SEED_RUN["period"],
        seed_key=SEED_RUN["seed_key"],
        operator=SEED_RUN["operator"],
    )


def ensure_audit(db) -> None:
    seeds = [
        ("seed-audit-1", "admin@invoice3way.io", "admin", "supplier.update", "supplier", {"tolerance_amount_cents": 2}),
        ("seed-audit-2", "analyst@invoice3way.io", "analyst", "run.create", "match_run", {"period": "2026-10"}),
        ("seed-audit-3", "admin@invoice3way.io", "admin", "invoice.create", "invoice", {"batch": "SRM-2026-10"}),
    ]
    for seed_key, email, role, action, entity, detail in seeds:
        if db.scalar(select(AuditLog).where(AuditLog.seed_key == seed_key)) is None:
            db.add(
                AuditLog(
                    actor_email=email,
                    actor_role=role,
                    action=action,
                    entity=entity,
                    detail=detail,
                    layer="seed",
                    seed_key=seed_key,
                )
            )
    db.flush()


def seed_all() -> dict:
    with session_scope() as db:
        supplier_specs = build_suppliers()
        order_specs = build_orders(supplier_specs)
        receipt_specs = build_receipts(order_specs)
        users = ensure_users(db)
        suppliers = ensure_suppliers(db, supplier_specs)
        orders = ensure_orders(db, order_specs)
        receipts = ensure_receipts(db, receipt_specs)
        invoices, rejected = ensure_invoices(db, build_invoice_rows(supplier_specs, order_specs, receipt_specs), build_rejected_rows())
        run = ensure_run(db)
        ensure_audit(db)
        runs = db.scalar(select(func.count()).select_from(MatchRun)) or 0
        all_cases = db.scalar(select(func.count()).select_from(MatchCase)) or 0
        # findings/pending 只统计本次 seed 运行产出的「差异工单」（三单一致的行不是待办），
        # 与导出行数口径一致；后续手动/定时运行不会改变这两个数字。
        cases = (
            db.scalar(
                select(func.count())
                .select_from(MatchCase)
                .where(MatchCase.run_id == run.id, MatchCase.match_status.in_(DIFF_STATUSES))
            )
            or 0
        )
        pending = (
            db.scalar(
                select(func.count())
                .select_from(MatchCase)
                .where(
                    MatchCase.run_id == run.id,
                    MatchCase.status == "pending",
                    MatchCase.match_status.in_(DIFF_STATUSES),
                )
            )
            or 0
        )
        summary = (
            f"SEED_SUMMARY brand=invoice3way users={users} sources={suppliers} "
            f"runs={runs} findings={cases} pending={pending}"
        )
        print(summary, flush=True)
        print(
            f"SEED_DETAIL period={run.period} orders={orders} receipts={receipts} "
            f"invoices={invoices} rejected={rejected} matched={run.matched_count} diffs={run.diff_count} "
            f"cases={all_cases}",
            flush=True,
        )
        return {
            "users": users,
            "suppliers": suppliers,
            "orders": orders,
            "receipts": receipts,
            "invoices": invoices,
            "rejected": rejected,
            "runs": runs,
            "cases": cases,
            "all_cases": all_cases,
            "pending": pending,
        }


if __name__ == "__main__":
    seed_all()
