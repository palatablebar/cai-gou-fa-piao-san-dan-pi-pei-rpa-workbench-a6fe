"""账期批次服务：幂等重算、水位核对、原子切换正式版与回滚。

关键约束（对应业务诉求）：
- 同一 batch_key 重试：水位未变时不新建运行、不新增差异工单；
- 迟到发票：生成新版本，只把受影响的差异标为 new / changed，未受影响的行标 unchanged，
  人工处理（status / reviewer / note）按发票自然键 case_key 跨版本继承；
- 切换：来源单据指纹（水位）、匹配结果、差异工单、审计事件四类数量在同一水位核对通过后，
  在一个事务（savepoint）内一次性切换；失败回滚到上一正式版，所有记录和处理意见保留。
"""
from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.constants.enums import (
    BATCH_STATUS_LABELS,
    BATCH_VERSION_STATUS_LABELS,
    CASE_DIFF_FIELDS,
    CHANGE_KIND_LABELS,
    DIFF_STATUSES,
    BatchStatus,
    BatchVersionStatus,
    CaseStatus,
    ChangeKind,
    InvoiceStatus,
)
from src.models.audit import AuditLog
from src.models.goods_receipt import GoodsReceipt
from src.models.invoice import Invoice
from src.models.match_batch import MatchBatch, MatchBatchVersion, watermark_label
from src.models.match_case import MatchCase
from src.models.match_run import MatchRun
from src.models.purchase_order import PurchaseOrder
from src.models.supplier import Supplier
from src.services import audit_service, match_service
from src.utils.errors import AppError
from src.utils.timeutil import iso_utc, utcnow

# 计入「审计数量」核对的动作：建档与重算。核对 / 切换本身发生在快照之后，不计入基线。
COUNTED_AUDIT_ACTIONS = ("batch.open", "batch.recompute")
CHANGE_FIELDS: tuple[str, ...] = CASE_DIFF_FIELDS


def _period_bounds(period: str) -> tuple[date, date]:
    return match_service._period_bounds(period)


def _watermark_of(lines: list[str]) -> str:
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return digest[:64]


def compute_watermark(db: Session, period: str) -> tuple[str, dict]:
    """来源单据指纹 + 计数。任何订单 / 收货 / 发票 / 供应商容差变化都会改变水位。"""
    start, end = _period_bounds(period)
    suppliers = db.scalars(select(Supplier).order_by(Supplier.id)).all()
    orders = db.scalars(select(PurchaseOrder).order_by(PurchaseOrder.po_no)).all()
    receipts = db.scalars(select(GoodsReceipt).order_by(GoodsReceipt.grn_no)).all()
    invoices = db.scalars(
        select(Invoice)
        .where(Invoice.issued_on >= start, Invoice.issued_on < end)
        .order_by(Invoice.invoice_no, Invoice.import_batch)
    ).all()

    lines: list[str] = []
    for supplier in suppliers:
        lines.append(
            "SUP|{id}|{name}|{tol_amt}|{tol_qty}".format(
                id=supplier.id,
                name=supplier.name_norm or supplier.name,
                tol_amt=supplier.tolerance_amount_cents,
                tol_qty=supplier.tolerance_qty_pct,
            )
        )
    for order in orders:
        lines.append(
            f"PO|{order.po_no}|{order.supplier_id}|{order.material_code}|"
            f"{order.qty}|{order.unit_price_cents}|{order.tax_rate_bp}"
        )
    for receipt in receipts:
        lines.append(f"GRN|{receipt.grn_no}|{receipt.po_no}|{receipt.qty}")
    for invoice in invoices:
        lines.append(
            f"INV|{invoice.invoice_no}|{invoice.import_batch}|{invoice.supplier_id}|"
            f"{invoice.po_no}|{invoice.material_code}|{invoice.amount_cents}|"
            f"{invoice.tax_rate_bp}|{invoice.is_red}|{invoice.status}|{invoice.reject_reason or ''}"
        )

    counts = {
        "suppliers": len(suppliers),
        "orders": len(orders),
        "receipts": len(receipts),
        "invoices": len(invoices),
        "invoices_valid": sum(1 for row in invoices if row.status == InvoiceStatus.VALID.value),
        "invoices_rejected": sum(1 for row in invoices if row.status == InvoiceStatus.REJECTED.value),
    }
    return _watermark_of(lines), counts


def next_batch_no(db: Session, period: str) -> str:
    prefix = f"BT-{period.replace('-', '')}"
    count = db.scalar(select(func.count()).select_from(MatchBatch).where(MatchBatch.batch_no.like(f"{prefix}%"))) or 0
    return f"{prefix}-{count + 1:03d}"


