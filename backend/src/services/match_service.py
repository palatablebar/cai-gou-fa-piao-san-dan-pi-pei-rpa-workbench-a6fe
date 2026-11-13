"""匹配运行服务：装配三单数据 -> 调算法 B -> 落 MatchCase -> 汇总指标。"""
from __future__ import annotations

import time
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.constants.enums import (
    CASE_STATUS_LABELS,
    CASE_STATUS_ORDER,
    DIFF_STATUSES,
    MATCH_STATUS_LABELS,
    MATCH_STATUS_ORDER,
    CaseStatus,
    DiffType,
    InvoiceStatus,
    MatchStatus,
    SUGGESTION_LABELS,
    DIFF_TYPE_LABELS,
    tax_rate_label,
)
from src.models.goods_receipt import GoodsReceipt
from src.models.invoice import Invoice
from src.models.match_case import MatchCase
from src.models.match_run import MatchRun
from src.models.purchase_order import PurchaseOrder
from src.models.supplier import Supplier
from src.services import matching_service
from src.services.normalization_service import yuan_from_cents
from src.utils.errors import AppError
from src.utils.timeutil import iso_utc, local_now, utcnow


# ---------------- 序列化 ----------------


def serialize_case(case: MatchCase, *, show_price: bool = True) -> dict:
    return {
        "id": case.id,
        "run_id": case.run_id,
        "case_key": case.case_key,
        "invoice_no": case.invoice_no,
        "import_batch": case.import_batch,
        "po_no": case.po_no,
        "supplier_id": case.supplier_id,
        "supplier_name": case.supplier_name,
        "material_code": case.material_code,
        "match_status": case.match_status,
        "match_status_label": MATCH_STATUS_LABELS.get(case.match_status, case.match_status),
        "diff_type": case.diff_type,
        "diff_type_label": DIFF_TYPE_LABELS.get(case.diff_type, case.diff_type),
        "diff_amount_cents": case.diff_amount_cents,
        "diff_amount": yuan_from_cents(case.diff_amount_cents),
        "invoice_amount_cents": case.invoice_amount_cents,
        "invoice_amount": yuan_from_cents(case.invoice_amount_cents),
        "payable_cents": case.payable_cents,
        "payable_amount": yuan_from_cents(case.payable_cents),
        # viewer 角色后端置空单价（不是前端隐藏）
        "unit_price": yuan_from_cents(case.unit_price_cents) if show_price else None,
        "qty_ordered": case.qty_ordered,
        "qty_received": case.qty_received,
        "suggestion": case.suggestion,
        "suggestion_label": SUGGESTION_LABELS.get(case.suggestion, case.suggestion),
        "status": case.status,
        "status_label": CASE_STATUS_LABELS.get(case.status, case.status),
        "reviewer": case.reviewer,
        "note": case.note,
        "payload": case.payload or {},
        "created_at": iso_utc(case.created_at),
        "updated_at": iso_utc(case.updated_at),
    }


def serialize_run(run: MatchRun) -> dict:
    return {
        "id": run.id,
        "run_no": run.run_no,
        "period": run.period,
        "trigger": run.trigger,
        "status": run.status,
        "operator_email": run.operator_email,
        "invoice_raw_count": run.invoice_raw_count,
        "rejected_count": run.rejected_count,
        "matched_count": run.matched_count,
        "diff_count": run.diff_count,
        "case_count": run.case_count,
        "metrics": run.metrics or {},
        "log_text": run.log_text,
        "started_at": iso_utc(run.started_at),
        "finished_at": iso_utc(run.finished_at),
    }


# ---------------- 运行 ----------------


def next_run_no(db: Session, period: str) -> str:
    prefix = f"MR-{period.replace('-', '')}"
    count = db.scalar(select(func.count()).select_from(MatchRun).where(MatchRun.run_no.like(f"{prefix}%"))) or 0
    return f"{prefix}-{count + 1:03d}"


def default_period(db: Session) -> str:
    latest: date | None = db.scalar(select(func.max(Invoice.issued_on)).where(Invoice.status == InvoiceStatus.VALID.value))
    if latest is None:
        return local_now().strftime("%Y-%m")
    return latest.strftime("%Y-%m")


