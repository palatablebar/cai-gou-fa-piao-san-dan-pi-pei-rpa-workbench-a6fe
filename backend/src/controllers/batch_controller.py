"""账期批次控制器：建档/重算、水位核对、切换正式版、回滚、前后差异。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.models.match_batch import MatchBatchVersion
from src.services import audit_service, batch_service
from src.utils.errors import AppError


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def list_batches(db: Session, **filters) -> dict:
    return batch_service.list_batches(db, **filters)


def get_batch(db: Session, batch_id: int) -> dict:
    batch = batch_service.get_batch(db, batch_id)
    payload = batch_service.serialize_batch(db, batch)
    latest = batch.staging_version_id or batch.official_version_id
    if latest:
        version = db.get(MatchBatchVersion, latest)
        payload["verification"] = batch_service.verify_version(db, batch, version)
    return payload


def create_batch(db: Session, payload: dict, principal: dict, request: Request) -> dict:
    batch, version, reused = batch_service.open_and_recompute(
        db,
        period=payload.get("period"),
        batch_key=payload.get("batch_key"),
        operator=principal["email"],
        trigger=payload.get("trigger") or "manual",
        remark=payload.get("remark"),
        force=bool(payload.get("force")),
    )
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="batch.submit",
        entity="match_batch",
        entity_id=batch.id,
        detail={
            "batch_no": batch.batch_no,
            "batch_key": batch.batch_key,
            "period": batch.period,
            "reused": reused,
            "version_no": version.version_no,
            "watermark": version.watermark,
        },
        ip=_ip(request),
    )
    db.commit()
    return {
        "batch": batch_service.serialize_batch(db, batch),
        "version": batch_service.serialize_version(version, batch=batch),
        "reused": reused,
    }


def recompute(db: Session, batch_id: int, payload: dict, principal: dict, request: Request) -> dict:
    batch = batch_service.get_batch(db, batch_id)
    version, reused = batch_service.recompute(
        db,
        batch,
        operator=principal["email"],
        trigger=payload.get("trigger") or "manual",
        force=bool(payload.get("force", True)),
    )
    db.commit()
    return {
        "batch": batch_service.serialize_batch(db, batch),
        "version": batch_service.serialize_version(version, batch=batch),
        "reused": reused,
    }


def verify(db: Session, batch_id: int, version_id: int | None = None) -> dict:
    batch = batch_service.get_batch(db, batch_id)
    target = version_id or batch.staging_version_id or batch.official_version_id
    if target is None:
        raise AppError("CONFLICT", 409, {"batch_id": batch.id, "reason": "批次还没有版本"})
    version = db.get(MatchBatchVersion, target)
    if version is None or version.batch_id != batch.id:
        raise AppError("NOT_FOUND", 404, {"entity": "match_batch_version", "id": target})
    return {
        "batch_id": batch.id,
        "version": batch_service.serialize_version(version, batch=batch),
        "verification": batch_service.verify_version(db, batch, version),
    }


def switch(db: Session, batch_id: int, payload: dict, principal: dict, request: Request) -> dict:
    batch = batch_service.get_batch(db, batch_id)
    try:
        result = batch_service.switch_version(
            db,
            batch,
            version_id=payload.get("version_id"),
            operator=principal["email"],
            fail_after_mutation=bool(payload.get("simulate_failure")),
        )
    except AppError as exc:
        db.commit()
        raise exc
    db.commit()
    return result


def rollback(db: Session, batch_id: int, payload: dict, principal: dict, request: Request) -> dict:
    batch = batch_service.get_batch(db, batch_id)
    result = batch_service.rollback(
        db, batch, operator=principal["email"], version_id=payload.get("version_id")
    )
    db.commit()
    return result


def changes(
    db: Session,
    batch_id: int,
    *,
    version_id: int | None = None,
    change_kind: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    batch = batch_service.get_batch(db, batch_id)
    return batch_service.changes(
        db, batch, version_id=version_id, change_kind=change_kind, limit=limit, offset=offset
    )


def options() -> dict:
    return {
        "statuses": batch_service.batch_status_options(),
        "version_statuses": batch_service.batch_version_status_options(),
        "change_kinds": batch_service.change_kind_options(),
    }
