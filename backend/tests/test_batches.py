"""账期批次端到端测试：幂等重试 / 迟到发票增量 / 人工处理跟随 / 切换与回滚 / 默认只看正式版。

用 SQLite 内存库 + FastAPI TestClient，不依赖 MySQL。
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PASSWORD = "Demo@2026"


@pytest.fixture()
def app_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_KIND", "sqlite")
    monkeypatch.setenv("DB_URL", f"sqlite:///{tmp_path / 'batch.db'}")
    monkeypatch.setenv("SEED_DEMO", "false")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")

    import src.config.settings as settings_module

    settings_module.get_settings.cache_clear()
    settings_module.settings = settings_module.get_settings()

    import src.config.database as database_module

    engine = create_engine(
        settings_module.settings.database_url,
        connect_args={"check_same_thread": False},
        future=True,
    )
    database_module.engine = engine
    database_module.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    import src.models as models

    models.Base.metadata.create_all(bind=engine)

    import src.config.app as app_module

    importlib.reload(app_module)
    app = app_module.create_app()
    try:
        with TestClient(app) as client:
            seed(client)
            yield client, database_module.SessionLocal
    finally:
        # 每个用例用独立 SQLite 文件；恢复全局 engine 为测试库，避免后续模块串库
        app_module._BATCH_COLUMNS_DONE.clear()
        engine.dispose()
        settings_module.get_settings.cache_clear()
        database_module.engine = create_engine(
            settings_module.settings.database_url,
            connect_args={"check_same_thread": False},
            future=True,
        )


def seed(client):
    from scripts.seed_demo import seed_all

    seed_all()


def login(client, email="admin@invoice3way.io"):
    resp = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def add_late_invoice(client, headers):
    """迟到发票：原发票漏开，月末补一张三单一致的发票（同一 PO）。"""
    resp = client.post(
        "/api/invoices",
        headers=headers,
        json={
            "invoice_no": "INV-2026-0700",
            "import_batch": "SRM-2026-10",
            "supplier_name": "宁波华翔汽车部件有限公司",
            "po_no": "PO-2026-0002",
            "amount": "1130.00",
            "tax_rate": "13%",
            "issued_on": "2026-10-28",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_batch_seed_is_idempotent_and_official(app_env):
    client, _ = app_env
    headers = login(client)
    seed(client)  # 再 seed 一次：不新增运行 / 工单

    batches = client.get("/api/match-batches", headers=headers).json()
    seed_batch = next(item for item in batches["items"] if item["batch_key"] == "seed-run-2026-10")
    assert seed_batch["status"] == "official"
    official = seed_batch["official_version"]
    assert official["status"] == "official"
    assert official["watermark_label"].startswith("WM-202610-")
    assert official["counts"]["diffs"] == 50

    runs = client.get("/api/match-runs", headers=headers).json()
    assert runs["total"] == 1
    assert all(run["batch_id"] == seed_batch["id"] for run in runs["items"])


def test_retry_same_batch_key_reuses_run(app_env):
    client, _ = app_env
    headers = login(client)
    payload = {"period": "2026-10", "batch_key": "push-2026-10-a", "trigger": "manual"}

    first = client.post("/api/match-batches", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["reused"] is False
    version = body["version"]
    assert version["change_summary"]["baseline"] is True

    second = client.post("/api/match-batches", headers=headers, json=payload)
    assert second.status_code == 201
    assert second.json()["reused"] is True
    assert second.json()["version"]["id"] == version["id"]

    runs = client.get("/api/match-runs", headers=headers).json()
    batch_runs = [row for row in runs["items"] if row["batch_id"] == body["batch"]["id"]]
    assert len(batch_runs) == 1

    # 同一批次只切换一次：切换后重试仍复用正式版，不再建版本
    switched = client.post(f"/api/match-batches/{body['batch']['id']}/switch", headers=headers, json={})
    assert switched.status_code == 200, switched.text
    third = client.post("/api/match-batches", headers=headers, json=payload)
    assert third.json()["reused"] is True
    assert third.json()["version"]["status"] == "official"


def test_late_invoice_creates_version_and_marks_only_affected(app_env):
    client, SessionLocal = app_env
    headers = login(client)
    created = client.post(
        "/api/match-batches",
        headers=headers,
        json={"period": "2026-10", "batch_key": "push-2026-10-b"},
    ).json()
    batch_id = created["batch"]["id"]
    assert client.post(f"/api/match-batches/{batch_id}/switch", headers=headers, json={}).status_code == 200

    # 正式版里先处理一条差异：INV-2026-0311 对应 PO-2026-0001 的量差
    cases = client.get(
        "/api/match-cases", headers=headers, params={"run_id": created["version"]["run_id"], "only_diffs": "true"}
    ).json()
    target = next(item for item in cases["items"] if item["invoice_no"] == "INV-2026-0311")
    reviewed = client.patch(
        f"/api/match-cases/{target['id']}/review",
        headers=headers,
        json={"status": "returned", "note": "已通知供应商补收"},
    )
    assert reviewed.status_code == 200

    add_late_invoice(client, headers)
    recomputed = client.post(f"/api/match-batches/{batch_id}/recompute", headers=headers, json={})
    assert recomputed.status_code == 200, recomputed.text
    new_version = recomputed.json()["version"]
    assert new_version["status"] == "staging"
    summary = new_version["change_summary"]
    assert summary["new"] >= 1
    assert summary["changed"] <= 1
    assert summary["affected"] == summary["new"] + summary["changed"]
    assert summary["unchanged"] > 40  # 绝大多数差异没被迟到发票影响

    changes = client.get(
        f"/api/match-batches/{batch_id}/changes", headers=headers, params={"version_id": new_version["id"]}
    ).json()
    assert [item["invoice_no"] for item in changes["items"]] == ["INV-2026-0700"]
    assert changes["items"][0]["change_kind"] == "new"

    # 人工处理跟随同一发票（case_key 相同）到新版本
    carried = client.get(
        "/api/match-cases",
        headers=headers,
        params={"version_id": new_version["id"], "q": "INV-2026-0311"},
    ).json()["items"][0]
    assert carried["status"] == "returned"
    assert carried["note"] == "已通知供应商补收"

    # 工作台默认只看正式版：暂存版的新增差异不会混进待办
    default_cases = client.get("/api/match-cases", headers=headers, params={"only_diffs": "true"}).json()
    invoices = {item["invoice_no"] for item in default_cases["items"]}
    assert "INV-2026-0700" not in invoices

    switched = client.post(
        f"/api/match-batches/{batch_id}/switch", headers=headers, json={"version_id": new_version["id"]}
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["previous_version_id"] == created["version"]["id"]
    after = client.get("/api/match-batches", headers=headers).json()
    batch = next(item for item in after["items"] if item["id"] == batch_id)
    assert batch["status"] == "official"
    assert batch["official_version"]["version_no"] == 2
    assert batch["official_version"]["counts"]["cases"] == created["version"]["counts"]["cases"] + 1


def test_switch_failure_restores_previous_version(app_env):
    client, _ = app_env
    headers = login(client)
    created = client.post(
        "/api/match-batches",
        headers=headers,
        json={"period": "2026-10", "batch_key": "push-2026-10-c"},
    ).json()
    batch_id = created["batch"]["id"]
    assert client.post(f"/api/match-batches/{batch_id}/switch", headers=headers, json={}).status_code == 200

    # 做一次人工处理，验证失败切换不丢处理意见
    case = client.get("/api/match-cases", headers=headers, params={"status": "pending", "only_diffs": "true"}).json()["items"][0]
    client.patch(
        f"/api/match-cases/{case['id']}/review",
        headers=headers,
        json={"status": "accepted", "note": "守住正式版"},
    )

    add_late_invoice(client, headers)
    recomputed = client.post(f"/api/match-batches/{batch_id}/recompute", headers=headers, json={}).json()
    new_version_id = recomputed["version"]["id"]

    failed = client.post(
        f"/api/match-batches/{batch_id}/switch",
        headers=headers,
        json={"version_id": new_version_id, "simulate_failure": True},
    )
    assert failed.status_code == 409, failed.text
    detail = failed.json()["detail"]
    assert detail["restored_version_id"] == created["version"]["id"]

    batch = next(
        item for item in client.get("/api/match-batches", headers=headers).json()["items"] if item["id"] == batch_id
    )
    assert batch["status"] == "failed"
    assert batch["official_version"]["id"] == created["version"]["id"]
    assert batch["official_version"]["status"] == "official"
    stale = next(item for item in batch["versions"] if item["id"] == new_version_id)
    assert stale["status"] == "staging"
    assert stale["error"].startswith("切换失败")

    kept = client.get(f"/api/match-cases/{case['id']}", headers=headers).json()
    assert kept["status"] == "accepted"
    assert kept["note"] == "守住正式版"

    # 重试切换成功，正式版前移
    retry = client.post(
        f"/api/match-batches/{batch_id}/switch", headers=headers, json={"version_id": new_version_id}
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["batch"]["official_version"]["version_no"] == 2


def test_switch_blocks_when_watermark_moved(app_env):
    client, SessionLocal = app_env
    headers = login(client)
    created = client.post(
        "/api/match-batches",
        headers=headers,
        json={"period": "2026-10", "batch_key": "push-2026-10-d"},
    ).json()
    batch_id = created["batch"]["id"]
    version_id = created["version"]["id"]
    assert client.post(f"/api/match-batches/{batch_id}/switch", headers=headers, json={}).status_code == 200

    add_late_invoice(client, headers)
    recomputed = client.post(f"/api/match-batches/{batch_id}/recompute", headers=headers, json={}).json()
    staged_id = recomputed["version"]["id"]

    # 生成暂存版之后又来了单据：水位已变，不能切换
    add_late_invoice_second(client, headers)
    blocked = client.post(
        f"/api/match-batches/{batch_id}/switch", headers=headers, json={"version_id": staged_id}
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["reason"].startswith("水位核对未通过")
    assert not blocked.json()["detail"]["verification"]["ok"]


def add_late_invoice_second(client, headers):
    resp = client.post(
        "/api/invoices",
        headers=headers,
        json={
            "invoice_no": "INV-2026-0701",
            "import_batch": "SRM-2026-10",
            "supplier_name": "华翔",
            "po_no": "PO-2026-0003",
            "amount": "100.00",
            "tax_rate": "13%",
            "issued_on": "2026-10-29",
        },
    )
    assert resp.status_code == 201, resp.text


def test_explicit_rollback_keeps_records_and_reviews(app_env):
    client, _ = app_env
    headers = login(client)
    created = client.post(
        "/api/match-batches",
        headers=headers,
        json={"period": "2026-10", "batch_key": "push-2026-10-e"},
    ).json()
    batch_id = created["batch"]["id"]
    assert client.post(f"/api/match-batches/{batch_id}/switch", headers=headers, json={}).status_code == 200

    case = client.get(
        "/api/match-cases", headers=headers, params={"only_diffs": "true", "status": "pending"}
    ).json()["items"][0]
    client.patch(
        f"/api/match-cases/{case['id']}/review",
        headers=headers,
        json={"status": "written_off", "note": "先挂账，等供应商确认"},
    )

    add_late_invoice(client, headers)
    new_version = client.post(
        f"/api/match-batches/{batch_id}/recompute", headers=headers, json={}
    ).json()["version"]
    assert client.post(
        f"/api/match-batches/{batch_id}/switch", headers=headers, json={"version_id": new_version["id"]}
    ).status_code == 200

    rolled = client.post(f"/api/match-batches/{batch_id}/rollback", headers=headers, json={})
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["version"]["version_no"] == 1
    versions = {item["version_no"]: item for item in rolled.json()["batch"]["versions"]}
    assert versions[1]["status"] == "official"
    assert versions[2]["status"] == "rolled_back"

    kept = client.get(f"/api/match-cases/{case['id']}", headers=headers).json()
    assert kept["status"] == "written_off"
    assert kept["note"] == "先挂账，等供应商确认"

    # 回滚后默认工作台重新只看 v1 正式版
    cases = client.get("/api/match-cases", headers=headers, params={"only_diffs": "true"}).json()
    assert all(row["run_id"] == created["version"]["run_id"] for row in cases["items"])


def test_batch_switch_requires_admin(app_env):
    client, _ = app_env
    admin = login(client)
    created = client.post(
        "/api/match-batches", headers=admin, json={"period": "2026-10", "batch_key": "push-2026-10-f"}
    ).json()
    analyst = login(client, "analyst@invoice3way.io")
    denied = client.post(f"/api/match-batches/{created['batch']['id']}/switch", headers=analyst, json={})
    assert denied.status_code == 403
    viewer = login(client, "viewer@invoice3way.io")
    assert client.get("/api/match-batches", headers=viewer).status_code == 200
