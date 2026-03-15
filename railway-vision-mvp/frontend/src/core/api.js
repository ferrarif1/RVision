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
  { test: /^dataset_label is required/i, message: '请先填写数据集标签，再继续导出或创建数据集。' },
  { test: /^Invalid JSON metadata field/i, message: '填写的 JSON 元信息格式不正确。请检查括号、引号和逗号。' },
  { test: /^JSON metadata field must be an object/i, message: 'JSON 元信息需要是对象格式，例如 {\"key\":\"value\"}。' },
  { test: /^Invalid buyer_tenant_code/i, message: '买家租户编码无效。请重新选择可见买家。' },
  { test: /^Invalid sensitivity_level/i, message: '敏感等级填写无效。请重新选择平台支持的等级。' },
  { test: /^Invalid asset_purpose/i, message: '资源用途填写无效。请改选训练、验证、微调或推理。' },
  { test: /^Unsupported file type/i, message: '当前文件类型不支持。请上传图片、视频、ZIP 数据集或 ZIP 模型包。' },
  { test: /^Missing file name/i, message: '上传文件缺少文件名。请重新选择文件后再试。' },
  { test: /^Empty file is not allowed/i, message: '上传文件为空。请确认文件内容后重新上传。' },
  { test: /^Invalid ZIP archive/i, message: 'ZIP 文件无法解析。请确认压缩包完整且没有损坏。' },
  { test: /^ZIP archive is empty/i, message: 'ZIP 压缩包是空的。请放入图片、视频或数据集内容后再上传。' },
  { test: /^ZIP archive must contain at least one supported image or video file/i, message: 'ZIP 数据集里没有可识别的图片或视频。请检查压缩包内容。' },
  { test: /^ZIP dataset asset is only allowed for training, finetune or validation purpose/i, message: 'ZIP 数据集包只适合训练、微调或验证，不适合直接在线识别。' },
  { test: /^Pipeline references unknown models/i, message: '流水线引用了不存在或当前不可见的模型。请先确认路由模型和专家模型。' },
  { test: /^router_model_id must reference a router model/i, message: '路由模型编号必须指向一版路由模型，不能选专家模型。' },
  { test: /^Expert binding for .* must reference expert models/i, message: '专家模型分配里引用了错误类型的模型。请为每个任务绑定专家模型。' },
  { test: /^Pipeline must reference at least one model/i, message: '流水线至少要绑定一版模型后才能注册。' },
  { test: /^Invalid change_scope/i, message: '当前变更范围不支持。请重新选择可用范围。' },
  { test: /^Only archive dataset versions can be rolled back/i, message: '只有 ZIP 数据集版本支持回滚为新版本。' },
  { test: /^Dataset archive file missing/i, message: '数据集压缩包文件不存在。请重新导出或重新上传。' },
  { test: /^Dataset archive metadata is malformed/i, message: '数据集包里的元信息损坏。请重新生成这版数据集。' },
  { test: /^Dataset preview is only available for archive assets/i, message: '只有 ZIP 数据集包支持预览样本。' },
  { test: /^Dataset preview file is only available for archive assets/i, message: '只有 ZIP 数据集包支持查看预览文件。' },
  { test: /^Unsupported dataset preview member/i, message: '当前预览文件类型不支持直接查看。请改看其他样本。' },
  { test: /^Asset content preview is only available for image, video or screenshot assets/i, message: '当前资源类型不支持直接预览内容。' },
  { test: /^Pipeline not found/i, message: '流水线不存在或当前账号不可见。请回到流水线中心刷新。' },
  { test: /^Only FAILED or CANCELLED jobs can be retried/i, message: '只有失败或已取消的训练作业才能重试。' },
  { test: /^RUNNING job cannot be reassigned directly, cancel it first/i, message: '训练作业正在运行，不能直接改派。请先取消后再重新分配。' },
  { test: /^SUCCEEDED job cannot be reassigned/i, message: '训练作业已经成功完成，不能再改派。' },
  { test: /^Training job already terminal/i, message: '训练作业已经结束，不能继续执行这个操作。' },
  { test: /^Training job assigned to a different worker/i, message: '这条训练作业已经分配给其他训练机器。请刷新列表后再试。' },
  { test: /^Target worker not found/i, message: '目标训练机器不存在。请刷新训练中心后重新选择。' },
  { test: /^Target worker is not ACTIVE/i, message: '目标训练机器当前不在线。请改选在线训练机器。' },
  { test: /^worker_code does not match worker_host/i, message: '训练机器编号和机器地址不匹配。请重新选择同一台机器。' },
  { test: /^worker_code or worker_host is required/i, message: '请至少填写训练机器编号或机器地址。' },
  { test: /^Asset not part of training job/i, message: '当前资源不属于这条训练作业，不能直接下载或查看。' },
  { test: /^Training job has no base model/i, message: '这条训练作业没有绑定基础模型，暂时不能拉取基础模型文件。' },
  { test: /^Training job already has a candidate model/i, message: '这条训练作业已经产出过待验证模型，不能再次上传候选模型包。' },
  { test: /^Invalid model_source_type/i, message: '模型来源填写无效。请重新选择来源。' },
  { test: /^Invalid model_type/i, message: '模型类型填写无效。请重新选择专家模型或路由模型。' },
  { test: /^Forbidden$/i, message: '当前账号没有权限访问这项模型操作。' },
  { test: /^Invalid username or password/i, message: '用户名或密码不正确。请重新输入后再试。' },
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
  assistant: 'dashboard.view',
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
