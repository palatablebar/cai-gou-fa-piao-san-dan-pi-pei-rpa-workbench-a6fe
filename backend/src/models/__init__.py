"""ORM 模型聚合导出（Base 用于 create_all）。"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from src.models.user import User  # noqa: E402
from src.models.audit import AuditLog  # noqa: E402
from src.models.supplier import Supplier  # noqa: E402
from src.models.purchase_order import PurchaseOrder  # noqa: E402
from src.models.goods_receipt import GoodsReceipt  # noqa: E402
from src.models.invoice import Invoice  # noqa: E402
from src.models.match_run import MatchRun  # noqa: E402
from src.models.match_case import MatchCase  # noqa: E402

__all__ = [
    "Base",
    "User",
    "AuditLog",
    "Supplier",
    "PurchaseOrder",
    "GoodsReceipt",
    "Invoice",
    "MatchRun",
    "MatchCase",
]
