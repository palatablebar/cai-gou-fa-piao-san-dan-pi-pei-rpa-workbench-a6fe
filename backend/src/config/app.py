"""FastAPI 装配：中间件顺序、异常处理、路由挂载、启动钩子。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config.database import engine, wait_for_db
from src.config.settings import settings
from src.middlewares.audit_logger import AuditMiddleware
from src.middlewares.auth import AuthMiddleware
from src.middlewares.error_handler import register_exception_handlers
from src.middlewares.rate_limit import RateLimitMiddleware
from src.routes import api_router

logger = logging.getLogger(f"{settings.app_name}.app")


def _bootstrap_database() -> None:
    from src.models import Base  # noqa: WPS433 - 延迟导入避免循环

    wait_for_db()
    Base.metadata.create_all(bind=engine)
    _ensure_batch_columns()


# create_all 只建新表，不会给已存在的表加列；老库升级时补齐批次相关列（幂等）
_ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("match_runs", "batch_id", "INTEGER NULL"),
    ("match_runs", "version_id", "INTEGER NULL"),
    ("match_runs", "watermark", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("match_cases", "batch_id", "INTEGER NULL"),
    ("match_cases", "version_id", "INTEGER NULL"),
    ("match_cases", "change_kind", "VARCHAR(16) NOT NULL DEFAULT 'unchanged'"),
]


_BATCH_COLUMNS_DONE: set[str] = set()


def _ensure_batch_columns() -> None:
    from sqlalchemy import inspect, text

    url = str(engine.url)
    if url in _BATCH_COLUMNS_DONE:
        return
    _BATCH_COLUMNS_DONE.add(url)

    inspector = inspect(engine)
    existing = {table: {col["name"] for col in inspector.get_columns(table)} for table in ("match_runs", "match_cases")}
    with engine.begin() as conn:
        for table, column, ddl in _ADDED_COLUMNS:
            if column in existing.get(table, set()):
                continue
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            except Exception as exc:  # noqa: BLE001 - 并发启动时另一进程已加列
                logger.debug("ensure column %s.%s skipped: %s", table, column, exc)


def _run_seed_once() -> None:
    if not settings.seed_demo:
        return
    try:
        from scripts.seed_demo import seed_all

        seed_all()
    except Exception as exc:  # noqa: BLE001 - 启动阶段不阻塞
        logger.warning("[SEED_DEMO] seed failed (ignored): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _bootstrap_database()
    _run_seed_once()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_title, version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AuthMiddleware)
    app.add_middleware(AuditMiddleware)
    app.add_middleware(RateLimitMiddleware)
    register_exception_handlers(app)

    app.include_router(api_router, prefix="/api")
    app.include_router(api_router, include_in_schema=False)
    return app