def next_version_no(db: Session, batch_id: int) -> int:
    latest = db.scalar(select(func.max(MatchBatchVersion.version_no)).where(MatchBatchVersion.batch_id == batch_id))
    return int(latest or 0) + 1


# ---------------- 序列化 ----------------


def serialize_version(version: MatchBatchVersion, *, batch: MatchBatch | None = None) -> dict:
    counts = version.counts or {}
    change = version.change_summary or {}
    return {
        "id": version.id,
        "batch_id": version.batch_id,
        "version_no": version.version_no,
        "label": f"v{version.version_no}",
        "version_label": f"v{version.version_no}",
        "run_id": version.run_id,
        "status": version.status,
        "status_label": BATCH_VERSION_STATUS_LABELS.get(version.status, version.status),
        "watermark": version.watermark,
        "watermark_label": watermark_label(batch.period if batch else "", version.watermark),
        "watermark_detail": version.watermark_detail or {},
        "counts": counts,
        # 列表/详情只带汇总，明细走 /match-batches/{id}/changes，避免响应体过大
        "change_summary": {key: value for key, value in change.items() if key != "items"},
        "verify": version.verify_snapshot or {},
        "error": version.error,
        "created_by": version.created_by,
        "created_at": iso_utc(version.created_at),
        "activated_at": iso_utc(version.activated_at),
    }


def serialize_batch(db: Session, batch: MatchBatch) -> dict:
    official = db.get(MatchBatchVersion, batch.official_version_id) if batch.official_version_id else None
    staging = db.get(MatchBatchVersion, batch.staging_version_id) if batch.staging_version_id else None
    versions = db.scalars(
        select(MatchBatchVersion)
        .where(MatchBatchVersion.batch_id == batch.id)
        .order_by(MatchBatchVersion.version_no.desc())
    ).all()
    return {
        "id": batch.id,
        "batch_no": batch.batch_no,
        "batch_key": batch.batch_key,
        "period": batch.period,
        "status": batch.status,
        "status_label": BATCH_STATUS_LABELS.get(batch.status, batch.status),
        "watermark": batch.watermark,
        "watermark_label": batch.watermark_label,
        "source_counts": batch.source_counts or {},
        "official_version_id": batch.official_version_id,
        "staging_version_id": batch.staging_version_id,
        "official_version": serialize_version(official, batch=batch) if official else None,
        "staging_version": serialize_version(staging, batch=batch) if staging else None,
        "versions": [serialize_version(row, batch=batch) for row in versions],
        "remark": batch.remark,
        "created_by": batch.created_by,
        "created_at": iso_utc(batch.created_at),
        "updated_at": iso_utc(batch.updated_at),
    }


def get_batch(db: Session, batch_id: int) -> MatchBatch:
    batch = db.get(MatchBatch, batch_id)
    if batch is None:
        raise AppError("NOT_FOUND", 404, {"entity": "match_batch", "id": batch_id})
    return batch


