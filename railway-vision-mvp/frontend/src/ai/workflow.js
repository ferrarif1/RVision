import { STORAGE_KEYS } from '../config/brand.js';
import {
  aiTaskLabel,
  readAiPendingConfirmations,
  readAiRecentActions,
  readAiWorkflowDraft,
  safeStorageJson,
  workflowRouteForAction,
  writeStorageJson,
} from './runtime.js';

const ROUTE_KIND_BY_NAME = {
  aiWorkflowUpload: 'upload',
  aiWorkflowTrain: 'train',
  aiWorkflowDeploy: 'deploy',
  aiWorkflowResults: 'results',
  aiWorkflowTroubleshoot: 'troubleshoot',
};

const STEP_DEFINITIONS = {
  upload: {
    key: 'upload',
    routeName: 'aiWorkflowUpload',
    routePath: 'ai/workflow/upload',
    title: '上传样例',
    shortTitle: '上传',
    description: '补齐图片、视频或 ZIP 数据集，建立当前任务的输入上下文。',
    completionHint: '至少带入一份可用样例后，才能继续后续流程。',
  },
  train: {
    key: 'train',
    routeName: 'aiWorkflowTrain',
    routePath: 'ai/workflow/train',
    title: '数据确认与训练',
    shortTitle: '训练',
    description: '确认任务类型、数据用途和训练入口，必要时回到训练工作区补样本。',
    completionHint: '当前数据集、训练参数或训练作业准备就绪后，才能继续。',
  },
  deploy: {
    key: 'deploy',
    routeName: 'aiWorkflowDeploy',
    routePath: 'ai/workflow/deploy',
    title: '审批与发布',
    shortTitle: '发布',
    description: '确认候选模型、审批状态与交付范围，再进入发布控制面继续。',
    completionHint: '至少要有可发布模型或明确的候选版本。',
  },
  results: {
    key: 'results',
    routeName: 'aiWorkflowResults',
    routePath: 'ai/workflow/results',
    title: '结果验收',
    shortTitle: '结果',
    description: '执行验证任务并核对输出，判断是否可闭环、回训或继续排障。',
    completionHint: '至少需要任务编号、验证结果或当前验证上下文。',
  },
  troubleshoot: {
    key: 'troubleshoot',
    routeName: 'aiWorkflowTroubleshoot',
    routePath: 'ai/workflow/troubleshoot',
    title: '异常排查',
    shortTitle: '排障',
    description: '定位失败任务、训练阻塞或设备异常，并确认修复后回到主流程。',
    completionHint: '只有存在阻塞信号或需要排查时才进入这里。',
  },
};

const FLOW_DEFINITIONS = {
  training: {
    id: 'training',
    title: '训练闭环',
    summary: '上传数据后进入训练准备，再完成审批发布与结果验收。',
    steps: ['upload', 'train', 'deploy', 'results'],
  },
  validation: {
    id: 'validation',
    title: '验证闭环',
    summary: '直接用现有模型验证样例，再根据结果决定是否排障。',
    steps: ['upload', 'results', 'troubleshoot'],
  },
  release: {
    id: 'release',
    title: '发布闭环',
    summary: '先完成候选模型审批发布，再回到结果页做验收。',
    steps: ['deploy', 'results', 'troubleshoot'],
  },
  troubleshoot: {
    id: 'troubleshoot',
    title: '排障闭环',
    summary: '先定位阻塞点，修复后再回到主流程继续执行。',
    steps: ['troubleshoot'],
  },
};

function normalizeIds(values) {
  return [...new Set((Array.isArray(values) ? values : [])
    .map((item) => String(item || '').trim())
    .filter(Boolean))];
}

function splitCsv(value) {
  return normalizeIds(String(value || '').split(/[,\n，]/));
}

