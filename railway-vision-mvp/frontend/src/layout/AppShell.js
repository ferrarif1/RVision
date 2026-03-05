import { PERMISSIONS } from '../core/api.js';

const GROUPS = [
  { title: '主线1：准备资产', pages: ['dashboard', 'assets'] },
  { title: '主线2：交付模型', pages: ['models', 'pipelines'] },
  { title: '主线3：执行结果', pages: ['tasks', 'results'] },
  { title: '主线4：治理运营', pages: ['audit', 'devices', 'settings'] },
];

const LABELS = {
  dashboard: '主页', assets: '资产', models: '模型', pipelines: '流水线',
  tasks: '任务', results: '结果', audit: '审计', devices: '设备', settings: '设置',
};

export function renderShell({ state, route, onNavigate, onLogout, contentHtml }) {
  const user = state.user;
  const perms = state.permissions || new Set();
  const can = (page) => !PERMISSIONS[page] || perms.has(PERMISSIONS[page]);

  const navHtml = GROUPS.map((g) => {
    const items = g.pages.filter(can).map((page) => `
      <button class="nav-item ${route.path === page ? 'active' : ''}" data-nav="${page}">${LABELS[page]}</button>
    `).join('');
    return items ? `<section class="nav-group"><h4>${g.title}</h4>${items}</section>` : '';
  }).join('');

  return `
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">VisionHub</div>
        ${navHtml}
      </aside>
      <div class="main">
        <header class="topbar">
          <button id="homeBtn" class="ghost">回到主页</button>
          <div class="topbar-right">
            <span class="pill">${user?.username || '未登录'}</span>
            <span class="pill">${user?.role || '-'}</span>
            <span class="pill">${user?.tenant_id || '-'}</span>
            <button id="logoutBtn" class="ghost">退出登录</button>
          </div>
        </header>
        <main class="page">${contentHtml}</main>
      </div>
    </div>
  `;
}

export function bindShellEvents(root, onNavigate, onLogout) {
  root.querySelectorAll('[data-nav]').forEach((btn) => {
    btn.addEventListener('click', () => onNavigate(btn.getAttribute('data-nav')));
  });
  root.querySelector('#homeBtn')?.addEventListener('click', () => onNavigate('dashboard'));
  root.querySelector('#logoutBtn')?.addEventListener('click', onLogout);
}