def list_batches(
    db: Session, *, period: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0
) -> dict:
    stmt = select(MatchBatch)
    count_stmt = select(func.count()).select_from(MatchBatch)
    if period:
        stmt = stmt.where(MatchBatch.period == period)
        count_stmt = count_stmt.where(MatchBatch.period == period)
    if status:
        stmt = stmt.where(MatchBatch.status == status)
        count_stmt = count_stmt.where(MatchBatch.status == status)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(MatchBatch.id.desc()).limit(limit).offset(offset)).all()
    return {
        "items": [serialize_batch(db, row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "periods": [
            row[0]
            for row in db.execute(select(MatchBatch.period).distinct().order_by(MatchBatch.period.desc())).all()
        ],
    }


# ---------------- 用例快照与变更比较 ----------------


def _case_snapshot(case: MatchCase) -> dict:
    return {
        "case_key": case.case_key,
        "invoice_no": case.invoice_no,
        "import_batch": case.import_batch,
        "po_no": case.po_no,
        "supplier_id": case.supplier_id,
        "supplier_name": case.supplier_name,
        "material_code": case.material_code,
        "match_status": case.match_status,
        "diff_type": case.diff_type,
        "diff_amount_cents": case.diff_amount_cents,
        "invoice_amount_cents": case.invoice_amount_cents,
        "payable_cents": case.payable_cents,
        "unit_price_cents": case.unit_price_cents,
        "qty_ordered": case.qty_ordered,
        "qty_received": case.qty_received,
        "suggestion": case.suggestion,
        "status": case.status,
        "reviewer": case.reviewer,
        "note": case.note,
    }


def _base_cases(db: Session, version: MatchBatchVersion | None) -> dict[str, dict]:
    if version is None or version.run_id is None:
        return {}
    rows = db.scalars(select(MatchCase).where(MatchCase.run_id == version.run_id)).all()
    return {row.case_key: _case_snapshot(row) for row in rows}


def _differences(base: dict, after: dict) -> dict:
    fields = {}
    for name in CHANGE_FIELDS:
        before_value = base.get(name)
        after_value = after.get(name)
        if before_value != after_value:
            fields[name] = {"before": before_value, "after": after_value}
    return fields


def _carry_reviews(db: Session, batch_id: int) -> dict[str, dict]:
    """同一发票在本批次历史版本中的人工处理，用于跨版本跟随。

    优先取最近一次「已处理」的意见（status != pending）；若从未处理过，则沿用最近一行的状态。
    这样先处理正式版、后生成暂存版时，人工意见不会被暂存版的 pending 覆盖。
    """
    rows = db.scalars(
        select(MatchCase)
        .join(MatchRun, MatchRun.id == MatchCase.run_id)
        .where(MatchRun.batch_id == batch_id)
        .order_by(MatchCase.updated_at, MatchCase.id)
    ).all()
    latest_any: dict[str, dict] = {}
    latest_reviewed: dict[str, dict] = {}
    for row in rows:
        entry = {"status": row.status, "reviewer": row.reviewer, "note": row.note}
        latest_any[row.case_key] = entry
        if row.status != CaseStatus.PENDING.value:
            latest_reviewed[row.case_key] = entry
    return {key: latest_reviewed.get(key) or value for key, value in latest_any.items()}


def _change_items(base: dict[str, dict], after: dict[str, dict]) -> list[dict]:
    items: list[dict] = []
    for key in sorted(after):
        now = after[key]
        before = base.get(key)
        if before is None:
            items.append(
                {
                    "case_key": key,
                    "invoice_no": now["invoice_no"],
                    "po_no": now.get("po_no"),
                    "supplier_name": now.get("supplier_name"),
                    "change_kind": ChangeKind.NEW.value,
                    "before": None,
                    "after": now,
                    "changed_fields": {},
                }
            )
            continue
        changed = _differences(before, now)
        if changed:
            items.append(
                {
                    "case_key": key,
                    "invoice_no": now["invoice_no"],
                    "po_no": now.get("po_no"),
                    "supplier_name": now.get("supplier_name"),
                    "change_kind": ChangeKind.CHANGED.value,
                    "before": before,
                    "after": now,
                    "changed_fields": changed,
                }
            )
    for key in sorted(set(base) - set(after)):
        before = base[key]
        items.append(
            {
                "case_key": key,
                "invoice_no": before["invoice_no"],
                "po_no": before.get("po_no"),
                "supplier_name": before.get("supplier_name"),
                "change_kind": ChangeKind.REMOVED.value,
                "before": before,
                "after": None,
                "changed_fields": {},
            }
        )
    return items


def _summary(items: list[dict], total_after: int, total_base: int) -> dict:
    kinds = {kind: 0 for kind in ChangeKind}
    for item in items:
        kinds[item["change_kind"]] = kinds.get(item["change_kind"], 0) + 1
    unaffected = max(0, total_after - kinds[ChangeKind.NEW.value] - kinds[ChangeKind.CHANGED.value])
    affected = kinds[ChangeKind.NEW.value] + kinds[ChangeKind.CHANGED.value] + kinds[ChangeKind.REMOVED.value]
    return {
        "new": kinds[ChangeKind.NEW.value],
        "changed": kinds[ChangeKind.CHANGED.value],
        "unchanged": unaffected,
        "removed": kinds[ChangeKind.REMOVED.value],
        "affected": affected,
        "total_before": total_base,
        "total_after": total_after,
        "items": items,
    }


# ---------------- 核对 ----------------


def _audit_event_count(db: Session, batch_id: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.entity == "match_batch",
                AuditLog.entity_id == str(batch_id),
                AuditLog.action.in_(COUNTED_AUDIT_ACTIONS),
            )
        )
        or 0
    )


