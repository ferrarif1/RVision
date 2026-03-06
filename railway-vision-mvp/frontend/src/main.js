import { createStore } from './core/store.js';
import { createRouter } from './core/router.js';
import { api, apiPost } from './core/api.js';
import { renderShell, bindShellEvents } from './layout/AppShell.js';
import { getPage } from './pages/index.js';

const root = document.getElementById('app');

const routes = [
  { name: 'login', pattern: 'login', requiresAuth: false, label: '登录', navPage: null },
  { name: 'dashboard', pattern: 'dashboard', requiresAuth: true, permission: 'dashboard.view', label: '工作台', navPage: 'dashboard' },
  { name: 'assets', pattern: 'assets', requiresAuth: true, permission: 'asset.upload', label: '资产', navPage: 'assets' },
  { name: 'models', pattern: 'models', requiresAuth: true, permission: 'model.view', label: '模型', navPage: 'models' },
  { name: 'training', pattern: 'training', requiresAuth: true, permission: 'training.job.view', label: '训练', navPage: 'training' },
  { name: 'pipelines', pattern: 'pipelines', requiresAuth: true, permission: 'model.view', label: '流水线', navPage: 'pipelines' },
  { name: 'tasks', pattern: 'tasks', requiresAuth: true, permission: 'task.create', label: '任务', navPage: 'tasks' },
  { name: 'taskDetail', pattern: 'tasks/:task_id', requiresAuth: true, permission: 'task.create', label: '任务详情', navPage: 'tasks', parentPath: 'tasks' },
  { name: 'results', pattern: 'results', requiresAuth: true, permission: 'result.read', label: '结果', navPage: 'results' },
  { name: 'resultTask', pattern: 'results/task/:task_id', requiresAuth: true, permission: 'result.read', label: '结果详情', navPage: 'results', parentPath: 'results' },
  { name: 'audit', pattern: 'audit', requiresAuth: true, permission: 'audit.read', label: '审计', navPage: 'audit' },
  { name: 'devices', pattern: 'devices', requiresAuth: true, permission: 'device.read', label: '设备', navPage: 'devices' },
  { name: 'settings', pattern: 'settings', requiresAuth: true, permission: 'settings.view', label: '设置', navPage: 'settings' },
  { name: '403', pattern: '403', requiresAuth: true, label: '无权限', navPage: 'dashboard', parentPath: 'dashboard' },
  { name: '404', pattern: '404', requiresAuth: false, label: '页面不存在', navPage: 'dashboard', parentPath: 'dashboard' },
];

const NAV_COMMANDS = [
  { path: 'dashboard', title: '工作台', description: '查看四条主线的整体状态', keywords: 'dashboard home 总览 主线' },
  { path: 'assets', title: '资产中心', description: '上传和筛选图片/视频资产', keywords: 'asset upload 资产 上传' },
  { path: 'models', title: '模型中心', description: '提交模型、审批、发布时间线', keywords: 'model release approve 模型 审批 发布' },
  { path: 'training', title: '训练管理', description: '训练作业与 worker 资源', keywords: 'training worker 训练 作业' },
  { path: 'pipelines', title: '流水线', description: '注册和管理推理流水线', keywords: 'pipeline 流水线 路由' },
  { path: 'tasks', title: '任务执行', description: '创建推理任务并跟踪状态', keywords: 'task infer 任务 推理' },
  { path: 'results', title: '结果中心', description: '查看任务输出与摘要', keywords: 'result 结果 输出' },
  { path: 'devices', title: '设备授权', description: '设备上线、授权与状态', keywords: 'device license 设备 授权' },
  { path: 'audit', title: '审计追踪', description: '审计日志与导出', keywords: 'audit log 审计 日志' },
  { path: 'settings', title: '系统设置', description: '平台配置与基础设置', keywords: 'setting 配置 设置' },
];

const store = createStore({
  token: localStorage.getItem('rv_token') || '',
  user: JSON.parse(localStorage.getItem('rv_user') || 'null'),
  permissions: new Set(JSON.parse(localStorage.getItem('rv_permissions') || '[]')),
  route: routes[0],
  sidebarCollapsed: localStorage.getItem('rv_sidebar_collapsed') === '1',
  commandPaletteOpen: false,
  commandPaletteQuery: '',
  commandPaletteSelectedIndex: 0,
});

