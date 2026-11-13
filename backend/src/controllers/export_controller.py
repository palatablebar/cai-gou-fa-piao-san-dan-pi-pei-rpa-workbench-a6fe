"""导出控制器：CSV 响应 + 审计。"""
from __future__ import annotations

from fastapi import Request, Response
from sqlalchemy.orm import Session

from src.services import audit_service, export_service
from src.utils.csv_export import csv_response_headers


def cases_csv(
    db: Session,
    run_id: int | None,
    status: str | None,
    principal: dict,
    request: Request,
    batch_id: int | None = None,
) -> Response:
    content = export_service.cases_csv(db, run_id, status, batch_id=batch_id)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="export.cases",
        entity="match_case",
        entity_id=run_id,
        detail={"bytes": len(content), "status": status, "batch_id": batch_id},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers=csv_response_headers("match-cases.csv"),
    )


def adjustments_csv(db: Session, principal: dict, request: Request) -> Response:
    content = export_service.adjustments_csv(db)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="export.cases",
        entity="match_case",
        entity_id=None,
        detail={"bytes": len(content), "kind": "adjustments"},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers=csv_response_headers("adjustments.csv"),
    )


def runs_csv(db: Session, principal: dict, request: Request) -> Response:
    content = export_service.runs_csv(db)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="export.runs",
        entity="match_run",
        entity_id=None,
        detail={"bytes": len(content)},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers=csv_response_headers("match-runs.csv"),
    )