function routeKindFromPath(path = '') {
  const clean = String(path || '').trim().replace(/^#\/?/, '').replace(/^\//, '');
  if (clean === 'ai/workflow/upload') return 'upload';
  if (clean === 'ai/workflow/train') return 'train';
  if (clean === 'ai/workflow/deploy') return 'deploy';
  if (clean === 'ai/workflow/results') return 'results';
  if (clean === 'ai/workflow/troubleshoot') return 'troubleshoot';
  return '';
}

function inferRouteKind(route) {
  if (!route) return '';
  return ROUTE_KIND_BY_NAME[route.name] || routeKindFromPath(route.currentPath || route.pattern || route.name);
}

function normalizeStore(store) {
  return {
    version: 1,
    flow_id: String(store?.flow_id || '').trim(),
    current_step: String(store?.current_step || '').trim(),
    completed: store?.completed && typeof store.completed === 'object' ? store.completed : {},
    errors: store?.errors && typeof store.errors === 'object' ? store.errors : {},
    updated_at: String(store?.updated_at || '').trim(),
  };
}

function buildWorkflowSignals(draft = {}, plan = null) {
  const goal = String(draft?.goal || plan?.goal || '').trim();
  const sourcePath = String(draft?.source_path || '').trim();
  const taskType = String(draft?.task_type || plan?.inferred_task_type || '').trim();
  const assetIds = normalizeIds(draft?.asset_ids);
  const currentState = plan?.current_state || {};
  const currentModelId = String(
    draft?.current_model_id
    || currentState?.approved_model?.model_id
    || currentState?.released_model?.model_id
    || currentState?.submitted_model?.model_id
    || localStorage.getItem(STORAGE_KEYS.focusModelId)
    || ''
  ).trim();
  const lastTaskId = String(localStorage.getItem(STORAGE_KEYS.lastTaskId) || '').trim();
  const trainingAssetIds = splitCsv(localStorage.getItem(STORAGE_KEYS.prefillTrainingAssetIds));
  const trainingValidationAssetIds = splitCsv(localStorage.getItem(STORAGE_KEYS.prefillTrainingValidationAssetIds));
  const trainingDatasetVersionId = String(localStorage.getItem(STORAGE_KEYS.prefillTrainingDatasetVersionId) || '').trim();
  const focusTrainingJobId = String(localStorage.getItem(STORAGE_KEYS.focusTrainingJobId) || '').trim();
  const recentActions = readAiRecentActions();
  const pending = readAiPendingConfirmations();
  const issueHint = `${goal} ${sourcePath} ${(recentActions || []).map((item) => item?.title || '').join(' ')} ${(pending || []).map((item) => item?.title || '').join(' ')}`;
  const hasIssueSignals = /(失败|故障|异常|排障|阻塞|卡住|没开始|超时|stuck|failed|troubleshoot|error)/i.test(issueHint);
  const recommendedPath = workflowRouteForAction(plan?.primary_action || {});
  const recommendedKind = routeKindFromPath(recommendedPath);
  return {
    goal,
    sourcePath,
    taskType,
    taskLabel: aiTaskLabel(taskType),
    assetIds,
    currentModelId,
    lastTaskId,
    trainingAssetIds,
    trainingValidationAssetIds,
    trainingDatasetVersionId,
    focusTrainingJobId,
    hasIssueSignals,
    recommendedPath,
    recommendedKind,
    hasAssets: assetIds.length > 0,
    hasTrainingSeed: Boolean(trainingAssetIds.length || trainingValidationAssetIds.length || trainingDatasetVersionId || focusTrainingJobId),
    hasModelSeed: Boolean(currentModelId),
    hasResultSeed: Boolean(lastTaskId),
  };
}

function inferFlowId(routeKind, signals, storeFlowId = '') {
  const remembered = FLOW_DEFINITIONS[storeFlowId];
  if (remembered && (!routeKind || remembered.steps.includes(routeKind))) {
    return remembered.id;
  }
  if (routeKind === 'train') return 'training';
  if (routeKind === 'deploy') return 'release';
  if (routeKind === 'results') return signals.recommendedKind === 'train' ? 'training' : 'validation';
  if (routeKind === 'troubleshoot') return 'troubleshoot';
  if (signals.recommendedKind === 'results') return 'validation';
  if (signals.recommendedKind === 'deploy') return 'release';
  if (signals.recommendedKind === 'troubleshoot') return 'troubleshoot';
  return 'training';
}

function stepSignature(stepKey, signals) {
  const base = {
    goal: signals.goal,
    source_path: signals.sourcePath,
    task_type: signals.taskType,
    asset_ids: signals.assetIds,
    current_model_id: signals.currentModelId,
    last_task_id: signals.lastTaskId,
  };
  if (stepKey === 'upload') return JSON.stringify({ goal: base.goal, asset_ids: base.asset_ids });
  if (stepKey === 'train') return JSON.stringify({ ...base, training_assets: signals.trainingAssetIds, validation_assets: signals.trainingValidationAssetIds, dataset_version: signals.trainingDatasetVersionId, training_job_id: signals.focusTrainingJobId });
  if (stepKey === 'deploy') return JSON.stringify({ ...base, current_model_id: signals.currentModelId });
  if (stepKey === 'results') return JSON.stringify({ ...base, current_model_id: signals.currentModelId, last_task_id: signals.lastTaskId });
  return JSON.stringify({ goal: base.goal, source_path: base.source_path, last_task_id: base.last_task_id, issue: signals.hasIssueSignals });
}

function readCompletedEntry(completed, stepKey) {
  const value = completed?.[stepKey];
  return value && typeof value === 'object' ? value : null;
}

function isAutoCompleted(stepKey, signals) {
  if (stepKey === 'upload') {
    return Boolean(
      signals.hasAssets
      || signals.hasTrainingSeed
      || signals.hasModelSeed
      || signals.hasResultSeed
    );
  }
  return false;
}

function unlockState(stepKey, completedMap, signals, flowId) {
  if (stepKey === 'upload') return { unlocked: true, reason: '' };
  if (stepKey === 'train') {
    if (!signals.hasAssets) return { unlocked: false, reason: '先上传样例或数据集。' };
    return { unlocked: true, reason: '' };
  }
  if (stepKey === 'deploy') {
    if (flowId === 'release' && signals.hasModelSeed) return { unlocked: true, reason: '' };
    if (!completedMap.train && !signals.hasModelSeed) return { unlocked: false, reason: '先完成训练准备，或先带入候选模型。' };
    return { unlocked: true, reason: '' };
  }
  if (stepKey === 'results') {
    if (flowId === 'validation') {
      if (!signals.hasAssets && !signals.hasResultSeed) return { unlocked: false, reason: '先带入样例或已有任务编号。' };
      return { unlocked: true, reason: '' };
    }
    if (!completedMap.deploy && !signals.hasResultSeed) return { unlocked: false, reason: '先完成发布准备，或先带入已有任务结果。' };
    return { unlocked: true, reason: '' };
  }
  if (stepKey === 'troubleshoot') {
    if (signals.hasIssueSignals || signals.hasResultSeed || completedMap.results) return { unlocked: true, reason: '' };
    return { unlocked: false, reason: '当前没有阻塞信号，先完成验证或带入任务结果。' };
  }
  return { unlocked: false, reason: '当前步骤尚未解锁。' };
}

function buildStepValidation(stepKey, signals) {
  if (stepKey === 'upload') {
    return {
      valid: signals.hasAssets,
      message: signals.hasAssets ? '已带入可用样例。' : '请先上传至少一份样例资源。',
    };
  }
  if (stepKey === 'train') {
    return {
      valid: signals.hasTrainingSeed,
      message: signals.hasTrainingSeed ? '训练输入已准备完成。' : '请先在训练专家页补齐数据集、工作区或训练作业。',
    };
  }
  if (stepKey === 'deploy') {
    return {
      valid: signals.hasModelSeed,
      message: signals.hasModelSeed ? '已带入候选模型。' : '请先在模型专家页确认待发布模型。',
    };
  }
  if (stepKey === 'results') {
    return {
      valid: signals.hasResultSeed || (signals.hasAssets && signals.hasModelSeed),
      message: signals.hasResultSeed
        ? '已有任务结果，可继续验收。'
        : '请先执行验证任务，或至少带入模型与样例。',
    };
  }
  return {
    valid: signals.hasIssueSignals || signals.hasResultSeed,
    message: signals.hasIssueSignals || signals.hasResultSeed ? '已有可排查对象。' : '当前没有需要排查的对象。',
  };
}

export function readWorkflowSessionStore() {
  return normalizeStore(safeStorageJson(STORAGE_KEYS.workflowSession, {}));
}

export function persistWorkflowSessionStore(value) {
  writeStorageJson(STORAGE_KEYS.workflowSession, normalizeStore(value));
}

function workflowAiContextFromResolved(resolved, signals) {
  return {
    flow_id: resolved.flow.id,
    flow_title: resolved.flow.title,
    current_step: resolved.currentStep?.key || '',
    current_step_title: resolved.currentStep?.title || '',
    current_step_index: resolved.currentStep ? resolved.currentStep.index + 1 : 0,
    total_steps: resolved.steps.length,
    next_step: resolved.nextStep?.key || '',
    next_step_title: resolved.nextStep?.title || '',
    can_continue: Boolean(resolved.canContinue),
    can_go_back: Boolean(resolved.backStep),
    has_pending_confirmations: Boolean(readAiPendingConfirmations().length),
    step_statuses: resolved.steps.map((step) => ({
      key: step.key,
      title: step.title,
      status: step.status,
      locked_reason: step.lockedReason || '',
      validation_message: step.validationMessage || '',
    })),
    task_type: signals.taskType,
    task_label: signals.taskLabel,
    asset_count: signals.assetIds.length,
    last_task_id: signals.lastTaskId,
  };
}

function findFirstIncompleteStep(flowSteps, completedMap, unlockMap) {
  return flowSteps.find((stepKey) => !completedMap[stepKey] && unlockMap[stepKey]?.unlocked) || '';
}

export function resolveWorkflowSession({ route = null, draft = readAiWorkflowDraft(), plan = null } = {}) {
  const routeKind = inferRouteKind(route);
  const store = readWorkflowSessionStore();
  const signals = buildWorkflowSignals(draft, plan);
  const flowId = inferFlowId(routeKind, signals, store.flow_id);
  const flow = FLOW_DEFINITIONS[flowId] || FLOW_DEFINITIONS.training;
  const signatures = Object.fromEntries(flow.steps.map((stepKey) => [stepKey, stepSignature(stepKey, signals)]));
  const completedMap = {};
  const invalidatedMap = {};
  const changedMap = {};
  let downstreamInvalidated = false;

  flow.steps.forEach((stepKey) => {
    const stored = readCompletedEntry(store.completed, stepKey);
    const validation = buildStepValidation(stepKey, signals);
    const autoDone = isAutoCompleted(stepKey, signals);
    const explicitDone = stored?.signature === signatures[stepKey];
    const changed = Boolean(stored && stored.signature !== signatures[stepKey]);
    changedMap[stepKey] = changed;

    let completed = Boolean(autoDone || explicitDone);
    let invalidated = Boolean(downstreamInvalidated && stored);

    // Input steps like "upload" may remain complete after content changed,
    // but every downstream dependent step must be re-confirmed.
    if (changed && stepKey === 'upload' && validation.valid) {
      completed = true;
      invalidated = false;
      downstreamInvalidated = true;
    } else if (changed) {
      completed = false;
      invalidated = true;
      downstreamInvalidated = true;
    } else if (downstreamInvalidated && stored) {
      completed = false;
      invalidated = true;
    }

    completedMap[stepKey] = completed;
    invalidatedMap[stepKey] = invalidated;
  });

  const unlockMap = {};
  flow.steps.forEach((stepKey) => {
    unlockMap[stepKey] = unlockState(stepKey, completedMap, signals, flowId);
  });

  const firstAttentionStep = flow.steps.find((stepKey) => invalidatedMap[stepKey] && unlockMap[stepKey]?.unlocked) || '';
  const firstIncomplete = findFirstIncompleteStep(flow.steps, completedMap, unlockMap);
  const requestedStep = flow.steps.includes(routeKind) ? routeKind : '';
  const requestedAllowed = Boolean(
    requestedStep
    && (
      completedMap[requestedStep]
      || requestedStep === firstAttentionStep
      || requestedStep === firstIncomplete
      || (flow.steps.length === 1 && unlockMap[requestedStep]?.unlocked)
    )
  );
  const currentStepKey = requestedAllowed
    ? requestedStep
    : (firstAttentionStep || firstIncomplete || flow.steps.find((stepKey) => completedMap[stepKey]) || flow.steps[0]);

  const currentValidation = buildStepValidation(currentStepKey, signals);
  const prospectiveCompletedMap = {
    ...completedMap,
    [currentStepKey]: completedMap[currentStepKey] || currentValidation.valid,
  };
  const prospectiveUnlockMap = {};
  flow.steps.forEach((stepKey) => {
    prospectiveUnlockMap[stepKey] = unlockState(stepKey, prospectiveCompletedMap, signals, flowId);
  });

  const steps = flow.steps.map((stepKey, index) => {
    const def = STEP_DEFINITIONS[stepKey];
    const validation = buildStepValidation(stepKey, signals);
    let status = 'locked';
    if (stepKey === currentStepKey) {
      status = 'current';
    } else if (invalidatedMap[stepKey]) {
      status = 'error';
    } else if (completedMap[stepKey]) {
      status = 'completed';
    } else if (prospectiveUnlockMap[stepKey]?.unlocked) {
      status = 'available';
    }
    return {
      ...def,
      index,
      status,
      completed: completedMap[stepKey],
      available: prospectiveUnlockMap[stepKey]?.unlocked,
      lockedReason: prospectiveUnlockMap[stepKey]?.reason || unlockMap[stepKey]?.reason || '',
      validationMessage: validation.message,
      valid: validation.valid,
      clickable: status === 'completed',
      error: invalidatedMap[stepKey],
      completedAt: store.completed?.[stepKey]?.completed_at || '',
    };
  });

  const currentStep = steps.find((step) => step.key === currentStepKey) || steps[0];
  const currentIndex = steps.findIndex((step) => step.key === currentStep?.key);
  const nextStep = steps.slice(currentIndex + 1).find((step) => step.status === 'available') || null;
  const backStep = [...steps].slice(0, currentIndex).reverse().find((step) => step.status === 'completed') || null;
  const needsAttention = steps.filter((step) => step.error);
  const guardReason = !requestedAllowed && requestedStep
    ? (unlockMap[requestedStep]?.reason || `${STEP_DEFINITIONS[requestedStep]?.title || '该步骤'} 尚未解锁。`)
    : '';

  return {
    flow,
    store,
    signals,
    steps,
    currentStep,
    nextStep,
    backStep,
    canContinue: Boolean(currentStep?.valid && nextStep),
    needsAttention,
    guard: {
      allowed: !requestedStep || requestedAllowed,
      redirectPath: requestedAllowed ? '' : (currentStep?.routePath || flow.steps[0]),
      reason: guardReason,
    },
    aiContext: workflowAiContextFromResolved({
      flow,
      steps,
      currentStep,
      nextStep,
      backStep,
      canContinue: Boolean(currentStep?.valid && nextStep),
    }, signals),
    signatures,
  };
}

function persistStorePatch(patch = {}) {
  const current = readWorkflowSessionStore();
  persistWorkflowSessionStore({
    ...current,
    ...patch,
    updated_at: new Date().toISOString(),
  });
}

export const WorkflowSessionStore = {
  read: readWorkflowSessionStore,
  persist: persistWorkflowSessionStore,
  touchCurrentStep(stepKey, context = {}) {
    const resolved = resolveWorkflowSession(context);
    persistStorePatch({
      flow_id: resolved.flow.id,
      current_step: stepKey || resolved.currentStep?.key || resolved.store.current_step || '',
    });
    return resolveWorkflowSession(context);
  },
  completeStep(stepKey, context = {}) {
    const resolved = resolveWorkflowSession(context);
    if (!stepKey || !resolved.signatures[stepKey]) return resolved;
    const nextCompleted = {
      ...(resolved.store.completed || {}),
      [stepKey]: {
        signature: resolved.signatures[stepKey],
        completed_at: new Date().toISOString(),
      },
    };
    persistStorePatch({
      flow_id: resolved.flow.id,
      current_step: stepKey,
      completed: nextCompleted,
    });
    return resolveWorkflowSession(context);
  },
  clear() {
    localStorage.removeItem(STORAGE_KEYS.workflowSession);
  },
};

export const WorkflowStateMachine = {
  resolve: resolveWorkflowSession,
};

export const StepStateResolver = {
  routeKind: inferRouteKind,
  routeKindFromPath,
};

export const WorkflowNavigationController = {
  guardRoute(route, context = {}) {
    return resolveWorkflowSession({ ...context, route }).guard;
  },
  getNextStepPath(context = {}) {
    return resolveWorkflowSession(context).nextStep?.routePath || '';
  },
  getBackStepPath(context = {}) {
    return resolveWorkflowSession(context).backStep?.routePath || '';
  },
};
