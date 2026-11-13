import { api } from '../api.js';
import { BRAND, ENUMS, can } from '../config.js';
import { barList, emptyState, errorBox, errorMessage, fmtTime, statStrip, trendChart } from '../ui.js';

export const overviewPage = {
  async render(view, ctx) {
    view.innerHTML = '<div class="empty"><div class="mark">读取本期凭证…</div></div>';
    try {
      const data = await api.get('/api/overview');
      const latest = data.latest_run;
      view.innerHTML = `
        <div class="voucher-head">
          <div class="title">本 期 核 对 汇 总</div>
          <div class="meta">
            账期 <b class="mono">${data.period}</b> · 供应商 <span class="mono">${data.suppliers_total}</span> ·
            发票 <span class="mono">${data.invoices_total}</span> ·
            差异额 <b class="mono">¥${Number(data.diff_amount_total).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</b>
          </div>
        </div>
        ${statStrip([
          { label: '供应商档案', value: data.suppliers_total, hint: `${data.orders_total} 张 PO / ${data.receipts_total} 张 GRN` },
          { label: '本期发票', value: data.invoices_total, hint: `归一失败 ${data.rejected_total} 张（留痕不入池）` },
          { label: '三单一致', value: data.matched_total, hint: latest ? `最近运行 ${latest.run_no}` : '尚未运行' },
          { label: '差异工单', value: data.cases_total - data.matched_total, hint: `待处理 ${data.pending_total} 条` },
        ])}
        <div class="grid-2">
          <section class="panel">
            <div class="panel-head"><h2>差异结构</h2><span class="meta">match_status</span></div>
            <div class="panel-body">${
              data.status_structure.some((item) => item.count)
                ? barList(data.status_structure)
                : emptyState({ title: '还没有匹配结果', hint: '去「匹配运行」发起一次。' })
            }</div>
          </section>
          <section class="panel">
            <div class="panel-head"><h2>处理进度</h2><span class="meta">case_status</span></div>
            <div class="panel-body">${barList(data.case_structure, 'ok')}</div>
          </section>
        </div>
        <div class="grid-2">
          <section class="panel">
            <div class="panel-head"><h2>近 7 天运行</h2><span class="meta">runs / day</span></div>
            <div class="panel-body">${trendChart(data.trend)}</div>
          </section>
          <section class="panel">
            <div class="panel-head"><h2>最近一次运行</h2><span class="meta">latest</span></div>
            <div class="panel-body">
              ${
                latest
                  ? `<div class="kv">
                      <dt>运行号</dt><dd class="mono">${latest.run_no}</dd>
                      <dt>账期</dt><dd class="mono">${latest.period}</dd>
                      <dt>状态</dt><dd>${latest.status_label}</dd>
                      <dt>开始</dt><dd>${fmtTime(latest.started_at)}</dd>
                      <dt>一致 / 差异</dt><dd class="mono">${latest.matched_count} / ${latest.diff_count}</dd>
                      <dt>后台任务</dt><dd>${data.worker_alive ? '在岗（心跳正常）' : '心跳超时'}</dd>
                    </div>
                    <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
                      <button class="btn sm ghost" data-go="#/cases?run_id=${latest.id}">查看本次差异</button>
                      <button class="btn sm ghost" data-go="#/runs">运行记录</button>
                      ${can(ctx.user.role, 'export:read') ? '<button class="btn sm seal" data-export>导出差异清单</button>' : ''}
                    </div>`
                  : emptyState({ title: '还没有运行记录', hint: '先在「单据中心」确认三单，再发起匹配。' })
              }
            </div>
          </section>
        </div>
        <section class="panel">
          <div class="panel-head"><h2>差异类别</h2><span class="meta">diff_type · 差异额 = 发票金额 − 应付金额</span></div>
          <div class="panel-body">${barList(data.type_structure.filter((item) => item.key !== 'none'))}</div>
        </section>`;
      view.querySelectorAll('[data-go]').forEach((node) =>
        node.addEventListener('click', () => {
          location.hash = node.dataset.go;
        }),
      );
      view.querySelector('[data-export]')?.addEventListener('click', async () => {
        try {
          await api.download(`/api/exports/cases.csv${latest ? `?run_id=${latest.id}` : ''}`, 'match-cases.csv');
        } catch (err) {
          console.error(err);
        }
      });
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => overviewPage.render(view, ctx));
    }
  },
};

export default overviewPage;