def verify_version(db: Session, batch: MatchBatch, version: MatchBatchVersion) -> dict:
    """在切换前核对：水位一致 + 来源单据 / 匹配结果 / 差异工单 / 审计数量四类对齐。"""
    current_wm, current_sources = compute_watermark(db, batch.period)
    counts = version.counts or {}
    snap_sources = counts.get("sources") or {}
    run = db.get(MatchRun, version.run_id) if version.run_id else None

    case_total = 0
    diff_rows = 0
    matched_rows = 0
    if run is not None:
        case_total = db.scalar(select(func.count()).select_from(MatchCase).where(MatchCase.run_id == run.id)) or 0
        diff_rows = (
            db.scalar(
                select(func.count())
                .select_from(MatchCase)
                .where(MatchCase.run_id == run.id, MatchCase.match_status.in_(DIFF_STATUSES))
            )
            or 0
        )
        matched_rows = case_total - diff_rows
    audit_events = _audit_event_count(db, batch.id)

    checks = [
        {
            "key": "watermark",
            "label": "来源水位未变化",
            "expected": version.watermark,
            "actual": current_wm,
            "ok": bool(version.watermark) and current_wm == version.watermark,
        },
        {
            "key": "sources",
            "label": "来源单据数量一致",
            "expected": snap_sources,
            "actual": current_sources,
            "ok": bool(snap_sources) and current_sources == snap_sources,
        },
        {
            "key": "run_counts",
            "label": "匹配结果汇总一致",
            "expected": {
                "cases": counts.get("cases"),
                "matched": counts.get("matched"),
                "diffs": counts.get("diffs"),
            },
            "actual": {"cases": case_total, "matched": matched_rows, "diffs": diff_rows},
            "ok": (
                run is not None
                and counts.get("cases") == case_total
                and counts.get("matched") == matched_rows
                and counts.get("diffs") == diff_rows
                and run.case_count == case_total
                and run.matched_count == matched_rows
                and run.diff_count == diff_rows
            ),
        },
        {
            "key": "diff_cases",
            "label": "差异工单数量一致",
            "expected": counts.get("diffs"),
            "actual": diff_rows,
            "ok": counts.get("diffs") == diff_rows,
        },
        {
            "key": "audit",
            "label": "审计事件数量一致",
            "expected": counts.get("audit_events"),
            "actual": audit_events,
            "ok": counts.get("audit_events") == audit_events,
        },
    ]
    return {
        "ok": all(check["ok"] for check in checks),
        "checked_at": iso_utc(utcnow()),
        "watermark": current_wm,
        "watermark_label": watermark_label(batch.period, current_wm),
        "checks": checks,
    }


# ---------------- 建档 / 重算 ----------------


def open_batch(
    db: Session,
    *,
    period: str,
    batch_key: str,
    operator: str,
    remark: str | None = None,
) -> tuple[MatchBatch, bool]:
    existing = db.scalar(select(MatchBatch).where(MatchBatch.batch_key == batch_key))
    if existing is not None:
        if existing.period != period:
            raise AppError(
                "CONFLICT", 409, {"batch_key": batch_key, "period": existing.period, "requested": period}
            )
        return existing, False

    watermark, counts = compute_watermark(db, period)
    batch = MatchBatch(
        batch_no=next_batch_no(db, period),
        batch_key=batch_key,
        period=period,
        status=BatchStatus.OPEN.value,
        watermark=watermark,
        source_counts=counts,
        remark=remark,
        created_by=operator,
    )
    db.add(batch)
    db.flush()
    audit_service.record(
        db,
        actor_email=operator,
        actor_role="system",
        action="batch.open",
        entity="match_batch",
        entity_id=batch.id,
        detail={
            "batch_no": batch.batch_no,
            "batch_key": batch_key,
            "period": period,
            "watermark": watermark,
            "sources": counts,
        },
        layer="domain",
    )
    db.flush()
    return batch, True


def _supersede_staging(db: Session, batch: MatchBatch, staging: MatchBatchVersion | None) -> None:
    if staging is not None and staging.status == BatchVersionStatus.STAGING.value:
        staging.status = BatchVersionStatus.SUPERSEDED.value
    if batch.staging_version_id:
        batch.staging_version_id = None


def _version_run_ok(db: Session, version: MatchBatchVersion) -> bool:
    if version.run_id is None:
        return False
    run = db.get(MatchRun, version.run_id)
    return run is not None and run.status in ("success", "partial")


