import { STORAGE_KEYS } from '../config/brand.js';

export function safeStorageJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    return parsed ?? fallback;
  } catch {
    return fallback;
  }
}

export function writeStorageJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

export function readAssistantLocalSettings() {
  return {
    llmMode: localStorage.getItem(STORAGE_KEYS.assistantLlmMode) || 'disabled',
    executionMode: localStorage.getItem(STORAGE_KEYS.assistantExecutionMode) || 'guide_only',
    localRepoId: localStorage.getItem(STORAGE_KEYS.assistantLocalModelRepoId) || '',
    apiProvider: localStorage.getItem(STORAGE_KEYS.assistantApiProvider) || 'openai_compatible',
    apiBaseUrl: localStorage.getItem(STORAGE_KEYS.assistantApiBaseUrl) || '',
    apiModelName: localStorage.getItem(STORAGE_KEYS.assistantApiModelName) || '',
    apiKey: localStorage.getItem(STORAGE_KEYS.assistantApiKey) || '',
  };
}

export function persistAssistantLocalSettings(next) {
  localStorage.setItem(STORAGE_KEYS.assistantLlmMode, next.llmMode || 'disabled');
  localStorage.setItem(STORAGE_KEYS.assistantExecutionMode, next.executionMode || 'guide_only');
  localStorage.setItem(STORAGE_KEYS.assistantLocalModelRepoId, next.localRepoId || '');
  localStorage.setItem(STORAGE_KEYS.assistantApiProvider, next.apiProvider || 'openai_compatible');
  localStorage.setItem(STORAGE_KEYS.assistantApiBaseUrl, next.apiBaseUrl || '');
  localStorage.setItem(STORAGE_KEYS.assistantApiModelName, next.apiModelName || '');
  localStorage.setItem(STORAGE_KEYS.assistantApiKey, next.apiKey || '');
}

export function assistantModeLabel(mode) {
  if (mode === 'api') return 'API 模式';
  if (mode === 'local') return '本地模型模式';
  return '平台规则引擎';
}

const AI_TASK_LABELS = {
  car_number_ocr: '车号识别',
  inspection_mark_ocr: '定检标记识别',
  performance_mark_ocr: '性能标记识别',
  door_lock_state_detect: '门锁状态检测',
  connector_defect_detect: '连接件缺陷检测',
  bolt_missing_detect: '螺栓缺失检测',
  object_detect: '通用目标检测',
};

export function aiTaskLabel(taskType) {
  return AI_TASK_LABELS[String(taskType || '').trim()] || '通用任务';
}

export function buildTrainingExpertPath(taskType = '') {
  const clean = String(taskType || '').trim();
  if (!clean) return 'training';
  if (clean === 'car_number_ocr') return 'training/car-number-labeling';
  if (['inspection_mark_ocr', 'performance_mark_ocr'].includes(clean)) return `training/inspection-ocr/${encodeURIComponent(clean)}`;
  if (['door_lock_state_detect', 'connector_defect_detect', 'bolt_missing_detect'].includes(clean)) return `training/inspection-state/${encodeURIComponent(clean)}`;
  return 'training';
}

export function workflowRouteForAction(action = {}) {
  const explicitWorkflowPath = String(action.workflow_path || '').trim();
  if (explicitWorkflowPath) return explicitWorkflowPath;
  const actionId = String(action.action_id || '').trim();
  const rawPath = String(action.path || '').trim();
  if (actionId === 'upload_or_select_assets' || rawPath === 'assets') return 'ai/workflow/upload';
  if (actionId === 'prepare_training_data' || rawPath.startsWith('training')) return 'ai/workflow/train';
  if (actionId === 'open_approval_workbench' || actionId === 'open_release_workbench' || rawPath === 'models' || rawPath === 'pipelines') return 'ai/workflow/deploy';
  if (actionId === 'validate_existing_model' || rawPath === 'tasks' || rawPath === 'results') return 'ai/workflow/results';
  if (rawPath === 'audit' || rawPath === 'devices') return 'ai/workflow/troubleshoot';
  return 'ai';
}

export function readAiSessions() {
  const value = safeStorageJson(STORAGE_KEYS.aiSessions, []);
  return Array.isArray(value) ? value : [];
}

export function persistAiSessions(rows) {
  writeStorageJson(STORAGE_KEYS.aiSessions, rows.slice(0, 16));
}

export function readAiRecentActions() {
  const value = safeStorageJson(STORAGE_KEYS.aiRecentActions, []);
  return Array.isArray(value) ? value : [];
}

export function persistAiRecentActions(rows) {
  writeStorageJson(STORAGE_KEYS.aiRecentActions, rows.slice(0, 12));
}

export function readAiPendingConfirmations() {
  const value = safeStorageJson(STORAGE_KEYS.aiPendingConfirmations, []);
  return Array.isArray(value) ? value : [];
}

export function persistAiPendingConfirmations(rows) {
  writeStorageJson(STORAGE_KEYS.aiPendingConfirmations, rows.slice(0, 8));
}

export function readAiWorkflowDraft() {
  return safeStorageJson(STORAGE_KEYS.aiWorkflowDraft, {});
}

export function persistAiWorkflowDraft(value) {
  writeStorageJson(STORAGE_KEYS.aiWorkflowDraft, value || {});
}

export function readAiLastPlan() {
  return safeStorageJson(STORAGE_KEYS.aiLastPlan, null);
}

export function persistAiLastPlan(plan) {
  writeStorageJson(STORAGE_KEYS.aiLastPlan, plan || null);
}
