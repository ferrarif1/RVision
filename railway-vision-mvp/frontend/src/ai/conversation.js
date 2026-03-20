import { STORAGE_KEYS } from '../config/brand.js';
import {
  persistAiSessions,
  readAiSessions,
  safeStorageJson,
  writeStorageJson,
} from './runtime.js';

const NEW_SESSION_KEY = 'new';

function clone(value) {
  return JSON.parse(JSON.stringify(value ?? null));
}

function derivePlanMessageText(message = {}) {
  const plan = message?.plan && typeof message.plan === 'object' ? message.plan : null;
  if (String(message.role || '').trim() !== 'assistant') return String(message.text || '').trim();
  if (String(message.kind || '').trim() !== 'plan') return String(message.text || '').trim();
  return String(
    plan?.llm_advice?.summary
    || message.text
    || plan?.guidance_summary
    || plan?.primary_action?.summary
    || ''
  ).trim();
}

function normalizeMessage(message = {}) {
  const plan = message?.plan && typeof message.plan === 'object' ? clone(message.plan) : null;
  const hasPrimaryAction = !!(plan && plan.primary_action && typeof plan.primary_action === 'object');
  return {
    id: String(message.id || '').trim(),
    role: String(message.role || 'assistant').trim() || 'assistant',
    kind: String(message.kind || 'text').trim() || 'text',
    text: derivePlanMessageText(message),
    created_at: String(message.created_at || new Date().toISOString()).trim(),
    status: String(message.status || 'ready').trim() || 'ready',
    attachments: Array.isArray(message.attachments) ? message.attachments.map(normalizeAttachment) : [],
    plan,
    workflow_context: hasPrimaryAction && message.workflow_context ? clone(message.workflow_context) : null,
    actions: Array.isArray(message.actions) ? clone(message.actions) : [],
    error: String(message.error || '').trim(),
  };
}

function deriveSessionSummaryFromMessages(messages = []) {
  const latestAssistantPlan = (Array.isArray(messages) ? messages : [])
    .slice()
    .reverse()
    .find((item) => item?.role === 'assistant' && item?.kind === 'plan');
  if (!latestAssistantPlan) return '';
  return String(latestAssistantPlan.text || '').trim();
}

export function normalizeAttachment(attachment = {}) {
  return {
    id: String(attachment.id || '').trim(),
    asset_id: String(attachment.asset_id || '').trim(),
    name: String(attachment.name || attachment.file_name || '').trim(),
    type: String(attachment.type || 'file').trim() || 'file',
    mime_type: String(attachment.mime_type || '').trim(),
    extension: String(attachment.extension || '').trim(),
    size: Number(attachment.size || 0) || 0,
    preview_url: String(attachment.preview_url || '').trim(),
    status: String(attachment.status || 'ready').trim() || 'ready',
    editable: attachment.editable !== false,
    metadata: attachment.metadata && typeof attachment.metadata === 'object' ? clone(attachment.metadata) : {},
  };
}

function normalizeDraft(draft = {}) {
  return {
    text: String(draft.text || '').trim(),
    mode: String(draft.mode || 'default').trim() || 'default',
    attachments: Array.isArray(draft.attachments) ? draft.attachments.map(normalizeAttachment) : [],
    updated_at: String(draft.updated_at || new Date().toISOString()).trim(),
  };
}

function normalizeSession(session = {}) {
  return {
    session_id: String(session.session_id || '').trim(),
    title: String(session.title || '未命名会话').trim(),
    created_at: String(session.created_at || new Date().toISOString()).trim(),
    updated_at: String(session.updated_at || session.created_at || new Date().toISOString()).trim(),
    summary: String(session.summary || '').trim(),
    task_type: String(session.task_type || '').trim(),
    asset_ids: Array.isArray(session.asset_ids) ? session.asset_ids.map((item) => String(item || '').trim()).filter(Boolean) : [],
    workflow_path: String(session.workflow_path || '').trim(),
    expert_path: String(session.expert_path || '').trim(),
    primary_action: session.primary_action ? clone(session.primary_action) : null,
    workflow_context: session.workflow_context ? clone(session.workflow_context) : null,
    last_message_preview: String(session.last_message_preview || '').trim(),
    message_count: Number(session.message_count || 0) || 0,
    provider_id: String(session.provider_id || '').trim(),
    model_name: String(session.model_name || '').trim(),
    model_label: String(session.model_label || '').trim(),
  };
}