function saveSession(state) {
  localStorage.setItem('rv_token', state.token || '');
  localStorage.setItem('rv_user', JSON.stringify(state.user || null));
  localStorage.setItem('rv_permissions', JSON.stringify([...(state.permissions || new Set())]));
}

function clearSession() {
  localStorage.removeItem('rv_token');
  localStorage.removeItem('rv_user');
  localStorage.removeItem('rv_permissions');
  localStorage.removeItem('rv_last_route');
}

async function hydrateSession() {
  const token = String(store.getState().token || '');
  if (!token) {
    clearSession();
    store.setState({ token: '', user: null, permissions: new Set() });
    return;
  }

  if (token.startsWith('demo_')) {
    clearSession();
    store.setState({ token: '', user: null, permissions: new Set() });
    return;
  }

  try {
    const me = await api('/users/me', {}, token);
    const permissions = new Set(me.permissions || []);
    store.setState({ token, user: me, permissions });
    saveSession(store.getState());
  } catch {
    clearSession();
    store.setState({ token: '', user: null, permissions: new Set() });
  }
}

function toast(message, type = 'info') {
  const toastEl = root.querySelector('#toast');
  if (!toastEl) return;
  toastEl.className = `toast ${type} show`;
  toastEl.textContent = message;
  window.setTimeout(() => {
    toastEl.className = 'toast';
    toastEl.textContent = '';
  }, 2600);
}

function routePathValue(route) {
  return route.currentPath || route.pattern || route.name || 'dashboard';
}

function buildRouteView(route) {
  if (route.name === 'taskDetail') {
    return {
      label: '任务详情',
      navPage: 'tasks',
      showBack: true,
      backPath: 'tasks',
      breadcrumb: [{ label: '任务', path: 'tasks' }, { label: route.params?.task_id || '详情' }],
    };
  }
  if (route.name === 'resultTask') {
    return {
      label: '结果详情',
      navPage: 'results',
      showBack: true,
      backPath: 'results',
      breadcrumb: [{ label: '结果', path: 'results' }, { label: route.params?.task_id || '详情' }],
    };
  }
  if (route.name === '403') {
    return {
      label: '无权限',
      navPage: 'dashboard',
      showBack: true,
      backPath: 'dashboard',
      breadcrumb: [{ label: '工作台', path: 'dashboard' }, { label: '403' }],
    };
  }
  if (route.name === '404') {
    return {
      label: '页面不存在',
      navPage: 'dashboard',
      showBack: true,
      backPath: 'dashboard',
      breadcrumb: [{ label: '工作台', path: 'dashboard' }, { label: '404' }],
    };
  }
  return {
    label: route.label || route.name,
    navPage: route.navPage || route.name,
    showBack: false,
    backPath: route.parentPath || 'dashboard',
    breadcrumb: [{ label: route.label || route.name }],
  };
}

function routeConfigByPath(path) {
  return routes.find((route) => route.pattern === path);
}

function canAccessPath(path, permissions) {
  const route = routeConfigByPath(path);
  if (!route?.permission) return true;
  return permissions.has(route.permission);
}

function isTypingTarget(target) {
  const el = target;
  if (!el || typeof el !== 'object') return false;
  const tagName = String(el.tagName || '').toLowerCase();
  return tagName === 'input' || tagName === 'textarea' || tagName === 'select' || Boolean(el.isContentEditable);
}

function buildCommandItems(state, routeView) {
  const permissions = state.permissions || new Set();
  const baseItems = NAV_COMMANDS
    .filter((item) => canAccessPath(item.path, permissions))
    .map((item) => ({
      type: 'navigate',
      value: item.path,
      title: item.title,
      description: item.description,
      shortcut: '',
      keywords: item.keywords || '',
    }));

  if (routeView?.showBack) {
    baseItems.unshift({
      type: 'action',
      value: 'back',
      title: '返回上一层',
      description: '回到上级页面',
      shortcut: 'Backspace',
      keywords: 'back 返回 上一层',
    });
  }

  baseItems.push(
    {
      type: 'action',
      value: 'toggle_sidebar',
      title: state.sidebarCollapsed ? '展开侧栏' : '收起侧栏',
      description: '切换左侧导航栏',
      shortcut: 'Ctrl/⌘ + B',
      keywords: 'sidebar nav 侧栏 导航',
    },
    {
      type: 'action',
      value: 'new_task',
      title: '快速创建任务',
      description: '进入任务页并新建推理任务',
      shortcut: '',
      keywords: 'task create 任务 创建',
    },
    {
      type: 'action',
      value: 'new_asset',
      title: '快速上传资产',
      description: '进入资产页上传文件',
      shortcut: '',
      keywords: 'asset upload 资产 上传',
    },
    {
      type: 'action',
      value: 'logout',
      title: '退出登录',
      description: '安全退出当前账号',
      shortcut: '',
      keywords: 'logout signout 退出 登出',
    },
  );

  const query = String(state.commandPaletteQuery || '').trim().toLowerCase();
  if (!query) return baseItems.slice(0, 12);
  const tokens = query.split(/\s+/).filter(Boolean);
  return baseItems
    .filter((item) => {
      const searchable = `${item.title} ${item.description} ${item.keywords}`.toLowerCase();
      return tokens.every((token) => searchable.includes(token));
    })
    .slice(0, 12);
}

