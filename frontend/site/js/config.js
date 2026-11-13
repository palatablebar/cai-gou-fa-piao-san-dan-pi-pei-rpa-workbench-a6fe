/**
 * 项目品牌、导航、角色权限与枚举文案（前端唯一定义处）。
 * 后端对应：backend/src/constants/{roles,enums}.py；README 列出全部出现位置。
 */
export const BRAND = {
  short: 'invoice3way',
  title: '采购发票三单匹配 RPA 工作台',
  voucherTitle: '应 付 凭 证 三 单 核 对 单',
  org: '联纬汽车零部件 · 财务共享中心',
  edition: 'VOUCHER · 2026-10',
  subtitle: 'PO / 收货单 / 发票 归一 → 三单匹配 → 差异处理 → 调整单',
  loginLead: '每一笔应付都要指得回三张纸：采购订单、收货单、发票。',
  loginPoints: [
    ['01', '供应商名去后缀 + 别名表归一，金额一律折成分，税率只认 13/9/6/3/1%。'],
    ['02', '数量容差 ±1%、金额容差 ±0.02 元、税率必须一致，差异由后端算。'],
    ['03', '差异工单退回重开 / 挂账 / 接受，处理痕迹与导出清单一并留档。'],
  ],
  voucherNo: '记 账 凭 证 · GJ-2026-10',
};

export const NAV = [
  { to: '#/overview', no: '01', label: '总览', permission: 'overview:read' },
  { to: '#/documents', no: '02', label: '单据中心', permission: 'invoice:read' },
  { to: '#/runs', no: '03', label: '匹配运行', permission: 'run:read' },
  { to: '#/cases', no: '04', label: '差异工作台', permission: 'case:read' },
  { to: '#/adjustments', no: '05', label: '调整单与导出', permission: 'case:read' },
  { to: '#/audit', no: '06', label: '审计日志', permission: 'audit:read' },
];

export const ROLE_LABELS = {
  admin: '财务主管',
  analyst: '应付会计',
  viewer: '供应商协同只读',
};

export const PERMISSIONS = {
  admin: [
    'overview:read', 'supplier:read', 'supplier:write', 'order:read', 'order:write',
    'receipt:read', 'receipt:write', 'invoice:read', 'invoice:write',
    'run:read', 'run:create', 'case:read', 'case:review', 'export:read', 'audit:read',
  ],
  analyst: [
    'overview:read', 'supplier:read', 'order:read', 'receipt:read', 'invoice:read', 'invoice:write',
    'run:read', 'run:create', 'case:read', 'case:review',
  ],
  viewer: ['overview:read', 'run:read', 'case:read'],
};

export const ENUMS = {
  matchStatus: {
    matched: '三单一致',
    price_diff: '金额差异',
    qty_diff: '数量差异',
    tax_diff: '税率不一致',
    duplicate: '重复发票',
    missing_po: '缺采购订单',
  },
  diffType: {
    none: '无差异',
    amount: '金额',
    qty: '数量',
    tax: '税率',
    duplicate: '重复',
    missing: '缺单',
  },
  suggestion: {
    none: '无需处理',
    red_reverse: '红冲',
    receive_more: '补收',
    fix_tax: '改税率',
    return_reissue: '退票重开',
    supplement_po: '补挂订单',
  },
  caseStatus: {
    pending: '待处理',
    returned: '退回重开',
    written_off: '差异挂账',
    accepted: '接受差异',
  },
  runStatus: {
    queued: '排队中',
    running: '执行中',
    success: '成功',
    partial: '部分成功',
    failed: '失败',
  },
  trigger: {
    manual: '手动',
    schedule: '定时',
    seed: '初始化',
  },
  invoiceStatus: {
    valid: '已入池',
    rejected: '归一失败',
  },
  docKind: {
    supplier: '供应商档案',
    order: '采购订单 PO',
    receipt: '收货单 GRN',
    invoice: '发票 INV',
  },
};

export function can(role, permission) {
  return (PERMISSIONS[role] || []).includes(permission);
}

export function statusTone(status) {
  return {
    matched: 'ok',
    price_diff: 'warn',
    qty_diff: 'warn',
    tax_diff: 'danger',
    duplicate: 'danger',
    missing_po: 'danger',
  }[status] || 'info';
}

export function caseTone(status) {
  return { pending: 'pending warn', returned: 'danger', written_off: 'info', accepted: 'ok' }[status] || 'info';
}

export function runTone(status) {
  return { success: 'ok', partial: 'warn', failed: 'danger', running: 'info', queued: '' }[status] || 'info';
}