def recompute(
    db: Session,
    batch: MatchBatch,
    *,
    operator: str,
    trigger: str = "manual",
    force: bool = False,
) -> tuple[MatchBatchVersion, bool]:
    """对批次账期重算；返回 (版本, 是否复用已有结果)。"""
    if batch.status == BatchStatus.CLOSED.value:
        raise AppError("CONFLICT", 409, {"batch_id": batch.id, "reason": "批次已关账"})

    wm, sources = compute_watermark(db, batch.period)
    official = (
        db.get(MatchBatchVersion, batch.official_version_id) if batch.official_version_id else None
    )
    staging = db.get(MatchBatchVersion, batch.staging_version_id) if batch.staging_version_id else None
    latest = db.scalar(
        select(MatchBatchVersion)
        .where(MatchBatchVersion.batch_id == batch.id)
        .order_by(MatchBatchVersion.version_no.desc())
        .limit(1)
    )

    # 幂等：同一水位下，待切换版本 / 正式版直接复用，不新增运行或工单。
    # 只有「跑成功」的版本才复用；上次跑失败的版本重试会重建。
    if not force:
        if (
            staging is not None
            and staging.watermark == wm
            and staging.status == BatchVersionStatus.STAGING.value
            and _version_run_ok(db, staging)
        ):
            if batch.status == BatchStatus.FAILED.value:
                # 切换失败后的重试：状态回到待切换，暂存版仍在
                batch.status = BatchStatus.STAGING.value
                db.flush()
            return staging, True
        if (
            official is not None
            and official.watermark == wm
            and official.status == BatchVersionStatus.OFFICIAL.value
            and _version_run_ok(db, official)
        ):
            return official, True

    # 对比基准：上一正式版；若还没有正式版，则对比本批次最近的版本（首次即基线）
    base_version = official or staging or latest
    base_map = _base_cases(db, base_version)
    carry = _carry_reviews(db, batch.id)
    version_no = next_version_no(db, batch.id)

    # 之前没切换的暂存版已被新水位取代：保留记录，标 superseded，不再允许切换
    _supersede_staging(db, batch, staging)

    version = MatchBatchVersion(
        batch_id=batch.id,
        version_no=version_no,
        status=BatchVersionStatus.STAGING.value,
        watermark=wm,
        watermark_detail=sources,
        created_by=operator,
    )
    db.add(version)
    db.flush()
    audit_service.record(
        db,
        actor_email=operator,
        actor_role="system",
        action="batch.recompute",
        entity="match_batch",
        entity_id=batch.id,
        detail={
            "batch_no": batch.batch_no,
            "version_no": version_no,
            "trigger": trigger,
            "watermark": wm,
            "sources": sources,
            "base_version_no": base_version.version_no if base_version else None,
        },
        layer="domain",
    )
    db.flush()
    # 审计事件数在生成快照前固定，切换前核对必须与它一致
    audit_events = _audit_event_count(db, batch.id)

    run = MatchRun(
        run_no=match_service.next_run_no(db, batch.period),
        period=batch.period,
        trigger=trigger,
        status="running",
        operator_email=operator,
        batch_id=batch.id,
        version_id=version.id,
        watermark=wm,
    )
    db.add(run)
    db.flush()
    match_service.execute_run(
        db,
        run,
        base_cases=base_map,
        carry=carry,
    )
    version.run_id = run.id
    db.flush()

    after_rows = db.scalars(select(MatchCase).where(MatchCase.run_id == run.id)).all()
    after_map = {row.case_key: _case_snapshot(row) for row in after_rows}
    if base_version is None or not base_map:
        # 首个版本没有对比基准，作为基线快照：全部记 unchanged，不制造「新增」噪音
        items = []
        summary = _summary([], total_after=len(after_map), total_base=0)
        summary.update({"new": 0, "unchanged": len(after_map), "affected": 0, "baseline": True})
    else:
        items = _change_items(base_map, after_map)
        summary = _summary(items, total_after=len(after_map), total_base=len(base_map))

    counts = {
        "cases": len(after_map),
        "matched": run.matched_count,
        "diffs": run.diff_count,
        "rejected": run.rejected_count,
        "sources": sources,
        "audit_events": audit_events,
    }
    version.counts = counts
    version.change_summary = summary
    db.flush()
    version.verify_snapshot = verify_version(db, batch, version)

    batch.staging_version_id = version.id
    batch.status = BatchStatus.STAGING.value
    batch.watermark = wm
    batch.source_counts = sources
    batch.updated_at = utcnow()
    db.flush()
    return version, False


