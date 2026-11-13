-- 核心表结构参考（PostgreSQL 语法，运行时不执行；建表由 SQLAlchemy create_all 完成）

CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(160) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    display_name    VARCHAR(80)  NOT NULL,
    role            VARCHAR(20)  NOT NULL,
    org             VARCHAR(120),
    created_at      TIMESTAMP    NOT NULL
);

CREATE TABLE sources (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(40)  NOT NULL UNIQUE,
    name            VARCHAR(120) NOT NULL,
    kind            VARCHAR(20)  NOT NULL,
    endpoint        VARCHAR(255),
    owner           VARCHAR(80),
    note            TEXT,
    config          JSON,
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    last_synced_at  TIMESTAMP,
    created_at      TIMESTAMP    NOT NULL,
    updated_at      TIMESTAMP    NOT NULL
);

CREATE TABLE runs (
    id              SERIAL PRIMARY KEY,
    run_no          VARCHAR(40)  NOT NULL UNIQUE,
    source_id       INTEGER      REFERENCES sources(id) ON DELETE SET NULL,
    trigger         VARCHAR(20)  NOT NULL,
    status          VARCHAR(20)  NOT NULL,
    operator_email  VARCHAR(160) NOT NULL,
    input_count     INTEGER      NOT NULL DEFAULT 0,
    output_count    INTEGER      NOT NULL DEFAULT 0,
    metrics         JSON,
    log_text        TEXT,
    seed_key        VARCHAR(120) UNIQUE,
    started_at      TIMESTAMP    NOT NULL,
    finished_at     TIMESTAMP
);

CREATE TABLE findings (
    id              SERIAL PRIMARY KEY,
    run_id          INTEGER      NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_id       INTEGER      REFERENCES sources(id) ON DELETE SET NULL,
    key             VARCHAR(120) NOT NULL,
    title           VARCHAR(200) NOT NULL,
    summary         TEXT,
    severity        VARCHAR(12)  NOT NULL,
    score           DOUBLE PRECISION NOT NULL DEFAULT 0,
    status          VARCHAR(16)  NOT NULL DEFAULT 'pending',
    payload         JSON,
    reviewer        VARCHAR(160),
    review_note     TEXT,
    created_at      TIMESTAMP    NOT NULL,
    updated_at      TIMESTAMP    NOT NULL,
    CONSTRAINT uq_findings_run_key UNIQUE (run_id, key)
);

CREATE TABLE audit_logs (
    id              SERIAL PRIMARY KEY,
    actor_email     VARCHAR(160) NOT NULL,
    actor_role      VARCHAR(20)  NOT NULL,
    action          VARCHAR(64)  NOT NULL,
    entity          VARCHAR(40)  NOT NULL,
    entity_id       VARCHAR(64),
    detail          JSON,
    layer           VARCHAR(16)  NOT NULL DEFAULT 'domain',
    ip              VARCHAR(64),
    seed_key        VARCHAR(120) UNIQUE,
    created_at      TIMESTAMP    NOT NULL
);
