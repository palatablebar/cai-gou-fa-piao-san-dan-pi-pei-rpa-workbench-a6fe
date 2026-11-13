import { api } from '../api.js';
import { ENUMS, can, runTone } from '../config.js';
import { drawer, errorBox, errorMessage, esc, field, fmtTime, kv, table, toast } from '../ui.js';

const state = { status: '' };

function duration(run) {
  if (!run.started_at || !run.finished_at) return '—';
  const ms = new Date(run.finished_at) - new Date(run.started_at);
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`;
}

function openRun(view, ctx, run) {
  const metrics = run.metrics || {};
  const { root } = drawer({
    title: `匹配运行 ${run.run_no}`,
    subtitle: `账期 ${run.period} · ${ENUMS.trigger[run.trigger] || run.trigger}`,
    body: `${kv([
      ['状态', `<span class="badge ${runTone(run.status)}">${esc(ENUMS.runStatus[run.status] || run.status)}</span>`],
      ['操作人', esc(run.operator_email)],
      ['原始发票', esc(run.invoice_raw_count)],
      ['归一失败', esc(run.rejected_count)],
      ['三单一致', esc(run.matched_count)],
      ['差异条数', `<b>${esc(run.diff_count)}</b>`],
      ['耗时', duration(run)],
      ['开始', fmtTime(run.started_at)],
      ['结束', fmtTime(run.finished_at)],
    ])}
    <h3 style="margin:14px 0 8px;font-size:0.95rem">运行日志</h3>
    <pre class="code">${esc(run.log_text || '（无日志）')}</pre>
    <h3 style="margin:14px 0 8px;font-size:0.95rem">指标</h3>
    <pre class="code">${esc(JSON.stringify(metrics, null, 2))}</pre>`,
    footer: `<button class="btn accent" data-cases>查看本次差异</button>
      ${run.batch_id ? `<button class="btn ghost" data-batch>账期批次</button>` : ''}`,
  });
  root.querySelector('[data-cases]')?.addEventListener('click', () => {
    location.hash = `#/cases?run_id=${run.id}&scope=all`;
  });
  root.querySelector('[data-batch]')?.addEventListener('click', () => {
    location.hash = '#/batches';
  });
}

function openCreate(view, ctx) {
  const { root, close } = drawer({
    title: '发起三单匹配',
    subtitle: '提交到账期批次：同一批次键重试不新增运行；迟到发票并入只更新受影响的差异',
    body: `<form id="run-form" style="display:grid;gap:12px">
      ${field({ label: '账期', name: 'period', placeholder: '2026-10（留空=最新发票账期）' })}
      ${field({ label: '批次键', name: 'batch_key', placeholder: '留空 = period:账期；重试必须带同一个键' })}
      ${field({ label: '触发方式', name: 'trigger', value: 'manual', options: [{ value: 'manual', label: '手动' }, { value: 'schedule', label: '定时补偿' }] })}
      <div class="form-error" id="run-error"></div>
      <button class="btn accent" type="submit">开始匹配</button>
    </form>`,
  });
  root.querySelector('#run-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    button.textContent = '匹配中…';
    try {
      const run = await api.post('/api/match-runs', {
        period: form.period.value.trim() || null,
        batch_key: form.batch_key.value.trim() || null,
        trigger: 'manual',
      });
      toast(
        run.reused
          ? `批次 ${run.batch_no} 复用 v${run.version_no}（水位未变，未新增运行）`
          : `运行 ${run.run_no} 完成：一致 ${run.matched_count}，差异 ${run.diff_count}`,
      );
      close();
      await runsPage.render(view, ctx);
    } catch (err) {
      root.querySelector('#run-error').textContent = errorMessage(err);
      button.disabled = false;
      button.textContent = '开始匹配';
    }
  });
}

export const runsPage = {
  async render(view, ctx) {
    let data;
    try {
      data = await api.get('/api/match-runs', { status: state.status, limit: 50 });
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => runsPage.render(view, ctx));
      return;
    }
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>匹配运行</h2>
          <div style="display:flex;gap:8px;align-items:center">
            <span class="meta">${data.total} 次</span>
            ${can(ctx.user.role, 'run:create') ? '<button class="btn sm accent" id="new-run">发起匹配</button>' : ''}
          </div>
        </div>
        <div class="panel-body">
          <div class="filter-bar" id="run-filters">
            ${field({ label: '状态', name: 'status', value: state.status, options: [{ value: '', label: '全部' }, ...Object.entries(ENUMS.runStatus).map(([value, label]) => ({ value, label }))] })}
          </div>
        </div>
        ${table({
          rows: data.items,
          empty: { title: '还没有运行记录', hint: '发起一次匹配，50 条差异会进入差异工作台。' },
          columns: [
            { key: 'run_no', label: '运行号', className: 'mono' },
            { key: 'watermark', label: '水位', className: 'mono', render: (row) => (row.watermark ? esc(row.watermark.slice(0, 12)) : '—') },
            { key: 'period', label: '账期', className: 'mono' },
            { key: 'status', label: '状态', render: (row) => `<span class="badge ${runTone(row.status)}">${esc(ENUMS.runStatus[row.status] || row.status)}</span>` },
            { key: 'trigger', label: '触发', render: (row) => esc(ENUMS.trigger[row.trigger] || row.trigger) },
            { key: 'invoice_raw_count', label: '原始', className: 'num' },
            { key: 'rejected_count', label: '拒绝', className: 'num' },
            { key: 'matched_count', label: '一致', className: 'num' },
            { key: 'diff_count', label: '差异', className: 'num' },
            { key: 'operator_email', label: '操作人', className: 'mono' },
            { key: 'started_at', label: '开始时间', render: (row) => fmtTime(row.started_at) },
          ],
        })}
      </section>`;
    const filters = view.querySelector('#run-filters');
    filters?.addEventListener('change', () => {
      state.status = filters.querySelector('[name=status]').value;
      runsPage.render(view, ctx);
    });
    view.querySelectorAll('table.data tbody tr').forEach((row) => {
      row.addEventListener('click', () => {
        const run = data.items.find((item) => String(item.id) === row.dataset.id);
        if (run) openRun(view, ctx, run);
      });
    });
    view.querySelector('#new-run')?.addEventListener('click', () => openCreate(view, ctx));
  },
};

export default runsPage;
