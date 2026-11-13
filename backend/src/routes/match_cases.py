from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.roles import REVIEW_ROLES
from src.controllers import match_controller
from src.middlewares.rbac import READ_ROLES, require_roles
from src.schemas.match import CaseReviewIn
from src.utils.pagination import page_params

router = APIRouter(prefix="/match-cases", tags=["match-cases"])


@router.get("")
def list_cases(
    run_id: int | None = None,
    match_status: str | None = None,
    diff_type: str | None = None,
    status: str | None = None,
    supplier_id: int | None = None,
    q: str | None = None,
    only_diffs: bool = False,
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    page = page_params(limit, offset)
    return match_controller.list_cases(
        db,
        principal,
        run_id=run_id,
        match_status=match_status,
        diff_type=diff_type,
        status=status,
        supplier_id=supplier_id,
        q=q,
        only_diffs=only_diffs,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/adjustments")
def adjustments(
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return match_controller.adjustments(db)


@router.get("/{case_id}")
def get_case(
    case_id: int,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return match_controller.get_case(db, case_id, principal)


@router.patch("/{case_id}/review")
def review_case(
    case_id: int,
    payload: CaseReviewIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*REVIEW_ROLES)),
) -> dict:
    return match_controller.review_case(db, case_id, payload.model_dump(), principal, request)
