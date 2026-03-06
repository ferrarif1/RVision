const API_BASE = '/api';

function isFormData(body) {
  return typeof FormData !== 'undefined' && body instanceof FormData;
}

export async function api(path, options = {}, token = '') {
  const body = options.body;
  const headers = { ...(options.headers || {}) };
  if (!isFormData(body) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  if (token) headers.Authorization = `Bearer ${token}`;

  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!resp.ok) {
    let message = `HTTP ${resp.status}`;
    try {
      const data = await resp.json();
      message = data?.detail || data?.message || message;
    } catch {
      const text = await resp.text();
      if (text) message = text;
    }
    throw new Error(message);
  }

  if (resp.status === 204) return null;
  const contentType = resp.headers.get('content-type') || '';
  if (contentType.includes('application/json')) return resp.json();
  return resp.text();
}

export function apiPost(path, payload, token = '') {
  return api(path, { method: 'POST', body: JSON.stringify(payload) }, token);
}

export function apiDelete(path, token = '') {
  return api(path, { method: 'DELETE' }, token);
}

export function apiForm(path, formData, token = '') {
  return api(path, { method: 'POST', body: formData }, token);
}

export function toQuery(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    query.set(key, String(value));
  });
  const rendered = query.toString();
  return rendered ? `?${rendered}` : '';
}

export function formatDateTime(value) {
  if (!value) return '-';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString();
}

export const DEMO_USERS = {
  platform_admin: { password: 'platform123', role: 'platform_admin', tenant_code: 'platform-001' },
  supplier_demo: { password: 'supplier123', role: 'supplier_engineer', tenant_code: 'supplier-demo-001' },
  buyer_operator: { password: 'buyer123', role: 'buyer_operator', tenant_code: 'buyer-demo-001' },
};

export const PERMISSIONS = {
  dashboard: 'dashboard.view',
  assets: 'asset.upload',
  models: 'model.view',
  training: 'training.job.view',
  pipelines: 'model.view',
  tasks: 'task.create',
  results: 'result.read',
  audit: 'audit.read',
  devices: 'device.read',
  settings: 'settings.view',
};

export function demoPermissions(role) {
  if (role === 'platform_admin') {
    return new Set([
      'dashboard.view',
      'asset.upload',
      'model.view',
      'model.submit',
      'model.approve',
      'model.release',
      'task.create',
      'result.read',
      'audit.read',
      'device.read',
      'settings.view',
      'training.job.view',
      'training.job.create',
      'training.worker.manage',
    ]);
  }
  if (role === 'supplier_engineer') {
    return new Set([
      'dashboard.view',
      'model.view',
      'model.submit',
      'settings.view',
      'training.job.view',
    ]);
  }
  return new Set([
    'dashboard.view',
    'asset.upload',
    'task.create',
    'result.read',
    'device.read',
    'settings.view',
  ]);
}
