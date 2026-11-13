from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.roles import DETAIL_READ_ROLES, SUPPLIER_WRITE_ROLES
from src.controllers import supplier_controller
from src.middlewares.rbac import require_roles
from src.schemas.supplier import SupplierIn, SupplierPatch
from src.utils.pagination import page_params

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("")
def list_suppliers(
    q: str | None = None,
    enabled: bool | None = None,
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*DETAIL_READ_ROLES)),
) -> dict:
    page = page_params(limit, offset)
    return supplier_controller.list_suppliers(db, q=q, enabled=enabled, limit=page.limit, offset=page.offset)


@router.get("/{supplier_id}")
def get_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*DETAIL_READ_ROLES)),
) -> dict:
    return supplier_controller.get_supplier(db, supplier_id)


@router.post("", status_code=201)
def create_supplier(
    payload: SupplierIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*SUPPLIER_WRITE_ROLES)),
) -> dict:
    return supplier_controller.create_supplier(db, payload.model_dump(), principal, request)


@router.patch("/{supplier_id}")
def update_supplier(
    supplier_id: int,
    payload: SupplierPatch,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*SUPPLIER_WRITE_ROLES)),
) -> dict:
    return supplier_controller.update_supplier(
        db, supplier_id, payload.model_dump(exclude_unset=True), principal, request
    )
