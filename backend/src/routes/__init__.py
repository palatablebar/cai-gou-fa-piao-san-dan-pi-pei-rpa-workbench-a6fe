"""路由聚合：统一 /api 前缀（Nginx 反代时剥掉 /api）。"""
from fastapi import APIRouter

from src.routes.audit import router as audit_router
from src.routes.auth import router as auth_router
from src.routes.exports import router as exports_router
from src.routes.health import router as health_router
from src.routes.invoices import router as invoices_router
from src.routes.match_cases import router as match_cases_router
from src.routes.match_runs import router as match_runs_router
from src.routes.orders import router as orders_router
from src.routes.overview import router as overview_router
from src.routes.receipts import router as receipts_router
from src.routes.suppliers import router as suppliers_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(overview_router)
api_router.include_router(suppliers_router)
api_router.include_router(orders_router)
api_router.include_router(receipts_router)
api_router.include_router(invoices_router)
api_router.include_router(match_runs_router)
api_router.include_router(match_cases_router)
api_router.include_router(exports_router)
api_router.include_router(audit_router)
