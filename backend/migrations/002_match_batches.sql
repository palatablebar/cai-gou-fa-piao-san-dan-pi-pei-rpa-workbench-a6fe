-- 账期批次 DDL 参考（PostgreSQL 语法，运行时不执行；建表由 SQLAlchemy create_all 完成）

CREATE TABLE match_batches (
    id                  SERIAL PRIMARY KEY,
    batch_no            VARCHAR(40)  NOT NULL UNIQUE,
    -- 幂等键：同一批次重复推送必须带同一个 key；缺省 period:<账期>
    batch_key           VARCHAR(120) NOT NULL UNIQUE,
    period              VARCHAR(10)  NOT NULL,
    status              VARCHAR(20)  NOT NULL DEFAULT 'open',
    -- 来源单据指纹（sha256 前 64 位），切换前与实时水位比对
    watermark           VARCHAR(64)  NOT NULL DEFAULT '',
    source_counts       JSON,
    official_version_id INTEGER,
    staging_version_id  INTEGER,
    remark              TEXT,
    created_by          VARCHAR(160) NOT NULL DEFAULT 'system',
    created_at          TIMESTAMP    NOT NULL,
    updated_at          TIMESTAMP    NOT NULL
);

CREATE TABLE match_batch_versions (
    id                  SERIAL PRIMARY KEY,
    batch_id            INTEGER      NOT NULL REFERENCES match_batches(id) ON DELETE CASCADE,
    version_no          INTEGER      NOT NULL,
    run_id              INTEGER      REFERENCES match_runs(id) ON DELETE SET NULL,
    -- staging / official / superseded / rolled_back / failed
    status              VARCHAR(20)  NOT NULL DEFAULT 'staging',
    watermark           VARCHAR(64)  NOT NULL DEFAULT '',
    watermark_detail    JSON,
    counts              JSON,        -- 来源单据 / 匹配结果 / 差异 / 审计事件数量
    change_summary      JSON,        -- 前后差异：new / changed / unchanged / removed
    verify_snapshot     JSON,        -- 最近一次水位核对结果
    error               TEXT,
    created_by          VARCHAR(160) NOT NULL DEFAULT 'system',
    created_at          TIMESTAMP    NOT NULL,
    activated_at        TIMESTAMP,
    CONSTRAINT uq_batch_versions_no UNIQUE (batch_id, version_no)
);

-- 既有表补列（老库升级时由 src/config/app.py::_ensure_batch_columns 幂等执行）
ALTER TABLE match_runs  ADD COLUMN batch_id   INTEGER NULL;
ALTER TABLE match_runs  ADD COLUMN version_id INTEGER NULL;
ALTER TABLE match_runs  ADD COLUMN watermark  VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE match_cases ADD COLUMN batch_id   INTEGER NULL;
ALTER TABLE match_cases ADD COLUMN version_id INTEGER NULL;
ALTER TABLE match_cases ADD COLUMN change_kind VARCHAR(16) NOT NULL DEFAULT 'unchanged';
