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
  lastRoute: namespacedStorageKey('last_route'),
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
  lastTaskId: namespacedStorageKey('last_task_id'),
};

const LEGACY_STORAGE_KEYS = {
  token: 'rv_token',
  user: 'rv_user',
  permissions: 'rv_permissions',
  lastRoute: 'rv_last_route',
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
  lastTaskId: 'rv_last_task_id',
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
