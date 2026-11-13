"""审计动作 -> 中文标签。"""
from __future__ import annotations

ACTIONS: dict[str, str] = {
    "auth.login": "登录",
    "supplier.create": "新建供应商档案",
    "supplier.update": "修改容差配置",
    "order.create": "导入采购订单",
    "receipt.create": "导入收货单",
    "invoice.create": "导入发票",
    "invoice.reject": "发票归一失败",
    "run.create": "发起三单匹配",
    "run.complete": "匹配完成",
    "case.review": "处理差异",
    "batch.open": "建立账期批次",
    "batch.submit": "提交账期批次",
    "batch.recompute": "批次重算生成版本",
    "batch.verify_failed": "批次水位核对未通过",
    "batch.switch": "切换正式版",
    "batch.switch_failed": "切换正式版失败并回滚",
    "batch.rollback": "回滚正式版",
    "export.cases": "导出差异清单",
    "export.runs": "导出运行记录",
    "http.mutation": "写请求",
}
