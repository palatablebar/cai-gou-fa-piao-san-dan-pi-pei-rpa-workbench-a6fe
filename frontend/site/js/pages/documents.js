import { api } from '../api.js';
import { ENUMS, can } from '../config.js';
import { drawer, emptyState, errorBox, errorMessage, esc, field, fmtTime, kv, table, toast } from '../ui.js';

const state = { tab: 'supplier', q: '', status: '', supplierId: '' };
const TABS = [
  { key: 'supplier', label: '供应商档案', endpoint: '/api/suppliers' },
  { key: 'order', label: '采购订单', endpoint: '/api/orders' },
  { key: 'receipt', label: '收货单', endpoint: '/api/receipts' },
  { key: 'invoice', label: '发票', endpoint: '/api/invoices' },
];

function money(value) {
  return `¥${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;
}

function supplierColumns() {
  return [
    { key: 'code', label: '供应商编码', className: 'mono' },
    { key: 'name', label: '名称', render: (row) => `<b>${esc(row.name)}</b><div class="mono muted">${esc(row.name_norm)}</div>` },
    { key: 'alias', label: '别名', render: (row) => esc(row.alias || '—') },
    { key: 'tolerance_amount', label: '金额容差', className: 'num', render: (row) => `±${row.tolerance_amount.toFixed(2)} 元` },
    { key: 'tolerance_qty_pct', label: '数量容差', className: 'num', render: (row) => `±${row.tolerance_qty_pct}%` },
    { key: 'order_count', label: '订单数', className: 'num' },
    { key: 'enabled', label: '状态', render: (row) => (row.enabled ? '<span class="badge ok">启用</span>' : '<span class="badge">停用</span>') },
  ];
}

function orderColumns() {
  return [
    { key: 'po_no', label: '采购订单', className: 'mono' },
    { key: 'supplier_name', label: '供应商' },
    { key: 'material_code', label: '物料', render: (row) => `${esc(row.material_code)}<div class="muted">${esc(row.material_name)}</div>` },
    { key: 'qty', label: '数量', className: 'num' },
    { key: 'unit_price', label: '单价', className: 'num', render: (row) => money(row.unit_price) },
    { key: 'tax_rate_label', label: '税率', className: 'mono' },
    { key: 'gross_amount', label: '含税金额', className: 'num', render: (row) => money(row.gross_amount) },
    { key: 'ordered_on', label: '下单日', className: 'mono' },
  ];
}

function receiptColumns() {
  return [
    { key: 'grn_no', label: '收货单', className: 'mono' },
    { key: 'po_no', label: '采购订单', className: 'mono' },
    { key: 'qty', label: '收货量', className: 'num' },
    { key: 'ordered_qty', label: '订单量', className: 'num', render: (row) => row.ordered_qty ?? '—' },
    { key: 'batch', label: '批次', className: 'mono' },
    { key: 'received_on', label: '收货日', className: 'mono' },
    { key: 'warehouse', label: '仓库' },
  ];
}

function invoiceColumns() {
  return [
    { key: 'invoice_no', label: '发票号', render: (row) => `<b class="mono">${esc(row.invoice_no)}</b><div class="mono muted">${esc(row.import_batch)}</div>` },
    { key: 'supplier_name', label: '供应商' },
    { key: 'po_no', label: '采购订单', className: 'mono' },
    { key: 'amount', label: '含税金额', className: 'num', render: (row) => money(row.amount) },
    { key: 'tax_rate_label', label: '税率', className: 'mono' },
    { key: 'issued_on', label: '开票日', className: 'mono' },
    {
      key: 'status',
      label: '归一',
      render: (row) =>
        row.status === 'valid'
          ? '<span class="badge ok">已入池</span>'
          : `<span class="badge danger">归一失败</span><div class="mono muted">${esc(row.reject_reason || '')}</div>`,
    },
  ];
}

async function openTolerance(view, ctx, supplier) {
  const editable = can(ctx.user.role, 'supplier:write');
  const { root, close } = drawer({
    title: supplier.name,
    subtitle: `${supplier.code} · 归一后 ${supplier.name_norm}`,
    body: `${kv([
      ['别名', esc(supplier.alias || '—')],
      ['对接人', esc(supplier.contact || '—')],
      ['订单数', esc(supplier.order_count ?? 0)],
      ['金额容差', `<span class="mono">±${supplier.tolerance_amount.toFixed(2)} 元</span>`],
      ['数量容差', `<span class="mono">±${supplier.tolerance_qty_pct}%</span>`],
      ['备注', esc(supplier.note || '—')],
    ])}
    <p class="muted" style="margin:10px 0 0">容差直接进入算法 B：数量偏差超过 ±${supplier.tolerance_qty_pct}% 判量差，金额偏差超过 ±${supplier.tolerance_amount.toFixed(2)} 元判价差。</p>`,
    footer: editable
      ? `<form id="tol-form" style="display:grid;gap:10px">
          ${field({ label: '金额容差（分）', name: 'tolerance_amount_cents', type: 'number', value: supplier.tolerance_amount_cents })}
          ${field({ label: '数量容差（%）', name: 'tolerance_qty_pct', type: 'number', value: supplier.tolerance_qty_pct })}
          ${field({ label: '别名（逗号分隔）', name: 'alias', value: supplier.alias || '' })}
          <button class="btn accent" type="submit">保存容差</button>
        </form>`
      : '<span class="mono muted">只读角色不可修改容差</span>',
  });
  root.querySelector('#tol-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      await api.patch(`/api/suppliers/${supplier.id}`, {
        tolerance_amount_cents: Number(form.tolerance_amount_cents.value),
        tolerance_qty_pct: Number(form.tolerance_qty_pct.value),
        alias: form.alias.value.trim() || null,
      });
      toast('容差已更新，下次运行生效');
      close();
      await documentsPage.render(view, ctx);
    } catch (err) {
      toast(errorMessage(err), 'err');
    }
  });
}

function openImport(view, ctx) {
  const tab = state.tab;
  const forms = {
    order: `${field({ label: '采购订单号', name: 'po_no', placeholder: 'PO-2026-0181' })}
      ${field({ label: '供应商 ID', name: 'supplier_id', type: 'number', placeholder: '1' })}
      ${field({ label: '物料编码', name: 'material_code', placeholder: 'MAT-1001' })}
      ${field({ label: '数量', name: 'qty', type: 'number', value: 100 })}
      ${field({ label: '单价（分）', name: 'unit_price_cents', type: 'number', value: 12000 })}
      ${field({ label: '税率', name: 'tax_rate_bp', value: '1300', options: [1300, 900, 600, 300, 100].map((bp) => ({ value: bp, label: `${bp / 100}%` })) })}
      ${field({ label: '下单日期', name: 'ordered_on', type: 'date', value: '2026-10-01' })}`,
    receipt: `${field({ label: '收货单号', name: 'grn_no', placeholder: 'GRN-2026-0211' })}
      ${field({ label: '采购订单号', name: 'po_no', placeholder: 'PO-2026-0001' })}
      ${field({ label: '收货数量', name: 'qty', type: 'number', value: 50 })}
      ${field({ label: '收货日期', name: 'received_on', type: 'date', value: '2026-10-12' })}
      ${field({ label: '批次', name: 'batch', value: 'B01' })}`,
    invoice: `${field({ label: '发票号', name: 'invoice_no', placeholder: 'INV-2026-0600' })}
      ${field({ label: '供应商名称（可写别名）', name: 'supplier_name', placeholder: '华翔' })}
      ${field({ label: '采购订单号', name: 'po_no', placeholder: 'PO-2026-0001' })}
      ${field({ label: '含税金额（元）', name: 'amount', placeholder: '1,234.56' })}
      ${field({ label: '税率', name: 'tax_rate', value: '13%' })}
      ${field({ label: '开票日期', name: 'issued_on', type: 'date', value: '2026-10-15' })}`,
  };
  if (!forms[tab]) {
    toast('供应商档案请用「新建供应商」');
    return;
  }
  const { root, close } = drawer({
    title: `导入${ENUMS.docKind[tab]}`,
    subtitle: '入库前先过算法 A 归一：供应商名、金额分、税率、开票日期',
    body: `<form id="import-form" style="display:grid;gap:12px">${forms[tab]}
      <div class="form-error" id="import-error"></div>
      <button class="btn accent" type="submit">归一并入库</button>
    </form>`,
  });
  root.querySelector('#import-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    const endpoint = { order: '/api/orders', receipt: '/api/receipts', invoice: '/api/invoices' }[tab];
    const body = {};
    Array.from(form.elements).forEach((el) => {
      if (!el.name) return;
      body[el.name] = el.type === 'number' ? Number(el.value) : el.value;
    });
    try {
      await api.post(endpoint, body);
      toast('已入库');
      close();
      await documentsPage.render(view, ctx);
    } catch (err) {
      root.querySelector('#import-error').textContent =
        err.code === 'CONFLICT' ? '自然键重复（409）：请核对单号或采集批次' : errorMessage(err);
    }
  });
}

export const documentsPage = {
  async render(view, ctx) {
    const tabsHtml = TABS.map(
      (tab) => `<button data-tab="${tab.key}" class="${state.tab === tab.key ? 'active' : ''}">${esc(tab.label)}</button>`,
    ).join('');
    let data;
    try {
      if (state.tab === 'supplier') {
        data = await api.get('/api/suppliers', { q: state.q, limit: 60 });
      } else if (state.tab === 'order') {
        data = await api.get('/api/orders', { q: state.q, supplier_id: state.supplierId, limit: 60 });
      } else if (state.tab === 'receipt') {
        data = await api.get('/api/receipts', { q: state.q, limit: 60 });
      } else {
        data = await api.get('/api/invoices', { q: state.q, status: state.status, limit: 60 });
      }
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => documentsPage.render(view, ctx));
      return;
    }
    const columns = {
      supplier: supplierColumns,
      order: orderColumns,
      receipt: receiptColumns,
      invoice: invoiceColumns,
    }[state.tab]();
    const importable = state.tab !== 'supplier' && can(ctx.user.role, state.tab === 'invoice' ? 'invoice:write' : 'order:write');
    view.innerHTML = `
      <section class="panel">
        <div class="tabs" id="doc-tabs">${tabsHtml}</div>
        <div class="panel-head">
          <h2>${esc(ENUMS.docKind[state.tab])}</h2>
          <div style="display:flex;gap:8px;align-items:center">
            <span class="meta">${data.total} 条</span>
            ${importable ? '<button class="btn sm accent" id="import-btn">导入</button>' : ''}
            ${state.tab === 'supplier' && can(ctx.user.role, 'supplier:write') ? '<button class="btn sm ghost" id="new-supplier">新建供应商</button>' : ''}
          </div>
        </div>
        <div class="panel-body">
          <div class="filter-bar" id="doc-filters">
            ${field({ label: '搜索', name: 'q', value: state.q, placeholder: '单号 / 名称 / 物料' })}
            ${state.tab === 'invoice' ? field({ label: '归一状态', name: 'status', value: state.status, options: [{ value: '', label: '全部' }, { value: 'valid', label: '已入池' }, { value: 'rejected', label: '归一失败' }] }) : ''}
            <div class="spacer"></div>
          </div>
        </div>
        ${
          data.items.length
            ? table({ columns, rows: data.items })
            : emptyState({ title: '没有单据', hint: '换筛选条件，或由主管导入一批数据。' })
        }
      </section>`;
    view.querySelectorAll('#doc-tabs button').forEach((node) =>
      node.addEventListener('click', () => {
        state.tab = node.dataset.tab;
        state.q = '';
        state.status = '';
        documentsPage.render(view, ctx);
      }),
    );
    const filters = view.querySelector('#doc-filters');
    filters?.addEventListener('change', () => {
      state.q = filters.querySelector('[name=q]').value.trim();
      if (filters.querySelector('[name=status]')) state.status = filters.querySelector('[name=status]').value;
      documentsPage.render(view, ctx);
    });
    filters?.querySelector('[name=q]')?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        state.q = event.target.value.trim();
        documentsPage.render(view, ctx);
      }
    });
    view.querySelectorAll('table.data tbody tr').forEach((row) => {
      row.addEventListener('click', () => {
        const item = data.items.find((entry) => String(entry.id) === row.dataset.id);
        if (!item) return;
        if (state.tab === 'supplier') return openTolerance(view, ctx, item);
        const entries = Object.entries(item)
          .filter(([key]) => !['id', 'supplier_id', 'material_code'].includes(key))
          .map(([key, value]) => [key, esc(typeof value === 'object' ? JSON.stringify(value) : value)]);
        const { root } = drawer({
          title: item.invoice_no || item.po_no || item.grn_no,
          subtitle: ENUMS.docKind[state.tab],
          body: kv(entries),
        });
        root.querySelector('[data-close]');
      });
    });
    view.querySelector('#import-btn')?.addEventListener('click', () => openImport(view, ctx));
    view.querySelector('#new-supplier')?.addEventListener('click', () => {
      const { root, close } = drawer({
        title: '新建供应商档案',
        subtitle: '编码 SUP-#### 全局唯一；重名/重码返回 409',
        body: `<form id="sup-form" style="display:grid;gap:12px">
          ${field({ label: '编码', name: 'code', placeholder: 'SUP-0047' })}
          ${field({ label: '名称', name: 'name', placeholder: '常州新锐冲压件有限公司' })}
          ${field({ label: '别名', name: 'alias', placeholder: '新锐,常州新锐' })}
          ${field({ label: '金额容差（分）', name: 'tolerance_amount_cents', type: 'number', value: 2 })}
          ${field({ label: '数量容差（%）', name: 'tolerance_qty_pct', type: 'number', value: 1 })}
          <div class="form-error" id="sup-error"></div>
          <button class="btn accent" type="submit">保存</button>
        </form>`,
      });
      root.querySelector('#sup-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const form = event.target;
        try {
          await api.post('/api/suppliers', {
            code: form.code.value.trim(),
            name: form.name.value.trim(),
            alias: form.alias.value.trim() || null,
            tolerance_amount_cents: Number(form.tolerance_amount_cents.value),
            tolerance_qty_pct: Number(form.tolerance_qty_pct.value),
          });
          toast('供应商已建档');
          close();
          await documentsPage.render(view, ctx);
        } catch (err) {
          root.querySelector('#sup-error').textContent =
            err.code === 'CONFLICT' ? '编码已存在（409）' : errorMessage(err);
        }
      });
    });
  },
};

export default documentsPage;
