"""供应商控制器：写操作记领域审计。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.services import audit_service, supplier_service


def list_suppliers(db: Session, **filters) -> dict:
    return supplier_service.list_suppliers(db, **filters)


def get_supplier(db: Session, supplier_id: int) -> dict:
    return supplier_service.serialize(supplier_service.get_supplier(db, supplier_id))


def create_supplier(db: Session, payload: dict, principal: dict, request: Request) -> dict:
    supplier = supplier_service.create_supplier(db, payload)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="supplier.create",
        entity="supplier",
        entity_id=supplier.id,
        detail={"code": supplier.code, "name": supplier.name, "name_norm": supplier.name_norm},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return supplier_service.serialize(supplier)


def update_supplier(db: Session, supplier_id: int, payload: dict, principal: dict, request: Request) -> dict:
    supplier = supplier_service.get_supplier(db, supplier_id)
    supplier_service.update_supplier(db, supplier, payload)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="supplier.update",
        entity="supplier",
        entity_id=supplier.id,
        detail={
            "fields": list(payload.keys()),
            "tolerance_amount_cents": supplier.tolerance_amount_cents,
            "tolerance_qty_pct": float(supplier.tolerance_qty_pct or 0),
        },
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return supplier_service.serialize(supplier)
