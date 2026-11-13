import { api } from '../api.js';
import { ENUMS, can } from '../config.js';
import {
  badge,
  drawer,
  emptyState,
  errorBox,
  errorMessage,
  esc,
  field,
  fmtTime,
  kv,
  statStrip,
  table,
  toast,
} from '../ui.js';

const filters = { period: '', status: '' };

/** 批次状态徽标：待切换 / 已切换 / 切换失败 / 已关账。 */
export function batchTone(status) {
  return {
    open: 'info',
    staging: 'pending warn',
    official: 'ok',
    failed: 'danger',
    closed: 'info',
  }[status] || 'info';
}

export function versionTone(status) {
  return {
    staging: 'pending warn',
    official: 'ok',
    superseded: 'info',
    rolled_back: 'danger',
    failed: 'danger',
  }[status] || 'info';
}

export function changeTone(kind) {
  return { new: 'ok', changed: 'warn', unchanged: 'info', removed: 'danger' }[kind] || 'info';
}

function money(cents) {
  return `¥${Number((cents || 0) / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`;
}

function diffLabel(before, after) {
  if (!before && !after) return '—';
  return `${Number((before || 0) / 100).toFixed(2)} → ${Number((after || 0) / 100).toFixed(2)}`;
}

function statusLabel(value) {
  return ENUMS.matchStatus[value] || ENUMS.caseStatus[value] || value || '—';
}

function fieldDiff(item, name) {
  const change = (item.changed_fields || {})[name];
  if (!change) return esc(statusLabel((item.after && item.after[name]) || '—'));
  if (name === 'diff_amount_cents') {
    return `<span class="mono">${esc(diffLabel(change.before, change.after))}</span>`;
  }
  return `<span class="mono">${esc(statusLabel(change.before))} → ${esc(statusLabel(change.after))}</span>`;
}

function changeColumns() {
  return [
    {
      key: 'invoice_no',
      label: '发票号',
      render: (row) => `<b class="mono">${esc(row.invoice_no)}</b><div class="mono muted">${esc(
        (row.after && row.after.import_batch) || (row.before && row.before.import_batch) || '',
      )}</div>`,
    },
    { key: 'po_no', label: '采购订单', className: 'mono', render: (row) => esc((row.after && row.after.po_no) || (row.before && row.before.po_no) || '—') },
    { key: 'change_kind', label: '变化', render: (row) => badge(changeTone(row.change_kind), row.change_kind_label || row.change_kind) },
    { key: 'before', label: '判定（前）', render: (row) => fieldDiff(row, 'match_status') },
    { key: 'after', label: '判定（后）', render: (row) => (row.after ? esc(statusLabel(row.after.match_status)) : '<span class="badge danger">退出批次</span>') },
    { key: 'diff_amount_cents', label: '差异额（前→后）', className: 'num', render: (row) => fieldDiff(row, 'diff_amount_cents') },
    {
      key: 'status',
      label: '人工处理',
      render: (row) =>
        row.after
          ? badge({ pending: 'pending warn', returned: 'danger', written_off: 'info', accepted: 'ok' }[row.after.status] || 'info',
              ENUMS.caseStatus[row.after.status] || row.after.status)
          : '—',
    },
  ];
}

function verifyPanel(verification) {
  if (!verification) return '';
  return `<div class="panel" style="margin:0">
    <div class="panel-head"><h2>切换前核对</h2><span class="meta">${
      verification.ok ? badge('ok', '全部通过') : badge('danger', '未通过，禁止切换')
    }</span></div>
    <div class="panel-body">
      <div class="kv">
        <dt>当前位置水位</dt><dd class="mono">${esc(verification.watermark_label || '—')}</dd>
      </div>
      <div class="table-wrap" style="margin-top:8px"><table class="data"><thead><tr>
        <th>核对项</th><th>应等于</th><th>实际</th><th>结论</th>
      </tr></thead><tbody>
        ${verification.checks
          .map(
            (check) => `<tr><td>${esc(check.label)}</td>
              <td class="mono">${esc(JSON.stringify(check.expected))}</td>
              <td class="mono">${esc(JSON.stringify(check.actual))}</td>
              <td>${check.ok ? badge('ok', '一致') : badge('danger', '不一致')}</td></tr>`,
          )
          .join('')}
      </tbody></table></div>
    </div>
  </div>`;
}

