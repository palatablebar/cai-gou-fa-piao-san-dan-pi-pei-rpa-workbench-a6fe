"""单据中心服务：采购订单 / 收货单 / 发票的列表与导入（发票走算法 A 归一）。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import INVOICE_STATUS_LABELS, TAX_RATE_LABELS, InvoiceStatus, tax_rate_label
from src.models.goods_receipt import GoodsReceipt
from src.models.invoice import Invoice
from src.models.purchase_order import PurchaseOrder
from src.models.supplier import Supplier
from src.services import normalization_service as norm
from src.services import supplier_service
from src.utils.errors import AppError, not_found
from src.utils.timeutil import iso_date, iso_utc


def serialize_order(order: PurchaseOrder, supplier_name: str | None = None) -> dict:
    net_cents = int(order.qty) * int(order.unit_price_cents)
    return {
        "id": order.id,
        "po_no": order.po_no,
        "supplier_id": order.supplier_id,
        "supplier_name": supplier_name,
        "material_code": order.material_code,
        "material_name": order.material_name,
        "qty": order.qty,
        "unit_price_cents": order.unit_price_cents,
        "unit_price": norm.yuan_from_cents(order.unit_price_cents),
        "tax_rate_bp": order.tax_rate_bp,
        "tax_rate_label": tax_rate_label(order.tax_rate_bp),
        "net_cents": net_cents,
        "net_amount": norm.yuan_from_cents(net_cents),
        "gross_amount": norm.yuan_from_cents(
            norm.gross_from_net_cents(net_cents, order.tax_rate_bp)
        ),
        "ordered_on": iso_date(order.ordered_on),
    }


def serialize_receipt(receipt: GoodsReceipt, ordered_qty: int | None = None) -> dict:
    return {
        "id": receipt.id,
        "grn_no": receipt.grn_no,
        "po_no": receipt.po_no,
        "qty": receipt.qty,
        "ordered_qty": ordered_qty,
        "received_on": iso_date(receipt.received_on),
        "batch": receipt.batch,
        "warehouse": receipt.warehouse,
    }


def serialize_invoice(invoice: Invoice, supplier_name: str | None = None) -> dict:
    return {
        "id": invoice.id,
        "invoice_no": invoice.invoice_no,
        "import_batch": invoice.import_batch,
        "supplier_id": invoice.supplier_id,
        "supplier_name": supplier_name or invoice.supplier_name_raw,
        "po_no": invoice.po_no,
        "material_code": invoice.material_code,
        "amount_cents": invoice.amount_cents,
        "amount": norm.yuan_from_cents(invoice.amount_cents),
        "tax_cents": invoice.tax_cents,
        "tax_amount": norm.yuan_from_cents(invoice.tax_cents),
        "net_amount": norm.yuan_from_cents(invoice.amount_cents - invoice.tax_cents),
        "tax_rate_bp": invoice.tax_rate_bp,
        "tax_rate_label": tax_rate_label(invoice.tax_rate_bp),
        "issued_on": iso_date(invoice.issued_on),
        "is_red": invoice.is_red,
        "status": invoice.status,
        "status_label": INVOICE_STATUS_LABELS.get(invoice.status, invoice.status),
        "reject_reason": invoice.reject_reason,
        "created_at": iso_utc(invoice.created_at),
    }


def list_orders(
    db: Session,
    *,
    q: str | None = None,
    supplier_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    stmt = select(PurchaseOrder)
    count_stmt = select(func.count()).select_from(PurchaseOrder)
    if q:
        like = f"%{q.strip()}%"
        clause = (
            PurchaseOrder.po_no.ilike(like)
            | PurchaseOrder.material_code.ilike(like)
            | PurchaseOrder.material_name.ilike(like)
        )
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
        count_stmt = count_stmt.where(PurchaseOrder.supplier_id == supplier_id)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(PurchaseOrder.po_no).limit(limit).offset(offset)).all()
    names = {s.id: s.name for s in db.scalars(select(Supplier)).all()}
    return {
        "items": [serialize_order(row, names.get(row.supplier_id)) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def create_order(db: Session, payload: dict) -> PurchaseOrder:
    if db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_no == payload["po_no"])) is not None:
        raise AppError("CONFLICT", 409, {"po_no": payload["po_no"]})
    if db.get(Supplier, payload["supplier_id"]) is None:
        raise not_found("supplier", payload["supplier_id"])
    bp = int(payload.get("tax_rate_bp") or 1300)
    if bp not in {1300, 900, 600, 300, 100}:
        raise AppError("VALIDATION", 422, {"field": "tax_rate_bp", "allowed": [1300, 900, 600, 300, 100]})
    order = PurchaseOrder(
        po_no=payload["po_no"],
        supplier_id=payload["supplier_id"],
        material_code=payload["material_code"],
        material_name=payload.get("material_name") or "",
        qty=int(payload["qty"]),
        unit_price_cents=int(payload["unit_price_cents"]),
        tax_rate_bp=bp,
        ordered_on=payload["ordered_on"],
    )
    db.add(order)
    db.flush()
    return order


def list_receipts(
    db: Session,
    *,
    q: str | None = None,
    po_no: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    stmt = select(GoodsReceipt)
    count_stmt = select(func.count()).select_from(GoodsReceipt)
    if q:
        like = f"%{q.strip()}%"
        clause = GoodsReceipt.grn_no.ilike(like) | GoodsReceipt.po_no.ilike(like) | GoodsReceipt.batch.ilike(like)
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    if po_no:
        stmt = stmt.where(GoodsReceipt.po_no == po_no.upper())
        count_stmt = count_stmt.where(GoodsReceipt.po_no == po_no.upper())
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(GoodsReceipt.grn_no).limit(limit).offset(offset)).all()
    ordered = {po.po_no: po.qty for po in db.scalars(select(PurchaseOrder)).all()}
    return {
        "items": [serialize_receipt(row, ordered.get(row.po_no)) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def create_receipt(db: Session, payload: dict) -> GoodsReceipt:
    if db.scalar(select(GoodsReceipt).where(GoodsReceipt.grn_no == payload["grn_no"])) is not None:
        raise AppError("CONFLICT", 409, {"grn_no": payload["grn_no"]})
    receipt = GoodsReceipt(
        grn_no=payload["grn_no"],
        po_no=payload["po_no"].upper(),
        qty=int(payload["qty"]),
        received_on=payload["received_on"],
        batch=payload.get("batch") or "B01",
    )
    db.add(receipt)
    db.flush()
    return receipt


def list_invoices(
    db: Session,
    *,
    q: str | None = None,
    status: str | None = None,
    supplier_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    stmt = select(Invoice)
    count_stmt = select(func.count()).select_from(Invoice)
    if q:
        like = f"%{q.strip()}%"
        clause = Invoice.invoice_no.ilike(like) | Invoice.po_no.ilike(like) | Invoice.supplier_name_raw.ilike(like)
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)
    if status:
        stmt = stmt.where(Invoice.status == status)
        count_stmt = count_stmt.where(Invoice.status == status)
    if supplier_id:
        stmt = stmt.where(Invoice.supplier_id == supplier_id)
        count_stmt = count_stmt.where(Invoice.supplier_id == supplier_id)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(Invoice.id.desc()).limit(limit).offset(offset)).all()
    names = {s.id: s.name for s in db.scalars(select(Supplier)).all()}
    return {
        "items": [serialize_invoice(row, names.get(row.supplier_id)) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def create_invoice(db: Session, payload: dict) -> Invoice:
    """单张发票导入：先过算法 A；归一失败返回 422（字段级原因），重复自然键 409。"""
    aliases = supplier_service.alias_map(db)
    index = supplier_service.supplier_index(db)
    try:
        normalized = norm.normalize_invoice_row(
            payload, aliases=aliases, supplier_index=index, default_batch=payload.get("import_batch") or "SRM-2026-10"
        )
    except norm.NormalizationError as exc:
        raise AppError(
            "VALIDATION", 422, {"field": exc.field, "reason": exc.reason, "stage": "normalization"}
        ) from None
    exists = db.scalar(
        select(Invoice).where(
            Invoice.invoice_no == normalized.invoice_no,
            Invoice.import_batch == normalized.import_batch,
        )
    )
    if exists is not None:
        raise AppError(
            "CONFLICT", 409, {"invoice_no": normalized.invoice_no, "import_batch": normalized.import_batch}
        )
    invoice = Invoice(
        invoice_no=normalized.invoice_no,
        import_batch=normalized.import_batch,
        supplier_id=normalized.supplier_id,
        supplier_name_raw=normalized.supplier_name_raw,
        po_no=normalized.po_no,
        material_code=normalized.material_code,
        amount_cents=normalized.amount_cents,
        tax_cents=normalized.tax_cents,
        tax_rate_bp=normalized.tax_rate_bp,
        issued_on=normalized.issued_on,
        is_red=normalized.is_red,
        status=InvoiceStatus.VALID.value,
    )
    db.add(invoice)
    db.flush()
    return invoice


def tax_rate_options() -> list[dict]:
    return [{"bp": bp, "label": label} for bp, label in sorted(TAX_RATE_LABELS.items(), reverse=True)]
