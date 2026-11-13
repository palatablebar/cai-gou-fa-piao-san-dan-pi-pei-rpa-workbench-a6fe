"""Celery 任务：心跳、每日匹配（对启用账期重跑一次三单匹配）。"""
from __future__ import annotations

import time

from src.config.celery_app import TASK_DAILY, TASK_HEARTBEAT, celery_app
from src.config.settings import settings
from src.services import match_service
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
    """每日 07:40 对本账期重算一次匹配（迟到发票并入后只更新受影响的差异）。

    走账期批次的默认幂等键：同一水位不会新增运行，新发票才产生新版本。
    """
    from src.config.database import session_scope
    from src.services import audit_service, batch_service

    with session_scope() as db:
        period = match_service.default_period(db)
        batch, version, reused = batch_service.open_and_recompute(
            db,
            period=period,
            batch_key=f"period:{period}",
            operator="scheduler@" + settings.app_name + ".io",
            trigger="schedule",
        )
        audit_service.record(
            db,
            actor_email="scheduler@" + settings.app_name + ".io",
            actor_role="admin",
            action="run.create",
            entity="match_run",
            entity_id=version.run_id,
            detail={
                "trigger": "schedule",
                "batch_no": batch.batch_no,
                "version_no": version.version_no,
                "reused": reused,
            },
            layer="worker",
        )
    logger.info("daily match finished: %s v%s reused=%s", batch.batch_no, version.version_no, reused)
    return {
        "batch_no": batch.batch_no,
        "version_no": version.version_no,
        "period": period,
        "diffs": (version.counts or {}).get("diffs", 0),
        "reused": reused,
    }
