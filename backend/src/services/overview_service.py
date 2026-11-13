"""总览：本期单据量、差异结构、最近运行、worker 心跳。"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.constants.enums import (
    BatchVersionStatus,
    CASE_STATUS_LABELS,
    CASE_STATUS_ORDER,
    DIFF_STATUSES,
    DIFF_TYPE_LABELS,
    MATCH_STATUS_LABELS,
    MATCH_STATUS_ORDER,
    RUN_STATUS_LABELS,
    CaseStatus,
    InvoiceStatus,
    MatchStatus,
)
from src.models.goods_receipt import GoodsReceipt
from src.models.invoice import Invoice
from src.models.match_batch import MatchBatch, MatchBatchVersion
from src.models.match_case import MatchCase
from src.models.match_run import MatchRun
from src.models.purchase_order import PurchaseOrder
from src.models.supplier import Supplier
from src.services.match_service import default_period
from src.services.normalization_service import yuan_from_cents
from src.utils.timeutil import local_now, utcnow


def worker_alive() -> bool:
    try:
        import time

        import redis

        client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2)
        value = client.get(f"{settings.app_name}:worker:heartbeat")
        return bool(value) and (time.time() - float(value)) < 120
    except Exception:
        return False


def overview(db: Session) -> dict:
    suppliers_total = db.scalar(select(func.count()).select_from(Supplier)) or 0
    orders_total = db.scalar(select(func.count()).select_from(PurchaseOrder)) or 0
    receipts_total = db.scalar(select(func.count()).select_from(GoodsReceipt)) or 0
    invoices_total = (
        db.scalar(select(func.count()).select_from(Invoice).where(Invoice.status == InvoiceStatus.VALID.value)) or 0
    )
    rejected_total = (
        db.scalar(select(func.count()).select_from(Invoice).where(Invoice.status == InvoiceStatus.REJECTED.value)) or 0
    )
    runs_total = db.scalar(select(func.count()).select_from(MatchRun)) or 0
    latest_run = db.scalar(select(MatchRun).order_by(MatchRun.id.desc()).limit(1))
    # 关账口径取正式版运行：暂存版（待切换）不进入总览统计
    official_run = db.scalar(
        select(MatchRun)
        .join(MatchBatchVersion, MatchBatchVersion.run_id == MatchRun.id)
        .where(MatchBatchVersion.status == BatchVersionStatus.OFFICIAL.value)
        .order_by(MatchRun.id.desc())
        .limit(1)
    )
    if official_run is not None:
        latest_run = official_run
    run_id = latest_run.id if latest_run else None

    case_stmt = select(MatchCase).where(MatchCase.match_status.in_(DIFF_STATUSES))
    if run_id:
        case_stmt = case_stmt.where(MatchCase.run_id == run_id)
    cases = db.scalars(case_stmt).all()
    all_cases_stmt = select(MatchCase)
    if run_id:
        all_cases_stmt = all_cases_stmt.where(MatchCase.run_id == run_id)
    all_cases = db.scalars(all_cases_stmt).all()
    by_status = {key: 0 for key in MATCH_STATUS_ORDER}
    by_type = {key: 0 for key in DIFF_TYPE_LABELS}
    by_case_status = {key: 0 for key in CASE_STATUS_ORDER}
    total_diff_cents = 0
    for case in all_cases:
        by_status[case.match_status] = by_status.get(case.match_status, 0) + 1
    for case in cases:
        by_type[case.diff_type] = by_type.get(case.diff_type, 0) + 1
        by_case_status[case.status] = by_case_status.get(case.status, 0) + 1
        total_diff_cents += int(case.diff_amount_cents or 0)

    pending_total = sum(1 for case in cases if case.status == CaseStatus.PENDING.value)
    matched_total = sum(1 for case in all_cases if case.match_status == MatchStatus.MATCHED.value)

    since = utcnow() - timedelta(days=7)
    recent_runs = db.scalars(select(MatchRun).where(MatchRun.started_at >= since)).all()
    today = local_now().date()
    trend = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        count = sum(
            1
            for run in recent_runs
            if run.started_at
            and (run.started_at + timedelta(minutes=settings.app_timezone_offset_minutes)).date() == day
        )
        trend.append({"date": day.isoformat(), "runs": count})

    period = latest_run.period if latest_run else default_period(db)
    batch = db.scalar(
        select(MatchBatch).where(MatchBatch.period == period).order_by(MatchBatch.id.desc()).limit(1)
    )
    batch_payload = None
    if batch is not None:
        official = db.get(MatchBatchVersion, batch.official_version_id) if batch.official_version_id else None
        staging = db.get(MatchBatchVersion, batch.staging_version_id) if batch.staging_version_id else None
        batch_payload = {
            "id": batch.id,
            "batch_no": batch.batch_no,
            "period": batch.period,
            "status": batch.status,
            "watermark_label": batch.watermark_label,
            "source_counts": batch.source_counts or {},
            "official_version_no": official.version_no if official else None,
            "official_diffs": (official.counts or {}).get("diffs") if official else None,
            "staging_version_no": staging.version_no if staging else None,
            "staging_affected": (staging.change_summary or {}).get("affected") if staging else None,
        }
    return {
        "period": period,
        "suppliers_total": suppliers_total,
        "orders_total": orders_total,
        "receipts_total": receipts_total,
        "invoices_total": invoices_total,
        "rejected_total": rejected_total,
        "runs_total": runs_total,
        "cases_total": len(all_cases),
        "pending_total": pending_total,
        "matched_total": matched_total,
        "diff_total": len(cases),
        "diff_amount_total": yuan_from_cents(total_diff_cents),
        "worker_alive": worker_alive(),
        "batch": batch_payload,
        "latest_run": {
            "id": latest_run.id,
            "run_no": latest_run.run_no,
            "period": latest_run.period,
            "status": latest_run.status,
            "status_label": RUN_STATUS_LABELS.get(latest_run.status, latest_run.status),
            "started_at": latest_run.started_at.isoformat(timespec="seconds") + "Z" if latest_run.started_at else None,
            "matched_count": latest_run.matched_count,
            "diff_count": latest_run.diff_count,
            "case_count": latest_run.case_count,
        }
        if latest_run
        else None,
        "status_structure": [
            {"key": key, "label": MATCH_STATUS_LABELS[key], "count": by_status.get(key, 0)}
            for key in MATCH_STATUS_ORDER
        ],
        "type_structure": [
            {"key": key, "label": label, "count": by_type.get(key, 0)} for key, label in DIFF_TYPE_LABELS.items()
        ],
        "case_structure": [
            {"key": key, "label": CASE_STATUS_LABELS[key], "count": by_case_status.get(key, 0)}
            for key in CASE_STATUS_ORDER
        ],
        "trend": trend,
    }