function openChanges(view, ctx, batch, version) {
  const { root, close } = drawer({
    title: `前后差异 · ${batch.batch_no} ${version.label}`,
    subtitle: `账期 ${batch.period} · 水位 ${version.watermark_label} · ${
      (version.change_summary && version.change_summary.affected) || 0
    } 条受影响`,
    body: `<div id="change-body"><div class="empty"><div class="mark">读取差异…</div></div></div>`,
    footer: `<button class="btn ghost" data-verify>重新核对</button>
      ${can(ctx.user.role, 'batch:switch') && version.status === 'staging' ? '<button class="btn accent" data-switch>核对并切换</button>' : ''}`,
  });
  const body = root.querySelector('#change-body');
  const load = async (kind = '') => {
    try {
      const data = await api.get(`/api/match-batches/${batch.id}/changes`, {
        version_id: version.id,
        change_kind: kind,
        limit: 300,
      });
      const summary = data.summary || {};
      body.innerHTML = `
        ${statStrip([
          { label: '新增', value: summary.new || 0, hint: '迟到发票并入' },
          { label: '判定变化', value: summary.changed || 0, hint: '只更新受影响差异' },
          { label: '未变化', value: summary.unchanged || 0, hint: '原结果保留' },
          { label: '退出批次', value: summary.removed || 0, hint: '上一版有、本版无' },
        ])}
        ${
          summary.baseline
            ? emptyState({ title: '首个版本没有对比基准', hint: '作为基线快照，下次迟到发票到达时再比较前后差异。' })
            : data.items.length
              ? table({ rows: data.items, columns: changeColumns() })
              : emptyState({ title: '这个筛选下没有变化', hint: '未受影响的差异不会进入前后差异清单。' })
        }
        <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
          ${['', 'new', 'changed', 'removed']
            .map(
              (kind) =>
                `<button class="btn sm ghost" data-kind="${kind}">${
                  kind ? ENUMS.changeKind[kind] : '全部变化'
                }</button>`,
            )
            .join('')}
        </div>`;
      body.querySelectorAll('[data-kind]').forEach((node) =>
        node.addEventListener('click', () => load(node.dataset.kind)),
      );
    } catch (err) {
      body.innerHTML = errorBox(errorMessage(err));
    }
  };
  load();

  const footer = root.querySelector('.drawer-foot');
  if (footer) {
    footer.querySelector('[data-verify]')?.addEventListener('click', async () => {
      try {
        const data = await api.get(`/api/match-batches/${batch.id}/verify`, { version_id: version.id });
        toast(data.verification.ok ? '水位核对通过，可切换' : '水位核对未通过', data.verification.ok ? '' : 'err');
      } catch (err) {
        toast(errorMessage(err), 'err');
      }
    });
    footer.querySelector('[data-switch]')?.addEventListener('click', async (event) => {
      event.target.disabled = true;
      try {
        const result = await doSwitch(ctx, batch, version);
        toast(`已切换正式版 ${result.batch.official_version.label}`);
        close();
        await batchesPage.render(view, ctx);
      } catch (err) {
        event.target.disabled = false;
        toast(errorMessage(err), 'err');
      }
    });
  }
}

async function doSwitch(ctx, batch, version) {
  return api.post(`/api/match-batches/${batch.id}/switch`, { version_id: version.id });
}

