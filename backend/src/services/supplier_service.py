"""供应商档案服务：容差配置 + 归一化名称回填。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.purchase_order import PurchaseOrder
from src.models.supplier import Supplier
from src.services.normalization_service import normalize_supplier_name, yuan_from_cents
from src.utils.errors import AppError, not_found

ORG_OWNER = "联纬汽车零部件 · 财务共享中心"


def serialize(supplier: Supplier, order_count: int | None = None) -> dict:
    return {
        "id": supplier.id,
        "code": supplier.code,
        "name": supplier.name,
        "name_norm": supplier.name_norm,
        "alias": supplier.alias,
        "contact": supplier.contact,
        "tolerance_amount_cents": supplier.tolerance_amount_cents,
        "tolerance_amount": yuan_from_cents(supplier.tolerance_amount_cents),
        "tolerance_qty_pct": float(supplier.tolerance_qty_pct or 0),
        "note": supplier.note,
        "enabled": supplier.enabled,
        "order_count": order_count,
    }


def _order_counts(db: Session) -> dict[int, int]:
    rows = db.execute(
        select(PurchaseOrder.supplier_id, func.count()).group_by(PurchaseOrder.supplier_id)
    ).all()
    return {supplier_id: count for supplier_id, count in rows}


def list_suppliers(
    db: Session,
    *,
    q: str | None = None,
    enabled: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    stmt = select(Supplier)
    count_stmt = select(func.count()).select_from(Supplier)
    if q:
        like = f"%{q.strip()}%"
        clause = Supplier.name.ilike(like) | Supplier.code.ilike(like) | Supplier.name_norm.ilike(like)
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    if enabled is not None:
        stmt = stmt.where(Supplier.enabled == enabled)
        count_stmt = count_stmt.where(Supplier.enabled == enabled)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(Supplier.code).limit(limit).offset(offset)).all()
    counts = _order_counts(db)
    return {
        "items": [serialize(row, counts.get(row.id, 0)) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_supplier(db: Session, supplier_id: int) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise not_found("supplier", supplier_id)
    return supplier


def create_supplier(db: Session, payload: dict) -> Supplier:
    exists = db.scalar(select(Supplier).where(Supplier.code == payload["code"]))
    if exists is not None:
        raise AppError("CONFLICT", 409, {"code": payload["code"]})
    supplier = Supplier(
        code=payload["code"],
        name=payload["name"],
        name_norm=normalize_supplier_name(payload["name"], _aliases_from_payload(payload)),
        alias=payload.get("alias"),
        contact=payload.get("contact"),
        tolerance_amount_cents=int(payload.get("tolerance_amount_cents", 2)),
        tolerance_qty_pct=payload.get("tolerance_qty_pct", 1.0),
        note=payload.get("note"),
        enabled=True,
    )
    db.add(supplier)
    db.flush()
    return supplier


def update_supplier(db: Session, supplier: Supplier, payload: dict) -> Supplier:
    if payload.get("name"):
        supplier.name = payload["name"]
        supplier.name_norm = normalize_supplier_name(
            payload["name"], _aliases_from_payload(payload, supplier.alias)
        )
    for field in ("alias", "contact", "note", "enabled"):
        if field in payload and payload[field] is not None:
            setattr(supplier, field, payload[field])
    if payload.get("tolerance_amount_cents") is not None:
        supplier.tolerance_amount_cents = int(payload["tolerance_amount_cents"])
    if payload.get("tolerance_qty_pct") is not None:
        supplier.tolerance_qty_pct = payload["tolerance_qty_pct"]
    db.flush()
    return supplier


def _aliases_from_payload(payload: dict, alias: str | None = None) -> dict[str, str]:
    raw = payload.get("alias") if payload.get("alias") is not None else alias
    if not raw:
        return {}
    return {part.strip(): payload["name"] for part in str(raw).split(",") if part.strip()}


def alias_map(db: Session) -> dict[str, str]:
    """别名表：别名 -> 供应商全名（算法 A 的别名步骤）。"""
    mapping: dict[str, str] = {}
    for supplier in db.scalars(select(Supplier).where(Supplier.enabled.is_(True))).all():
        mapping[supplier.name] = supplier.name
        if supplier.name_norm:
            mapping[supplier.name_norm] = supplier.name
        if supplier.alias:
            for part in str(supplier.alias).split(","):
                if part.strip():
                    mapping[part.strip()] = supplier.name
    return mapping


def supplier_index(db: Session) -> dict[str, int]:
    """归一化供应商名 -> supplier_id。"""
    index: dict[str, int] = {}
    for supplier in db.scalars(select(Supplier)).all():
        index[supplier.name_norm or normalize_supplier_name(supplier.name)] = supplier.id
    return index
