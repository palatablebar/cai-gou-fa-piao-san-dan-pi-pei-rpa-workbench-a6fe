import { api } from '../api.js';
import { session } from '../store.js';
import { BRAND } from '../config.js';
import { errorMessage, esc, toast } from '../ui.js';

export const loginPage = {
  async render(root, ctx) {
    root.className = 'login-host';
    root.innerHTML = `
      <div class="login">
        <section class="login-brief punch-rail">
          <div class="voucher-cover">
            <div class="no">${esc(BRAND.voucherNo)}</div>
            <h1>${esc(BRAND.title)}<br /><em>三单核对单</em></h1>
            <p class="tagline">${esc(BRAND.loginLead)}</p>
            <div class="eyebrow">${esc(BRAND.edition)} · 联纬财务共享中心</div>
          </div>
          <div class="brief-points">
            ${BRAND.loginPoints
              .map(([no, text]) => `<div class="brief-point"><i>${esc(no)}</i><span>${esc(text)}</span></div>`)
              .join('')}
          </div>
        </section>
        <section class="login-form-wrap">
          <form class="login-card" id="login-form" novalidate>
            <div>
              <div class="brand">${esc(BRAND.title)}</div>
              <div class="sub">内部账号登录 · 三个演示账号权限不同，页面与按钮随角色变化。</div>
            </div>
            <div class="field">
              <label for="email">邮箱 / EMAIL</label>
              <input id="email" name="email" type="email" autocomplete="username" value="admin@${esc(BRAND.short)}.io" required />
            </div>
            <div class="field">
              <label for="password">密码 / PASSWORD</label>
              <input id="password" name="password" type="password" autocomplete="current-password" value="Demo@2026" required />
            </div>
            <div class="form-error" id="login-error" role="alert"></div>
            <button class="btn accent" id="login-submit" type="submit">进入应付凭证台</button>
            <div class="login-hint">
              演示账号（密码 <code>Demo@2026</code>）：<br />
              <code>admin@${esc(BRAND.short)}.io</code> 财务主管 · <code>analyst@${esc(BRAND.short)}.io</code> 应付会计 ·
              <code>viewer@${esc(BRAND.short)}.io</code> 只读
            </div>
          </form>
        </section>
      </div>`;

    const form = root.querySelector('#login-form');
    const errorNode = root.querySelector('#login-error');
    const submit = root.querySelector('#login-submit');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      errorNode.textContent = '';
      submit.disabled = true;
      submit.textContent = '正在验证…';
      try {
        const result = await api.post('/api/auth/login', {
          email: form.email.value.trim(),
          password: form.password.value,
        });
        session.set(result.access_token, result.user);
        toast(`欢迎回来，${result.user.display_name}`);
        location.hash = '#/overview';
        await ctx.reload();
      } catch (err) {
        errorNode.textContent = err.code === 'AUTH_INVALID' ? '账号或密码不正确' : errorMessage(err);
      } finally {
        submit.disabled = false;
        submit.textContent = '进入应付凭证台';
      }
    });
  },
};

export default loginPage;
