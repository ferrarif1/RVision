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

const SHELL_SECTIONS = [
  {
    title: 'AI Workspace',
    mode: 'ai',
    items: [
      { page: 'ai', title: 'AI 首页' },
      { page: 'aiWorkflowUpload', title: '上传流程' },
      { page: 'aiWorkflowTrain', title: '训练流程' },
      { page: 'aiWorkflowDeploy', title: '发布流程' },
      { page: 'aiWorkflowResults', title: '结果流程' },
      { page: 'aiWorkflowTroubleshoot', title: '排障流程' },
    ],
  },
  {
    title: 'Expert Console',
    mode: 'expert',
    items: [
      { page: 'dashboard', title: 'Dashboard' },
      { page: 'assets', title: 'Assets' },
      { page: 'models', title: 'Models' },
      { page: 'training', title: 'Training' },
      { page: 'pipelines', title: 'Pipelines' },
      { page: 'tasks', title: 'Tasks' },
      { page: 'results', title: 'Results' },
      { page: 'devices', title: 'Devices' },
      { page: 'audit', title: 'Audit' },
      { page: 'settings', title: 'Settings' },
    ],
  },
];

const LABELS = {
  ai: 'AI Workspace',
  aiChat: 'AI 会话',
  aiWorkflowUpload: '上传流程',
  aiWorkflowTrain: '训练流程',
  aiWorkflowDeploy: '发布流程',
  aiWorkflowResults: '结果流程',
  aiWorkflowTroubleshoot: '排障流程',
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

function primaryRoleLabel(user) {
  const role = String((user?.roles || [])[0] || user?.role || '');
  return ROLE_LABELS[role] || role || '-';
}

function buildVisibleSections(can, currentMode) {
  return SHELL_SECTIONS
    .filter((section) => section.mode === currentMode || section.mode === 'expert')
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => can(item.page)),
    }))
    .filter((section) => section.items.length);
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
          <input id="commandPaletteInput" class="command-input" placeholder="输入指令或页面名，例如：AI、资产、训练、发布..." value="${esc(commandPalette?.query || '')}" />
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
  const collapsed = state.sidebarCollapsed ? 'sidebar-collapsed' : '';
  const visibleSections = buildVisibleSections(can, routeView.mode || 'expert');

  if (routeView.mode === 'ai') {
    return `
      <div class="ai-app-shell">
        <header class="ai-topbar">
          <button class="ai-brand ai-brand-button" id="openAiWorkspaceBtn" type="button">
            <span class="ai-brand-mark">V</span>
            <span class="ai-brand-copy">
              <strong>${BRAND_NAME}</strong>
              <span>AI 工作入口</span>
            </span>
          </button>
          <div class="ai-topbar-right">
            <button id="openExpertConsoleBtnTop" class="ghost" type="button">工作台</button>
            <button class="ghost" type="button" data-nav="guide">帮助</button>
            <button class="ghost" type="button" data-nav="settings">设置</button>
          </div>
        </header>
        <main class="ai-page">
          ${contentHtml}
        </main>
        <div id="toast" class="toast"></div>
        ${renderCommandPalette(commandPalette)}
      </div>
    `;
  }

  const navHtml = visibleSections.map((section) => {
    const items = section.items.map((item) => `
      <button class="nav-item ${routeView.navPage === item.page ? 'active' : ''}" data-nav="${item.page}">
        <span class="nav-label">${LABELS[item.page] || item.title}</span>
      </button>
    `).join('');
    return `<section class="nav-group"><h4>${section.title}</h4>${items}</section>`;
  }).join('');

  return `
    <div class="app-shell ${collapsed}">
      <aside class="sidebar">
        <div class="brand-row">
          <button class="brand brand-button" id="openAiWorkspaceBtn" type="button">${BRAND_NAME}</button>
          <button class="icon-btn" id="toggleSidebarBtn" title="切换侧栏">☰</button>
        </div>
        <div class="mode-switcher">
          <button id="openAiWorkspaceBtnInline" class="${routeView.mode === 'ai' ? 'primary' : 'ghost'}" type="button">AI Workspace</button>
          <button id="openExpertConsoleBtnInline" class="${routeView.mode === 'expert' ? 'primary' : 'ghost'}" type="button">Expert Console</button>
        </div>
        ${navHtml}
      </aside>
      <div class="main">
        <header class="topbar">
          <div class="topbar-left">
            ${routeView.showBack ? '<button id="backBtn" class="ghost">返回</button>' : ''}
            <div class="topbar-mode-badge">${esc(routeView.modeLabel || '控制台')}</div>
            <div class="breadcrumb">${renderBreadcrumb(routeView)}</div>
          </div>
          <div class="topbar-right">
            <button id="openAiWorkspaceBtnTop" class="ghost" type="button">AI Workspace</button>
            <button class="ghost topbar-guide-btn ${routeView.navPage === 'guide' ? 'active' : ''}" data-nav="guide">帮助</button>
            <button class="ghost" data-nav="settings" type="button">设置</button>
            <span class="pill topbar-user-pill">${user?.username || '未登录'}</span>
            <button id="logoutBtn" class="ghost">退出</button>
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
  onOpenAiWorkspace,
  onOpenExpertConsole,
}) {
  root.querySelectorAll('[data-nav]').forEach((btn) => {
    btn.addEventListener('click', () => onNavigate(btn.getAttribute('data-nav')));
  });
  ['#openAiWorkspaceBtn', '#openAiWorkspaceBtnInline', '#openAiWorkspaceBtnTop'].forEach((selector) => {
    root.querySelector(selector)?.addEventListener('click', () => onOpenAiWorkspace?.());
  });
  ['#openExpertConsoleBtnInline', '#openExpertConsoleBtnTop'].forEach((selector) => {
    root.querySelector(selector)?.addEventListener('click', () => onOpenExpertConsole?.());
  });
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
