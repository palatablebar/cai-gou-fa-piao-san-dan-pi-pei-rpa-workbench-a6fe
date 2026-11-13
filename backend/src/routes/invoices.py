from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.roles import DETAIL_READ_ROLES, INVOICE_WRITE_ROLES
from src.controllers import document_controller
from src.middlewares.rbac import require_roles
from src.schemas.documents import InvoiceIn
from src.utils.pagination import page_params

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("")
def list_invoices(
    q: str | None = None,
    status: str | None = None,
    supplier_id: int | None = None,
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*DETAIL_READ_ROLES)),
) -> dict:
    page = page_params(limit, offset)
    return document_controller.list_invoices(
        db, q=q, status=status, supplier_id=supplier_id, limit=page.limit, offset=page.offset
    )


@router.post("", status_code=201)
def create_invoice(
    payload: InvoiceIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*INVOICE_WRITE_ROLES)),
) -> dict:
    return document_controller.create_invoice(db, payload.model_dump(), principal, request)
