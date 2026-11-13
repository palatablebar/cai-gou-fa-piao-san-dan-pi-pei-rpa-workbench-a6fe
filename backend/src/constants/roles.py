"""角色 -> 权限点映射。README 与前端 site/js/config.js 同步。

角色键固定为 admin / analyst / viewer，本项目的职责：
  admin   导入单据、配置容差、导出调整单
  analyst 跑匹配、处理差异
  viewer  只读差异清单（单价由后端置空）
"""
from __future__ import annotations

from src.constants.enums import Role

ROLE_LABELS: dict[str, str] = {
    Role.ADMIN.value: "财务主管",
    Role.ANALYST.value: "应付会计",
    Role.VIEWER.value: "供应商协同只读",
}

ROLE_DUTIES: dict[str, str] = {
    Role.ADMIN.value: "导入三单、维护供应商容差、导出调整单与审计",
    Role.ANALYST.value: "发起三单匹配、处理差异（退回重开 / 挂账 / 接受）",
    Role.VIEWER.value: "只读差异清单与运行结果，单价字段由后端置空",
}

PERMISSIONS: dict[str, set[str]] = {
    Role.ADMIN.value: {
        "supplier:read", "supplier:write",
        "order:read", "order:write",
        "receipt:read", "receipt:write",
        "invoice:read", "invoice:write",
        "run:read", "run:create",
        "case:read", "case:review",
        "export:read", "audit:read", "overview:read",
    },
    Role.ANALYST.value: {
        "supplier:read",
        "order:read", "receipt:read", "invoice:read", "invoice:write",
        "run:read", "run:create",
        "case:read", "case:review",
        "overview:read",
    },
    Role.VIEWER.value: {
        "run:read", "case:read", "overview:read",
    },
}

SUPPLIER_WRITE_ROLES = (Role.ADMIN.value,)
DOC_WRITE_ROLES = (Role.ADMIN.value,)
INVOICE_WRITE_ROLES = (Role.ADMIN.value, Role.ANALYST.value)
DETAIL_READ_ROLES = (Role.ADMIN.value, Role.ANALYST.value)
RUN_CREATE_ROLES = (Role.ADMIN.value, Role.ANALYST.value)
REVIEW_ROLES = (Role.ADMIN.value, Role.ANALYST.value)
EXPORT_ROLES = (Role.ADMIN.value,)
AUDIT_ROLES = (Role.ADMIN.value,)
READ_ROLES = (Role.ADMIN.value, Role.ANALYST.value, Role.VIEWER.value)


def has_permission(role: str, permission: str) -> bool:
    return permission in PERMISSIONS.get(role, set())
