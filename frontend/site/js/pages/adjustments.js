import { api } from '../api.js';
import { ENUMS, can, caseTone, statusTone } from '../config.js';
import { emptyState, errorBox, errorMessage, esc, fmtTime, table, toast } from '../ui.js';

function money(value) {
  return `¥${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;
}

export const adjustmentsPage = {
  async render(view, ctx) {
    let data;
    try {
      data = await api.get('/api/match-cases/adjustments');
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => adjustmentsPage.render(view, ctx));
      return;
    }
    const summary = data.summary || [];
    view.innerHTML = `
      <div class="voucher-head">
        <div class="title">调 整 单 与 导 出</div>
        <div class="meta">已处理 ${data.total} 条 · 差异额合计 <b class="mono">${money(
          summary.reduce((sum, item) => sum + Number(item.diff_amount || 0), 0),
        )}</b></div>
      </div>
      <div class="grid-3">
        ${['returned', 'written_off', 'accepted']
          .map((status) => {
            const row = summary.find((item) => item.status === status) || { count: 0, diff_amount: 0 };
            return `<section class="panel"><div class="panel-head"><h2>${esc(ENUMS.caseStatus[status])}</h2>
              <span class="meta">${row.count} 条</span></div>
              <div class="panel-body"><div class="stat" style="padding:0">
                <span class="v mono">${row.count}</span>
                <span class="hint">差异额 ${money(row.diff_amount)}</span>
              </div></div></section>`;
          })
          .join('')}
      </div>
      <section class="panel">
        <div class="panel-head">
          <h2>已处理差异工单</h2>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            ${
              can(ctx.user.role, 'export:read')
                ? `<button class="btn sm ghost" id="export-adjust">导出调整单</button>
                   <button class="btn sm ghost" id="export-cases">导出差异清单</button>
                   <button class="btn sm ghost" id="export-runs">导出运行记录</button>`
                : '<span class="mono muted">导出需要财务主管权限（analyst / viewer 会收到 403）</span>'
            }
          </div>
        </div>
        ${
          data.items.length
            ? table({
                rows: data.items,
                columns: [
                  { key: 'invoice_no', label: '发票号', className: 'mono' },
                  { key: 'po_no', label: '采购订单', className: 'mono' },
                  { key: 'supplier_name', label: '供应商' },
                  { key: 'match_status', label: '判定', render: (row) => `<span class="badge ${statusTone(row.match_status)}">${esc(ENUMS.matchStatus[row.match_status] || row.match_status)}</span>` },
                  { key: 'diff_amount', label: '差异额', className: 'num', render: (row) => money(row.diff_amount) },
                  { key: 'suggestion', label: '建议', render: (row) => esc(ENUMS.suggestion[row.suggestion] || row.suggestion) },
                  { key: 'status', label: '处理', render: (row) => `<span class="badge ${caseTone(row.status)}">${esc(ENUMS.caseStatus[row.status] || row.status)}</span>` },
                  { key: 'reviewer', label: '处理人', className: 'mono' },
                  { key: 'updated_at', label: '处理时间', render: (row) => fmtTime(row.updated_at) },
                ],
              })
            : emptyState({
                title: '还没有处理过的差异',
                hint: '去「差异工作台」打开一条差异，处理为退回重开 / 挂账 / 接受。',
              })
        }
      </section>`;
    const downloads = [
      ['#export-adjust', '/api/exports/adjustments.csv', 'adjustments.csv'],
      ['#export-cases', '/api/exports/cases.csv', 'match-cases.csv'],
      ['#export-runs', '/api/exports/runs.csv', 'match-runs.csv'],
    ];
    downloads.forEach(([selector, path, filename]) => {
      view.querySelector(selector)?.addEventListener('click', async () => {
        try {
          await api.download(path, filename);
          toast(`${filename} 已开始下载`);
        } catch (err) {
          toast(errorMessage(err), 'err');
        }
      });
    });
  },
};

export default adjustmentsPage;
