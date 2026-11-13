"""共享枚举（后端唯一定义处）。前端副本见 frontend/site/js/config.js。

README「共享枚举出现位置」一节列出全部出现点，改动需两侧同步。
"""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class DocKind(StrEnum):
    """单据中心四类单据（供应商档案 + 三单）。"""

    SUPPLIER = "supplier"
    ORDER = "order"
    RECEIPT = "receipt"
    INVOICE = "invoice"


DOC_KIND_LABELS: dict[str, str] = {
    DocKind.SUPPLIER.value: "供应商档案",
    DocKind.ORDER.value: "采购订单 PO",
    DocKind.RECEIPT.value: "收货单 GRN",
    DocKind.INVOICE.value: "发票 INV",
}


class InvoiceStatus(StrEnum):
    """归一结果：valid 入池参与匹配；rejected 归一失败只做留痕。"""

    VALID = "valid"
    REJECTED = "rejected"


INVOICE_STATUS_LABELS: dict[str, str] = {
    InvoiceStatus.VALID.value: "已入池",
    InvoiceStatus.REJECTED.value: "归一失败",
}


class MatchStatus(StrEnum):
    """三单匹配判定（算法 B 的唯一判定结果集合）。"""

    MATCHED = "matched"
    PRICE_DIFF = "price_diff"
    QTY_DIFF = "qty_diff"
    TAX_DIFF = "tax_diff"
    DUPLICATE = "duplicate"
    MISSING_PO = "missing_po"


MATCH_STATUS_LABELS: dict[str, str] = {
    MatchStatus.MATCHED.value: "三单一致",
    MatchStatus.PRICE_DIFF.value: "金额差异",
    MatchStatus.QTY_DIFF.value: "数量差异",
    MatchStatus.TAX_DIFF.value: "税率不一致",
    MatchStatus.DUPLICATE.value: "重复发票",
    MatchStatus.MISSING_PO.value: "缺采购订单",
}

MATCH_STATUS_ORDER: list[str] = [
    MatchStatus.MATCHED.value,
    MatchStatus.PRICE_DIFF.value,
    MatchStatus.QTY_DIFF.value,
    MatchStatus.TAX_DIFF.value,
    MatchStatus.DUPLICATE.value,
    MatchStatus.MISSING_PO.value,
]

DIFF_STATUSES: list[str] = [
    MatchStatus.PRICE_DIFF.value,
    MatchStatus.QTY_DIFF.value,
    MatchStatus.TAX_DIFF.value,
    MatchStatus.DUPLICATE.value,
    MatchStatus.MISSING_PO.value,
]


class DiffType(StrEnum):
    """差异类别，用于差异工作台的结构筛选（比 match_status 更粗一层）。"""

    NONE = "none"
    AMOUNT = "amount"
    QTY = "qty"
    TAX = "tax"
    DUPLICATE = "duplicate"
    MISSING = "missing"


DIFF_TYPE_LABELS: dict[str, str] = {
    DiffType.NONE.value: "无差异",
    DiffType.AMOUNT.value: "金额",
    DiffType.QTY.value: "数量",
    DiffType.TAX.value: "税率",
    DiffType.DUPLICATE.value: "重复",
    DiffType.MISSING.value: "缺单",
}

MATCH_DIFF_TYPE: dict[str, str] = {
    MatchStatus.MATCHED.value: DiffType.NONE.value,
    MatchStatus.PRICE_DIFF.value: DiffType.AMOUNT.value,
    MatchStatus.QTY_DIFF.value: DiffType.QTY.value,
    MatchStatus.TAX_DIFF.value: DiffType.TAX.value,
    MatchStatus.DUPLICATE.value: DiffType.DUPLICATE.value,
    MatchStatus.MISSING_PO.value: DiffType.MISSING.value,
}


class Suggestion(StrEnum):
    """差异处理建议（红冲 / 补收 / 改税率 / 退票重开 为核心四条）。"""

    NONE = "none"
    RED_REVERSE = "red_reverse"
    RECEIVE_MORE = "receive_more"
    FIX_TAX = "fix_tax"
    RETURN_REISSUE = "return_reissue"
    SUPPLEMENT_PO = "supplement_po"


SUGGESTION_LABELS: dict[str, str] = {
    Suggestion.NONE.value: "无需处理",
    Suggestion.RED_REVERSE.value: "红冲",
    Suggestion.RECEIVE_MORE.value: "补收",
    Suggestion.FIX_TAX.value: "改税率",
    Suggestion.RETURN_REISSUE.value: "退票重开",
    Suggestion.SUPPLEMENT_PO.value: "补挂订单",
}