def _period_bounds(period: str) -> tuple[date, date]:
    year, month = (int(part) for part in period.split("-"))
    start = date(year, month, 1)
    end = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return start, end


def _load_views(db: Session, period: str) -> tuple[list, list, list, dict, list[Invoice]]:
    start, end = _period_bounds(period)
    invoices = db.scalars(
        select(Invoice)
        .where(Invoice.status == InvoiceStatus.VALID.value)
        .where(Invoice.issued_on >= start)
        .where(Invoice.issued_on < end)
        .order_by(Invoice.id)
    ).all()
    orders = db.scalars(select(PurchaseOrder)).all()
    receipts = db.scalars(select(GoodsReceipt)).all()
    suppliers = db.scalars(select(Supplier)).all()

    supplier_names = {supplier.id: supplier.name for supplier in suppliers}
    tolerances = {
        supplier.id: matching_service.Tolerance(
            amount_cents=int(supplier.tolerance_amount_cents or 0),
            qty_pct=supplier.tolerance_qty_pct or 0,
        )
        for supplier in suppliers
    }
    invoice_views = [
        matching_service.InvoiceView(
            case_key=f"{invoice.invoice_no}#{invoice.import_batch}",
            invoice_no=invoice.invoice_no,
            import_batch=invoice.import_batch,
            supplier_id=invoice.supplier_id,
            supplier_name=supplier_names.get(invoice.supplier_id, invoice.supplier_name_raw),
            po_no=invoice.po_no,
            material_code=invoice.material_code,
            amount_cents=invoice.amount_cents,
            tax_rate_bp=invoice.tax_rate_bp,
            is_red=bool(invoice.is_red),
        )
        for invoice in invoices
    ]
    order_views = [
        matching_service.OrderView(
            po_no=order.po_no,
            supplier_id=order.supplier_id,
            material_code=order.material_code,
            qty=order.qty,
            unit_price_cents=order.unit_price_cents,
            tax_rate_bp=order.tax_rate_bp,
        )
        for order in orders
    ]
    receipt_views = [matching_service.ReceiptView(po_no=row.po_no, qty=row.qty) for row in receipts]
    return invoice_views, order_views, receipt_views, tolerances, invoices


def _persist_cases(db: Session, run: MatchRun, cases: list[dict], order_tax: dict[str, int]) -> None:
    existing = {
        case.case_key: case
        for case in db.scalars(select(MatchCase).where(MatchCase.run_id == run.id)).all()
    }
    for item in cases:
        payload = dict(item["payload"])
        payload["po_tax_rate_bp"] = order_tax.get((item.get("po_no") or "").upper())
        payload["po_tax_rate_label"] = tax_rate_label(payload["po_tax_rate_bp"])
        payload["invoice_tax_rate_label"] = tax_rate_label(payload["tax_rate_bp"])
        case = existing.get(item["case_key"])
        if case is None:
            case = MatchCase(
                run_id=run.id,
                case_key=item["case_key"],
                invoice_no=item["invoice_no"],
                import_batch=item["import_batch"],
                po_no=item["po_no"],
                supplier_id=item["supplier_id"],
                supplier_name=item["supplier_name"],
                material_code=item["material_code"],
                match_status=item["match_status"],
                diff_type=item["diff_type"],
                diff_amount_cents=item["diff_amount_cents"],
                invoice_amount_cents=item["invoice_amount_cents"],
                payable_cents=item["payable_cents"],
                unit_price_cents=item["unit_price_cents"],
                qty_ordered=item["qty_ordered"],
                qty_received=item["qty_received"],
                suggestion=item["suggestion"],
                status=CaseStatus.PENDING.value,
                payload=payload,
            )
            db.add(case)
        else:
            # 重跑同一个 run：更新算法结论，但保留人工处理状态/备注
            case.match_status = item["match_status"]
            case.diff_type = item["diff_type"]
            case.diff_amount_cents = item["diff_amount_cents"]
            case.invoice_amount_cents = item["invoice_amount_cents"]
            case.payable_cents = item["payable_cents"]
            case.unit_price_cents = item["unit_price_cents"]
            case.qty_ordered = item["qty_ordered"]
            case.qty_received = item["qty_received"]
            case.suggestion = item["suggestion"]
            case.payload = payload
    db.flush()


