import { assistantModeLabel, persistAssistantLocalSettings, readAssistantLocalSettings } from './runtime.js';

export async function loadAISettingsBundle(ctx) {
  const [providers, knowledge, behavior, providerModes, localModels, downloadJobs, localRuntime] = await Promise.all([
    ctx.get('/settings/ai/providers'),
    ctx.get('/settings/ai/knowledge'),
    ctx.get('/settings/ai/behavior'),
    ctx.get('/settings/llm/provider-modes'),
    ctx.get('/settings/llm/local-models'),
    ctx.get('/settings/llm/download-jobs'),
    ctx.get('/settings/llm/local-runtime'),
  ]);
  return { providers, knowledge, behavior, providerModes, localModels, downloadJobs, localRuntime };
}

function providerMatchesScope(provider, preferredScope = 'global') {
  const scope = String(preferredScope || 'global').trim() || 'global';
  const rows = Array.isArray(provider?.scope) ? provider.scope.map((item) => String(item || '').trim()).filter(Boolean) : [];
  if (!rows.length || rows.includes('global')) return true;
  return rows.includes(scope);
}

function providerHasExactScope(provider, preferredScope = 'global') {
  const scope = String(preferredScope || 'global').trim() || 'global';
  if (scope === 'global') return false;
  const rows = Array.isArray(provider?.scope) ? provider.scope.map((item) => String(item || '').trim()).filter(Boolean) : [];
  return rows.length > 0 && !rows.includes('global') && rows.includes(scope);
}

export function inferPlannerScopeHint({ goal = '', assetIds = [], currentModelId = '', taskType = '', sourcePath = '' } = {}) {
  const path = String(sourcePath || '').trim();
  if (path.includes('training')) return 'train';
  if (path.includes('results') || path.includes('tasks')) return 'results';
  if (path.includes('models') || path.includes('pipelines')) return 'deploy';
  if (path.includes('assets')) return 'upload';
  if (path.includes('devices') || path.includes('audit')) return 'troubleshoot';
  const text = `${goal} ${taskType}`.toLowerCase();
  if (/\b(upload|asset|dataset|样例|上传|资产|数据集)\b/.test(text)) return 'upload';
  if (/\b(train|training|fine[- ]?tune|微调|训练)\b/.test(text)) return 'train';
  if (/\b(deploy|release|approve|publish|发布|审批)\b/.test(text)) return 'deploy';
  if (/\b(troubleshoot|device|audit|error|failed|排障|设备|审计|失败)\b/.test(text)) return 'troubleshoot';
  if (currentModelId || (Array.isArray(assetIds) && assetIds.length) || /\b(validate|result|infer|verify|识别|验证|推理|结果)\b/.test(text)) return 'results';
  return 'global';
}

export function resolveEffectiveProvider(aiSettingsBundle, preferredScope = 'global') {
  const providerRows = (aiSettingsBundle?.providers?.providers || []).filter(Boolean);
  const enabledRows = providerRows.filter((item) => item.enabled);
  const exactScopedEnabled = enabledRows.filter((item) => providerHasExactScope(item, preferredScope));
  const scopedEnabled = enabledRows.filter((item) => providerMatchesScope(item, preferredScope));
  return exactScopedEnabled.find((item) => item.is_default)
    || exactScopedEnabled[0]
    || scopedEnabled.find((item) => item.is_default)
    || scopedEnabled[0]
    || enabledRows.find((item) => item.is_default)
    || enabledRows[0]
    || providerRows.find((item) => item.is_default)
    || providerRows[0]
    || null;
}

export function buildPlannerRuntime(aiSettingsBundle, preferredScope = 'global') {
  const provider = resolveEffectiveProvider(aiSettingsBundle, preferredScope);
  if (!provider || !provider.enabled) {
    persistAssistantLocalSettings({ ...readAssistantLocalSettings(), llmMode: 'disabled' });
    return { llmMode: 'disabled', modeLabel: assistantModeLabel('disabled'), llmSelection: {}, apiConfig: {}, preferredScope };
  }
  const llmMode = provider.mode === 'local' ? 'local' : 'api';
  persistAssistantLocalSettings({
    ...readAssistantLocalSettings(),
    llmMode,
    apiProvider: provider.id || '',
    apiBaseUrl: provider.base_url || '',
    apiModelName: provider.model_name || '',
  });
  return {
    llmMode,
    modeLabel: provider.name || assistantModeLabel(llmMode),
    llmSelection: {
      provider_id: provider.id,
      provider_label: provider.name,
      model_name: provider.model_name,
    },
    apiConfig: {
      provider_id: provider.id,
    },
    preferredScope,
  };
}
