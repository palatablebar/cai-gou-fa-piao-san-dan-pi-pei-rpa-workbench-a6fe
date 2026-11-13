from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.roles import DETAIL_READ_ROLES, DOC_WRITE_ROLES
from src.controllers import document_controller
from src.middlewares.rbac import require_roles
from src.schemas.documents import ReceiptIn
from src.utils.pagination import page_params

router = APIRouter(prefix="/receipts", tags=["receipts"])


@router.get("")
def list_receipts(
    q: str | None = None,
    po_no: str | None = None,
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*DETAIL_READ_ROLES)),
) -> dict:
    page = page_params(limit, offset)
    return document_controller.list_receipts(db, q=q, po_no=po_no, limit=page.limit, offset=page.offset)


@router.post("", status_code=201)
def create_receipt(
    payload: ReceiptIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*DOC_WRITE_ROLES)),
) -> dict:
    return document_controller.create_receipt(db, payload.model_dump(), principal, request)
