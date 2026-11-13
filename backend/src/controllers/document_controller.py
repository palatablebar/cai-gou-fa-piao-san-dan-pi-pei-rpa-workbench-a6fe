"""单据中心控制器：订单 / 收货单 / 发票导入与查询。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.services import audit_service, document_service


def list_orders(db: Session, **filters) -> dict:
    return document_service.list_orders(db, **filters)


def create_order(db: Session, payload: dict, principal: dict, request: Request) -> dict:
    order = document_service.create_order(db, payload)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="order.create",
        entity="purchase_order",
        entity_id=order.id,
        detail={"po_no": order.po_no, "qty": order.qty, "unit_price_cents": order.unit_price_cents},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return document_service.serialize_order(order)


def list_receipts(db: Session, **filters) -> dict:
    return document_service.list_receipts(db, **filters)


def create_receipt(db: Session, payload: dict, principal: dict, request: Request) -> dict:
    receipt = document_service.create_receipt(db, payload)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="receipt.create",
        entity="goods_receipt",
        entity_id=receipt.id,
        detail={"grn_no": receipt.grn_no, "po_no": receipt.po_no, "qty": receipt.qty},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return document_service.serialize_receipt(receipt)


def list_invoices(db: Session, **filters) -> dict:
    return document_service.list_invoices(db, **filters)


def create_invoice(db: Session, payload: dict, principal: dict, request: Request) -> dict:
    invoice = document_service.create_invoice(db, payload)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="invoice.create",
        entity="invoice",
        entity_id=invoice.id,
        detail={
            "invoice_no": invoice.invoice_no,
            "amount_cents": invoice.amount_cents,
            "tax_rate_bp": invoice.tax_rate_bp,
            "import_batch": invoice.import_batch,
        },
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return document_service.serialize_invoice(invoice)


def tax_rates() -> dict:
    return {"items": document_service.tax_rate_options()}
