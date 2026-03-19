export const BRAND_NAME = 'Vistral';
export const BRAND_SHORT_NAME = 'Vistral';
export const BRAND_FULL_NAME = 'Vistral 小模型管理与交付平台';
export const BRAND_MODEL_HUB_NAME = 'Vistral Model Hub';
export const BRAND_EDGE_PLATFORM_NAME = 'Vistral Edge AI Platform';
export const BRAND_TAGLINE = 'Vistral 是面向行业场景的小模型管理、审批发布与边缘交付平台。';
export const BRAND_CONTROL_CONSOLE_NAME = 'Vistral 控制台';

const STORAGE_PREFIX = 'vistral';

function namespacedStorageKey(key) {
  return `${STORAGE_PREFIX}_${key}`;
}

export const STORAGE_KEYS = {
  token: namespacedStorageKey('token'),
  user: namespacedStorageKey('user'),
  permissions: namespacedStorageKey('permissions'),
  visualTheme: namespacedStorageKey('visual_theme'),
  lastRoute: namespacedStorageKey('last_route'),
  lastExpertRoute: namespacedStorageKey('last_expert_route'),
  sidebarCollapsed: namespacedStorageKey('sidebar_collapsed'),
  prefillTrainingAssetIds: namespacedStorageKey('prefill_training_asset_ids'),
  prefillTrainingValidationAssetIds: namespacedStorageKey('prefill_training_validation_asset_ids'),
  prefillAssetId: namespacedStorageKey('prefill_asset_id'),
  quickDetectAssetId: namespacedStorageKey('quick_detect_asset_id'),
  focusModelId: namespacedStorageKey('focus_model_id'),
  focusModelTimeline: namespacedStorageKey('focus_model_timeline'),
  prefillTrainingDatasetLabel: namespacedStorageKey('prefill_training_dataset_label'),
  prefillTrainingDatasetVersionId: namespacedStorageKey('prefill_training_dataset_version_id'),
  prefillTrainingTargetModelCode: namespacedStorageKey('prefill_training_target_model_code'),
  focusTrainingJobId: namespacedStorageKey('focus_training_job_id'),
  prefillTaskModelId: namespacedStorageKey('prefill_task_model_id'),
  prefillTaskAssetId: namespacedStorageKey('prefill_task_asset_id'),
  prefillTaskType: namespacedStorageKey('prefill_task_type'),
  prefillTaskDeviceCode: namespacedStorageKey('prefill_task_device_code'),
  prefillTaskHint: namespacedStorageKey('prefill_task_hint'),
  lastTaskId: namespacedStorageKey('last_task_id'),
  inspectionOcrProxyOnly: namespacedStorageKey('inspection_ocr_proxy_only'),
  inspectionOcrReadinessBlockerOnly: namespacedStorageKey('inspection_ocr_readiness_blocker_only'),
  assistantLlmMode: namespacedStorageKey('assistant_llm_mode'),
  assistantExecutionMode: namespacedStorageKey('assistant_execution_mode'),
  assistantVisualTheme: namespacedStorageKey('assistant_visual_theme'),
  assistantLocalModelRepoId: namespacedStorageKey('assistant_local_model_repo_id'),
  assistantApiProvider: namespacedStorageKey('assistant_api_provider'),
  assistantApiBaseUrl: namespacedStorageKey('assistant_api_base_url'),
  assistantApiModelName: namespacedStorageKey('assistant_api_model_name'),
  assistantApiKey: namespacedStorageKey('assistant_api_key'),
  prefillTaskMeta: namespacedStorageKey('prefill_task_meta'),
  prefillTrainingMeta: namespacedStorageKey('prefill_training_meta'),
  focusModelMeta: namespacedStorageKey('focus_model_meta'),
  aiSessions: namespacedStorageKey('ai_sessions'),
  aiRecentActions: namespacedStorageKey('ai_recent_actions'),
  aiPendingConfirmations: namespacedStorageKey('ai_pending_confirmations'),
  aiLastPlan: namespacedStorageKey('ai_last_plan'),
  aiWorkflowDraft: namespacedStorageKey('ai_workflow_draft'),
};

