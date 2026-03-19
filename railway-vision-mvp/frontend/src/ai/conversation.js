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

function normalizeMessage(message = {}) {
  return {
    id: String(message.id || '').trim(),
    role: String(message.role || 'assistant').trim() || 'assistant',
    kind: String(message.kind || 'text').trim() || 'text',
    text: String(message.text || '').trim(),
    created_at: String(message.created_at || new Date().toISOString()).trim(),
    status: String(message.status || 'ready').trim() || 'ready',
    attachments: Array.isArray(message.attachments) ? message.attachments.map(normalizeAttachment) : [],
    plan: message.plan ? clone(message.plan) : null,
    workflow_context: message.workflow_context ? clone(message.workflow_context) : null,
    actions: Array.isArray(message.actions) ? clone(message.actions) : [],
    error: String(message.error || '').trim(),
  };
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
