import { PERMISSIONS } from '../core/api.js';
import { BRAND_NAME } from '../config/brand.js';

const ROLE_LABELS = {
  platform_admin: '平台管理员',
  platform_operator: '平台运营',
  platform_auditor: '平台审计',
  supplier_engineer: '供应商工程师',
  buyer_operator: '客户操作员',
  buyer_auditor: '客户审计',
  admin: '平台管理员',
  operator: '平台运营',
  auditor: '平台审计',
};

const NAV_ITEMS = [
  { page: 'dashboard', title: 'Dashboard', group: '主线1：客户资产准备' },
  { page: 'assistant', title: 'Assistant', group: '主线1：客户资产准备' },
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
  guide: '接入与使用指南',
  assistant: '智能引导',
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

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function buildGroups(can) {
  const grouped = new Map();
  NAV_ITEMS.forEach((item) => {
    if (!can(item.page)) return;
    if (!grouped.has(item.group)) grouped.set(item.group, []);
    grouped.get(item.group).push(item);
  });
  return [...grouped.entries()].map(([title, items]) => ({ title, items }));
}

function primaryRoleLabel(user) {
  const role = String((user?.roles || [])[0] || user?.role || '');
  return ROLE_LABELS[role] || role || '-';
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

function renderCommandPalette(commandPalette) {
  const items = commandPalette?.items || [];
  const selectedIndex = commandPalette?.selectedIndex || 0;
  const listHtml = items.length
    ? items
      .map((item, idx) => `
        <button class="command-item ${idx === selectedIndex ? 'active' : ''}" data-command-index="${idx}" type="button">
          <span class="command-title">${esc(item.title || '-')}</span>
          <span class="command-desc">${esc(item.description || '')}</span>
          <span class="command-meta">${esc(item.shortcut || '')}</span>
        </button>
      `)
      .join('')
    : '<div class="command-empty">没有匹配的指令</div>';
  const visible = commandPalette?.open ? 'show' : '';
  return `
    <div id="commandOverlay" class="command-overlay ${visible}">
      <div class="command-panel">
        <div class="command-input-wrap">
          <span class="command-prefix">></span>
          <input id="commandPaletteInput" class="command-input" placeholder="输入指令或页面名，例如：资产、任务、发布..." value="${esc(commandPalette?.query || '')}" />
          <span class="command-kbd">Esc</span>
        </div>
        <div class="command-list">${listHtml}</div>
      </div>
    </div>
  `;
}

export function renderShell({ state, routeView, contentHtml, commandPalette }) {
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
          <div class="brand">${BRAND_NAME}</div>
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
            <button class="ghost topbar-guide-btn ${routeView.navPage === 'guide' ? 'active' : ''}" data-nav="guide">接入与使用指南</button>
            <label class="theme-switcher">
              <span>主题</span>
              <select id="themeSelect">
                <option value="classic_dark" ${state.visualTheme === 'classic_dark' ? 'selected' : ''}>夜幕金</option>
                <option value="chatgpt_light" ${state.visualTheme === 'chatgpt_light' ? 'selected' : ''}>ChatGPT 清透白</option>
                <option value="summer_cream" ${state.visualTheme === 'summer_cream' ? 'selected' : ''}>夏日奶油色</option>
              </select>
            </label>
            <button id="openCommandPaletteBtn" class="command-trigger" title="打开命令面板（Ctrl/Cmd + K）">
              <span>命令面板</span><kbd>Ctrl/⌘ K</kbd>
            </button>
            <span class="pill">${user?.username || '未登录'}</span>
            <span class="pill">${primaryRoleLabel(user)}</span>
            <span class="pill">${user?.tenant_code || user?.tenant_id || '-'}</span>
            <button id="logoutBtn" class="ghost">退出登录</button>
          </div>
        </header>
        <main class="page">
          ${contentHtml}
        </main>
        <div id="toast" class="toast"></div>
        ${renderCommandPalette(commandPalette)}
      </div>
    </div>
  `;
}

export function bindShellEvents(root, {
  onNavigate,
  onLogout,
  onBack,
  onThemeChange,
  onToggleSidebar,
  onOpenCommandPalette,
  onCloseCommandPalette,
  onCommandQueryChange,
  onCommandExecute,
}) {
  root.querySelectorAll('[data-nav]').forEach((btn) => {
    btn.addEventListener('click', () => onNavigate(btn.getAttribute('data-nav')));
  });
  root.querySelector('#homeBtn')?.addEventListener('click', () => onNavigate('dashboard'));
  root.querySelector('#backBtn')?.addEventListener('click', onBack);
  root.querySelector('#themeSelect')?.addEventListener('change', (event) => onThemeChange?.(event.target.value));
  root.querySelector('#toggleSidebarBtn')?.addEventListener('click', onToggleSidebar);
  root.querySelector('#logoutBtn')?.addEventListener('click', onLogout);
  root.querySelector('#openCommandPaletteBtn')?.addEventListener('click', onOpenCommandPalette);
  root.querySelector('#commandOverlay')?.addEventListener('click', (event) => {
    if (event.target?.id === 'commandOverlay') onCloseCommandPalette();
  });
  root.querySelector('#commandPaletteInput')?.addEventListener('input', (event) => {
    onCommandQueryChange(event.target.value);
  });
  root.querySelectorAll('[data-command-index]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = Number(btn.getAttribute('data-command-index') || 0);
      onCommandExecute(idx);
    });
  });
}
