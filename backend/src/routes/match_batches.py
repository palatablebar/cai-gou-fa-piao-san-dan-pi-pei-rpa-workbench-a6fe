from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.enums import Role
from src.constants.roles import BATCH_SWITCH_ROLES, REVIEW_ROLES, RUN_CREATE_ROLES
from src.controllers import batch_controller
from src.middlewares.rbac import READ_ROLES, require_roles
from src.schemas.match import BatchCreateIn, BatchRecomputeIn, BatchRollbackIn, BatchSwitchIn
from src.utils.pagination import page_params

router = APIRouter(prefix="/match-batches", tags=["match-batches"])


@router.get("")
def list_batches(
    period: str | None = None,
    status: str | None = None,
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    page = page_params(limit, offset)
    return batch_controller.list_batches(db, period=period, status=status, limit=page.limit, offset=page.offset)


@router.get("/options")
def options(
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return batch_controller.options()


@router.post("", status_code=201)
def create_batch(
    payload: BatchCreateIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*RUN_CREATE_ROLES)),
) -> dict:
    return batch_controller.create_batch(db, payload.model_dump(), principal, request)


@router.get("/{batch_id}")
def get_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return batch_controller.get_batch(db, batch_id)


@router.get("/{batch_id}/changes")
def changes(
    batch_id: int,
    version_id: int | None = Query(default=None),
    change_kind: str | None = Query(default=None),
    limit: int = Query(200),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    page = page_params(limit, offset)
    data = batch_controller.changes(
        db, batch_id, version_id=version_id, change_kind=change_kind, limit=page.limit, offset=page.offset
    )
    if principal["role"] == Role.VIEWER.value:
        for item in data["items"]:
            for side in ("before", "after"):
                if item.get(side):
                    item[side]["unit_price_cents"] = None
            change = (item.get("changed_fields") or {}).get("unit_price_cents")
            if change:
                # 单价对只读角色一律置空（含变化前后值）
                item["changed_fields"]["unit_price_cents"] = {"before": None, "after": None}
    return data


@router.get("/{batch_id}/verify")
def verify(
    batch_id: int,
    version_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return batch_controller.verify(db, batch_id, version_id)


@router.post("/{batch_id}/recompute")
def recompute(
    batch_id: int,
    payload: BatchRecomputeIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*REVIEW_ROLES)),
) -> dict:
    return batch_controller.recompute(db, batch_id, payload.model_dump(), principal, request)


@router.post("/{batch_id}/switch")
def switch(
    batch_id: int,
    payload: BatchSwitchIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*BATCH_SWITCH_ROLES)),
) -> dict:
    return batch_controller.switch(db, batch_id, payload.model_dump(), principal, request)


@router.post("/{batch_id}/rollback")
def rollback(
    batch_id: int,
    payload: BatchRollbackIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*BATCH_SWITCH_ROLES)),
) -> dict:
    return batch_controller.rollback(db, batch_id, payload.model_dump(), principal, request)