class CaseStatus(StrEnum):
    PENDING = "pending"
    RETURNED = "returned"
    WRITTEN_OFF = "written_off"
    ACCEPTED = "accepted"


CASE_STATUS_LABELS: dict[str, str] = {
    CaseStatus.PENDING.value: "待处理",
    CaseStatus.RETURNED.value: "退回重开",
    CaseStatus.WRITTEN_OFF.value: "差异挂账",
    CaseStatus.ACCEPTED.value: "接受差异",
}

CASE_STATUS_ORDER: list[str] = [
    CaseStatus.PENDING.value,
    CaseStatus.RETURNED.value,
    CaseStatus.WRITTEN_OFF.value,
    CaseStatus.ACCEPTED.value,
]


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


RUN_STATUS_LABELS: dict[str, str] = {
    RunStatus.QUEUED.value: "排队中",
    RunStatus.RUNNING.value: "执行中",
    RunStatus.SUCCESS.value: "成功",
    RunStatus.PARTIAL.value: "部分成功",
    RunStatus.FAILED.value: "失败",
}


class TriggerKind(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    SEED = "seed"


TRIGGER_LABELS: dict[str, str] = {
    TriggerKind.MANUAL.value: "手动",
    TriggerKind.SCHEDULE.value: "定时",
    TriggerKind.SEED.value: "初始化",
}


class BatchStatus(StrEnum):
    """账期批次状态。

    open     已建档，尚无版本
    staging  有暂存版待核对 / 待切换
    official 已切换出正式版
    failed   切换失败（已回滚）
    closed   已关账
    """

    OPEN = "open"
    STAGING = "staging"
    OFFICIAL = "official"
    FAILED = "failed"
    CLOSED = "closed"


BATCH_STATUS_LABELS: dict[str, str] = {
    BatchStatus.OPEN.value: "已建档",
    BatchStatus.STAGING.value: "待切换",
    BatchStatus.OFFICIAL.value: "已切换",
    BatchStatus.FAILED.value: "切换失败",
    BatchStatus.CLOSED.value: "已关账",
}

# 批次可继续推进（重算 / 切换）的状态
BATCH_ACTIVE_STATUSES: list[str] = [
    BatchStatus.OPEN.value,
    BatchStatus.STAGING.value,
    BatchStatus.OFFICIAL.value,
    BatchStatus.FAILED.value,
]


class BatchVersionStatus(StrEnum):
    STAGING = "staging"
    OFFICIAL = "official"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


BATCH_VERSION_STATUS_LABELS: dict[str, str] = {
    BatchVersionStatus.STAGING.value: "暂存版（未生效）",
    BatchVersionStatus.OFFICIAL.value: "正式版",
    BatchVersionStatus.SUPERSEDED.value: "已替代",
    BatchVersionStatus.ROLLED_BACK.value: "已回滚",
    BatchVersionStatus.FAILED.value: "切换失败",
}


class ChangeKind(StrEnum):
    """同一发票在版本间相对上一正式版（无则相对上一暂存版）的变化。"""

    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    REMOVED = "removed"


CHANGE_KIND_LABELS: dict[str, str] = {
    ChangeKind.NEW.value: "新增",
    ChangeKind.CHANGED.value: "判定变化",
    ChangeKind.UNCHANGED.value: "未变化",
    ChangeKind.REMOVED.value: "退出本批次",
}


# 视为「差异结论变化」的字段
CASE_DIFF_FIELDS: tuple[str, ...] = (
    "match_status",
    "diff_type",
    "diff_amount_cents",
    "invoice_amount_cents",
    "payable_cents",
    "unit_price_cents",
    "qty_ordered",
    "qty_received",
    "suggestion",
    "po_no",
    "supplier_id",
)


# 允许的增值税率（basis point，1% = 100bp）：1% / 3% / 6% / 9% / 13%
TAX_RATE_BPS: list[int] = [1300, 900, 600, 300, 100]

TAX_RATE_LABELS: dict[int, str] = {
    1300: "13%",
    900: "9%",
    600: "6%",
    300: "3%",
    100: "1%",
    0: "0%",
}


def tax_rate_label(bp: int | None) -> str:
    if bp is None:
        return "—"
    return TAX_RATE_LABELS.get(int(bp), f"{int(bp) / 100:g}%")