def open_and_recompute(
    db: Session,
    *,
    period: str | None,
    batch_key: str | None,
    operator: str,
    trigger: str = "manual",
    remark: str | None = None,
    force: bool = False,
) -> tuple[MatchBatch, MatchBatchVersion, bool]:
    period = period or match_service.default_period(db)
    batch_key = (batch_key or "").strip() or f"period:{period}"
    batch, created = open_batch(db, period=period, batch_key=batch_key, operator=operator, remark=remark)
    version, reused = recompute(db, batch, operator=operator, trigger=trigger, force=force)
    return batch, version, reused and not created


# ---------------- 切换 / 回滚 ----------------


def _switch_mutation(
    db: Session,
    batch: MatchBatch,
    version: MatchBatchVersion,
    previous: MatchBatchVersion | None,
    *,
    operator: str,
) -> None:
    now = utcnow()
    version.status = BatchVersionStatus.OFFICIAL.value
    version.activated_at = now
    version.error = None
    if previous is not None and previous.id != version.id:
        previous.status = BatchVersionStatus.SUPERSEDED.value
    batch.official_version_id = version.id
    batch.staging_version_id = None
    batch.status = BatchStatus.OFFICIAL.value
    batch.watermark = version.watermark
    batch.source_counts = (version.counts or {}).get("sources") or batch.source_counts
    batch.updated_at = now
    audit_service.record(
        db,
        actor_email=operator,
        actor_role="system",
        action="batch.switch",
        entity="match_batch",
        entity_id=batch.id,
        detail={
            "batch_no": batch.batch_no,
            "version_no": version.version_no,
            "previous_version_no": previous.version_no if previous else None,
            "watermark": version.watermark,
            "counts": {
                "cases": (version.counts or {}).get("cases"),
                "diffs": (version.counts or {}).get("diffs"),
                "affected": (version.change_summary or {}).get("affected"),
            },
        },
        layer="domain",
    )
    db.flush()


def switch_version(
    db: Session,
    batch: MatchBatch,
    *,
    version_id: int | None = None,
    operator: str,
    fail_after_mutation: bool = False,
) -> dict:
    """核对并切换正式版。失败时恢复上一正式版与人工处理，不丢记录。"""
    target_id = version_id or batch.staging_version_id
    if not target_id:
        raise AppError("CONFLICT", 409, {"batch_id": batch.id, "reason": "批次没有待切换版本"})
    version = db.get(MatchBatchVersion, target_id)
    if version is None or version.batch_id != batch.id:
        raise AppError("NOT_FOUND", 404, {"entity": "match_batch_version", "id": target_id})
    if version.status != BatchVersionStatus.STAGING.value:
        raise AppError(
            "CONFLICT", 409, {"version_id": version.id, "status": version.status, "reason": "只有暂存版可切换"}
        )

    verification = verify_version(db, batch, version)
    version.verify_snapshot = verification
    db.flush()
    if not verification["ok"]:
        audit_service.record(
            db,
            actor_email=operator,
            actor_role="system",
            action="batch.verify_failed",
            entity="match_batch",
            entity_id=batch.id,
            detail={
                "batch_no": batch.batch_no,
                "version_no": version.version_no,
                "failed": [check["key"] for check in verification["checks"] if not check["ok"]],
            },
            layer="domain",
        )
        db.flush()
        raise AppError(
            "CONFLICT",
            409,
            {
                "batch_id": batch.id,
                "version_id": version.id,
                "reason": "水位核对未通过，未切换正式版",
                "verification": verification,
            },
        )

    previous_id = batch.official_version_id
    previous = db.get(MatchBatchVersion, previous_id) if previous_id else None
    savepoint = db.begin_nested()
    try:
        _switch_mutation(db, batch, version, previous, operator=operator)
        if fail_after_mutation:
            raise RuntimeError("模拟切换失败（事务内异常）")
        savepoint.commit()
    except Exception as exc:  # noqa: BLE001 - 失败必须回滚到上一正式版
        savepoint.rollback()
        # savepoint 回滚后重新加载，确保内存对象与库里保持一致
        db.expire_all()
        batch = get_batch(db, batch.id)
        version = db.get(MatchBatchVersion, target_id)
        version.error = f"切换失败：{exc}"
        batch.status = BatchStatus.FAILED.value
        batch.updated_at = utcnow()
        audit_service.record(
            db,
            actor_email=operator,
            actor_role="system",
            action="batch.switch_failed",
            entity="match_batch",
            entity_id=batch.id,
            detail={
                "batch_no": batch.batch_no,
                "version_no": version.version_no,
                "restored_version_id": batch.official_version_id,
                "error": str(exc)[:300],
            },
            layer="domain",
        )
        db.flush()
        raise AppError(
            "CONFLICT",
            409,
            {
                "batch_id": batch.id,
                "version_id": version.id,
                "reason": "切换失败，已恢复上一正式版",
                "restored_version_id": batch.official_version_id,
                "error": str(exc)[:300],
            },
        ) from None

    return {
        "batch": serialize_batch(db, batch),
        "version": serialize_version(version, batch=batch),
        "previous_version_id": previous.id if previous else None,
        "verification": verification,
    }


