import { createStore } from './core/store.js';
import { createRouter } from './core/router.js';
import { api, DEMO_USERS, demoPermissions, PERMISSIONS } from './core/api.js';
import { renderShell, bindShellEvents } from './layout/AppShell.js';
import { pages } from './pages/index.js';

const root = document.getElementById('app');

const store = createStore({
  token: localStorage.getItem('rv_token') || '',
  user: JSON.parse(localStorage.getItem('rv_user') || 'null'),
  permissions: new Set(JSON.parse(localStorage.getItem('rv_permissions') || '[]')),
  route: 'login',
});

const routes = [
  { path: 'login', requiresAuth: false },
  { path: 'dashboard', requiresAuth: true },
  { path: 'assets', requiresAuth: true },
  { path: 'models', requiresAuth: true },
  { path: 'pipelines', requiresAuth: true },
  { path: 'tasks', requiresAuth: true },
  { path: 'results', requiresAuth: true },
  { path: 'audit', requiresAuth: true },
  { path: 'devices', requiresAuth: true },
  { path: 'settings', requiresAuth: true },
  { path: '403', requiresAuth: true },
  { path: '404', requiresAuth: false },
];

function hasPagePermission(path, permissions) {
  const need = PERMISSIONS[path];
  return !need || permissions.has(need);
}

function saveSession(state) {
  localStorage.setItem('rv_token', state.token || '');
  localStorage.setItem('rv_user', JSON.stringify(state.user || null));
  localStorage.setItem('rv_permissions', JSON.stringify([...state.permissions]));
}

async function login(username, password) {
  try {
    const resp = await api('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
    const me = await api('/users/me', {}, resp.access_token);
    const permissions = new Set(me.permissions || resp.permissions || []);
    store.setState({ token: resp.access_token, user: me, permissions });
    saveSession(store.getState());
    router.navigate(localStorage.getItem('rv_last_route') || 'dashboard');
    return { ok: true };
  } catch {
    const demo = DEMO_USERS[username];
    if (!demo || demo.password !== password) return { ok: false, message: '账号或密码错误' };
    const user = { username, role: demo.role, tenant_id: demo.tenant_id };
    const permissions = demoPermissions(demo.role);
    store.setState({ token: `demo_${username}`, user, permissions });
    saveSession(store.getState());
    router.navigate('dashboard');
    return { ok: true };
  }
}

function logout() {
  localStorage.removeItem('rv_token');
  localStorage.removeItem('rv_user');
  localStorage.removeItem('rv_permissions');
  localStorage.removeItem('rv_last_route');
  store.setState({ token: '', user: null, permissions: new Set() });
  router.navigate('login');
}

function render() {
  const state = store.getState();
  const route = state.route;
  if (route === 'login') {
    root.innerHTML = pages.login();
    const btn = document.getElementById('loginBtn');
    btn?.addEventListener('click', async () => {
      const username = document.getElementById('username').value.trim();
      const password = document.getElementById('password').value;
      const out = await login(username, password);
      if (!out.ok) document.getElementById('loginMsg').textContent = out.message;
    });
    return;
  }

  const contentHtml = (pages[route] || pages['404'])();
  root.innerHTML = renderShell({
    state,
    route: { path: route },
    contentHtml,
    onNavigate: (path) => router.navigate(path),
    onLogout: logout,
  });
  bindShellEvents(root, (path) => router.navigate(path), logout);
}

const router = createRouter({
  routes,
  onRoute(route) {
    const { user, permissions } = store.getState();
    if (route.requiresAuth && !user) {
      store.setState({ route: 'login' });
      render();
      return;
    }
    if (route.requiresAuth && !hasPagePermission(route.path, permissions)) {
      store.setState({ route: '403' });
      render();
      return;
    }
    const next = route.path;
    store.setState({ route: next });
    if (next !== 'login') localStorage.setItem('rv_last_route', next);
    render();
  },
});

store.subscribe(() => {});

if (store.getState().user) {
  const start = localStorage.getItem('rv_last_route') || 'dashboard';
  window.location.hash = `#/${start}`;
} else {
  window.location.hash = '#/login';
}
router.start();