def execute_run(db: Session, run: MatchRun) -> MatchRun:
    started = time.perf_counter()
    run.status = "running"
    db.flush()
    try:
        invoice_views, order_views, receipt_views, tolerances, invoices = _load_views(db, run.period)
        rejected = db.scalar(
            select(func.count())
            .select_from(Invoice)
            .where(Invoice.status == InvoiceStatus.REJECTED.value)
        ) or 0
        outcome = matching_service.run_match(
            invoice_views,
            order_views,
            receipt_views,
            tolerances=tolerances,
            default_tolerance=matching_service.Tolerance(),
        )
        order_tax = {order.po_no: order.tax_rate_bp for order in order_views}
        _persist_cases(db, run, outcome.cases, order_tax)

        metrics = outcome.metrics()
        metrics.update(
            {
                "period": run.period,
                "invoice_raw_count": len(invoices) + int(rejected),
                "rejected_count": int(rejected),
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "tolerance": {"amount_cents": matching_service.DEFAULT_TOLERANCE_AMOUNT_CENTS},
                "suppliers": len(tolerances),
                "orders": len(order_views),
                "receipts": len(receipt_views),
            }
        )
        run.invoice_raw_count = len(invoices) + int(rejected)
        run.rejected_count = int(rejected)
        run.case_count = len(outcome.cases)
        run.matched_count = outcome.matched
        run.diff_count = outcome.diffs
        run.metrics = metrics
        run.status = "success" if outcome.cases else "partial"
        run.log_text = (
            f"账期 {run.period}：原始发票 {run.invoice_raw_count} 张，归一失败 {run.rejected_count} 张，"
            f"入池 {len(outcome.cases)} 张；三单一致 {outcome.matched} 张，差异 {outcome.diffs} 张（"
            + "，".join(
                f"{MATCH_STATUS_LABELS[key]} {metrics['by_status'].get(key, 0)}"
                for key in MATCH_STATUS_ORDER
                if key != MatchStatus.MATCHED.value
            )
            + f"）；差异合计 {yuan_from_cents(outcome.total_diff_cents):,.2f} 元。"
        )
    except Exception as exc:  # noqa: BLE001 - 失败留痕，不抛 500
        run.status = "failed"
        run.log_text = f"匹配失败：{exc}"
        run.metrics = {"error": str(exc)[:300]}
    run.finished_at = utcnow()
    db.flush()
    return run


def create_and_execute(
    db: Session,
    *,
    period: str | None,
    trigger: str,
    operator_email: str,
    seed_key: str | None = None,
) -> MatchRun:
    if seed_key:
        existing = db.scalar(select(MatchRun).where(MatchRun.seed_key == seed_key))
        if existing is not None:
            return existing
    period = period or default_period(db)
    run = MatchRun(
        run_no=next_run_no(db, period),
        period=period,
        trigger=trigger,
        status="running",
        operator_email=operator_email,
        seed_key=seed_key,
    )
    db.add(run)
    db.flush()
    return execute_run(db, run)