const LEGACY_STORAGE_KEYS = {
  token: 'rv_token',
  user: 'rv_user',
  permissions: 'rv_permissions',
  visualTheme: 'rv_visual_theme',
  lastRoute: 'rv_last_route',
  lastExpertRoute: 'rv_last_expert_route',
  sidebarCollapsed: 'rv_sidebar_collapsed',
  prefillTrainingAssetIds: 'rv_prefill_training_asset_ids',
  prefillTrainingValidationAssetIds: 'rv_prefill_training_validation_asset_ids',
  prefillAssetId: 'rv_prefill_asset_id',
  quickDetectAssetId: 'rv_quick_detect_asset_id',
  focusModelId: 'rv_focus_model_id',
  focusModelTimeline: 'rv_focus_model_timeline',
  prefillTrainingDatasetLabel: 'rv_prefill_training_dataset_label',
  prefillTrainingDatasetVersionId: 'rv_prefill_training_dataset_version_id',
  prefillTrainingTargetModelCode: 'rv_prefill_training_target_model_code',
  focusTrainingJobId: 'rv_focus_training_job_id',
  prefillTaskModelId: 'rv_prefill_task_model_id',
  prefillTaskAssetId: 'rv_prefill_task_asset_id',
  prefillTaskType: 'rv_prefill_task_type',
  prefillTaskDeviceCode: 'rv_prefill_task_device_code',
  prefillTaskHint: 'rv_prefill_task_hint',
  lastTaskId: 'rv_last_task_id',
  inspectionOcrProxyOnly: 'rv_inspection_ocr_proxy_only',
  inspectionOcrReadinessBlockerOnly: 'rv_inspection_ocr_readiness_blocker_only',
  assistantLlmMode: 'rv_assistant_llm_mode',
  assistantExecutionMode: 'rv_assistant_execution_mode',
  assistantVisualTheme: 'rv_assistant_visual_theme',
  assistantLocalModelRepoId: 'rv_assistant_local_model_repo_id',
  assistantApiProvider: 'rv_assistant_api_provider',
  assistantApiBaseUrl: 'rv_assistant_api_base_url',
  assistantApiModelName: 'rv_assistant_api_model_name',
  assistantApiKey: 'rv_assistant_api_key',
  prefillTaskMeta: 'rv_prefill_task_meta',
  prefillTrainingMeta: 'rv_prefill_training_meta',
  focusModelMeta: 'rv_focus_model_meta',
  aiSessions: 'rv_ai_sessions',
  aiRecentActions: 'rv_ai_recent_actions',
  aiPendingConfirmations: 'rv_ai_pending_confirmations',
  aiLastPlan: 'rv_ai_last_plan',
  aiWorkflowDraft: 'rv_ai_workflow_draft',
};

export function migrateLegacyStorageKeys(storage = window.localStorage) {
  Object.entries(LEGACY_STORAGE_KEYS).forEach(([logicalKey, legacyKey]) => {
    const nextKey = STORAGE_KEYS[logicalKey];
    if (!nextKey) return;
    const legacyValue = storage.getItem(legacyKey);
    if (legacyValue === null) return;
    if (storage.getItem(nextKey) === null) {
      storage.setItem(nextKey, legacyValue);
    }
    storage.removeItem(legacyKey);
  });
}

export function buildDocumentTitle(pageTitle = '') {
  const cleanPageTitle = String(pageTitle || '').trim();
  if (!cleanPageTitle) return BRAND_CONTROL_CONSOLE_NAME;
  if (cleanPageTitle === BRAND_NAME || cleanPageTitle === BRAND_CONTROL_CONSOLE_NAME) {
    return BRAND_CONTROL_CONSOLE_NAME;
  }
  return `${cleanPageTitle} | ${BRAND_NAME}`;
}
