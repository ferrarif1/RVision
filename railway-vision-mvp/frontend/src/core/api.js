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