def list_runs(db: Session, *, period: str | None, status: str | None, limit: int, offset: int) -> dict:
    stmt = select(MatchRun)
    count_stmt = select(func.count()).select_from(MatchRun)
    if period:
        stmt = stmt.where(MatchRun.period == period)
        count_stmt = count_stmt.where(MatchRun.period == period)
    if status:
        stmt = stmt.where(MatchRun.status == status)
        count_stmt = count_stmt.where(MatchRun.status == status)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(MatchRun.id.desc()).limit(limit).offset(offset)).all()
    return {
        "items": [serialize_run(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_run(db: Session, run_id: int) -> MatchRun:
    run = db.get(MatchRun, run_id)
    if run is None:
        raise AppError("NOT_FOUND", 404, {"entity": "match_run", "id": run_id})
    return run


def list_cases(
    db: Session,
    *,
    run_id: int | None = None,
    match_status: str | None = None,
    diff_type: str | None = None,
    status: str | None = None,
    supplier_id: int | None = None,
    q: str | None = None,
    only_diffs: bool = False,
    show_price: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    stmt = select(MatchCase)
    count_stmt = select(func.count()).select_from(MatchCase)
    clauses = []
    if run_id:
        clauses.append(MatchCase.run_id == run_id)
    if match_status:
        clauses.append(MatchCase.match_status == match_status)
    if diff_type:
        clauses.append(MatchCase.diff_type == diff_type)
    if status:
        clauses.append(MatchCase.status == status)
    if supplier_id:
        clauses.append(MatchCase.supplier_id == supplier_id)
    if only_diffs:
        clauses.append(MatchCase.match_status.in_(DIFF_STATUSES))
    if q:
        like = f"%{q.strip()}%"
        clauses.append(
            MatchCase.invoice_no.ilike(like)
            | MatchCase.po_no.ilike(like)
            | MatchCase.supplier_name.ilike(like)
        )
    for clause in clauses:
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(MatchCase.run_id.desc(), MatchCase.id).limit(limit).offset(offset)
    ).all()
    return {
        "items": [serialize_case(row, show_price=show_price) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_case(db: Session, case_id: int) -> MatchCase:
    case = db.get(MatchCase, case_id)
    if case is None:
        raise AppError("NOT_FOUND", 404, {"entity": "match_case", "id": case_id})
    return case


def review_case(db: Session, case: MatchCase, *, status: str, note: str | None, reviewer: str) -> MatchCase:
    if case.match_status == MatchStatus.MATCHED.value and status != CaseStatus.PENDING.value:
        raise AppError("VALIDATION", 422, {"field": "status", "reason": "三单一致的记录无需处理"})
    case.status = status
    case.note = note
    case.reviewer = reviewer
    case.updated_at = utcnow()
    db.flush()
    return case


def adjustments(db: Session, *, limit: int = 200) -> dict:
    """调整单汇总：已处理（非待处理）的差异工单，按处理结果分组。"""
    rows = db.scalars(
        select(MatchCase)
        .where(MatchCase.status != CaseStatus.PENDING.value)
        .order_by(MatchCase.updated_at.desc(), MatchCase.id)
        .limit(limit)
    ).all()
    grouped: dict[str, list[dict]] = {key: [] for key in CASE_STATUS_ORDER if key != CaseStatus.PENDING.value}
    for row in rows:
        grouped.setdefault(row.status, []).append(serialize_case(row))
    totals = db.execute(
        select(MatchCase.status, func.count(), func.sum(MatchCase.diff_amount_cents))
        .where(MatchCase.status != CaseStatus.PENDING.value)
        .group_by(MatchCase.status)
    ).all()
    return {
        "items": [serialize_case(row) for row in rows],
        "total": len(rows),
        "groups": [
            {"status": key, "label": CASE_STATUS_LABELS.get(key, key), "count": len(items), "items": items}
            for key, items in grouped.items()
        ],
        "summary": [
            {"status": st, "label": CASE_STATUS_LABELS.get(st, st), "count": count, "diff_amount": yuan_from_cents(total or 0)}
            for st, count, total in totals
        ],
    }


def case_status_options() -> list[dict]:
    return [{"value": key, "label": CASE_STATUS_LABELS[key]} for key in CASE_STATUS_ORDER]


def suggestion_options() -> list[dict]:
    return [{"value": key, "label": label} for key, label in SUGGESTION_LABELS.items()]


def diff_filter_options() -> list[dict]:
    return [{"value": key, "label": label} for key, label in DIFF_TYPE_LABELS.items()]


def app_name() -> str:
    return settings.app_name


def match_status_options() -> list[dict]:
    return [{"value": key, "label": MATCH_STATUS_LABELS[key]} for key in MATCH_STATUS_ORDER]


def diff_type_value(status: str) -> str:
    return {
        MatchStatus.PRICE_DIFF.value: DiffType.AMOUNT.value,
    }.get(status, DiffType.NONE.value)
