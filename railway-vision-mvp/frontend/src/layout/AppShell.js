import { PERMISSIONS } from '../core/api.js';

const NAV_ITEMS = [
  { page: 'dashboard', title: 'Dashboard', group: '主线1：客户资产准备' },
  { page: 'assets', title: 'Assets', group: '主线1：客户资产准备' },
  { page: 'models', title: 'Models', group: '主线2：供应商模型交付' },
  { page: 'training', title: 'Training', group: '主线2：供应商模型交付' },
  { page: 'pipelines', title: 'Pipelines', group: '主线2：供应商模型交付' },
  { page: 'tasks', title: 'Tasks', group: '主线3：平台验证发布' },
  { page: 'results', title: 'Results', group: '主线3：平台验证发布' },
  { page: 'devices', title: 'Devices', group: '主线4：设备授权与运行' },
  { page: 'audit', title: 'Audit', group: '主线4：设备授权与运行' },
  { page: 'settings', title: 'Settings', group: '主线4：设备授权与运行' },
];

const LABELS = {
  dashboard: '工作台',
  assets: '资产',
  models: '模型',
  training: '训练',
  pipelines: '流水线',
  tasks: '任务',
  results: '结果',
  audit: '审计',
  devices: '设备',
  settings: '设置',
};

function buildGroups(can) {
  const grouped = new Map();
  NAV_ITEMS.forEach((item) => {
    if (!can(item.page)) return;
    if (!grouped.has(item.group)) grouped.set(item.group, []);
    grouped.get(item.group).push(item);
  });
  return [...grouped.entries()].map(([title, items]) => ({ title, items }));
}

function renderBreadcrumb(routeView) {
  const crumb = routeView?.breadcrumb || [{ label: routeView?.label || '页面' }];
  return crumb
    .map((item, idx) => {
      const label = item?.label || '-';
      if (item?.path && idx < crumb.length - 1) {
        return `<button class="crumb-link" data-nav="${item.path}">${label}</button>`;
      }
      return `<span class="crumb-current">${label}</span>`;
    })
    .join('<span class="crumb-sep">/</span>');
}

export function renderShell({ state, routeView, contentHtml }) {
  const user = state.user;
  const perms = state.permissions || new Set();
  const can = (page) => !PERMISSIONS[page] || perms.has(PERMISSIONS[page]);
  const groups = buildGroups(can);
  const collapsed = state.sidebarCollapsed ? 'sidebar-collapsed' : '';

  const navHtml = groups.map((g) => {
    const items = g.items.map((item) => `
      <button class="nav-item ${routeView.navPage === item.page ? 'active' : ''}" data-nav="${item.page}">
        <span class="nav-label">${LABELS[item.page] || item.title}</span>
      </button>
    `).join('');
    return `<section class="nav-group"><h4>${g.title}</h4>${items}</section>`;
  }).join('');

  return `
    <div class="app-shell ${collapsed}">
      <aside class="sidebar">
        <div class="brand-row">
          <div class="brand">VisionHub</div>
          <button class="icon-btn" id="toggleSidebarBtn" title="切换侧栏">☰</button>
        </div>
        ${navHtml}
      </aside>
      <div class="main">
        <header class="topbar">
          <div class="topbar-left">
            ${routeView.showBack ? '<button id="backBtn" class="ghost">返回</button>' : ''}
            <button id="homeBtn" class="ghost">工作台</button>
            <div class="breadcrumb">${renderBreadcrumb(routeView)}</div>
          </div>
          <div class="topbar-right">
            <span class="pill">${user?.username || '未登录'}</span>
            <span class="pill">${(user?.roles || [])[0] || user?.role || '-'}</span>
            <span class="pill">${user?.tenant_code || user?.tenant_id || '-'}</span>
            <button id="logoutBtn" class="ghost">退出登录</button>
          </div>
        </header>
        <main class="page">
          ${contentHtml}
        </main>
        <div id="toast" class="toast"></div>
      </div>
    </div>
  `;
}

export function bindShellEvents(root, { onNavigate, onLogout, onBack, onToggleSidebar }) {
  root.querySelectorAll('[data-nav]').forEach((btn) => {
    btn.addEventListener('click', () => onNavigate(btn.getAttribute('data-nav')));
  });
  root.querySelector('#homeBtn')?.addEventListener('click', () => onNavigate('dashboard'));
  root.querySelector('#backBtn')?.addEventListener('click', onBack);
  root.querySelector('#toggleSidebarBtn')?.addEventListener('click', onToggleSidebar);
  root.querySelector('#logoutBtn')?.addEventListener('click', onLogout);
}
