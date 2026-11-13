"""Celery 任务：心跳、每日匹配（对启用账期重跑一次三单匹配）。"""
from __future__ import annotations

import time

from src.config.celery_app import TASK_DAILY, TASK_HEARTBEAT, celery_app
from src.config.settings import settings
from src.utils.logger import get_logger

logger = get_logger("tasks")


def _redis():
    import redis

    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


@celery_app.task(name=TASK_HEARTBEAT)
def heartbeat() -> str:
    try:
        _redis().set(f"{settings.app_name}:worker:heartbeat", time.time())
        return "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("heartbeat failed: %s", exc)
        return "error"


@celery_app.task(name=TASK_DAILY)
def daily_match() -> dict:
    """每日 07:40 对本账期重跑一次匹配（新导入的发票会自动进入结果）。"""
    from src.config.database import session_scope
    from src.services import audit_service, match_service

    with session_scope() as db:
        period = match_service.default_period(db)
        run = match_service.create_and_execute(
            db,
            period=period,
            trigger="schedule",
            operator_email="scheduler@" + settings.app_name + ".io",
        )
        audit_service.record(
            db,
            actor_email="scheduler@" + settings.app_name + ".io",
            actor_role="admin",
            action="run.create",
            entity="match_run",
            entity_id=run.id,
            detail={"trigger": "schedule", "run_no": run.run_no, "period": run.period},
            layer="worker",
        )
    logger.info("daily match finished: %s", run.run_no)
    return {"run_no": run.run_no, "period": period, "diffs": run.diff_count}
