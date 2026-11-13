"""匹配运行与差异工单控制器。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.constants.enums import Role
from src.services import audit_service, match_service


def create_run(db: Session, payload: dict, principal: dict, request: Request) -> dict:
    run = match_service.create_and_execute(
        db,
        period=payload.get("period"),
        trigger=payload.get("trigger") or "manual",
        operator_email=principal["email"],
    )
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="run.create",
        entity="match_run",
        entity_id=run.id,
        detail={"run_no": run.run_no, "period": run.period, "status": run.status},
        ip=request.client.host if request.client else None,
    )
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="run.complete",
        entity="match_run",
        entity_id=run.id,
        detail={
            "matched": run.matched_count,
            "diffs": run.diff_count,
            "cases": run.case_count,
            "rejected": run.rejected_count,
        },
        layer="domain",
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return match_service.serialize_run(run)


def list_runs(db: Session, **filters) -> dict:
    return match_service.list_runs(db, **filters)


def get_run(db: Session, run_id: int) -> dict:
    return match_service.serialize_run(match_service.get_run(db, run_id))


def list_cases(db: Session, principal: dict, **filters) -> dict:
    filters["show_price"] = principal["role"] != Role.VIEWER.value
    return match_service.list_cases(db, **filters)


def get_case(db: Session, case_id: int, principal: dict) -> dict:
    case = match_service.get_case(db, case_id)
    return match_service.serialize_case(case, show_price=principal["role"] != Role.VIEWER.value)


def review_case(db: Session, case_id: int, payload: dict, principal: dict, request: Request) -> dict:
    case = match_service.get_case(db, case_id)
    before = case.status
    match_service.review_case(
        db,
        case,
        status=payload["status"],
        note=payload.get("note"),
        reviewer=principal["email"],
    )
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="case.review",
        entity="match_case",
        entity_id=case.id,
        detail={
            "invoice_no": case.invoice_no,
            "from": before,
            "to": case.status,
            "diff_amount_cents": case.diff_amount_cents,
        },
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return match_service.serialize_case(case)


def adjustments(db: Session) -> dict:
    return match_service.adjustments(db)