async function openBatch(view, ctx, batchSummary) {
  let batch = batchSummary;
  try {
    // 列表只带版本摘要；详情接口附带当前等待版本的水位核对结果
    batch = await api.get(`/api/match-batches/${batchSummary.id}`);
  } catch {
    batch = batchSummary;
  }
  const official = batch.official_version;
  const staging = batch.staging_version;
  const verification = batch.verification;
  const { root, close } = drawer({
    title: `${batch.batch_no} · ${ENUMS.batchStatus[batch.status] || batch.status}`,
    subtitle: `账期 ${batch.period} · 批次键 ${batch.batch_key}`,
    body: `
      ${statStrip([
        { label: '批次状态', value: ENUMS.batchStatus[batch.status] || batch.status, hint: `水位 ${batch.watermark_label}` },
        { label: '来源单据', value: Object.values(batch.source_counts || {}).slice(0, 2).join(' / '), hint: '订单 / 收货 / 发票' },
        { label: '正式版', value: official ? official.label : '—', hint: official ? `${official.counts.diffs} 条差异` : '尚未切换' },
        { label: '待切换版', value: staging ? staging.label : '—', hint: staging ? `影响 ${staging.change_summary.affected} 条` : '无暂存版本' },
      ])}
      ${verifyPanel(verification)}
      <h3 style="margin:14px 0 8px;font-size:0.95rem">版本历史</h3>
      <div class="table-wrap"><table class="data"><thead><tr>
        <th>版本</th><th>状态</th><th>水位</th><th>来源</th><th>差异</th><th>受影响</th><th>建立</th>
      </tr></thead><tbody>
        ${(batch.versions || [])
          .map(
            (version) => `<tr data-version="${version.id}">
              <td><b class="mono">${esc(version.label)}</b></td>
              <td>${badge(versionTone(version.status), version.status_label)}</td>
              <td class="mono">${esc(version.watermark_label)}</td>
              <td class="mono">${esc((version.watermark_detail || {}).invoices || '—')} 张发票</td>
              <td class="num">${esc((version.counts || {}).diffs ?? '—')}</td>
              <td class="num">${esc(version.change_summary?.affected ?? '—')}</td>
              <td class="mono">${fmtTime(version.created_at)}</td>
            </tr>`,
          )
          .join('')}
      </tbody></table></div>
      ${batch.versions?.some((version) => version.error) ? `<pre class="code">${esc(batch.versions.map((v) => (v.error ? `${v.label}: ${v.error}` : '')).filter(Boolean).join('\n'))}</pre>` : ''}
    `,
    footer: `<button class="btn ghost" data-close>关闭</button>
      ${can(ctx.user.role, 'batch:switch') && staging ? '<button class="btn ghost" data-recompute>重新生成暂存版</button><button class="btn accent" data-switch>核对并切换</button>' : ''}
      ${can(ctx.user.role, 'batch:switch') && official && batch.versions?.length > 1 ? '<button class="btn ghost" data-rollback>回滚上一版</button>' : ''}`,
  });

  root.querySelectorAll('[data-version]').forEach((row) => {
    row.addEventListener('click', () => {
      const version = batch.versions.find((item) => String(item.id) === row.dataset.version);
      if (version) openChanges(view, ctx, batch, version);
    });
  });
  root.querySelector('[data-switch]')?.addEventListener('click', async (event) => {
    event.target.disabled = true;
    try {
      const result = await doSwitch(ctx, batch, staging);
      toast(`已切换正式版 ${result.batch.official_version.label}`);
      close();
      await batchesPage.render(view, ctx);
    } catch (err) {
      event.target.disabled = false;
      toast(errorMessage(err), 'err');
    }
  });
  root.querySelector('[data-recompute]')?.addEventListener('click', async (event) => {
    event.target.disabled = true;
    try {
      await api.post(`/api/match-batches/${batch.id}/recompute`, { trigger: 'manual', force: true });
      toast('已重新生成暂存版');
      close();
      await batchesPage.render(view, ctx);
    } catch (err) {
      event.target.disabled = false;
      toast(errorMessage(err), 'err');
    }
  });
  root.querySelector('[data-rollback]')?.addEventListener('click', async (event) => {
    event.target.disabled = true;
    try {
      const result = await api.post(`/api/match-batches/${batch.id}/rollback`, {});
      toast(`已回滚到 ${result.version.label}，处理意见保留`);
      close();
      await batchesPage.render(view, ctx);
    } catch (err) {
      event.target.disabled = false;
      toast(errorMessage(err), 'err');
    }
  });
}

function openCreate(view, ctx) {
  const { root, close } = drawer({
    title: '处理账期批次',
    subtitle: '同一批次键重试不会新增运行或单据；迟到发票并入后生成新版本，只更新受影响的差异',
    body: `<form id="batch-form" style="display:grid;gap:12px">
      ${field({ label: '账期', name: 'period', placeholder: '2026-10（留空=最新发票账期）' })}
      ${field({ label: '批次键', name: 'batch_key', placeholder: '留空 = period:账期；重试必须带同一个键' })}
      ${field({ label: '触发方式', name: 'trigger', value: 'manual', options: [{ value: 'manual', label: '手动' }, { value: 'schedule', label: '定时补偿' }] })}
      ${field({ label: '强制重算', name: 'force', value: 'false', options: [{ value: 'false', label: '水位未变则复用' }, { value: 'true', label: '强制生成新版本' }] })}
      <div class="form-error" id="batch-error"></div>
      <button class="btn accent" type="submit">提交批次</button>
    </form>`,
  });
  root.querySelector('#batch-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    button.textContent = '处理中…';
    try {
      const result = await api.post('/api/match-batches', {
        period: form.period.value.trim() || null,
        batch_key: form.batch_key.value.trim() || null,
        trigger: 'manual',
        force: form.force.value === 'true',
      });
      toast(
        result.reused
          ? `批次 ${result.batch.batch_no} 复用 ${result.version.label}（水位未变，未新增运行）`
          : `批次 ${result.batch.batch_no} 生成 ${result.version.label}，影响 ${result.version.change_summary.affected} 条`,
      );
      close();
      await batchesPage.render(view, ctx);
    } catch (err) {
      root.querySelector('#batch-error').textContent = errorMessage(err);
      button.disabled = false;
      button.textContent = '提交批次';
    }
  });
}

