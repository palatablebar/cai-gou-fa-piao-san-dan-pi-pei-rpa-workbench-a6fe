# invoice3way · 采购发票三单匹配 RPA 工作台

联纬汽车零部件财务共享中心（12 人，月均 1,800 张发票、46 家供应商）的应付核对工作台。
SRM / WMS / 发票平台的导出数据先进「单据中心」，由后端做**字段归一（算法 A）**，
再对每个账期跑一次**三单匹配（算法 B）**，差异进「差异工作台」人工处理，
处理结果形成调整单并导出 CSV。前端只负责展示，所有判定、差异额、建议都由后端计算。

## 1. 场景

| 环节 | 说明 |
| --- | --- |
| 上游 | 采购订单（SRM）、收货单（WMS，支持分批收货）、发票（SRM 批次 + 发票平台批次） |
| 归一 | 供应商名去企业后缀 + 别名表；金额一律折成「分」；含税/不含税互算；税率标准化到 13/9/6/3/1% |
| 匹配 | 数量容差 ±1%（按供应商可配）、金额容差 ±0.02 元、税率必须一致 |
| 判定 | `matched` / `price_diff` / `qty_diff` / `tax_diff` / `duplicate` / `missing_po` |
| 差异额 | 发票金额 − 应付金额（应付 = 已收货量 × 订单单价 × (1 + 订单税率)） |
| 建议 | 红冲 / 补收 / 改税率 / 退票重开 / 补挂订单 |
| 下游 | 应付会计处理、供应商协同、调整单与差异清单导出 |

## 2. 角色与三账号（密码统一 `Demo@2026`）

| 账号 | 角色 | 权限 |
| --- | --- | --- |
| `admin@invoice3way.io` | 财务主管 | 导入三单、维护供应商容差、发起匹配、处理差异、导出、审计 |
| `analyst@invoice3way.io` | 应付会计 | 导入发票、发起匹配、处理差异；**不能导出、不能看审计、不能改容差** |
| `viewer@invoice3way.io` | 供应商协同只读 | 只读差异清单与运行记录；**单据接口 403；单价字段由后端置空** |

越权是真 403（`require_roles` 依赖），不是前端隐藏按钮。

## 3. 算法口径

### 算法 A｜字段归一与匹配键（`backend/src/services/normalization_service.py`）

1. `to_halfwidth` → 去内部空白 → 统一括号；
2. 别名表优先（`suppliers.alias` 逗号分隔，seed 里 8 家带别名）；
3. 循环剥离企业后缀：`股份有限公司 / 有限责任公司 / 有限公司 / 分公司 / 集团 / 公司 / 制造厂 / 厂 / 商行 / 经营部 / 部 / (中国)`；
4. 金额 `parse_amount_cents`：支持 `1,234.56`、`￥123.4元`，四舍五入到分；**存储与比较一律 int 分**；
5. 税率 `parse_tax_rate_bp`：`13%` / `0.13` / `13` → 1300bp，只接受 `[1300, 900, 600, 300, 100]`；
6. `gross_from_net_cents` / `net_from_gross_cents` 处理含税/不含税；
7. `match_key = (supplier_norm, po_no, material_code)`；
8. 归一失败抛 `NormalizationError(field, reason)`，批量导入时收进 `rejected`，不阻塞整批。

### 算法 B｜三单匹配（`backend/src/services/matching_service.py`）

- 应付金额 `payable = gross(已收货量 × 订单单价, 订单税率)`；收货量按 `po_no` 汇总（支持分批）；
- 判定顺序固定：**duplicate → missing_po → tax_diff → qty_diff → price_diff → matched**；
- 数量：`|收货 − 订单| > 订单 × tolerance_qty_pct%` 判量差（默认 ±1%，边界含等号）；
- 金额：`|发票 − 应付| > tolerance_amount_cents` 判价差（默认 2 分 = 0.02 元）；
- 税率：`invoice.tax_rate_bp != po.tax_rate_bp` 直接判税差；
- 重复发票：同一 `invoice_no` 第二次出现即 `duplicate`（自然键是 `invoice_no + import_batch`，
  重复来自两个采集批次重复导入）；
- 差异额带符号；建议按判定与差异方向映射（见 `suggest_for`）。

## 4. 页面

