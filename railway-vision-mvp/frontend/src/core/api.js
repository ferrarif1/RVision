const API_BASE = '/api';

const ERROR_RULES = [
  { test: /^Asset not found/i, message: '资源不存在、已被清理，或当前账号无权访问。请刷新列表或重新上传。' },
  { test: /^Model not found/i, message: '模型不存在或当前账号不可见。请重新选择模型。' },
  { test: /^Task not found/i, message: '任务不存在或已超出当前账号可见范围。请回到任务中心刷新。' },
  { test: /^Result not found/i, message: '结果不存在或当前账号不可见。请刷新结果页后重试。' },
  { test: /^Training job not found/i, message: '训练作业不存在或当前账号不可见。请回到训练中心刷新。' },
  { test: /^Training worker not found/i, message: '训练机不存在。请刷新训练页并重新选择可用 worker。' },
  { test: /^Base model not found/i, message: '基础模型不存在。请重新选择一个可用基线模型。' },
  { test: /^Base model is not released to current buyer tenant/i, message: '当前基础模型还没有授权给当前买方租户，不能直接用于训练。' },
  { test: /^Model not released to your tenant or device/i, message: '当前模型还没有授权到你的租户或设备，请先走发布或换一版可用模型。' },
  { test: /^Model artifacts missing/i, message: '模型文件不完整，暂时无法执行。请重新发布或重新拉取模型。' },
  { test: /^model decrypt failed/i, message: '模型包解密失败。请确认设备密钥可用，并重新拉取这版模型后再试。' },
  { test: /^Task type does not match model capability/i, message: '所选模型能力与当前任务类型不匹配。请改选同任务类型的模型。' },
  { test: /^No schedulable model found/i, message: '当前没有可调度的模型。请先发布一版可用模型，或显式选择具体模型。' },
  { test: /^No schedulable models available for preflight inspection/i, message: '当前没有可用于预检的模型。请先发布至少一版可用模型。' },
  { test: /^Model or pipeline resolution failed/i, message: '任务没有解析到可执行模型或流水线。请检查模型选择、任务类型和发布状态。' },
  { test: /^Task type cannot be resolved/i, message: '系统没能判断当前要执行哪类任务。请明确填写识别目标，或直接选择具体模型。' },
  { test: /^Archive dataset assets cannot be used for inference tasks/i, message: 'ZIP 数据集包不能直接做在线识别，请改选单图、视频或已有推理资产。' },
  { test: /^Only \.zip model package is allowed/i, message: '这里只接受 ZIP 模型包，请重新打包后上传。' },
  { test: /^Candidate package model_id does not match training job target_model_code/i, message: '候选模型包里的模型编码和训练作业目标不一致，请确认导出来源。' },
  { test: /^Candidate package version does not match training job target_version/i, message: '候选模型包版本和训练作业目标版本不一致，请确认当前上传的是正确产物。' },
  { test: /^Model code\+version already exists/i, message: '同编码同版本的模型已存在。请换一个新版本号后再提交。' },
  { test: /^Pipeline code\+version already exists/i, message: '同编码同版本的流水线已存在。请换一个新版本号后再提交。' },
  { test: /^Asset file missing/i, message: '资源记录还在，但源文件已丢失。请重新上传该资源。' },
  { test: /^Crop file not found/i, message: '标注裁剪图不存在。请重新生成 OCR 标注清单。' },
  { test: /^Labeling manifest is empty/i, message: '当前 OCR 标注清单为空，暂时不能继续导出训练集。' },
  { test: /^Not enough labeled rows to export OCR text dataset/i, message: '已确认的 OCR 文本样本还不够，暂时不能导出训练集。' },
  { test: /^Need both train and validation rows to export OCR text dataset/i, message: '导出训练集时需要同时具备训练样本和验证样本，请先补足复核。' },
  { test: /^Generated OCR dataset bundle is invalid/i, message: '系统生成的 OCR 数据包不完整，请重新导出；若持续失败，检查标注清单。' },
  { test: /^ocr_unavailable$/i, message: '当前图片里的车号文本没有稳定识别出来，请更换更清晰样本或人工复核。' },
];

function isFormData(body) {
  return typeof FormData !== 'undefined' && body instanceof FormData;
}

function composeStructuredUiError(detail, status = 0) {
  const message = String(detail?.message || '').trim();
  const nextStep = String(detail?.next_step || '').trim();
  const hint = String(detail?.hint || '').trim();
  const segments = [message || (status ? `请求失败（HTTP ${status}）` : '请求失败，请稍后重试')];
  if (nextStep) segments.push(`下一步：${nextStep}`);
  if (hint) segments.push(`提示：${hint}`);
  return segments.join(' ');
}

export function normalizeUiErrorMessage(rawMessage, status = 0) {
  if (rawMessage && typeof rawMessage === 'object') {
    return composeStructuredUiError(rawMessage, status);
  }
  const fallback = status ? `请求失败（HTTP ${status}）` : '请求失败，请稍后重试';
  const message = String(rawMessage || '').trim() || fallback;

  for (const rule of ERROR_RULES) {
    if (rule.test.test(message)) return rule.message;
  }

  if (/^HTTP 401$/i.test(message) || status === 401) return '登录状态已失效，请重新登录。';
  if (/^HTTP 403$/i.test(message) || status === 403) return '当前账号没有权限执行这个操作。';
  if (/^HTTP 404$/i.test(message) || status === 404) return '请求的对象不存在，或当前账号不可见。请刷新页面后重试。';
  if (/^HTTP 409$/i.test(message) || status === 409) return '当前对象状态已变化，不能继续这个操作。请先刷新页面。';
  if (/^HTTP 5\d\d$/i.test(message) || status >= 500) return '服务端执行失败，请稍后重试；如果持续失败，再看详细日志。';

  return message;
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
    let detailPayload = null;
    const rawText = await resp.text();
    if (rawText) {
      try {
        const data = JSON.parse(rawText);
        detailPayload = data?.detail && typeof data.detail === 'object' ? data.detail : null;
        message = detailPayload || data?.detail || data?.message || rawText || message;
      } catch {
        message = rawText;
      }
    }
    const error = new Error(normalizeUiErrorMessage(message, resp.status));
    error.status = resp.status;
    error.rawMessage = detailPayload?.raw_detail || message;
    error.uiDetail = detailPayload;
    throw error;
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