export const batchesPage = {
  async render(view, ctx) {
    let data;
    let options;
    try {
      [data, options] = await Promise.all([
        api.get('/api/match-batches', { period: filters.period, status: filters.status, limit: 50 }),
        api.get('/api/match-batches/options'),
      ]);
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => batchesPage.render(view, ctx));
      return;
    }
    const officialCount = data.items.filter((item) => item.status === 'official').length;
    const stagingCount = data.items.filter((item) => item.status === 'staging').length;
    const failedCount = data.items.filter((item) => item.status === 'failed').length;
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>账期批次</h2>
          <div style="display:flex;gap:8px;align-items:center">
            <span class="meta">${data.total} 个批次</span>
            ${can(ctx.user.role, 'run:create') ? '<button class="btn sm accent" id="new-batch">处理批次</button>' : ''}
          </div>
        </div>
        <div class="panel-body">
          ${statStrip([
            { label: '待切换', value: stagingCount, hint: '暂存版核对后切换' },
            { label: '已切换', value: officialCount, hint: '关账用正式版' },
            { label: '切换失败', value: failedCount, hint: '已恢复上一版' },
            { label: '来源水位', value: data.items[0]?.watermark_label || '—', hint: '来源单据指纹' },
          ])}
          <div class="filter-bar" id="batch-filters">
            ${field({ label: '账期', name: 'period', value: filters.period, options: [{ value: '', label: '全部账期' }, ...data.periods.map((period) => ({ value: period, label: period }))] })}
            ${field({ label: '状态', name: 'status', value: filters.status, options: [{ value: '', label: '全部状态' }, ...options.statuses] })}
            <div class="spacer"></div>
          </div>
        </div>
        ${
          data.items.length
            ? table({
                rows: data.items,
                columns: [
                  { key: 'batch_no', label: '批次号', className: 'mono' },
                  { key: 'period', label: '账期', className: 'mono' },
                  { key: 'status', label: '状态', render: (row) => badge(batchTone(row.status), row.status_label) },
                  { key: 'watermark_label', label: '来源水位', className: 'mono', render: (row) => esc(row.watermark_label) },
                  {
                    key: 'source_counts',
                    label: '来源单据',
                    className: 'mono',
                    render: (row) => `PO ${row.source_counts?.orders || 0} · GRN ${row.source_counts?.receipts || 0} · INV ${row.source_counts?.invoices_valid || 0}`,
                  },
                  {
                    key: 'official_version',
                    label: '正式版',
                    render: (row) =>
                      row.official_version
                        ? `<b class="mono">${esc(row.official_version.label)}</b><div class="mono muted">${row.official_version.counts.diffs} 条差异</div>`
                        : '<span class="muted">—</span>',
                  },
                  {
                    key: 'staging_version',
                    label: '待切换',
                    render: (row) =>
                      row.staging_version
                        ? badge('pending warn', row.staging_version.label) +
                          `<div class="mono muted">影响 ${row.staging_version.change_summary.affected} 条</div>`
                        : '—',
                  },
                  {
                    key: 'change_summary',
                    label: '前后差异',
                    render: (row) => {
                      const summary = (row.staging_version || row.official_version)?.change_summary || {};
                      return summary.baseline
                        ? '<span class="muted">基线快照</span>'
                        : `<span class="mono">+${summary.new || 0} 新增 / ~${summary.changed || 0} 变化 / -${summary.removed || 0} 退出</span>`;
                    },
                  },
                  { key: 'updated_at', label: '更新', render: (row) => fmtTime(row.updated_at) },
                ],
              })
            : emptyState({ title: '还没有账期批次', hint: '点「处理批次」按账期建立批次，重试同一批次键不会重复生成运行。' })
        }
      </section>`;
    const bar = view.querySelector('#batch-filters');
    bar?.addEventListener('change', () => {
      filters.period = bar.querySelector('[name=period]').value;
      filters.status = bar.querySelector('[name=status]').value;
      batchesPage.render(view, ctx);
    });
    view.querySelectorAll('table.data tbody tr').forEach((row) => {
      row.addEventListener('click', () => {
        const batch = data.items.find((item) => String(item.id) === row.dataset.id);
        if (batch) openBatch(view, ctx, batch);
      });
    });
    view.querySelector('#new-batch')?.addEventListener('click', () => openCreate(view, ctx));
  },
};

export default batchesPage;