| 路由 | 页面 | 说明 |
| --- | --- | --- |
| `#/login` | 登录（凭证封面） | 双规线 + 打孔边 + 复写联标记 |
| `#/overview` | 总览 | 本期单据量、差异结构、处理进度、最近运行、worker 心跳 |
| `#/documents` | 单据中心 | 供应商 / 订单 / 收货单 / 发票四个页签，主管可导入，供应商页可改容差 |
| `#/runs` | 匹配运行 | 发起匹配、运行指标与日志 |
| `#/cases` | 差异工作台 | 判定/处理状态/运行筛选，抽屉处理为退回重开/挂账/接受 |
| `#/adjustments` | 调整单与导出 | 处理结果汇总 + 三类 CSV 导出（仅主管） |
| `#/audit` | 审计日志 | 仅主管 |

## 5. API（前缀 `/api`，Nginx 反代）

```
POST /auth/login                 GET /auth/me
GET  /overview
GET  /suppliers                  POST /suppliers        PATCH /suppliers/{id}
GET  /orders                     POST /orders
GET  /receipts                   POST /receipts
GET  /invoices                   POST /invoices
GET  /match-runs                 POST /match-runs       GET /match-runs/{id}
GET  /match-cases                GET  /match-cases/adjustments
GET  /match-cases/{id}           PATCH /match-cases/{id}/review
GET  /exports/cases.csv          GET  /exports/adjustments.csv   GET /exports/runs.csv
GET  /audit                      GET  /health
```

## 6. 共享枚举出现位置（改动需两侧同步）

| 枚举 | 后端 | 前端 |
| --- | --- | --- |
| `match_status` / `MATCH_STATUS_LABELS` | `backend/src/constants/enums.py` | `frontend/site/js/config.js` → `ENUMS.matchStatus` |
| `diff_type` / `DIFF_TYPE_LABELS` | `enums.py` + `MATCH_DIFF_TYPE` | `config.js` → `ENUMS.diffType` |
| `suggestion` / `SUGGESTION_LABELS` | `enums.py` | `config.js` → `ENUMS.suggestion` |
| `case_status` / `CASE_STATUS_LABELS` | `enums.py` | `config.js` → `ENUMS.caseStatus` |
| `run_status` / `RUN_STATUS_LABELS` | `enums.py` | `config.js` → `ENUMS.runStatus` |
| `trigger` / `TRIGGER_LABELS` | `enums.py` | `config.js` → `ENUMS.trigger` |
| `invoice_status` / `INVOICE_STATUS_LABELS` | `enums.py` | `config.js` → `ENUMS.invoiceStatus` |
| `doc_kind` / `DOC_KIND_LABELS` | `enums.py` | `config.js` → `ENUMS.docKind` |
| 角色标签 / 权限集 | `constants/roles.py` | `config.js` → `ROLE_LABELS` / `PERMISSIONS` |

## 7. seed 数据（`backend/scripts/{demo_config,seed_demo}.py`）

固定种子 `20261113` 确定性生成：**46 供应商 / 180 PO / 210 GRN（30 张订单分两批收货）/
190 张有效发票 + 5 条归一失败样本 / 1 次匹配运行 → 50 条差异**。
差异构成：12 重复（发票平台批次二次导入，含 `INV-2026-0417`）、8 税差、15 量差、9 价差、6 缺单，
其余 140 张三单一致。

```
SEED_SUMMARY brand=invoice3way users=3 sources=46 runs=1 findings=50 pending=50
SEED_DETAIL period=2026-10 orders=180 receipts=210 invoices=190 rejected=5 matched=140 diffs=50
```

> `sources` 键沿用批次固定契约，本项目映射为「供应商档案数」。

幂等：`users.email` / `suppliers.code` / `purchase_orders.po_no` / `goods_receipts.grn_no` /
`invoices(invoice_no, import_batch)` / `match_runs.seed_key` / `match_cases(run_id, case_key)`
为自然键 upsert，重复执行不新增、不覆盖人工处理状态。

## 8. 本地运行

```bash
docker compose up -d --build          # 5 服务：frontend / backend / worker / db / redis
# 首次启动自动 seed（SEED_DEMO=true）；也可手动：
docker compose exec -T backend python -m scripts.seed_demo
docker compose exec -T backend python -m pytest tests -q
open http://localhost:18203
```

端口：前端 18203 / 后端 19203 / MySQL 17703（见 `.env`，勿改）。

## 9. 目录

```
backend/src/{config,constants,controllers,middlewares,models,routes,schemas,services,utils}
backend/scripts/{seed_demo.py,demo_config.py,worker_healthcheck.sh}
backend/tests/{test_normalization.py,test_matching.py,test_security.py}
frontend/site/{index.html,css/{tokens,app}.css,js/{config,api,store,ui,app}.js,js/pages/*.js}
```

横切能力：JWT 三角色、领域 + HTTP 两层审计、Redis 固定窗口限流、CSV 导出（UTF-8 BOM）、
Celery 心跳与每日 07:40 自动重跑匹配。