function animateViewEntry() {
  const page = root.querySelector('.page');
  if (!page) return;
  page.classList.remove('page-enter', 'page-enter-active');
  void page.offsetWidth;
  page.classList.add('page-enter');
  requestAnimationFrame(() => {
    page.classList.add('page-enter-active');
  });
  window.setTimeout(() => {
    page.classList.remove('page-enter', 'page-enter-active');
  }, 240);
}

async function login(username, password) {
  const resp = await apiPost('/auth/login', { username, password });
  const me = await api('/users/me', {}, resp.access_token);
  const permissions = new Set(me.permissions || resp.permissions || []);
  store.setState({ token: resp.access_token, user: me, permissions });
  saveSession(store.getState());
  router.navigate(localStorage.getItem('rv_last_route') || 'dashboard');
  return { ok: true };
}

function logout() {
  clearSession();
  store.setState({
    token: '',
    user: null,
    permissions: new Set(),
    commandPaletteOpen: false,
    commandPaletteQuery: '',
    commandPaletteSelectedIndex: 0,
  });
  router.navigate('login');
}

function toggleSidebar() {
  const next = !store.getState().sidebarCollapsed;
  store.setState({ sidebarCollapsed: next });
  localStorage.setItem('rv_sidebar_collapsed', next ? '1' : '0');
  render();
}

function openCommandPalette(seedQuery = '') {
  const state = store.getState();
  if (!state.user) return;
  store.setState({
    commandPaletteOpen: true,
    commandPaletteQuery: seedQuery,
    commandPaletteSelectedIndex: 0,
  });
  render();
}

function closeCommandPalette({ rerender = true } = {}) {
  if (!store.getState().commandPaletteOpen) return;
  store.setState({
    commandPaletteOpen: false,
    commandPaletteQuery: '',
    commandPaletteSelectedIndex: 0,
  });
  if (rerender) render();
}

function setCommandPaletteQuery(query) {
  store.setState({
    commandPaletteQuery: query,
    commandPaletteSelectedIndex: 0,
  });
  render();
}

function moveCommandSelection(step, itemsLength) {
  if (!itemsLength) return;
  const current = store.getState().commandPaletteSelectedIndex || 0;
  const next = (current + step + itemsLength) % itemsLength;
  store.setState({ commandPaletteSelectedIndex: next });
  render();
}

function executeCommandItem(item, routeView) {
  if (!item) return;
  closeCommandPalette({ rerender: false });
  if (item.type === 'navigate') {
    router.navigate(item.value);
    return;
  }

  if (item.value === 'back') {
    router.back(routeView.backPath || 'dashboard');
    return;
  }
  if (item.value === 'toggle_sidebar') {
    toggleSidebar();
    return;
  }
  if (item.value === 'new_task') {
    router.navigate('tasks');
    window.setTimeout(() => toast('已打开任务页，可直接创建任务'), 50);
    return;
  }
  if (item.value === 'new_asset') {
    router.navigate('assets');
    window.setTimeout(() => toast('已打开资产页，可直接上传文件'), 50);
    return;
  }
  if (item.value === 'logout') {
    logout();
    return;
  }
  render();
}

let hotkeyBound = false;