function normalizeMemoryEntry(entry = {}) {
  return {
    id: String(entry.id || '').trim(),
    title: String(entry.title || '未命名记忆').trim() || '未命名记忆',
    summary: String(entry.summary || '').trim(),
    content: String(entry.content || '').trim(),
    source_session_id: String(entry.source_session_id || '').trim(),
    source_message_id: String(entry.source_message_id || '').trim(),
    task_type: String(entry.task_type || '').trim(),
    asset_ids: Array.isArray(entry.asset_ids) ? entry.asset_ids.map((item) => String(item || '').trim()).filter(Boolean) : [],
    model_name: String(entry.model_name || '').trim(),
    model_label: String(entry.model_label || '').trim(),
    created_at: String(entry.created_at || new Date().toISOString()).trim(),
    updated_at: String(entry.updated_at || entry.created_at || new Date().toISOString()).trim(),
  };
}

export function buildAttachmentFromUpload({ result, file, previewUrl = '', metadata = {} } = {}) {
  const name = String(file?.name || result?.file_name || result?.id || 'file').trim();
  const mimeType = String(file?.type || result?.mime_type || '').trim();
  const extension = name.includes('.') ? name.split('.').pop() : '';
  return normalizeAttachment({
    id: `att-${Math.random().toString(36).slice(2, 10)}`,
    asset_id: String(result?.asset_id || result?.id || '').trim(),
    name,
    type: mimeType.startsWith('image/') ? 'image' : 'file',
    mime_type: mimeType,
    extension,
    size: Number(file?.size || result?.meta?.size || 0) || 0,
    preview_url: previewUrl,
    status: 'ready',
    editable: mimeType.startsWith('image/'),
    metadata,
  });
}

export function readAiMessageMap() {
  const value = safeStorageJson(STORAGE_KEYS.aiMessageMap, {});
  return value && typeof value === 'object' ? value : {};
}

export function persistAiMessageMap(value) {
  writeStorageJson(STORAGE_KEYS.aiMessageMap, value && typeof value === 'object' ? value : {});
}

export function readAiMemoryEntries() {
  const value = safeStorageJson(STORAGE_KEYS.aiMemoryEntries, []);
  return (Array.isArray(value) ? value : [])
    .map(normalizeMemoryEntry)
    .sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))
    .slice(0, 40);
}

export function persistAiMemoryEntries(rows) {
  writeStorageJson(STORAGE_KEYS.aiMemoryEntries, (Array.isArray(rows) ? rows : []).map(normalizeMemoryEntry).slice(0, 40));
}

export function reconcileConversationStorage() {
  const rawSessions = readAiSessions().map(normalizeSession);
  const rawMessageMap = readAiMessageMap();
  let changed = false;
  const nextMessageMap = {};
  for (const [sessionId, rows] of Object.entries(rawMessageMap || {})) {
    const normalizedRows = (Array.isArray(rows) ? rows : []).map(normalizeMessage);
    nextMessageMap[sessionId] = normalizedRows;
    if (JSON.stringify(rows || []) !== JSON.stringify(normalizedRows)) {
      changed = true;
    }
  }
  const nextSessions = rawSessions.map((session) => {
    const sessionMessages = Array.isArray(nextMessageMap[session.session_id]) ? nextMessageMap[session.session_id] : [];
    const latestSummary = deriveSessionSummaryFromMessages(sessionMessages);
    const latestPreview = latestSummary || session.last_message_preview;
    const latestAssistantPlan = sessionMessages
      .slice()
      .reverse()
      .find((item) => item?.role === 'assistant' && item?.kind === 'plan');
    const latestPrimaryAction = latestAssistantPlan?.plan?.primary_action && typeof latestAssistantPlan.plan.primary_action === 'object'
      ? clone(latestAssistantPlan.plan.primary_action)
      : null;
    const nextSession = normalizeSession({
      ...session,
      summary: latestSummary || session.summary,
      last_message_preview: latestPreview,
      message_count: sessionMessages.length || session.message_count,
      primary_action: latestAssistantPlan ? latestPrimaryAction : session.primary_action,
      workflow_context: latestPrimaryAction ? session.workflow_context : null,
      workflow_path: latestAssistantPlan ? (latestPrimaryAction ? session.workflow_path : '') : session.workflow_path,
      expert_path: latestAssistantPlan ? (latestPrimaryAction ? session.expert_path : '') : session.expert_path,
    });
    if (JSON.stringify(session) !== JSON.stringify(nextSession)) {
      changed = true;
    }
    return nextSession;
  });
  if (changed) {
    persistAiMessageMap(nextMessageMap);
    persistAiSessions(nextSessions);
  }
  return { sessions: nextSessions, messageMap: nextMessageMap, changed };
}

