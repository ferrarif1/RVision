const API_BASE = '/api';

export async function api(path, options = {}, token = '') {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!resp.ok) {
    let message = `HTTP ${resp.status}`;
    try {
      const data = await resp.json();
      message = data?.detail || data?.message || message;
    } catch {}
    throw new Error(message);
  }
  return resp.json();
}

export const DEMO_USERS = {
  platform_admin: { password: 'platform123', role: 'platform_admin', tenant_id: 'tenant_demo' },
  supplier_demo: { password: 'supplier123', role: 'supplier_engineer', tenant_id: 'tenant_demo' },
  buyer_operator: { password: 'buyer123', role: 'buyer_operator', tenant_id: 'tenant_demo' },
};

export const PERMISSIONS = {
  dashboard: null,
  assets: 'asset.upload',
  models: 'model.view',
  pipelines: 'model.view',
  tasks: 'task.create',
  results: 'result.read',
  audit: 'audit.read',
  devices: 'device.read',
  settings: 'settings.view',
};

export function demoPermissions(role) {
  if (role === 'platform_admin') return new Set(['asset.upload', 'model.view', 'model.submit', 'model.approve', 'model.release', 'task.create', 'result.read', 'audit.read', 'device.read', 'settings.view']);
  if (role === 'supplier_engineer') return new Set(['model.view', 'model.submit', 'task.create', 'result.read']);
  return new Set(['asset.upload', 'task.create', 'result.read']);
}
