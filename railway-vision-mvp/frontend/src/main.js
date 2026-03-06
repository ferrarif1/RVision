import { createStore } from './core/store.js';
import { createRouter } from './core/router.js';
import { api, apiPost, DEMO_USERS, demoPermissions } from './core/api.js';
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

const store = createStore({
  token: localStorage.getItem('rv_token') || '',
  user: JSON.parse(localStorage.getItem('rv_user') || 'null'),
  permissions: new Set(JSON.parse(localStorage.getItem('rv_permissions') || '[]')),
  route: routes[0],
  sidebarCollapsed: localStorage.getItem('rv_sidebar_collapsed') === '1',
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

async function login(username, password) {
  try {
    const resp = await apiPost('/auth/login', { username, password });
    const me = await api('/users/me', {}, resp.access_token);
    const permissions = new Set(me.permissions || resp.permissions || []);
    store.setState({ token: resp.access_token, user: me, permissions });
    saveSession(store.getState());
    router.navigate(localStorage.getItem('rv_last_route') || 'dashboard');
    return { ok: true };
  } catch (error) {
    const demo = DEMO_USERS[username];
    if (!demo || demo.password !== password) throw error;
    const user = {
      username,
      roles: [demo.role],
      role: demo.role,
      tenant_code: demo.tenant_code,
      tenant_id: demo.tenant_code,
    };
    const permissions = demoPermissions(demo.role);
    store.setState({ token: `demo_${username}`, user, permissions });
    saveSession(store.getState());
    router.navigate('dashboard');
    return { ok: true };
  }
}

function logout() {
  clearSession();
  store.setState({ token: '', user: null, permissions: new Set() });
  router.navigate('login');
}

function toggleSidebar() {
  const next = !store.getState().sidebarCollapsed;
  store.setState({ sidebarCollapsed: next });
  localStorage.setItem('rv_sidebar_collapsed', next ? '1' : '0');
  render();
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
    root.innerHTML = page.html;
    page.mount?.(root, pageCtxFor(route));
    return;
  }

  const routeView = buildRouteView(route);
  root.innerHTML = renderShell({
    state,
    routeView,
    contentHtml: page.html,
  });

  bindShellEvents(root, {
    onNavigate: (path) => router.navigate(path),
    onLogout: logout,
    onBack: () => router.back(routeView.backPath || 'dashboard'),
    onToggleSidebar: toggleSidebar,
  });
  page.mount?.(root.querySelector('.page') || root, pageCtxFor(route));
}

const router = createRouter({
  routes,
  onRoute(route) {
    store.setState({ route });
    render();
  },
});

if (store.getState().user) {
  const start = localStorage.getItem('rv_last_route') || 'dashboard';
  window.location.hash = `#/${start}`;
} else {
  window.location.hash = '#/login';
}
router.start();
