"""导出服务：差异清单 / 匹配运行 / 调整单 CSV（UTF-8 BOM，Excel 直接打开）。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.constants.enums import (
    CASE_STATUS_LABELS,
    DIFF_STATUSES,
    MATCH_STATUS_LABELS,
    RUN_STATUS_LABELS,
    SUGGESTION_LABELS,
    TRIGGER_LABELS,
    DIFF_TYPE_LABELS,
    tax_rate_label,
)
from src.models.match_case import MatchCase
from src.models.match_run import MatchRun
from src.services.normalization_service import yuan_from_cents
from src.utils.csv_export import to_csv

CSV_HEADERS = [
    "账期",
    "运行编号",
    "发票号",
    "采集批次",
    "采购订单",
    "供应商",
    "物料编码",
    "匹配判定",
    "差异类别",
    "发票金额(元)",
    "应付金额(元)",
    "差异额(元)",
    "处理建议",
    "处理状态",
    "处理人",
    "备注",
]


def _case_row(case: MatchCase, run_no: str, period: str) -> list[object]:
    return [
        period,
        run_no,
        case.invoice_no,
        case.import_batch,
        case.po_no or "",
        case.supplier_name,
        case.material_code or "",
        MATCH_STATUS_LABELS.get(case.match_status, case.match_status),
        DIFF_TYPE_LABELS.get(case.diff_type, case.diff_type),
        f"{yuan_from_cents(case.invoice_amount_cents):.2f}",
        f"{yuan_from_cents(case.payable_cents):.2f}",
        f"{yuan_from_cents(case.diff_amount_cents):.2f}",
        SUGGESTION_LABELS.get(case.suggestion, case.suggestion),
        CASE_STATUS_LABELS.get(case.status, case.status),
        case.reviewer or "",
        case.note or "",
    ]


def cases_csv(db: Session, run_id: int | None = None, status: str | None = None) -> bytes:
    """差异清单：默认只导差异工单（三单一致的行不进应付处理清单）。"""
    runs = {run.id: run for run in db.scalars(select(MatchRun)).all()}
    stmt = select(MatchCase).where(MatchCase.match_status.in_(DIFF_STATUSES))
    if run_id:
        stmt = stmt.where(MatchCase.run_id == run_id)
    if status:
        stmt = stmt.where(MatchCase.status == status)
    cases = db.scalars(stmt.order_by(MatchCase.run_id, MatchCase.id)).all()
    rows = [
        _case_row(case, runs[case.run_id].run_no if case.run_id in runs else "", runs[case.run_id].period if case.run_id in runs else "")
        for case in cases
    ]
    return to_csv(CSV_HEADERS, rows)


def adjustments_csv(db: Session) -> bytes:
    headers = ["账期", "发票号", "采购订单", "供应商", "匹配判定", "差异额(元)", "处理建议", "处理状态", "处理人", "备注"]
    runs = {run.id: run for run in db.scalars(select(MatchRun)).all()}
    cases = db.scalars(
        select(MatchCase).where(MatchCase.status != "pending").order_by(MatchCase.updated_at.desc())
    ).all()
    rows = [
        [
            runs[case.run_id].period if case.run_id in runs else "",
            case.invoice_no,
            case.po_no or "",
            case.supplier_name,
            MATCH_STATUS_LABELS.get(case.match_status, case.match_status),
            f"{yuan_from_cents(case.diff_amount_cents):.2f}",
            SUGGESTION_LABELS.get(case.suggestion, case.suggestion),
            CASE_STATUS_LABELS.get(case.status, case.status),
            case.reviewer or "",
            case.note or "",
        ]
        for case in cases
    ]
    return to_csv(headers, rows)


def runs_csv(db: Session) -> bytes:
    headers = ["运行编号", "账期", "触发方式", "状态", "原始发票", "归一失败", "入池", "一致", "差异", "操作人", "开始时间", "结束时间"]
    rows = [
        [
            run.run_no,
            run.period,
            TRIGGER_LABELS.get(run.trigger, run.trigger),
            RUN_STATUS_LABELS.get(run.status, run.status),
            run.invoice_raw_count,
            run.rejected_count,
            run.case_count,
            run.matched_count,
            run.diff_count,
            run.operator_email,
            run.started_at.strftime("%Y-%m-%d %H:%M") if run.started_at else "",
            run.finished_at.strftime("%Y-%m-%d %H:%M") if run.finished_at else "",
        ]
        for run in db.scalars(select(MatchRun).order_by(MatchRun.id)).all()
    ]
    return to_csv(headers, rows)