function bindGlobalHotkeys() {
  if (hotkeyBound) return;
  hotkeyBound = true;
  window.addEventListener('keydown', (event) => {
    const state = store.getState();
    const isMeta = event.metaKey || event.ctrlKey;
    const key = String(event.key || '');
    const lower = key.toLowerCase();
    const typing = isTypingTarget(event.target);

    if (isMeta && lower === 'k') {
      if (!state.user) return;
      event.preventDefault();
      if (state.commandPaletteOpen) {
        closeCommandPalette();
      } else {
        openCommandPalette();
      }
      return;
    }

    if (!state.user) return;

    if (!state.commandPaletteOpen && !typing && key === '/') {
      event.preventDefault();
      openCommandPalette();
      return;
    }

    if (isMeta && lower === 'b') {
      event.preventDefault();
      toggleSidebar();
      return;
    }

    if (!state.commandPaletteOpen) return;
    const routeView = buildRouteView(state.route);
    const items = buildCommandItems(state, routeView);

    if (key === 'Escape') {
      event.preventDefault();
      closeCommandPalette();
      return;
    }

    if (key === 'ArrowDown' || key === 'Tab') {
      event.preventDefault();
      moveCommandSelection(event.shiftKey ? -1 : 1, items.length);
      return;
    }

    if (key === 'ArrowUp') {
      event.preventDefault();
      moveCommandSelection(-1, items.length);
      return;
    }

    if (key === 'Enter' && !event.shiftKey) {
      if (typing) event.preventDefault();
      const idx = Math.min(
        store.getState().commandPaletteSelectedIndex || 0,
        Math.max(0, items.length - 1),
      );
      executeCommandItem(items[idx], routeView);
    }
  });
}

function pageCtxFor(route) {
  return {
    state: store.getState(),
    navigate: (path) => router.navigate(path),
    back: () => router.back(buildRouteView(route).backPath || 'dashboard'),
    login,
    logout,
    toast,
  };
}

function render() {
  const state = store.getState();
  const route = state.route;
  const hasUser = Boolean(state.user);
  const permissions = state.permissions || new Set();

  if (!hasUser && route.name !== 'login') {
    router.navigate('login');
    return;
  }

  if (hasUser && route.name === 'login') {
    router.navigate(localStorage.getItem('rv_last_route') || 'dashboard');
    return;
  }

  if (route.requiresAuth && route.permission && !permissions.has(route.permission)) {
    if (route.name !== '403') {
      router.navigate('403');
      return;
    }
  }

  if (route.requiresAuth && !['403', '404', 'login'].includes(route.name)) {
    localStorage.setItem('rv_last_route', routePathValue(route));
  }

  const page = getPage(route, pageCtxFor(route));

  if (route.name === 'login') {
    closeCommandPalette({ rerender: false });
    root.innerHTML = page.html;
    page.mount?.(root, pageCtxFor(route));
    return;
  }

  const routeView = buildRouteView(route);
  const commandItems = buildCommandItems(state, routeView);
  const selectedIndex = Math.min(
    state.commandPaletteSelectedIndex || 0,
    Math.max(0, commandItems.length - 1),
  );

  root.innerHTML = renderShell({
    state,
    routeView,
    contentHtml: page.html,
    commandPalette: {
      open: state.commandPaletteOpen,
      query: state.commandPaletteQuery || '',
      items: commandItems,
      selectedIndex,
    },
  });

  bindShellEvents(root, {
    onNavigate: (path) => router.navigate(path),
    onLogout: logout,
    onBack: () => router.back(routeView.backPath || 'dashboard'),
    onToggleSidebar: toggleSidebar,
    onOpenCommandPalette: () => openCommandPalette(state.commandPaletteQuery || ''),
    onCloseCommandPalette: () => closeCommandPalette(),
    onCommandQueryChange: (query) => setCommandPaletteQuery(query),
    onCommandExecute: (idx) => executeCommandItem(commandItems[idx], routeView),
  });
  page.mount?.(root.querySelector('.page') || root, pageCtxFor(route));
  animateViewEntry();

  if (state.commandPaletteOpen) {
    const commandInput = root.querySelector('#commandPaletteInput');
    if (commandInput) {
      commandInput.focus();
      const pos = commandInput.value.length;
      commandInput.setSelectionRange(pos, pos);
    }
  }
}

const router = createRouter({
  routes,
  onRoute(route) {
    store.setState({
      route,
      commandPaletteOpen: false,
      commandPaletteQuery: '',
      commandPaletteSelectedIndex: 0,
    });
    render();
  },
});

async function bootstrap() {
  await hydrateSession();
  if (store.getState().user) {
    const start = localStorage.getItem('rv_last_route') || 'dashboard';
    window.location.hash = `#/${start}`;
  } else {
    window.location.hash = '#/login';
  }
  bindGlobalHotkeys();
  router.start();
}

bootstrap();