export function upsertAiMemoryEntry(entry = {}) {
  const normalized = normalizeMemoryEntry(entry);
  if (!normalized.id) return normalized;
  const next = [
    normalized,
    ...readAiMemoryEntries().filter((item) => item.id !== normalized.id),
  ]
    .sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))
    .slice(0, 40);
  persistAiMemoryEntries(next);
  return normalized;
}

export function removeAiMemoryEntry(memoryId = '') {
  const key = String(memoryId || '').trim();
  if (!key) return;
  persistAiMemoryEntries(readAiMemoryEntries().filter((item) => item.id !== key));
}

export function readSessionMessages(sessionId) {
  const rows = readAiMessageMap()?.[sessionId];
  return Array.isArray(rows) ? rows.map(normalizeMessage) : [];
}

export function persistSessionMessages(sessionId, rows) {
  const map = readAiMessageMap();
  map[sessionId] = (Array.isArray(rows) ? rows : []).map(normalizeMessage).slice(-120);
  persistAiMessageMap(map);
}

export function appendSessionMessage(sessionId, message) {
  const next = [...readSessionMessages(sessionId), normalizeMessage(message)];
  persistSessionMessages(sessionId, next);
  return next;
}

export function replaceSessionMessage(sessionId, messageId, nextMessage) {
  const next = readSessionMessages(sessionId).map((message) => (
    message.id === messageId ? normalizeMessage({ ...message, ...nextMessage }) : message
  ));
  persistSessionMessages(sessionId, next);
  return next;
}

export function removeSessionMessage(sessionId, messageId) {
  const next = readSessionMessages(sessionId).filter((message) => message.id !== messageId);
  persistSessionMessages(sessionId, next);
  return next;
}

export function readComposerDraftMap() {
  const value = safeStorageJson(STORAGE_KEYS.aiComposerDraftMap, {});
  return value && typeof value === 'object' ? value : {};
}

export function persistComposerDraftMap(value) {
  writeStorageJson(STORAGE_KEYS.aiComposerDraftMap, value && typeof value === 'object' ? value : {});
}

export function readComposerDraft(sessionId = NEW_SESSION_KEY) {
  const value = readComposerDraftMap()?.[sessionId];
  return normalizeDraft(value || {});
}

export function persistComposerDraft(sessionId = NEW_SESSION_KEY, draft = {}) {
  const next = readComposerDraftMap();
  next[sessionId] = normalizeDraft(draft);
  persistComposerDraftMap(next);
}

export function clearComposerDraft(sessionId = NEW_SESSION_KEY) {
  const next = readComposerDraftMap();
  delete next[sessionId];
  persistComposerDraftMap(next);
}

export function readActiveAiSessionId() {
  return String(localStorage.getItem(STORAGE_KEYS.aiActiveSessionId) || '').trim();
}

export function persistActiveAiSessionId(sessionId = '') {
  if (!sessionId) {
    localStorage.removeItem(STORAGE_KEYS.aiActiveSessionId);
    return;
  }
  localStorage.setItem(STORAGE_KEYS.aiActiveSessionId, String(sessionId || '').trim());
}

export function upsertConversationSession(session = {}) {
  const normalized = normalizeSession(session);
  if (!normalized.session_id) return normalized;
  const rows = readAiSessions();
  const next = [
    normalized,
    ...rows.filter((item) => item.session_id !== normalized.session_id).map(normalizeSession),
  ]
    .sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))
    .slice(0, 24);
  persistAiSessions(next);
  return normalized;
}

export function removeConversationSession(sessionId = '') {
  const key = String(sessionId || '').trim();
  if (!key) return;
  persistAiSessions(readAiSessions().filter((item) => item.session_id !== key));
  const messageMap = readAiMessageMap();
  delete messageMap[key];
  persistAiMessageMap(messageMap);
  clearComposerDraft(key);
  if (readActiveAiSessionId() === key) persistActiveAiSessionId('');
}

export function touchConversationSession(sessionId, patch = {}) {
  const existing = readAiSessions().find((item) => item.session_id === sessionId) || {};
  const messages = readSessionMessages(sessionId);
  const lastMessage = messages[messages.length - 1] || null;
  return upsertConversationSession({
    ...existing,
    ...patch,
    session_id: sessionId,
    updated_at: new Date().toISOString(),
    created_at: existing.created_at || patch.created_at || new Date().toISOString(),
    last_message_preview: patch.last_message_preview || lastMessage?.text || existing.last_message_preview || '',
    message_count: patch.message_count ?? messages.length,
  });
}