def rollback(db: Session, batch: MatchBatch, *, operator: str, version_id: int | None = None) -> dict:
    """显式回滚到上一正式版（切换失败后的兜底 / 事后纠错），记录与处理意见原样保留。"""
    current = db.get(MatchBatchVersion, batch.official_version_id) if batch.official_version_id else None
    if current is None:
        raise AppError("CONFLICT", 409, {"batch_id": batch.id, "reason": "批次尚无正式版"})
    if version_id:
        target = db.get(MatchBatchVersion, version_id)
    else:
        target = db.scalar(
            select(MatchBatchVersion)
            .where(
                MatchBatchVersion.batch_id == batch.id,
                MatchBatchVersion.status.in_(
                    [BatchVersionStatus.SUPERSEDED.value, BatchVersionStatus.ROLLED_BACK.value]
                ),
                MatchBatchVersion.id != current.id,
            )
            .order_by(MatchBatchVersion.version_no.desc())
            .limit(1)
        )
    if target is None or target.batch_id != batch.id:
        raise AppError("NOT_FOUND", 404, {"entity": "match_batch_version", "id": version_id})
    if target.id == current.id:
        raise AppError("CONFLICT", 409, {"version_id": target.id, "reason": "已是当前正式版"})

    now = utcnow()
    current.status = BatchVersionStatus.ROLLED_BACK.value
    target.status = BatchVersionStatus.OFFICIAL.value
    target.activated_at = now
    batch.official_version_id = target.id
    batch.status = BatchStatus.STAGING.value if batch.staging_version_id else BatchStatus.OFFICIAL.value
    batch.watermark = target.watermark
    batch.source_counts = (target.counts or {}).get("sources") or batch.source_counts
    batch.updated_at = now
    audit_service.record(
        db,
        actor_email=operator,
        actor_role="system",
        action="batch.rollback",
        entity="match_batch",
        entity_id=batch.id,
        detail={
            "batch_no": batch.batch_no,
            "from_version_no": current.version_no,
            "to_version_no": target.version_no,
            "watermark": target.watermark,
        },
        layer="domain",
    )
    db.flush()
    return {"batch": serialize_batch(db, batch), "version": serialize_version(target, batch=batch)}


