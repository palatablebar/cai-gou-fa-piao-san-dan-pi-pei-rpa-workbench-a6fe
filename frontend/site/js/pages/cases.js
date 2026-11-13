import { api } from '../api.js';
import { ENUMS, can, caseTone, statusTone } from '../config.js';
import { drawer, emptyState, errorBox, errorMessage, esc, field, fmtTime, kv, table, toast } from '../ui.js';

const state = { runId: '', matchStatus: '', status: '', q: '', onlyDiffs: true };

function money(value) {
  if (value === null || value === undefined) return '—';
  return `¥${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;
}

function openCase(view, ctx, item) {
  const canReview = can(ctx.user.role, 'case:review') && item.match_status !== 'matched';
  const { root, close } = drawer({
    title: `${item.invoice_no} · ${ENUMS.matchStatus[item.match_status] || item.match_status}`,
    subtitle: `${item.po_no || '无采购订单'} · 采集批次 ${item.import_batch}`,
    body: `${kv([
      ['供应商', esc(item.supplier_name || '—')],
      ['物料', esc(item.material_code || '—')],
      ['判定', `<span class="badge ${statusTone(item.match_status)}">${esc(ENUMS.matchStatus[item.match_status] || item.match_status)}</span>`],
      ['处理建议', `<span class="badge info">${esc(ENUMS.suggestion[item.suggestion] || item.suggestion)}</span>`],
      ['发票金额', `<span class="mono">${money(item.invoice_amount)}</span>`],
      ['应付金额', `<span class="mono">${money(item.payable_amount)}</span>`],
      ['差异额', `<b class="mono" style="color:var(--stamp)">${money(item.diff_amount)}</b>`],
      ['订单单价', item.unit_price === null ? '<span class="mono muted">只读角色隐藏</span>' : `<span class="mono">${money(item.unit_price)}</span>`],
      ['数量 订单 / 收货', `<span class="mono">${item.qty_ordered} / ${item.qty_received}</span>`],
      ['发票税率 / 订单税率', `<span class="mono">${esc(item.payload.invoice_tax_rate_label || '—')} / ${esc(item.payload.po_tax_rate_label || '—')}</span>`],
      ['处理状态', `<span class="badge ${caseTone(item.status)}">${esc(ENUMS.caseStatus[item.status] || item.status)}</span>`],
      ['处理人', esc(item.reviewer || '—')],
      ['备注', esc(item.note || '—')],
      ['生成时间', fmtTime(item.created_at)],
    ])}
    <h3 style="margin:14px 0 8px;font-size:0.95rem">算法明细</h3>
    <pre class="code">${esc(JSON.stringify(item.payload || {}, null, 2))}</pre>`,
    footer: canReview
      ? `<form id="case-form" style="display:grid;gap:10px">
          ${field({
            label: '处理结果',
            name: 'status',
            value: item.status,
            options: ['returned', 'written_off', 'accepted'].map((value) => ({ value, label: ENUMS.caseStatus[value] })),
          })}
          ${field({ label: '处理备注', name: 'note', value: item.note || '', placeholder: '例如：已通知供应商退回重开' })}
          <button class="btn accent" type="submit">提交处理</button>
        </form>`
      : '<span class="mono muted">只读角色可查看差异，不能处理</span>',
  });
  root.querySelector('#case-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      await api.patch(`/api/match-cases/${item.id}/review`, {
        status: form.status.value,
        note: form.note.value.trim() || null,
      });
      toast(`已处理为「${ENUMS.caseStatus[form.status.value]}」`);
      close();
      await casesPage.render(view, ctx);
    } catch (err) {
      toast(errorMessage(err), 'err');
    }
  });
}

export const casesPage = {
  async render(view, ctx) {
    state.runId = ctx.query.run_id || state.runId;
    let data;
    let runs;
    try {
      [data, runs] = await Promise.all([
        api.get('/api/match-cases', {
          run_id: state.runId,
          match_status: state.matchStatus,
          status: state.status,
          q: state.q,
          only_diffs: state.onlyDiffs ? 'true' : '',
          limit: 80,
        }),
        api.get('/api/match-runs', { limit: 20 }),
      ]);
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => casesPage.render(view, ctx));
      return;
    }
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>差异工作台</h2>
          <div style="display:flex;gap:8px;align-items:center">
            <span class="meta">${data.total} 条</span>
            ${can(ctx.user.role, 'export:read') ? '<button class="btn sm seal" id="export-cases">导出 CSV</button>' : ''}
          </div>
        </div>
        <div class="panel-body">
          <div class="filter-bar" id="case-filters">
            ${field({ label: '运行', name: 'run_id', value: state.runId, options: [{ value: '', label: '全部运行' }, ...runs.items.map((run) => ({ value: run.id, label: `${run.run_no}（${run.period}）` }))] })}
            ${field({ label: '判定', name: 'match_status', value: state.matchStatus, options: [{ value: '', label: '全部判定' }, ...Object.entries(ENUMS.matchStatus).map(([value, label]) => ({ value, label }))] })}
            ${field({ label: '处理状态', name: 'status', value: state.status, options: [{ value: '', label: '全部处理' }, ...Object.entries(ENUMS.caseStatus).map(([value, label]) => ({ value, label }))] })}
            ${field({ label: '搜索', name: 'q', value: state.q, placeholder: '发票号 / PO / 供应商' })}
            ${field({ label: '只看差异', name: 'only_diffs', value: state.onlyDiffs ? 'true' : 'false', options: [{ value: 'true', label: '只看差异' }, { value: 'false', label: '含一致' }] })}
          </div>
        </div>
        ${
          data.items.length
            ? table({
                rows: data.items,
                columns: [
                  { key: 'invoice_no', label: '发票号', render: (row) => `<b class="mono">${esc(row.invoice_no)}</b><div class="mono muted">${esc(row.import_batch)}</div>` },
                  { key: 'supplier_name', label: '供应商' },
                  { key: 'po_no', label: '采购订单', className: 'mono' },
                  { key: 'match_status', label: '判定', render: (row) => `<span class="badge ${statusTone(row.match_status)}">${esc(ENUMS.matchStatus[row.match_status] || row.match_status)}</span>` },
                  { key: 'diff_amount', label: '差异额', className: 'num', render: (row) => (row.diff_amount_cents ? money(row.diff_amount) : '—') },
                  { key: 'suggestion', label: '建议', render: (row) => esc(ENUMS.suggestion[row.suggestion] || row.suggestion) },
                  { key: 'status', label: '处理', render: (row) => `<span class="badge ${caseTone(row.status)}">${esc(ENUMS.caseStatus[row.status] || row.status)}</span>` },
                  { key: 'reviewer', label: '处理人', render: (row) => esc(row.reviewer || '—') },
                ],
              })
            : emptyState({ title: '这个筛选下没有差异', hint: '换个运行或判定条件；一致记录可切换「含一致」查看。' })
        }
      </section>`;
    const filters = view.querySelector('#case-filters');
    filters?.addEventListener('change', () => {
      state.runId = filters.querySelector('[name=run_id]').value;
      state.matchStatus = filters.querySelector('[name=match_status]').value;
      state.status = filters.querySelector('[name=status]').value;
      state.onlyDiffs = filters.querySelector('[name=only_diffs]').value === 'true';
      casesPage.render(view, ctx);
    });
    filters?.querySelector('[name=q]')?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        state.q = event.target.value.trim();
        casesPage.render(view, ctx);
      }
    });
    view.querySelectorAll('table.data tbody tr').forEach((row) => {
      row.addEventListener('click', () => {
        const item = data.items.find((entry) => String(entry.id) === row.dataset.id);
        if (item) openCase(view, ctx, item);
      });
    });
    view.querySelector('#export-cases')?.addEventListener('click', async () => {
      try {
        await api.download(`/api/exports/cases.csv${state.runId ? `?run_id=${state.runId}` : ''}`, 'match-cases.csv');
        toast('差异清单已开始下载');
      } catch (err) {
        toast(errorMessage(err), 'err');
      }
    });
  },
};

export default casesPage;