export function createConversationSession({
  sessionId = `ai-session-${Math.random().toString(36).slice(2, 10)}`,
  title = '新会话',
  summary = '',
  taskType = '',
  assetIds = [],
  workflowPath = '',
  expertPath = '',
  primaryAction = null,
  workflowContext = null,
} = {}) {
  const session = upsertConversationSession({
    session_id: sessionId,
    title,
    summary,
    task_type: taskType,
    asset_ids: assetIds,
    workflow_path: workflowPath,
    expert_path: expertPath,
    primary_action: primaryAction,
    workflow_context: workflowContext,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    last_message_preview: '',
    message_count: 0,
  });
  persistActiveAiSessionId(session.session_id);
  return session;
}

export function listConversationSessions() {
  return readAiSessions().map(normalizeSession);
}

export function saveConversationMemory(sessionId = '', { modelName = '', modelLabel = '' } = {}) {
  const key = String(sessionId || '').trim();
  if (!key) return null;
  const session = listConversationSessions().find((item) => item.session_id === key) || null;
  const messages = readSessionMessages(key)
    .filter((item) => item.kind !== 'typing' && String(item.text || '').trim())
    .slice(-8);
  if (!session && !messages.length) return null;
  const assistantSummary = [...messages].reverse().find((item) => item.role === 'assistant' && item.text)?.text || '';
  const content = messages
    .map((item) => `${item.role === 'user' ? '用户' : 'AI'}：${String(item.text || '').trim()}`)
    .filter(Boolean)
    .join('\n');
  const existing = readAiMemoryEntries().find((item) => item.source_session_id === key);
  return upsertAiMemoryEntry({
    id: existing?.id || `mem-${key}`,
    title: String(session?.title || '会话记忆').trim() || '会话记忆',
    summary: String(session?.summary || assistantSummary || content.slice(0, 120) || '已保存当前会话上下文').trim(),
    content,
    source_session_id: key,
    task_type: String(session?.task_type || '').trim(),
    asset_ids: Array.isArray(session?.asset_ids) ? session.asset_ids : [],
    model_name: String(modelName || session?.model_name || '').trim(),
    model_label: String(modelLabel || session?.model_label || '').trim(),
    created_at: existing?.created_at || new Date().toISOString(),
    updated_at: new Date().toISOString(),
  });
}

export function buildConversationHistoryContext(messages = [], limit = 8) {
  return (Array.isArray(messages) ? messages : [])
    .filter((item) => item && item.kind !== 'typing' && (String(item.text || '').trim() || (Array.isArray(item.attachments) && item.attachments.length)))
    .slice(-Math.max(1, limit))
    .map((item) => ({
      role: String(item.role || 'assistant').trim() || 'assistant',
      text: String(item.text || '').trim(),
      created_at: String(item.created_at || '').trim(),
      attachments: Array.isArray(item.attachments)
        ? item.attachments.slice(0, 4).map((attachment) => ({
          asset_id: String(attachment?.asset_id || '').trim(),
          name: String(attachment?.name || '').trim(),
          type: String(attachment?.type || 'file').trim(),
        }))
        : [],
    }));
}

export function buildAiMemoryContext(entries = [], limit = 8) {
  return (Array.isArray(entries) ? entries : [])
    .slice(0, Math.max(1, limit))
    .map((item) => ({
      id: String(item.id || '').trim(),
      title: String(item.title || '').trim(),
      summary: String(item.summary || '').trim(),
      content: String(item.content || '').trim(),
      task_type: String(item.task_type || '').trim(),
      asset_ids: Array.isArray(item.asset_ids) ? item.asset_ids.slice(0, 8).map((part) => String(part || '').trim()).filter(Boolean) : [],
      model_name: String(item.model_name || '').trim(),
      updated_at: String(item.updated_at || '').trim(),
    }))
    .filter((item) => item.title || item.summary || item.content);
}

export function buildMessage({
  id = `msg-${Math.random().toString(36).slice(2, 10)}`,
  role = 'assistant',
  kind = 'text',
  text = '',
  attachments = [],
  status = 'ready',
  plan = null,
  workflowContext = null,
  actions = [],
  error = '',
} = {}) {
  return normalizeMessage({
    id,
    role,
    kind,
    text,
    attachments,
    status,
    plan,
    workflow_context: workflowContext,
    actions,
    error,
    created_at: new Date().toISOString(),
  });
}

export const CONVERSATION_KEYS = {
  newSession: NEW_SESSION_KEY,
};