def changes(
    db: Session,
    batch: MatchBatch,
    *,
    version_id: int | None = None,
    change_kind: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    version = None
    if version_id:
        version = db.get(MatchBatchVersion, version_id)
    elif batch.staging_version_id:
        version = db.get(MatchBatchVersion, batch.staging_version_id)
    elif batch.official_version_id:
        version = db.get(MatchBatchVersion, batch.official_version_id)
    if version is None or version.batch_id != batch.id:
        raise AppError("NOT_FOUND", 404, {"entity": "match_batch_version", "id": version_id})

    summary = version.change_summary or {}
    items = summary.get("items") or []
    if (
        not items
        and not summary.get("baseline")
        and version.status in (BatchVersionStatus.OFFICIAL.value, BatchVersionStatus.SUPERSEDED.value)
    ):
        # 历史版本 / 采用旧运行建档时按需重算前后差异
        base = None
        previous = db.scalar(
            select(MatchBatchVersion)
            .where(MatchBatchVersion.batch_id == batch.id, MatchBatchVersion.version_no < version.version_no)
            .order_by(MatchBatchVersion.version_no.desc())
            .limit(1)
        )
        base = previous
        base_map = _base_cases(db, base)
        after_map = _base_cases(db, version)
        items = _change_items(base_map, after_map)
        summary = _summary(items, len(after_map), len(base_map))
    if change_kind:
        items = [item for item in items if item["change_kind"] == change_kind]
    total = len(items)
    page = items[offset : offset + limit]
    for item in page:
        item["change_kind_label"] = CHANGE_KIND_LABELS.get(item["change_kind"], item["change_kind"])
    return {
        "batch_id": batch.id,
        "version": serialize_version(version, batch=batch),
        "summary": {key: value for key, value in summary.items() if key != "items"},
        "items": page,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def official_case_filter(db: Session):
    """工作台默认只看正式版（以及尚无批次的历史运行）的工单。"""
    official_ids = select(MatchBatchVersion.id).where(
        MatchBatchVersion.status == BatchVersionStatus.OFFICIAL.value
    )
    return or_(MatchCase.version_id.is_(None), MatchCase.version_id.in_(official_ids))


# ---------------- seed 兼容 ----------------


def ensure_seed_batch(
    db: Session,
    *,
    period: str,
    seed_key: str,
    operator: str,
) -> MatchRun:
    """seed 幂等：已有批次直接复用；旧库里的 seed 运行采用为正式版，不重复建运行。"""
    batch = db.scalar(select(MatchBatch).where(MatchBatch.batch_key == seed_key))
    if batch is None:
        legacy = db.scalar(select(MatchRun).where(MatchRun.seed_key == seed_key))
        if legacy is not None:
            version = _adopt_legacy_run(db, legacy=legacy, seed_key=seed_key, operator=operator)
            run = db.get(MatchRun, version.run_id)
            assert run is not None
            return run
        batch, _ = open_batch(db, period=period, batch_key=seed_key, operator=operator, remark="初始化批次")
        version, _ = recompute(db, batch, operator=operator, trigger="seed")
        switch_version(db, batch, version_id=version.id, operator=operator)
        run = db.get(MatchRun, version.run_id)
        assert run is not None
        return run

    if batch.official_version_id:
        official = db.get(MatchBatchVersion, batch.official_version_id)
        run = db.get(MatchRun, official.run_id) if official and official.run_id else None
        if run is not None:
            return run
    batch, version, _ = open_and_recompute(
        db, period=period, batch_key=seed_key, operator=operator, trigger="seed"
    )
    switch_version(db, batch, version_id=version.id, operator=operator)
    run = db.get(MatchRun, version.run_id)
    assert run is not None
    return run


def _adopt_legacy_run(db: Session, *, legacy: MatchRun, seed_key: str, operator: str) -> MatchBatchVersion:
    wm, sources = compute_watermark(db, legacy.period)
    batch, _ = open_batch(
        db, period=legacy.period, batch_key=seed_key, operator=operator, remark="采用历史初始化运行"
    )
    version = MatchBatchVersion(
        batch_id=batch.id,
        version_no=1,
        run_id=legacy.id,
        status=BatchVersionStatus.OFFICIAL.value,
        watermark=wm,
        watermark_detail=sources,
        created_by=operator,
        activated_at=utcnow(),
    )
    db.add(version)
    db.flush()
    legacy.batch_id = batch.id
    legacy.version_id = version.id
    legacy.watermark = wm
    cases = db.scalars(select(MatchCase).where(MatchCase.run_id == legacy.id)).all()
    for case in cases:
        case.batch_id = batch.id
        case.version_id = version.id
        # 历史运行即基线快照：不制造「新增」噪音
        case.change_kind = ChangeKind.UNCHANGED.value
    total = len(cases)
    diff_rows = sum(1 for case in cases if case.match_status in DIFF_STATUSES)
    counts = {
        "cases": total,
        "matched": total - diff_rows,
        "diffs": diff_rows,
        "rejected": legacy.rejected_count,
        "sources": sources,
        "audit_events": _audit_event_count(db, batch.id),
    }
    summary = _summary([], total_after=total, total_base=0)
    summary["new"] = 0
    summary["unchanged"] = total
    summary["affected"] = 0
    summary["total_before"] = 0
    summary["baseline"] = True
    version.counts = counts
    version.change_summary = summary
    db.flush()
    version.verify_snapshot = verify_version(db, batch, version)
    batch.official_version_id = version.id
    batch.status = BatchStatus.OFFICIAL.value
    batch.watermark = wm
    batch.source_counts = sources
    db.flush()
    return version


def batch_status_options() -> list[dict]:
    return [{"value": key, "label": label} for key, label in BATCH_STATUS_LABELS.items()]


def batch_version_status_options() -> list[dict]:
    return [{"value": key, "label": label} for key, label in BATCH_VERSION_STATUS_LABELS.items()]


def change_kind_options() -> list[dict]:
    return [{"value": key, "label": label} for key, label in CHANGE_KIND_LABELS.items()]


__all__ = [
    "compute_watermark",
    "open_batch",
    "open_and_recompute",
    "recompute",
    "switch_version",
    "rollback",
    "verify_version",
    "changes",
    "serialize_batch",
    "serialize_version",
    "list_batches",
    "get_batch",
    "ensure_seed_batch",
    "official_case_filter",
    "batch_status_options",
    "batch_version_status_options",
    "change_kind_options",
]
