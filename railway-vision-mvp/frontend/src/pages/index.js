import { api, apiForm, apiPost, formatDateTime, normalizeUiErrorMessage, toQuery } from '../core/api.js';
import { BRAND_NAME, BRAND_TAGLINE, STORAGE_KEYS } from '../config/brand.js';

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function renderLoading(text = '加载中...') {
  return `<div class="state loading">${esc(text)}</div>`;
}

function renderEmpty(text = '暂无数据') {
  return `<div class="state empty">${esc(text)}</div>`;
}

function renderError(text) {
  return `<div class="state error">${esc(text || '加载失败')}</div>`;
}

function renderPageHero({ eyebrow = '', title = '', summary = '', highlights = [], actions = [] } = {}) {
  const safeHighlights = Array.isArray(highlights) ? highlights.filter(Boolean) : [];
  const safeActions = Array.isArray(actions) ? actions.filter((item) => item?.path && item?.label) : [];
  return `
    <section class="card page-hero">
      <div class="page-hero-copy">
        ${eyebrow ? `<span class="hero-eyebrow">${esc(eyebrow)}</span>` : ''}
        <h2>${esc(title)}</h2>
        ${summary ? `<p>${esc(summary)}</p>` : ''}
        ${safeHighlights.length ? `
          <div class="page-hero-highlights">
            ${safeHighlights.map((item) => `<span class="page-hero-pill">${esc(item)}</span>`).join('')}
          </div>
        ` : ''}
      </div>
      ${safeActions.length ? `
        <div class="page-hero-actions">
          ${safeActions.map((item) => `<button class="${item.primary ? 'primary' : 'ghost'}" type="button" data-page-nav="${esc(item.path)}">${esc(item.label)}</button>`).join('')}
        </div>
      ` : ''}
    </section>
  `;
}

function renderWorkbenchOverview({ title = '', summary = '', status = '', metrics = [], actions = [] } = {}) {
  const metricRows = Array.isArray(metrics) ? metrics.filter((item) => item && (item.label || item.value || item.note)) : [];
  const actionRows = Array.isArray(actions) ? actions.filter((item) => item && item.label) : [];
  return `
    <div class="workbench-overview">
      <div class="workbench-overview-main">
        <div>
          <strong>${esc(title || '当前工作台')}</strong>
          ${status ? `<span class="badge">${esc(status)}</span>` : ''}
        </div>
        <p>${esc(summary || '选择一项后，这里会显示当前状态和推荐下一步动作。')}</p>
      </div>
      ${metricRows.length ? `
        <div class="workbench-overview-grid">
          ${metricRows.map((item) => `
            <article class="metric-card compact">
              <h4>${esc(item.label || '-')}</h4>
              <p class="metric">${esc(item.value ?? '-')}</p>
              <span>${esc(item.note || '')}</span>
            </article>
          `).join('')}
        </div>
      ` : ''}
      ${actionRows.length ? `
        <div class="workbench-overview-actions">
          ${actionRows.map((item) => `<button class="${item.primary ? 'primary' : 'ghost'}" type="button" data-workbench-action="${esc(item.id || '')}">${esc(item.label)}</button>`).join('')}
        </div>
      ` : ''}
    </div>
  `;
}

function bindPageNavButtons(root, ctx) {
  root.querySelectorAll('[data-page-nav]').forEach((button) => {
    button.addEventListener('click', () => {
      const path = button.getAttribute('data-page-nav');
      if (path) ctx.navigate(path);
    });
  });
}

function safeJson(value) {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return '{}';
  }
}

function cloneJson(value) {
  if (value === undefined) return undefined;
  return JSON.parse(JSON.stringify(value ?? null));
}

function makeLocalId(prefix = 'id') {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

function normalizeReviewBBox(value) {
  if (!Array.isArray(value) || value.length !== 4) return null;
  const next = value.map((item) => Number.parseInt(item, 10));
  if (next.some((item) => Number.isNaN(item))) return null;
  return next;
}

function clampNumber(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function makeReviewPrediction(prediction, fallbackLabel = 'object') {
  const bbox = normalizeReviewBBox(prediction?.bbox) || [12, 12, 120, 120];
  return {
    _id: String(prediction?._id || makeLocalId('pred')),
    label: String(prediction?.label || fallbackLabel || 'object').trim() || 'object',
    text: String(prediction?.text || prediction?.attributes?.text || '').trim(),
    score: Number(prediction?.score ?? 1),
    bbox,
    attributes: cloneJson(prediction?.attributes || {}) || {},
    source: String(prediction?.source || prediction?.attributes?.review_source || 'auto'),
  };
}

function extractPredictionText(prediction) {
  return String(prediction?.text || prediction?.attributes?.text || '').trim();
}

function predictionBadgeText(prediction) {
  const score = Number.isFinite(Number(prediction?.score)) ? Number(prediction.score).toFixed(2) : '1.00';
  const text = extractPredictionText(prediction);
  if (text) return `${prediction?.label || 'object'}:${text} ${score}`;
  return `${prediction?.label || 'object'}:${score}`;
}

function collectRecognizedTexts(predictions, summary = {}) {
  const values = [
    ...((Array.isArray(predictions) ? predictions : []).map((prediction) => extractPredictionText(prediction))),
    String(summary?.car_number || '').trim(),
  ];
  return [...new Set(values.filter(Boolean))];
}

function normalizeCarNumberText(value) {
  return String(value || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
}

function validateCarNumberByRule(value, rule) {
  const normalized = normalizeCarNumberText(value);
  const pattern = String(rule?.pattern || '^\\d{8}$');
  let valid = false;
  try {
    valid = !!(normalized && new RegExp(pattern).test(normalized));
  } catch {
    valid = false;
  }
  return {
    valid,
    normalized,
    ruleId: String(rule?.rule_id || 'railcar_digits_v1'),
    label: String(rule?.label || '铁路车号 · 8位数字'),
    description: String(rule?.description || '当前默认要求车号为 8 位数字。'),
    pattern,
  };
}

function splitCsv(value) {
  return String(value || '')
    .split(/[\n,，\s]+/)
    .map((v) => v.trim())
    .filter(Boolean);
}

function mergeCsvValues(...values) {
  return [...new Set(values.flatMap((value) => (Array.isArray(value) ? value : splitCsv(value))))];
}

function parseVersionOrdinal(value) {
  const match = String(value || '').trim().toLowerCase().match(/^v(\d+)$/);
  return match ? Number.parseInt(match[1], 10) : 0;
}

function truncateMiddle(value, left = 12, right = 8) {
  const text = String(value || '').trim();
  if (!text) return '-';
  if (text.length <= left + right + 3) return text;
  return `${text.slice(0, left)}...${text.slice(-right)}`;
}

function formatMetricValue(value, options = {}) {
  const { percent = false, digits = 4 } = options;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    const text = String(value ?? '').trim();
    return text || '-';
  }
  if (percent) {
    const normalized = numeric >= 0 && numeric <= 1 ? numeric * 100 : numeric;
    const precision = Number.isInteger(normalized) ? 0 : Math.abs(normalized) >= 10 ? 1 : 2;
    return `${normalized.toFixed(precision)}%`;
  }
  if (Number.isInteger(numeric)) return String(numeric);
  return numeric.toFixed(digits).replace(/\.?0+$/, '');
}

function formatDurationWindow(startedAt, finishedAt, durationSec) {
  let seconds = Number(durationSec);
  if (!Number.isFinite(seconds) || seconds < 0) {
    const start = startedAt ? new Date(startedAt).getTime() : NaN;
    const end = finishedAt ? new Date(finishedAt).getTime() : NaN;
    if (Number.isFinite(start) && Number.isFinite(end) && end >= start) {
      seconds = (end - start) / 1000;
    }
  }
  if (!Number.isFinite(seconds) || seconds < 0) return '-';
  if (seconds < 60) return `${seconds.toFixed(seconds >= 10 ? 0 : 1)} 秒`;
  const totalSeconds = Math.round(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainder = totalSeconds % 60;
  if (hours > 0) return `${hours} 小时 ${minutes} 分`;
  if (minutes > 0) return `${minutes} 分 ${remainder} 秒`;
  return `${remainder} 秒`;
}

function hasSyntheticMarker(value) {
  const text = String(value || '').trim().toLowerCase();
  if (!text) return false;
  return (
    text.startsWith('api-')
    || text.startsWith('api_')
    || text.startsWith('qa-')
    || text.startsWith('qa_')
    || text.startsWith('quick-detect')
    || text.includes('api-regression')
    || text.includes('api_regression')
    || text.includes('api-runtime')
    || text.includes('api_runtime')
    || text.includes('runtime-eval')
    || text.includes('runtime_eval')
  );
}

function isSyntheticAssetRow(row) {
  if (!row || typeof row !== 'object') return false;
  const assetType = String(row.asset_type || '').trim().toLowerCase();
  if (assetType === 'screenshot') return true;
  const meta = row.meta && typeof row.meta === 'object' ? row.meta : {};
  return hasSyntheticMarker(row.file_name)
    || hasSyntheticMarker(row.storage_uri)
    || hasSyntheticMarker(row.source_uri)
    || hasSyntheticMarker(meta.dataset_label)
    || hasSyntheticMarker(meta.use_case)
    || hasSyntheticMarker(meta.intended_model_code);
}

function isSyntheticModelRow(row) {
  if (!row || typeof row !== 'object') return false;
  return hasSyntheticMarker(row.model_code);
}

function isSyntheticTrainingJobRow(row) {
  if (!row || typeof row !== 'object') return false;
  if (row.is_synthetic === true) return true;
  return hasSyntheticMarker(row.target_model_code)
    || isSyntheticModelRow(row.base_model)
    || isSyntheticModelRow(row.candidate_model);
}

function isSyntheticDatasetVersionRow(row) {
  if (!row || typeof row !== 'object') return false;
  return hasSyntheticMarker(row.dataset_label)
    || hasSyntheticMarker(row.source_type)
    || isSyntheticAssetRow(row.asset);
}

function filterBusinessAssets(rows) {
  return (Array.isArray(rows) ? rows : []).filter((row) => !isSyntheticAssetRow(row));
}

function filterBusinessModels(rows) {
  return (Array.isArray(rows) ? rows : []).filter((row) => !isSyntheticModelRow(row));
}

function filterBusinessTrainingJobs(rows) {
  return (Array.isArray(rows) ? rows : []).filter((row) => !isSyntheticTrainingJobRow(row));
}

function filterBusinessDatasetVersions(rows) {
  return (Array.isArray(rows) ? rows : []).filter((row) => !isSyntheticDatasetVersionRow(row));
}

function isCarNumberOcrExportAsset(row) {
  if (!row || typeof row !== 'object') return false;
  const meta = row.meta && typeof row.meta === 'object' ? row.meta : {};
  const sourceUri = String(row.source_uri || '').trim().toLowerCase();
  const datasetKey = String(meta.dataset_key || '').trim().toLowerCase();
  return sourceUri.startsWith('vistral://training/car-number-labeling/export-text-dataset/')
    || datasetKey.startsWith('local-car-number-ocr-text-');
}

function collapseLatestCarNumberExportAssets(rows) {
  const ordered = Array.isArray(rows) ? rows : [];
  const kept = [];
  const seenGroups = new Set();
  let hiddenCount = 0;
  ordered.forEach((row) => {
    if (!isCarNumberOcrExportAsset(row)) {
      kept.push(row);
      return;
    }
    const meta = row.meta && typeof row.meta === 'object' ? row.meta : {};
    const key = [
      String(meta.dataset_key || '').trim().toLowerCase(),
      String(row.source_uri || '').trim().toLowerCase(),
      String(row.file_name || '').trim().toLowerCase(),
    ].join('::');
    if (seenGroups.has(key)) {
      hiddenCount += 1;
      return;
    }
    seenGroups.add(key);
    kept.push(row);
  });
  return { rows: kept, hiddenCount };
}

function renderInfoPanel(title, items, actions = '') {
  const rows = Array.isArray(items) ? items.filter((item) => item && item.label) : [];
  return `
    <div class="selection-summary upload-result-panel">
      <strong>${esc(title || '结果摘要')}</strong>
      ${
        rows.length
          ? `
              <div class="keyvals compact-info-grid">
                ${rows.map((item) => `
                  <div>
                    <span>${esc(item.label)}</span>
                    <strong class="${item.mono ? 'mono' : ''}">${esc(item.value ?? '-')}</strong>
                  </div>
                `).join('')}
              </div>
            `
          : ''
      }
      ${actions || ''}
    </div>
  `;
}

function normalizeTrainingHistory(rawHistory) {
  if (!Array.isArray(rawHistory)) return [];
  return rawHistory
    .map((entry) => {
      if (!entry || typeof entry !== 'object') return null;
      const epoch = Number(entry.epoch);
      if (!Number.isInteger(epoch) || epoch <= 0) return null;
      const normalized = { epoch };
      ['train_loss', 'val_loss', 'train_accuracy', 'val_accuracy', 'learning_rate', 'duration_sec'].forEach((key) => {
        const numeric = Number(entry[key]);
        normalized[key] = Number.isFinite(numeric) ? numeric : null;
      });
      return normalized;
    })
    .filter(Boolean)
    .sort((left, right) => left.epoch - right.epoch);
}

function normalizeTrainingCheckpoint(value) {
  if (!value || typeof value !== 'object') return null;
  const epoch = Number(value.epoch);
  if (!Number.isInteger(epoch) || epoch <= 0) return null;
  const numericValue = Number(value.value);
  return {
    epoch,
    metric: String(value.metric || 'val_score').trim() || 'val_score',
    value: Number.isFinite(numericValue) ? numericValue : null,
    path: String(value.path || '').trim() || '',
  };
}

function renderTrainingHistoryChart({ title, description, history, lines, percent = false, lowerIsBetter = false }) {
  const width = 360;
  const height = 182;
  const padding = { top: 18, right: 12, bottom: 24, left: 36 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const availableLines = lines
    .map((line) => ({
      ...line,
      points: history
        .map((entry) => {
          const value = entry[line.key];
          return Number.isFinite(value) ? { epoch: entry.epoch, value } : null;
        })
        .filter(Boolean),
    }))
    .filter((line) => line.points.length);

  if (!availableLines.length) {
    return `
      <article class="training-history-card">
        <div class="training-history-head">
          <div>
            <strong>${esc(title)}</strong>
            <p>${esc(description)}</p>
          </div>
          <span class="badge">暂无历史</span>
        </div>
        <div class="training-history-empty">当前作业还没有回写 epoch 级历史指标。</div>
      </article>
    `;
  }

  const values = availableLines.flatMap((line) => line.points.map((point) => point.value));
  let minValue = Math.min(...values);
  let maxValue = Math.max(...values);
  if (percent) {
    minValue = Math.max(0, minValue);
    maxValue = Math.min(1, maxValue);
  }
  if (!Number.isFinite(minValue) || !Number.isFinite(maxValue)) {
    minValue = 0;
    maxValue = 1;
  }
  if (Math.abs(maxValue - minValue) < 1e-9) {
    const offset = Math.abs(maxValue || 1) * 0.08 || 0.08;
    minValue -= offset;
    maxValue += offset;
  }
  const epochMin = Math.min(...history.map((entry) => entry.epoch));
  const epochMax = Math.max(...history.map((entry) => entry.epoch));
  const epochSpan = Math.max(epochMax - epochMin, 1);
  const valueSpan = Math.max(maxValue - minValue, 1e-9);

  const mapX = (epoch) => padding.left + (((epoch - epochMin) / epochSpan) * plotWidth);
  const mapY = (value) => padding.top + plotHeight - (((value - minValue) / valueSpan) * plotHeight);
  const gridValues = Array.from({ length: 4 }, (_, index) => minValue + ((valueSpan * index) / 3));

  const pathFor = (points) =>
    points
      .map((point, index) => `${index === 0 ? 'M' : 'L'} ${mapX(point.epoch).toFixed(2)} ${mapY(point.value).toFixed(2)}`)
      .join(' ');

  const primaryLine = availableLines[0];
  const firstValue = primaryLine.points[0]?.value;
  const lastValue = primaryLine.points[primaryLine.points.length - 1]?.value;
  const trendDelta = Number.isFinite(firstValue) && Number.isFinite(lastValue) ? lastValue - firstValue : null;
  const trendPrefix = trendDelta == null ? '-' : trendDelta > 0 ? '+' : '';
  const trendLabel = trendDelta == null
    ? '趋势待观察'
    : `${lowerIsBetter ? '收敛变化' : '阶段变化'} ${trendPrefix}${formatMetricValue(trendDelta, { percent, digits: percent ? 2 : 4 })}`;

  return `
    <article class="training-history-card">
      <div class="training-history-head">
        <div>
          <strong>${esc(title)}</strong>
          <p>${esc(description)}</p>
        </div>
        <span class="badge">${esc(`epoch ${history.length}`)}</span>
      </div>
      <svg class="training-history-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(title)}">
        ${gridValues
          .map((value) => {
            const y = mapY(value).toFixed(2);
            return `
              <line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" class="training-history-grid" />
              <text x="8" y="${(Number(y) + 4).toFixed(2)}" class="training-history-axis">${esc(formatMetricValue(value, { percent, digits: percent ? 2 : 4 }))}</text>
            `;
          })
          .join('')}
        <text x="${padding.left}" y="${height - 6}" class="training-history-axis">${esc(`E${epochMin}`)}</text>
        <text x="${width - padding.right - 8}" y="${height - 6}" text-anchor="end" class="training-history-axis">${esc(`E${epochMax}`)}</text>
        ${availableLines
          .map((line) => `<path d="${pathFor(line.points)}" class="training-history-path ${esc(line.className || '')}" />`)
          .join('')}
        ${availableLines
          .flatMap((line) =>
            line.points.map(
              (point) => `<circle cx="${mapX(point.epoch).toFixed(2)}" cy="${mapY(point.value).toFixed(2)}" r="3" class="training-history-point ${esc(line.className || '')}" />`
            )
          )
          .join('')}
      </svg>
      <div class="training-history-legend">
        ${availableLines
          .map((line) => {
            const lastPoint = line.points[line.points.length - 1];
            return `
              <span>
                <i class="${esc(line.className || '')}"></i>
                ${esc(line.label)} · ${esc(formatMetricValue(lastPoint?.value, { percent, digits: percent ? 2 : 4 }))}
              </span>
            `;
          })
          .join('')}
      </div>
      <div class="training-history-foot">
        <span>${esc(trendLabel)}</span>
        <span>${esc(`区间 ${formatMetricValue(minValue, { percent, digits: percent ? 2 : 4 })} ~ ${formatMetricValue(maxValue, { percent, digits: percent ? 2 : 4 })}`)}</span>
      </div>
    </article>
  `;
}

function renderBestCheckpointCard(bestCheckpoint, history, trainer) {
  if (!bestCheckpoint) {
    return `
      <article class="training-checkpoint-card">
        <div class="training-history-head">
          <div>
            <strong>最佳检查点</strong>
            <p>${esc(String(trainer || '受控训练机'))}</p>
          </div>
          <span class="badge">待生成</span>
        </div>
        <div class="training-history-empty">当前训练结果还没有回写 best checkpoint 信息。</div>
      </article>
    `;
  }
  const historyEntry = history.find((item) => item.epoch === bestCheckpoint.epoch) || null;
  const metricLabel = bestCheckpoint.metric || 'val_score';
  return `
    <article class="training-checkpoint-card">
      <div class="training-history-head">
        <div>
            <strong>最佳检查点</strong>
          <p>${esc('训练过程中当前最优的一次 checkpoint，适合做回归和精调参考。')}</p>
        </div>
        <span class="badge">${esc(`epoch ${bestCheckpoint.epoch}`)}</span>
      </div>
      <div class="keyvals compact">
        <div><span>metric</span><strong>${esc(metricLabel)}</strong></div>
        <div><span>value</span><strong>${esc(formatMetricValue(bestCheckpoint.value, { percent: metricLabel.includes('accuracy') || metricLabel.includes('score') }))}</strong></div>
        <div><span>path</span><strong class="mono">${esc(bestCheckpoint.path || '-')}</strong></div>
        <div><span>对应轮次</span><strong>${esc(String(bestCheckpoint.epoch))}</strong></div>
      </div>
      ${
        historyEntry
          ? `<div class="training-checkpoint-summary">
              <span>train_loss：${esc(formatMetricValue(historyEntry.train_loss))}</span>
              <span>val_loss：${esc(formatMetricValue(historyEntry.val_loss))}</span>
              <span>train_accuracy：${esc(formatMetricValue(historyEntry.train_accuracy, { percent: true }))}</span>
              <span>val_accuracy：${esc(formatMetricValue(historyEntry.val_accuracy, { percent: true }))}</span>
            </div>`
          : '<div class="training-history-empty">未找到该 checkpoint 对应的 epoch 历史记录。</div>'
      }
    </article>
  `;
}

function summarizeResultRow(row) {
  const resultJson = row?.result_json && typeof row.result_json === 'object' ? row.result_json : {};
  const summary = resultJson?.summary && typeof resultJson.summary === 'object' ? resultJson.summary : {};
  const predictions = Array.isArray(resultJson.predictions)
    ? resultJson.predictions
    : Array.isArray(summary.predictions)
      ? summary.predictions
      : [];
  const recognizedTexts = collectRecognizedTexts(predictions, {
    car_number: resultJson.car_number || summary.car_number || row?.label_result || '',
  });
  const labelCounts = predictions.reduce((acc, item) => {
    const label = String(item?.label || '').trim();
    if (!label) return acc;
    acc[label] = (acc[label] || 0) + 1;
    return acc;
  }, {});
  const scores = predictions.map((item) => Number(item?.score)).filter((value) => Number.isFinite(value));
  const avgScore = scores.length ? scores.reduce((sum, value) => sum + value, 0) / scores.length : null;
  const durationMs = Number(row?.duration_ms ?? resultJson?.metrics?.duration_ms ?? summary?.metrics?.duration_ms);
  const taskType = String(resultJson.task_type || summary.task_type || '-');
  const primaryPrediction = predictions[0] || null;
  const ocrText = recognizedTexts[0] || '';
  const ocrConfidenceRaw = Number(resultJson.confidence ?? summary.confidence ?? primaryPrediction?.score);
  const ocrConfidence = Number.isFinite(ocrConfidenceRaw) ? ocrConfidenceRaw : null;
  const ocrEngine = String(resultJson.engine || summary.engine || primaryPrediction?.attributes?.engine || '').trim() || null;
  const ocrBBox = normalizeReviewBBox(resultJson.bbox || summary.bbox || primaryPrediction?.bbox);
  const ocrValidation = resultJson.car_number_validation || summary.car_number_validation || primaryPrediction?.attributes?.validation || null;
  const ocrRule = resultJson.car_number_rule || summary.car_number_rule || null;
  const ocrRisk = taskType !== 'car_number_ocr'
    ? null
    : !ocrText
      ? 'high'
      : ocrValidation && ocrValidation.valid === false
        ? 'high'
      : ocrConfidence == null
        ? 'warning'
        : ocrConfidence < 0.6
          ? 'warning'
          : 'ok';
  const ocrRiskLabel = !ocrRisk
    ? ''
    : ocrRisk === 'high'
      ? '需要复核'
      : ocrRisk === 'warning'
        ? '低置信度'
        : '结果稳定';
  const ocrRiskSummary = !ocrRisk
    ? ''
    : ocrRisk === 'high'
      ? (ocrValidation && ocrValidation.valid === false
        ? `当前文本不符合规则：${ocrValidation.description || '请人工复核。'}`
        : '当前没有稳定 OCR 文本，建议人工框选或重新复核。')
      : ocrRisk === 'warning'
        ? '当前已识别出车号文本，但置信度偏低，建议人工复核后再用于训练或验收。'
        : '当前 OCR 文本和置信度均达到可直接浏览的水平。';
  return {
    row,
    resultJson,
    summary,
    predictions,
    recognizedTexts,
    labelCounts,
    stage: String(resultJson.stage || summary.stage || '-'),
    taskType,
    objectCount: Number(resultJson.object_count ?? summary.object_count ?? predictions.length ?? 0) || 0,
    avgScore,
    durationMs: Number.isFinite(durationMs) ? durationMs : null,
    ocrText,
    ocrConfidence,
    ocrEngine,
    ocrBBox,
    ocrValidation,
    ocrRule,
    ocrRisk,
    ocrRiskLabel,
    ocrRiskSummary,
  };
}

function renderResultConfidenceBars(predictions) {
  const items = (Array.isArray(predictions) ? predictions : [])
    .map((item) => ({
      label: String(item?.label || 'object').trim() || 'object',
      text: extractPredictionText(item),
      score: Number(item?.score),
    }))
    .filter((item) => Number.isFinite(item.score))
    .sort((left, right) => right.score - left.score)
    .slice(0, 5);
  if (!items.length) return '<div class="training-history-empty">当前结果没有可展示的置信度分布。</div>';
  return `
    <div class="result-confidence-list">
      ${items.map((item) => `
        <div class="result-confidence-row">
          <div class="result-confidence-meta">
            <strong>${esc(item.text ? `${item.label}:${item.text}` : item.label)}</strong>
            <span>${esc(formatMetricValue(item.score, { percent: true }))}</span>
          </div>
          <div class="result-confidence-track"><i style="width:${clampNumber(item.score * 100, 4, 100).toFixed(1)}%"></i></div>
        </div>
      `).join('')}
    </div>
  `;
}

function resultLabelDisplayText(taskType, label) {
  const normalized = String(label || '').trim();
  if (!normalized) return '未命名标签';
  if (taskType === 'car_number_ocr' && normalized === 'car_number') return '车号文本';
  if (taskType === 'car_number_ocr' && normalized === 'ocr') return 'OCR 文本';
  return enumText('task_type', normalized) !== normalized ? enumText('task_type', normalized) : normalized;
}

function renderResultLabelCloud(item) {
  const labels = Object.entries(item?.labelCounts || {})
    .sort((left, right) => right[1] - left[1])
    .slice(0, 6);
  if (!labels.length) {
    return {
      headerLabel: '暂无',
      title: '命中标签',
      html: '<div class="training-history-empty">当前结果没有结构化标签命中。</div>',
    };
  }
  if (item?.taskType === 'car_number_ocr') {
    const primaryLabel = resultLabelDisplayText(item.taskType, labels[0][0]);
    const totalCount = labels.reduce((sum, [, count]) => sum + Number(count || 0), 0);
    return {
      headerLabel: '文本输出',
      title: '识别类型',
      html: `
        <div class="result-label-cloud result-label-cloud-ocr">
          <span class="badge">${esc(primaryLabel)}</span>
          <span class="badge subtle">${esc(`命中 ${totalCount} 条`)}</span>
          ${item.ocrValidation ? `<span class="badge ${item.ocrValidation.valid ? 'ok' : 'warn'}">${esc(item.ocrValidation.valid ? '规则通过' : '规则待复核')}</span>` : ''}
        </div>
      `,
    };
  }
  return {
    headerLabel: `${labels.length} 类`,
    title: '命中标签',
    html: `<div class="result-label-cloud">${labels.map(([label, count]) => `<span class="badge">${esc(`${resultLabelDisplayText(item?.taskType, label)} · ${count}`)}</span>`).join('')}</div>`,
  };
}

function resultStageLabel(value) {
  const normalized = String(value || '').trim().toLowerCase();
  if (!normalized || normalized === '-') return '结果';
  if (normalized === 'final') return '最终结果';
  if (normalized === 'expert') return '专家结果';
  if (normalized === 'router') return '路由结果';
  return normalized;
}

function renderResultCardTitle(item) {
  const taskLabel = enumText('task_type', item?.taskType || '-');
  if (item?.taskType === 'car_number_ocr') {
    return item?.ocrText ? `车号结果 · ${item.ocrText}` : '车号结果';
  }
  if (item?.recognizedTexts?.length) {
    return `${taskLabel} · ${item.recognizedTexts[0]}`;
  }
  return `${taskLabel}结果`;
}

function renderResultSummaryStats(item, validationMetrics = {}) {
  if (item?.taskType === 'car_number_ocr') {
    const validityText = item.ocrValidation
      ? (item.ocrValidation.valid ? '规则通过' : '规则待复核')
      : '待确认';
    return `
      <div class="keyvals compact result-summary-keyvals">
        <div><span>车号文本</span><strong>${esc(item.ocrText || '-')}</strong></div>
        <div><span>规则状态</span><strong>${esc(validityText)}</strong></div>
        <div><span>识别置信度</span><strong>${esc(formatMetricValue(item.ocrConfidence, { percent: true }))}</strong></div>
        <div><span>执行耗时</span><strong>${esc(item.durationMs != null ? `${formatMetricValue(item.durationMs)} ms` : '-')}</strong></div>
      </div>
    `;
  }
  return `
    <div class="keyvals compact result-summary-keyvals">
      <div><span>命中结果</span><strong>${esc(formatMetricValue(item.objectCount))}</strong></div>
      <div><span>平均置信度</span><strong>${esc(formatMetricValue(item.avgScore, { percent: true }))}</strong></div>
      <div><span>执行耗时</span><strong>${esc(item.durationMs != null ? `${formatMetricValue(item.durationMs)} ms` : '-')}</strong></div>
      <div><span>模型验证准确率</span><strong>${esc(formatMetricValue(validationMetrics.val_accuracy, { percent: true }))}</strong></div>
    </div>
  `;
}

function renderResultOcrSignal(item) {
  if (item?.taskType !== 'car_number_ocr') return '';
  const riskClass = item.ocrRisk || 'warning';
  return `
    <section class="result-ocr-signal result-risk-${esc(riskClass)}">
      <div class="result-panel-head">
        <div>
          <strong>OCR 风险提示</strong>
          <p>${esc(item.ocrRiskSummary || '当前识别结果建议人工复核。')}</p>
        </div>
        <span class="risk-pill ${esc(riskClass)}">${esc(item.ocrRiskLabel || '待确认')}</span>
      </div>
      <div class="result-ocr-grid">
        <div><span>文本</span><strong>${esc(item.ocrText || '-')}</strong></div>
        <div><span>识别置信度</span><strong>${esc(formatMetricValue(item.ocrConfidence, { percent: true }))}</strong></div>
        <div><span>识别引擎</span><strong>${esc(item.ocrEngine || '-')}</strong></div>
        <div><span>定位框</span><strong>${esc(item.ocrBBox?.join(', ') || '-')}</strong></div>
        <div><span>合法校验</span><strong>${esc(item.ocrValidation ? (item.ocrValidation.valid ? '合法' : '不合法') : '-')}</strong></div>
        <div><span>规则</span><strong>${esc(item.ocrRule?.label || item.ocrValidation?.label || '-')}</strong></div>
      </div>
      ${(item.ocrRule?.description || item.ocrValidation?.description) ? `<div class="hint">${esc(item.ocrRule?.description || item.ocrValidation?.description || '')}</div>` : ''}
    </section>
  `;
}

function renderModelInsightBlock(modelId, readiness) {
  if (!readiness || typeof readiness !== 'object') return '';
  const validationReport = readiness.validation_report || {};
  const metrics = validationReport.metrics || {};
  const history = normalizeTrainingHistory(metrics.history);
  const trainingJob = validationReport.training_job || {};
  return `
    <section class="result-model-insight">
      <div class="result-model-insight-head">
        <div>
          <strong>关联模型表现</strong>
          <p>${esc(validationReport.summary || '当前结果使用的模型验证摘要')}</p>
        </div>
        <div class="quick-review-statuses">
          <span class="badge">${esc(validationReport.decision || '-')}</span>
          ${trainingJob?.job_code ? `<span class="badge">${esc(`训练作业 ${trainingJob.job_code}`)}</span>` : ''}
        </div>
      </div>
      <div class="keyvals compact result-summary-keyvals">
        <div><span>验证得分</span><strong>${esc(formatMetricValue(metrics.val_score, { percent: true }))}</strong></div>
        <div><span>验证准确率</span><strong>${esc(formatMetricValue(metrics.val_accuracy, { percent: true }))}</strong></div>
        <div><span>平均延迟</span><strong>${esc(metrics.latency_ms != null ? `${formatMetricValue(metrics.latency_ms)} ms` : '-')}</strong></div>
        <div><span>显存占用</span><strong>${esc(metrics.gpu_mem_mb != null ? `${formatMetricValue(metrics.gpu_mem_mb)} MB` : '-')}</strong></div>
      </div>
      <details class="inline-details">
        <summary>查看训练曲线与技术指标</summary>
        <div class="details-panel">
          <div class="keyvals compact result-tech-keyvals">
            <div><span>模型编号</span><strong class="mono">${esc(truncateMiddle(modelId, 12, 10))}</strong></div>
            <div><span>验证损失</span><strong>${esc(formatMetricValue(metrics.val_loss))}</strong></div>
            <div><span>历史点数</span><strong>${esc(formatMetricValue(metrics.history_count ?? history.length))}</strong></div>
          </div>
          ${
            history.length
              ? `
                  <div class="grid-two training-history-grid-wrap result-model-history-grid">
                    ${renderTrainingHistoryChart({
                      title: '准确率曲线',
                      description: '复用训练作业回写的 epoch 历史，快速判断该识别结果背后的模型泛化水平。',
                      history,
                      percent: true,
                      lines: [
                        { key: 'train_accuracy', label: 'train_accuracy', className: 'train-line' },
                        { key: 'val_accuracy', label: 'val_accuracy', className: 'validation-line' },
                      ],
                    })}
                    ${renderTrainingHistoryChart({
                      title: '损失曲线',
                      description: '对比 train / val loss，观察训练是否收敛以及是否存在过拟合迹象。',
                      history,
                      lowerIsBetter: true,
                      lines: [
                        { key: 'train_loss', label: 'train_loss', className: 'train-line' },
                        { key: 'val_loss', label: 'val_loss', className: 'validation-line' },
                      ],
                    })}
                  </div>
                `
              : '<div class="training-history-empty">当前模型已记录验证指标，但还没有可展示的 epoch 历史曲线。</div>'
          }
        </div>
      </details>
    </section>
  `;
}

function renderResultValidationConclusion(rows, summaries, modelInsights = {}) {
  const total = Array.isArray(rows) ? rows.length : 0;
  if (!total) return '';
  const ocrRows = summaries.filter((item) => item.taskType === 'car_number_ocr');
  const lowConfidenceCount = ocrRows.filter((item) => !Number.isFinite(item.ocrConfidence) || item.ocrConfidence < 0.8 || item.ocrRisk !== 'stable').length;
  const recognizedTexts = [...new Set(ocrRows.flatMap((item) => item.recognizedTexts))].filter(Boolean);
  const durations = summaries.map((item) => item.durationMs).filter((value) => Number.isFinite(value));
  const avgDuration = durations.length ? Math.round(durations.reduce((sum, value) => sum + value, 0) / durations.length) : null;
  const readinessRows = Object.values(modelInsights || {}).filter(Boolean);
  const firstReadiness = readinessRows[0] || null;
  const validationReport = firstReadiness?.validation_report || {};
  const valMetrics = validationReport.metrics || {};
  const canPromote = Boolean(validationReport.can_approve) && (ocrRows.length ? lowConfidenceCount === 0 : total > 0);
  const recommendation = canPromote
    ? '当前结果已经达到可进入审批/发布复核的水平。'
    : ocrRows.length && lowConfidenceCount > 0
      ? `仍有 ${lowConfidenceCount} 条低置信度 OCR 结果，建议先人工复核再用于审批。`
      : '建议继续补验证样本或复核结果后，再进入审批。';
  return `
    <section class="result-validation-conclusion ${canPromote ? 'ok' : 'warning'}">
      <div class="result-panel-head">
        <div>
          <strong>验证结论</strong>
          <p>${esc(recommendation)}</p>
        </div>
        <span class="risk-pill ${esc(canPromote ? 'ok' : 'warning')}">${esc(canPromote ? '建议推进' : '建议复核')}</span>
      </div>
      <div class="result-validation-grid">
        <div><span>验证结果</span><strong>${esc(total)}</strong></div>
        <div><span>低置信度</span><strong>${esc(lowConfidenceCount)}</strong></div>
        <div><span>识别文本</span><strong>${esc(recognizedTexts.length || 0)}</strong></div>
        <div><span>平均耗时</span><strong>${esc(avgDuration ?? '-')}</strong></div>
        <div><span>验证准确率</span><strong>${esc(formatMetricValue(valMetrics.val_accuracy, { percent: true }))}</strong></div>
        <div><span>门禁结论</span><strong>${esc(validationReport.decision || '-')}</strong></div>
      </div>
      <div class="result-validation-notes">
        <span>${esc(validationReport.summary || '当前模型尚未返回验证门禁摘要。')}</span>
        ${recognizedTexts.length ? `<span>${esc(`示例文本：${recognizedTexts.slice(0, 3).join(' / ')}`)}</span>` : ''}
      </div>
    </section>
  `;
}

function renderResultActionWorkbench(taskId, summaries, exported = null) {
  if (!taskId || !Array.isArray(summaries) || !summaries.length) {
    return renderEmpty('查询到结果后，这里会根据当前状态给出下一步建议。');
  }
  const ocrRows = summaries.filter((item) => item.taskType === 'car_number_ocr');
  const lowConfidenceCount = ocrRows.filter((item) => !Number.isFinite(item.ocrConfidence) || item.ocrConfidence < 0.8 || item.ocrRisk !== 'stable').length;
  const stableTexts = [...new Set(ocrRows.flatMap((item) => item.recognizedTexts || []).filter(Boolean))];
  const recommendation = exported?.asset?.id
    ? '结果样本已经导出到训练中心，可直接继续训练或验证。'
    : lowConfidenceCount > 0
      ? `当前仍有 ${lowConfidenceCount} 条待复核结果，建议先核对文本和截图，再决定是否回灌训练。`
      : stableTexts.length
        ? '当前结果已经较稳定，可以直接导出到训练中心或继续查看任务详情。'
        : '建议先查看任务详情和截图，确认结果是否符合预期。';
  return `
    <div class="result-action-workbench">
      <div class="result-panel-head">
        <div>
          <strong>下一步动作</strong>
          <p>${esc(recommendation)}</p>
        </div>
        <span class="badge">${esc(exported?.asset?.id ? '已回灌' : (lowConfidenceCount > 0 ? '建议复核' : '可继续推进'))}</span>
      </div>
      <div class="result-action-grid">
        <button class="primary" type="button" data-result-action="open-training">${esc(exported?.asset?.id ? '去训练中心' : '整理好并带去训练中心')}</button>
        <button class="ghost" type="button" data-result-action="open-task-detail">打开任务详情</button>
        <button class="ghost" type="button" data-result-action="back-tasks">返回任务中心</button>
      </div>
      <div class="result-next-steps">
        <span class="result-next-step"><strong>1</strong><span>${esc(lowConfidenceCount > 0 ? '先复核低置信度结果和截图，再决定是否把它整理成训练数据。' : '当前结果已经比较稳定，可直接进入训练或验收。')}</span></span>
        <span class="result-next-step"><strong>2</strong><span>${esc(exported?.asset?.id ? '训练中心已经预填当前导出的数据集版本。' : '需要时在下方把当前结果导出成训练或验证数据集版本。')}</span></span>
        <span class="result-next-step"><strong>3</strong><span>${esc('若需追溯执行过程，可随时打开任务详情查看设备、模型和证据截图。')}</span></span>
      </div>
    </div>
  `;
}

function renderResultOverviewCards(rows, summaries) {
  const total = Array.isArray(rows) ? rows.length : 0;
  const totalObjects = summaries.reduce((sum, item) => sum + item.objectCount, 0);
  const durations = summaries.map((item) => item.durationMs).filter((value) => Number.isFinite(value));
  const avgDuration = durations.length ? Math.round(durations.reduce((sum, value) => sum + value, 0) / durations.length) : null;
  const allTexts = [...new Set(summaries.flatMap((item) => item.recognizedTexts))].filter(Boolean);
  const ocrRows = summaries.filter((item) => item.taskType === 'car_number_ocr');
  const lowConfidenceCount = ocrRows.filter((item) => !Number.isFinite(item.ocrConfidence) || item.ocrConfidence < 0.8 || item.ocrRisk !== 'stable').length;
  if (ocrRows.length) {
    return `
      <div class="result-overview-grid">
        <article class="metric-card">
          <h4>车号结果</h4>
          <p class="metric">${esc(total)}</p>
          <span>当前任务回查到的车号结果条数</span>
        </article>
        <article class="metric-card">
          <h4>稳定文本</h4>
          <p class="metric">${esc(allTexts.length)}</p>
          <span>${esc(allTexts.slice(0, 3).join(' / ') || '当前还没有稳定车号文本')}</span>
        </article>
        <article class="metric-card">
          <h4>待复核</h4>
          <p class="metric">${esc(lowConfidenceCount)}</p>
          <span>${esc(lowConfidenceCount ? '仍有低置信度或规则未通过结果' : '当前结果已基本稳定')}</span>
        </article>
        <article class="metric-card">
          <h4>平均执行耗时</h4>
          <p class="metric">${esc(avgDuration ?? '-')}</p>
          <span>${esc(avgDuration != null ? '毫秒' : '当前结果未回写耗时')}</span>
        </article>
      </div>
    `;
  }
  return `
    <div class="result-overview-grid">
      <article class="metric-card">
        <h4>结果条数</h4>
        <p class="metric">${esc(total)}</p>
        <span>当前任务编号下已回查到的结果记录</span>
      </article>
      <article class="metric-card">
        <h4>识别对象</h4>
        <p class="metric">${esc(totalObjects)}</p>
        <span>累计命中的框 / 文本结果数量</span>
      </article>
      <article class="metric-card">
        <h4>平均执行耗时</h4>
        <p class="metric">${esc(avgDuration ?? '-')}</p>
        <span>${esc(avgDuration != null ? '毫秒' : '当前结果未回写耗时')}</span>
      </article>
      <article class="metric-card">
        <h4>识别文本</h4>
        <p class="metric">${esc(allTexts.length)}</p>
        <span>${esc(allTexts.slice(0, 3).join(' / ') || '暂无 OCR 文本')}</span>
      </article>
    </div>
  `;
}

const ENUM_ZH = {
  asset_purpose: {
    inference: '推理',
    training: '训练',
    finetune: '微调',
    validation: '验证',
  },
  asset_type: {
    image: '图片',
    video: '视频',
    archive: '压缩数据集',
    screenshot: '截图',
  },
  sensitivity_level: {
    L1: '低敏',
    L2: '中敏',
    L3: '高敏',
  },
  model_source_type: {
    delivery_candidate: '交付候选',
    finetuned_candidate: '微调候选',
    initial_algorithm: '初始算法',
    pretrained_seed: '预训练种子',
  },
  model_type: {
    expert: '专家模型',
    router: '路由模型',
  },
  training_kind: {
    train: '训练',
    finetune: '微调',
    evaluate: '评估',
  },
  training_status: {
    PENDING: '待调度',
    DISPATCHED: '已派发',
    RUNNING: '执行中',
    SUCCEEDED: '成功',
    FAILED: '失败',
    CANCELLED: '已取消',
  },
  worker_status: {
    ACTIVE: '活跃',
    INACTIVE: '停用',
    UNHEALTHY: '异常',
  },
  task_status: {
    PENDING: '待处理',
    DISPATCHED: '已派发',
    RUNNING: '执行中',
    SUCCEEDED: '成功',
    FAILED: '失败',
    CANCELLED: '已取消',
  },
  model_status: {
    SUBMITTED: '已提交',
    APPROVED: '已审批',
    RELEASED: '已发布',
  },
  pipeline_status: {
    DRAFT: '草稿',
    RELEASED: '已发布',
  },
  device_status: {
    ONLINE: '在线',
    OFFLINE: '离线',
    STALE: '心跳超时',
    ACTIVE: '活跃',
    INACTIVE: '停用',
    UNHEALTHY: '异常',
  },
  task_type: {
    pipeline_orchestrated: '编排推理',
    object_detect: '快速识别',
    car_number_ocr: '车号识别',
    bolt_missing_detect: '螺栓缺失',
    ocr: '文字识别',
    detect: '目标检测',
  },
};

const ROLE_LABELS = {
  platform_admin: '平台管理员',
  platform_operator: '平台运营',
  platform_auditor: '平台审计',
  supplier_engineer: '供应商工程师',
  buyer_operator: '客户操作员',
  buyer_auditor: '客户审计',
  admin: '平台管理员',
  operator: '平台运营',
  auditor: '平台审计',
};

const QUICK_DETECT_PROMPTS = ['car', 'person', 'train', 'bus', '车号'];
const QUICK_DETECT_INTENT_OPTIONS = [
  {
    prompt: 'car',
    taskType: 'object_detect',
    title: '车辆目标',
    description: '通用框选 car / vehicle / bus / truck',
    aliases: ['car', 'vehicle', '车辆', '汽车', '货车', '卡车', '巴士'],
  },
  {
    prompt: 'person',
    taskType: 'object_detect',
    title: '人员目标',
    description: '通用框选 person / people / pedestrian',
    aliases: ['person', 'people', 'human', 'pedestrian', '人', '人员', '行人'],
  },
  {
    prompt: 'train',
    taskType: 'object_detect',
    title: '列车目标',
    description: '通用框选 train / wagon / locomotive',
    aliases: ['train', 'wagon', 'locomotive', '列车', '火车', '车厢'],
  },
  {
    prompt: '车号',
    taskType: 'car_number_ocr',
    title: '车号内容',
    description: '走 OCR，输出车号文本，不只是画框',
    aliases: ['车号', '车厢号', '车皮号', '编号', '号码', '货车号', '货车编号', '车体编号', 'railcar number', 'wagon number', 'car number'],
  },
  {
    prompt: '螺栓缺失',
    taskType: 'bolt_missing_detect',
    title: '螺栓缺失',
    description: '检测紧固件缺失或松动',
    aliases: ['螺栓', '螺母', '紧固件', '缺失', 'bolt', 'fastener', 'screw'],
  },
];

function normalizeQuickPrompt(value) {
  return String(value || '').trim().toLowerCase();
}

function quickIntentOptions(prompt) {
  const normalized = normalizeQuickPrompt(prompt);
  const ranked = QUICK_DETECT_INTENT_OPTIONS
    .map((option) => {
      const aliasMatches = option.aliases.filter((alias) => normalized && normalized.includes(String(alias).toLowerCase()));
      const titleMatch = normalized && normalized.includes(String(option.title).toLowerCase()) ? 1 : 0;
      return {
        ...option,
        matchScore: aliasMatches.length * 2 + titleMatch + (normalized === normalizeQuickPrompt(option.prompt) ? 3 : 0),
      };
    })
    .sort((left, right) => right.matchScore - left.matchScore);
  if (!normalized) return ranked.slice(0, 4);
  return [...ranked.filter((item) => item.matchScore > 0), ...ranked.filter((item) => item.matchScore === 0)].slice(0, 4);
}

function inferQuickDetectTaskType(prompt) {
  return quickIntentOptions(prompt)[0]?.taskType || 'object_detect';
}

const DASHBOARD_ROLE_PRESETS = {
  platform_admin: {
    eyebrow: '平台治理控制面',
    title: '掌握模型审批、发布授权与审计闭环',
    subtitle: '优先处理待验证模型、训练作业与设备授权，确保成果模型只在受控范围内交付。',
    focus: ['待审模型与待验证训练结果', '租户 / 设备授权范围', '审计证据与结果追溯'],
    pathHint: '模型审批 -> 发布授权 -> 审计追踪',
    actions: [
      { label: '进入模型中心', path: 'models', permission: 'model.view' },
      { label: '查看训练作业', path: 'training', permission: 'training.job.view' },
      { label: '核对设备授权', path: 'devices', permission: 'device.read' },
      { label: '查看审计追踪', path: 'audit', permission: 'audit.read' },
    ],
  },
  platform_operator: {
    eyebrow: '平台运营控制面',
    title: '推进资产、任务与模型交付节奏',
    subtitle: '围绕资产准备、任务执行和发布协同，保证客户测试与交付节奏顺畅推进。',
    focus: ['资产准备与任务执行状态', '新模型协同与发布准备', '客户联调与结果回查'],
    pathHint: '资产准备 -> 任务执行 -> 协同发布',
    actions: [
      { label: '进入资产中心', path: 'assets', permission: 'asset.upload' },
      { label: '进入任务执行', path: 'tasks', permission: 'task.create' },
      { label: '查看模型中心', path: 'models', permission: 'model.view' },
      { label: '查看结果中心', path: 'results', permission: 'result.read' },
    ],
  },
  platform_auditor: {
    eyebrow: '平台审计控制面',
    title: '验证发布动作、结果输出与设备运行证据',
    subtitle: '聚焦结果、设备、审计日志，确保每次发布、导出和执行都有完整证据链。',
    focus: ['审计事件完整性', '结果可追溯性', '设备运行与版本状态'],
    pathHint: '结果中心 -> 审计追踪 -> 设备状态',
    actions: [
      { label: '进入结果中心', path: 'results', permission: 'result.read' },
      { label: '查看审计追踪', path: 'audit', permission: 'audit.read' },
      { label: '查看设备状态', path: 'devices', permission: 'device.read' },
    ],
  },
  supplier_engineer: {
    eyebrow: '供应商协作入口',
    title: '提交算法能力并跟踪受控训练与新模型交付',
    subtitle: '在受控环境里提交模型、参与微调协作，并持续跟踪待验证模型和审批反馈。',
    focus: ['模型提交与版本状态', '训练协作与新模型生成', '审批反馈与补充说明'],
    pathHint: '提交模型 -> 训练协作 -> 新模型交付',
    actions: [
      { label: '提交模型包', path: 'models', permission: 'model.view' },
      { label: '查看训练中心', path: 'training', permission: 'training.job.view' },
      { label: '查看流水线', path: 'pipelines', permission: 'model.view' },
    ],
  },
  buyer_operator: {
    eyebrow: '客户业务入口',
    title: '上传资产、创建任务并回查结果',
    subtitle: '把资产准备、任务执行和结果回查收敛成最短路径，确保数据留在受控域内。',
    focus: ['训练 / 验证 / 推理资产准备', '任务创建与执行状态', '结果摘要与截图回查'],
    pathHint: '上传资产 -> 创建任务 -> 查看结果',
    actions: [
      { label: '上传资产', path: 'assets', permission: 'asset.upload' },
      { label: '创建训练作业', path: 'training', permission: 'training.job.create' },
      { label: '创建任务', path: 'tasks', permission: 'task.create' },
      { label: '查看结果', path: 'results', permission: 'result.read' },
      { label: '查看设备状态', path: 'devices', permission: 'device.read' },
    ],
  },
  buyer_auditor: {
    eyebrow: '客户审计入口',
    title: '核对结果、设备与授权状态',
    subtitle: '围绕结果回查、设备状态和租户授权范围，形成客户侧可解释的验收视图。',
    focus: ['结果验收与导出摘要', '设备状态与心跳', '租户授权范围'],
    pathHint: '结果回查 -> 设备核对 -> 授权确认',
    actions: [
      { label: '查看结果', path: 'results', permission: 'result.read' },
      { label: '查看设备', path: 'devices', permission: 'device.read' },
      { label: '查看设置', path: 'settings', permission: 'settings.view' },
    ],
  },
};

function enumText(group, value) {
  const rendered = String(value ?? '-');
  const label = ENUM_ZH[group]?.[rendered];
  return label ? `${rendered}(${label})` : rendered;
}

function primaryRole(user) {
  return String((user?.roles || [])[0] || user?.role || '');
}

function roleLabel(role) {
  const key = String(role || '');
  return ROLE_LABELS[key] || key || '当前角色';
}

function rolePreset(user) {
  const role = primaryRole(user);
  if (DASHBOARD_ROLE_PRESETS[role]) return DASHBOARD_ROLE_PRESETS[role];
  if (role.startsWith('platform_')) return DASHBOARD_ROLE_PRESETS.platform_operator;
  if (role.startsWith('supplier')) return DASHBOARD_ROLE_PRESETS.supplier_engineer;
  if (role.startsWith('buyer_')) return DASHBOARD_ROLE_PRESETS.buyer_operator;
  return {
    eyebrow: `${BRAND_NAME} 控制面`,
    title: '围绕主权、协作、交付和审计完成业务闭环',
    subtitle: '从当前角色的默认路径进入，逐步完成资产、模型、任务和设备侧交付。',
    focus: ['当前角色默认路径', '关键对象状态', '下一步推荐动作'],
    pathHint: '工作台 -> 默认入口 -> 关键结果',
    actions: [
      { label: '进入工作台', path: 'dashboard', permission: 'dashboard.view' },
      { label: '查看设置', path: 'settings', permission: 'settings.view' },
    ],
  };
}

function hasPermission(state, permission) {
  return state.permissions instanceof Set && state.permissions.has(permission);
}

function archiveResourceCount(meta) {
  return Number(meta?.archive_resource_count || 0);
}

function isTaskAsset(row) {
  return ['image', 'video'].includes(String(row?.asset_type || ''));
}

function makeContext(route, ctx) {
  const token = ctx.state.token || '';
  return {
    ...ctx,
    route,
    token,
    get(path) {
      return api(path, { method: 'GET' }, token);
    },
    post(path, payload) {
      return apiPost(path, payload, token);
    },
    postForm(path, formData) {
      return apiForm(path, formData, token);
    },
  };
}

async function fetchAuthorizedBlobUrl(path, token) {
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const resp = await fetch(`/api${path}`, { headers });
  if (!resp.ok) {
    throw new Error(normalizeUiErrorMessage(`HTTP ${resp.status}`, resp.status));
  }
  const blob = await resp.blob();
  return URL.createObjectURL(blob);
}

function pickQuickDetectResult(rows) {
  if (!Array.isArray(rows) || !rows.length) return null;
  return (
    rows.find((row) => row?.result_json?.stage === 'expert' && row?.result_json?.task_type === 'object_detect') ||
    rows.find((row) => row?.result_json?.stage === 'final') ||
    rows.find((row) => row?.screenshot_uri) ||
    rows[0]
  );
}

function page404() {
  return {
    html: `<section class="card"><h2>404</h2><p>页面不存在。</p><button class="primary" data-nav="dashboard">回到工作台</button></section>`,
    mount(root, ctx) {
      root.querySelector('[data-nav]')?.addEventListener('click', () => ctx.navigate('dashboard'));
    },
  };
}

function page403() {
  return {
    html: `<section class="card"><h2>403</h2><p>你没有访问该页面的权限。</p><button class="primary" data-nav="dashboard">回到工作台</button></section>`,
    mount(root, ctx) {
      root.querySelector('[data-nav]')?.addEventListener('click', () => ctx.navigate('dashboard'));
    },
  };
}

function pageLogin(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  return {
    html: `
      <section class="login-shell">
        <div class="login-brand"><span class="brand-mark"></span><span>${BRAND_NAME}</span></div>
        <section class="login-card">
          <h2>进入 ${BRAND_NAME}</h2>
          <p class="login-subtitle">${BRAND_TAGLINE}</p>
          <div class="login-value-grid">
            <span class="login-value-chip">模型主权</span>
            <span class="login-value-chip">数据主权</span>
            <span class="login-value-chip">受控协作</span>
            <span class="login-value-chip">边缘交付</span>
          </div>
          <div class="init-account-box">
            <div class="init-account-title">初始账户（用户名 / 密码 / 角色价值）</div>
            <ul class="init-account-list">
              <li>
                <div class="account-main"><span class="mono">platform_admin</span><span class="mono">platform123</span></div>
                <div class="account-role">平台管理员：审批发布、设备授权、审计追踪</div>
              </li>
              <li>
                <div class="account-main"><span class="mono">supplier_demo</span><span class="mono">supplier123</span></div>
                <div class="account-role">供应商工程师：提交模型、参与受控训练、跟踪候选交付</div>
              </li>
              <li>
                <div class="account-main"><span class="mono">buyer_operator</span><span class="mono">buyer123</span></div>
                <div class="account-role">客户操作员：上传资产、创建任务、查看结果</div>
              </li>
            </ul>
          </div>
          <label>用户名</label>
          <input id="username" value="platform_admin" placeholder="请输入用户名" />
          <label>密码</label>
          <input id="password" type="password" value="platform123" />
          <button id="loginBtn" class="primary">继续</button>
          <div id="loginMsg" class="hint danger"></div>
        </section>
        <div class="login-footnote">服务条款和隐私政策</div>
      </section>
    `,
    mount(root) {
      const usernameEl = root.querySelector('#username');
      const passwordEl = root.querySelector('#password');
      const loginBtn = root.querySelector('#loginBtn');
      const loginMsg = root.querySelector('#loginMsg');

      async function submit() {
        const username = usernameEl?.value.trim();
        const password = passwordEl?.value || '';
        if (!username || !password) {
          loginMsg.textContent = '请输入用户名和密码';
          return;
        }
        loginBtn.disabled = true;
        loginMsg.textContent = '';
        try {
          await ctx.login(username, password);
        } catch (error) {
          loginMsg.textContent = error?.message || '登录失败';
        } finally {
          loginBtn.disabled = false;
        }
      }

      loginBtn?.addEventListener('click', submit);
      passwordEl?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') submit();
      });
      usernameEl?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') submit();
      });
    },
  };
}

function pageDashboard(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const userRole = primaryRole(ctx.state.user);
  const preset = rolePreset(ctx.state.user);
  const availableActions = preset.actions.filter((item) => !item.permission || hasPermission(ctx.state, item.permission));
  const roleBadges = [...new Set((ctx.state.user?.roles || []).map((item) => roleLabel(item)).filter(Boolean))];
  return {
    html: `
      <section class="card hero-panel">
        <div class="hero-copy">
          <span class="hero-eyebrow">${esc(preset.eyebrow)}</span>
          <h2>${esc(preset.title)}</h2>
          <p>${esc(preset.subtitle)}</p>
          <div class="role-chip-row">
            <span class="role-chip">${esc(roleLabel(userRole))}</span>
            ${roleBadges.slice(1).map((item) => `<span class="role-chip muted">${esc(item)}</span>`).join('')}
          </div>
        </div>
        <div class="hero-side">
          <div class="hero-stat">
            <span>默认路径</span>
            <strong>${esc(preset.pathHint)}</strong>
          </div>
          <div class="hero-stat">
            <span>当前租户</span>
            <strong>${esc(ctx.state.user?.tenant_code || ctx.state.user?.tenant_id || '-')}</strong>
          </div>
        </div>
      </section>
      <section class="grid-two dashboard-brief-grid">
        <div class="card">
          <h3>推荐动作</h3>
          <div class="quick-action-grid">
            ${availableActions.length
              ? availableActions.map((item) => `<button class="primary quick-action-btn" data-dashboard-nav="${esc(item.path)}">${esc(item.label)}</button>`).join('')
              : '<div class="state empty">当前角色暂无推荐动作</div>'}
          </div>
        </div>
        <div class="card">
          <h3>当前角色重点</h3>
          <ul class="focus-list">
            ${preset.focus.map((item) => `<li>${esc(item)}</li>`).join('')}
          </ul>
        </div>
      </section>
      <section class="card">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-dashboard-panel-tab="overview">工作台总览</button>
          <button class="ghost" type="button" data-dashboard-panel-tab="assets">最近资产</button>
          <button class="ghost" type="button" data-dashboard-panel-tab="models">最近模型</button>
          <button class="ghost" type="button" data-dashboard-panel-tab="tasks">最近任务</button>
        </div>
        <div id="dashboardPanelMeta" class="hint">默认先看工作台总览；最近资产、模型、任务按需进入，不再一次性全铺开。</div>
      </section>
      <section class="card" data-dashboard-panel="overview">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-dashboard-overview-tab="lanes">主线指标</button>
          <button class="ghost" type="button" data-dashboard-overview-tab="real-data">真实数据盘</button>
        </div>
        <div id="dashboardOverviewMeta" class="hint">默认先看四条主线指标；需要确认真实资产和车号数据基础盘时，再进入真实数据盘。</div>
      </section>
      <section class="lane-grid" id="laneGrid" data-dashboard-panel="overview" data-dashboard-overview-panel="lanes">${renderLoading('加载主线指标...')}</section>
      <section class="lane-grid" id="realDataGrid" data-dashboard-panel="overview" data-dashboard-overview-panel="real-data" hidden>${renderLoading('加载真实数据来源...')}</section>
      <section class="card" data-dashboard-panel="assets" hidden>
        <h3>最近资产</h3>
        <div id="recentAssets">${renderLoading()}</div>
      </section>
      <section class="card" data-dashboard-panel="models" hidden>
        <h3>最近模型</h3>
        <div id="recentModels">${renderLoading()}</div>
      </section>
      <section class="card" data-dashboard-panel="tasks" hidden>
        <h3>最近任务</h3>
        <div id="recentTasks">${renderLoading()}</div>
      </section>
    `,
    async mount(root) {
      root.querySelectorAll('[data-dashboard-nav]').forEach((btn) => {
        btn.addEventListener('click', () => ctx.navigate(btn.getAttribute('data-dashboard-nav')));
      });
      const dashboardPanelMeta = root.querySelector('#dashboardPanelMeta');
      const dashboardPanelTabs = Array.from(root.querySelectorAll('[data-dashboard-panel-tab]'));
      const dashboardPanels = Array.from(root.querySelectorAll('[data-dashboard-panel]'));
      const dashboardOverviewMeta = root.querySelector('#dashboardOverviewMeta');
      const dashboardOverviewTabs = Array.from(root.querySelectorAll('[data-dashboard-overview-tab]'));
      const dashboardOverviewPanels = Array.from(root.querySelectorAll('[data-dashboard-overview-panel]'));
      const laneGrid = root.querySelector('#laneGrid');
      const realDataGrid = root.querySelector('#realDataGrid');
      const recentAssets = root.querySelector('#recentAssets');
      const recentModels = root.querySelector('#recentModels');
      const recentTasks = root.querySelector('#recentTasks');
      let activeDashboardPanel = 'overview';
      let activeDashboardOverviewPanel = 'lanes';

      function setDashboardOverviewPanel(panel) {
        activeDashboardOverviewPanel = ['lanes', 'real-data'].includes(panel) ? panel : 'lanes';
        dashboardOverviewPanels.forEach((section) => {
          section.hidden = section.getAttribute('data-dashboard-overview-panel') !== activeDashboardOverviewPanel;
        });
        dashboardOverviewTabs.forEach((btn) => {
          const active = btn.getAttribute('data-dashboard-overview-tab') === activeDashboardOverviewPanel;
          btn.classList.toggle('primary', active);
          btn.classList.toggle('ghost', !active);
          btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (dashboardOverviewMeta) {
          dashboardOverviewMeta.textContent = activeDashboardOverviewPanel === 'lanes'
            ? '先看四条主线指标，确认资产、模型、执行和设备运行面。'
            : '需要确认真实演示资产、车号样本和 OCR 训练包时，再进入真实数据盘。';
        }
      }

      function setDashboardPanel(panel) {
        activeDashboardPanel = panel;
        dashboardPanelTabs.forEach((btn) => {
          const active = btn.getAttribute('data-dashboard-panel-tab') === panel;
          btn.classList.toggle('primary', active);
          btn.classList.toggle('ghost', !active);
        });
        dashboardPanels.forEach((section) => {
          if (section.hasAttribute('data-dashboard-overview-panel')) return;
          section.hidden = section.getAttribute('data-dashboard-panel') !== panel;
        });
        if (panel === 'overview') {
          setDashboardOverviewPanel(activeDashboardOverviewPanel);
        } else {
          dashboardOverviewPanels.forEach((section) => {
            section.hidden = true;
          });
        }
        if (dashboardPanelMeta) {
          dashboardPanelMeta.textContent = ({
            overview: '先看当前角色重点、主线指标和真实数据基础盘。',
            assets: '聚焦最近准备好的真实资产，适合继续去任务、训练或验证。',
            models: '查看最近模型状态，决定是继续验证、审批还是发布。',
            tasks: '查看最近任务执行情况，快速进入结果或任务详情。',
          })[panel] || '按当前工作区继续查看。';
        }
      }

      dashboardPanelTabs.forEach((btn) => {
        btn.addEventListener('click', () => {
          setDashboardPanel(btn.getAttribute('data-dashboard-panel-tab') || 'overview');
        });
      });
      dashboardOverviewTabs.forEach((btn) => {
        btn.addEventListener('click', () => {
          setDashboardOverviewPanel(btn.getAttribute('data-dashboard-overview-tab') || 'lanes');
        });
      });
      try {
        const data = await ctx.get('/dashboard/summary');
        const lanes = data?.lanes || {};
        const hygiene = data?.hygiene || {};
        const realData = data?.real_data || {};
        laneGrid.innerHTML = `
          <article class="lane-card">
            <h4>主线1 资产输入</h4>
            <p class="metric">${lanes.line1_assets?.total_assets ?? 0}</p>
            <p class="muted">可用于训练 / 验证 / 推理的真实资产总量${Number(hygiene.hidden_assets || 0) > 0 ? ` · 已隐藏 ${Number(hygiene.hidden_assets)} 个测试/截图资产` : ''}</p>
          </article>
          <article class="lane-card">
            <h4>主线2 模型交付与微调</h4>
            <p class="metric">${lanes.line2_models_training?.models_submitted ?? 0} / ${lanes.line2_models_training?.models_released ?? 0}</p>
            <p class="muted">待审模型 / 已发布模型${Number(hygiene.hidden_models || 0) > 0 ? ` · 已隐藏 ${Number(hygiene.hidden_models)} 个测试候选` : ''}</p>
          </article>
          <article class="lane-card">
            <h4>主线3 验证与执行</h4>
            <p class="metric">${lanes.line3_execution?.tasks_succeeded ?? 0}</p>
            <p class="muted">成功任务数（累计）${Number(hygiene.hidden_tasks || 0) > 0 ? ` · 已隐藏 ${Number(hygiene.hidden_tasks)} 条测试任务` : ''}</p>
          </article>
          <article class="lane-card">
            <h4>主线4 授权设备运行</h4>
            <p class="metric">${lanes.line4_governance_delivery?.devices_online ?? 0} / ${lanes.line4_governance_delivery?.devices_total ?? 0}</p>
            <p class="muted">在线设备 / 设备总数</p>
          </article>
        `;
        realDataGrid.innerHTML = `
          <article class="lane-card">
            <h4>真实演示资产</h4>
            <p class="metric">${realData.demo_assets ?? 0}</p>
            <p class="muted">来自 demo_data / 演示导入的真实图片、视频和本地训练包</p>
          </article>
          <article class="lane-card">
            <h4>本地车号样本</h4>
            <p class="metric">${realData.local_train_images ?? 0}</p>
            <p class="muted">demo_data/train 内已整理好的现有车号照片</p>
          </article>
          <article class="lane-card">
            <h4>待复核文本行</h4>
            <p class="metric">${realData.labeling_rows ?? 0}</p>
            <p class="muted">车号 OCR 文本标注清单总行数</p>
          </article>
          <article class="lane-card">
            <h4>OCR 文本训练包</h4>
            <p class="metric">${realData.text_train_rows ?? 0} / ${realData.text_validation_rows ?? 0}</p>
            <p class="muted">当前真值/建议值回灌后的 train / validation 行数</p>
          </article>
        `;

        const assets = data?.recent?.assets || [];
        const models = data?.recent?.models || [];
        const tasks = data?.recent?.tasks || [];
        recentAssets.innerHTML = assets.length
          ? `
            <div class="selection-grid">
              ${assets.slice(0, 6).map((row) => `
                <article class="selection-card">
                  <div class="selection-card-head selection-card-head--stack">
                    <div class="selection-card-title">
                      <strong>${esc(row.file_name)}</strong>
                      <span class="selection-card-subtitle">${esc(enumText('asset_purpose', row.asset_purpose || 'inference'))}</span>
                    </div>
                    <span class="badge">${esc(enumText('sensitivity_level', row.sensitivity_level || 'L2'))}</span>
                  </div>
                  <div class="selection-card-meta selection-card-meta--compact">
                    <span>资源类型</span><strong>${esc(row.asset_type || '-')}</strong>
                    <span>创建时间</span><strong>${formatDateTime(row.created_at)}</strong>
                    <span>资源数</span><strong>${esc(row.resource_count ?? '-')}</strong>
                    <span>下一步</span><strong>用于任务 / 训练 / 验证</strong>
                  </div>
                  <details class="inline-details">
                    <summary>技术详情</summary>
                    <div class="details-panel">
                      <div class="selection-card-meta selection-card-meta--compact">
                        <span>资产编号</span><strong class="mono">${esc(truncateMiddle(row.id || '-', 10, 8))}</strong>
                        <span>数据集标签</span><strong>${esc(row.dataset_label || '-')}</strong>
                        <span>目标模型</span><strong>${esc(row.intended_model_code || '-')}</strong>
                      </div>
                    </div>
                  </details>
                </article>
              `).join('')}
            </div>
          `
          : renderEmpty('暂无资产');
        recentModels.innerHTML = models.length
          ? `
            <div class="selection-grid">
              ${models.slice(0, 6).map((row) => `
                <article class="selection-card">
                  <div class="selection-card-head selection-card-head--stack">
                    <div class="selection-card-title">
                      <strong>${esc(row.model_code || '-')}</strong>
                      <span class="selection-card-subtitle">${esc(row.version || '-')}</span>
                    </div>
                    <span class="badge">${esc(enumText('model_status', row.status || '-'))}</span>
                  </div>
                  <div class="selection-card-meta selection-card-meta--compact">
                    <span>任务类型</span><strong>${esc(enumText('task_type', row.task_type || '-'))}</strong>
                    <span>来源</span><strong>${esc(enumText('model_type', row.model_type || '-') || row.model_type || '-')}</strong>
                    <span>创建时间</span><strong>${formatDateTime(row.created_at)}</strong>
                    <span>下一步</span><strong>${row.status === 'RELEASED' ? '可验证 / 可执行' : '审批 / 发布'}</strong>
                  </div>
                  <details class="inline-details">
                    <summary>技术详情</summary>
                    <div class="details-panel">
                      <div class="selection-card-meta selection-card-meta--compact">
                        <span>模型编号</span><strong class="mono">${esc(truncateMiddle(row.id || '-', 10, 8))}</strong>
                        <span>状态</span><strong>${esc(row.status || '-')}</strong>
                        <span>编码</span><strong>${esc(row.model_code || '-')}</strong>
                      </div>
                    </div>
                  </details>
                </article>
              `).join('')}
            </div>
          `
          : renderEmpty('暂无模型');
        recentTasks.innerHTML = tasks.length
          ? `
            <div class="selection-grid">
              ${tasks.slice(0, 6).map((row) => `
                <article class="selection-card">
                  <div class="selection-card-head selection-card-head--stack">
                    <div class="selection-card-title">
                      <strong>${esc(enumText('task_type', row.task_type || '-'))}</strong>
                      <span class="selection-card-subtitle">${formatDateTime(row.created_at)}</span>
                    </div>
                    <span class="badge">${esc(enumText('task_status', row.status || '-'))}</span>
                  </div>
                  <div class="selection-card-meta selection-card-meta--compact">
                    <span>执行方式</span><strong>${row.model_id ? '按显式模型' : row.pipeline_id ? '按流水线' : '按调度器'}</strong>
                    <span>设备</span><strong>${esc(row.device_code || '-')}</strong>
                    <span>资产</span><strong class="mono">${esc(truncateMiddle(row.asset_id || '-', 10, 8))}</strong>
                    <span>下一步</span><strong>${row.status === 'SUCCEEDED' ? '查看结果' : '继续等待 / 查看详情'}</strong>
                  </div>
                  <details class="inline-details">
                    <summary>技术详情</summary>
                    <div class="details-panel">
                      <div class="selection-card-meta selection-card-meta--compact">
                        <span>任务编号</span><strong class="mono">${esc(truncateMiddle(row.id || '-', 10, 8))}</strong>
                        <span>流水线编号</span><strong class="mono">${esc(truncateMiddle(row.pipeline_id || '-', 10, 8))}</strong>
                        <span>模型编号</span><strong class="mono">${esc(truncateMiddle(row.model_id || '-', 10, 8))}</strong>
                      </div>
                    </div>
                  </details>
                </article>
              `).join('')}
            </div>
          `
          : renderEmpty('暂无任务');
      } catch (error) {
        laneGrid.innerHTML = renderError(error.message);
        realDataGrid.innerHTML = renderError(error.message);
        recentAssets.innerHTML = renderError(error.message);
        recentModels.innerHTML = renderError(error.message);
        recentTasks.innerHTML = renderError(error.message);
      }
      setDashboardPanel(activeDashboardPanel);
    },
  };
}

function pageGuide(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const flowSteps = [
    '真实资产上传',
    '在线任务验证',
    '结果复核',
    '数据集回灌',
    '训练作业',
    '待验证模型审批',
    '发布到设备',
  ];
  const quickLinks = [
    { path: 'assets', label: '上传真实资产', hint: '先准备训练 / 验证 / 推理用的图片、视频或数据集包。' },
    { path: 'tasks', label: '创建在线验证任务', hint: '用现有模型先跑一轮真实样本验证。' },
    { path: 'training/car-number-labeling', label: '车号文本复核', hint: '逐条确认 OCR 真值，再回灌训练。' },
    { path: 'training', label: '创建训练作业', hint: '让本机或指定训练机器执行训练 / 微调。' },
    { path: 'models', label: '审批与发布模型', hint: '在审批工作台和发布工作台完成晋级。' },
    { path: 'results', label: '把结果变成训练数据', hint: '把复核后的结果整理成训练 / 验证数据集版本。' },
  ];
  const roleCards = [
    {
      title: '客户操作员',
      summary: '负责上传现场资产、创建任务、查看结果、复核 OCR 文本。',
      steps: ['先上传真实资产', '再创建任务验证现有模型', '结果确认后再进入训练或验收'],
    },
    {
      title: '供应商工程师',
      summary: '负责组织训练数据、创建训练作业、产出待验证模型并提交审批。',
      steps: ['先确认训练机器在线', '创建训练作业', '训练成功后去模型中心走审批验证'],
    },
    {
      title: '平台管理员',
      summary: '负责挑样本验证新模型、审批通过、配置发布范围与交付方式。',
      steps: ['先看审批工作台', '再看发布工作台', '最后用已发布模型做任务回归验证'],
    },
  ];
  const featureCards = [
    ['工作台', '只用于看全局状态与推荐动作，不建议在这里做复杂编辑。'],
    ['资产', '上传和筛选图片 / 视频 / ZIP 数据集，建议按 training / validation / inference 分用途管理。'],
    ['训练', '创建训练作业、查看训练机器和待验证模型；车号 OCR 建议先走“车号文本复核”。'],
    ['模型', '统一查看模型状态、审批工作台、发布工作台和验证门禁。'],
    ['任务', '创建在线推理任务；明确目标后优先直接选模型，不明确时再做预检。'],
    ['结果', '查看文本、框、截图和验证结论；确认后可回灌训练。'],
    ['设备 / 审计', '核对设备授权、在线状态与关键操作证据。'],
  ];
  const screenCards = [
    {
      path: 'assets',
      title: '资产页',
      eyebrow: '真实输入',
      bullets: ['上传图片 / 视频 / ZIP', '按用途管理 training / validation / inference', '上传后可直达任务或训练'],
    },
    {
      path: 'tasks',
      title: '任务页',
      eyebrow: '在线验证',
      bullets: ['明确目标后直接选模型', '等待任务完成并打开结果页', '多图场景支持批量快速识别'],
    },
    {
      path: 'training',
      title: '训练页',
      eyebrow: '训练闭环',
      bullets: ['查看训练机器是否在线', '创建训练作业', '训练成功后直达新模型验证'],
    },
    {
      path: 'models',
      title: '模型页',
      eyebrow: '审批发布',
      bullets: ['审批工作台挑样本验证', '发布工作台配置设备 / 买家', '统一看验证门禁与状态'],
    },
    {
      path: 'results',
      title: '结果页',
      eyebrow: '复核与训练数据',
      bullets: ['查看文本 / 框 / 截图', '确认验证结论', '导出训练 / 验证数据集版本'],
    },
  ];
  const faqCards = [
    ['为什么不建议一上来就训练？', '先验证现有模型和在线链路是否正常，能显著减少后面把问题误判成训练问题的概率。'],
    ['在线验证该用什么输入？', '优先用单图或短视频资产。训练 ZIP / 数据集包不适合直接拿来做在线任务输入。'],
    ['OCR 结果出来了就能直接相信吗？', '不能。应结合合法规则、置信度和人工复核一起判断，尤其是低清车号图。'],
    ['审批和发布有什么区别？', '审批是在确认模型能力是否达标；发布是在确认给谁、给哪些设备、以什么方式交付。'],
  ];
  const scenarioFlows = [
    {
      title: '客户快速验证',
      path: ['上传资产', '创建任务', '查看结果'],
      hint: '适合先验证平台和现有模型是否跑得通。',
    },
    {
      title: '车号 OCR 提精度',
      path: ['车号文本复核', '创建训练', '审批模型', '发布上线'],
      hint: '适合把 OCR 结果补成真值，再推进微调。',
    },
    {
      title: '平台审批发布',
      path: ['挑样本验证', '审批通过', '发布工作台', '设备回归验证'],
      hint: '适合控制候选模型到正式上线的过程。',
    },
  ];
  return {
    html: `
      <section class="card guide-hero">
        <div>
          <span class="hero-eyebrow">商业交付说明</span>
          <h2>平台接入与使用指南</h2>
          <p>这份指南面向真实业务交付，重点回答“谁先做什么、在哪个页面做、做完怎么判断是否成功”。它不是源码说明，而是平台上手、验证、训练、审批和发布的统一操作口径。</p>
        </div>
        <div class="row-actions">
          <button class="primary" type="button" data-guide-nav="dashboard">返回工作台</button>
          <button class="ghost" type="button" data-guide-nav="assets">先上传真实资产</button>
          <button class="ghost" type="button" data-guide-nav="tasks">先验证现有模型</button>
        </div>
      </section>

      <section class="card">
        <h3>一图看懂平台闭环</h3>
        <div class="guide-flow">
          ${flowSteps.map((step, index) => `
            <div class="guide-flow-step">
              <strong>${esc(step)}</strong>
              ${index < flowSteps.length - 1 ? '<span class="guide-flow-arrow">→</span>' : ''}
            </div>
          `).join('')}
        </div>
        <div class="hint">先用真实资产验证现有模型，再把结果沉淀成训练数据，训练出新模型后进入审批与发布。</div>
      </section>

      <section class="guide-grid">
        <article class="card">
          <h3>平台接入五步法</h3>
          <div class="guide-step-list">
            <div><strong>1. 确认账号、租户、角色</strong><span>先确认自己属于客户、供应商还是平台侧，并核对租户和权限是否正确。</span></div>
            <div><strong>2. 准备真实资产</strong><span>按 training / validation / inference 分用途整理样本，避免测试文件混入正式资产。</span></div>
            <div><strong>3. 明确目标与验收标准</strong><span>先定义任务是检测还是 OCR，以及什么输出才算达标。</span></div>
            <div><strong>4. 先跑小闭环</strong><span>上传 1 张真实图片，创建 1 条任务，确认结果页输出正常后再进入训练和审批。</span></div>
            <div><strong>5. 再做训练与发布</strong><span>结果真值确认后整理成数据集，创建训练作业，验证新模型并进入审批发布。</span></div>
          </div>
        </article>

        <article class="card">
          <h3>推荐最短路径</h3>
          <div class="compact-list">
            <li><strong>客户快速验证</strong><span>资产 -> 任务 -> 结果</span></li>
            <li><strong>车号 OCR 真值闭环</strong><span>车号文本复核 -> 训练 -> 模型审批 -> 发布</span></li>
            <li><strong>平台审批发布</strong><span>审批工作台 -> 发布工作台 -> 已发布模型验证</span></li>
          </div>
          <div class="hint">建议不要一上来就训练。先确认现有模型和在线执行链路是通的，再决定是否进入微调。</div>
        </article>
      </section>

      <section class="card">
        <h3>角色上手路径</h3>
        <div class="guide-role-grid">
          ${roleCards.map((card) => `
            <article class="selection-card guide-role-card">
              <div class="selection-card-head"><strong>${esc(card.title)}</strong></div>
              <div class="selection-summary">
                <span>${esc(card.summary)}</span>
                ${card.steps.map((step) => `<span>${esc(step)}</span>`).join('')}
              </div>
            </article>
          `).join('')}
        </div>
      </section>

      <section class="card">
        <h3>按场景直接走</h3>
        <div class="guide-scenario-grid">
          ${scenarioFlows.map((item) => `
            <article class="selection-card">
              <div class="selection-card-head"><strong>${esc(item.title)}</strong></div>
              <div class="guide-mini-flow">
                ${item.path.map((step, index) => `
                  <span class="badge">${esc(step)}</span>${index < item.path.length - 1 ? '<span class="guide-mini-arrow">→</span>' : ''}
                `).join('')}
              </div>
              <div class="selection-summary"><span>${esc(item.hint)}</span></div>
            </article>
          `).join('')}
        </div>
      </section>

      <section class="card">
        <h3>功能地图</h3>
        <div class="guide-feature-grid">
          ${featureCards.map(([title, summary]) => `
            <article class="selection-card">
              <div class="selection-card-head"><strong>${esc(title)}</strong></div>
              <div class="selection-summary"><span>${esc(summary)}</span></div>
            </article>
          `).join('')}
        </div>
      </section>

      <section class="card">
        <h3>关键页面导览</h3>
        <div class="guide-screen-grid">
          ${screenCards.map((item) => `
            <button class="selection-card guide-screen-card" type="button" data-guide-nav="${esc(item.path)}">
              <div class="guide-screen-preview">
                <span class="guide-screen-preview-bar"></span>
                <span class="guide-screen-preview-bar short"></span>
                <span class="guide-screen-preview-panel"></span>
                <span class="guide-screen-preview-panel small"></span>
              </div>
              <div class="selection-card-head">
                <div class="selection-card-title">
                  <span class="selection-card-subtitle">${esc(item.eyebrow)}</span>
                  <strong>${esc(item.title)}</strong>
                </div>
              </div>
              <div class="selection-summary">
                ${item.bullets.map((line) => `<span>${esc(line)}</span>`).join('')}
              </div>
            </button>
          `).join('')}
        </div>
      </section>

      <section class="card">
        <h3>直接开始</h3>
        <div class="guide-link-grid">
          ${quickLinks.map((item) => `
            <button class="selection-card guide-link-card" type="button" data-guide-nav="${esc(item.path)}">
              <div class="selection-card-head"><strong>${esc(item.label)}</strong></div>
              <div class="selection-summary"><span>${esc(item.hint)}</span></div>
            </button>
          `).join('')}
        </div>
      </section>

      <section class="card">
        <h3>成熟交付建议</h3>
        <div class="selection-summary">
          <strong>统一操作原则</strong>
          <span>在线验证使用单图 / 视频资产；训练使用数据集包；两类输入不要混用。</span>
          <span>结果出来后不要默认可信，尤其 OCR 要结合合法规则、置信度和人工复核一起判断。</span>
          <span>审批和发布是两个阶段：先确认模型能力，再配置发布对象、设备范围和交付方式。</span>
          <span>仓库内正式说明文档见 <span class="mono">docs/platform_access_and_feature_guide.md</span>。</span>
        </div>
      </section>

      <section class="card">
        <h3>常见问题</h3>
        <div class="guide-faq-grid">
          ${faqCards.map(([q, a]) => `
            <article class="selection-card guide-faq-card">
              <div class="selection-card-head"><strong>${esc(q)}</strong></div>
              <div class="selection-summary"><span>${esc(a)}</span></div>
            </article>
          `).join('')}
        </div>
      </section>
    `,
    async mount(root) {
      root.querySelectorAll('[data-guide-nav]').forEach((btn) => {
        btn.addEventListener('click', () => ctx.navigate(btn.getAttribute('data-guide-nav')));
      });
    },
  };
}

function pageAssets(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const role = primaryRole(ctx.state.user);
  const heroSummary = role.startsWith('buyer_')
    ? '把现场图片、视频和 ZIP 数据集包收成受控资产，后续任务、训练、验证都直接复用同一个资产编号。'
    : role.startsWith('platform_')
      ? '统一管理客户资产、用途标记和敏感等级，保证训练、验证和审批都基于同一份可信输入。'
      : '查看资产输入、用途标记和数据集包摘要。';
  return {
    html: `
      ${renderPageHero({
        eyebrow: '真实资产输入',
        title: '资产中心',
        summary: heroSummary,
        highlights: ['单图 / 视频用于任务', 'ZIP 数据集包用于训练', '资产编号全流程复用'],
        actions: [
          { path: 'tasks', label: '去任务中心', primary: true },
          { path: 'training', label: '去训练中心' },
        ],
      })}
      <section class="card">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-asset-panel-tab="overview">资产总览</button>
          <button class="ghost" type="button" data-asset-panel-tab="upload">上传资产</button>
          <button class="ghost" type="button" data-asset-panel-tab="guide">使用建议</button>
        </div>
        <div id="assetPanelMeta" class="hint">默认先看资产总览；上传和使用说明按工作区展开。</div>
      </section>
      <section class="grid-two" data-asset-panel="upload" hidden>
        <form id="assetUploadForm" class="card form-grid">
          <h3>上传资产</h3>
          <label>文件</label>
          <input type="file" name="file" accept=".jpg,.jpeg,.png,.bmp,.mp4,.avi,.mov,.zip" required />
          <div class="hint">训练/验证/微调用途支持上传包含多层文件夹的 ZIP 数据集包；ZIP 内可包含多张图片或多段视频。</div>
          <label>用途</label>
          <select name="asset_purpose">
            <option value="inference">${enumText('asset_purpose', 'inference')}</option>
            <option value="training">${enumText('asset_purpose', 'training')}</option>
            <option value="finetune">${enumText('asset_purpose', 'finetune')}</option>
            <option value="validation">${enumText('asset_purpose', 'validation')}</option>
          </select>
          <label>敏感等级</label>
          <select name="sensitivity_level">
            <option value="L2">${enumText('sensitivity_level', 'L2')}</option>
            <option value="L1">${enumText('sensitivity_level', 'L1')}</option>
            <option value="L3">${enumText('sensitivity_level', 'L3')}</option>
          </select>
          <label>数据集标签</label>
          <input name="dataset_label" placeholder="demo-dataset-001" />
          <label>业务场景</label>
          <input name="use_case" placeholder="railway-defect-inspection" />
          <label>希望适配的模型</label>
          <input name="intended_model_code" placeholder="例如 car_number_ocr" />
          <button class="primary" type="submit">上传资产</button>
          <div id="assetUploadMsg" class="hint"></div>
        </form>
        <section class="card">
          <h3>上传结果</h3>
          <div id="assetUploadResult">${renderEmpty('上传后会生成资产编号、资源摘要和下一步入口')}</div>
        </section>
      </section>
      <section class="card" data-asset-panel="guide" hidden>
        <h3>使用建议</h3>
        <ul class="focus-list">
          <li>训练 / 微调 / 验证优先使用 ZIP 数据集包，便于一次性提交多层文件夹和多资源样本。</li>
          <li>上传成功后会固定生成资产编号，后续训练作业、验证流程和任务执行都直接引用该记录。</li>
          <li>推理任务优先使用单图或单视频资产；训练链路可组合 0-n 个单文件资产或多个 ZIP 数据集包。</li>
        </ul>
      </section>
      <section class="card" data-asset-panel="overview">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-asset-overview-tab="summary">使用概览</button>
          <button class="ghost" type="button" data-asset-overview-tab="list">资产列表</button>
        </div>
        <div id="assetOverviewPanelMeta" class="hint">默认先看这批资产适合怎么用；需要复制资产编号或挑选具体资产时再进入资产列表。</div>
      </section>
      <section class="card" data-asset-panel="overview" data-asset-overview-panel="summary" hidden>
        <div id="assetOverviewWorkbenchWrap">${renderLoading('加载资产概览...')}</div>
      </section>
      <section class="card" data-asset-panel="overview" data-asset-overview-panel="list" hidden>
        <form id="assetFilterForm" class="inline-form">
          <input name="q" placeholder="搜索文件名 / 业务场景 / 希望适配的模型" />
          <select name="asset_purpose">
            <option value="">全部用途</option>
            <option value="inference">${enumText('asset_purpose', 'inference')}</option>
            <option value="training">${enumText('asset_purpose', 'training')}</option>
            <option value="finetune">${enumText('asset_purpose', 'finetune')}</option>
            <option value="validation">${enumText('asset_purpose', 'validation')}</option>
          </select>
          <label class="checkbox-row"><input id="assetShowHistoryExports" type="checkbox" /> 显示 OCR 导出历史</label>
          <div id="assetListMeta" class="hint"></div>
          <button class="ghost" type="submit">刷新列表</button>
        </form>
        <div id="assetsTableWrap">${renderLoading('加载资产列表...')}</div>
      </section>
    `,
    async mount(root) {
      bindPageNavButtons(root, ctx);
      const assetPanelMeta = root.querySelector('#assetPanelMeta');
      const assetPanelTabs = [...root.querySelectorAll('[data-asset-panel-tab]')];
      const assetPanels = [...root.querySelectorAll('[data-asset-panel]')];
      const assetOverviewPanelMeta = root.querySelector('#assetOverviewPanelMeta');
      const assetOverviewTabs = [...root.querySelectorAll('[data-asset-overview-tab]')];
      const assetOverviewPanels = [...root.querySelectorAll('[data-asset-overview-panel]')];
      const assetOverviewWorkbenchWrap = root.querySelector('#assetOverviewWorkbenchWrap');
      const uploadForm = root.querySelector('#assetUploadForm');
      const uploadMsg = root.querySelector('#assetUploadMsg');
      const uploadResult = root.querySelector('#assetUploadResult');
      const filterForm = root.querySelector('#assetFilterForm');
      const tableWrap = root.querySelector('#assetsTableWrap');
      const assetShowHistoryExports = root.querySelector('#assetShowHistoryExports');
      const assetListMeta = root.querySelector('#assetListMeta');
      const assetListFilters = { showExportHistory: false };
      let activeAssetPanel = 'overview';
      let activeAssetOverviewPanel = 'summary';

      function setAssetOverviewPanel(panel) {
        activeAssetOverviewPanel = ['summary', 'list'].includes(panel) ? panel : 'summary';
        assetOverviewPanels.forEach((section) => {
          section.hidden = section.getAttribute('data-asset-overview-panel') !== activeAssetOverviewPanel || activeAssetPanel !== 'overview';
        });
        assetOverviewTabs.forEach((button) => {
          const active = button.getAttribute('data-asset-overview-tab') === activeAssetOverviewPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (assetOverviewPanelMeta) {
          assetOverviewPanelMeta.textContent = activeAssetOverviewPanel === 'summary'
            ? '先看当前资产池的用途分布和推荐下一步动作。'
            : '需要复制资产编号、指定资产去任务或训练时，再进入资产列表。';
        }
      }

      function setAssetPanel(panel) {
        activeAssetPanel = ['overview', 'upload', 'guide'].includes(panel) ? panel : 'overview';
        assetPanels.forEach((section) => {
          const panelName = section.getAttribute('data-asset-panel');
          if (panelName !== activeAssetPanel) {
            section.hidden = true;
            return;
          }
          if (panelName === 'overview' && section.hasAttribute('data-asset-overview-panel')) return;
          section.hidden = false;
        });
        assetPanelTabs.forEach((button) => {
          const active = button.getAttribute('data-asset-panel-tab') === activeAssetPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (assetPanelMeta) {
          assetPanelMeta.textContent = activeAssetPanel === 'overview'
            ? '先看资产列表和用途分布。'
            : activeAssetPanel === 'upload'
              ? '集中处理新资产上传和结果回跳。'
              : '快速确认训练、验证、推理三类资产的推荐用法。';
        }
        if (activeAssetPanel === 'overview') setAssetOverviewPanel(activeAssetOverviewPanel);
      }

      function prefillTrainingAssets(assetIds) {
        const merged = [...new Set([...splitCsv(localStorage.getItem(STORAGE_KEYS.prefillTrainingAssetIds) || ''), ...assetIds])];
        localStorage.setItem(STORAGE_KEYS.prefillTrainingAssetIds, merged.join(', '));
      }

      async function loadAssets() {
        tableWrap.innerHTML = renderLoading('加载资产列表...');
        if (assetOverviewWorkbenchWrap) assetOverviewWorkbenchWrap.innerHTML = renderLoading('加载资产概览...');
        try {
          const fd = new FormData(filterForm);
          const query = toQuery({
            q: fd.get('q'),
            asset_purpose: fd.get('asset_purpose'),
            limit: 100,
          });
          const rows = filterBusinessAssets(await ctx.get(`/assets${query}`));
          const collapsed = assetListFilters.showExportHistory ? { rows, hiddenCount: 0 } : collapseLatestCarNumberExportAssets(rows);
          const visibleRows = collapsed.rows;
          if (assetListMeta) {
            assetListMeta.textContent = assetListFilters.showExportHistory
              ? `显示 ${visibleRows.length} 条真实资产`
              : `显示 ${visibleRows.length} 条真实资产，收起 OCR 导出历史 ${collapsed.hiddenCount} 条`;
          }
          if (assetOverviewWorkbenchWrap) {
            const counts = {
              inference: visibleRows.filter((row) => (row.meta || {}).asset_purpose === 'inference').length,
              training: visibleRows.filter((row) => (row.meta || {}).asset_purpose === 'training').length,
              validation: visibleRows.filter((row) => (row.meta || {}).asset_purpose === 'validation').length,
            };
            const primaryNext = counts.inference ? '去任务中心验证' : counts.training ? '去训练中心准备训练' : '先上传资产';
            assetOverviewWorkbenchWrap.innerHTML = renderWorkbenchOverview({
              title: '当前资产池',
              summary: counts.inference
                ? '当前已有可直接用于识别验证的图片或视频资产。优先去任务中心创建任务。'
                : counts.training
                  ? '当前主要是训练/验证资产，适合直接进入训练中心准备训练。'
                  : '当前资产以整理和归档为主，建议先补充真实图片或视频，再进入任务或训练链路。',
              metrics: [
                { label: '总资产', value: visibleRows.length, note: '当前筛选结果' },
                { label: '推理资产', value: counts.inference, note: '可直接用于任务' },
                { label: '训练资产', value: counts.training, note: '可用于训练 / 微调' },
                { label: '验证资产', value: counts.validation, note: '可用于回归验证' },
              ],
              actions: [
                { id: 'asset-open-upload', label: '上传新资产', primary: true },
                { id: 'asset-open-list', label: '查看资产列表' },
                { id: 'asset-open-next', label: primaryNext },
              ],
            });
            assetOverviewWorkbenchWrap.querySelector('[data-workbench-action="asset-open-upload"]')?.addEventListener('click', () => {
              setAssetPanel('upload');
            });
            assetOverviewWorkbenchWrap.querySelector('[data-workbench-action="asset-open-list"]')?.addEventListener('click', () => {
              setAssetPanel('overview');
              setAssetOverviewPanel('list');
            });
            assetOverviewWorkbenchWrap.querySelector('[data-workbench-action="asset-open-next"]')?.addEventListener('click', () => {
              if (counts.inference) ctx.navigate('tasks');
              else if (counts.training) ctx.navigate('training');
              else setAssetPanel('upload');
            });
          }
          if (!visibleRows.length) {
            tableWrap.innerHTML = renderEmpty('暂无资产。建议先上传一条单图 / 单视频资产用于推理，或上传 ZIP 数据集包用于训练准备');
            return;
          }
          tableWrap.innerHTML = `
            <div class="selection-grid">
              ${visibleRows.map((row) => {
                const datasetMeta = row.dataset_version_meta || null;
                const datasetBadge = isCarNumberOcrExportAsset(row)
                  ? `<span class="badge">${esc(datasetMeta?.is_latest ? `OCR 最新 ${datasetMeta?.version || ''}`.trim() : `OCR 历史 ${datasetMeta?.version || ''}`.trim())}</span>`
                  : '';
                return `
                  <article class="selection-card">
                    <div class="selection-card-head selection-card-head--stack">
                      <div class="selection-card-title">
                        <strong title="${esc(row.file_name)}">${esc(row.file_name)}</strong>
                        <span class="selection-card-subtitle mono">${esc(truncateMiddle(row.id, 10, 8))}</span>
                      </div>
                      <div class="quick-review-statuses">
                        <span class="badge">${esc(enumText('asset_type', row.asset_type))}</span>
                        ${datasetBadge}
                      </div>
                    </div>
                    <div class="selection-card-meta selection-card-meta--compact">
                      <span>用途</span><strong>${esc(enumText('asset_purpose', (row.meta || {}).asset_purpose || '-'))}</strong>
                      <span>敏感等级</span><strong>${esc(enumText('sensitivity_level', row.sensitivity_level))}</strong>
                      <span>资源数</span><strong>${archiveResourceCount(row.meta || {}) || 1}</strong>
                      <span>创建时间</span><strong>${formatDateTime(row.created_at)}</strong>
                    </div>
                    <div class="row-actions">
                      <button class="ghost" data-copy-asset="${esc(row.id)}">复制资产编号</button>
                      <button class="ghost" data-use-training-asset="${esc(row.id)}">用于训练</button>
                      ${isTaskAsset(row) ? `<button class="primary" data-quick-detect-asset="${esc(row.id)}">快速识别</button>` : ''}
                      ${isTaskAsset(row) ? `<button class="ghost" data-use-asset="${esc(row.id)}">用于任务</button>` : ''}
                    </div>
                    <details class="inline-details">
                      <summary>技术详情</summary>
                      <div class="details-panel">
                        <div class="selection-card-meta selection-card-meta--compact">
                          <span>资产编号</span><strong class="mono">${esc(row.id)}</strong>
                          <span>数据集标签</span><strong>${esc((row.meta || {}).dataset_label || '-')}</strong>
                          <span>业务场景</span><strong>${esc((row.meta || {}).use_case || '-')}</strong>
                          <span>希望适配的模型</span><strong>${esc((row.meta || {}).intended_model_code || '-')}</strong>
                        </div>
                      </div>
                    </details>
                  </article>
                `;
              }).join('')}
            </div>
          `;
          tableWrap.querySelectorAll('[data-copy-asset]').forEach((btn) => {
            btn.addEventListener('click', async () => {
              const assetId = btn.getAttribute('data-copy-asset') || '';
              try {
                await navigator.clipboard.writeText(assetId);
                ctx.toast('资产编号已复制');
              } catch {
                ctx.toast(`资产编号: ${assetId}`);
              }
            });
          });
          tableWrap.querySelectorAll('[data-use-asset]').forEach((btn) => {
            btn.addEventListener('click', () => {
              localStorage.setItem(STORAGE_KEYS.prefillAssetId, btn.getAttribute('data-use-asset') || '');
              ctx.navigate('tasks');
            });
          });
          tableWrap.querySelectorAll('[data-use-training-asset]').forEach((btn) => {
            btn.addEventListener('click', () => {
              prefillTrainingAssets([btn.getAttribute('data-use-training-asset') || '']);
              ctx.navigate('training');
            });
          });
          tableWrap.querySelectorAll('[data-quick-detect-asset]').forEach((btn) => {
            btn.addEventListener('click', () => {
              localStorage.setItem(STORAGE_KEYS.quickDetectAssetId, btn.getAttribute('data-quick-detect-asset') || '');
              ctx.navigate('tasks');
            });
          });
        } catch (error) {
          tableWrap.innerHTML = renderError(error.message);
        }
      }

      uploadForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        uploadMsg.textContent = '';
        const submitBtn = uploadForm.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        try {
          const formData = new FormData(uploadForm);
          const data = await ctx.postForm('/assets/upload', formData);
          uploadMsg.textContent = '上传成功';
          uploadResult.innerHTML = renderInfoPanel(
            '上传结果',
            [
              { label: '资产编号', value: data.id, mono: true },
              { label: '文件名', value: data.file_name },
              { label: '资源类型', value: enumText('asset_type', data.asset_type) },
              { label: '敏感等级', value: enumText('sensitivity_level', data.sensitivity_level) },
              archiveResourceCount(data.meta || {})
                ? { label: '资源数', value: archiveResourceCount(data.meta || {}) }
                : null,
            ],
            `
              <div class="row-actions">
                <button class="ghost" id="copyAssetIdBtn">复制资产编号</button>
                ${isTaskAsset(data) ? `<button class="primary" id="gotoQuickDetectFromAsset">快速识别</button>` : ''}
                ${isTaskAsset(data) ? `<button class="primary" id="gotoTaskFromAsset">用该资产创建任务</button>` : ''}
                <button class="ghost" id="gotoTrainingFromAsset">用于训练</button>
              </div>
            `,
          );
          root.querySelector('#copyAssetIdBtn')?.addEventListener('click', async () => {
            try {
              await navigator.clipboard.writeText(String(data.id || ''));
              ctx.toast('资产ID已复制');
            } catch {
              ctx.toast(`资产ID: ${data.id}`);
            }
          });
          root.querySelector('#gotoTaskFromAsset')?.addEventListener('click', () => {
            localStorage.setItem(STORAGE_KEYS.prefillAssetId, data.id);
            ctx.navigate('tasks');
          });
          root.querySelector('#gotoQuickDetectFromAsset')?.addEventListener('click', () => {
            localStorage.setItem(STORAGE_KEYS.quickDetectAssetId, data.id);
            ctx.navigate('tasks');
          });
          root.querySelector('#gotoTrainingFromAsset')?.addEventListener('click', () => {
            prefillTrainingAssets([data.id]);
            ctx.navigate('training');
          });
          setAssetPanel('overview');
          await loadAssets();
          uploadForm.reset();
        } catch (error) {
          uploadMsg.textContent = error.message || '上传失败';
        } finally {
          submitBtn.disabled = false;
        }
      });

      filterForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        await loadAssets();
      });
      assetShowHistoryExports?.addEventListener('change', () => {
        assetListFilters.showExportHistory = assetShowHistoryExports.checked;
        loadAssets();
      });
      assetPanelTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setAssetPanel(button.getAttribute('data-asset-panel-tab') || 'overview');
        });
      });
      assetOverviewTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setAssetOverviewPanel(button.getAttribute('data-asset-overview-tab') || 'summary');
        });
      });

      setAssetPanel('overview');
      await loadAssets();
    },
  };
}

function pageModels(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const role = primaryRole(ctx.state.user);
  const canApprove = hasPermission(ctx.state, 'model.approve');
  const canRelease = hasPermission(ctx.state, 'model.release');
  const canCreateTrainingJob = hasPermission(ctx.state, 'training.job.create');
  const canViewTrainingJob = hasPermission(ctx.state, 'training.job.view');
  const canCreateTask = hasPermission(ctx.state, 'task.create');
  const heroSummary = role.startsWith('supplier')
    ? '提交基础算法和待验证模型，持续看审批反馈、验证表现和训练协作状态。'
    : role.startsWith('platform_')
      ? '统一完成新模型验证、审批和发布，把成果模型收进受控交付链路。'
      : '查看已授权模型、候选状态与交付进度。';

  return {
    html: `
      ${renderPageHero({
        eyebrow: '模型交付与审批',
        title: '模型中心',
        summary: heroSummary,
        highlights: ['模型提交', '审批工作台', '发布工作台'],
        actions: [
          { path: 'training', label: '去训练中心' },
          { path: 'tasks', label: '去任务中心验证', primary: true },
        ],
      })}
      <section class="card" data-model-panel="overview">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-model-overview-tab="workbench">工作台概览</button>
          <button class="ghost" type="button" data-model-overview-tab="list">模型列表</button>
        </div>
        <div id="modelOverviewPanelMeta" class="hint">默认先看模型工作台概览；需要批量筛选或切换模型时再进入模型列表。</div>
      </section>
      <section class="card" data-model-panel="overview" data-model-overview-panel="workbench" hidden>
        <h3>模型工作台概览</h3>
        <div id="modelWorkbenchOverviewWrap">${renderEmpty('先从模型列表选择一版待验证模型，这里会汇总当前状态、验证结论和推荐下一步动作。')}</div>
      </section>
      <section class="card">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-model-panel-tab="overview">模型总览</button>
          <button class="ghost" type="button" data-model-panel-tab="build">提交与训练协作</button>
          <button class="ghost" type="button" data-model-panel-tab="governance">审批与发布</button>
        </div>
        <div id="modelPanelMeta" class="hint">默认先看模型总览；低频操作按工作区展开。</div>
      </section>
      <section class="card" data-model-panel="build" hidden>
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-model-build-tab="submit">提交与协作</button>
          <button class="ghost" type="button" data-model-build-tab="create-job">创建训练</button>
        </div>
        <div id="modelBuildPanelMeta" class="hint">默认先看模型提交和训练协作；需要继续训练时再切到创建训练。</div>
      </section>
      <section class="card" data-model-panel="governance" hidden>
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-model-governance-tab="timeline">时间线与评估</button>
          <button class="ghost" type="button" data-model-governance-tab="approval">审批工作台</button>
          <button class="ghost" type="button" data-model-governance-tab="release">发布工作台</button>
        </div>
        <div id="modelGovernancePanelMeta" class="hint">默认先看时间线和评估；审批、发布按当前阶段进入。</div>
      </section>
      <section class="card" data-model-panel="overview" data-model-overview-panel="list" hidden>
        <h3>模型列表</h3>
        <div class="section-toolbar">
          <input id="modelListSearch" placeholder="搜索模型名称 / 版本 / 插件 / 租户" />
          <select id="modelStatusFilter">
            <option value="">全部状态</option>
            <option value="SUBMITTED">${enumText('model_status', 'SUBMITTED')}</option>
            <option value="APPROVED">${enumText('model_status', 'APPROVED')}</option>
            <option value="RELEASED">${enumText('model_status', 'RELEASED')}</option>
          </select>
          <select id="modelSourceFilter">
            <option value="">全部来源</option>
            <option value="delivery_candidate">${enumText('model_source_type', 'delivery_candidate')}</option>
            <option value="finetuned_candidate">${enumText('model_source_type', 'finetuned_candidate')}</option>
            <option value="initial_algorithm">${enumText('model_source_type', 'initial_algorithm')}</option>
            <option value="pretrained_seed">${enumText('model_source_type', 'pretrained_seed')}</option>
          </select>
          <div id="modelListMeta" class="hint"></div>
        </div>
        <div id="modelsTableWrap">${renderLoading('加载模型列表...')}</div>
      </section>
      <section class="grid-two" data-model-panel="build" data-model-build-panel="submit" hidden>
        <form id="modelRegisterForm" class="card form-grid">
          <h3>提交模型包</h3>
          <label>模型包(.zip)</label>
          <input type="file" name="package" accept=".zip" required />
          <label>模型来源</label>
          <select name="model_source_type">
            <option value="delivery_candidate">${enumText('model_source_type', 'delivery_candidate')}</option>
            <option value="finetuned_candidate">${enumText('model_source_type', 'finetuned_candidate')}</option>
            <option value="initial_algorithm">${enumText('model_source_type', 'initial_algorithm')}</option>
            <option value="pretrained_seed">${enumText('model_source_type', 'pretrained_seed')}</option>
          </select>
          <label>模型类型</label>
          <select name="model_type">
            <option value="expert">${enumText('model_type', 'expert')}</option>
            <option value="router">${enumText('model_type', 'router')}</option>
          </select>
          <details>
            <summary>高级元信息（可选）</summary>
            <div class="details-panel form-grid">
              <label>插件名称</label>
              <input name="plugin_name" placeholder="例如 car_number_ocr_plugin" />
              <label>训练轮次</label>
              <input name="training_round" placeholder="round-1" />
              <label>数据集标签</label>
              <input name="dataset_label" placeholder="buyer-demo-v1" />
              <label>训练摘要</label>
              <textarea name="training_summary" rows="2" placeholder="微调摘要"></textarea>
            </div>
          </details>
          <button class="primary" type="submit">提交模型</button>
          <div id="modelRegisterMsg" class="hint"></div>
          <div id="modelRegisterResult">${renderEmpty('提交模型后会在这里显示模型编号、版本和下一步动作')}</div>
        </form>
        <section class="card">
          <h3>训练作业协作</h3>
          <div id="trainingJobsWrap">${canViewTrainingJob ? renderLoading('加载训练作业...') : renderEmpty('当前角色无训练作业查看权限')}</div>
        </section>
      </section>
      <section class="grid-two" data-model-panel="build" data-model-build-panel="create-job" hidden>
        <section class="card">
          <h3>创建训练作业</h3>
          ${
            canCreateTrainingJob
              ? `
                <form id="trainingJobForm" class="form-grid">
                  <label>训练类型</label>
                  <select name="training_kind">
                    <option value="finetune">${enumText('training_kind', 'finetune')}</option>
                    <option value="train">${enumText('training_kind', 'train')}</option>
                    <option value="evaluate">${enumText('training_kind', 'evaluate')}</option>
                  </select>
                  <label>训练数据（资产编号，可多个）</label>
                  <input name="asset_ids" placeholder="资产编号-1, 资产编号-2" />
                  <div class="hint">支持单图/单视频资产，也支持 ZIP 数据集包；一个 ZIP 包对应 1 个资产编号。</div>
                  <label>验证数据（资产编号，可多个）</label>
                  <input name="validation_asset_ids" placeholder="资产编号-3, 资产编号-4" />
                  <label>基础模型编号（可选）</label>
                  <input name="base_model_id" placeholder="模型编号" />
                  <label>训练后模型名称</label>
                  <input name="target_model_code" placeholder="car_number_ocr" required />
                  <label>训练后版本号</label>
                  <input name="target_version" placeholder="v2.0.0" required />
                  <button class="primary" type="submit">创建训练作业</button>
                  <div id="trainingJobMsg" class="hint"></div>
                </form>
              `
              : renderEmpty('当前角色无训练作业创建权限')
          }
        </section>
      </section>
      <section class="grid-two" data-model-panel="governance" data-model-governance-panel="timeline" hidden>
        <section class="card">
          <h3>模型时间线</h3>
          <div id="modelTimelineWrap">${renderEmpty('在模型列表点击“时间线”，查看提交、审批、发布和回收轨迹')}</div>
        </section>
        <section class="card">
          <h3>评估与风险</h3>
          <div id="modelReadinessWrap">${renderEmpty('在模型列表点击“评估”，查看自动验证结论和发布前风险摘要')}</div>
        </section>
      </section>
      <section class="card" data-model-panel="governance" data-model-governance-panel="approval" hidden>
        <section class="card">
          <h3>审批工作台</h3>
          <div id="modelApprovalWorkbenchWrap">${renderEmpty('先在模型列表里选一版待验证模型，这里会自动推荐验证样本、汇总验证结果，并在满足门禁后给出一键审批。')}</div>
        </section>
      </section>
      <section class="card" data-model-panel="governance" data-model-governance-panel="release" hidden>
        <section class="card">
          <h3>发布工作台</h3>
          <div id="modelReleaseWorkbenchWrap">${renderEmpty('审批通过后，在这里选择设备、买家和交付方式。系统会先做发布前评估，再确认发布。')}</div>
        </section>
      </section>
    `,
    async mount(root) {
      bindPageNavButtons(root, ctx);
      const modelsWrap = root.querySelector('#modelsTableWrap');
      const registerForm = root.querySelector('#modelRegisterForm');
      const registerMsg = root.querySelector('#modelRegisterMsg');
      const registerResult = root.querySelector('#modelRegisterResult');
      const modelWorkbenchOverviewWrap = root.querySelector('#modelWorkbenchOverviewWrap');
      const modelPanelMeta = root.querySelector('#modelPanelMeta');
      const modelPanelTabs = [...root.querySelectorAll('[data-model-panel-tab]')];
      const modelPanels = [...root.querySelectorAll('[data-model-panel]')];
      const modelOverviewPanelMeta = root.querySelector('#modelOverviewPanelMeta');
      const modelOverviewTabs = [...root.querySelectorAll('[data-model-overview-tab]')];
      const modelOverviewPanels = [...root.querySelectorAll('[data-model-overview-panel]')];
      const modelBuildPanelMeta = root.querySelector('#modelBuildPanelMeta');
      const modelBuildTabs = [...root.querySelectorAll('[data-model-build-tab]')];
      const modelBuildPanels = [...root.querySelectorAll('[data-model-build-panel]')];
      const modelGovernancePanelMeta = root.querySelector('#modelGovernancePanelMeta');
      const modelGovernanceTabs = [...root.querySelectorAll('[data-model-governance-tab]')];
      const modelGovernancePanels = [...root.querySelectorAll('[data-model-governance-panel]')];
      const timelineWrap = root.querySelector('#modelTimelineWrap');
      const readinessWrap = root.querySelector('#modelReadinessWrap');
      const approvalWorkbenchWrap = root.querySelector('#modelApprovalWorkbenchWrap');
      const releaseWorkbenchWrap = root.querySelector('#modelReleaseWorkbenchWrap');
      const trainingJobsWrap = root.querySelector('#trainingJobsWrap');
      const trainingJobForm = root.querySelector('#trainingJobForm');
      const trainingJobMsg = root.querySelector('#trainingJobMsg');
      const modelListSearch = root.querySelector('#modelListSearch');
      const modelStatusFilter = root.querySelector('#modelStatusFilter');
      const modelSourceFilter = root.querySelector('#modelSourceFilter');
      const modelListMeta = root.querySelector('#modelListMeta');
      let cachedModels = [];
      let activeApprovalModelId = '';
      let activeReleaseModelId = '';
      const requestedFocusModelId = localStorage.getItem(STORAGE_KEYS.focusModelId);
      const requestedOpenModelTimeline = localStorage.getItem(STORAGE_KEYS.focusModelTimeline) === '1';
      let activeModelId = requestedFocusModelId || '';
      let activeModelPanel = requestedFocusModelId ? 'governance' : 'overview';
      let activeModelOverviewPanel = 'workbench';
      let activeModelBuildPanel = 'submit';
      let activeModelGovernancePanel = requestedFocusModelId ? 'timeline' : 'timeline';
      const modelListFilters = { q: '', status: '', source: '' };

      function setModelOverviewPanel(panel) {
        activeModelOverviewPanel = ['workbench', 'list'].includes(panel) ? panel : 'workbench';
        modelOverviewPanels.forEach((section) => {
          section.hidden = section.getAttribute('data-model-overview-panel') !== activeModelOverviewPanel || activeModelPanel !== 'overview';
        });
        modelOverviewTabs.forEach((button) => {
          const active = button.getAttribute('data-model-overview-tab') === activeModelOverviewPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (modelOverviewPanelMeta) {
          modelOverviewPanelMeta.textContent = activeModelOverviewPanel === 'workbench'
            ? '先看当前焦点模型的风险、验证结论和推荐下一步动作。'
            : '需要批量筛选、切换模型或查看全量状态时，再进入模型列表。';
        }
      }

      function setModelBuildPanel(panel) {
        activeModelBuildPanel = ['submit', 'create-job'].includes(panel) ? panel : 'submit';
        modelBuildPanels.forEach((section) => {
          section.hidden = section.getAttribute('data-model-build-panel') !== activeModelBuildPanel || activeModelPanel !== 'build';
        });
        modelBuildTabs.forEach((button) => {
          const active = button.getAttribute('data-model-build-tab') === activeModelBuildPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (modelBuildPanelMeta) {
          modelBuildPanelMeta.textContent = activeModelBuildPanel === 'submit'
            ? '先提交新模型，或查看训练协作记录。'
            : '当你已经准备好训练数据和基础算法时，再创建训练作业。';
        }
      }

      function setModelGovernancePanel(panel) {
        activeModelGovernancePanel = ['timeline', 'approval', 'release'].includes(panel) ? panel : 'timeline';
        modelGovernancePanels.forEach((section) => {
          section.hidden = section.getAttribute('data-model-governance-panel') !== activeModelGovernancePanel || activeModelPanel !== 'governance';
        });
        modelGovernanceTabs.forEach((button) => {
          const active = button.getAttribute('data-model-governance-tab') === activeModelGovernancePanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (modelGovernancePanelMeta) {
          modelGovernancePanelMeta.textContent = activeModelGovernancePanel === 'timeline'
            ? '先看时间线和评估，再决定是否进入审批或发布。'
            : activeModelGovernancePanel === 'approval'
              ? '集中处理验证样本、审批判断和批准动作。'
              : '集中处理设备范围、买家范围和正式发布。';
        }
      }

      function setModelPanel(panel) {
        activeModelPanel = ['overview', 'build', 'governance'].includes(panel) ? panel : 'overview';
        modelPanels.forEach((section) => {
          const panelName = section.getAttribute('data-model-panel');
          if (panelName !== activeModelPanel) {
            section.hidden = true;
            return;
          }
          if (panelName === 'overview' && section.hasAttribute('data-model-overview-panel')) return;
          if (panelName === 'build' && section.hasAttribute('data-model-build-panel')) return;
          if (panelName === 'governance' && section.hasAttribute('data-model-governance-panel')) return;
          section.hidden = false;
        });
        modelPanelTabs.forEach((button) => {
          const active = button.getAttribute('data-model-panel-tab') === activeModelPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (modelPanelMeta) {
          modelPanelMeta.textContent = activeModelPanel === 'overview'
            ? '先看模型状态、风险和下一步动作。'
            : activeModelPanel === 'build'
              ? '把模型提交和训练协作放在同一处，减少审批信息干扰。'
              : '把时间线、评估、审批和发布集中处理。';
        }
        if (activeModelPanel === 'overview') setModelOverviewPanel(activeModelOverviewPanel);
        if (activeModelPanel === 'build') setModelBuildPanel(activeModelBuildPanel);
        if (activeModelPanel === 'governance') setModelGovernancePanel(activeModelGovernancePanel);
      }

      function selectedModelRecord() {
        return cachedModels.find((row) => row.id === activeModelId) || null;
      }

      function renderModelWorkbenchOverview() {
        if (!modelWorkbenchOverviewWrap) return;
        const model = selectedModelRecord();
        if (!model) {
          modelWorkbenchOverviewWrap.innerHTML = renderWorkbenchOverview({
            title: '还没有选中模型',
            summary: '先从下方模型列表选一版待验证模型。系统会把时间线、门禁、审批和发布动作聚合到同一屏。',
            metrics: [
              { label: '待验证模型', value: filteredModels(cachedModels).filter((row) => row.status === 'SUBMITTED').length, note: '待审批' },
              { label: '已审批', value: filteredModels(cachedModels).filter((row) => row.status === 'APPROVED').length, note: '可进入发布工作台' },
              { label: '已发布', value: filteredModels(cachedModels).filter((row) => row.status === 'RELEASED').length, note: '可直接授权使用' },
            ],
            actions: [
              { id: 'model-open-list', label: '查看模型列表', primary: true },
              { id: 'model-open-training', label: '去训练中心' },
            ],
          });
        } else {
          const sourceType = (model.platform_meta || {}).model_source_type || '-';
          const validationDecision = model.validation_report?.decision || '待验证';
          const latestRisk = model.latest_release_risk_summary?.decision || '待评估';
          const actions = [
            { id: 'model-open-readiness', label: '查看评估', primary: true },
            { id: 'model-open-timeline', label: '查看时间线' },
          ];
          if (canApprove && model.status === 'SUBMITTED') {
            actions.push({ id: 'model-open-approval', label: '进入审批工作台' });
          }
          if (canRelease && ['APPROVED', 'RELEASED'].includes(model.status)) {
            actions.push({ id: 'model-open-release', label: '进入发布工作台' });
          }
          modelWorkbenchOverviewWrap.innerHTML = renderWorkbenchOverview({
            title: `${model.model_code}:${model.version}`,
            status: enumText('model_status', model.status),
            summary: model.status === 'SUBMITTED'
              ? '这版待验证模型还在审批前验证阶段。建议先检查门禁，再批量创建验证任务。'
              : model.status === 'APPROVED'
                ? '模型已审批通过，下一步进入发布工作台，确认设备范围、买家范围和交付方式。'
                : '模型已进入正式交付链路，可回看发布前评估和最近风险摘要。',
            metrics: [
              { label: '验证门禁', value: validationDecision, note: model.validation_report?.summary || '待生成验证摘要' },
              { label: '发布风险', value: latestRisk, note: model.latest_release_risk_summary?.summary || '待做发布评估' },
              { label: '来源', value: enumText('model_source_type', sourceType), note: model.owner_tenant_name || model.owner_tenant_code || '当前租户' },
            ],
            actions,
          });
        }
        modelWorkbenchOverviewWrap.querySelector('[data-workbench-action="model-open-list"]')?.addEventListener('click', () => {
          setModelPanel('overview');
          setModelOverviewPanel('list');
          modelsWrap?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        modelWorkbenchOverviewWrap.querySelector('[data-workbench-action="model-open-training"]')?.addEventListener('click', () => {
          ctx.navigate('training');
        });
        modelWorkbenchOverviewWrap.querySelector('[data-workbench-action="model-open-readiness"]')?.addEventListener('click', async () => {
          if (!activeModelId) return;
          try {
            setModelPanel('governance');
            setModelGovernancePanel('timeline');
            await openModelReadiness(activeModelId);
            readinessWrap?.scrollIntoView({ behavior: 'smooth', block: 'center' });
          } catch (error) {
            ctx.toast(error.message || '模型评估失败', 'error');
          }
        });
        modelWorkbenchOverviewWrap.querySelector('[data-workbench-action="model-open-timeline"]')?.addEventListener('click', async () => {
          if (!activeModelId) return;
          setModelPanel('governance');
          setModelGovernancePanel('timeline');
          await openModelTimeline(activeModelId);
          timelineWrap?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
        modelWorkbenchOverviewWrap.querySelector('[data-workbench-action="model-open-approval"]')?.addEventListener('click', async () => {
          if (!activeModelId) return;
          try {
            setModelPanel('governance');
            setModelGovernancePanel('approval');
            await openModelReadiness(activeModelId);
            await openModelApprovalWorkbench(activeModelId);
            approvalWorkbenchWrap?.scrollIntoView({ behavior: 'smooth', block: 'center' });
          } catch (error) {
            ctx.toast(error.message || '审批工作台加载失败', 'error');
          }
        });
        modelWorkbenchOverviewWrap.querySelector('[data-workbench-action="model-open-release"]')?.addEventListener('click', async () => {
          if (!activeModelId) return;
          try {
            setModelPanel('governance');
            setModelGovernancePanel('release');
            await openModelReleaseWorkbench(activeModelId);
            releaseWorkbenchWrap?.scrollIntoView({ behavior: 'smooth', block: 'center' });
          } catch (error) {
            ctx.toast(error.message || '发布工作台加载失败', 'error');
          }
        });
      }

      function renderReadinessChecks(title, report) {
        const checks = Array.isArray(report?.checks) ? report.checks : [];
        return `
          <section class="readiness-section">
            <div class="readiness-head">
              <strong>${esc(title)}</strong>
              <span class="badge">${esc(report?.decision || '-')}</span>
            </div>
            <p>${esc(report?.summary || '-')}</p>
            <div class="readiness-counts">
              <span>阻断 ${esc(report?.counts?.blocker_count ?? 0)}</span>
              <span>提醒 ${esc(report?.counts?.warning_count ?? 0)}</span>
              <span>通过 ${esc(report?.counts?.ok_count ?? 0)}</span>
            </div>
            ${checks.length ? `
              <ul class="readiness-checklist">
                ${checks.map((item) => `
                  <li class="readiness-check ${esc(item.status || 'warning')}">
                    <strong>${esc(item.label || item.code || '-')}</strong>
                    <span>${esc(item.reason || '-')}</span>
                  </li>
                `).join('')}
              </ul>
            ` : '<div class="hint">暂无检查项</div>'}
          </section>
        `;
      }

      function renderModelReadinessPanel(data, releaseTitle = '默认发布评估') {
        const validationReport = data?.validation_report || {};
        const releaseRiskSummary = data?.release_risk_summary || data?.default_release_risk_summary || {};
        const metrics = validationReport.metrics || {};
        const trainingJob = validationReport.training_job || null;
        return `
          <div class="readiness-summary-grid">
            <article class="metric-card">
              <h4>自动验证</h4>
              <p class="metric">${esc(validationReport.decision || '-')}</p>
              <span>${esc(validationReport.summary || '暂无自动验证结果')}</span>
            </article>
            <article class="metric-card">
              <h4>${esc(releaseTitle)}</h4>
              <p class="metric">${esc(releaseRiskSummary.decision || '-')}</p>
              <span>${esc(releaseRiskSummary.summary || '暂无发布评估')}</span>
            </article>
            <article class="metric-card">
              <h4>验证资产</h4>
              <p class="metric">${esc((validationReport.validation_asset_ids || []).length)}</p>
              <span>${esc(trainingJob ? `训练作业 ${trainingJob.job_code}` : '未绑定训练作业')}</span>
            </article>
          </div>
          <div class="keyvals compact">
            <div><span>验证得分</span><strong>${esc(formatMetricValue(metrics.val_score, { digits: 4 }))}</strong></div>
            <div><span>验证准确率</span><strong>${esc(formatMetricValue(metrics.val_accuracy, { percent: true, digits: 4 }))}</strong></div>
            <div><span>验证损失</span><strong>${esc(formatMetricValue(metrics.val_loss, { digits: 4 }))}</strong></div>
            <div><span>历史点数</span><strong>${esc(metrics.history_count ?? 0)}</strong></div>
            <div><span>最佳检查点</span><strong>${esc(metrics.best_checkpoint?.path || metrics.best_checkpoint?.metric || '-')}</strong></div>
            <div><span>延迟 / 显存</span><strong>${esc(`${metrics.latency_ms ?? '-'} / ${metrics.gpu_mem_mb ?? '-'}`)}</strong></div>
          </div>
          ${renderReadinessChecks('审批门禁', validationReport)}
          ${renderReadinessChecks(releaseTitle, releaseRiskSummary)}
          <details><summary>技术详情</summary><pre>${esc(safeJson(data))}</pre></details>
        `;
      }

      function buildWorkbenchApprovalSummary(workbench, validationAssetIds) {
        const capability = workbench?.capability || {};
        const readiness = workbench?.readiness?.validation_report || {};
        const counts = workbench?.recent_validation_counts || {};
        const successRows = (workbench?.recent_validation_tasks || []).filter((row) => row.status === 'SUCCEEDED');
        const successTexts = successRows
          .map((row) => row?.result?.recognized_text)
          .filter(Boolean)
          .slice(0, 3);
        const metricText = [
          readiness?.metrics?.val_score != null ? `val_score=${formatMetricValue(readiness.metrics.val_score, { digits: 4 })}` : '',
          readiness?.metrics?.val_accuracy != null ? `val_accuracy=${formatMetricValue(readiness.metrics.val_accuracy, { percent: true, digits: 4 })}` : '',
          readiness?.metrics?.val_loss != null ? `val_loss=${formatMetricValue(readiness.metrics.val_loss, { digits: 4 })}` : '',
        ].filter(Boolean).join('，');
        return [
          `审批前已完成 ${capability.task_label || capability.task_type || '候选模型'} 验证。`,
          validationAssetIds.length ? `验证资产 ${validationAssetIds.length} 个。` : '',
          counts.success ? `运行验证成功 ${counts.success} 条。` : '',
          successTexts.length ? `示例输出：${successTexts.join(' / ')}。` : '',
          readiness?.summary ? `门禁结论：${readiness.summary}` : '',
          metricText ? `训练指标：${metricText}。` : '',
        ].filter(Boolean).join(' ');
      }

      function renderApprovalWorkbenchPanel(workbench) {
        const capability = workbench?.capability || {};
        const readiness = workbench?.readiness?.validation_report || {};
        const suggestions = Array.isArray(workbench?.suggested_assets) ? workbench.suggested_assets : [];
        const recentTasks = Array.isArray(workbench?.recent_validation_tasks) ? workbench.recent_validation_tasks : [];
        const counts = workbench?.recent_validation_counts || {};
        const successfulAssetIds = Array.from(new Set(
          recentTasks.filter((row) => row.status === 'SUCCEEDED' && row.asset_id).map((row) => row.asset_id),
        ));
        const defaultSelection = new Set(
          successfulAssetIds.length
            ? successfulAssetIds
            : suggestions.slice(0, Math.min(3, suggestions.length)).map((row) => row.id),
        );
        const canApproveNow = Boolean(readiness?.can_approve) && successfulAssetIds.length > 0;
        return `
          <div class="approval-workbench" data-approval-model="${esc(workbench?.model?.id || '')}">
            <div class="approval-workbench-grid">
              <article class="metric-card">
                <h4>模型能力</h4>
                <p class="metric">${esc(capability.task_label || capability.task_type || '-')}</p>
                <span>${esc(capability.summary || '暂无能力描述')}</span>
              </article>
              <article class="metric-card">
                <h4>建议样本</h4>
                <p class="metric">${esc(suggestions.length)}</p>
                <span>${esc(suggestions.length ? '已按模型能力和用途排序推荐' : '当前没有命中的建议样本')}</span>
              </article>
              <article class="metric-card">
                <h4>运行验证</h4>
                <p class="metric">${esc(`${counts.success || 0} / ${counts.total || 0}`)}</p>
                <span>${esc((counts.running || 0) > 0 ? `仍有 ${counts.running} 条执行中` : '优先看成功验证再审批')}</span>
              </article>
            </div>
            <div class="approval-workbench-actions">
              <div class="inline-form compact">
                <label class="approval-inline-label">任务类型</label>
                <input id="approvalTaskType" value="${esc(workbench?.recommended_task_type || capability.task_type || '')}" />
                <label class="approval-inline-label">device_code</label>
                <input id="approvalDeviceCode" value="${esc(workbench?.recommended_device_code || 'edge-01')}" />
              </div>
              <div class="row-actions">
                <button class="ghost" type="button" data-approval-select-all>全选建议样本</button>
                <button class="ghost" type="button" data-approval-refresh>刷新验证结果</button>
                <button class="primary" type="button" data-approval-create-tasks ${(suggestions.length && canCreateTask) ? '' : 'disabled'}>批量创建验证任务</button>
              </div>
            </div>
            <div class="hint">${esc(canCreateTask ? '审批前建议先点选几张最贴近该模型能力的样本做运行验证。系统会自动汇总成功样本，不再手填 validation_asset_ids。' : '当前角色没有创建任务权限，只能查看建议样本和已有验证结果。')}</div>
            <div id="approvalWorkbenchMsg" class="hint"></div>
            <div class="approval-suggestion-list">
              ${suggestions.length ? suggestions.map((row) => `
                <label class="approval-asset-card">
                  <input type="checkbox" data-approval-asset value="${esc(row.id)}" ${defaultSelection.has(row.id) ? 'checked' : ''} />
                  <div class="approval-asset-card-body">
                    <strong>${esc(row.file_name || row.id)}</strong>
                    <span class="mono">${esc(row.id)}</span>
                    <span>${esc(enumText('asset_type', row.asset_type || '-'))} · score ${esc(row.score ?? '-')}</span>
                    <span>${esc((row.reason_tags || []).join(' · ') || '推荐样本')}</span>
                  </div>
                </label>
              `).join('') : renderEmpty('当前没有建议样本，可先上传几张单图或视频资产')}
            </div>
            <div class="approval-runtime-list">
              <h4>最近验证结果</h4>
              ${recentTasks.length ? `
                <div class="table-wrap">
                  <table class="table">
                    <thead>
                      <tr><th>任务</th><th>资产</th><th>状态</th><th>输出</th><th>识别置信度</th><th>操作</th></tr>
                    </thead>
                    <tbody>
                      ${recentTasks.map((row) => `
                        <tr>
                          <td class="mono">${esc((row.id || '').slice(0, 12))}</td>
                          <td>${esc(row.asset_file_name || row.asset_id || '-')}</td>
                          <td><span class="badge">${esc(enumText('task_status', row.status || '-'))}</span></td>
                          <td>${esc(row?.result?.recognized_text || row?.result?.summary?.car_number || row.error_message || '-')}</td>
                          <td>${esc(formatMetricValue(row?.result?.confidence, { digits: 3 }))}</td>
                          <td class="row-actions">
                            ${row.status === 'SUCCEEDED' ? `<button class="ghost" type="button" data-open-validation-result="${esc(row.id)}">打开结果</button>` : ''}
                          </td>
                        </tr>
                      `).join('')}
                    </tbody>
                  </table>
                </div>
              ` : renderEmpty('还没有针对这版模型的运行验证任务')}
            </div>
            <div class="approval-summary-card">
              <strong>审批建议</strong>
              <span>${esc(canApproveNow ? '门禁已通过，且已有成功验证样本。可以直接审批。' : readiness?.can_approve ? '训练门禁已通过，但还缺成功运行验证。建议先跑几张样本。' : (readiness?.summary || '当前仍有阻断项，暂不能审批。'))}</span>
              <textarea id="approvalSummaryInput" rows="3" placeholder="审批说明会自动生成，这里可补充少量备注">${esc(buildWorkbenchApprovalSummary(workbench, successfulAssetIds))}</textarea>
              <div class="row-actions">
                <button class="primary" type="button" data-approval-approve ${canApproveNow ? '' : 'disabled'}>一键审批通过</button>
              </div>
            </div>
          </div>
        `;
      }

      function renderReleaseWorkbenchPanel(workbench, evaluated = null) {
        const capability = workbench?.capability || {};
        const recommended = workbench?.recommended_release || {};
        const releaseRisk = evaluated?.release_risk_summary || workbench?.readiness?.release_risk_summary || {};
        const devices = Array.isArray(workbench?.scope_candidates?.devices) ? workbench.scope_candidates.devices : [];
        const buyers = Array.isArray(workbench?.scope_candidates?.buyers) ? workbench.scope_candidates.buyers : [];
        const latestRelease = workbench?.latest_release || null;
        const initialDevices = (recommended.target_devices || []).join(', ');
        const initialBuyers = (recommended.target_buyers || []).join(', ');
        return `
          <div class="release-workbench" data-release-model="${esc(workbench?.model?.id || '')}">
            <div class="approval-workbench-grid">
              <article class="metric-card">
                <h4>发布对象</h4>
                <p class="metric">${esc(capability.task_label || capability.task_type || '-')}</p>
                <span>${esc(workbench?.model?.model_code || '-')} : ${esc(workbench?.model?.version || '-')}</span>
              </article>
              <article class="metric-card">
                <h4>设备范围</h4>
                <p class="metric">${esc(String((recommended.target_devices || []).length || 0))}</p>
                <span>${esc(latestRelease ? '优先继承最近一次发布范围' : '默认取在线设备和可见买家')}</span>
              </article>
              <article class="metric-card">
                <h4>发布前评估</h4>
                <p class="metric">${esc(releaseRisk.decision || '-')}</p>
                <span>${esc(releaseRisk.summary || '先填写交付范围后做评估')}</span>
              </article>
            </div>
            <div class="form-grid release-workbench-form">
              <div class="grid-two">
                <div class="form-grid">
                  <label>目标设备（逗号分隔）</label>
                  <input id="releaseTargetDevices" value="${esc(initialDevices)}" list="releaseDevicesDatalist" placeholder="edge-01" />
                  <label>目标买家（租户编码，逗号分隔）</label>
                  <input id="releaseTargetBuyers" value="${esc(initialBuyers)}" list="releaseBuyersDatalist" placeholder="buyer-demo-001" />
                  <datalist id="releaseDevicesDatalist">
                    ${devices.map((row) => `<option value="${esc(row.code)}">${esc(row.name || row.code)}</option>`).join('')}
                  </datalist>
                  <datalist id="releaseBuyersDatalist">
                    ${buyers.map((row) => `<option value="${esc(row.tenant_code)}">${esc(row.name || row.tenant_code)}</option>`).join('')}
                  </datalist>
                </div>
                <div class="form-grid">
                  <label>交付方式</label>
                  <select id="releaseDeliveryMode">
                    <option value="local_key" ${recommended.delivery_mode === 'local_key' ? 'selected' : ''}>本地解密</option>
                    <option value="api" ${recommended.delivery_mode === 'api' ? 'selected' : ''}>API</option>
                    <option value="hybrid" ${recommended.delivery_mode === 'hybrid' ? 'selected' : ''}>混合</option>
                  </select>
                  <label>授权方式</label>
                  <select id="releaseAuthorizationMode">
                    <option value="device_key" ${recommended.authorization_mode === 'device_key' ? 'selected' : ''}>设备密钥</option>
                    <option value="api_token" ${recommended.authorization_mode === 'api_token' ? 'selected' : ''}>API 令牌</option>
                    <option value="hybrid" ${recommended.authorization_mode === 'hybrid' ? 'selected' : ''}>混合</option>
                  </select>
                  <label>本地密钥标签（可选）</label>
                  <input id="releaseLocalKeyLabel" value="${esc(recommended.local_key_label || '')}" placeholder="edge/keys/model_decrypt.key" />
                  <label>API 密钥标签（可选）</label>
                  <input id="releaseApiKeyLabel" value="${esc(recommended.api_access_key_label || '')}" placeholder="vh_api" />
                </div>
              </div>
              <label class="checkbox-row"><input id="releaseRuntimeEncryption" type="checkbox" ${recommended.runtime_encryption === false ? '' : 'checked'} /> 启用运行时解密</label>
              <div class="hint">推荐直接从下拉候选里选设备和买家。系统会自动检查交付方式、授权方式和解密要求是否匹配。</div>
              <div id="releaseWorkbenchMsg" class="hint"></div>
              <div class="row-actions">
                <button class="ghost" type="button" data-release-evaluate>先做发布评估</button>
                <button class="primary" type="button" data-release-confirm ${releaseRisk.can_release ? '' : 'disabled'}>确认发布</button>
              </div>
            </div>
            <div class="readiness-section">
              <div class="readiness-head">
                <strong>发布风险摘要</strong>
                <span class="badge">${esc(releaseRisk.decision || '-')}</span>
              </div>
              <p>${esc(releaseRisk.summary || '填写参数后点“先做发布评估”')}</p>
              <div class="readiness-counts">
                <span>阻断 ${esc(releaseRisk?.counts?.blocker_count ?? 0)}</span>
                <span>提醒 ${esc(releaseRisk?.counts?.warning_count ?? 0)}</span>
                <span>通过 ${esc(releaseRisk?.counts?.ok_count ?? 0)}</span>
              </div>
              ${Array.isArray(releaseRisk?.checks) && releaseRisk.checks.length ? `
                <ul class="readiness-checklist">
                  ${releaseRisk.checks.map((item) => `
                    <li class="readiness-check ${esc(item.status || 'warning')}">
                      <strong>${esc(item.label || item.code || '-')}</strong>
                      <span>${esc(item.reason || '-')}</span>
                    </li>
                  `).join('')}
                </ul>
              ` : ''}
            </div>
          </div>
        `;
      }

      async function openModelTimeline(modelId) {
        activeModelId = modelId;
        renderModelsTable(cachedModels);
        renderModelWorkbenchOverview();
        timelineWrap.innerHTML = renderLoading('加载模型时间线...');
        try {
          const data = await ctx.get(`/models/${modelId}/timeline`);
          const timeline = data.timeline || [];
          timelineWrap.innerHTML = timeline.length
            ? `
                <ol class="timeline-list">
                  ${timeline.map((item) => `
                    <li>
                      <div><strong>${esc(item.title)}</strong><span>${esc(enumText('model_status', item.status || '-'))}</span></div>
                      <p>${esc(item.summary || '-')}</p>
                      <p class="muted">${esc(item.actor_username || '-')} · ${formatDateTime(item.created_at)}</p>
                    </li>
                  `).join('')}
                </ol>
                <details><summary>技术详情</summary><pre>${esc(safeJson(data))}</pre></details>
              `
            : renderEmpty('该模型暂无时间线数据');
        } catch (error) {
          timelineWrap.innerHTML = renderError(error.message);
        }
      }

      async function openModelReadiness(modelId, releasePayload = null) {
        activeModelId = modelId;
        renderModelsTable(cachedModels);
        renderModelWorkbenchOverview();
        readinessWrap.innerHTML = renderLoading('加载模型评估...');
        try {
          const baseReadiness = await ctx.get(`/models/${modelId}/readiness`);
          let rendered = baseReadiness;
          let releaseTitle = '默认发布评估';
          if (releasePayload) {
            const releaseReadiness = await ctx.post('/models/release-readiness', releasePayload);
            rendered = {
              ...baseReadiness,
              validation_report: releaseReadiness.validation_report,
              release_risk_summary: releaseReadiness.release_risk_summary,
            };
            releaseTitle = '本次发布评估';
          }
          readinessWrap.innerHTML = renderModelReadinessPanel(rendered, releaseTitle);
          return rendered;
        } catch (error) {
          readinessWrap.innerHTML = renderError(error.message || '模型评估加载失败');
          throw error;
        }
      }

      async function openModelApprovalWorkbench(modelId) {
        if (!approvalWorkbenchWrap) return null;
        activeApprovalModelId = modelId;
        activeModelId = modelId;
        renderModelsTable(cachedModels);
        renderModelWorkbenchOverview();
        approvalWorkbenchWrap.innerHTML = renderLoading('加载审批工作台...');
        try {
          const workbench = await ctx.get(`/models/${modelId}/approval-workbench`);
          approvalWorkbenchWrap.innerHTML = renderApprovalWorkbenchPanel(workbench);
          const workbenchMsg = approvalWorkbenchWrap.querySelector('#approvalWorkbenchMsg');
          const taskTypeInput = approvalWorkbenchWrap.querySelector('#approvalTaskType');
          const deviceCodeInput = approvalWorkbenchWrap.querySelector('#approvalDeviceCode');
          const collectSelectedAssetIds = () => Array.from(
            approvalWorkbenchWrap.querySelectorAll('[data-approval-asset]:checked'),
          ).map((node) => node.value).filter(Boolean);

          approvalWorkbenchWrap.querySelector('[data-approval-select-all]')?.addEventListener('click', () => {
            approvalWorkbenchWrap.querySelectorAll('[data-approval-asset]').forEach((input) => {
              input.checked = true;
            });
          });
          approvalWorkbenchWrap.querySelector('[data-approval-refresh]')?.addEventListener('click', async () => {
            await openModelApprovalWorkbench(modelId);
          });
          approvalWorkbenchWrap.querySelectorAll('[data-open-validation-result]').forEach((button) => {
            button.addEventListener('click', () => {
              const taskId = button.getAttribute('data-open-validation-result');
              if (taskId) ctx.navigate(`results/task/${taskId}`);
            });
          });
          approvalWorkbenchWrap.querySelector('[data-approval-create-tasks]')?.addEventListener('click', async () => {
            const assetIds = collectSelectedAssetIds();
            if (!assetIds.length) {
              ctx.toast('先勾选至少一个建议样本', 'error');
              return;
            }
            const taskType = String(taskTypeInput?.value || workbench?.recommended_task_type || '').trim();
            const deviceCode = String(deviceCodeInput?.value || workbench?.recommended_device_code || 'edge-01').trim();
            const createButton = approvalWorkbenchWrap.querySelector('[data-approval-create-tasks]');
            createButton.disabled = true;
            if (workbenchMsg) workbenchMsg.textContent = `正在创建 ${assetIds.length} 条验证任务...`;
            try {
              for (const assetId of assetIds) {
                await ctx.post('/tasks/create', {
                  asset_id: assetId,
                  model_id: modelId,
                  task_type: taskType || workbench?.capability?.task_type || '',
                  device_code: deviceCode || 'edge-01',
                  use_master_scheduler: false,
                  intent_text: workbench?.capability?.task_label || workbench?.capability?.task_type || '',
                });
              }
              ctx.toast(`已创建 ${assetIds.length} 条验证任务`);
              await openModelApprovalWorkbench(modelId);
            } catch (error) {
              if (workbenchMsg) workbenchMsg.textContent = error.message || '创建验证任务失败';
              ctx.toast(error.message || '创建验证任务失败', 'error');
            } finally {
              createButton.disabled = false;
            }
          });
          approvalWorkbenchWrap.querySelector('[data-approval-approve]')?.addEventListener('click', async () => {
            const readiness = workbench?.readiness?.validation_report || {};
            if (!readiness.can_approve) {
              ctx.toast(readiness.summary || '当前仍有阻断项，不能审批', 'error');
              return;
            }
            const validationAssetIds = Array.from(new Set(
              (workbench?.recent_validation_tasks || [])
                .filter((row) => row.status === 'SUCCEEDED' && row.asset_id)
                .map((row) => row.asset_id),
            ));
            if (!validationAssetIds.length) {
              ctx.toast('至少需要一条成功的运行验证样本后再审批', 'error');
              return;
            }
            const summaryInput = approvalWorkbenchWrap.querySelector('#approvalSummaryInput');
            const validationSummary = String(summaryInput?.value || '').trim() || buildWorkbenchApprovalSummary(workbench, validationAssetIds);
            const approveButton = approvalWorkbenchWrap.querySelector('[data-approval-approve]');
            approveButton.disabled = true;
            if (workbenchMsg) workbenchMsg.textContent = '正在提交审批...';
            try {
              await ctx.post('/models/approve', {
                model_id: modelId,
                validation_asset_ids: validationAssetIds,
                validation_result: 'passed',
                validation_summary: validationSummary,
              });
              ctx.toast('模型已审批通过');
              await loadModels();
              await openModelTimeline(modelId);
              await openModelReadiness(modelId);
              await openModelApprovalWorkbench(modelId);
              if (canRelease) {
                await openModelReleaseWorkbench(modelId);
              }
            } catch (error) {
              if (workbenchMsg) workbenchMsg.textContent = error.message || '审批失败';
              ctx.toast(error.message || '审批失败', 'error');
            } finally {
              approveButton.disabled = false;
            }
          });
          return workbench;
        } catch (error) {
          approvalWorkbenchWrap.innerHTML = renderError(error.message || '审批工作台加载失败');
          throw error;
        }
      }

      async function openModelReleaseWorkbench(modelId, releasePayload = null) {
        if (!releaseWorkbenchWrap) return null;
        activeReleaseModelId = modelId;
        activeModelId = modelId;
        renderModelsTable(cachedModels);
        renderModelWorkbenchOverview();
        releaseWorkbenchWrap.innerHTML = renderLoading('加载发布工作台...');
        try {
          const workbench = await ctx.get(`/models/${modelId}/release-workbench`);
          let evaluated = null;
          if (releasePayload) {
            evaluated = await ctx.post('/models/release-readiness', releasePayload);
          }
          releaseWorkbenchWrap.innerHTML = renderReleaseWorkbenchPanel(workbench, evaluated);
          const msg = releaseWorkbenchWrap.querySelector('#releaseWorkbenchMsg');
          const collectPayload = () => {
            const targetDevices = splitCsv(releaseWorkbenchWrap.querySelector('#releaseTargetDevices')?.value || '');
            const targetBuyers = splitCsv(releaseWorkbenchWrap.querySelector('#releaseTargetBuyers')?.value || '');
            const deliveryMode = String(releaseWorkbenchWrap.querySelector('#releaseDeliveryMode')?.value || 'local_key').trim();
            const authorizationMode = String(releaseWorkbenchWrap.querySelector('#releaseAuthorizationMode')?.value || 'device_key').trim();
            const runtimeEncryption = Boolean(releaseWorkbenchWrap.querySelector('#releaseRuntimeEncryption')?.checked);
            const localKeyLabel = String(releaseWorkbenchWrap.querySelector('#releaseLocalKeyLabel')?.value || '').trim() || null;
            const apiAccessKeyLabel = String(releaseWorkbenchWrap.querySelector('#releaseApiKeyLabel')?.value || '').trim() || null;
            return {
              model_id: modelId,
              target_devices: targetDevices,
              target_buyers: targetBuyers,
              delivery_mode: deliveryMode,
              authorization_mode: authorizationMode,
              runtime_encryption: runtimeEncryption,
              local_key_label: localKeyLabel,
              api_access_key_label: apiAccessKeyLabel,
            };
          };
          releaseWorkbenchWrap.querySelector('[data-release-evaluate]')?.addEventListener('click', async () => {
            const payload = collectPayload();
            const button = releaseWorkbenchWrap.querySelector('[data-release-evaluate]');
            button.disabled = true;
            if (msg) msg.textContent = '正在执行发布前评估...';
            try {
              await openModelReadiness(modelId, payload);
              await openModelReleaseWorkbench(modelId, payload);
            } catch (error) {
              if (msg) msg.textContent = error.message || '发布前评估失败';
              ctx.toast(error.message || '发布前评估失败', 'error');
            } finally {
              button.disabled = false;
            }
          });
          releaseWorkbenchWrap.querySelector('[data-release-confirm]')?.addEventListener('click', async () => {
            const payload = collectPayload();
            const button = releaseWorkbenchWrap.querySelector('[data-release-confirm]');
            button.disabled = true;
            if (msg) msg.textContent = '正在发布模型...';
            try {
              await ctx.post('/models/release', payload);
              ctx.toast('模型已发布');
              await loadModels();
              await openModelTimeline(modelId);
              await openModelReadiness(modelId, payload);
              await openModelReleaseWorkbench(modelId, payload);
            } catch (error) {
              if (msg) msg.textContent = error.message || '模型发布失败';
              ctx.toast(error.message || '模型发布失败', 'error');
            } finally {
              button.disabled = false;
            }
          });
          return workbench;
        } catch (error) {
          releaseWorkbenchWrap.innerHTML = renderError(error.message || '发布工作台加载失败');
          throw error;
        }
      }

      async function loadTrainingJobs() {
        if (!canViewTrainingJob || !trainingJobsWrap) return;
        trainingJobsWrap.innerHTML = renderLoading();
        try {
          const rows = await ctx.get('/training/jobs');
          if (!rows.length) {
            trainingJobsWrap.innerHTML = renderEmpty('暂无训练作业，可在右侧直接创建一条训练 / 微调作业');
            return;
          }
          trainingJobsWrap.innerHTML = `
            <ul class="compact-list">
              ${rows.slice(0, 12).map((row) => `
                <li>
                  <strong>${esc(row.job_code)}</strong>
                  <span>${esc(enumText('training_kind', row.training_kind))} · ${esc(enumText('training_status', row.status))} · 训练集=${esc(row.asset_count ?? 0)} · 验证集=${esc(row.validation_asset_count ?? 0)} · 待验证模型=${esc(row.candidate_model?.id || '-')}</span>
                </li>
              `).join('')}
            </ul>
          `;
        } catch (error) {
          trainingJobsWrap.innerHTML = renderError(error.message);
        }
      }

      function filteredModels(rows) {
        const q = String(modelListFilters.q || '').trim().toLowerCase();
        return (rows || []).filter((row) => {
          if (modelListFilters.status && row.status !== modelListFilters.status) return false;
          const sourceType = String((row.platform_meta || {}).model_source_type || '').trim();
          if (modelListFilters.source && sourceType !== modelListFilters.source) return false;
          if (!q) return true;
          const haystack = [
            row.model_code,
            row.version,
            row.plugin_name,
            row.task_type,
            row.owner_tenant_name,
            row.owner_tenant_code,
            sourceType,
          ]
            .map((item) => String(item || '').toLowerCase())
            .join(' ');
          return haystack.includes(q);
        });
      }

      function renderModelsTable(rows) {
        const filtered = filteredModels(rows);
        if (modelListMeta) modelListMeta.textContent = `显示 ${filtered.length} / ${rows.length} 个模型`;
        if (!filtered.length) {
          modelsWrap.innerHTML = renderEmpty('当前筛选条件下没有模型');
          return;
        }
        modelsWrap.innerHTML = `
          <div class="selection-grid">
            ${filtered.map((row) => {
              const isActive = (activeModelId || requestedFocusModelId) === row.id;
              const sourceType = enumText('model_source_type', (row.platform_meta || {}).model_source_type || '-');
              const validationDecision = row.validation_report?.decision || '待验证';
              const riskDecision = row.latest_release_risk_summary?.decision || '待评估';
              return `
                <article data-model-row="${esc(row.id)}" class="selection-card ${isActive ? 'selected active-row' : ''}">
                  <div class="selection-card-head selection-card-head--stack">
                    <div class="selection-card-title">
                      <strong>${esc(row.model_code)}</strong>
                      <span class="selection-card-subtitle">${esc(row.version)}</span>
                    </div>
                    <div class="quick-review-statuses">
                      <span class="badge">${esc(enumText('model_status', row.status))}</span>
                      ${row.validation_report?.decision ? `<span class="badge">${esc(validationDecision)}</span>` : ''}
                    </div>
                  </div>
                  <div class="selection-card-meta selection-card-meta--compact">
                    <span>来源</span><strong>${esc(sourceType)}</strong>
                    <span>风险</span><strong>${esc(riskDecision)}</strong>
                    <span>任务类型</span><strong>${esc(row.task_type || row.plugin_name || '-')}</strong>
                    <span>租户</span><strong>${esc(row.owner_tenant_name || row.owner_tenant_code || '-')}</strong>
                    <span>摘要</span><strong class="mono">${esc(truncateMiddle(row.model_hash || '-', 8, 6))}</strong>
                  </div>
                  <div class="row-actions">
                    <button class="ghost" data-model-timeline="${esc(row.id)}">时间线</button>
                    <button class="primary" data-model-readiness="${esc(row.id)}">${isActive ? '当前查看评估' : '查看评估'}</button>
                    ${(canApprove && row.status === 'SUBMITTED') || (canRelease && ['APPROVED', 'RELEASED'].includes(row.status))
                      ? `
                          <details class="inline-details">
                            <summary>更多操作</summary>
                            <div class="details-panel action-panel">
                              ${canApprove && row.status === 'SUBMITTED' ? `<button class="ghost" data-model-approve="${esc(row.id)}">审批工作台</button>` : ''}
                              ${canRelease && ['APPROVED', 'RELEASED'].includes(row.status) ? `<button class="ghost" data-model-release="${esc(row.id)}">发布工作台</button>` : ''}
                            </div>
                          </details>
                        `
                      : ''}
                  </div>
                  <details class="inline-details">
                    <summary>技术详情</summary>
                    <div class="details-panel">
                      <div class="selection-card-meta selection-card-meta--compact">
                        <span>模型编号</span><strong class="mono">${esc(row.id)}</strong>
                        <span>插件名称</span><strong>${esc(row.plugin_name || '-')}</strong>
                        <span>任务类型</span><strong>${esc(row.task_type || '-')}</strong>
                        <span>模型摘要</span><strong class="mono">${esc(row.model_hash || '-')}</strong>
                      </div>
                    </div>
                  </details>
                </article>
              `;
            }).join('')}
          </div>
        `;

        modelsWrap.querySelectorAll('[data-model-timeline]').forEach((btn) => {
          btn.addEventListener('click', async () => {
            const modelId = btn.getAttribute('data-model-timeline');
            setModelPanel('governance');
            setModelGovernancePanel('timeline');
            await openModelTimeline(modelId);
          });
        });

        modelsWrap.querySelectorAll('[data-model-readiness]').forEach((btn) => {
          btn.addEventListener('click', async () => {
            const modelId = btn.getAttribute('data-model-readiness');
            try {
              setModelPanel('governance');
              setModelGovernancePanel('timeline');
              await openModelReadiness(modelId);
            } catch (error) {
              ctx.toast(error.message || '模型评估失败', 'error');
            }
          });
        });

        modelsWrap.querySelectorAll('[data-model-approve]').forEach((btn) => {
          btn.addEventListener('click', async () => {
            const modelId = btn.getAttribute('data-model-approve');
            try {
              setModelPanel('governance');
              setModelGovernancePanel('approval');
              await openModelReadiness(modelId);
              await openModelApprovalWorkbench(modelId);
              approvalWorkbenchWrap?.scrollIntoView({ block: 'center', behavior: 'smooth' });
            } catch (error) {
              ctx.toast(error.message || '审批工作台加载失败', 'error');
            }
          });
        });

        modelsWrap.querySelectorAll('[data-model-release]').forEach((btn) => {
          btn.addEventListener('click', async () => {
            const modelId = btn.getAttribute('data-model-release');
            try {
              setModelPanel('governance');
              setModelGovernancePanel('release');
              await openModelReleaseWorkbench(modelId);
              releaseWorkbenchWrap?.scrollIntoView({ block: 'center', behavior: 'smooth' });
            } catch (error) {
              ctx.toast(error.message || '发布工作台加载失败', 'error');
            }
          });
        });
        renderModelWorkbenchOverview();
      }

      async function loadModels() {
        modelsWrap.innerHTML = renderLoading('加载模型列表...');
        try {
          const rows = await ctx.get('/models');
          const visibleRows = filterBusinessModels(rows || []);
          cachedModels = visibleRows;
          if (!visibleRows.length) {
            modelsWrap.innerHTML = renderEmpty((rows || []).length ? '当前只有测试/占位模型，已自动隐藏' : '暂无模型，可先提交一个模型包，或等待供应商交付候选模型');
            activeModelId = '';
            renderModelWorkbenchOverview();
            return;
          }
          if (!activeModelId || !visibleRows.some((row) => row.id === activeModelId)) {
            activeModelId = requestedFocusModelId && visibleRows.some((row) => row.id === requestedFocusModelId)
              ? requestedFocusModelId
              : visibleRows[0].id;
          }
          renderModelsTable(visibleRows);

          if (requestedFocusModelId && visibleRows.some((row) => row.id === requestedFocusModelId)) {
            const focusRow = modelsWrap.querySelector(`[data-model-row="${requestedFocusModelId}"]`);
            focusRow?.scrollIntoView({ block: 'center', behavior: 'smooth' });
            if (requestedOpenModelTimeline) {
              await openModelTimeline(requestedFocusModelId);
            }
            await openModelReadiness(requestedFocusModelId);
            if (canApprove && visibleRows.find((row) => row.id === requestedFocusModelId)?.status === 'SUBMITTED') {
              await openModelApprovalWorkbench(requestedFocusModelId);
            }
            if (canRelease && ['APPROVED', 'RELEASED'].includes(visibleRows.find((row) => row.id === requestedFocusModelId)?.status || '')) {
              await openModelReleaseWorkbench(requestedFocusModelId);
            }
          } else if (activeModelId && visibleRows.some((row) => row.id === activeModelId)) {
            await openModelReadiness(activeModelId);
            if (activeApprovalModelId && activeApprovalModelId === activeModelId) {
              await openModelApprovalWorkbench(activeApprovalModelId);
            }
            if (activeReleaseModelId && activeReleaseModelId === activeModelId) {
              await openModelReleaseWorkbench(activeReleaseModelId);
            }
          }
          localStorage.removeItem(STORAGE_KEYS.focusModelId);
          localStorage.removeItem(STORAGE_KEYS.focusModelTimeline);
        } catch (error) {
          modelsWrap.innerHTML = renderError(error.message);
        }
      }

      registerForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const submitBtn = registerForm.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        registerMsg.textContent = '';
        try {
          const formData = new FormData(registerForm);
          const created = await ctx.postForm('/models/register', formData);
          registerMsg.textContent = `提交成功：${created.model_code}:${created.version}`;
          registerResult.innerHTML = renderInfoPanel(
            '模型提交结果',
            [
              { label: '模型编号', value: created.id, mono: true },
              { label: '模型名称', value: created.model_code },
              { label: '版本', value: created.version },
              { label: '状态', value: enumText('model_status', created.status || 'SUBMITTED') },
              { label: '插件名称', value: created.plugin_name || '-' },
              { label: '模型类型', value: enumText('model_type', created.model_type || '-') },
            ],
            `
              <div class="row-actions">
                <button class="ghost" type="button" id="copyModelIdBtn">复制模型编号</button>
                <button class="ghost" type="button" id="openModelTimelineBtn">查看时间线</button>
                <button class="primary" type="button" id="openModelReadinessBtn">查看评估</button>
              </div>
            `,
          );
          root.querySelector('#copyModelIdBtn')?.addEventListener('click', async () => {
            try {
              await navigator.clipboard.writeText(String(created.id || ''));
              ctx.toast('模型ID已复制');
            } catch {
              ctx.toast(`模型ID: ${created.id}`);
            }
          });
          root.querySelector('#openModelTimelineBtn')?.addEventListener('click', async () => {
            setModelPanel('governance');
            setModelGovernancePanel('timeline');
            await openModelTimeline(created.id);
          });
          root.querySelector('#openModelReadinessBtn')?.addEventListener('click', async () => {
            try {
              setModelPanel('governance');
              setModelGovernancePanel('timeline');
              await openModelReadiness(created.id);
            } catch (error) {
              ctx.toast(error.message || '模型评估失败', 'error');
            }
          });
          ctx.toast('模型提交成功');
          registerForm.reset();
          setModelPanel('overview');
          await loadModels();
        } catch (error) {
          registerMsg.textContent = error.message || '提交失败';
        } finally {
          submitBtn.disabled = false;
        }
      });

      trainingJobForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        trainingJobMsg.textContent = '';
        try {
          const fd = new FormData(trainingJobForm);
          const payload = {
            training_kind: fd.get('training_kind') || 'finetune',
            asset_ids: splitCsv(fd.get('asset_ids')),
            validation_asset_ids: splitCsv(fd.get('validation_asset_ids')),
            base_model_id: String(fd.get('base_model_id') || '').trim() || null,
            target_model_code: String(fd.get('target_model_code') || '').trim(),
            target_version: String(fd.get('target_version') || '').trim(),
            worker_selector: {},
            spec: {},
          };
          const result = await ctx.post('/training/jobs', payload);
          trainingJobMsg.textContent = `创建成功：${result.job_code}`;
          ctx.toast('训练作业已创建');
          await loadTrainingJobs();
        } catch (error) {
          trainingJobMsg.textContent = error.message || '创建失败';
        }
      });

      modelListSearch?.addEventListener('input', () => {
        modelListFilters.q = modelListSearch.value || '';
        renderModelsTable(cachedModels);
      });
      modelStatusFilter?.addEventListener('change', () => {
        modelListFilters.status = modelStatusFilter.value || '';
        renderModelsTable(cachedModels);
      });
      modelSourceFilter?.addEventListener('change', () => {
        modelListFilters.source = modelSourceFilter.value || '';
        renderModelsTable(cachedModels);
      });

      modelPanelTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setModelPanel(button.getAttribute('data-model-panel-tab') || 'overview');
        });
      });
      modelOverviewTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setModelOverviewPanel(button.getAttribute('data-model-overview-tab') || 'workbench');
        });
      });
      modelBuildTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setModelBuildPanel(button.getAttribute('data-model-build-tab') || 'submit');
        });
      });
      modelGovernanceTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setModelGovernancePanel(button.getAttribute('data-model-governance-tab') || 'timeline');
        });
      });

      setModelPanel(activeModelPanel);
      await Promise.all([loadModels(), loadTrainingJobs()]);
      if (cachedModels.length && trainingJobForm && !trainingJobForm.querySelector('[data-helper]')) {
        const hint = document.createElement('div');
        hint.className = 'hint';
        hint.setAttribute('data-helper', 'true');
        hint.textContent = `可选基础算法编号示例：${cachedModels[0].id}`;
        trainingJobForm.appendChild(hint);
      }
    },
  };
}

function pageTraining(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const role = primaryRole(ctx.state.user);
  const canCreateTrainingJob = hasPermission(ctx.state, 'training.job.create');
  const canManageWorkers = hasPermission(ctx.state, 'training.worker.manage');
  const canCreateTask = hasPermission(ctx.state, 'task.create');
  const heroSummary = role.startsWith('platform_')
    ? '统一查看训练作业、训练机器健康和待验证模型生成状态，保证训练链路始终处于平台控制面内。'
    : '创建训练作业、查看训练机器健康，并把训练成功的新模型继续送入验证和审批。';
  return {
    html: `
      ${renderPageHero({
        eyebrow: '训练与微调',
        title: '训练中心',
        summary: heroSummary,
        highlights: ['先确认训练机器在线', '预设驱动创建训练', '训练成功后直达验证'],
        actions: [
          { path: 'training/car-number-labeling', label: '打开车号文本复核', primary: true },
          { path: 'models', label: '查看模型审批' },
        ],
      })}
      <section class="card">
        <h3>训练工作台概览</h3>
        <div id="trainingWorkbenchOverviewWrap">${renderEmpty('选择一条训练作业后，这里会汇总当前状态、训练机器健康和推荐下一步动作。')}</div>
      </section>
      <section class="card">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-training-panel-tab="overview">训练总览</button>
          <button class="ghost" type="button" data-training-panel-tab="create">创建训练</button>
          <button class="ghost" type="button" data-training-panel-tab="workers">训练机器</button>
        </div>
        <div id="trainingPanelMeta" class="hint">默认先看训练总览；创建和训练机器按工作区展开。</div>
      </section>
      <section class="card" data-training-panel="overview">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-training-overview-tab="alerts">运行告警</button>
          <button class="ghost" type="button" data-training-overview-tab="jobs">训练作业</button>
          <button class="ghost" type="button" data-training-overview-tab="summary">训练结果摘要</button>
        </div>
        <div id="trainingOverviewPanelMeta" class="hint">默认先看运行告警；需要追踪作业或查看训练结果摘要时再切到对应分区。</div>
      </section>
      <section class="card" data-training-panel="overview" data-training-overview-panel="alerts" hidden>
        <h3>运行告警</h3>
        <div id="trainingRuntimeAlertWrap">${renderLoading('加载训练运行健康状态...')}</div>
      </section>
      <section class="grid-two" data-training-panel="overview" data-training-overview-panel="jobs" hidden>
        <section class="card">
          <h3>训练作业</h3>
          <form id="trainingFilterForm" class="inline-form">
            <select name="status">
              <option value="">全部状态</option>
              <option value="PENDING">${enumText('training_status', 'PENDING')}</option>
              <option value="DISPATCHED">${enumText('training_status', 'DISPATCHED')}</option>
              <option value="RUNNING">${enumText('training_status', 'RUNNING')}</option>
              <option value="SUCCEEDED">${enumText('training_status', 'SUCCEEDED')}</option>
              <option value="FAILED">${enumText('training_status', 'FAILED')}</option>
              <option value="CANCELLED">${enumText('training_status', 'CANCELLED')}</option>
            </select>
            <select name="training_kind">
              <option value="">全部类型</option>
              <option value="finetune">${enumText('training_kind', 'finetune')}</option>
              <option value="train">${enumText('training_kind', 'train')}</option>
              <option value="evaluate">${enumText('training_kind', 'evaluate')}</option>
            </select>
          <button class="ghost" type="submit">筛选</button>
          </form>
          <div id="trainingJobsTableWrap">${renderLoading('加载训练作业...')}</div>
        </section>
      </section>
      <section class="card" data-training-panel="overview" data-training-overview-panel="summary" hidden>
        <h3>训练结果摘要</h3>
        <p class="hint">把基础模型、数据规模、关键指标和后续动作放在一屏里，方便快速判断这轮训练是否值得进入审批、发布或继续迭代。</p>
        <div id="trainingRunSummaryWrap">${renderLoading('加载训练摘要...')}</div>
      </section>
      <section class="card" data-training-panel="workers" hidden>
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-training-workers-tab="overview">机器总览</button>
          <button class="ghost" type="button" data-training-workers-tab="manage">登记与清理</button>
        </div>
        <div id="trainingWorkersPanelMeta" class="hint">默认先看训练机器状态和可用节点；需要新增、刷新或清理历史异常时再进入登记与清理。</div>
      </section>
      <section class="card" data-training-panel="workers" data-training-workers-panel="overview" hidden>
        <h3>训练机器</h3>
        <div id="trainingWorkersWrap">${renderLoading('加载训练机器...')}</div>
      </section>
      <section class="card" data-training-panel="workers" data-training-workers-panel="manage" hidden>
        <h3>登记与清理</h3>
        ${
          canManageWorkers
            ? `
              <form id="registerWorkerForm" class="form-grid">
                <label>训练机器编号</label><input name="worker_code" placeholder="training-node-01" required />
                <label>显示名称</label><input name="name" placeholder="训练机器 01" required />
                <label>机器地址</label><input name="host" placeholder="10.0.0.31" />
                <label>状态</label>
                <select name="status">
                  <option value="ACTIVE">${enumText('worker_status', 'ACTIVE')}</option>
                  <option value="INACTIVE">${enumText('worker_status', 'INACTIVE')}</option>
                  <option value="UNHEALTHY">${enumText('worker_status', 'UNHEALTHY')}</option>
                </select>
                <label>机器标签（JSON）</label><textarea name="labels" rows="2">{}</textarea>
                <label>机器资源（JSON）</label><textarea name="resources" rows="2">{}</textarea>
                <button class="primary" type="submit">保存训练机器</button>
                <div id="registerWorkerMsg" class="hint"></div>
              </form>
              <div class="hint">历史异常训练机器的清理入口保留在“机器总览”里，只在确实需要时操作，避免误删正在排障的节点记录。</div>
            `
            : renderEmpty('当前角色无训练机器管理权限')
        }
      </section>
      ${
        canCreateTrainingJob
          ? `
            <section class="card" data-training-panel="create" hidden>
              <div class="workspace-switcher">
                <button class="ghost" type="button" data-training-create-tab="prep">准备训练</button>
                <button class="ghost" type="button" data-training-create-tab="dataset">数据集版本</button>
                <button class="ghost" type="button" data-training-create-tab="form">创建训练</button>
              </div>
              <div id="trainingCreatePanelMeta" class="hint">默认先准备基础算法和训练机器；确认数据集后再进入创建训练。</div>
            </section>
            <section class="card" data-training-panel="create" data-training-create-panel="prep" hidden>
              <div class="workspace-switcher">
                <button class="ghost" type="button" data-training-prep-tab="model">选择算法</button>
                <button class="ghost" type="button" data-training-prep-tab="worker">选择训练机器</button>
              </div>
              <div id="trainingPrepPanelMeta" class="hint">默认先选择基础算法；确认算法后再切到训练机器。</div>
              <section class="lane-card" data-training-prep-panel="model" hidden>
                <h4>供应商算法库</h4>
                <p class="hint">从已发布给当前租户的算法里直接选一个基础模型，系统会自动带入供应商归属信息。</p>
                <div class="section-toolbar compact">
                  <input id="trainingModelSearch" placeholder="搜索算法 / 供应商 / 任务类型" />
                  <div id="trainingModelMeta" class="hint"></div>
                </div>
                <div id="trainingModelLibrary">${renderLoading('加载供应商算法...')}</div>
              </section>
              <section class="lane-card" data-training-prep-panel="worker" hidden>
                <h4>训练机池</h4>
                <p class="hint">选择要执行训练的机器。可按训练机名称、地址或 IP 精确派发到指定节点。</p>
                <div class="section-toolbar compact">
                  <input id="trainingWorkerSearch" placeholder="搜索训练机名称 / 地址 / 状态" />
                  <label class="checkbox-row"><input id="trainingWorkerShowHistory" type="checkbox" /> 显示历史异常</label>
                  <div id="trainingWorkerMeta" class="hint"></div>
                </div>
                <div id="trainingWorkerPool">${renderLoading('加载训练机...')}</div>
              </section>
            </section>
            <section class="card" data-training-panel="create" data-training-create-panel="dataset" hidden>
              <section class="lane-card">
                <h4>训练数据集版本</h4>
                <p class="hint">快速识别导出的数据集会自动形成版本记录。可直接把某个版本放入训练集或验证集，不必手工回填资产编号。</p>
                <div class="section-toolbar compact">
                  <input id="trainingDatasetSearch" placeholder="搜索数据集标签 / 版本说明 / 来源" />
                  <select id="trainingDatasetPurposeFilter">
                    <option value="">全部用途</option>
                    <option value="training">${enumText('asset_purpose', 'training')}</option>
                    <option value="validation">${enumText('asset_purpose', 'validation')}</option>
                    <option value="finetune">${enumText('asset_purpose', 'finetune')}</option>
                  </select>
                  <label class="checkbox-row"><input id="trainingDatasetRecommendedOnly" type="checkbox" /> 仅看推荐</label>
                  <label class="checkbox-row"><input id="trainingDatasetShowHistory" type="checkbox" /> 显示历史</label>
                  <div id="trainingDatasetMeta" class="hint"></div>
                </div>
                <div id="trainingDatasetVersionLibrary">${renderLoading('加载数据集版本...')}</div>
                <div id="trainingDatasetCompareWrap" class="selection-summary">${renderEmpty('选择某个数据集版本后，可在这里查看与上一版的差异，或设为推荐训练集。')}</div>
                <div id="trainingDatasetRollbackWrap" class="selection-summary">${renderEmpty('需要回滚某个版本时，点对应卡片里的“回滚为新版本”，这里会出现确认区。')}</div>
                <div id="trainingDatasetPreviewWrap" class="selection-summary">${renderEmpty('选择某个数据集版本后，可在这里查看样本摘要、标签和复核状态。')}</div>
              </section>
            </section>
            <section class="card" data-training-panel="create" data-training-create-panel="form" hidden>
              <form id="trainingCreateForm" class="form-grid">
                <div class="grid-two">
                  <div class="form-grid">
                    <label>训练类型</label>
                    <select name="training_kind">
                      <option value="finetune">${enumText('training_kind', 'finetune')}</option>
                      <option value="train">${enumText('training_kind', 'train')}</option>
                      <option value="evaluate">${enumText('training_kind', 'evaluate')}</option>
                    </select>
                    <label>训练数据（资产编号，可多个）</label>
                    <input name="asset_ids" list="trainingAssetsDatalist" placeholder="资产编号-1, 资产编号-2" />
                    <div class="hint">训练/验证资产可以为空，也可以引用多个单文件资产或多个 ZIP 数据集包。</div>
                    <label>验证数据（资产编号，可多个）</label>
                    <input name="validation_asset_ids" list="trainingAssetsDatalist" placeholder="资产编号-3" />
                    <label>训练后模型名称</label>
                    <input name="target_model_code" placeholder="railway-defect-ft" required />
                    <label>训练后版本号</label>
                    <input name="target_version" placeholder="v20260306.1" required />
                    <label>训练预设</label>
                    <select id="trainingPresetSelect" name="training_preset">
                      <option value="car_number_balanced">车号 OCR · 标准微调</option>
                      <option value="car_number_fast">车号 OCR · 快速验证</option>
                      <option value="car_number_eval">车号 OCR · 验证评估</option>
                      <option value="custom">自定义</option>
                    </select>
                    <div class="hint">默认按预设自动生成训练参数。只有确实需要覆盖时，再展开下面的高级 JSON。</div>
                  </div>
                  <div class="form-grid">
                    <label>基础算法（可选）</label>
                    <input name="base_model_id" list="trainingModelsDatalist" placeholder="模型编号" />
                    <div class="hint">建议先从上方“供应商算法库”选择，避免手工输入错误模型编号。</div>
                    <details>
                      <summary>高级参数与训练机器（可选）</summary>
                      <div class="form-grid">
                        <label>训练机名称（可选）</label>
                        <input name="worker_code" list="trainingWorkersCodeDatalist" placeholder="默认自动选择在线训练机器" />
                        <label>训练机地址（可选）</label>
                        <input name="worker_host" list="trainingWorkersHostDatalist" placeholder="可留空，由系统自动补在线训练机器" />
                        <label>训练参数（JSON，可选）</label>
                        <textarea name="spec" rows="4">{}</textarea>
                        <div class="hint">留空时按上面的训练预设自动生成。只有你要覆盖 epochs / learning_rate / preprocessing 时才需要改。</div>
                      </div>
                    </details>
                  </div>
                </div>
                <datalist id="trainingAssetsDatalist"></datalist>
                <datalist id="trainingModelsDatalist"></datalist>
                <datalist id="trainingWorkersCodeDatalist"></datalist>
                <datalist id="trainingWorkersHostDatalist"></datalist>
                <div id="trainingSelectionSummary" class="selection-summary">
                  <strong>当前选择</strong>
                  <span>尚未选择供应商算法和训练机，可手工输入，也可点击上方卡片快速填入。</span>
                </div>
                <button class="primary" type="submit">创建训练作业</button>
                <div id="trainingCreateMsg" class="hint"></div>
                <div id="trainingCreateResultWrap">${renderEmpty('创建成功后，这里会直接给出下一步动作。')}</div>
              </form>
            </section>
          `
          : ''
      }
    `,
    async mount(root) {
      bindPageNavButtons(root, ctx);
      const jobsWrap = root.querySelector('#trainingJobsTableWrap');
      const workersWrap = root.querySelector('#trainingWorkersWrap');
      const filterForm = root.querySelector('#trainingFilterForm');
      const registerWorkerForm = root.querySelector('#registerWorkerForm');
      const registerWorkerMsg = root.querySelector('#registerWorkerMsg');
      const createForm = root.querySelector('#trainingCreateForm');
      const createMsg = root.querySelector('#trainingCreateMsg');
      const createResultWrap = root.querySelector('#trainingCreateResultWrap');
      const trainingPanelMeta = root.querySelector('#trainingPanelMeta');
      const trainingPanelTabs = [...root.querySelectorAll('[data-training-panel-tab]')];
      const trainingPanels = [...root.querySelectorAll('[data-training-panel]')];
      const trainingOverviewPanelMeta = root.querySelector('#trainingOverviewPanelMeta');
      const trainingOverviewTabs = [...root.querySelectorAll('[data-training-overview-tab]')];
      const trainingOverviewPanels = [...root.querySelectorAll('[data-training-overview-panel]')];
      const trainingPrepPanelMeta = root.querySelector('#trainingPrepPanelMeta');
      const trainingPrepTabs = [...root.querySelectorAll('[data-training-prep-tab]')];
      const trainingPrepPanels = [...root.querySelectorAll('[data-training-prep-panel]')];
      const trainingWorkersPanelMeta = root.querySelector('#trainingWorkersPanelMeta');
      const trainingWorkersTabs = [...root.querySelectorAll('[data-training-workers-tab]')];
      const trainingWorkersPanels = [...root.querySelectorAll('[data-training-workers-panel]')];
      const trainingCreatePanelMeta = root.querySelector('#trainingCreatePanelMeta');
      const trainingCreateTabs = [...root.querySelectorAll('[data-training-create-tab]')];
      const trainingCreatePanels = [...root.querySelectorAll('[data-training-create-panel]')];
      const trainingRuntimeAlertWrap = root.querySelector('#trainingRuntimeAlertWrap');
      const trainingWorkbenchOverviewWrap = root.querySelector('#trainingWorkbenchOverviewWrap');
      const trainingRunSummaryWrap = root.querySelector('#trainingRunSummaryWrap');
      const assetsDatalist = root.querySelector('#trainingAssetsDatalist');
      const modelsDatalist = root.querySelector('#trainingModelsDatalist');
      const workerCodesDatalist = root.querySelector('#trainingWorkersCodeDatalist');
      const workerHostsDatalist = root.querySelector('#trainingWorkersHostDatalist');
      const modelLibrary = root.querySelector('#trainingModelLibrary');
      const workerPool = root.querySelector('#trainingWorkerPool');
      const datasetVersionLibrary = root.querySelector('#trainingDatasetVersionLibrary');
      const trainingModelSearch = root.querySelector('#trainingModelSearch');
      const trainingModelMeta = root.querySelector('#trainingModelMeta');
      const trainingWorkerSearch = root.querySelector('#trainingWorkerSearch');
      const trainingWorkerShowHistory = root.querySelector('#trainingWorkerShowHistory');
      const trainingWorkerMeta = root.querySelector('#trainingWorkerMeta');
      const trainingDatasetSearch = root.querySelector('#trainingDatasetSearch');
      const trainingDatasetPurposeFilter = root.querySelector('#trainingDatasetPurposeFilter');
      const trainingDatasetRecommendedOnly = root.querySelector('#trainingDatasetRecommendedOnly');
      const trainingDatasetShowHistory = root.querySelector('#trainingDatasetShowHistory');
      const trainingDatasetMeta = root.querySelector('#trainingDatasetMeta');
      const datasetCompareWrap = root.querySelector('#trainingDatasetCompareWrap');
      const datasetRollbackWrap = root.querySelector('#trainingDatasetRollbackWrap');
      const datasetPreviewWrap = root.querySelector('#trainingDatasetPreviewWrap');
      const selectionSummary = root.querySelector('#trainingSelectionSummary');
      const prefillTrainingAssetIds = localStorage.getItem(STORAGE_KEYS.prefillTrainingAssetIds);
      const prefillTrainingValidationAssetIds = localStorage.getItem(STORAGE_KEYS.prefillTrainingValidationAssetIds);
      const prefillTrainingDatasetLabel = localStorage.getItem(STORAGE_KEYS.prefillTrainingDatasetLabel);
      let prefillTrainingDatasetVersionId = localStorage.getItem(STORAGE_KEYS.prefillTrainingDatasetVersionId);
      const prefillTrainingTargetModelCode = localStorage.getItem(STORAGE_KEYS.prefillTrainingTargetModelCode);
      const requestedFocusTrainingJobId = localStorage.getItem(STORAGE_KEYS.focusTrainingJobId);
      const assetIdsInput = createForm?.querySelector('input[name="asset_ids"]');
      const validationAssetIdsInput = createForm?.querySelector('input[name="validation_asset_ids"]');
      const baseModelInput = createForm?.querySelector('input[name="base_model_id"]');
      const workerCodeInput = createForm?.querySelector('input[name="worker_code"]');
      const workerHostInput = createForm?.querySelector('input[name="worker_host"]');
      const targetModelCodeInput = createForm?.querySelector('input[name="target_model_code"]');
      const targetVersionInput = createForm?.querySelector('input[name="target_version"]');
      const trainingPresetInput = createForm?.querySelector('#trainingPresetSelect');
      const specInput = createForm?.querySelector('textarea[name="spec"]');
      let assistAssets = [];
      let assistModels = [];
      let assistWorkers = [];
      let assistDatasetVersions = [];
      let activeDatasetCompare = null;
      let activeDatasetCompareVersionId = '';
      let activeDatasetRollback = null;
      let datasetCompareFilters = defaultDatasetCompareFilters();
      let activeDatasetPreview = null;
      let datasetCompareBlobUrls = [];
      let datasetPreviewBlobUrls = [];
      let cachedTrainingJobs = [];
      let activeTrainingJobId = '';
      let activeTrainingPanel = 'overview';
      let activeTrainingOverviewPanel = 'alerts';
      let activeTrainingCreatePanel = 'prep';
      let activeTrainingPrepPanel = 'model';
      let activeTrainingWorkersPanel = 'overview';
      let lastAutoSpecSerialized = '{}';
      const trainingLibraryFilters = {
        modelQuery: '',
        workerQuery: '',
        workerShowHistory: false,
        datasetQuery: '',
        datasetPurpose: '',
        datasetRecommendedOnly: false,
        datasetShowHistory: false,
      };

      const TRAINING_SPEC_PRESETS = {
        car_number_balanced: {
          trainer: 'car_number_ocr_local',
          epochs: 3,
          learning_rate: 0.0005,
          batch_size: 16,
          preprocessing: { resize: [320, 96] },
          augmentations: { grayscale_jitter: 0.08, contrast_jitter: 0.1 },
        },
        car_number_fast: {
          trainer: 'car_number_ocr_local',
          epochs: 1,
          learning_rate: 0.001,
          batch_size: 16,
          preprocessing: { resize: [320, 96] },
        },
        car_number_eval: {
          trainer: 'car_number_ocr_local',
          mode: 'evaluate',
          epochs: 1,
          learning_rate: 0.0001,
          batch_size: 8,
          preprocessing: { resize: [320, 96] },
        },
      };

      function setTrainingCreatePanel(panel) {
        activeTrainingCreatePanel = ['prep', 'dataset', 'form'].includes(panel) ? panel : 'prep';
        trainingCreatePanels.forEach((section) => {
          section.hidden = section.getAttribute('data-training-create-panel') !== activeTrainingCreatePanel || activeTrainingPanel !== 'create';
        });
        trainingCreateTabs.forEach((button) => {
          const active = button.getAttribute('data-training-create-tab') === activeTrainingCreatePanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (trainingCreatePanelMeta) {
          trainingCreatePanelMeta.textContent = activeTrainingCreatePanel === 'prep'
            ? '先准备基础算法和训练机器，再继续看数据集或创建训练。'
            : activeTrainingCreatePanel === 'dataset'
              ? '集中选择训练数据集版本，再决定推荐、回滚或预览样本。'
              : '最后统一确认训练参数、资产和训练机器，再创建训练作业。';
        }
        if (activeTrainingCreatePanel === 'prep') setTrainingPrepPanel(activeTrainingPrepPanel);
      }

      function setTrainingPrepPanel(panel) {
        activeTrainingPrepPanel = ['model', 'worker'].includes(panel) ? panel : 'model';
        trainingPrepPanels.forEach((section) => {
          section.hidden = section.getAttribute('data-training-prep-panel') !== activeTrainingPrepPanel || activeTrainingPanel !== 'create' || activeTrainingCreatePanel !== 'prep';
        });
        trainingPrepTabs.forEach((button) => {
          const active = button.getAttribute('data-training-prep-tab') === activeTrainingPrepPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (trainingPrepPanelMeta) {
          trainingPrepPanelMeta.textContent = activeTrainingPrepPanel === 'model'
            ? '先选基础算法，确认供应商来源和任务类型。'
            : '算法确认后，再挑训练机器并检查历史异常。';
        }
      }

      function setTrainingOverviewPanel(panel) {
        activeTrainingOverviewPanel = ['alerts', 'jobs', 'summary'].includes(panel) ? panel : 'alerts';
        trainingOverviewPanels.forEach((section) => {
          section.hidden = section.getAttribute('data-training-overview-panel') !== activeTrainingOverviewPanel || activeTrainingPanel !== 'overview';
        });
        trainingOverviewTabs.forEach((button) => {
          const active = button.getAttribute('data-training-overview-tab') === activeTrainingOverviewPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (trainingOverviewPanelMeta) {
          trainingOverviewPanelMeta.textContent = activeTrainingOverviewPanel === 'alerts'
            ? '先看当前是否有超时作业或训练机器异常。'
            : activeTrainingOverviewPanel === 'jobs'
              ? '在这里追踪训练作业状态、改派、取消或继续查看。'
              : '这里汇总训练结果、候选模型和下一步动作。';
        }
      }

      function setTrainingWorkersPanel(panel) {
        activeTrainingWorkersPanel = ['overview', 'manage'].includes(panel) ? panel : 'overview';
        trainingWorkersPanels.forEach((section) => {
          section.hidden = section.getAttribute('data-training-workers-panel') !== activeTrainingWorkersPanel || activeTrainingPanel !== 'workers';
        });
        trainingWorkersTabs.forEach((button) => {
          const active = button.getAttribute('data-training-workers-tab') === activeTrainingWorkersPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (trainingWorkersPanelMeta) {
          trainingWorkersPanelMeta.textContent = activeTrainingWorkersPanel === 'overview'
            ? '先看训练机器健康、可用节点和历史异常。'
            : '需要新增、刷新或修正训练机器信息时，再进入登记与清理。';
        }
      }

      function setTrainingPanel(panel) {
        activeTrainingPanel = ['overview', 'create', 'workers'].includes(panel) ? panel : 'overview';
        trainingPanels.forEach((section) => {
          const panelName = section.getAttribute('data-training-panel');
          if (panelName !== activeTrainingPanel) {
            section.hidden = true;
            return;
          }
          if (panelName === 'create' && section.hasAttribute('data-training-create-panel')) return;
          if (panelName === 'workers' && section.hasAttribute('data-training-workers-panel')) return;
          section.hidden = false;
        });
        trainingPanelTabs.forEach((button) => {
          const active = button.getAttribute('data-training-panel-tab') === activeTrainingPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (trainingPanelMeta) {
          trainingPanelMeta.textContent = activeTrainingPanel === 'overview'
            ? '先看训练作业状态、运行告警和训练摘要。'
            : activeTrainingPanel === 'create'
              ? '把训练参数、数据集和训练机选择集中在一处。'
              : '集中处理训练机器健康、历史异常和节点登记。';
        }
        if (activeTrainingPanel === 'overview') setTrainingOverviewPanel(activeTrainingOverviewPanel);
        if (activeTrainingPanel === 'create') setTrainingCreatePanel(activeTrainingCreatePanel);
        if (activeTrainingPanel === 'workers') setTrainingWorkersPanel(activeTrainingWorkersPanel);
      }

      async function waitForTaskTerminal(taskId, { timeoutMs = 90_000 } = {}) {
        const startedAt = Date.now();
        while (Date.now() - startedAt < timeoutMs) {
          const task = await ctx.get(`/tasks/${taskId}`);
          if (['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(task?.status)) {
            if (task.status !== 'SUCCEEDED') {
              throw new Error(normalizeUiErrorMessage(task.error_message || `任务已结束：${task.status}`));
            }
            return task;
          }
          await new Promise((resolve) => window.setTimeout(resolve, 1200));
        }
        throw new Error('等待验证任务完成超时，请稍后在任务中心查看');
      }

      if (createForm && (prefillTrainingAssetIds || prefillTrainingValidationAssetIds || prefillTrainingDatasetVersionId)) {
        if (assetIdsInput && prefillTrainingAssetIds) assetIdsInput.value = prefillTrainingAssetIds;
        if (validationAssetIdsInput && prefillTrainingValidationAssetIds) validationAssetIdsInput.value = prefillTrainingValidationAssetIds;
        if (targetModelCodeInput && prefillTrainingTargetModelCode) targetModelCodeInput.value = prefillTrainingTargetModelCode;
        if (createMsg) {
          createMsg.textContent = `已预填 OCR 文本训练资产：train ${prefillTrainingAssetIds || '-'} / validation ${prefillTrainingValidationAssetIds || '-'}${prefillTrainingDatasetLabel ? ` · ${prefillTrainingDatasetLabel}` : ''}${prefillTrainingDatasetVersionId ? ` · ${prefillTrainingDatasetVersionId}` : ''}。这一步还没有创建训练作业，确认参数后请点击“创建训练作业”。`;
        }
        localStorage.removeItem(STORAGE_KEYS.prefillTrainingAssetIds);
        localStorage.removeItem(STORAGE_KEYS.prefillTrainingValidationAssetIds);
        localStorage.removeItem(STORAGE_KEYS.prefillTrainingDatasetLabel);
        localStorage.removeItem(STORAGE_KEYS.prefillTrainingDatasetVersionId);
        localStorage.removeItem(STORAGE_KEYS.prefillTrainingTargetModelCode);
        activeTrainingPanel = 'create';
        activeTrainingCreatePanel = prefillTrainingDatasetVersionId ? 'form' : 'prep';
      }

      function pickDefaultTrainingJob(rows) {
        if (!Array.isArray(rows) || !rows.length) return null;
        return (
          rows.find((row) => row.status === 'SUCCEEDED') ||
          rows.find((row) => row.status === 'RUNNING') ||
          rows.find((row) => row.status === 'DISPATCHED') ||
          rows[0]
        );
      }

      function getSelectedTrainingJob() {
        return cachedTrainingJobs.find((row) => row.id === activeTrainingJobId) || null;
      }

      function renderTrainingWorkbenchOverview() {
        if (!trainingWorkbenchOverviewWrap) return;
        const job = getSelectedTrainingJob();
        const activeWorkerCount = assistWorkers.filter((row) => row.status === 'ACTIVE').length;
        const unhealthyWorkerCount = assistWorkers.filter((row) => row.status === 'UNHEALTHY').length;
        if (!job) {
          trainingWorkbenchOverviewWrap.innerHTML = renderWorkbenchOverview({
            title: '等待选择训练作业',
            summary: '先从左侧训练作业列表选择一条运行中的、成功的或刚创建的作业，再决定是否验证候选模型或继续迭代数据。',
            metrics: [
              { label: '在线训练机器', value: activeWorkerCount, note: unhealthyWorkerCount ? `异常 ${unhealthyWorkerCount}` : '心跳正常' },
              { label: '训练作业', value: cachedTrainingJobs.length, note: '当前筛选结果' },
              { label: '推荐下一步', value: '创建训练', note: '也可先打开车号文本复核' },
            ],
            actions: [
              { id: 'training-open-create', label: '去创建训练作业', primary: true },
              { id: 'training-open-review', label: '打开车号文本复核' },
            ],
          });
        } else {
          const actions = [
            { id: 'training-open-summary', label: '查看训练摘要', primary: true },
            { id: 'training-open-review', label: '打开车号文本复核' },
          ];
          if (job.candidate_model?.id) {
            actions.push({ id: 'training-open-candidate-model', label: '查看待验证模型' });
          }
          if (canCreateTask && job.candidate_model?.id) {
            actions.push({ id: 'training-open-validation', label: '直接验证新模型' });
          }
          trainingWorkbenchOverviewWrap.innerHTML = renderWorkbenchOverview({
            title: job.job_code || '训练作业',
            status: enumText('training_status', job.status),
            summary: job.status === 'SUCCEEDED'
              ? '这轮训练已经完成。优先看候选模型和验证入口，再决定是否进入审批。'
              : job.status === 'RUNNING'
                ? '训练正在进行中。先看训练机器健康和训练曲线，避免长时间空跑。'
                : '当前作业仍在排队或等待调度，可继续检查训练机器和数据集配置。',
            metrics: [
              { label: '候选模型', value: job.candidate_model ? `${job.candidate_model.model_code}:${job.candidate_model.version}` : '等待回收', note: job.target_model_code || '目标模型' },
              { label: '执行节点', value: job.assigned_worker_code || '待派发', note: activeWorkerCount ? `在线训练机器 ${activeWorkerCount}` : '暂无在线训练机器' },
              { label: '训练 / 验证', value: `${job.asset_count ?? 0}/${job.validation_asset_count ?? 0}`, note: '资产数量' },
            ],
            actions,
          });
        }
        trainingWorkbenchOverviewWrap.querySelector('[data-workbench-action="training-open-create"]')?.addEventListener('click', () => {
          setTrainingPanel('create');
          setTrainingCreatePanel('form');
          createForm?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        trainingWorkbenchOverviewWrap.querySelector('[data-workbench-action="training-open-review"]')?.addEventListener('click', () => {
          ctx.navigate('training/car-number-labeling');
        });
        trainingWorkbenchOverviewWrap.querySelector('[data-workbench-action="training-open-summary"]')?.addEventListener('click', () => {
          setTrainingPanel('overview');
          setTrainingOverviewPanel('summary');
          trainingRunSummaryWrap?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        trainingWorkbenchOverviewWrap.querySelector('[data-workbench-action="training-open-candidate-model"]')?.addEventListener('click', () => {
          if (!job?.candidate_model?.id) return;
          localStorage.setItem(STORAGE_KEYS.focusModelId, job.candidate_model.id);
          localStorage.setItem(STORAGE_KEYS.focusModelTimeline, '1');
          ctx.navigate('models');
        });
        trainingWorkbenchOverviewWrap.querySelector('[data-workbench-action="training-open-validation"]')?.addEventListener('click', () => {
          if (!job?.candidate_model?.id) return;
          setTrainingPanel('overview');
          setTrainingOverviewPanel('summary');
          trainingRunSummaryWrap?.querySelector('[data-launch-candidate-validation-open]')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
      }

      function compactValue(value) {
        if (value === null || value === undefined || value === '') return '未声明';
        if (Array.isArray(value)) return value.length ? value.join(', ') : '未声明';
        if (typeof value === 'object') {
          const keys = Object.keys(value);
          return keys.length ? keys.map((key) => `${key}=${value[key]}`).join(' · ') : '未声明';
        }
        return String(value);
      }

      function pickSuggestedValidationAsset(candidates = []) {
        const rows = Array.isArray(candidates) ? candidates : [];
        return rows[0]?.id || '';
      }

      function renderDatasetRollbackWorkbench() {
        if (!datasetRollbackWrap) return;
        if (!activeDatasetRollback) {
          datasetRollbackWrap.innerHTML = renderEmpty('需要回滚某个版本时，点对应卡片里的“回滚为新版本”，这里会出现确认区。');
          return;
        }
        datasetRollbackWrap.innerHTML = `
          <div class="result-dataset-workbench">
            <div class="result-panel-head">
              <div>
                <strong>回滚为新版本</strong>
                <p>${esc(`将基于 ${activeDatasetRollback.dataset_label || '-'}:${activeDatasetRollback.version || '-'} 复制出一个新的 ${activeDatasetRollback.asset_purpose || 'training'} 版本，旧版本不会被覆盖。`)}</p>
              </div>
              <span class="badge">${esc(activeDatasetRollback.asset_purpose || 'training')}</span>
            </div>
            <div class="form-grid result-dataset-form">
              <label>
                <span>回滚说明</span>
                <input id="datasetRollbackNote" value="training_page_rollback" placeholder="training_page_rollback" />
              </label>
            </div>
            <div class="row-actions">
              <button class="primary" type="button" data-confirm-dataset-rollback>确认回滚</button>
              <button class="ghost" type="button" data-cancel-dataset-rollback>取消</button>
            </div>
          </div>
        `;
        datasetRollbackWrap.querySelector('[data-cancel-dataset-rollback]')?.addEventListener('click', () => {
          activeDatasetRollback = null;
          renderDatasetRollbackWorkbench();
        });
        datasetRollbackWrap.querySelector('[data-confirm-dataset-rollback]')?.addEventListener('click', async (event) => {
          const button = event.currentTarget;
          const note = String(datasetRollbackWrap.querySelector('#datasetRollbackNote')?.value || '').trim();
          button.disabled = true;
          try {
            const result = await ctx.post(`/assets/dataset-versions/${activeDatasetRollback.id}/rollback`, {
              asset_purpose: activeDatasetRollback.asset_purpose || 'training',
              note: note || null,
            });
            const newVersionId = result.dataset_version?.id || '';
            if (newVersionId) prefillTrainingDatasetVersionId = newVersionId;
            ctx.toast(`已生成回滚版本：${result.dataset_version?.version || '-'}`);
            activeDatasetRollback = null;
            renderDatasetRollbackWorkbench();
            await loadFormAssistData();
            if (newVersionId) {
              await compareWithPreviousDatasetVersion(newVersionId);
              await previewDatasetVersion(newVersionId);
            }
          } catch (error) {
            ctx.toast(error.message || '回滚失败', 'error');
          } finally {
            button.disabled = false;
          }
        });
      }

      function buildTrainingAssetRefs(assetIds) {
        return (Array.isArray(assetIds) ? assetIds : []).map((assetId) => {
          const asset = assistAssets.find((row) => row.id === assetId) || null;
          const version = assistDatasetVersions.find((row) => row.asset_id === assetId) || null;
          return { assetId, asset, version };
        });
      }

      function renderTrainingRuntimeAlerts() {
        if (!trainingRuntimeAlertWrap) return;
        const criticalJobs = cachedTrainingJobs.filter((row) => row.alert_level === 'CRITICAL');
        const warningJobs = cachedTrainingJobs.filter((row) => row.alert_level === 'WARNING');
        const unhealthyWorkers = assistWorkers.filter((row) => row.status === 'UNHEALTHY');
        if (!criticalJobs.length && !warningJobs.length && !unhealthyWorkers.length) {
          trainingRuntimeAlertWrap.innerHTML = renderEmpty('当前没有训练超时或训练机器心跳异常告警。');
          return;
        }
        trainingRuntimeAlertWrap.innerHTML = `
          <div class="alert-grid">
            <article class="alert-card critical">
              <span>CRITICAL 作业</span>
              <strong>${esc(String(criticalJobs.length))}</strong>
              <small>${esc(criticalJobs[0]?.alert_reason || '运行中超时或训练机器已失联')}</small>
            </article>
            <article class="alert-card warning">
              <span>WARNING 作业</span>
              <strong>${esc(String(warningJobs.length))}</strong>
              <small>${esc(warningJobs[0]?.alert_reason || '派发后长时间未开始')}</small>
            </article>
            <article class="alert-card">
              <span>异常训练机器</span>
              <strong>${esc(String(unhealthyWorkers.length))}</strong>
              <small>${esc(unhealthyWorkers[0] ? `${unhealthyWorkers[0].worker_code} · ${unhealthyWorkers[0].alert_reason || '心跳超时'}` : '心跳正常')}</small>
            </article>
          </div>
          ${
            criticalJobs.length || warningJobs.length || unhealthyWorkers.length
              ? `
                  <div class="selection-summary">
                    ${criticalJobs.slice(0, 2).map((row) => `<span>作业 ${esc(row.job_code)} · ${esc(row.alert_reason || row.error_message || '-')}</span>`).join('')}
                    ${warningJobs.slice(0, 2).map((row) => `<span>作业 ${esc(row.job_code)} · ${esc(row.alert_reason || row.error_message || '-')}</span>`).join('')}
                    ${unhealthyWorkers.slice(0, 2).map((row) => `<span>训练机器 ${esc(row.worker_code)} · ${esc(row.alert_reason || '心跳异常')}</span>`).join('')}
                    ${canManageWorkers ? '<div class="row-actions"><button class="ghost" type="button" data-training-runtime-reconcile>立即刷新健康状态</button></div>' : ''}
                  </div>
                `
              : ''
          }
        `;
        trainingRuntimeAlertWrap.querySelector('[data-training-runtime-reconcile]')?.addEventListener('click', async (event) => {
          const button = event.currentTarget;
          button.disabled = true;
          try {
            const result = await ctx.post('/training/runtime/reconcile', { note: 'training_page_manual_reconcile' });
            ctx.toast(`已刷新训练运行健康状态：异常训练机器 ${result.counts?.unhealthy_worker_count || 0}，超时作业 ${result.counts?.timed_out_job_count || 0}`);
            await Promise.all([loadWorkers(), loadJobTable()]);
          } catch (error) {
            ctx.toast(error.message || '刷新健康状态失败', 'error');
          } finally {
            button.disabled = false;
          }
        });
        renderTrainingWorkbenchOverview();
      }

      function defaultDatasetCompareFilters() {
        return { change_scope: 'all', label: '', review_status: '', changed_field: '', q: '' };
      }

      function renderTrainingAssetRefList(title, refs) {
        return `
          <div class="training-run-ref-block">
            <strong>${esc(title)}</strong>
            ${
              refs.length
                ? `
                    <div class="training-run-ref-list">
                      ${refs.map((row) => `
                        <article class="training-run-ref">
                          <strong>${esc(row.version ? `${row.version.dataset_label}:${row.version.version}` : row.asset?.file_name || row.assetId)}</strong>
                          <span class="mono">${esc(row.assetId)}</span>
                          <span>${esc(row.asset ? `${enumText('asset_type', row.asset.asset_type)} · ${enumText('asset_purpose', row.asset.purpose || row.version?.asset_purpose || '-')}` : '资产详情未加载')}</span>
                        </article>
                      `).join('')}
                    </div>
                  `
                : '<span class="muted">未绑定资产</span>'
            }
          </div>
        `;
      }

      function renderTrainingRunSummary() {
        if (!trainingRunSummaryWrap) return;
        const job = getSelectedTrainingJob();
        if (!job) {
          trainingRunSummaryWrap.innerHTML = renderEmpty('选择一条训练作业后，这里会显示基础模型、指标摘要和下一步动作。');
          return;
        }
        const output = job.output_summary || {};
        const history = normalizeTrainingHistory(output.history);
        const bestCheckpoint = normalizeTrainingCheckpoint(output.best_checkpoint);
        const runtimeAlert = job.alert_level
          ? {
              level: job.alert_level,
              reason: job.alert_reason || job.error_message || '训练运行存在异常',
              action: job.recommended_action || 'retry_or_reassign',
            }
          : null;
        const trainRefs = buildTrainingAssetRefs(job.asset_ids || []);
        const validationRefs = buildTrainingAssetRefs(job.validation_asset_ids || []);
        const trainResources = Number(output.train_resource_count ?? output.train_samples ?? job.asset_count ?? 0);
        const validationResources = Number(output.validation_resource_count ?? output.val_samples ?? job.validation_asset_count ?? 0);
        const totalResources = Math.max(0, trainResources) + Math.max(0, validationResources);
        const trainShare = totalResources ? `${Math.round((Math.max(0, trainResources) / totalResources) * 100)}%` : '-';
        const validationShare = totalResources ? `${Math.round((Math.max(0, validationResources) / totalResources) * 100)}%` : '-';
        const trainer = output.trainer || job.spec?.trainer || '受控训练机';
        const currentStage = output.stage || (job.status === 'SUCCEEDED' ? 'completed' : job.status === 'RUNNING' ? 'training' : '-');
        const candidateModel = job.candidate_model;
        const historyEpochCount = Number(output.epochs ?? 0) || history.length || Number(job.spec?.epochs ?? 0) || 0;
        const validationSampleCandidates = assistAssets
          .filter((row) => row.asset_type !== 'archive')
          .filter((row) => {
            const meta = row.meta || {};
            const purpose = String(meta.asset_purpose || '').trim().toLowerCase();
            const intended = String(meta.intended_model_code || '').trim().toLowerCase();
            return (
              intended === String(job.target_model_code || '').trim().toLowerCase()
              || purpose === 'validation'
              || purpose === 'inference'
            );
          })
          .slice(0, 6);
        const metrics = [
          { label: '验证得分', value: formatMetricValue(output.val_score, { percent: true }), note: 'val_score' },
          { label: '验证准确率', value: formatMetricValue(output.val_accuracy, { percent: true }), note: 'val_accuracy' },
          { label: '训练准确率', value: formatMetricValue(output.train_accuracy, { percent: true }), note: 'train_accuracy' },
          { label: '最终损失', value: formatMetricValue(output.final_loss), note: 'final_loss' },
          { label: '轮次', value: formatMetricValue(historyEpochCount), note: 'epochs' },
          { label: '学习率', value: formatMetricValue(output.learning_rate ?? job.spec?.learning_rate, { digits: 6 }), note: 'learning_rate' },
        ];
        const historySummary = history.length
          ? `已记录 ${history.length} 个 epoch，可直接判断收敛趋势和当前最佳 checkpoint。`
          : '当前作业还没有回写 epoch 级历史指标；若使用外部 trainer，请确认 metrics_json 已输出 history。';
        trainingRunSummaryWrap.innerHTML = `
          <div class="training-run-summary">
            <section class="training-run-hero">
              <div class="training-run-hero-main">
                <div class="quick-review-statuses">
                  <span class="badge">${esc(enumText('training_status', job.status))}</span>
                  <span class="badge">${esc(enumText('training_kind', job.training_kind))}</span>
                  <span class="badge">${esc(String(trainer))}</span>
                </div>
                <h4>${esc(`${job.target_model_code}:${job.target_version}`)}</h4>
                <p>${esc(
                  job.status === 'SUCCEEDED'
                    ? '训练已完成，可以根据指标决定是否进入候选审批、发布授权或继续迭代。'
                    : job.status === 'RUNNING'
                      ? '训练正在执行中，当前摘要会随着训练机器回写持续刷新。'
                      : '当前展示的是这条训练作业的最新状态，适合快速核对基础模型、数据规模和目标节点。'
                )}</p>
              </div>
              <div class="row-actions">
                <button class="ghost" type="button" data-copy-training-job="${esc(job.id)}">复制作业ID</button>
                ${
                  candidateModel?.id
                    ? `<button class="ghost" type="button" data-copy-candidate-model="${esc(candidateModel.id)}">复制待验证模型ID</button>`
                    : ''
                }
                ${
                  candidateModel?.id
                    ? `<button class="primary" type="button" data-open-candidate-model="${esc(candidateModel.id)}">查看待验证模型</button>`
                    : ''
                }
                ${
                  canCreateTask && candidateModel?.id
                    ? '<button class="ghost" type="button" data-create-candidate-validation>去任务中心验证新模型</button>'
                    : canCreateTask
                      ? '<button class="ghost" type="button" data-go-training-task>去任务中心</button>'
                      : ''
                }
              </div>
            </section>
            <div class="keyvals">
              <div><span>作业编号</span><strong class="mono">${esc(job.job_code)}</strong></div>
              <div><span>基础模型</span><strong>${esc(job.base_model ? `${job.base_model.model_code}:${job.base_model.version}` : '未指定')}</strong></div>
              <div><span>待验证模型</span><strong>${esc(candidateModel ? `${candidateModel.model_code}:${candidateModel.version}` : '等待生成')}</strong></div>
              <div><span>执行节点</span><strong>${esc(job.assigned_worker_code || job.worker_selector?.host || job.worker_selector?.hosts?.[0] || '未派发')}</strong></div>
              <div><span>当前阶段</span><strong>${esc(currentStage)}</strong></div>
              <div><span>训练时长</span><strong>${esc(formatDurationWindow(job.started_at, job.finished_at, output.duration_sec))}</strong></div>
              <div><span>创建时间</span><strong>${esc(formatDateTime(job.created_at))}</strong></div>
              <div><span>完成时间</span><strong>${esc(formatDateTime(job.finished_at))}</strong></div>
              <div><span>供应商</span><strong>${esc(job.owner_tenant_code || '-')}</strong></div>
              <div><span>买家租户</span><strong>${esc(job.buyer_tenant_code || '-')}</strong></div>
              <div><span>产物摘要</span><strong class="mono">${esc(truncateMiddle(output.artifact_sha256, 10, 8))}</strong></div>
              <div><span>基础模型摘要</span><strong class="mono">${esc(truncateMiddle(output.base_model_hash, 10, 8))}</strong></div>
            </div>
            ${
              runtimeAlert
                ? `
                    <section class="training-runtime-alert ${esc(String(runtimeAlert.level || '').toLowerCase())}">
                      <strong>${esc(`运行告警 · ${runtimeAlert.level}`)}</strong>
                      <span>${esc(runtimeAlert.reason)}</span>
                      <span>${esc(`建议动作：${runtimeAlert.action}`)}</span>
                    </section>
                  `
                : ''
            }
            <section class="training-run-metrics">
              ${metrics.map((metric) => `
                <article class="training-run-metric-card">
                  <span>${esc(metric.label)}</span>
                  <strong>${esc(metric.value)}</strong>
                  <small>${esc(metric.note)}</small>
                </article>
              `).join('')}
            </section>
            <section class="grid-two training-history-grid-wrap">
              ${renderTrainingHistoryChart({
                title: '损失曲线',
                description: '按轮次查看训练 / 验证损失，判断是否出现发散或过拟合。',
                history,
                lowerIsBetter: true,
                lines: [
                  { key: 'train_loss', label: 'train_loss', className: 'train-line' },
                  { key: 'val_loss', label: 'val_loss', className: 'validation-line' },
                ],
              })}
              ${renderTrainingHistoryChart({
                title: '准确率曲线',
                description: '按轮次查看训练 / 验证准确率，适合快速判断收敛与泛化。',
                history,
                percent: true,
                lines: [
                  { key: 'train_accuracy', label: 'train_accuracy', className: 'train-line' },
                  { key: 'val_accuracy', label: 'val_accuracy', className: 'validation-line' },
                ],
              })}
            </section>
            <section class="grid-two training-history-grid-wrap">
              ${renderBestCheckpointCard(bestCheckpoint, history, trainer)}
              <article class="training-checkpoint-card">
                <div class="training-history-head">
                  <div>
                    <strong>训练历史摘要</strong>
                    <p>${esc('把 epoch 级回写指标和下一步动作放在同一屏内，避免只看终态数字。')}</p>
                  </div>
                  <span class="badge">${esc(history.length ? '已回写' : '待回写')}</span>
                </div>
                <div class="training-checkpoint-summary">
                  <span>${esc(historySummary)}</span>
                  <span>${esc(`历史点数=${output.history_count ?? history.length}`)}</span>
                  <span>${esc(`当前阶段=${currentStage}`)}</span>
                  <span>${esc(`训练器=${String(trainer)}`)}</span>
                </div>
              </article>
            </section>
            <section class="training-run-splits">
              <article class="training-run-split-card train">
                <div class="training-run-split-head">
                  <span>训练集</span>
                  <strong>${esc(trainShare)}</strong>
                </div>
                <div class="training-run-split-value">${esc(String(trainResources))}</div>
                <p>${esc(`资产数=${job.asset_count ?? 0} · 样本数=${output.train_samples ?? '-'}`)}</p>
              </article>
              <article class="training-run-split-card validation">
                <div class="training-run-split-head">
                  <span>验证集</span>
                  <strong>${esc(validationShare)}</strong>
                </div>
                <div class="training-run-split-value">${esc(String(validationResources))}</div>
                <p>${esc(`资产数=${job.validation_asset_count ?? 0} · 样本数=${output.val_samples ?? '-'}`)}</p>
              </article>
            </section>
            <div class="grid-two">
              <section class="selection-summary">
                <strong>训练配置</strong>
                <span>训练器：${esc(String(trainer))}</span>
                <span>预处理：${esc(compactValue(job.spec?.preprocessing || job.spec?.preprocess || job.spec?.resize))}</span>
                <span>增强：${esc(compactValue(job.spec?.augmentations || job.spec?.augmentation))}</span>
                <span>特征说明：${esc(compactValue(output.feature_spec || job.spec?.feature_spec))}</span>
                <details><summary>训练参数与输出摘要</summary><pre>${esc(safeJson({ spec: job.spec || {}, output_summary: output }))}</pre></details>
              </section>
              <section class="selection-summary">
                <strong>数据来源</strong>
                <span>目标版本：${esc(`${job.target_model_code}:${job.target_version}`)}</span>
                <span>训练资产：${esc(trainRefs.length ? trainRefs.map((row) => row.version ? `${row.version.dataset_label}:${row.version.version}` : row.asset?.file_name || row.assetId).join(' / ') : '未绑定')}</span>
                <span>验证资产：${esc(validationRefs.length ? validationRefs.map((row) => row.version ? `${row.version.dataset_label}:${row.version.version}` : row.asset?.file_name || row.assetId).join(' / ') : '未绑定')}</span>
                ${candidateModel?.id ? '<span>下一步：新模型已经准备好，可点上方“去任务中心验证新模型”。任务页会自动预填模型、任务类型和设备，你只需要补一张单图或视频资产；训练用 ZIP 数据集不能直接做在线验证。</span>' : '<span>下一步：训练结束后，系统会生成一版待验证模型，再去任务中心挑真实图片验证。</span>'}
                ${job.error_message ? `<span>错误摘要：${esc(job.error_message)}</span>` : '<span>错误摘要：无</span>'}
              </section>
            </div>
            ${
              canCreateTask && candidateModel?.id
                ? `
                    <section class="selection-summary training-inline-validation">
                      <strong>直接验证新模型</strong>
                      <span>不必先跳任务中心。系统会优先帮你带一张合适的单图/视频资产；你也可以手动改成别的资产，再直接创建验证任务。</span>
                      <div class="training-inline-validation-grid">
                        <input id="trainingValidationAssetInput" list="trainingValidationAssetsDatalist" placeholder="优先使用推荐资产；也可手动改成别的单图或视频资产编号" value="${esc(pickSuggestedValidationAsset(validationSampleCandidates))}" />
                        <datalist id="trainingValidationAssetsDatalist">
                          ${assistAssets.filter((row) => row.asset_type !== 'archive').map((row) => `<option value="${esc(row.id)}">${esc(row.file_name)}</option>`).join('')}
                        </datalist>
                        <button class="ghost" type="button" data-launch-candidate-validation>创建验证任务</button>
                        <button class="primary" type="button" data-launch-candidate-validation-open>创建并等待结果</button>
                      </div>
                      ${
                        validationSampleCandidates.length
                          ? `<div class="result-text-ribbon">${validationSampleCandidates.map((row) => `<button class="ghost" type="button" data-pick-validation-asset="${esc(row.id)}">${esc(row.file_name)}</button>`).join('')}</div>`
                          : ''
                      }
                      <div id="trainingValidationLaunchMsg" class="hint">默认会使用刚训练出来的新模型 ${esc(candidateModel.model_code)}:${esc(candidateModel.version)}，以及设备 ${esc(job.assigned_worker_code ? 'edge-01' : (job.worker_selector?.hosts?.[0] || job.worker_selector?.host || 'edge-01'))}。</div>
                    </section>
                  `
                : ''
            }
            <div class="grid-two">
              ${renderTrainingAssetRefList('训练资产明细', trainRefs)}
              ${renderTrainingAssetRefList('验证资产明细', validationRefs)}
            </div>
          </div>
        `;
        trainingRunSummaryWrap.querySelector('[data-copy-training-job]')?.addEventListener('click', async () => {
          try {
            await navigator.clipboard.writeText(String(job.id || ''));
            ctx.toast('训练作业ID已复制');
          } catch {
            ctx.toast('复制失败，请手工复制', 'error');
          }
        });
        trainingRunSummaryWrap.querySelector('[data-copy-candidate-model]')?.addEventListener('click', async () => {
          try {
            await navigator.clipboard.writeText(String(candidateModel?.id || ''));
            ctx.toast('候选模型ID已复制');
          } catch {
            ctx.toast('复制失败，请手工复制', 'error');
          }
        });
        trainingRunSummaryWrap.querySelector('[data-open-candidate-model]')?.addEventListener('click', () => {
          if (!candidateModel?.id) return;
          localStorage.setItem(STORAGE_KEYS.focusModelId, candidateModel.id);
          localStorage.setItem(STORAGE_KEYS.focusModelTimeline, '1');
          ctx.navigate('models');
        });
        trainingRunSummaryWrap.querySelector('[data-go-training-task]')?.addEventListener('click', () => {
          ctx.navigate('tasks');
        });
        trainingRunSummaryWrap.querySelector('[data-create-candidate-validation]')?.addEventListener('click', () => {
          if (!candidateModel?.id) return;
          localStorage.setItem(STORAGE_KEYS.prefillTaskModelId, candidateModel.id);
          localStorage.setItem(STORAGE_KEYS.prefillTaskType, job.target_model_code || 'car_number_ocr');
          localStorage.setItem(
            STORAGE_KEYS.prefillTaskDeviceCode,
            job.assigned_worker_code ? 'edge-01' : (job.worker_selector?.hosts?.[0] || job.worker_selector?.host || 'edge-01'),
          );
          localStorage.removeItem(STORAGE_KEYS.prefillTaskAssetId);
          localStorage.setItem(
            STORAGE_KEYS.prefillTaskHint,
            `已预填候选模型 ${candidateModel.model_code}:${candidateModel.version}。下一步请选择一张单图/视频资产做在线验证；训练/验证 ZIP 数据集不能直接作为任务输入。`,
          );
          ctx.navigate('tasks');
        });
        trainingRunSummaryWrap.querySelectorAll('[data-pick-validation-asset]').forEach((button) => {
          button.addEventListener('click', () => {
            const assetId = button.getAttribute('data-pick-validation-asset') || '';
            const input = trainingRunSummaryWrap.querySelector('#trainingValidationAssetInput');
            if (input) input.value = assetId;
          });
        });
        const launchValidation = async ({ openResults = false } = {}) => {
          if (!candidateModel?.id) return;
          const assetInput = trainingRunSummaryWrap.querySelector('#trainingValidationAssetInput');
          const launchMsg = trainingRunSummaryWrap.querySelector('#trainingValidationLaunchMsg');
          const assetId = String(assetInput?.value || '').trim() || pickSuggestedValidationAsset(validationSampleCandidates);
          if (assetInput && assetId && !String(assetInput.value || '').trim()) assetInput.value = assetId;
          if (!assetId) {
            ctx.toast('先选择一张单图或视频资产', 'error');
            return;
          }
          const payload = {
            asset_id: assetId,
            model_id: candidateModel.id,
            task_type: job.target_model_code || 'car_number_ocr',
            device_code: job.assigned_worker_code ? 'edge-01' : (job.worker_selector?.hosts?.[0] || job.worker_selector?.host || 'edge-01'),
            use_master_scheduler: false,
            intent_text: `${candidateModel.model_code}:${candidateModel.version} 验证`,
          };
          const createBtn = trainingRunSummaryWrap.querySelector(openResults ? '[data-launch-candidate-validation-open]' : '[data-launch-candidate-validation]');
          if (createBtn) createBtn.disabled = true;
          if (launchMsg) launchMsg.textContent = '正在创建验证任务...';
          try {
            const created = await ctx.post('/tasks/create', payload);
            localStorage.setItem(STORAGE_KEYS.lastTaskId, created.id);
            if (!openResults) {
              if (launchMsg) launchMsg.textContent = `已创建验证任务 ${created.id}，可继续在本页等待，或去结果中心查看。`;
              ctx.toast('验证任务已创建');
              return;
            }
            if (launchMsg) launchMsg.textContent = `任务 ${created.id} 已创建，等待执行完成...`;
            await waitForTaskTerminal(created.id);
            if (launchMsg) launchMsg.textContent = `任务 ${created.id} 已完成，正在打开结果页。`;
            ctx.navigate(`results/task/${created.id}`);
          } catch (error) {
            if (launchMsg) launchMsg.textContent = error.message || '创建验证任务失败';
            ctx.toast(error.message || '创建验证任务失败', 'error');
          } finally {
            if (createBtn) createBtn.disabled = false;
          }
        };
        trainingRunSummaryWrap.querySelector('[data-launch-candidate-validation]')?.addEventListener('click', async () => {
          await launchValidation({ openResults: false });
        });
        trainingRunSummaryWrap.querySelector('[data-launch-candidate-validation-open]')?.addEventListener('click', async () => {
          await launchValidation({ openResults: true });
        });
      }

      function renderTrainingJobTable(rows) {
        if (!rows.length) {
          jobsWrap.innerHTML = renderEmpty('暂无训练作业，可从模型中心或本页下方创建一条训练 / 微调作业');
          renderTrainingRunSummary();
          renderTrainingWorkbenchOverview();
          return;
        }
        jobsWrap.innerHTML = `
          <div class="selection-grid">
            ${rows.map((row) => {
              const isActive = activeTrainingJobId === row.id;
              const workerLabel = row.assigned_worker_code || row.worker_selector?.host || row.worker_selector?.hosts?.[0] || '待派发';
              return `
                <article class="selection-card ${isActive ? 'selected active-row' : ''}">
                  <div class="selection-card-head selection-card-head--stack">
                    <div class="selection-card-title">
                      <strong>${esc(row.job_code)}</strong>
                      <span class="selection-card-subtitle">${esc(formatDateTime(row.created_at))}</span>
                    </div>
                    <div class="quick-review-statuses">
                      ${row.alert_level ? `<span class="badge">${esc(row.alert_level)}</span>` : ''}
                      <span class="badge">${esc(enumText('training_status', row.status))}</span>
                      <span class="badge">${esc(enumText('training_kind', row.training_kind))}</span>
                    </div>
                  </div>
                  <div class="selection-card-meta selection-card-meta--compact">
                    <span>训练/验证</span><strong>${esc(`${row.asset_count ?? 0}/${row.validation_asset_count ?? 0}`)}</strong>
                    <span>基础模型</span><strong>${esc(row.base_model ? `${row.base_model.model_code}:${row.base_model.version}` : '未指定')}</strong>
                    <span>待验证模型</span><strong>${esc(row.candidate_model ? `${row.candidate_model.model_code}:${row.candidate_model.version}` : '等待生成')}</strong>
                    <span>执行节点</span><strong>${esc(workerLabel)}</strong>
                  </div>
                  <div class="row-actions">
                    <button class="primary" type="button" data-training-open-summary="${esc(row.id)}">${isActive ? '当前摘要' : '查看摘要'}</button>
                    ${row.can_cancel ? `<button class="ghost" type="button" data-training-cancel="${esc(row.id)}">取消</button>` : ''}
                    ${row.can_retry ? `<button class="ghost" type="button" data-training-retry="${esc(row.id)}">重试</button>` : ''}
                    ${row.can_reassign ? `<button class="ghost" type="button" data-training-reassign="${esc(row.id)}">改派到当前训练机</button>` : ''}
                  </div>
                  <details class="inline-details">
                    <summary>技术详情</summary>
                    <div class="details-panel">
                      <div class="selection-card-meta selection-card-meta--compact">
                        <span>job_id</span><strong class="mono">${esc(row.id)}</strong>
                        <span>目标版本</span><strong>${esc(`${row.target_model_code || '-'}:${row.target_version || '-'}`)}</strong>
                        <span>基础模型ID</span><strong class="mono">${esc(row.base_model?.id || '-')}</strong>
                        <span>候选模型ID</span><strong class="mono">${esc(row.candidate_model?.id || '-')}</strong>
                      </div>
                    </div>
                  </details>
                </article>
              `;
            }).join('')}
          </div>
        `;
        jobsWrap.querySelectorAll('[data-training-open-summary]').forEach((button) => {
          button.addEventListener('click', () => {
            activeTrainingJobId = button.getAttribute('data-training-open-summary') || '';
            setTrainingOverviewPanel('summary');
            renderTrainingJobTable(cachedTrainingJobs);
            renderTrainingRunSummary();
            renderTrainingWorkbenchOverview();
          });
        });
        jobsWrap.querySelectorAll('[data-training-cancel]').forEach((button) => {
          button.addEventListener('click', async () => {
            button.disabled = true;
            await performTrainingJobAction(
              button.getAttribute('data-training-cancel') || '',
              'cancel',
              { note: 'training_page_cancel' },
              '训练作业已取消',
            );
            button.disabled = false;
          });
        });
        jobsWrap.querySelectorAll('[data-training-retry]').forEach((button) => {
          button.addEventListener('click', async () => {
            button.disabled = true;
            await performTrainingJobAction(
              button.getAttribute('data-training-retry') || '',
              'retry',
              { note: 'training_page_retry' },
              '训练作业已重置为待派发',
            );
            button.disabled = false;
          });
        });
        jobsWrap.querySelectorAll('[data-training-reassign]').forEach((button) => {
          button.addEventListener('click', async () => {
            const workerCode = String(workerCodeInput?.value || '').trim();
            const workerHost = String(workerHostInput?.value || '').trim();
            if (!workerCode && !workerHost) {
              ctx.toast('请先在训练机池里选一台机器，再执行改派', 'error');
              return;
            }
            button.disabled = true;
            await performTrainingJobAction(
              button.getAttribute('data-training-reassign') || '',
              'reassign',
              { worker_code: workerCode || null, worker_host: workerHost || null, note: 'training_page_reassign' },
              '训练作业已改派到当前训练机',
            );
            button.disabled = false;
          });
        });
      }

      async function loadJobTable() {
        jobsWrap.innerHTML = renderLoading('加载训练作业...');
        if (trainingRunSummaryWrap) trainingRunSummaryWrap.innerHTML = renderLoading('加载训练摘要...');
        try {
          const fd = new FormData(filterForm);
          const query = toQuery({
            status: fd.get('status'),
            training_kind: fd.get('training_kind'),
          });
          const rows = await ctx.get(`/training/jobs${query}`);
          cachedTrainingJobs = filterBusinessTrainingJobs(rows || []);
          if (requestedFocusTrainingJobId && cachedTrainingJobs.some((row) => row.id === requestedFocusTrainingJobId)) {
            activeTrainingJobId = requestedFocusTrainingJobId;
            localStorage.removeItem(STORAGE_KEYS.focusTrainingJobId);
          } else if (!activeTrainingJobId || !cachedTrainingJobs.some((row) => row.id === activeTrainingJobId)) {
            activeTrainingJobId = pickDefaultTrainingJob(cachedTrainingJobs)?.id || '';
          }
          renderTrainingJobTable(cachedTrainingJobs);
          renderTrainingRunSummary();
          renderTrainingRuntimeAlerts();
          renderTrainingWorkbenchOverview();
        } catch (error) {
          jobsWrap.innerHTML = renderError(error.message);
          if (trainingRunSummaryWrap) trainingRunSummaryWrap.innerHTML = renderError(error.message);
          renderTrainingRuntimeAlerts();
          renderTrainingWorkbenchOverview();
        }
      }

      async function loadWorkers() {
        workersWrap.innerHTML = renderLoading('加载训练机器...');
        try {
          const rows = await ctx.get('/training/workers');
          assistWorkers = rows || [];
          if (!rows.length) {
            workersWrap.innerHTML = renderEmpty('暂无训练机器，请先接入训练执行节点或在下方登记训练机器');
            if (workerPool) workerPool.innerHTML = renderEmpty('当前没有可用于训练分配的机器');
            if (workerCodesDatalist) workerCodesDatalist.innerHTML = '';
            if (workerHostsDatalist) workerHostsDatalist.innerHTML = '';
            renderTrainingRuntimeAlerts();
            renderTrainingWorkbenchOverview();
            return;
          }
          const activeRows = rows.filter((row) => row.status === 'ACTIVE');
          const archivedRows = rows.filter((row) => row.status !== 'ACTIVE');
          const visibleRows = trainingLibraryFilters.workerShowHistory ? rows : activeRows;
          workersWrap.innerHTML = `
            <div class="hint">默认仅展示活跃训练机器。历史异常/失联记录 ${archivedRows.length} 条，可在训练机池里勾选“显示历史异常”查看。</div>
            ${canManageWorkers && archivedRows.length ? '<div class="row-actions"><button class="ghost" type="button" data-cleanup-workers>清理历史异常</button></div>' : ''}
            <div class="selection-grid">
              ${visibleRows.map((row) => `
                <article class="selection-card ${row.status === 'ACTIVE' ? 'selected' : ''}">
                  <div class="selection-card-head selection-card-head--stack">
                    <div class="selection-card-title">
                      <strong>${esc(row.worker_code)}</strong>
                      <span class="selection-card-subtitle">${esc(row.host || '未登记主机')}</span>
                    </div>
                    <div class="quick-review-statuses">
                      ${row.alert_level ? `<span class="badge">${esc(row.alert_level)}</span>` : ''}
                      <span class="badge">${esc(enumText('worker_status', row.status))}</span>
                    </div>
                  </div>
                  <div class="selection-card-meta selection-card-meta--compact">
                    <span>待处理作业</span><strong>${esc(row.outstanding_jobs ?? 0)}</strong>
                    <span>最近心跳</span><strong>${formatDateTime(row.last_seen_at)}</strong>
                    <span>显示名称</span><strong>${esc(row.name || row.worker_code)}</strong>
                    <span>下一步</span><strong>${row.status === 'ACTIVE' ? '可直接选为训练机' : '仅排障查看'}</strong>
                  </div>
                  <div class="row-actions">
                    <button class="ghost" type="button" data-pick-worker="${esc(row.worker_code)}">选为训练机</button>
                  </div>
                  <details class="inline-details">
                    <summary>技术详情</summary>
                    <div class="details-panel">
                      <div class="selection-card-meta selection-card-meta--compact">
                        <span>机器编号</span><strong class="mono">${esc(row.id || '-')}</strong>
                        <span>机器地址</span><strong>${esc(row.host || '-')}</strong>
                        <span>最近出现</span><strong>${formatDateTime(row.last_seen_at)}</strong>
                        <span>告警级别</span><strong>${esc(row.alert_level || '-')}</strong>
                      </div>
                      <details class="inline-details">
                        <summary>机器资源详情</summary>
                        <div class="details-panel">
                          <pre>${esc(safeJson(row.resources || {}))}</pre>
                        </div>
                      </details>
                    </div>
                  </details>
                </article>
              `).join('')}
            </div>
            ${!visibleRows.length && archivedRows.length ? renderEmpty('当前没有活跃训练机器；如需排查历史失联节点，请勾选“显示历史异常”') : ''}
          `;
          if (workerCodesDatalist) {
            workerCodesDatalist.innerHTML = rows.map((row) => `<option value="${esc(row.worker_code)}">${esc(row.name || row.worker_code)}</option>`).join('');
          }
          if (workerHostsDatalist) {
            workerHostsDatalist.innerHTML = rows
              .filter((row) => row.host)
              .map((row) => `<option value="${esc(row.host)}">${esc(row.worker_code)}</option>`)
              .join('');
          }
          ensureDefaultWorkerSelection();
          renderWorkerPool();
          refreshSelectionSummary();
          renderTrainingRuntimeAlerts();
          workersWrap.querySelectorAll('[data-pick-worker]').forEach((button) => {
            button.addEventListener('click', () => fillWorkerSelection(button.getAttribute('data-pick-worker') || ''));
          });
          workersWrap.querySelector('[data-cleanup-workers]')?.addEventListener('click', async (event) => {
            const button = event.currentTarget;
            button.disabled = true;
            try {
              const result = await ctx.post('/training/workers/cleanup', {
                stale_hours: 24,
                note: 'training_page_cleanup_archived_workers',
              });
              ctx.toast(`已清理 ${result.removed_count || 0} 条历史异常训练机器记录`);
              await Promise.all([loadWorkers(), loadJobTable()]);
            } catch (error) {
              ctx.toast(error.message || '训练机清理失败', 'error');
            } finally {
              button.disabled = false;
            }
          });
        } catch (error) {
          if (String(error.message || '').includes('403')) {
            workersWrap.innerHTML = renderEmpty('当前角色无训练机器查看权限');
            if (workerPool) workerPool.innerHTML = renderEmpty('当前角色无训练机查看权限');
            renderTrainingRuntimeAlerts();
            renderTrainingWorkbenchOverview();
            return;
          }
          workersWrap.innerHTML = renderError(error.message);
          if (workerPool) workerPool.innerHTML = renderError(error.message);
          renderTrainingRuntimeAlerts();
          renderTrainingWorkbenchOverview();
        }
      }

      function selectedModel() {
        const modelId = String(baseModelInput?.value || '').trim();
        return assistModels.find((row) => row.id === modelId) || null;
      }

      function selectedWorker() {
        const workerCode = String(workerCodeInput?.value || '').trim();
        const workerHost = String(workerHostInput?.value || '').trim().toLowerCase();
        return (
          assistWorkers.find((row) => workerCode && row.worker_code === workerCode)
          || assistWorkers.find((row) => workerHost && String(row.host || '').trim().toLowerCase() === workerHost)
          || null
        );
      }

      function preferredActiveWorker() {
        const activeRows = assistWorkers.filter((row) => row.status === 'ACTIVE');
        return activeRows.find((row) => row.worker_code === 'local-train-worker')
          || activeRows[0]
          || null;
      }

      function selectedPresetName() {
        return String(trainingPresetInput?.value || 'car_number_balanced').trim() || 'car_number_balanced';
      }

      function presetSpecValue() {
        return TRAINING_SPEC_PRESETS[selectedPresetName()] || {};
      }

      function applyTrainingPreset({ force = false } = {}) {
        if (!specInput) return;
        const current = String(specInput.value || '').trim() || '{}';
        if (!force && current && current !== '{}' && current !== lastAutoSpecSerialized) return;
        const next = presetSpecValue();
        const serialized = safeJson(next);
        lastAutoSpecSerialized = serialized;
        specInput.value = serialized;
      }

      function ensureDefaultWorkerSelection() {
        if (!createForm || selectedWorker()) return;
        const preferred = preferredActiveWorker();
        if (!preferred) return;
        if (workerCodeInput) workerCodeInput.value = preferred.worker_code;
        if (workerHostInput) workerHostInput.value = preferred.host || '';
      }

      function refreshSelectionSummary() {
        if (!selectionSummary) return;
        const model = selectedModel();
        const worker = selectedWorker() || preferredActiveWorker();
        const trainAssetIds = splitCsv(assetIdsInput?.value || '');
        const validationAssetIds = splitCsv(validationAssetIdsInput?.value || '');
        const selectedTrainVersions = assistDatasetVersions.filter((row) => trainAssetIds.includes(row.asset_id));
        const selectedValidationVersions = assistDatasetVersions.filter((row) => validationAssetIds.includes(row.asset_id));
        selectionSummary.innerHTML = `
          <strong>当前选择</strong>
          <span>供应商算法：${esc(model ? `${model.model_code}:${model.version} · ${model.owner_tenant_name || model.owner_tenant_code || '供应商'}` : '未选择')}</span>
          <span>训练预设：${esc(trainingPresetInput?.selectedOptions?.[0]?.textContent?.trim() || '未选择')}</span>
          <span>训练机：${esc(worker ? `${worker.worker_code}${worker.host ? ` · ${worker.host}` : ''}` : '未选择')}</span>
          <span>训练集版本：${esc(selectedTrainVersions.length ? selectedTrainVersions.map((row) => `${row.dataset_label}:${row.version}`).join(' / ') : `${trainAssetIds.length} 个资产`)}</span>
          <span>验证集版本：${esc(selectedValidationVersions.length ? selectedValidationVersions.map((row) => `${row.dataset_label}:${row.version}`).join(' / ') : `${validationAssetIds.length} 个资产`)}</span>
        `;
      }

      function renderTrainingCreateResult(job = null) {
        if (!createResultWrap) return;
        if (!job) {
          createResultWrap.innerHTML = renderEmpty('创建成功后，这里会直接给出下一步动作。');
          return;
        }
        const workerHint = job.assigned_worker_code || selectedWorker()?.worker_code || preferredActiveWorker()?.worker_code || '待调度';
        const nextHint = job.target_model_code === 'car_number_ocr'
          ? '建议下一步继续关注这条作业，等候候选模型回收后直接在训练摘要里发起验证。'
          : '建议先关注训练摘要和候选模型回收，再决定是否进入审批/发布。';
        createResultWrap.innerHTML = `
          <div class="selection-summary training-create-next">
            <strong>训练作业已创建</strong>
            <span>job_code：${esc(job.job_code || '-')}</span>
            <span>目标模型：${esc(`${job.target_model_code || '-'}:${job.target_version || '-'}`)}</span>
            <span>训练机：${esc(workerHint)}</span>
            <span>${esc(nextHint)}</span>
            <div class="row-actions">
              <button class="primary" type="button" data-focus-created-job="${esc(job.id || '')}">聚焦这条作业</button>
              <button class="ghost" type="button" data-scroll-training-summary>查看训练摘要</button>
              ${job.target_model_code === 'car_number_ocr' ? '<button class="ghost" type="button" data-open-car-number-review>回车号文本复核</button>' : ''}
            </div>
          </div>
        `;
        createResultWrap.querySelector('[data-focus-created-job]')?.addEventListener('click', async () => {
          activeTrainingJobId = job.id || activeTrainingJobId;
          setTrainingPanel('overview');
          setTrainingOverviewPanel('jobs');
          await loadJobTable();
          trainingRunSummaryWrap?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        createResultWrap.querySelector('[data-scroll-training-summary]')?.addEventListener('click', () => {
          setTrainingPanel('overview');
          setTrainingOverviewPanel('summary');
          trainingRunSummaryWrap?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        createResultWrap.querySelector('[data-open-car-number-review]')?.addEventListener('click', () => {
          ctx.navigate('training/car-number-labeling');
        });
      }

      async function performTrainingJobAction(jobId, action, payload, successMessage) {
        try {
          await ctx.post(`/training/jobs/${jobId}/${action}`, payload || {});
          ctx.toast(successMessage);
          await loadJobTable();
        } catch (error) {
          ctx.toast(error.message || '训练作业操作失败', 'error');
        }
      }

      function fillModelSelection(modelId) {
        const model = assistModels.find((row) => row.id === modelId);
        if (!model || !baseModelInput) return;
        baseModelInput.value = model.id;
        setTrainingPrepPanel('worker');
        if (targetModelCodeInput && !String(targetModelCodeInput.value || '').trim()) {
          targetModelCodeInput.value = model.model_code === 'car_number_ocr' ? 'car_number_ocr' : `${model.model_code}-ft`;
        }
        if (targetVersionInput && !String(targetVersionInput.value || '').trim()) {
          const stamp = new Date().toISOString().slice(0, 10).replaceAll('-', '');
          targetVersionInput.value = `v${stamp}.1`;
        }
        applyTrainingPreset({ force: String(specInput?.value || '').trim() === '{}' });
        refreshSelectionSummary();
        renderModelLibrary();
      }

      function fillWorkerSelection(workerCode) {
        const worker = assistWorkers.find((row) => row.worker_code === workerCode);
        if (!worker) return;
        if (workerCodeInput) workerCodeInput.value = worker.worker_code;
        if (workerHostInput) workerHostInput.value = worker.host || '';
        refreshSelectionSummary();
        renderWorkerPool();
      }

      function fillDatasetSelection(assetId, targetField, versionId) {
        const input = targetField === 'validation' ? validationAssetIdsInput : assetIdsInput;
        if (!input || !assetId) return;
        input.value = mergeCsvValues(input.value, [assetId]).join(', ');
        if (createMsg) {
          createMsg.textContent = `已把数据集版本 ${versionId || '-'} 加入${targetField === 'validation' ? '验证集' : '训练集'}：${assetId}`;
        }
        refreshSelectionSummary();
        renderDatasetVersionLibrary();
      }

      function renderModelLibrary() {
        if (!modelLibrary) return;
        const q = String(trainingLibraryFilters.modelQuery || '').trim().toLowerCase();
        const rows = assistModels
          .filter((row) => row.model_type === 'expert')
          .filter((row) => {
            if (!q) return true;
            const haystack = [
              row.model_code,
              row.version,
              row.owner_tenant_name,
              row.owner_tenant_code,
              row.task_type,
              row.plugin_name,
            ]
              .map((item) => String(item || '').toLowerCase())
              .join(' ');
            return haystack.includes(q);
          });
        const currentModelId = String(baseModelInput?.value || '').trim();
        if (trainingModelMeta) trainingModelMeta.textContent = `显示 ${rows.length} / ${assistModels.filter((row) => row.model_type === 'expert').length} 个算法`;
        if (!rows.length) {
          modelLibrary.innerHTML = renderEmpty('当前角色暂无可用供应商算法，请先由平台发布模型到当前租户');
          return;
        }
        modelLibrary.innerHTML = `
          <div class="selection-grid">
            ${rows.map((row) => `
              <article class="selection-card ${currentModelId === row.id ? 'selected' : ''}">
                <div class="selection-card-head">
                  <strong>${esc(row.model_code)}:${esc(row.version)}</strong>
                  <span class="badge">${esc(enumText('model_status', row.status))}</span>
                </div>
                <div class="selection-card-meta">
                  <span>供应商</span><strong>${esc(row.owner_tenant_name || row.owner_tenant_code || row.owner_tenant_id || '平台模型')}</strong>
                  <span>任务</span><strong>${esc(row.task_type || row.plugin_name || '-')}</strong>
                  <span>来源</span><strong>${esc(enumText('model_source_type', (row.platform_meta || {}).model_source_type || '-'))}</strong>
                  <span>资源</span><strong>${esc(`${row.gpu_mem_mb || '-'} MB / ${row.latency_ms || '-'} ms`)}</strong>
                </div>
                <div class="row-actions">
                  <button class="primary" type="button" data-pick-model="${esc(row.id)}">选用算法</button>
                </div>
              </article>
            `).join('')}
          </div>
        `;
        modelLibrary.querySelectorAll('[data-pick-model]').forEach((button) => {
          button.addEventListener('click', () => fillModelSelection(button.getAttribute('data-pick-model') || ''));
        });
      }

      function renderWorkerPool() {
        if (!workerPool) return;
        const currentCode = String(workerCodeInput?.value || '').trim();
        const currentHost = String(workerHostInput?.value || '').trim().toLowerCase();
        const localWorker = assistWorkers.find((row) => row.worker_code === 'local-train-worker') || null;
        const localWorkerStartCmd = 'python3 deploy/training-worker/bootstrap_local_worker.py bootstrap --start --restart';
        const localWorkerStatus = localWorker?.status || 'NOT_REGISTERED';
        const localWorkerSummary = localWorkerStatus === 'ACTIVE'
          ? '本机训练机器已在线，页面创建的新训练作业会优先改派或调度到这台机器。'
          : localWorkerStatus === 'UNHEALTHY'
            ? '检测到本机训练机器曾注册但当前离线。建议重新生成 token 并后台拉起本机训练机器。'
            : '当前还没有可用的本机训练机器。建议先注册并启动本机训练机器，再创建训练作业。';
        const localWorkerMeta = localWorker
          ? `
              <div class="selection-card-meta">
                <span>机器编号</span><strong class="mono">${esc(localWorker.worker_code)}</strong>
                <span>状态</span><strong>${esc(enumText('worker_status', localWorker.status))}</strong>
                <span>机器地址</span><strong class="mono">${esc(localWorker.host || '-')}</strong>
                <span>最近心跳</span><strong>${esc(localWorker.heartbeat_age_sec == null ? '-' : `${localWorker.heartbeat_age_sec}s`)}</strong>
              </div>
            `
          : `
              <div class="selection-card-meta">
                <span>机器编号</span><strong class="mono">local-train-worker</strong>
                <span>状态</span><strong>未注册</strong>
                <span>推荐脚本</span><strong class="mono">deploy/training-worker/bootstrap_local_worker.py</strong>
              </div>
            `;
        const localWorkerGuide = `
          <article class="selection-card ${localWorkerStatus === 'ACTIVE' ? 'selected' : ''}">
            <div class="selection-card-head">
              <strong>本机训练机器</strong>
              <span class="badge">${esc(localWorkerStatus === 'NOT_REGISTERED' ? '未注册' : enumText('worker_status', localWorkerStatus))}</span>
            </div>
            <p class="muted">${esc(localWorkerSummary)}</p>
            ${localWorkerMeta}
            <div class="row-actions">
              <button class="ghost" type="button" data-copy-local-worker-cmd>复制启动命令</button>
              ${localWorker ? `<button class="primary" type="button" data-pick-worker-card="${esc(localWorker.worker_code)}">选这台机器</button>` : ''}
            </div>
            <div class="hint mono">${esc(localWorkerStartCmd)}</div>
          </article>
        `;
        if (!assistWorkers.length) {
          workerPool.innerHTML = `${localWorkerGuide}${renderEmpty('当前没有训练机可供分配')}`;
          workerPool.querySelector('[data-copy-local-worker-cmd]')?.addEventListener('click', async () => {
            try {
              await navigator.clipboard.writeText(localWorkerStartCmd);
              ctx.toast('本机训练机器启动命令已复制');
            } catch {
              ctx.toast('复制失败，请手工复制命令', 'error');
            }
          });
          return;
        }
        const q = String(trainingLibraryFilters.workerQuery || '').trim().toLowerCase();
        const visibleSource = trainingLibraryFilters.workerShowHistory
          ? [...assistWorkers]
          : assistWorkers.filter((row) => row.status === 'ACTIVE');
        const filteredWorkers = visibleSource.filter((row) => {
          if (!q) return true;
          const haystack = [
            row.worker_code,
            row.name,
            row.host,
            row.status,
            row.alert_level,
          ]
            .map((item) => String(item || '').toLowerCase())
            .join(' ');
          return haystack.includes(q);
        });
        if (trainingWorkerMeta) {
          const activeCount = assistWorkers.filter((row) => row.status === 'ACTIVE').length;
          const archivedCount = assistWorkers.length - activeCount;
          trainingWorkerMeta.textContent = trainingLibraryFilters.workerShowHistory
            ? `显示 ${filteredWorkers.length} / ${assistWorkers.length} 台训练机（活跃 ${activeCount} / 历史异常 ${archivedCount}）`
            : `显示 ${filteredWorkers.length} / ${activeCount} 台活跃训练机（历史异常 ${archivedCount} 已折叠）`;
        }
        if (!filteredWorkers.length) {
          workerPool.innerHTML = renderEmpty(trainingLibraryFilters.workerShowHistory ? '当前筛选条件下没有训练机' : '当前没有活跃训练机；可勾选“显示历史异常”查看失联节点');
          return;
        }
        const sorted = [...filteredWorkers].sort((left, right) => {
          if (left.status === right.status) return String(left.worker_code).localeCompare(String(right.worker_code));
          if (left.status === 'ACTIVE') return -1;
          if (right.status === 'ACTIVE') return 1;
          return 0;
        });
        workerPool.innerHTML = `
          ${localWorkerGuide}
          <div class="selection-grid">
            ${sorted.map((row) => {
              const isSelected = currentCode === row.worker_code || (currentHost && currentHost === String(row.host || '').trim().toLowerCase());
              return `
                <article class="selection-card ${isSelected ? 'selected' : ''}">
                  <div class="selection-card-head">
                    <strong>${esc(row.name || row.worker_code)}</strong>
                    <span class="badge">${esc(enumText('worker_status', row.status))}</span>
                  </div>
                  <div class="selection-card-meta">
                    <span>训练机器编号</span><strong class="mono">${esc(row.worker_code)}</strong>
                    <span>机器地址</span><strong class="mono">${esc(row.host || '-')}</strong>
                    <span>待处理</span><strong>${esc(row.outstanding_jobs ?? 0)}</strong>
                    <span>GPU 资源</span><strong>${esc(`${(row.resources || {}).gpu_count || 0} / ${(row.resources || {}).gpu_mem_mb || 0} MB`)}</strong>
                    <span>告警</span><strong>${esc(row.alert_level || '-')}</strong>
                  </div>
                  <div class="row-actions">
                    <button class="primary" type="button" data-pick-worker-card="${esc(row.worker_code)}">选这台机器</button>
                  </div>
                </article>
              `;
            }).join('')}
          </div>
        `;
        workerPool.querySelector('[data-copy-local-worker-cmd]')?.addEventListener('click', async () => {
          try {
            await navigator.clipboard.writeText(localWorkerStartCmd);
            ctx.toast('本机训练机器启动命令已复制');
          } catch {
            ctx.toast('复制失败，请手工复制命令', 'error');
          }
        });
        workerPool.querySelectorAll('[data-pick-worker-card]').forEach((button) => {
          button.addEventListener('click', () => fillWorkerSelection(button.getAttribute('data-pick-worker-card') || ''));
        });
      }

      function renderDatasetVersionLibrary() {
        if (!datasetVersionLibrary) return;
        if (!assistDatasetVersions.length) {
          datasetVersionLibrary.innerHTML = renderEmpty('暂无可直接用于训练的数据集版本。快速识别结果导出后会自动出现在这里。');
          if (datasetCompareWrap) datasetCompareWrap.innerHTML = renderEmpty('暂无数据集版本可对比');
          if (datasetPreviewWrap) datasetPreviewWrap.innerHTML = renderEmpty('暂无数据集版本可预览');
          return;
        }
        const trainAssetIds = splitCsv(assetIdsInput?.value || '');
        const validationAssetIds = splitCsv(validationAssetIdsInput?.value || '');
        const q = String(trainingLibraryFilters.datasetQuery || '').trim().toLowerCase();
        const matchingVersions = assistDatasetVersions.filter((row) => {
          if (trainingLibraryFilters.datasetPurpose && row.asset_purpose !== trainingLibraryFilters.datasetPurpose) return false;
          if (trainingLibraryFilters.datasetRecommendedOnly && !row.recommended) return false;
          if (!q) return true;
          const summary = row.summary || {};
          const meta = row.asset?.meta || {};
          const haystack = [
            row.dataset_label,
            row.version,
            row.source_type,
            row.asset_purpose,
            ...(summary.label_vocab || meta.label_vocab || []),
          ]
            .map((item) => String(item || '').toLowerCase())
            .join(' ');
          return haystack.includes(q);
        });
        const filteredVersions = (() => {
          if (trainingLibraryFilters.datasetShowHistory) return matchingVersions;
          const picked = [];
          const pickedKeys = new Set();
          const selectedVersionIds = new Set(
            [prefillTrainingDatasetVersionId, activeDatasetCompareVersionId].filter(Boolean),
          );
          matchingVersions.forEach((row) => {
            const key = String(row.dataset_key || row.id);
            if (!pickedKeys.has(key) && row.is_latest !== false) {
              picked.push(row);
              pickedKeys.add(key);
              return;
            }
            if (selectedVersionIds.has(row.id) && !picked.some((item) => item.id === row.id)) {
              picked.push(row);
            }
          });
          return picked.length ? picked : matchingVersions;
        })();
        if (trainingDatasetMeta) {
          const hiddenHistoryCount = Math.max(matchingVersions.length - filteredVersions.length, 0);
          trainingDatasetMeta.textContent = trainingLibraryFilters.datasetShowHistory
            ? `显示 ${filteredVersions.length} / ${assistDatasetVersions.length} 个版本`
            : `显示 ${filteredVersions.length} 个最新版本，收起历史 ${hiddenHistoryCount} 条`;
        }
        if (!filteredVersions.length) {
          datasetVersionLibrary.innerHTML = renderEmpty('当前筛选条件下没有数据集版本');
          return;
        }
        datasetVersionLibrary.innerHTML = `
          <div class="selection-grid">
            ${filteredVersions.map((row) => {
              const summary = row.summary || {};
              const meta = row.asset?.meta || {};
              const selected = trainAssetIds.includes(row.asset_id) || validationAssetIds.includes(row.asset_id) || row.id === prefillTrainingDatasetVersionId;
              return `
                <article class="selection-card ${selected ? 'selected' : ''}">
                  <div class="selection-card-head">
                    <strong>${esc(row.dataset_label)}:${esc(row.version)}</strong>
                    <div class="quick-review-statuses">
                      <span class="badge">${esc(enumText('asset_purpose', row.asset_purpose || '-'))}</span>
                      ${row.recommended ? '<span class="badge">推荐</span>' : ''}
                      ${row.is_latest ? '<span class="badge">最新</span>' : '<span class="badge">历史版</span>'}
                      ${row.is_latest && row.history_depth > 1 ? `<span class="badge">历史 ${esc(String(row.history_depth - 1))}</span>` : ''}
                    </div>
                  </div>
                  <div class="selection-card-meta">
                    <span>资产编号</span><strong class="mono">${esc(row.asset_id)}</strong>
                    <span>来源</span><strong>${esc(row.source_type || '-')}</strong>
                    <span>样本数</span><strong>${esc(String(summary.task_count ?? summary.source_result_count ?? meta.archive_resource_count ?? 0))}</strong>
                    <span>标签</span><strong>${esc((summary.label_vocab || meta.label_vocab || []).slice(0, 6).join(', ') || '-')}</strong>
                    <span>版本链</span><strong>${esc(row.previous_version ? `${row.version} -> ${row.previous_version}` : `${row.version} -> -`)}</strong>
                  </div>
                  <div class="row-actions">
                    <button class="primary" type="button" data-pick-dataset-training="${esc(row.asset_id)}" data-dataset-version-id="${esc(row.id)}">加入训练集</button>
                    <button class="ghost" type="button" data-pick-dataset-validation="${esc(row.asset_id)}" data-dataset-version-id="${esc(row.id)}">加入验证集</button>
                    <button class="ghost" type="button" data-preview-dataset-version="${esc(row.id)}">查看内容</button>
                    <details class="inline-details">
                      <summary>更多操作</summary>
                      <div class="details-panel action-panel">
                        <button class="ghost" type="button" data-recommend-dataset-version="${esc(row.id)}" data-recommend-purpose="training">推荐训练集</button>
                        <button class="ghost" type="button" data-recommend-dataset-version="${esc(row.id)}" data-recommend-purpose="validation">推荐验证集</button>
                        <button class="ghost" type="button" data-compare-dataset-version="${esc(row.id)}">对比上一版</button>
                        <button class="ghost" type="button" data-rollback-dataset-version="${esc(row.id)}">回滚为新版本</button>
                      </div>
                    </details>
                  </div>
                </article>
              `;
            }).join('')}
          </div>
        `;
        datasetVersionLibrary.querySelectorAll('[data-pick-dataset-training]').forEach((button) => {
          button.addEventListener('click', () => fillDatasetSelection(button.getAttribute('data-pick-dataset-training') || '', 'training', button.getAttribute('data-dataset-version-id') || ''));
        });
        datasetVersionLibrary.querySelectorAll('[data-pick-dataset-validation]').forEach((button) => {
          button.addEventListener('click', () => fillDatasetSelection(button.getAttribute('data-pick-dataset-validation') || '', 'validation', button.getAttribute('data-dataset-version-id') || ''));
        });
        datasetVersionLibrary.querySelectorAll('[data-recommend-dataset-version]').forEach((button) => {
          button.addEventListener('click', async () => {
            const versionId = button.getAttribute('data-recommend-dataset-version') || '';
            const purpose = button.getAttribute('data-recommend-purpose') || 'training';
            button.disabled = true;
            try {
              await ctx.post(`/assets/dataset-versions/${versionId}/recommend`, { asset_purpose: purpose, note: `training_page_recommended_${purpose}` });
              ctx.toast(`已标记为推荐${purpose === 'validation' ? '验证集' : '训练集'}`);
              await loadFormAssistData();
            } catch (error) {
              ctx.toast(error.message || '推荐失败', 'error');
            } finally {
              button.disabled = false;
            }
          });
        });
        datasetVersionLibrary.querySelectorAll('[data-compare-dataset-version]').forEach((button) => {
          button.addEventListener('click', async () => {
            const versionId = button.getAttribute('data-compare-dataset-version') || '';
            datasetCompareFilters = defaultDatasetCompareFilters();
            await compareWithPreviousDatasetVersion(versionId);
          });
        });
        datasetVersionLibrary.querySelectorAll('[data-preview-dataset-version]').forEach((button) => {
          button.addEventListener('click', async () => {
            const versionId = button.getAttribute('data-preview-dataset-version') || '';
            await previewDatasetVersion(versionId);
          });
        });
        datasetVersionLibrary.querySelectorAll('[data-rollback-dataset-version]').forEach((button) => {
          button.addEventListener('click', async () => {
            const versionId = button.getAttribute('data-rollback-dataset-version') || '';
            activeDatasetRollback = filteredVersions.find((row) => row.id === versionId) || null;
            renderDatasetRollbackWorkbench();
            datasetRollbackWrap?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          });
        });
        renderDatasetCompare();
        renderDatasetRollbackWorkbench();
        renderDatasetPreview();
      }

      function renderDatasetCompare() {
        if (!datasetCompareWrap) return;
        if (!activeDatasetCompare) {
          datasetCompareWrap.innerHTML = renderEmpty('选择某个数据集版本后，可在这里查看与上一版的差异、筛选变更样本，或回滚为新版本。');
          return;
        }
        const diff = activeDatasetCompare.diff || {};
        const formatJoined = (value) => esc((Array.isArray(value) ? value : []).join(', ') || '-');
        const formatScalar = (value) => esc(String(value ?? '-'));
        const renderSampleRows = (title, rows, mode) => {
          if (!Array.isArray(rows) || !rows.length) return '';
          return `
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>${esc(title)}</th><th>source</th><th>labels</th><th>objects</th><th>review</th>${mode === 'changed' ? '<th>变更字段</th>' : ''}</tr></thead>
                <tbody>
                  ${rows.map((row) => {
                    const sample = mode === 'changed' ? (row.right || row.left || {}) : row;
                    const thumb = row.preview_url || sample.preview_url || null;
                    return `
                      <tr>
                        <td>
                          <div class="dataset-compare-sample">
                            ${
                              thumb
                                ? `
                                    <div class="dataset-compare-thumb">
                                      <img src="${esc(thumb)}" alt="${esc(row.source_file_name || sample.source_file_name || row.sample_id || sample.sample_id || 'dataset-compare')}" />
                                    </div>
                                  `
                                : ''
                            }
                            <div class="dataset-compare-meta">
                              <strong class="mono">${esc(row.sample_id || sample.sample_id || '-')}</strong>
                              <span>${esc(sample.object_prompt || '-')}</span>
                            </div>
                          </div>
                        </td>
                        <td>${esc(row.source_file_name || sample.source_file_name || '-')}</td>
                        <td>${mode === 'changed' ? `${formatJoined(row.left?.matched_labels)} -> ${formatJoined(row.right?.matched_labels)}` : formatJoined(sample.matched_labels)}</td>
                        <td>${mode === 'changed' ? `${formatScalar(row.left?.object_count ?? 0)} -> ${formatScalar(row.right?.object_count ?? 0)}` : formatScalar(sample.object_count ?? 0)}</td>
                        <td>${mode === 'changed' ? `${formatScalar(row.left?.review_status || '-')} -> ${formatScalar(row.right?.review_status || '-')}` : formatScalar(sample.review_status || '-')}</td>
                        ${mode === 'changed' ? `<td>${esc((row.change_fields || []).join(', ') || '-')}</td>` : ''}
                      </tr>
                    `;
                  }).join('')}
                </tbody>
              </table>
            </div>
          `;
        };
        datasetCompareWrap.innerHTML = `
          <strong>版本对比</strong>
          <span>${esc(`${activeDatasetCompare.left?.dataset_label || '-'}:${activeDatasetCompare.left?.version || '-'} -> ${activeDatasetCompare.right?.dataset_label || '-'}:${activeDatasetCompare.right?.version || '-'}`)}</span>
          <form id="datasetCompareFilterForm" class="inline-form dataset-compare-toolbar">
            <select name="change_scope">
              <option value="all" ${datasetCompareFilters.change_scope === 'all' ? 'selected' : ''}>全部变化</option>
              <option value="added" ${datasetCompareFilters.change_scope === 'added' ? 'selected' : ''}>仅新增</option>
              <option value="removed" ${datasetCompareFilters.change_scope === 'removed' ? 'selected' : ''}>仅移除</option>
              <option value="changed" ${datasetCompareFilters.change_scope === 'changed' ? 'selected' : ''}>仅变更</option>
            </select>
            <input name="label" placeholder="label 筛选" value="${esc(datasetCompareFilters.label || '')}" />
            <input name="review_status" placeholder="review 状态" value="${esc(datasetCompareFilters.review_status || '')}" />
            <input name="changed_field" placeholder="changed_field" value="${esc(datasetCompareFilters.changed_field || '')}" />
            <input name="q" placeholder="sample / file / prompt" value="${esc(datasetCompareFilters.q || '')}" />
            <button class="ghost" type="submit">筛选差异</button>
            <button class="ghost" type="button" data-dataset-compare-reset>重置</button>
          </form>
          <div class="keyvals">
            <div><span>样本变化</span><strong>${esc(String(diff.task_count_delta ?? 0))}</strong></div>
            <div><span>资源变化</span><strong>${esc(String(diff.resource_count_delta ?? 0))}</strong></div>
            <div><span>已复核变化</span><strong>${esc(String(diff.reviewed_task_count_delta ?? 0))}</strong></div>
            <div><span>同一数据集</span><strong>${esc(diff.same_dataset_key ? '是' : '否')}</strong></div>
            <div><span>新增样本</span><strong>${esc(String(diff.sample_added_count ?? 0))}</strong></div>
            <div><span>移除样本</span><strong>${esc(String(diff.sample_removed_count ?? 0))}</strong></div>
            <div><span>变更样本</span><strong>${esc(String(diff.sample_changed_count ?? 0))}</strong></div>
            <div><span>样本净变化</span><strong>${esc(String(diff.sample_task_count_delta ?? 0))}</strong></div>
            <div><span>筛选后样本</span><strong>${esc(String(diff.filtered_sample_count ?? 0))}</strong></div>
          </div>
          <span>新增标签：${esc((diff.labels_added || []).join(', ') || '-')}</span>
          <span>移除标签：${esc((diff.labels_removed || []).join(', ') || '-')}</span>
          ${renderSampleRows('新增样本', diff.added_samples || [], 'added')}
          ${renderSampleRows('移除样本', diff.removed_samples || [], 'removed')}
          ${renderSampleRows('变更样本', diff.changed_samples || [], 'changed')}
        `;
        datasetCompareWrap.querySelector('#datasetCompareFilterForm')?.addEventListener('submit', async (event) => {
          event.preventDefault();
          const fd = new FormData(event.currentTarget);
          datasetCompareFilters = {
            change_scope: String(fd.get('change_scope') || 'all').trim() || 'all',
            label: String(fd.get('label') || '').trim(),
            review_status: String(fd.get('review_status') || '').trim(),
            changed_field: String(fd.get('changed_field') || '').trim(),
            q: String(fd.get('q') || '').trim(),
          };
          await compareWithPreviousDatasetVersion(activeDatasetCompareVersionId);
        });
        datasetCompareWrap.querySelector('[data-dataset-compare-reset]')?.addEventListener('click', async () => {
          datasetCompareFilters = defaultDatasetCompareFilters();
          await compareWithPreviousDatasetVersion(activeDatasetCompareVersionId);
        });
      }

      function renderDatasetPreview() {
        if (!datasetPreviewWrap) return;
        if (!activeDatasetPreview) {
          datasetPreviewWrap.innerHTML = renderEmpty('选择某个数据集版本后，可在这里查看样本摘要、标签和复核状态。');
          return;
        }
        const version = activeDatasetPreview.dataset_version || {};
        const summary = version.summary || {};
        const manifest = activeDatasetPreview.manifest || {};
        const samples = activeDatasetPreview.samples || [];
        datasetPreviewWrap.innerHTML = `
          <strong>${esc(`${version.dataset_label || '-'}:${version.version || '-'}`)}</strong>
          <span>标签：${esc((summary.label_vocab || manifest.label_vocab || []).join(', ') || '-')}</span>
          <span>样本数：${esc(String(summary.task_count ?? manifest.task_count ?? 0))} · 已复核：${esc(String(summary.reviewed_task_count ?? 0))}</span>
          <span>预览文件：${esc(((version.asset?.meta || {}).archive_preview_members || []).slice(0, 5).join(', ') || '-')}</span>
          ${
            samples.some((row) => row.preview_url)
              ? `
                  <div class="dataset-preview-gallery">
                    ${samples.filter((row) => row.preview_url).map((row) => `
                      <article class="dataset-preview-card">
                        <div class="dataset-preview-thumb">
                          <img src="${esc(row.preview_url)}" alt="${esc(row.source_file_name || row.sample_id || 'dataset-preview')}" />
                        </div>
                        <div class="dataset-preview-meta">
                          <strong>${esc(row.source_file_name || row.sample_id || '-')}</strong>
                          <span>${esc((row.matched_labels || []).join(', ') || row.object_prompt || '-')}</span>
                        </div>
                      </article>
                    `).join('')}
                  </div>
                `
              : ''
          }
          ${
            samples.length
              ? `
                  <div class="table-wrap">
                    <table class="table">
                      <thead><tr><th>sample_id</th><th>source</th><th>prompt</th><th>labels</th><th>objects</th><th>review</th></tr></thead>
                      <tbody>
                        ${samples.map((row) => `
                          <tr>
                            <td class="mono">${esc(row.sample_id || row.task_id || '-')}</td>
                            <td>${esc(row.source_file_name || '-')}</td>
                            <td>${esc(row.object_prompt || '-')}</td>
                            <td>${esc((row.matched_labels || []).join(', ') || '-')}</td>
                            <td>${esc(String(row.object_count ?? 0))}</td>
                            <td>${esc(row.review_status || '-')}</td>
                          </tr>
                        `).join('')}
                      </tbody>
                    </table>
                  </div>
                `
              : renderEmpty('当前版本没有可展示的样本摘要')
          }
        `;
      }

      function revokeDatasetPreviewBlobUrls() {
        datasetPreviewBlobUrls.forEach((url) => URL.revokeObjectURL(url));
        datasetPreviewBlobUrls = [];
      }

      function revokeDatasetCompareBlobUrls() {
        datasetCompareBlobUrls.forEach((url) => URL.revokeObjectURL(url));
        datasetCompareBlobUrls = [];
      }

      async function attachDatasetSamplePreview(row, versionId, bucket) {
        if (!row) return row;
        let previewUrl = null;
        try {
          if (row.preview_file && versionId) {
            previewUrl = await fetchAuthorizedBlobUrl(
              `/assets/dataset-versions/${versionId}/preview-file${toQuery({ member: row.preview_file })}`,
              ctx.token,
            );
          } else if (row.asset_type === 'image' && row.asset_id) {
            previewUrl = await fetchAuthorizedBlobUrl(`/assets/${row.asset_id}/content`, ctx.token);
          }
        } catch {
          previewUrl = null;
        }
        if (previewUrl) bucket.push(previewUrl);
        return { ...row, preview_url: previewUrl };
      }

      async function enrichDatasetComparePayload(payload) {
        revokeDatasetCompareBlobUrls();
        const leftVersionId = payload?.left?.id;
        const rightVersionId = payload?.right?.id;
        const addedSamples = await Promise.all((payload?.diff?.added_samples || []).map((row) => attachDatasetSamplePreview(row, rightVersionId, datasetCompareBlobUrls)));
        const removedSamples = await Promise.all((payload?.diff?.removed_samples || []).map((row) => attachDatasetSamplePreview(row, leftVersionId, datasetCompareBlobUrls)));
        const changedSamples = await Promise.all((payload?.diff?.changed_samples || []).map(async (row) => {
          const left = await attachDatasetSamplePreview(row.left, leftVersionId, datasetCompareBlobUrls);
          const right = await attachDatasetSamplePreview(row.right, rightVersionId, datasetCompareBlobUrls);
          return { ...row, left, right, preview_url: right?.preview_url || left?.preview_url || null };
        }));
        return {
          ...payload,
          diff: {
            ...(payload?.diff || {}),
            added_samples: addedSamples,
            removed_samples: removedSamples,
            changed_samples: changedSamples,
          },
        };
      }

      async function compareWithPreviousDatasetVersion(versionId) {
        activeDatasetCompareVersionId = versionId;
        const current = assistDatasetVersions.find((row) => row.id === versionId);
        if (!current) {
          revokeDatasetCompareBlobUrls();
          activeDatasetCompare = null;
          renderDatasetCompare();
          return;
        }
        const previous = assistDatasetVersions
          .filter((row) => row.dataset_key === current.dataset_key && row.id !== current.id)
          .sort((left, right) => parseVersionOrdinal(right.version) - parseVersionOrdinal(left.version))
          .find((row) => parseVersionOrdinal(row.version) < parseVersionOrdinal(current.version));
        if (!previous) {
          revokeDatasetCompareBlobUrls();
          activeDatasetCompare = {
            left: current,
            right: current,
            diff: {
              same_dataset_key: true,
              task_count_delta: 0,
              resource_count_delta: 0,
              reviewed_task_count_delta: 0,
              labels_added: [],
              labels_removed: [],
              sample_added_count: 0,
              sample_removed_count: 0,
              sample_changed_count: 0,
              sample_task_count_delta: 0,
              filtered_sample_count: 0,
              added_samples: [],
              removed_samples: [],
              changed_samples: [],
            },
          };
          renderDatasetCompare();
          return;
        }
        datasetCompareWrap.innerHTML = renderLoading('加载版本对比...');
        try {
          const payload = await ctx.get(`/assets/dataset-versions/compare${toQuery({ left_id: previous.id, right_id: current.id, sample_limit: 6, ...datasetCompareFilters })}`);
          activeDatasetCompare = await enrichDatasetComparePayload(payload);
          renderDatasetCompare();
        } catch (error) {
          revokeDatasetCompareBlobUrls();
          datasetCompareWrap.innerHTML = renderError(error.message);
        }
      }

      async function previewDatasetVersion(versionId) {
        if (!datasetPreviewWrap) return;
        datasetPreviewWrap.innerHTML = renderLoading('加载数据集版本内容...');
        try {
          revokeDatasetPreviewBlobUrls();
          const preview = await ctx.get(`/assets/dataset-versions/${versionId}/preview${toQuery({ sample_limit: 6 })}`);
          const enrichedSamples = await Promise.all((preview.samples || []).map(async (row) => {
            let previewUrl = null;
            try {
              if (row.preview_file) {
                previewUrl = await fetchAuthorizedBlobUrl(
                  `/assets/dataset-versions/${versionId}/preview-file${toQuery({ member: row.preview_file })}`,
                  ctx.token,
                );
              } else if (row.asset_type === 'image' && row.asset_id) {
                previewUrl = await fetchAuthorizedBlobUrl(`/assets/${row.asset_id}/content`, ctx.token);
              }
            } catch {
              previewUrl = null;
            }
            if (previewUrl) datasetPreviewBlobUrls.push(previewUrl);
            return { ...row, preview_url: previewUrl };
          }));
          activeDatasetPreview = { ...preview, samples: enrichedSamples };
          renderDatasetPreview();
        } catch (error) {
          datasetPreviewWrap.innerHTML = renderError(error.message);
        }
      }

      async function loadFormAssistData() {
        if (!createForm) return;
        try {
          const [assets, models, datasetVersions] = await Promise.all([
            ctx.get('/assets?limit=200'),
            ctx.get('/models'),
            ctx.get('/assets/dataset-versions?limit=60'),
          ]);
          assistAssets = filterBusinessAssets(assets || []);
          assistModels = filterBusinessModels(models || []);
          assistDatasetVersions = [...filterBusinessDatasetVersions(datasetVersions || [])].sort((left, right) => {
            const leftRecommended = left.recommended ? 1 : 0;
            const rightRecommended = right.recommended ? 1 : 0;
            if (leftRecommended !== rightRecommended) return rightRecommended - leftRecommended;
            return parseVersionOrdinal(right.version) - parseVersionOrdinal(left.version);
          });
          assetsDatalist.innerHTML = assistAssets.map((row) => `<option value="${esc(row.id)}">${esc(row.file_name)}</option>`).join('');
          modelsDatalist.innerHTML = assistModels.map((row) => `<option value="${esc(row.id)}">${esc(row.model_code)}:${esc(row.version)}</option>`).join('');
          renderModelLibrary();
          renderDatasetVersionLibrary();
          if (prefillTrainingDatasetVersionId) {
            await compareWithPreviousDatasetVersion(prefillTrainingDatasetVersionId);
            await previewDatasetVersion(prefillTrainingDatasetVersionId);
          } else {
            renderDatasetCompare();
            renderDatasetPreview();
          }
          refreshSelectionSummary();
          renderTrainingRunSummary();
        } catch {
          if (modelLibrary) modelLibrary.innerHTML = renderEmpty('供应商算法加载失败，请稍后刷新');
          if (datasetVersionLibrary) datasetVersionLibrary.innerHTML = renderEmpty('数据集版本加载失败，请稍后刷新');
          if (datasetCompareWrap) datasetCompareWrap.innerHTML = renderEmpty('数据集版本对比不可用，请稍后刷新');
          if (datasetPreviewWrap) datasetPreviewWrap.innerHTML = renderEmpty('数据集版本预览不可用，请稍后刷新');
          renderTrainingRunSummary();
        }
      }

      filterForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        await loadJobTable();
      });

      registerWorkerForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        registerWorkerMsg.textContent = '';
        const submitBtn = registerWorkerForm.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        try {
          const fd = new FormData(registerWorkerForm);
          const payload = {
            worker_code: String(fd.get('worker_code') || '').trim(),
            name: String(fd.get('name') || '').trim(),
            host: String(fd.get('host') || '').trim() || null,
            status: String(fd.get('status') || 'ACTIVE'),
            labels: JSON.parse(String(fd.get('labels') || '{}')),
            resources: JSON.parse(String(fd.get('resources') || '{}')),
          };
          const result = await ctx.post('/training/workers/register', payload);
          registerWorkerMsg.textContent = `注册成功，引导令牌：${result.bootstrap_token || '-'}`;
          ctx.toast('训练机器登记成功');
          await loadWorkers();
        } catch (error) {
          registerWorkerMsg.textContent = error.message || '注册失败';
        } finally {
          submitBtn.disabled = false;
        }
      });

      createForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        createMsg.textContent = '';
        const submitBtn = createForm.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        try {
          const fd = new FormData(createForm);
          const baseModelId = String(fd.get('base_model_id') || '').trim() || null;
          const fallbackWorker = selectedWorker() || preferredActiveWorker();
          const workerCode = String(fd.get('worker_code') || '').trim() || String(fallbackWorker?.worker_code || '').trim();
          const workerHost = String(fd.get('worker_host') || '').trim() || String(fallbackWorker?.host || '').trim();
          const model = assistModels.find((row) => row.id === baseModelId) || null;
          const workerSelector = {};
          if (workerCode) workerSelector.worker_codes = [workerCode];
          if (workerHost) workerSelector.hosts = [workerHost];
          let parsedSpec = {};
          const rawSpec = String(fd.get('spec') || '').trim();
          if (!rawSpec || rawSpec === '{}' || rawSpec === lastAutoSpecSerialized) {
            parsedSpec = presetSpecValue();
          } else {
            parsedSpec = JSON.parse(rawSpec || '{}');
          }
          const payload = {
            training_kind: String(fd.get('training_kind') || 'finetune'),
            asset_ids: splitCsv(fd.get('asset_ids')),
            validation_asset_ids: splitCsv(fd.get('validation_asset_ids')),
            base_model_id: baseModelId,
            owner_tenant_id: model?.owner_tenant_id || null,
            target_model_code: String(fd.get('target_model_code') || '').trim(),
            target_version: String(fd.get('target_version') || '').trim(),
            worker_selector: workerSelector,
            spec: parsedSpec,
          };
          const result = await ctx.post('/training/jobs', payload);
          activeTrainingJobId = result.id || activeTrainingJobId;
          createMsg.textContent = `创建成功：${result.job_code}${result.assigned_worker_code ? ` · ${result.assigned_worker_code}` : workerHost ? ` · ${workerHost}` : ''}`;
          renderTrainingCreateResult(result);
          ctx.toast('训练作业创建成功');
          await loadJobTable();
          setTrainingPanel('overview');
          setTrainingOverviewPanel('summary');
          trainingRunSummaryWrap?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } catch (error) {
          createMsg.textContent = error.message || '创建失败';
          renderTrainingCreateResult(null);
        } finally {
          submitBtn.disabled = false;
        }
      });

      baseModelInput?.addEventListener('change', () => {
        refreshSelectionSummary();
        renderModelLibrary();
      });
      workerCodeInput?.addEventListener('change', () => {
        refreshSelectionSummary();
        renderWorkerPool();
      });
      workerHostInput?.addEventListener('change', () => {
        refreshSelectionSummary();
        renderWorkerPool();
      });
      trainingPresetInput?.addEventListener('change', () => {
        applyTrainingPreset();
        refreshSelectionSummary();
      });
      assetIdsInput?.addEventListener('change', () => {
        refreshSelectionSummary();
        renderDatasetVersionLibrary();
      });
      validationAssetIdsInput?.addEventListener('change', () => {
        refreshSelectionSummary();
        renderDatasetVersionLibrary();
      });
      specInput?.addEventListener('blur', () => {
        if (!String(specInput.value || '').trim()) {
          specInput.value = '{}';
          applyTrainingPreset({ force: true });
        }
      });
      trainingModelSearch?.addEventListener('input', () => {
        trainingLibraryFilters.modelQuery = trainingModelSearch.value || '';
        renderModelLibrary();
      });
      trainingWorkerSearch?.addEventListener('input', () => {
        trainingLibraryFilters.workerQuery = trainingWorkerSearch.value || '';
        renderWorkerPool();
      });
      trainingWorkerShowHistory?.addEventListener('change', () => {
        trainingLibraryFilters.workerShowHistory = trainingWorkerShowHistory.checked;
        renderWorkerPool();
        loadWorkers();
      });
      trainingDatasetSearch?.addEventListener('input', () => {
        trainingLibraryFilters.datasetQuery = trainingDatasetSearch.value || '';
        renderDatasetVersionLibrary();
      });
      trainingDatasetPurposeFilter?.addEventListener('change', () => {
        trainingLibraryFilters.datasetPurpose = trainingDatasetPurposeFilter.value || '';
        renderDatasetVersionLibrary();
      });
      trainingDatasetRecommendedOnly?.addEventListener('change', () => {
        trainingLibraryFilters.datasetRecommendedOnly = trainingDatasetRecommendedOnly.checked;
        renderDatasetVersionLibrary();
      });
      trainingDatasetShowHistory?.addEventListener('change', () => {
        trainingLibraryFilters.datasetShowHistory = trainingDatasetShowHistory.checked;
        renderDatasetVersionLibrary();
      });
      trainingPanelTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setTrainingPanel(button.getAttribute('data-training-panel-tab') || 'overview');
        });
      });
      trainingOverviewTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setTrainingOverviewPanel(button.getAttribute('data-training-overview-tab') || 'alerts');
        });
      });
      trainingPrepTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setTrainingPrepPanel(button.getAttribute('data-training-prep-tab') || 'model');
        });
      });
      trainingWorkersTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setTrainingWorkersPanel(button.getAttribute('data-training-workers-tab') || 'overview');
        });
      });
      trainingCreateTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setTrainingCreatePanel(button.getAttribute('data-training-create-tab') || 'prep');
        });
      });

      await Promise.all([loadJobTable(), loadWorkers(), loadFormAssistData()]);
      ensureDefaultWorkerSelection();
      applyTrainingPreset({ force: String(specInput?.value || '').trim() === '{}' });
      refreshSelectionSummary();
      setTrainingPanel(activeTrainingPanel);
      renderTrainingCreateResult(null);
    },
  };
}

function pageCarNumberLabeling(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  return {
    html: `
      <section class="card">
        <h2>车号文本复核</h2>
        <p>直接浏览 <code>demo_data/train</code> 裁剪出来的车号 crop，接受或修正 OCR 建议，并把复核结果回写到标注清单。</p>
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-labeling-panel-tab="overview">复核总览</button>
          <button class="ghost" type="button" data-labeling-panel-tab="queue">待处理样本</button>
          <button class="ghost" type="button" data-labeling-panel-tab="review">当前样本复核</button>
          <button class="ghost" type="button" data-labeling-panel-tab="export">导出与训练</button>
        </div>
        <div id="labelingPanelMeta" class="hint">默认先看复核总览；选择样本后会自动切到当前样本复核，导出训练数据时会自动切到导出与训练。</div>
      </section>
      <section class="card" data-labeling-panel="overview">
        <div id="carNumberLabelingSummaryWrap">${renderLoading('加载复核摘要...')}</div>
      </section>
      <section class="card" data-labeling-panel="review" hidden>
        <div id="carNumberLabelingDetailWrap">${renderEmpty('先到“待处理样本”里选择一个样本开始复核')}</div>
      </section>
      <section class="card" data-labeling-panel="export" hidden>
        <div class="row-actions review-toolbar">
          <label class="checkbox-row"><input id="carNumberAllowSuggestionsExport" type="checkbox" /> 导出时允许建议值补空</label>
          <button id="exportCarNumberTextDataset" class="ghost" type="button">导出文本训练包</button>
          <button id="exportCarNumberTextAssets" class="primary" type="button">先准备训练数据</button>
          <button id="exportCarNumberTrainingJob" class="ghost" type="button">现在开始训练</button>
        </div>
        <div class="hint">快捷键：<code>Ctrl/Cmd+S</code> 保存，<code>Alt+↑/↓</code> 切换上一条/下一条。“先准备训练数据”会打开训练页并自动预填，“现在开始训练”会直接创建训练作业。</div>
        <div id="carNumberLabelingExportMsg" class="hint"></div>
      </section>
      <section class="grid-two" data-labeling-panel="queue" hidden>
        <section class="card">
          <form id="carNumberLabelingFilterForm" class="section-toolbar compact">
            <input id="carNumberLabelingSearch" name="q" placeholder="搜索 sample_id / 源文件 / 建议文本" />
            <select id="carNumberLabelingStatus" name="review_status">
              <option value="">全部状态</option>
              <option value="pending">待处理</option>
              <option value="done">已完成</option>
              <option value="needs_check">待复核</option>
            </select>
            <select id="carNumberLabelingSplit" name="split_hint">
              <option value="">全部切分</option>
              <option value="train">train</option>
              <option value="validation">validation</option>
            </select>
            <label class="checkbox-row"><input id="carNumberOnlyMissingFinal" type="checkbox" /> 仅看未补最终文本</label>
            <label class="checkbox-row"><input id="carNumberOnlyWithSuggestion" type="checkbox" /> 仅看有建议</label>
            <button class="ghost" type="submit">刷新列表</button>
          </form>
          <div class="row-actions review-toolbar">
            <button id="presetCarNumberTodo" class="ghost" type="button">只看待处理</button>
            <button id="presetCarNumberNeedsCheck" class="ghost" type="button">只看待复核</button>
            <button id="presetCarNumberReset" class="ghost" type="button">重置筛选</button>
          </div>
          <div id="carNumberLabelingListMeta" class="hint"></div>
          <div id="carNumberLabelingListWrap">${renderLoading('加载待复核样本...')}</div>
        </section>
        <section class="card">
          <h3>待处理说明</h3>
          <div class="hint">在左侧筛选和浏览样本；选中后系统会自动切到“当前样本复核”。如果你只是想看进度，留在“复核总览”；如果准备导出训练数据，切到“导出与训练”。</div>
          <div class="selection-summary">
            <strong>推荐顺序</strong>
            <span>先处理待处理和缺少最终文本的样本，再导出训练数据或直接开始训练。</span>
          </div>
        </section>
      </section>
    `,
    async mount(root) {
      const filterForm = root.querySelector('#carNumberLabelingFilterForm');
      const summaryWrap = root.querySelector('#carNumberLabelingSummaryWrap');
      const listMeta = root.querySelector('#carNumberLabelingListMeta');
      const listWrap = root.querySelector('#carNumberLabelingListWrap');
      const detailWrap = root.querySelector('#carNumberLabelingDetailWrap');
      const searchInput = root.querySelector('#carNumberLabelingSearch');
      const statusInput = root.querySelector('#carNumberLabelingStatus');
      const splitInput = root.querySelector('#carNumberLabelingSplit');
      const onlyMissingFinalInput = root.querySelector('#carNumberOnlyMissingFinal');
      const onlyWithSuggestionInput = root.querySelector('#carNumberOnlyWithSuggestion');
      const presetTodoBtn = root.querySelector('#presetCarNumberTodo');
      const presetNeedsCheckBtn = root.querySelector('#presetCarNumberNeedsCheck');
      const presetResetBtn = root.querySelector('#presetCarNumberReset');
      const exportAllowSuggestionsInput = root.querySelector('#carNumberAllowSuggestionsExport');
      const exportBtn = root.querySelector('#exportCarNumberTextDataset');
      const exportAssetsBtn = root.querySelector('#exportCarNumberTextAssets');
      const exportTrainingJobBtn = root.querySelector('#exportCarNumberTrainingJob');
      const exportMsg = root.querySelector('#carNumberLabelingExportMsg');
      const labelingPanelMeta = root.querySelector('#labelingPanelMeta');
      const labelingPanelTabs = Array.from(root.querySelectorAll('[data-labeling-panel-tab]'));
      const labelingPanels = Array.from(root.querySelectorAll('[data-labeling-panel]'));
      let selectedSampleId = '';
      let currentItems = [];
      let currentPreviewUrl = '';
      let activeSaveRequest = null;
      let currentCarNumberRule = null;
      let activeLabelingPanel = 'overview';

      function revokePreviewUrl() {
        if (currentPreviewUrl) URL.revokeObjectURL(currentPreviewUrl);
        currentPreviewUrl = '';
      }

      function currentFilters() {
        return {
          q: String(searchInput?.value || '').trim(),
          review_status: String(statusInput?.value || '').trim(),
          split_hint: String(splitInput?.value || '').trim(),
          has_final_text: onlyMissingFinalInput?.checked ? 'false' : '',
          has_suggestion: onlyWithSuggestionInput?.checked ? 'true' : '',
          limit: 120,
        };
      }

      function setLabelingPanel(panel) {
        activeLabelingPanel = panel;
        labelingPanelTabs.forEach((btn) => {
          const active = btn.getAttribute('data-labeling-panel-tab') === panel;
          btn.classList.toggle('primary', active);
          btn.classList.toggle('ghost', !active);
        });
        labelingPanels.forEach((section) => {
          section.hidden = section.getAttribute('data-labeling-panel') !== panel;
        });
        if (labelingPanelMeta) {
          labelingPanelMeta.textContent = ({
            overview: '先看整体进度、规则和最近导出情况。',
            queue: '在这里筛选和选择待处理样本；选中后会自动切到当前样本复核。',
            review: '聚焦当前样本，接受建议、修正文本并保存复核。',
            export: '当一批样本已经补好真值后，在这里整理训练数据或直接开始训练。',
          })[panel] || '按当前工作区继续操作。';
        }
      }

      function renderSummary(summary) {
        currentCarNumberRule = summary?.car_number_rule || currentCarNumberRule;
        const reviewCounts = summary?.review_status_counts || {};
        const latestExport = summary?.latest_export || null;
        const latestTrainCount = latestExport?.bundles?.train?.sample_count ?? 0;
        const latestValidationCount = latestExport?.bundles?.validation?.sample_count ?? 0;
        const latestSourceLabel = Object.entries(latestExport?.text_sources || {})
          .map(([key, value]) => `${key} ${value}`)
          .join(' / ');
        return `
          <div class="result-overview-grid">
            <article class="metric-card">
              <h4>总样本</h4>
              <p class="metric">${esc(summary?.annotated_rows ?? '-')}</p>
              <span>当前车号文本复核队列中的 crop 数量</span>
            </article>
            <article class="metric-card">
              <h4>已有建议</h4>
              <p class="metric">${esc(summary?.suggestion_rows ?? '-')}</p>
              <span>${esc(summary?.suggestion_ratio != null ? `${Math.round(Number(summary.suggestion_ratio) * 100)}%` : '-')}</span>
            </article>
            <article class="metric-card">
              <h4>已补真值</h4>
              <p class="metric">${esc(summary?.final_text_rows ?? '-')}</p>
              <span>${esc(summary?.final_text_ratio != null ? `${Math.round(Number(summary.final_text_ratio) * 100)}%` : '-')}</span>
            </article>
            <article class="metric-card">
              <h4>合法真值</h4>
              <p class="metric">${esc(summary?.valid_final_text_rows ?? '-')}</p>
              <span>${esc(summary?.car_number_rule?.label || '当前规则')}</span>
            </article>
            <article class="metric-card">
              <h4>复核状态</h4>
              <p class="metric">${esc(reviewCounts.done ?? 0)}</p>
              <span>${esc(`待处理 ${reviewCounts.pending ?? 0} / 待复核 ${reviewCounts.needs_check ?? 0}`)}</span>
            </article>
            <article class="metric-card">
              <h4>最近导出</h4>
              <p class="metric">${esc(latestExport?.accepted_rows ?? 0)}</p>
              <span>${esc(latestExport ? `train ${latestTrainCount} / validation ${latestValidationCount}` : '还没有导出记录')}</span>
            </article>
          </div>
          ${
            latestExport
              ? `<div class="hint">最近导出：${esc(formatDateTime(latestExport.generated_at) || '-')} · ${esc(latestSourceLabel || '无来源拆分统计')} · 输出 ${esc(latestExport.output_dir || '-')}</div>`
              : ''
          }
          ${summary?.car_number_rule?.description ? `<div class="hint">当前车号规则：${esc(summary.car_number_rule.label || '')} · ${esc(summary.car_number_rule.description || '')}</div>` : ''}
        `;
      }

      function renderList(payload) {
        const items = payload?.items || [];
        if (!items.length) return renderEmpty('当前筛选条件下没有样本');
        return `
          <div class="text-review-list">
            ${items.map((item) => `
              <button class="text-review-item ${selectedSampleId === item.sample_id ? 'active' : ''}" type="button" data-labeling-sample="${esc(item.sample_id)}">
                <div class="text-review-item-head">
                  <strong>${esc(item.sample_id)}</strong>
                  <span class="badge">${esc(item.review_status)}</span>
                </div>
                <div class="text-review-item-meta">${esc(item.source_file || '-')}</div>
                <div class="text-review-item-badges">
                  ${item.ocr_suggestion ? `<span class="badge">${esc(`建议 ${item.ocr_suggestion}`)}</span>` : '<span class="badge">无建议</span>'}
                  ${item.final_text ? `<span class="badge">${esc(`真值 ${item.final_text}`)}</span>` : ''}
                  ${item.split_hint ? `<span class="badge">${esc(item.split_hint)}</span>` : ''}
                </div>
              </button>
            `).join('')}
          </div>
        `;
      }

      function renderDetail(item) {
        if (!item) {
          detailWrap.innerHTML = renderEmpty('从左侧选择一个样本开始复核');
          return;
        }
        detailWrap.innerHTML = `
          <div class="text-review-detail">
            <div class="text-review-preview">
              ${
                currentPreviewUrl
                  ? `<img src="${esc(currentPreviewUrl)}" alt="车号 crop 预览" />`
                  : `<div class="text-review-preview-empty">${renderLoading('加载 crop 预览...')}</div>`
              }
            </div>
            <form id="carNumberReviewForm" class="form-grid">
              <div class="selection-summary">
                <strong>${esc(item.sample_id)}</strong>
                <span>${esc(item.source_file || '-')}</span>
              </div>
              <div class="keyvals compact">
                <div><span>切分</span><strong>${esc(item.split_hint || '-')}</strong></div>
                <div><span>复核状态</span><strong>${esc(item.review_status || '-')}</strong></div>
                <div><span>定位框</span><strong>${esc((item.bbox || []).join(', ') || '-')}</strong></div>
                <div><span>识别引擎</span><strong>${esc(item.ocr_suggestion_engine || '-')}</strong></div>
              </div>
              <label>模型建议</label>
              <input value="${esc(item.ocr_suggestion || '')}" disabled />
              <div class="hint">confidence=${esc(item.ocr_suggestion_confidence || '-')} · quality=${esc(item.ocr_suggestion_quality || '-')}</div>
              <label>最终文本（人工确认）</label>
              <input id="carNumberFinalText" name="final_text" value="${esc(item.final_text || '')}" placeholder="输入最终车号文本" />
              <div class="hint">${esc(item.car_number_rule?.description || currentCarNumberRule?.description || '当前默认要求车号符合激活规则')}</div>
              ${item.final_text_validation ? `<div class="hint">当前最终文本校验：${esc(item.final_text_validation.valid ? '合法' : '不合法')}</div>` : ''}
              <label>复核状态</label>
              <select name="review_status">
                <option value="pending" ${item.review_status === 'pending' ? 'selected' : ''}>待处理</option>
                <option value="done" ${item.review_status === 'done' ? 'selected' : ''}>已完成</option>
                <option value="needs_check" ${item.review_status === 'needs_check' ? 'selected' : ''}>待复核</option>
              </select>
              <label>复核人</label>
              <input name="reviewer" value="${esc(item.reviewer || ctx.state.user?.username || '')}" />
              <label>备注</label>
              <textarea name="notes" rows="3" placeholder="记录特殊情况、模糊字符、需要复查的原因">${esc(item.notes || '')}</textarea>
              <div class="row-actions">
                <button id="acceptCarNumberSuggestion" class="ghost" type="button" ${item.ocr_suggestion ? '' : 'disabled'}>采用建议</button>
                <button id="clearCarNumberFinalText" class="ghost" type="button">清空最终文本</button>
              </div>
              <div class="row-actions">
                <button id="selectPrevCarNumberReview" class="ghost" type="button">上一条</button>
                <button id="selectNextCarNumberReview" class="ghost" type="button">下一条</button>
              </div>
              <div class="row-actions">
                <button class="primary" type="submit">保存复核</button>
                <button id="saveAndNextCarNumberReview" class="ghost" type="button">保存并下一条</button>
              </div>
              <div id="carNumberReviewMsg" class="hint"></div>
            </form>
          </div>
        `;
        const finalTextInput = detailWrap.querySelector('#carNumberFinalText');
        detailWrap.querySelector('#acceptCarNumberSuggestion')?.addEventListener('click', () => {
          if (finalTextInput) finalTextInput.value = item.ocr_suggestion || '';
        });
        detailWrap.querySelector('#clearCarNumberFinalText')?.addEventListener('click', () => {
          if (finalTextInput) finalTextInput.value = '';
        });
        detailWrap.querySelector('#selectPrevCarNumberReview')?.addEventListener('click', async () => {
          await selectRelativeItem(-1);
        });
        detailWrap.querySelector('#selectNextCarNumberReview')?.addEventListener('click', async () => {
          await selectRelativeItem(1);
        });
        detailWrap.querySelector('#saveAndNextCarNumberReview')?.addEventListener('click', async () => {
          const form = detailWrap.querySelector('#carNumberReviewForm');
          if (!form) return;
          await submitReview(form, { moveNext: true });
        });
        detailWrap.querySelector('#carNumberReviewForm')?.addEventListener('submit', async (event) => {
          event.preventDefault();
          await submitReview(event.currentTarget, { moveNext: false });
        });
      }

      async function loadPreview(sampleId) {
        revokePreviewUrl();
        try {
          currentPreviewUrl = await fetchAuthorizedBlobUrl(`/training/car-number-labeling/items/${sampleId}/crop`, ctx.token);
        } catch {
          currentPreviewUrl = '';
        }
      }

      async function selectItem(sampleId, { openPanel = true } = {}) {
        selectedSampleId = sampleId;
        const item = currentItems.find((row) => row.sample_id === sampleId) || null;
        renderDetail(item);
        if (!item) return;
        if (openPanel) setLabelingPanel('review');
        await loadPreview(sampleId);
        if (selectedSampleId === sampleId) renderDetail(item);
        listWrap.innerHTML = renderList({ items: currentItems });
        bindListClicks();
      }

      function bindListClicks() {
        listWrap.querySelectorAll('[data-labeling-sample]').forEach((btn) => {
          btn.addEventListener('click', async () => {
            await selectItem(btn.getAttribute('data-labeling-sample') || '', { openPanel: true });
          });
        });
      }

      async function selectRelativeItem(step) {
        if (!currentItems.length) return;
        const currentIndex = currentItems.findIndex((item) => item.sample_id === selectedSampleId);
        const baseIndex = currentIndex >= 0 ? currentIndex : 0;
        const nextIndex = (baseIndex + step + currentItems.length) % currentItems.length;
        const nextItem = currentItems[nextIndex];
        if (nextItem) await selectItem(nextItem.sample_id, { openPanel: true });
      }

      function activeReviewForm() {
        return detailWrap.querySelector('#carNumberReviewForm');
      }

      function preferredOpenItem(items, currentId = '') {
        if (currentId && items.some((item) => item.sample_id === currentId)) return currentId;
        const unresolved = items.find((item) => item.review_status !== 'done' || !item.has_final_text);
        return unresolved?.sample_id || items[0]?.sample_id || '';
      }

      async function loadSummary() {
        summaryWrap.innerHTML = renderLoading('加载复核摘要...');
        try {
          const summary = await ctx.get('/training/car-number-labeling/summary');
          summaryWrap.innerHTML = renderSummary(summary);
        } catch (error) {
          summaryWrap.innerHTML = renderError(error.message);
        }
      }

      async function loadItems({ preserveSelection = true } = {}) {
        listWrap.innerHTML = renderLoading('加载待复核样本...');
        detailWrap.innerHTML = renderLoading('加载样本详情...');
        try {
          const payload = await ctx.get(`/training/car-number-labeling/items${toQuery(currentFilters())}`);
          currentItems = payload?.items || [];
          listMeta.textContent = `当前列表 ${currentItems.length} / ${payload?.total ?? 0}`;
          listWrap.innerHTML = renderList(payload);
          bindListClicks();
          const nextSampleId = preserveSelection
            ? preferredOpenItem(currentItems, selectedSampleId)
            : preferredOpenItem(currentItems);
          if (nextSampleId) {
            await selectItem(nextSampleId, { openPanel: activeLabelingPanel === 'review' });
          } else {
            selectedSampleId = '';
            revokePreviewUrl();
            renderDetail(null);
          }
        } catch (error) {
          listWrap.innerHTML = renderError(error.message);
          detailWrap.innerHTML = renderEmpty('列表加载失败，无法展示复核详情');
        }
      }

      async function submitReview(form, { moveNext = false } = {}) {
        if (!selectedSampleId) return null;
        const msg = detailWrap.querySelector('#carNumberReviewMsg');
        const formData = new FormData(form);
        const payload = {
          final_text: String(formData.get('final_text') || '').trim().toUpperCase(),
          review_status: String(formData.get('review_status') || 'pending').trim() || 'pending',
          reviewer: String(formData.get('reviewer') || '').trim(),
          notes: String(formData.get('notes') || '').trim(),
        };
        const validation = validateCarNumberByRule(payload.final_text, currentCarNumberRule);
        if (payload.final_text && !validation.valid) {
          if (msg) msg.textContent = `当前文本不符合规则：${validation.description}`;
          throw new Error(`当前文本不符合规则：${validation.description}`);
        }
        if (msg) msg.textContent = '保存中...';
        try {
          activeSaveRequest = ctx.post(`/training/car-number-labeling/items/${selectedSampleId}/review`, payload);
          const data = await activeSaveRequest;
          ctx.toast('复核已保存');
          await Promise.all([loadSummary(), loadItems({ preserveSelection: true })]);
          if (moveNext && currentItems.length > 1) {
            const currentIndex = currentItems.findIndex((item) => item.sample_id === data?.item?.sample_id);
            const pendingAfter = currentItems
              .slice(currentIndex + 1)
              .concat(currentItems.slice(0, currentIndex + 1))
              .find((item) => item.review_status !== 'done' || !item.has_final_text);
            const nextItem = pendingAfter || currentItems[(currentIndex + 1) % currentItems.length];
            if (nextItem) await selectItem(nextItem.sample_id, { openPanel: true });
          }
          if (msg) msg.textContent = '保存成功';
          return data;
        } catch (error) {
          if (msg) msg.textContent = error.message || '保存失败';
          throw error;
        } finally {
          activeSaveRequest = null;
        }
      }

      async function exportTextDataset() {
        if (!exportBtn || !exportMsg) return;
        setLabelingPanel('export');
        exportBtn.disabled = true;
        if (exportAssetsBtn) exportAssetsBtn.disabled = true;
        if (exportTrainingJobBtn) exportTrainingJobBtn.disabled = true;
        exportMsg.textContent = '正在导出 OCR 文本训练包...';
        try {
          const payload = await ctx.post('/training/car-number-labeling/export-text-dataset', {
            allow_suggestions: !!exportAllowSuggestionsInput?.checked,
          });
          const trainCount = payload?.bundles?.train?.sample_count ?? 0;
          const validationCount = payload?.bundles?.validation?.sample_count ?? 0;
          exportMsg.textContent = `导出完成：train ${trainCount}，validation ${validationCount}。输出目录 ${payload?.output_dir || '-'}`;
          ctx.toast('OCR 文本训练包已导出');
        } catch (error) {
          exportMsg.textContent = error.message || '导出失败';
          ctx.toast(error.message || '导出失败', 'error');
        } finally {
          exportBtn.disabled = false;
          if (exportAssetsBtn) exportAssetsBtn.disabled = false;
          if (exportTrainingJobBtn) exportTrainingJobBtn.disabled = false;
        }
      }

      async function exportAssetsToTraining() {
        if (!exportAssetsBtn || !exportMsg) return;
        setLabelingPanel('export');
        exportBtn.disabled = true;
        exportAssetsBtn.disabled = true;
        if (exportTrainingJobBtn) exportTrainingJobBtn.disabled = true;
        exportMsg.textContent = '正在导出并注册训练/验证资产，随后打开训练页...';
        try {
          const payload = await ctx.post('/training/car-number-labeling/export-text-assets', {
            allow_suggestions: !!exportAllowSuggestionsInput?.checked,
          });
          const prefill = payload?.prefill || {};
          localStorage.setItem(STORAGE_KEYS.prefillTrainingAssetIds, (prefill.train_asset_ids || []).join(', '));
          localStorage.setItem(STORAGE_KEYS.prefillTrainingValidationAssetIds, (prefill.validation_asset_ids || []).join(', '));
          if (prefill.dataset_label) localStorage.setItem(STORAGE_KEYS.prefillTrainingDatasetLabel, prefill.dataset_label);
          if (prefill.training_dataset_version_id) localStorage.setItem(STORAGE_KEYS.prefillTrainingDatasetVersionId, prefill.training_dataset_version_id);
          if (prefill.intended_model_code) localStorage.setItem(STORAGE_KEYS.prefillTrainingTargetModelCode, prefill.intended_model_code);
          exportMsg.textContent = `已注册训练资产 ${payload?.training_asset?.asset_id || '-'} / 验证资产 ${payload?.validation_asset?.asset_id || '-'}。训练页已预填这些资产编号，但还需要你手动点“创建训练作业”。`;
          ctx.toast('训练资产已导出，训练页已预填');
          ctx.navigate('training');
        } catch (error) {
          exportMsg.textContent = error.message || '注册训练资产失败';
          ctx.toast(error.message || '注册训练资产失败', 'error');
        } finally {
          exportBtn.disabled = false;
          exportAssetsBtn.disabled = false;
          if (exportTrainingJobBtn) exportTrainingJobBtn.disabled = false;
        }
      }

      async function exportTrainingJob() {
        if (!exportTrainingJobBtn || !exportMsg) return;
        setLabelingPanel('export');
        exportBtn.disabled = true;
        if (exportAssetsBtn) exportAssetsBtn.disabled = true;
        exportTrainingJobBtn.disabled = true;
          exportMsg.textContent = '正在导出资产并直接创建 car_number_ocr 训练作业...';
        try {
          const payload = await ctx.post('/training/car-number-labeling/export-text-training-job', {
            allow_suggestions: !!exportAllowSuggestionsInput?.checked,
          });
          const job = payload?.job || {};
          if (job.id) localStorage.setItem(STORAGE_KEYS.focusTrainingJobId, job.id);
          exportMsg.textContent = `已创建训练作业 ${job.job_code || '-'} · ${job.target_model_code || 'car_number_ocr'}:${job.target_version || '-'}，即将跳转训练中心。`;
          ctx.toast('OCR 文本训练作业已创建');
          ctx.navigate('training');
        } catch (error) {
          exportMsg.textContent = error.message || '创建训练作业失败';
          ctx.toast(error.message || '创建训练作业失败', 'error');
        } finally {
          exportBtn.disabled = false;
          if (exportAssetsBtn) exportAssetsBtn.disabled = false;
          exportTrainingJobBtn.disabled = false;
        }
      }

      filterForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        await loadItems({ preserveSelection: false });
      });

      presetTodoBtn?.addEventListener('click', async () => {
        statusInput.value = '';
        onlyMissingFinalInput.checked = true;
        onlyWithSuggestionInput.checked = false;
        searchInput.value = '';
        await loadItems({ preserveSelection: false });
      });

      presetNeedsCheckBtn?.addEventListener('click', async () => {
        statusInput.value = 'needs_check';
        onlyMissingFinalInput.checked = false;
        onlyWithSuggestionInput.checked = false;
        searchInput.value = '';
        await loadItems({ preserveSelection: false });
      });

      presetResetBtn?.addEventListener('click', async () => {
        statusInput.value = '';
        splitInput.value = '';
        onlyMissingFinalInput.checked = false;
        onlyWithSuggestionInput.checked = false;
        searchInput.value = '';
        await loadItems({ preserveSelection: false });
      });

      exportBtn?.addEventListener('click', async () => {
        await exportTextDataset();
      });

      exportAssetsBtn?.addEventListener('click', async () => {
        await exportAssetsToTraining();
      });

      exportTrainingJobBtn?.addEventListener('click', async () => {
        await exportTrainingJob();
      });

      labelingPanelTabs.forEach((btn) => {
        btn.addEventListener('click', () => {
          setLabelingPanel(btn.getAttribute('data-labeling-panel-tab') || 'overview');
        });
      });

      root.setAttribute('tabindex', '-1');
      root.addEventListener('keydown', async (event) => {
        const target = event.target;
        const isTextEditing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement;
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
          event.preventDefault();
          if (activeSaveRequest) return;
          const form = activeReviewForm();
          if (!form) return;
          try {
            await submitReview(form, { moveNext: false });
          } catch {
            return;
          }
          return;
        }
        if (!event.altKey || (isTextEditing && !event.ctrlKey && !event.metaKey)) return;
        if (event.key === 'ArrowUp') {
          event.preventDefault();
          await selectRelativeItem(-1);
        }
        if (event.key === 'ArrowDown') {
          event.preventDefault();
          await selectRelativeItem(1);
        }
      });

      await Promise.all([loadSummary(), loadItems({ preserveSelection: false })]);
      setLabelingPanel(activeLabelingPanel);
      root.focus();
    },
  };
}

function pagePipelines(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const role = primaryRole(ctx.state.user);
  const canRelease = hasPermission(ctx.state, 'model.release');
  const heroSummary = role.startsWith('platform_')
    ? '把路由模型、专家模型和阈值规则收敛成可发布的执行方案，并在发布前完成验证。'
    : '维护推理编排方案，确保任务执行时命中正确的模型组合和规则。';
  return {
    html: `
      ${renderPageHero({
        eyebrow: '编排与发布',
        title: '流水线中心',
        summary: heroSummary,
        highlights: ['路由模型 + 专家模型', '统一阈值配置', '发布工作台'],
        actions: [
          { path: 'tasks', label: '去任务中心验证', primary: true },
          { path: 'models', label: '去模型中心' },
        ],
      })}
      <section class="card" data-pipeline-panel="overview">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-pipeline-overview-tab="workbench">工作台概览</button>
          <button class="ghost" type="button" data-pipeline-overview-tab="list">流水线列表</button>
        </div>
        <div id="pipelineOverviewPanelMeta" class="hint">默认先看流水线工作台概览；需要切换版本或做筛选时再进入流水线列表。</div>
      </section>
      <section class="card" data-pipeline-panel="overview" data-pipeline-overview-panel="workbench" hidden>
        <h3>流水线工作台概览</h3>
        <div id="pipelineWorkbenchOverviewWrap">${renderEmpty('先从流水线列表选择一版配置，这里会汇总当前状态和推荐的发布动作。')}</div>
      </section>
      <section class="card">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-pipeline-panel-tab="overview">流水线总览</button>
          <button class="ghost" type="button" data-pipeline-panel-tab="build">注册配置</button>
          <button class="ghost" type="button" data-pipeline-panel-tab="release">发布管理</button>
        </div>
        <div id="pipelinePanelMeta" class="hint">默认先看流水线总览；注册和发布按工作区展开。</div>
      </section>
      <section class="card" data-pipeline-panel="build" hidden>
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-pipeline-build-tab="register">注册流水线</button>
          <button class="ghost" type="button" data-pipeline-build-tab="guide">发布前提示</button>
        </div>
        <div id="pipelineBuildPanelMeta" class="hint">默认先注册流水线；发布前提示按需查看。</div>
      </section>
      <section class="card" data-pipeline-panel="overview" data-pipeline-overview-panel="list" hidden>
        <h3>流水线列表</h3>
        <div id="pipelinesTableWrap">${renderLoading('加载流水线列表...')}</div>
      </section>
      <section class="grid-two" data-pipeline-panel="build" data-pipeline-build-panel="register" hidden>
        <form id="pipelineRegisterForm" class="card form-grid">
          <h3>注册流水线</h3>
          <label>流水线编码</label><input name="pipeline_code" placeholder="railway-mainline" required />
          <label>名称</label><input name="name" placeholder="主线路由流水线" required />
          <label>版本</label><input name="version" placeholder="v1.0.0" required />
          <label>路由模型编号（可选）</label><input name="router_model_id" placeholder="路由模型编号" />
          <details>
            <summary>路由配置与高级参数</summary>
            <div class="details-panel form-grid">
              <label>专家模型分配（JSON）</label><textarea name="expert_map" rows="3">{}</textarea>
              <label>阈值配置（JSON）</label><textarea name="thresholds" rows="2">{}</textarea>
              <label>融合规则（JSON）</label><textarea name="fusion_rules" rows="2">{}</textarea>
              <label>扩展配置（JSON，可空）</label><textarea name="config" rows="4">{}</textarea>
            </div>
          </details>
          <button class="primary" type="submit">注册流水线</button>
          <div id="pipelineRegisterMsg" class="hint"></div>
        </form>
      </section>
      <section class="card" data-pipeline-panel="build" data-pipeline-build-panel="guide" hidden>
        <section class="card">
          <h3>发布前检查</h3>
          <div class="selection-summary">
            <strong>建议顺序</strong>
            <span>先确认路由模型、专家模型和阈值规则齐备，再生成正式流水线版本。</span>
            <span>注册后先去任务中心创建一次验证任务，确认结果符合预期，再执行发布。</span>
            <span>发布时限定目标租户和设备范围，逐步放量，而不是一次性全量下发。</span>
          </div>
          <details>
            <summary>示例专家模型分配</summary>
            <pre>{
  "car_number_ocr": {"model_id": "模型编号"}
}</pre>
          </details>
        </section>
      </section>
      <section class="card" data-pipeline-panel="release" hidden>
        <h3>流水线发布工作台</h3>
        <div id="pipelineReleaseWorkbenchWrap">${renderEmpty('在流水线列表里点“发布工作台”，这里会自动带出推荐设备、买家范围和最近发布配置。')}</div>
      </section>
    `,
    async mount(root) {
      bindPageNavButtons(root, ctx);
      const registerForm = root.querySelector('#pipelineRegisterForm');
      const registerMsg = root.querySelector('#pipelineRegisterMsg');
      const tableWrap = root.querySelector('#pipelinesTableWrap');
      const pipelineWorkbenchOverviewWrap = root.querySelector('#pipelineWorkbenchOverviewWrap');
      const pipelinePanelMeta = root.querySelector('#pipelinePanelMeta');
      const pipelinePanelTabs = [...root.querySelectorAll('[data-pipeline-panel-tab]')];
      const pipelinePanels = [...root.querySelectorAll('[data-pipeline-panel]')];
      const pipelineOverviewPanelMeta = root.querySelector('#pipelineOverviewPanelMeta');
      const pipelineOverviewTabs = [...root.querySelectorAll('[data-pipeline-overview-tab]')];
      const pipelineOverviewPanels = [...root.querySelectorAll('[data-pipeline-overview-panel]')];
      const pipelineBuildPanelMeta = root.querySelector('#pipelineBuildPanelMeta');
      const pipelineBuildTabs = [...root.querySelectorAll('[data-pipeline-build-tab]')];
      const pipelineBuildPanels = [...root.querySelectorAll('[data-pipeline-build-panel]')];
      const releaseWorkbenchWrap = root.querySelector('#pipelineReleaseWorkbenchWrap');
      let activePipelineReleaseId = '';
      let activePipelineId = '';
      let activePipelinePanel = 'overview';
      let activePipelineOverviewPanel = 'workbench';
      let activePipelineBuildPanel = 'register';
      let cachedPipelines = [];

      function setPipelineOverviewPanel(panel) {
        activePipelineOverviewPanel = ['workbench', 'list'].includes(panel) ? panel : 'workbench';
        pipelineOverviewPanels.forEach((section) => {
          section.hidden = section.getAttribute('data-pipeline-overview-panel') !== activePipelineOverviewPanel || activePipelinePanel !== 'overview';
        });
        pipelineOverviewTabs.forEach((button) => {
          const active = button.getAttribute('data-pipeline-overview-tab') === activePipelineOverviewPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (pipelineOverviewPanelMeta) {
          pipelineOverviewPanelMeta.textContent = activePipelineOverviewPanel === 'workbench'
            ? '先看当前焦点流水线的状态、风险和推荐发布动作。'
            : '需要切换版本、筛选或查看全部流水线时，再进入流水线列表。';
        }
      }

      function setPipelineBuildPanel(panel) {
        activePipelineBuildPanel = ['register', 'guide'].includes(panel) ? panel : 'register';
        pipelineBuildPanels.forEach((section) => {
          section.hidden = section.getAttribute('data-pipeline-build-panel') !== activePipelineBuildPanel || activePipelinePanel !== 'build';
        });
        pipelineBuildTabs.forEach((button) => {
          const active = button.getAttribute('data-pipeline-build-tab') === activePipelineBuildPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (pipelineBuildPanelMeta) {
          pipelineBuildPanelMeta.textContent = activePipelineBuildPanel === 'register'
            ? '先注册新的流水线版本，再考虑发布。'
            : '先看发布前检查建议，确认路由模型、专家模型和阈值规则没有遗漏。';
        }
      }

      function setPipelinePanel(panel) {
        activePipelinePanel = ['overview', 'build', 'release'].includes(panel) ? panel : 'overview';
        pipelinePanels.forEach((section) => {
          const panelName = section.getAttribute('data-pipeline-panel');
          if (panelName !== activePipelinePanel) {
            section.hidden = true;
            return;
          }
          if (panelName === 'overview' && section.hasAttribute('data-pipeline-overview-panel')) return;
          if (panelName === 'build' && section.hasAttribute('data-pipeline-build-panel')) return;
          section.hidden = false;
        });
        pipelinePanelTabs.forEach((button) => {
          const active = button.getAttribute('data-pipeline-panel-tab') === activePipelinePanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (pipelinePanelMeta) {
          pipelinePanelMeta.textContent = activePipelinePanel === 'overview'
            ? '先看流水线状态、路由模型和下一步动作。'
            : activePipelinePanel === 'build'
              ? '把注册和路由配置集中处理。'
              : '把发布范围、设备和买家配置放在同一处。';
        }
        if (activePipelinePanel === 'overview') setPipelineOverviewPanel(activePipelineOverviewPanel);
        if (activePipelinePanel === 'build') setPipelineBuildPanel(activePipelineBuildPanel);
      }

      function selectedPipelineRecord() {
        return cachedPipelines.find((row) => row.id === activePipelineId) || null;
      }

      function renderPipelineWorkbenchOverview() {
        if (!pipelineWorkbenchOverviewWrap) return;
        const pipeline = selectedPipelineRecord();
        if (!pipeline) {
          pipelineWorkbenchOverviewWrap.innerHTML = renderWorkbenchOverview({
            title: '还没有选中流水线',
            summary: '先从列表里选一版流水线。发布工作台会自动带出设备、买家和流量范围。',
            metrics: [
              { label: '流水线总数', value: cachedPipelines.length, note: '当前可见' },
              { label: '已发布', value: cachedPipelines.filter((row) => row.status === 'RELEASED').length, note: '正式可用' },
              { label: '下一步', value: '注册 / 发布', note: '也可先去任务中心验证' },
            ],
            actions: [
              { id: 'pipeline-open-register', label: '注册流水线', primary: true },
              { id: 'pipeline-open-tasks', label: '去任务中心验证' },
            ],
          });
        } else {
          pipelineWorkbenchOverviewWrap.innerHTML = renderWorkbenchOverview({
            title: `${pipeline.pipeline_code}:${pipeline.version}`,
            status: enumText('pipeline_status', pipeline.status),
            summary: pipeline.status === 'RELEASED'
              ? '这条流水线已经正式发布。建议继续用真实样本做验证回查，确认路由与专家模型命中稳定。'
              : '这条流水线还没有正式发布。建议先核对路由模型、专家路由和阈值，再进入发布工作台。',
            metrics: [
              { label: '路由模型', value: pipeline.router_model_id ? truncateMiddle(pipeline.router_model_id, 8, 6) : '未配置', note: '当前绑定的路由模型' },
              { label: '阈值版本', value: pipeline.threshold_version || '未声明', note: '当前阈值规则版本' },
              { label: '状态', value: enumText('pipeline_status', pipeline.status), note: pipeline.name || '当前流水线' },
            ],
            actions: [
              { id: 'pipeline-open-release', label: '打开发布工作台', primary: true },
              { id: 'pipeline-open-tasks', label: '去任务中心验证' },
              { id: 'pipeline-open-register', label: '再注册一版' },
            ],
          });
        }
        pipelineWorkbenchOverviewWrap.querySelector('[data-workbench-action="pipeline-open-register"]')?.addEventListener('click', () => {
          setPipelinePanel('build');
          setPipelineBuildPanel('register');
          registerForm?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        pipelineWorkbenchOverviewWrap.querySelector('[data-workbench-action="pipeline-open-tasks"]')?.addEventListener('click', () => {
          ctx.navigate('tasks');
        });
        pipelineWorkbenchOverviewWrap.querySelector('[data-workbench-action="pipeline-open-release"]')?.addEventListener('click', async () => {
          if (!activePipelineId) return;
          try {
            setPipelinePanel('release');
            await openPipelineReleaseWorkbench(activePipelineId);
            releaseWorkbenchWrap?.scrollIntoView({ behavior: 'smooth', block: 'center' });
          } catch (error) {
            ctx.toast(error.message || '流水线发布工作台加载失败', 'error');
          }
        });
      }

      function renderPipelineReleaseWorkbench(workbench) {
        const recommended = workbench?.recommended_release || {};
        const devices = Array.isArray(workbench?.scope_candidates?.devices) ? workbench.scope_candidates.devices : [];
        const buyers = Array.isArray(workbench?.scope_candidates?.buyers) ? workbench.scope_candidates.buyers : [];
        return `
          <div class="release-workbench" data-pipeline-release="${esc(workbench?.pipeline?.id || '')}">
            <div class="approval-workbench-grid">
              <article class="metric-card">
                <h4>流水线</h4>
                <p class="metric">${esc(workbench?.pipeline?.pipeline_code || '-')}</p>
                <span>${esc(workbench?.pipeline?.version || '-')}</span>
              </article>
              <article class="metric-card">
                <h4>目标设备</h4>
                <p class="metric">${esc((recommended.target_devices || []).length || 0)}</p>
                <span>默认沿用最近配置或在线设备</span>
              </article>
              <article class="metric-card">
                <h4>目标买家</h4>
                <p class="metric">${esc((recommended.target_buyers || []).length || 0)}</p>
                <span>默认沿用最近配置或可见买家</span>
              </article>
            </div>
            <div class="form-grid release-workbench-form">
              <div class="grid-two">
                <div class="form-grid">
                  <label>目标设备（逗号分隔）</label>
                  <input id="pipelineReleaseTargetDevices" list="pipelineReleaseDevicesDatalist" value="${esc((recommended.target_devices || []).join(', '))}" placeholder="edge-01" />
                  <datalist id="pipelineReleaseDevicesDatalist">
                    ${devices.map((row) => `<option value="${esc(row.code)}">${esc(row.name || row.code)}</option>`).join('')}
                  </datalist>
                </div>
                <div class="form-grid">
                  <label>目标买家（租户编码，逗号分隔）</label>
                  <input id="pipelineReleaseTargetBuyers" list="pipelineReleaseBuyersDatalist" value="${esc((recommended.target_buyers || []).join(', '))}" placeholder="buyer-demo-001" />
                  <datalist id="pipelineReleaseBuyersDatalist">
                    ${buyers.map((row) => `<option value="${esc(row.tenant_code)}">${esc(row.name || row.tenant_code)}</option>`).join('')}
                  </datalist>
                </div>
              </div>
              <div class="grid-two">
                <div class="form-grid">
                  <label>流量比例</label>
                  <input id="pipelineReleaseTrafficRatio" type="number" min="1" max="100" value="${esc(recommended.traffic_ratio || 100)}" />
                </div>
                <div class="form-grid">
                  <label>发布说明</label>
                  <input id="pipelineReleaseNotes" value="${esc(recommended.release_notes || '控制台发布')}" placeholder="控制台发布" />
                </div>
              </div>
              <div id="pipelineReleaseMsg" class="hint">先确认这条流水线引用的模型都正确，再发布到目标范围。</div>
              <div class="row-actions">
                <button class="primary" type="button" data-confirm-pipeline-release>确认发布</button>
              </div>
            </div>
          </div>
        `;
      }

      async function openPipelineReleaseWorkbench(pipelineId) {
        if (!releaseWorkbenchWrap) return null;
        activePipelineReleaseId = pipelineId;
        activePipelineId = pipelineId;
        setPipelinePanel('release');
        renderPipelineWorkbenchOverview();
        releaseWorkbenchWrap.innerHTML = renderLoading('加载流水线发布工作台...');
        try {
          const workbench = await ctx.get(`/pipelines/${pipelineId}/release-workbench`);
          releaseWorkbenchWrap.innerHTML = renderPipelineReleaseWorkbench(workbench);
          const msg = releaseWorkbenchWrap.querySelector('#pipelineReleaseMsg');
          releaseWorkbenchWrap.querySelector('[data-confirm-pipeline-release]')?.addEventListener('click', async () => {
            const button = releaseWorkbenchWrap.querySelector('[data-confirm-pipeline-release]');
            const payload = {
              pipeline_id: pipelineId,
              target_devices: splitCsv(releaseWorkbenchWrap.querySelector('#pipelineReleaseTargetDevices')?.value || ''),
              target_buyers: splitCsv(releaseWorkbenchWrap.querySelector('#pipelineReleaseTargetBuyers')?.value || ''),
              traffic_ratio: Number(releaseWorkbenchWrap.querySelector('#pipelineReleaseTrafficRatio')?.value || 100) || 100,
              release_notes: String(releaseWorkbenchWrap.querySelector('#pipelineReleaseNotes')?.value || '').trim() || '控制台发布',
            };
            button.disabled = true;
            if (msg) msg.textContent = '正在发布流水线...';
            try {
              await ctx.post('/pipelines/release', payload);
              if (msg) msg.textContent = '流水线发布成功。';
              ctx.toast('流水线已发布');
              await loadPipelines();
              await openPipelineReleaseWorkbench(pipelineId);
            } catch (error) {
              if (msg) msg.textContent = error.message || '流水线发布失败';
              ctx.toast(error.message || '流水线发布失败', 'error');
            } finally {
              button.disabled = false;
            }
          });
          return workbench;
        } catch (error) {
          releaseWorkbenchWrap.innerHTML = renderError(error.message || '流水线发布工作台加载失败');
          throw error;
        }
      }

      async function loadPipelines() {
        tableWrap.innerHTML = renderLoading('加载流水线列表...');
        try {
          const rows = await ctx.get('/pipelines');
          cachedPipelines = rows || [];
          if (!rows.length) {
            tableWrap.innerHTML = renderEmpty('暂无流水线。建议先准备路由模型和专家模型，再注册一条用于验证的流水线');
            activePipelineId = '';
            renderPipelineWorkbenchOverview();
            return;
          }
          if (!activePipelineId || !rows.some((row) => row.id === activePipelineId)) {
            activePipelineId = rows[0].id;
          }
          tableWrap.innerHTML = `
            <div class="selection-grid">
              ${rows.map((row) => `
                <article class="selection-card ${activePipelineId === row.id ? 'selected active-row' : ''}">
                  <div class="selection-card-head selection-card-head--stack">
                    <div class="selection-card-title">
                      <strong>${esc(row.pipeline_code)}</strong>
                      <span class="selection-card-subtitle">${esc(row.version)}</span>
                    </div>
                    <div class="quick-review-statuses">
                      <span class="badge">${esc(enumText('pipeline_status', row.status))}</span>
                      ${row.threshold_version ? `<span class="badge">${esc(row.threshold_version)}</span>` : ''}
                    </div>
                  </div>
                  <div class="selection-card-meta selection-card-meta--compact">
                    <span>路由模型</span><strong class="mono">${esc(truncateMiddle(row.router_model_id || '-', 8, 6))}</strong>
                    <span>阈值版本</span><strong>${esc(row.threshold_version || '未声明')}</strong>
                    <span>配置名</span><strong>${esc(row.name || '-')}</strong>
                    <span>状态说明</span><strong>${esc(row.status === 'RELEASED' ? '正式可用' : '待发布 / 待验证')}</strong>
                  </div>
                  <div class="row-actions">
                    ${canRelease ? `<button class="primary" data-release-pipeline="${esc(row.id)}">${activePipelineId === row.id ? '当前发布工作台' : '发布工作台'}</button>` : '<span class="hint">当前角色无发布权限</span>'}
                  </div>
                  <details class="inline-details">
                    <summary>技术详情</summary>
                    <div class="details-panel">
                      <div class="selection-card-meta selection-card-meta--compact">
                        <span>流水线编号</span><strong class="mono">${esc(row.id)}</strong>
                        <span>路由模型编号</span><strong class="mono">${esc(row.router_model_id || '-')}</strong>
                        <span>阈值版本</span><strong>${esc(row.threshold_version || '-')}</strong>
                        <span>配置名称</span><strong>${esc(row.name || '-')}</strong>
                      </div>
                    </div>
                  </details>
                </article>
              `).join('')}
            </div>
          `;
          if (canRelease) {
            tableWrap.querySelectorAll('[data-release-pipeline]').forEach((btn) => {
              btn.addEventListener('click', async () => {
                const pipelineId = btn.getAttribute('data-release-pipeline');
                try {
                  setPipelinePanel('release');
                  await openPipelineReleaseWorkbench(pipelineId);
                  releaseWorkbenchWrap?.scrollIntoView({ block: 'center', behavior: 'smooth' });
                } catch (error) {
                  ctx.toast(error.message || '流水线发布工作台加载失败', 'error');
                }
              });
            });
          }
          renderPipelineWorkbenchOverview();
        } catch (error) {
          tableWrap.innerHTML = renderError(error.message);
        }
      }

      registerForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        registerMsg.textContent = '';
        const submitBtn = registerForm.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        try {
          const fd = new FormData(registerForm);
          const payload = {
            pipeline_code: String(fd.get('pipeline_code') || '').trim(),
            name: String(fd.get('name') || '').trim(),
            version: String(fd.get('version') || '').trim(),
            router_model_id: String(fd.get('router_model_id') || '').trim() || null,
            expert_map: JSON.parse(String(fd.get('expert_map') || '{}')),
            thresholds: JSON.parse(String(fd.get('thresholds') || '{}')),
            fusion_rules: JSON.parse(String(fd.get('fusion_rules') || '{}')),
            config: JSON.parse(String(fd.get('config') || '{}')),
          };
          const result = await ctx.post('/pipelines/register', payload);
          registerMsg.textContent = `注册成功：${result.pipeline_code}:${result.version}`;
          ctx.toast('流水线注册成功');
          setPipelinePanel('overview');
          await loadPipelines();
          if (canRelease && result.id) {
            await openPipelineReleaseWorkbench(result.id);
          }
        } catch (error) {
          registerMsg.textContent = error.message || '注册失败';
        } finally {
          submitBtn.disabled = false;
        }
      });

      pipelinePanelTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setPipelinePanel(button.getAttribute('data-pipeline-panel-tab') || 'overview');
        });
      });
      pipelineOverviewTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setPipelineOverviewPanel(button.getAttribute('data-pipeline-overview-tab') || 'workbench');
        });
      });
      pipelineBuildTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setPipelineBuildPanel(button.getAttribute('data-pipeline-build-tab') || 'register');
        });
      });

      setPipelinePanel('overview');
      await loadPipelines();
      if (activePipelineReleaseId) {
        await openPipelineReleaseWorkbench(activePipelineReleaseId);
      }
    },
  };
}

function pageTasks(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const role = primaryRole(ctx.state.user);
  const heroSummary = role.startsWith('buyer_')
    ? '上传一张图或视频后直接输入目标，或用已有资产、授权模型 / 流水线创建任务。'
    : role.startsWith('platform_')
      ? '统一创建和跟踪推理任务，既支持一键快速识别，也支持核对模型、流水线、设备与结果交付状态。'
      : '查看任务执行状态与结果回查入口。';
  return {
    html: `
      ${renderPageHero({
        eyebrow: '在线推理与验证',
        title: '任务中心',
        summary: heroSummary,
        highlights: ['明确目标后直接选模型', '创建后等待完成并打开结果', '批量快速识别已收纳'],
        actions: [
          { path: 'assets', label: '先上传资产' },
          { path: 'results', label: '查看结果页', primary: true },
        ],
      })}
      <section class="card">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-task-panel-tab="quick">快速识别</button>
          <button class="ghost" type="button" data-task-panel-tab="create">创建任务</button>
          <button class="ghost" type="button" data-task-panel-tab="models">可选模型</button>
          <button class="ghost" type="button" data-task-panel-tab="list">任务列表</button>
        </div>
        <div id="taskPanelMeta" class="hint">默认先看快速识别；需要精确控制时再切到创建任务或可选模型。</div>
      </section>
      <section class="grid-two" data-task-panel="quick">
        <form id="quickDetectForm" class="card form-grid">
          <h3>快速识别</h3>
          <label>file(上传图片 / 视频，可选)</label>
          <input id="quickDetectFile" type="file" accept=".jpg,.jpeg,.png,.bmp,.mp4,.avi,.mov" multiple />
          <div class="hint">支持单图/短视频，也支持一次上传多张图片或多个短视频；如果资产已经在平台内，也可以直接填写 1-n 个已有资产编号。</div>
          <label>已有资产编号（可选，可多个）</label>
          <input name="asset_id" id="quickDetectAssetInput" list="taskAssetsDatalist" placeholder="资产编号-1, 资产编号-2" />
          <label>object_prompt / intent_text(要识别什么)</label>
          <input name="object_prompt" id="quickDetectPrompt" placeholder="例如 车号 / car / person / train / bus" required />
          <div class="chip-row" id="quickDetectPromptChips">
            ${QUICK_DETECT_PROMPTS.map((item) => `<button type="button" class="ghost chip-btn" data-quick-prompt="${esc(item)}">${esc(item)}</button>`).join('')}
          </div>
          <div id="quickDetectIntentOptions" class="quick-intent-grid"></div>
          <div class="hint">系统会先按你的描述归一化意图并选模。输入“车号 / 车厢号 / 车皮号 / 编号”都会优先走车号 OCR，并直接输出文本。</div>
          <div id="quickDetectModelOptions">${renderEmpty('明确输入“车号”等目标后，这里会直接显示可用模型，不再要求先走一遍目标预检。')}</div>
          <label>设备编号</label>
          <input name="device_code" id="quickDetectDeviceCode" value="edge-01" />
          <div class="row-actions">
            <button class="ghost" type="button" id="quickDetectPreflightBtn">先扫一遍给建议</button>
            <button class="primary" type="submit">开始快速识别</button>
          </div>
          <div id="quickDetectMsg" class="hint"></div>
          <div id="quickDetectPreview" class="quick-detect-preview state empty">选择图片后会在这里显示预览；如果选择视频或已有资产，会显示摘要信息。</div>
        </form>
        <section class="card">
          <h3>快速识别结果</h3>
          <div id="quickDetectResult">${renderEmpty(`上传一张或多张图片 / 视频，输入要识别的对象后，${BRAND_NAME} 会自动选模、创建任务、回传标注图，并支持把本次结果直接打包为训练 / 验证数据集。`)}</div>
        </section>
      </section>
      <section class="grid-two" data-task-panel="create" hidden>
        <form id="taskCreateForm" class="card form-grid">
          <h3>创建任务</h3>
          <label>资产编号</label>
          <input name="asset_id" id="taskAssetInput" list="taskAssetsDatalist" placeholder="资产编号" required />
          <label>任务类型（可选）</label>
          <select name="task_type">
            <option value="">自动选择</option>
            <option value="pipeline_orchestrated">${enumText('task_type', 'pipeline_orchestrated')}</option>
            <option value="object_detect">${enumText('task_type', 'object_detect')}</option>
            <option value="car_number_ocr">${enumText('task_type', 'car_number_ocr')}</option>
            <option value="bolt_missing_detect">${enumText('task_type', 'bolt_missing_detect')}</option>
          </select>
          <label>设备编号</label>
          <input name="device_code" value="edge-01" />
          <label>补充说明</label>
          <input name="intent_text" placeholder="例如：优先识别车号" />
          <details class="inline-details task-create-advanced">
            <summary>高级控制（模型 / 流水线 / 调度）</summary>
            <div class="details-panel">
              <label>流水线编号（优先，可选）</label>
              <input name="pipeline_id" id="taskPipelineInput" list="taskPipelinesDatalist" placeholder="流水线编号，可空" />
              <label>模型编号（可选）</label>
              <input name="model_id" id="taskModelInput" list="taskModelsDatalist" placeholder="模型编号，可空" />
              <label class="checkbox-row"><input type="checkbox" name="use_master_scheduler" /> 启用主调度器自动选模</label>
              <div class="hint">如果你已经明确知道要用哪一版模型，建议直接从下方“可选模型”里点选，避免手输模型编号。</div>
            </div>
          </details>
          <div id="taskCreateAssist" class="selection-summary">当前会根据你填写的资产、模型 / 流水线和任务类型生成一条识别任务。</div>
          <datalist id="taskAssetsDatalist"></datalist>
          <datalist id="taskPipelinesDatalist"></datalist>
          <datalist id="taskModelsDatalist"></datalist>
          <button class="primary" type="submit">创建任务</button>
          <div id="taskCreateMsg" class="hint"></div>
        </form>
        <section class="card">
          <h3>创建结果</h3>
          <div id="taskCreateResult">${renderEmpty('创建成功后会显示任务编号，并提供结果页直达入口')}</div>
        </section>
      </section>
      <section class="card" data-task-panel="models" hidden>
        <h3>可选模型</h3>
        <div class="section-toolbar compact">
          <input id="taskModelSearch" placeholder="搜索模型名称 / 版本 / 任务类型 / 来源" />
          <div id="taskModelMeta" class="hint"></div>
        </div>
        <div id="taskModelLibrary">${renderLoading('加载可选模型...')}</div>
      </section>
      <section class="card" data-task-panel="list" hidden>
        <h3>任务列表</h3>
        <div id="tasksTableWrap">${renderLoading('加载任务列表...')}</div>
      </section>
    `,
    async mount(root) {
      bindPageNavButtons(root, ctx);
      const taskPanelMeta = root.querySelector('#taskPanelMeta');
      const taskPanelTabs = [...root.querySelectorAll('[data-task-panel-tab]')];
      const taskPanels = [...root.querySelectorAll('[data-task-panel]')];
      const quickDetectForm = root.querySelector('#quickDetectForm');
      const quickDetectFile = root.querySelector('#quickDetectFile');
      const quickDetectAssetInput = root.querySelector('#quickDetectAssetInput');
      const quickDetectPrompt = root.querySelector('#quickDetectPrompt');
      const quickDetectIntentOptions = root.querySelector('#quickDetectIntentOptions');
      const quickDetectModelOptions = root.querySelector('#quickDetectModelOptions');
      const quickDetectDeviceCode = root.querySelector('#quickDetectDeviceCode');
      const quickDetectPreflightBtn = root.querySelector('#quickDetectPreflightBtn');
      const quickDetectMsg = root.querySelector('#quickDetectMsg');
      const quickDetectPreview = root.querySelector('#quickDetectPreview');
      const quickDetectResult = root.querySelector('#quickDetectResult');
      const createForm = root.querySelector('#taskCreateForm');
      const createMsg = root.querySelector('#taskCreateMsg');
      const createResult = root.querySelector('#taskCreateResult');
      const taskCreateAssist = root.querySelector('#taskCreateAssist');
      const tableWrap = root.querySelector('#tasksTableWrap');
      const assetsDatalist = root.querySelector('#taskAssetsDatalist');
      const pipelinesDatalist = root.querySelector('#taskPipelinesDatalist');
      const modelsDatalist = root.querySelector('#taskModelsDatalist');
      const taskModelSearch = root.querySelector('#taskModelSearch');
      const taskModelMeta = root.querySelector('#taskModelMeta');
      const taskModelLibrary = root.querySelector('#taskModelLibrary');
      let quickPreviewUrl = '';
      let quickResultScreenshotUrls = [];
      let quickAssetPreviewUrls = [];
      let quickPreflightPreviewUrls = [];
      let quickBatchTaskIds = [];
      let quickDatasetExport = null;
      let quickPreflightOutcomes = [];
      let quickSelectedModelId = '';
      let assistAssets = [];
      let assistModels = [];
      let taskModelQuery = '';
      let activeTaskPanel = 'quick';

      function setTaskPanel(panel) {
        activeTaskPanel = ['quick', 'create', 'models', 'list'].includes(panel) ? panel : 'quick';
        taskPanels.forEach((section) => {
          section.hidden = section.getAttribute('data-task-panel') !== activeTaskPanel;
        });
        taskPanelTabs.forEach((button) => {
          const active = button.getAttribute('data-task-panel-tab') === activeTaskPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (taskPanelMeta) {
          taskPanelMeta.textContent = {
            quick: '先上传图片或已有资产，明确目标后直接识别。',
            create: '当你已经知道要用哪台设备、哪版模型或流水线时，再切到创建任务。',
            models: '先挑模型，再带入创建任务；避免手输模型编号。',
            list: '统一查看已创建任务、等待完成并进入结果页。',
          }[activeTaskPanel];
        }
      }

      function revokeQuickUrls() {
        if (quickPreviewUrl) {
          URL.revokeObjectURL(quickPreviewUrl);
          quickPreviewUrl = '';
        }
        if (quickResultScreenshotUrls.length) {
          quickResultScreenshotUrls.forEach((item) => URL.revokeObjectURL(item));
          quickResultScreenshotUrls = [];
        }
        if (quickAssetPreviewUrls.length) {
          quickAssetPreviewUrls.forEach((item) => URL.revokeObjectURL(item));
          quickAssetPreviewUrls = [];
        }
        if (quickPreflightPreviewUrls.length) {
          quickPreflightPreviewUrls.forEach((item) => URL.revokeObjectURL(item));
          quickPreflightPreviewUrls = [];
        }
      }

      function renderQuickPreview() {
        const files = Array.from(quickDetectFile?.files || []);
        const file = files[0];
        const assetIds = splitCsv(quickDetectAssetInput?.value || '');
        revokeQuickUrls();
        if (!file) {
          if (assetIds.length) {
            quickDetectPreview.className = 'quick-detect-preview';
            quickDetectPreview.innerHTML = `
              <div class="quick-detect-preview-meta">
                <strong>已有资产队列</strong>
                <span class="mono">${esc(assetIds.slice(0, 4).join(', '))}${assetIds.length > 4 ? ' ...' : ''}</span>
                <span>共 ${esc(String(assetIds.length))} 个已有资产</span>
              </div>
            `;
            return;
          }
          quickDetectPreview.className = 'quick-detect-preview state empty';
          quickDetectPreview.textContent = '选择图片后会在这里显示预览；如果选择多个文件、视频或已有资产，会显示批量摘要信息。';
          return;
        }

        quickDetectPreview.className = 'quick-detect-preview';
        if (files.length === 1 && String(file.type || '').startsWith('image/')) {
          quickPreviewUrl = URL.createObjectURL(file);
          quickDetectPreview.innerHTML = `
            <img src="${quickPreviewUrl}" alt="快速识别预览" />
            <div class="quick-detect-preview-meta">
              <strong>${esc(file.name)}</strong>
              <span>${esc(`${Math.max(1, Math.round(file.size / 1024))} KB`)}</span>
            </div>
          `;
          return;
        }

        quickDetectPreview.innerHTML = `
          <div class="quick-detect-preview-meta">
            <strong>${esc(files.length > 1 ? `批量文件队列（${files.length}）` : file.name)}</strong>
            <span>${esc(files.length > 1 ? files.slice(0, 4).map((item) => item.name).join(' / ') : (file.type || 'video/*'))}${files.length > 4 ? ' ...' : ''}</span>
            <span>${esc(files.length > 1 ? `总大小约 ${Math.max(1, Math.round(files.reduce((sum, item) => sum + (item.size || 0), 0) / 1024))} KB` : `${Math.max(1, Math.round(file.size / 1024))} KB`)}</span>
          </div>
        `;
      }

      function renderQuickIntentOptions() {
        if (!quickDetectIntentOptions) return;
        const prompt = String(quickDetectPrompt?.value || '').trim();
        const activeTaskType = inferQuickDetectTaskType(prompt);
        const options = quickIntentOptions(prompt);
        quickDetectIntentOptions.innerHTML = options.map((option) => `
          <button
            type="button"
            class="quick-intent-card ${activeTaskType === option.taskType ? 'active' : ''}"
            data-quick-intent-prompt="${esc(option.prompt)}"
            data-quick-intent-task="${esc(option.taskType)}"
            title="${esc(option.description)}"
          >
            <strong>${esc(option.title)}</strong>
            <span>${esc(option.description)}</span>
          </button>
        `).join('');
        quickDetectIntentOptions.querySelectorAll('[data-quick-intent-prompt]').forEach((button) => {
          button.addEventListener('click', () => {
            if (quickDetectPrompt) quickDetectPrompt.value = button.getAttribute('data-quick-intent-prompt') || '';
            renderQuickIntentOptions();
            renderQuickDetectModelOptions();
          });
        });
      }

      function resolveQuickDetectIntent(prompt) {
        const normalized = normalizeQuickPrompt(prompt);
        const primary = quickIntentOptions(prompt)[0] || null;
        const explicit = !!(normalized && primary && Number(primary.matchScore || 0) > 0);
        return {
          explicit,
          option: primary,
          taskType: primary?.taskType || 'object_detect',
        };
      }

      function quickDetectModelCandidates(prompt) {
        const intent = resolveQuickDetectIntent(prompt);
        if (!intent.explicit) return [];
        return assistModels
          .filter((row) => row.status === 'RELEASED')
          .filter((row) => !row.task_type || row.task_type === intent.taskType)
          .sort((left, right) => {
            const leftExact = left.model_code === intent.taskType ? 1 : 0;
            const rightExact = right.model_code === intent.taskType ? 1 : 0;
            if (leftExact !== rightExact) return rightExact - leftExact;
            return String(right.version || '').localeCompare(String(left.version || ''));
          });
      }

      function serializeQuickDetectModel(row) {
        if (!row) return null;
        return {
          model_id: row.id,
          model_code: row.model_code,
          version: row.version,
          model_hash: row.model_hash,
          task_type: row.task_type || row.plugin_name || null,
          task_type_label: enumText('task_type', row.task_type || row.plugin_name || '-'),
          score: row.status === 'RELEASED' ? 100 : 10,
          reasons: [`显式选择模型 ${row.model_code}:${row.version}`],
          target_devices: row.target_devices || [],
          target_buyers: row.target_buyers || [],
          created_at: row.created_at || null,
        };
      }

      function renderQuickDetectModelOptions() {
        if (!quickDetectModelOptions) return;
        const prompt = String(quickDetectPrompt?.value || '').trim();
        const intent = resolveQuickDetectIntent(prompt);
        if (!prompt) {
          quickDetectModelOptions.innerHTML = renderEmpty('明确输入“车号”等目标后，这里会直接显示可用模型。');
          return;
        }
        if (!intent.explicit) {
          quickDetectModelOptions.innerHTML = `
            <div class="hint">当前描述还比较泛，建议点“先扫一遍给建议”；如果你已经知道就是车号、人员或螺栓缺失，直接把目标写明确即可。</div>
          `;
          return;
        }
        const models = quickDetectModelCandidates(prompt);
        if (!models.length) {
          quickDetectModelOptions.innerHTML = renderEmpty(`当前没有可直接用于 ${enumText('task_type', intent.taskType)} 的已发布模型`);
          return;
        }
        if (!models.some((row) => row.id === quickSelectedModelId)) {
          quickSelectedModelId = models[0].id;
        }
        quickDetectModelOptions.innerHTML = `
          <div class="section-toolbar compact">
            <div class="hint">已明确选择 <strong>${esc(intent.option?.title || enumText('task_type', intent.taskType))}</strong>，可直接选模型并开始识别；不会再强制你先做目标预检。</div>
            <button class="ghost" type="button" data-use-quick-selection>带入下方精确任务</button>
          </div>
          <div class="selection-grid">
            ${models.map((row) => `
              <article class="selection-card ${quickSelectedModelId === row.id ? 'selected' : ''}">
                <div class="selection-card-head selection-card-head--stack">
                  <div class="selection-card-title">
                    <strong title="${esc(`${row.model_code}:${row.version}`)}">${esc(row.model_code)}</strong>
                    <span class="selection-card-subtitle mono" title="${esc(row.version)}">${esc(truncateMiddle(row.version, 18, 10))}</span>
                  </div>
                  <span class="badge">${esc(row.model_code === intent.taskType ? '推荐' : enumText('model_status', row.status || '-'))}</span>
                </div>
                <div class="selection-card-meta selection-card-meta--compact">
                  <span>任务类型</span><strong>${esc(row.task_type || row.plugin_name || '-')}</strong>
                  <span>插件名称</span><strong>${esc(row.plugin_name || '-')}</strong>
                  <span>来源</span><strong>${esc(enumText('model_source_type', (row.platform_meta || {}).model_source_type || '-'))}</strong>
                  <span>模型编号</span><strong class="mono">${esc(truncateMiddle(row.id, 8, 6))}</strong>
                </div>
                <div class="row-actions">
                  <button class="${quickSelectedModelId === row.id ? 'primary' : 'ghost'}" type="button" data-pick-quick-model="${esc(row.id)}">${quickSelectedModelId === row.id ? '当前将使用这版' : '选这版模型'}</button>
                </div>
              </article>
            `).join('')}
          </div>
        `;
        quickDetectModelOptions.querySelectorAll('[data-pick-quick-model]').forEach((button) => {
          button.addEventListener('click', () => {
            quickSelectedModelId = button.getAttribute('data-pick-quick-model') || '';
            renderQuickDetectModelOptions();
          });
        });
        quickDetectModelOptions.querySelector('[data-use-quick-selection]')?.addEventListener('click', applyQuickSelectionToCreateForm);
      }

      function currentQuickWorkItems() {
        const prompt = String(quickDetectPrompt?.value || '').trim();
        const deviceCode = String(quickDetectDeviceCode?.value || 'edge-01').trim() || 'edge-01';
        const existingAssetIds = splitCsv(quickDetectAssetInput?.value || '');
        const files = Array.from(quickDetectFile?.files || []);
        return {
          prompt,
          deviceCode,
          existingAssetIds,
          files,
          items: [
            ...files.map((file) => ({ file, existingAssetId: '', prompt, deviceCode })),
            ...existingAssetIds.map((assetId) => ({ file: null, existingAssetId: assetId, prompt, deviceCode })),
          ],
        };
      }

      function selectedQuickPreflightCandidate(item) {
        if (!item) return null;
        const selectedTaskId = String(item.selectedCandidate?.task_id || '').trim();
        if (selectedTaskId) {
          const matched = (item.candidates || []).find((candidate) => String(candidate?.task_id || '').trim() === selectedTaskId);
          if (matched) return matched;
        }
        return item.selectedCandidate || item.candidates?.[0] || null;
      }

      async function hydrateQuickPreflightOutcome(outcome) {
        if (!outcome?.candidates?.length) return outcome;
        const candidates = await Promise.all((outcome.candidates || []).map(async (candidate) => {
          const previewResultId = String(candidate?.preview_result_id || '').trim();
          if (!previewResultId) return candidate;
          try {
            const previewUrl = await fetchAuthorizedBlobUrl(`/results/${previewResultId}/screenshot`, ctx.token);
            if (previewUrl) quickPreflightPreviewUrls.push(previewUrl);
            return { ...candidate, previewUrl };
          } catch {
            return { ...candidate, previewUrl: '' };
          }
        }));
        const selectedCandidate = selectedQuickPreflightCandidate({ ...outcome, candidates });
        return {
          ...outcome,
          candidates,
          selectedCandidate,
        };
      }

      function renderQuickPreflightOutcomes(outcomes) {
        quickPreflightOutcomes = outcomes;
        quickDetectResult.innerHTML = `
          <div class="quick-detect-result">
            <div class="quick-detect-recommend">预检已经先扫过图片/视频，并生成了候选任务类型与目标标签。先选一个建议，再继续正式识别。</div>
            <div class="row-actions">
              <button class="primary" type="button" id="quickPreflightRunAll">全部按首选建议继续</button>
            </div>
            <div class="quick-detect-batch-list">
              ${outcomes.map((item, outcomeIndex) => `
                <article class="quick-detect-batch-card">
                  ${(() => {
                    const selectedCandidate = selectedQuickPreflightCandidate(item);
                    const selectedCandidateTaskId = String(selectedCandidate?.task_id || '').trim();
                    return `
                  <div class="quick-detect-batch-head">
                    <strong>${esc(item.uploadedAsset?.file_name || item.assetId || `item-${outcomeIndex + 1}`)}</strong>
                    <span class="badge">${esc(String(item.completedOutcome ? '已完成识别' : item.preflight?.timed_out ? '预检超时' : '预检完成'))}</span>
                  </div>
                  <div class="keyvals">
                    <div><span>资产编号</span><strong class="mono">${esc(item.assetId || '-')}</strong></div>
                    <div><span>候选数</span><strong>${esc(String(item.candidates.length))}</strong></div>
                    <div><span>当前建议</span><strong>${esc(enumText('task_type', selectedCandidate?.task_type || '-'))}</strong></div>
                    <div><span>提示词</span><strong>${esc(selectedCandidate?.recommended_prompt || item.prompt || '-')}</strong></div>
                  </div>
                  ${selectedCandidate?.recognized_texts?.length ? `<div class="quick-detect-text-panel"><strong>预检文本</strong><div class="quick-detect-texts">${selectedCandidate.recognized_texts.map((text) => `<span class="badge">${esc(text)}</span>`).join('')}</div></div>` : ''}
                  <div class="quick-preflight-grid">
                    ${item.candidates.map((candidate, candidateIndex) => `
                      <article
                        class="quick-preflight-card ${selectedCandidateTaskId === String(candidate.task_id || '') ? 'active' : ''} ${item.completedOutcome ? 'disabled' : ''}"
                        data-preflight-select="${outcomeIndex}"
                        data-preflight-candidate="${candidateIndex}"
                      >
                        ${candidate.previewUrl ? `<div class="quick-preflight-card-preview"><img src="${candidate.previewUrl}" alt="${esc(candidate.title || enumText('task_type', candidate.task_type))} 预检截图" /></div>` : ''}
                        <strong>${esc(candidate.title || enumText('task_type', candidate.task_type))}</strong>
                        <span>${esc(candidate.summary || '-')}</span>
                        <span>${esc(enumText('task_type', candidate.task_type))}</span>
                        <span>${esc(candidate.matched_labels?.join(', ') || candidate.recognized_texts?.join(', ') || candidate.recommended_prompt || '-')}</span>
                        <div class="quick-preflight-card-actions">
                          <button
                            class="ghost"
                            type="button"
                            data-preflight-pick="${outcomeIndex}"
                            data-preflight-candidate="${candidateIndex}"
                            ${item.completedOutcome ? 'disabled' : ''}
                          >
                            ${selectedCandidateTaskId === String(candidate.task_id || '') ? '当前首选' : '设为首选'}
                          </button>
                          <button
                            class="primary"
                            type="button"
                            data-preflight-run="${outcomeIndex}"
                            data-preflight-candidate="${candidateIndex}"
                            ${item.completedOutcome ? 'disabled' : ''}
                          >
                            按此建议继续
                          </button>
                        </div>
                      </article>
                    `).join('')}
                  </div>
                  `;
                  })()}
                </article>
              `).join('')}
            </div>
          </div>
        `;
        root.querySelectorAll('[data-preflight-select]').forEach((card) => {
          card.addEventListener('click', (event) => {
            if (event.target?.closest?.('button')) return;
            const outcomeIndex = Number(card.getAttribute('data-preflight-select'));
            const candidateIndex = Number(card.getAttribute('data-preflight-candidate'));
            const outcome = quickPreflightOutcomes[outcomeIndex];
            const candidate = outcome?.candidates?.[candidateIndex];
            if (!outcome || !candidate || outcome.completedOutcome) return;
            const merged = [...quickPreflightOutcomes];
            merged[outcomeIndex] = { ...outcome, selectedCandidate: candidate };
            renderQuickPreflightOutcomes(merged);
          });
        });
        root.querySelectorAll('[data-preflight-pick]').forEach((button) => {
          button.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            const outcomeIndex = Number(button.getAttribute('data-preflight-pick'));
            const candidateIndex = Number(button.getAttribute('data-preflight-candidate'));
            const outcome = quickPreflightOutcomes[outcomeIndex];
            const candidate = outcome?.candidates?.[candidateIndex];
            if (!outcome || !candidate) return;
            const merged = [...quickPreflightOutcomes];
            merged[outcomeIndex] = { ...outcome, selectedCandidate: candidate };
            renderQuickPreflightOutcomes(merged);
          });
        });
        root.querySelectorAll('[data-preflight-run]').forEach((button) => {
          button.addEventListener('click', async () => {
            const outcomeIndex = Number(button.getAttribute('data-preflight-run'));
            const candidateIndex = Number(button.getAttribute('data-preflight-candidate'));
            const outcome = quickPreflightOutcomes[outcomeIndex];
            const candidate = outcome?.candidates?.[candidateIndex];
            if (!outcome || !candidate) return;
            button.disabled = true;
            quickDetectMsg.textContent = '';
            try {
              const runOutcome = await runQuickDetectItem({
                file: null,
                existingAssetId: outcome.assetId,
                prompt: candidate.recommended_prompt || outcome.prompt,
                deviceCode: outcome.deviceCode,
                index: outcomeIndex,
                total: quickPreflightOutcomes.length,
                uploadedAsset: outcome.uploadedAsset,
                forcedTaskType: candidate.task_type,
              });
              const merged = [...quickPreflightOutcomes];
              merged[outcomeIndex] = { ...outcome, completedOutcome: runOutcome };
              const finished = merged.filter((item) => item?.completedOutcome?.task?.id);
              if (finished.length === merged.length) {
                renderQuickDetectBatchOutcome(merged.map((item) => item.completedOutcome));
                quickDetectMsg.textContent = `快速识别完成：${finished.length} 条`;
              } else {
                quickPreflightOutcomes = merged;
                quickDetectMsg.textContent = `已完成 ${finished.length}/${merged.length} 条，可继续选择剩余建议`;
                renderQuickPreflightOutcomes(merged);
              }
            } catch (error) {
              quickDetectMsg.textContent = error.message || '快速识别失败';
              ctx.toast(error.message || '快速识别失败', 'error');
            } finally {
              button.disabled = false;
            }
          });
        });
        root.querySelector('#quickPreflightRunAll')?.addEventListener('click', async () => {
          const button = root.querySelector('#quickPreflightRunAll');
          button.disabled = true;
          quickDetectMsg.textContent = '';
          try {
            const finished = [];
            for (let index = 0; index < quickPreflightOutcomes.length; index += 1) {
              const outcome = quickPreflightOutcomes[index];
              if (outcome?.completedOutcome?.task?.id) {
                finished.push(outcome.completedOutcome);
                continue;
              }
              const candidate = selectedQuickPreflightCandidate(outcome);
              if (!candidate) continue;
              finished.push(await runQuickDetectItem({
                file: null,
                existingAssetId: outcome.assetId,
                prompt: candidate.recommended_prompt || outcome.prompt,
                deviceCode: outcome.deviceCode,
                index,
                total: quickPreflightOutcomes.length,
                uploadedAsset: outcome.uploadedAsset,
                forcedTaskType: candidate.task_type,
              }));
            }
            renderQuickDetectBatchOutcome(finished);
            quickDetectMsg.textContent = `快速识别完成：${finished.length} 条`;
            ctx.toast('快速识别完成');
            await Promise.all([loadTasks(), loadAssistData()]);
          } catch (error) {
            quickDetectMsg.textContent = error.message || '快速识别失败';
            quickDetectResult.innerHTML = renderError(error.message || '快速识别失败');
          } finally {
            button.disabled = false;
          }
        });
      }

      const prefillAsset = localStorage.getItem(STORAGE_KEYS.prefillAssetId);
      if (prefillAsset) {
        const assetInput = root.querySelector('#taskAssetInput');
        if (assetInput) assetInput.value = prefillAsset;
        localStorage.removeItem(STORAGE_KEYS.prefillAssetId);
      }
      const prefillTaskModelId = localStorage.getItem(STORAGE_KEYS.prefillTaskModelId);
      const prefillTaskAssetId = localStorage.getItem(STORAGE_KEYS.prefillTaskAssetId);
      const prefillTaskType = localStorage.getItem(STORAGE_KEYS.prefillTaskType);
      const prefillTaskDeviceCode = localStorage.getItem(STORAGE_KEYS.prefillTaskDeviceCode);
      const prefillTaskHint = localStorage.getItem(STORAGE_KEYS.prefillTaskHint);
      if (createForm && (prefillTaskModelId || prefillTaskAssetId || prefillTaskType || prefillTaskDeviceCode || prefillTaskHint)) {
        const modelInput = createForm.querySelector('input[name="model_id"]');
        const assetInput = createForm.querySelector('input[name="asset_id"]');
        const taskTypeInput = createForm.querySelector('select[name="task_type"]');
        const deviceCodeInput = createForm.querySelector('input[name="device_code"]');
        if (modelInput && prefillTaskModelId) modelInput.value = prefillTaskModelId;
        if (assetInput && prefillTaskAssetId) assetInput.value = prefillTaskAssetId;
        if (taskTypeInput && prefillTaskType) taskTypeInput.value = prefillTaskType;
        if (deviceCodeInput && prefillTaskDeviceCode) deviceCodeInput.value = prefillTaskDeviceCode;
        if (createMsg) {
          createMsg.textContent = prefillTaskHint
            || `已预填验证任务：模型 ${prefillTaskModelId || '-'} · 任务类型 ${prefillTaskType || '-'} · 设备 ${prefillTaskDeviceCode || '-'}`;
        }
        localStorage.removeItem(STORAGE_KEYS.prefillTaskModelId);
        localStorage.removeItem(STORAGE_KEYS.prefillTaskAssetId);
        localStorage.removeItem(STORAGE_KEYS.prefillTaskType);
        localStorage.removeItem(STORAGE_KEYS.prefillTaskDeviceCode);
        localStorage.removeItem(STORAGE_KEYS.prefillTaskHint);
      }
      const quickPrefillAsset = localStorage.getItem(STORAGE_KEYS.quickDetectAssetId);
      if (quickPrefillAsset && quickDetectAssetInput) {
        quickDetectAssetInput.value = quickPrefillAsset;
        localStorage.removeItem(STORAGE_KEYS.quickDetectAssetId);
      }
      renderQuickPreview();
      renderQuickIntentOptions();
      renderQuickDetectModelOptions();

      async function loadAssistData() {
        try {
          const [assets, pipelines, models] = await Promise.all([
            ctx.get('/assets?limit=200'),
            ctx.get('/pipelines'),
            ctx.get('/models'),
          ]);
          assistAssets = filterBusinessAssets(assets || []);
          const visibleModels = filterBusinessModels(models || []);
          assistModels = visibleModels;
          assetsDatalist.innerHTML = assistAssets.map((row) => `<option value="${esc(row.id)}">${esc(row.file_name)}</option>`).join('');
          pipelinesDatalist.innerHTML = (pipelines || []).map((row) => `<option value="${esc(row.id)}">${esc(row.pipeline_code)}:${esc(row.version)}</option>`).join('');
          modelsDatalist.innerHTML = visibleModels.map((row) => `<option value="${esc(row.id)}">${esc(row.model_code)}:${esc(row.version)}</option>`).join('');
          renderTaskModelLibrary();
          renderQuickDetectModelOptions();
          renderTaskCreateAssist();
        } catch {
          // Ignore suggestion loading failure.
        }
      }

      function taskCreateInputs() {
        return {
          assetInput: createForm?.querySelector('input[name="asset_id"]'),
          pipelineInput: createForm?.querySelector('input[name="pipeline_id"]'),
          modelInput: createForm?.querySelector('input[name="model_id"]'),
          taskTypeInput: createForm?.querySelector('select[name="task_type"]'),
          schedulerInput: createForm?.querySelector('input[name="use_master_scheduler"]'),
          deviceInput: createForm?.querySelector('input[name="device_code"]'),
          intentInput: createForm?.querySelector('input[name="intent_text"]'),
        };
      }

      function renderTaskCreateAssist() {
        if (!taskCreateAssist) return;
        const {
          assetInput,
          pipelineInput,
          modelInput,
          taskTypeInput,
          schedulerInput,
          deviceInput,
          intentInput,
        } = taskCreateInputs();
        const assetId = String(assetInput?.value || '').trim();
        const pipelineId = String(pipelineInput?.value || '').trim();
        const modelId = String(modelInput?.value || '').trim();
        const taskType = String(taskTypeInput?.value || '').trim();
        const deviceCode = String(deviceInput?.value || '').trim() || 'edge-01';
        const intentText = String(intentInput?.value || '').trim();
        const asset = assistAssets.find((row) => row.id === assetId);
        const model = assistModels.find((row) => row.id === modelId);
        const assetText = assetId ? (asset?.file_name || '已选 1 个资产') : '尚未选择';
        const executionText = model
          ? `${model.model_code}:${model.version}`
          : pipelineId
            ? '按已选流水线执行'
            : schedulerInput?.checked
              ? '由主调度器自动选模'
              : '尚未显式指定';
        const taskTypeText = taskType ? enumText('task_type', taskType) : '自动判断';
        const modeText = pipelineId
          ? '优先按已选流水线执行'
          : schedulerInput?.checked
            ? '优先由主调度器自动选模'
            : model
              ? '直接使用已选模型执行'
              : '按当前表单字段创建任务';
        taskCreateAssist.innerHTML = `
          <strong>${esc(modeText)}</strong>
          <span>${esc(`本次识别：${taskTypeText}`)}</span>
          <span>${esc(`资产：${assetText}`)}</span>
          <span>${esc(`执行方式：${executionText} · 设备 ${deviceCode}`)}</span>
          <span>${esc(intentText ? `识别意图：${intentText}` : '创建后可直接等待执行并打开结果页。')}</span>
        `;
      }

      function fillTaskModelSelection(modelId) {
        const row = assistModels.find((item) => item.id === modelId);
        const { modelInput, taskTypeInput, schedulerInput, intentInput } = taskCreateInputs();
        if (!row || !modelInput) return;
        modelInput.value = row.id;
        if (taskTypeInput && row.task_type) taskTypeInput.value = row.task_type;
        if (schedulerInput) schedulerInput.checked = false;
        if (intentInput && !String(intentInput.value || '').trim()) {
          intentInput.value = row.task_type === 'car_number_ocr' ? '验证候选车号模型' : `验证模型 ${row.model_code}`;
        }
        if (createMsg) {
          createMsg.textContent = `已选择具体模型 ${row.model_code}:${row.version}${row.task_type ? ` · ${row.task_type}` : ''}。创建任务时将直接使用这版模型，不走主调度器。`;
        }
        renderTaskCreateAssist();
        renderTaskModelLibrary();
      }

      function applyQuickSelectionToCreateForm() {
        const prompt = String(quickDetectPrompt?.value || '').trim();
        const intent = resolveQuickDetectIntent(prompt);
        const selectedModel = assistModels.find((row) => row.id === quickSelectedModelId) || null;
        const { assetInput, taskTypeInput, deviceInput, intentInput, schedulerInput } = taskCreateInputs();
        if (selectedModel) fillTaskModelSelection(selectedModel.id);
        if (taskTypeInput && intent.taskType) taskTypeInput.value = intent.taskType;
        if (deviceInput) deviceInput.value = String(quickDetectDeviceCode?.value || 'edge-01').trim() || 'edge-01';
        if (intentInput && prompt) intentInput.value = prompt;
        if (schedulerInput) schedulerInput.checked = false;
        const assetIds = splitCsv(quickDetectAssetInput?.value || '');
        if (assetInput && assetIds.length === 1) assetInput.value = assetIds[0];
        renderTaskCreateAssist();
        if (createMsg) {
          createMsg.textContent = selectedModel
            ? `已从快速识别带入模型 ${selectedModel.model_code}:${selectedModel.version}${assetIds.length === 1 ? ` · asset ${assetIds[0]}` : ''}。`
            : '已把上方快速识别的任务类型、设备和意图带入下方精确任务。';
        }
        setTaskPanel('create');
        createForm?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }

      function clearTaskModelSelection() {
        const { modelInput, schedulerInput } = taskCreateInputs();
        if (modelInput) modelInput.value = '';
        if (schedulerInput) schedulerInput.checked = false;
        if (createMsg) createMsg.textContent = '已取消显式模型选择，可继续手动选模型、选流水线，或启用主调度器。';
        renderTaskCreateAssist();
        renderTaskModelLibrary();
      }

      function renderTaskModelLibrary() {
        if (!taskModelLibrary) return;
        const { modelInput, taskTypeInput, schedulerInput } = taskCreateInputs();
        const currentModelId = String(modelInput?.value || '').trim();
        const requestedTaskType = String(taskTypeInput?.value || '').trim();
        const currentModel = assistModels.find((row) => row.id === currentModelId) || null;
        const q = String(taskModelQuery || '').trim().toLowerCase();
        const filtered = assistModels
          .filter((row) => {
            if (!requestedTaskType || requestedTaskType === 'pipeline_orchestrated') return true;
            return !row.task_type || row.task_type === requestedTaskType;
          })
          .filter((row) => {
            if (!q) return true;
            const haystack = [
              row.model_code,
              row.version,
              row.task_type,
              row.plugin_name,
              row.status,
              (row.platform_meta || {}).model_source_type,
            ]
              .map((item) => String(item || '').toLowerCase())
              .join(' ');
            return haystack.includes(q);
          })
          .sort((left, right) => {
            const leftReleased = left.status === 'RELEASED' ? 1 : 0;
            const rightReleased = right.status === 'RELEASED' ? 1 : 0;
            if (leftReleased !== rightReleased) return rightReleased - leftReleased;
            return String(left.model_code || '').localeCompare(String(right.model_code || '')) || String(right.version || '').localeCompare(String(left.version || ''));
          });
        if (taskModelMeta) {
          taskModelMeta.textContent = `显示 ${filtered.length} / ${assistModels.length} 个模型${requestedTaskType && requestedTaskType !== 'pipeline_orchestrated' ? ` · 当前任务类型 ${requestedTaskType}` : ''}${schedulerInput?.checked ? ' · 当前已勾选主调度器' : ''}`;
        }
        if (!filtered.length) {
          taskModelLibrary.innerHTML = renderEmpty('当前筛选条件下没有可直接点选的模型');
          return;
        }
        const libraryOpen = !currentModel || !!q;
        taskModelLibrary.innerHTML = `
          <div class="task-model-library-stack">
            ${
              currentModel
                ? `
                    <div class="selection-summary task-model-current">
                      <strong>当前已显式选择模型</strong>
                      <span>${esc(`${currentModel.model_code}:${currentModel.version}`)}</span>
                      <span>${esc(`任务类型：${currentModel.task_type || currentModel.plugin_name || '-'} · 来源：${enumText('model_source_type', (currentModel.platform_meta || {}).model_source_type || '-')}`)}</span>
                      <div class="row-actions">
                        <button class="ghost" type="button" data-clear-task-model>取消显式模型</button>
                      </div>
                    </div>
                  `
                : ''
            }
            <details class="inline-details task-model-library-details" ${libraryOpen ? 'open' : ''}>
              <summary>${currentModel ? '展开可选模型库' : '浏览可选模型库'}</summary>
              <div class="details-panel">
                <div class="selection-grid">
                  ${filtered.map((row) => `
                    <article class="selection-card ${currentModelId === row.id ? 'selected' : ''}">
                      <div class="selection-card-head selection-card-head--stack">
                        <div class="selection-card-title">
                          <strong title="${esc(`${row.model_code}:${row.version}`)}">${esc(row.model_code)}</strong>
                          <span class="selection-card-subtitle mono" title="${esc(row.version)}">${esc(truncateMiddle(row.version, 18, 10))}</span>
                        </div>
                        <span class="badge">${esc(enumText('model_status', row.status || '-'))}</span>
                      </div>
                      <div class="selection-card-meta selection-card-meta--compact">
                        <span>任务类型</span><strong>${esc(row.task_type || row.plugin_name || '-')}</strong>
                        <span>来源</span><strong>${esc(enumText('model_source_type', (row.platform_meta || {}).model_source_type || '-'))}</strong>
                        <span>插件</span><strong>${esc(row.plugin_name || '-')}</strong>
                        <span>模型编号</span><strong class="mono">${esc(truncateMiddle(row.id, 8, 6))}</strong>
                      </div>
                      <div class="row-actions">
                        <button class="primary" type="button" data-pick-task-model="${esc(row.id)}">${currentModelId === row.id ? '当前使用中' : '选这版模型'}</button>
                      </div>
                    </article>
                  `).join('')}
                </div>
              </div>
            </details>
          </div>
        `;
        taskModelLibrary.querySelectorAll('[data-pick-task-model]').forEach((button) => {
          button.addEventListener('click', () => fillTaskModelSelection(button.getAttribute('data-pick-task-model') || ''));
        });
        taskModelLibrary.querySelector('[data-clear-task-model]')?.addEventListener('click', clearTaskModelSelection);
      }

      async function waitForQuickDetect(taskId) {
        const deadline = Date.now() + 90_000;
        while (Date.now() < deadline) {
          const task = await ctx.get(`/tasks/${taskId}`);
          const rows = await ctx.get(`/results${toQuery({ task_id: taskId })}`);
          if (rows.length) {
            return { task, rows };
          }
          if (['FAILED', 'CANCELLED'].includes(String(task?.status || ''))) {
            throw new Error(normalizeUiErrorMessage(task?.error_message || `任务执行失败：${task?.status}`));
          }
          await new Promise((resolve) => window.setTimeout(resolve, 2000));
        }
        throw new Error(`快速识别超时，任务 ${taskId} 尚未产出结果`);
      }

      async function waitForTaskTerminal(taskId, { timeoutMs = 90_000 } = {}) {
        const deadline = Date.now() + timeoutMs;
        while (Date.now() < deadline) {
          const task = await ctx.get(`/tasks/${taskId}`);
          const status = String(task?.status || '');
          if (status === 'SUCCEEDED') return task;
          if (['FAILED', 'CANCELLED'].includes(status)) {
            throw new Error(normalizeUiErrorMessage(task?.error_message || `任务执行失败：${status}`));
          }
          await new Promise((resolve) => window.setTimeout(resolve, 2000));
        }
        throw new Error(`任务 ${taskId} 执行超时，尚未产出结果`);
      }

      function syncQuickReviewResult(outcome, { dirty = outcome.reviewDirty } = {}) {
        const editablePredictions = (outcome.predictions || []).map((prediction) => makeReviewPrediction(prediction, outcome.prompt));
        const selectedExists = editablePredictions.some((prediction) => prediction._id === outcome.activePredictionId);
        outcome.activePredictionId = selectedExists ? outcome.activePredictionId : (editablePredictions[0]?._id || null);
        const serializedPredictions = editablePredictions.map(({ _id, source, ...rest }) => ({
          ...rest,
          attributes: {
            ...(cloneJson(rest.attributes || {}) || {}),
            review_source: source || 'manual',
          },
        }));
        const matchedLabels = [...new Set(editablePredictions.map((item) => String(item.label || '').trim()).filter(Boolean))].sort();
        const resultJson = cloneJson(outcome.focus?.result_json || {}) || {};
        const recognizedTexts = collectRecognizedTexts(serializedPredictions, resultJson.summary || {});
        resultJson.predictions = serializedPredictions;
        resultJson.object_count = editablePredictions.length;
        resultJson.matched_labels = matchedLabels;
        if ((resultJson.summary?.task_type || resultJson.task_type || outcome.taskType) === 'car_number_ocr') {
          resultJson.summary = {
            ...(cloneJson(resultJson.summary || {}) || {}),
            task_type: 'car_number_ocr',
            car_number: recognizedTexts[0] || null,
            confidence: serializedPredictions[0]?.score ?? resultJson.summary?.confidence ?? null,
            bbox: serializedPredictions[0]?.bbox ?? resultJson.summary?.bbox ?? null,
          };
        }
        if (dirty) {
          resultJson.review_status = 'pending_review';
          resultJson.manual_review = {
            ...(cloneJson(resultJson.manual_review || {}) || {}),
            status: 'pending_review',
            prediction_count: editablePredictions.length,
          };
        }
        outcome.focus = {
          ...(outcome.focus || {}),
          result_json: resultJson,
        };
        outcome.predictions = editablePredictions;
      }

      function serializeReviewPrediction(prediction) {
        const next = makeReviewPrediction(prediction);
        const bbox = normalizeReviewBBox(next.bbox);
        if (!bbox || bbox[2] <= bbox[0] || bbox[3] <= bbox[1]) {
          throw new Error(`修订框坐标无效：${next.label || 'object'}`);
        }
        return {
          label: String(next.label || '').trim() || 'object',
          text: String(next.text || '').trim() || null,
          score: Number.isFinite(Number(next.score)) ? Number(Number(next.score).toFixed(4)) : 1,
          bbox,
          attributes: {
            ...(cloneJson(next.attributes || {}) || {}),
            ...(String(next.text || '').trim() ? { text: String(next.text || '').trim() } : {}),
            review_source: next.source || 'manual',
          },
        };
      }

      function markQuickReviewDirty(outcome) {
        outcome.reviewDirty = true;
        outcome.reviewStatus = 'pending_review';
        quickDatasetExport = null;
        syncQuickReviewResult(outcome, { dirty: true });
      }

      function quickReviewBoxes(outcome) {
        if (!outcome.previewWidth || !outcome.previewHeight) return '';
        const visiblePredictions = [
          ...(outcome.predictions || []),
          ...(outcome.draftPrediction ? [outcome.draftPrediction] : []),
        ];
        return visiblePredictions
          .filter((prediction) => {
            const bbox = normalizeReviewBBox(prediction?.bbox);
            return bbox && bbox[2] > bbox[0] && bbox[3] > bbox[1];
          })
          .map((prediction) => {
            const bbox = normalizeReviewBBox(prediction.bbox);
            const [x1, y1, x2, y2] = bbox;
            const left = (x1 / outcome.previewWidth) * 100;
            const top = (y1 / outcome.previewHeight) * 100;
            const width = ((x2 - x1) / outcome.previewWidth) * 100;
            const height = ((y2 - y1) / outcome.previewHeight) * 100;
            const score = Number.isFinite(Number(prediction.score)) ? Number(prediction.score).toFixed(2) : '1.00';
            const text = extractPredictionText(prediction);
            return `
              <div
                class="quick-review-box ${prediction.source === 'manual' ? 'manual' : ''} ${prediction.source === 'draft' ? 'draft' : ''} ${prediction._id === outcome.activePredictionId ? 'selected' : ''}"
                style="left:${left}%;top:${top}%;width:${width}%;height:${height}%;"
                data-review-box="${esc(prediction._id)}"
                data-review-index="${esc(String(outcome._index ?? 0))}"
                data-review-pred="${esc(prediction._id)}"
              >
                <span>${esc(text ? `${prediction.label}:${text} ${score}` : `${prediction.label} ${score}`)}</span>
                ${
                  prediction.source !== 'draft'
                    ? `<button class="quick-review-handle" type="button" data-review-handle="${esc(prediction._id)}" data-review-index="${esc(String(outcome._index ?? 0))}" data-review-pred="${esc(prediction._id)}" aria-label="resize box"></button>`
                    : ''
                }
              </div>
            `;
          })
          .join('');
      }

      function bindQuickReviewPreviewMeasurements(outcomes) {
        root.querySelectorAll('[data-review-preview-index]').forEach((img) => {
          const applyPreviewSize = () => {
            const outcomeIndex = Number(img.getAttribute('data-review-preview-index'));
            if (!Number.isFinite(outcomeIndex) || !outcomes[outcomeIndex]) return;
            const width = img.naturalWidth || img.width || 0;
            const height = img.naturalHeight || img.height || 0;
            if (!width || !height) return;
            if (outcomes[outcomeIndex].previewWidth === width && outcomes[outcomeIndex].previewHeight === height) return;
            outcomes[outcomeIndex].previewWidth = width;
            outcomes[outcomeIndex].previewHeight = height;
            window.requestAnimationFrame(() => renderQuickDetectBatchOutcome(outcomes));
          };
          if (img.complete) {
            applyPreviewSize();
          } else {
            img.addEventListener('load', applyPreviewSize, { once: true });
          }
        });
      }

      function bindQuickReviewDrawing(outcomes) {
        root.querySelectorAll('[data-review-canvas]').forEach((canvas) => {
          const outcomeIndex = Number(canvas.getAttribute('data-review-canvas'));
          const outcome = outcomes[outcomeIndex];
          if (!outcome?.drawMode) return;
          const image = canvas.querySelector('[data-review-preview-index]');
          if (!image) return;
          canvas.addEventListener('mousedown', (event) => {
            if (event.button !== 0) return;
            if (event.target?.closest?.('[data-review-box]')) return;
            const rect = image.getBoundingClientRect();
            if (!rect.width || !rect.height || !outcome.previewWidth || !outcome.previewHeight) return;
            const clampPoint = (clientX, clientY) => {
              const x = Math.min(Math.max(clientX - rect.left, 0), rect.width);
              const y = Math.min(Math.max(clientY - rect.top, 0), rect.height);
              return { x, y };
            };
            const start = clampPoint(event.clientX, event.clientY);
            const overlay = canvas.querySelector('.quick-review-overlay');
            if (!overlay) return;
            const draftBox = document.createElement('div');
            draftBox.className = 'quick-review-box draft';
            draftBox.innerHTML = '<span>draft 1.00</span>';
            overlay.appendChild(draftBox);
            const renderDraftBox = (point) => {
              const left = Math.min(start.x, point.x);
              const top = Math.min(start.y, point.y);
              const width = Math.abs(point.x - start.x);
              const height = Math.abs(point.y - start.y);
              draftBox.style.left = `${(left / rect.width) * 100}%`;
              draftBox.style.top = `${(top / rect.height) * 100}%`;
              draftBox.style.width = `${(width / rect.width) * 100}%`;
              draftBox.style.height = `${(height / rect.height) * 100}%`;
            };
            renderDraftBox(start);
            outcome.draftPrediction = makeReviewPrediction({ label: outcome.prompt || 'object', text: '', score: 1, bbox: [0, 0, 1, 1], source: 'draft' }, outcome.prompt);
            const onMove = (moveEvent) => {
              const point = clampPoint(moveEvent.clientX, moveEvent.clientY);
              renderDraftBox(point);
            };
            const onUp = (upEvent) => {
              document.removeEventListener('mousemove', onMove);
              document.removeEventListener('mouseup', onUp);
              const point = clampPoint(upEvent.clientX, upEvent.clientY);
              const left = Math.min(start.x, point.x);
              const top = Math.min(start.y, point.y);
              const right = Math.max(start.x, point.x);
              const bottom = Math.max(start.y, point.y);
              const scaleX = outcome.previewWidth / rect.width;
              const scaleY = outcome.previewHeight / rect.height;
              const bbox = [
                Math.round(left * scaleX),
                Math.round(top * scaleY),
                Math.round(right * scaleX),
                Math.round(bottom * scaleY),
              ];
              outcome.draftPrediction = null;
              outcome.drawMode = false;
              if ((bbox[2] - bbox[0]) >= 4 && (bbox[3] - bbox[1]) >= 4) {
                outcome.predictions = [
                  ...(outcome.predictions || []),
                  makeReviewPrediction(
                    {
                      label: outcome.prompt || 'object',
                      text: '',
                      score: 1,
                      bbox,
                      attributes: { review_source: 'manual' },
                      source: 'manual',
                    },
                    outcome.prompt,
                  ),
                ];
                outcome.activePredictionId = outcome.predictions[outcome.predictions.length - 1]?._id || null;
                markQuickReviewDirty(outcome);
              }
              renderQuickDetectBatchOutcome(outcomes);
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp, { once: true });
          }, { once: true });
        });
      }

      function bindQuickReviewDragResize(outcomes) {
        const startInteraction = (event, outcome, prediction, mode) => {
          if (event.button !== 0) return;
          const canvas = event.currentTarget.closest('.quick-review-canvas');
          const image = canvas?.querySelector('[data-review-preview-index]');
          if (!canvas || !image || !outcome || !prediction || outcome.drawMode) return;
          const rect = image.getBoundingClientRect();
          if (!rect.width || !rect.height || !outcome.previewWidth || !outcome.previewHeight) return;
          event.preventDefault();
          event.stopPropagation();
          const startBBox = normalizeReviewBBox(prediction.bbox);
          if (!startBBox) return;
          outcome.activePredictionId = prediction._id;
          const minBoxSize = 4;
          const scaleX = outcome.previewWidth / rect.width;
          const scaleY = outcome.previewHeight / rect.height;
          const startClientX = event.clientX;
          const startClientY = event.clientY;
          const onMove = (moveEvent) => {
            const dx = Math.round((moveEvent.clientX - startClientX) * scaleX);
            const dy = Math.round((moveEvent.clientY - startClientY) * scaleY);
            let nextBBox = [...startBBox];
            if (mode === 'move') {
              const boxWidth = startBBox[2] - startBBox[0];
              const boxHeight = startBBox[3] - startBBox[1];
              const nextX1 = clampNumber(startBBox[0] + dx, 0, Math.max(0, outcome.previewWidth - boxWidth));
              const nextY1 = clampNumber(startBBox[1] + dy, 0, Math.max(0, outcome.previewHeight - boxHeight));
              nextBBox = [nextX1, nextY1, nextX1 + boxWidth, nextY1 + boxHeight];
            } else if (mode === 'resize') {
              const nextX2 = clampNumber(startBBox[2] + dx, startBBox[0] + minBoxSize, outcome.previewWidth);
              const nextY2 = clampNumber(startBBox[3] + dy, startBBox[1] + minBoxSize, outcome.previewHeight);
              nextBBox = [startBBox[0], startBBox[1], nextX2, nextY2];
            }
            prediction.bbox = nextBBox;
            syncQuickReviewResult(outcome, { dirty: true });
            renderQuickDetectBatchOutcome(outcomes);
          };
          const onUp = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            markQuickReviewDirty(outcome);
            renderQuickDetectBatchOutcome(outcomes);
          };
          document.addEventListener('mousemove', onMove);
          document.addEventListener('mouseup', onUp, { once: true });
        };

        root.querySelectorAll('[data-review-box]').forEach((box) => {
          const outcomeIndex = Number(box.getAttribute('data-review-index'));
          const predictionId = box.getAttribute('data-review-pred') || '';
          const outcome = outcomes[outcomeIndex];
          const prediction = outcome?.predictions?.find((item) => item._id === predictionId);
          if (!outcome || !prediction || outcome.drawMode) return;
          box.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            outcome.activePredictionId = predictionId;
            renderQuickDetectBatchOutcome(outcomes);
          });
          box.addEventListener('mousedown', (event) => {
            if (event.target?.closest?.('[data-review-handle]')) return;
            startInteraction(event, outcome, prediction, 'move');
          });
        });

        root.querySelectorAll('[data-review-handle]').forEach((handle) => {
          const outcomeIndex = Number(handle.getAttribute('data-review-index'));
          const predictionId = handle.getAttribute('data-review-pred') || '';
          const outcome = outcomes[outcomeIndex];
          const prediction = outcome?.predictions?.find((item) => item._id === predictionId);
          if (!outcome || !prediction || outcome.drawMode) return;
          handle.addEventListener('mousedown', (event) => {
            startInteraction(event, outcome, prediction, 'resize');
          });
        });
      }

      async function saveQuickDetectReview(outcomes, outcomeIndex) {
        const outcome = outcomes[outcomeIndex];
        if (!outcome?.focus?.id) throw new Error('当前结果不可修订');
        const activeRule = outcome?.focus?.result_json?.car_number_rule
          || outcome?.focus?.result_json?.summary?.car_number_rule
          || null;
        if (String(outcome?.taskType || '') === 'car_number_ocr') {
          const invalidPrediction = (outcome.predictions || []).find((prediction) => {
            if (String(prediction?.label || '').trim() !== 'car_number') return false;
            const validation = validateCarNumberByRule(extractPredictionText(prediction), activeRule);
            return !!validation.normalized && !validation.valid;
          });
          if (invalidPrediction) {
            const validation = validateCarNumberByRule(extractPredictionText(invalidPrediction), activeRule);
            throw new Error(`当前车号文本不符合规则：${validation.description}`);
          }
        }
        const payload = {
          predictions: (outcome.predictions || []).map((prediction) => serializeReviewPrediction(prediction)),
          note: 'quick_detect_lite_review',
        };
        const saved = await ctx.post(`/results/${outcome.focus.id}/review`, payload);
        const updatedResult = saved?.result;
        if (!updatedResult) throw new Error('修订保存失败');
        const resultJson = updatedResult.result_json || {};
        const currentPredictions = Array.isArray(resultJson.predictions) ? resultJson.predictions : [];
        const autoPredictions = Array.isArray(resultJson.auto_predictions) && resultJson.auto_predictions.length
          ? resultJson.auto_predictions
          : currentPredictions;
        outcome.focus = updatedResult;
        outcome.rows = (outcome.rows || []).map((row) => (row.id === updatedResult.id ? updatedResult : row));
        outcome.predictions = currentPredictions.map((prediction) => makeReviewPrediction(prediction, outcome.prompt));
        outcome.autoPredictions = autoPredictions.map((prediction) => makeReviewPrediction(prediction, outcome.prompt));
        outcome.summary = cloneJson(resultJson.summary || {}) || outcome.summary || {};
        outcome.taskType = String(resultJson.task_type || outcome.summary?.task_type || outcome.taskType || outcome.task?.task_type || 'object_detect');
        outcome.recognizedTexts = collectRecognizedTexts(currentPredictions, outcome.summary);
        outcome.activePredictionId = outcome.predictions[0]?._id || null;
        outcome.reviewDirty = false;
        outcome.reviewStatus = resultJson.review_status || 'revised';
        quickDatasetExport = null;
        syncQuickReviewResult(outcome, { dirty: false });
      }

      async function buildQuickDetectOutcome({ uploadedAsset, recommendation, task, rows, prompt }) {
        const focus = pickQuickDetectResult(rows);
        const resultJson = focus?.result_json || {};
        const predictions = Array.isArray(resultJson.predictions) ? resultJson.predictions : [];
        const autoPredictions = Array.isArray(resultJson.auto_predictions) && resultJson.auto_predictions.length
          ? resultJson.auto_predictions
          : predictions;
        const promptSupported = resultJson.prompt_supported;
        const summary = cloneJson(resultJson.summary || {}) || {};
        const taskType = String(resultJson.task_type || summary.task_type || task.task_type || recommendation?.inferred_task_type || recommendation?.selected_model?.task_type || 'object_detect');
        const recognizedTexts = collectRecognizedTexts(predictions, summary);
        const assetInfo = uploadedAsset || assistAssets.find((row) => row.id === task.asset_id) || {
          id: task.asset_id,
          file_name: resultJson.source_file_name || task.asset_id,
          asset_type: resultJson.source_asset_type || '',
        };
        let screenshotUrl = '';
        let assetPreviewUrl = '';
        if (focus?.id) {
          try {
            screenshotUrl = await fetchAuthorizedBlobUrl(`/results/${focus.id}/screenshot`, ctx.token);
          } catch {
            screenshotUrl = '';
          }
        }
        if (assetInfo?.id && assetInfo.asset_type === 'image') {
          try {
            assetPreviewUrl = await fetchAuthorizedBlobUrl(`/assets/${assetInfo.id}/content`, ctx.token);
          } catch {
            assetPreviewUrl = '';
          }
        }
        if (screenshotUrl) quickResultScreenshotUrls.push(screenshotUrl);
        if (assetPreviewUrl) quickAssetPreviewUrls.push(assetPreviewUrl);
        const outcome = {
          uploadedAsset: assetInfo,
          recommendation,
          task,
          taskType,
          summary,
          recognizedTexts,
          rows,
          focus,
          predictions: predictions.map((prediction) => makeReviewPrediction(prediction, prompt)),
          autoPredictions: autoPredictions.map((prediction) => makeReviewPrediction(prediction, prompt)),
          promptSupported,
          prompt,
          screenshotUrl,
          assetPreviewUrl,
          previewUrl: assetPreviewUrl || screenshotUrl,
          previewSource: assetPreviewUrl ? 'asset' : (screenshotUrl ? 'screenshot' : ''),
          previewWidth: 0,
          previewHeight: 0,
          reviewDirty: false,
          reviewStatus: resultJson.review_status || (resultJson.manual_review ? 'revised' : 'auto'),
          drawMode: false,
          draftPrediction: null,
          activePredictionId: null,
        };
        syncQuickReviewResult(outcome, { dirty: false });
        return outcome;
      }

      function renderQuickDetectBatchOutcome(outcomes) {
        outcomes.forEach((item, outcomeIndex) => {
          item._index = outcomeIndex;
          item.recognizedTexts = collectRecognizedTexts(item.predictions, item.summary || item.focus?.result_json?.summary || {});
          if (typeof item.uiCollapsed !== 'boolean') {
            item.uiCollapsed = outcomes.length > 1 && outcomeIndex > 0;
          }
        });
        quickBatchTaskIds = outcomes.map((item) => item.task.id);
        const totalObjects = outcomes.reduce(
          (sum, item) => sum + Number(item?.predictions?.length ?? item?.focus?.result_json?.object_count ?? 0),
          0,
        );
        const uniqueLabels = [...new Set(outcomes.flatMap((item) => item.predictions.map((pred) => String(pred.label || '').trim()).filter(Boolean)))];
        const uniqueTexts = [...new Set(outcomes.flatMap((item) => item.recognizedTexts || []))];
        const defaultLabel = quickDatasetExport?.asset?.meta?.dataset_label || `quick-detect-${(outcomes[0]?.prompt || 'dataset').replace(/\s+/g, '-')}`;
        const dirtyCount = outcomes.filter((item) => item.reviewDirty).length;

        quickDetectResult.innerHTML = `
          <div class="quick-detect-result">
            <div class="keyvals">
              <div><span>batch_count</span><strong>${esc(String(outcomes.length))}</strong></div>
              <div><span>object_prompt</span><strong>${esc(outcomes[0]?.prompt || '-')}</strong></div>
              <div><span>任务条数</span><strong>${esc(String(outcomes.length))} 条</strong></div>
              <div><span>命中目标数</span><strong>${esc(String(totalObjects))}</strong></div>
            </div>
            <div class="quick-detect-recommend">
              ${
                uniqueTexts.length
                  ? `本次快速识别已输出文本结果：${esc(uniqueTexts.slice(0, 8).join(' / '))}。你可以继续修订框与文本，再把整批结果打包为训练 / 验证数据集版本。`
                  : '本次快速识别已完成。你可以删掉误检、补手工框并保存修订，然后把整批结果打包为训练 / 验证数据集版本。'
              }
            </div>
            <div class="quick-detect-export-bar">
              <input id="quickDetectDatasetLabel" value="${esc(defaultLabel)}" placeholder="quick-detect-dataset" />
              <select id="quickDetectDatasetPurpose">
                <option value="training">training(训练)</option>
                <option value="validation">validation(验证)</option>
                <option value="finetune">finetune(微调)</option>
              </select>
              <label class="checkbox-row quick-detect-checkbox"><input id="quickDetectIncludeScreenshots" type="checkbox" checked /> 包含标注图</label>
              <button class="primary" type="button" id="quickDetectExportDatasetBtn" ${dirtyCount ? 'disabled' : ''}>打包本次结果</button>
            </div>
            <div class="hint">${dirtyCount ? `还有 ${dirtyCount} 条结果存在未保存修订，先保存后再导出版本。` : '所有修订已保存，可直接导出为训练数据集版本。'}</div>
            <div id="quickDetectDatasetExportResult">${
              quickDatasetExport
                ? `
                    <div class="quick-detect-export-result">
                      <div class="keyvals">
                        <div><span>数据集资产编号</span><strong class="mono">${esc(quickDatasetExport.asset.id)}</strong></div>
                        <div><span>数据集版本</span><strong>${esc(`${quickDatasetExport.dataset_version?.dataset_label || '-'}:${quickDatasetExport.dataset_version?.version || '-'}`)}</strong></div>
                        <div><span>资源数</span><strong>${esc(String(quickDatasetExport.asset.meta?.archive_resource_count || 0))}</strong></div>
                        <div><span>标签集合</span><strong>${esc((quickDatasetExport.asset.meta?.label_vocab || []).join(', ') || '-')}</strong></div>
                        <div><span>用途</span><strong>${esc(quickDatasetExport.asset.meta?.asset_purpose || '-')}</strong></div>
                      </div>
                      <div class="row-actions">
                        <button class="primary" type="button" id="openQuickDatasetTraining">去训练中心</button>
                        <button class="ghost" type="button" id="openQuickDatasetAssets">去资产中心</button>
                      </div>
                    </div>
                  `
                : renderEmpty('结果打包后会在这里显示新数据集资产 ID，并提供训练入口')
            }</div>
            <div class="quick-detect-preds">
              ${
                uniqueLabels.length
                  ? uniqueLabels.slice(0, 12).map((label) => `<span class="badge">${esc(label)}</span>`).join('')
                  : `<span class="hint">当前批次暂无命中的目标标签。</span>`
              }
            </div>
            ${
              uniqueTexts.length
                ? `<div class="quick-detect-texts">${uniqueTexts.slice(0, 12).map((text) => `<span class="badge">${esc(text)}</span>`).join('')}</div>`
                : ''
            }
            <div class="quick-detect-batch-list">
              ${outcomes
                .map((item, outcomeIndex) => `
                  <article class="quick-detect-batch-card">
                    <div class="quick-detect-batch-head">
                      <div class="quick-detect-batch-title">
                        <strong title="${esc(item.uploadedAsset?.file_name || item.focus?.result_json?.source_file_name || item.task.id)}">${esc(item.uploadedAsset?.file_name || item.focus?.result_json?.source_file_name || item.task.id)}</strong>
                        <span class="hint">${esc(`${Math.max(0, Number(item.uploadedAsset?.meta?.size || 0) / 1024 | 0)} KB` || '')}</span>
                      </div>
                      <div class="quick-review-statuses">
                        <span class="badge">${esc(enumText('task_status', item.task.status))}</span>
                        <span class="badge">${esc(item.reviewDirty ? '修订未保存' : item.reviewStatus === 'revised' ? '已确认' : '自动结果')}</span>
                        <button class="ghost" type="button" data-toggle-quick-batch="${outcomeIndex}">${item.uiCollapsed ? '展开详情' : '收起详情'}</button>
                      </div>
                    </div>
                    <div class="keyvals compact quick-detect-batch-meta">
                      <div><span>资产编号</span><strong class="mono" title="${esc(item.uploadedAsset?.id || item.task.asset_id || '-')}">${esc(truncateMiddle(item.uploadedAsset?.id || item.task.asset_id || '-', 10, 8))}</strong></div>
                      <div><span>任务编号</span><strong class="mono" title="${esc(item.task.id)}">${esc(truncateMiddle(item.task.id, 10, 8))}</strong></div>
                      <div><span>任务类型</span><strong>${esc(enumText('task_type', item.taskType || item.task.task_type || '-'))}</strong></div>
                      <div><span>当前模型</span><strong title="${esc(`${item.recommendation?.selected_model?.model_code || '-'}:${item.recommendation?.selected_model?.version || '-'}`)}">${esc(item.recommendation?.selected_model?.model_code || '-')} · ${esc(truncateMiddle(item.recommendation?.selected_model?.version || '-', 16, 8))}</strong></div>
                      <div><span>命中目标数</span><strong>${esc(String(item.predictions.length))}</strong></div>
                    </div>
                    <div class="quick-detect-recommend">${esc(item.recommendation?.summary || '已完成自动选模并执行快速识别')}</div>
                    ${
                      item.recognizedTexts?.length
                        ? `<div class="quick-detect-text-panel">
                            <strong>识别文本</strong>
                            <div class="quick-detect-texts">${item.recognizedTexts.map((text) => `<span class="badge">${esc(text)}</span>`).join('')}</div>
                          </div>`
                        : ''
                    }
                    ${
                      item.uiCollapsed
                        ? `<div class="selection-summary quick-detect-collapsed-summary">
                            <strong>已收起该条识别详情</strong>
                            <span>${esc(item.predictions.length ? `当前有 ${item.predictions.length} 个框 / 文本，可点击“展开详情”继续修订。` : '当前没有框，可点击“展开详情”继续手工修订。')}</span>
                          </div>`
                        : `
                          <div class="quick-review-stage">
                            ${
                              item.previewUrl
                                ? `
                                    <div class="quick-review-preview">
                                      <div class="quick-review-canvas ${item.previewSource === 'screenshot' ? 'screenshot' : 'asset'} ${item.drawMode ? 'draw-active' : ''}" data-review-canvas="${outcomeIndex}">
                                        <img data-review-preview-index="${outcomeIndex}" class="quick-review-stage-image" src="${item.previewUrl}" alt="快速识别预览" />
                                        <div class="quick-review-overlay">${quickReviewBoxes(item)}</div>
                                      </div>
                                      <div class="hint">${esc(item.drawMode ? '拖拽图片区域即可新增手工框，松开鼠标后会写入修订列表。' : (item.previewSource === 'asset' ? '当前预览使用原始图片。可直接拖动框体移动，拖右下角缩放。' : '当前预览使用任务标注图。若原始资产不可预览，修订框会叠加显示在标注图上，并支持拖动/缩放。'))}</div>
                                    </div>
                                  `
                                : renderEmpty('当前结果暂无可用预览图')
                            }
                            <div class="quick-review-editor">
                              <div class="quick-review-toolbar">
                                <strong>轻量标注修订</strong>
                                <span class="hint">删掉误检、修正标签或坐标，也可以新增手工框后保存。</span>
                              </div>
                              <div class="quick-detect-preds">
                                ${
                                  item.predictions.length
                                    ? item.predictions
                                        .slice(0, 12)
                                        .map((pred) => `<span class="badge">${esc(predictionBadgeText(pred))}</span>`)
                                        .join('')
                                    : `<span class="hint">${esc(item.promptSupported === false ? '当前提示词不在模型可识别标签内，建议尝试 car / person / train / bus。' : '当前没有框，可手工新增。')}</span>`
                                }
                              </div>
                              <div class="quick-review-rows">
                                ${
                                  item.predictions.length
                                    ? item.predictions.map((pred) => `
                                  <div class="quick-review-row ${item.activePredictionId === pred._id ? 'selected' : ''}">
                                    <div class="quick-review-row-head">
                                      <div class="quick-review-row-summary">
                                        <span class="badge">${esc(pred.source === 'manual' ? 'manual' : 'auto')}</span>
                                        <strong title="${esc(predictionBadgeText(pred))}">${esc(predictionBadgeText(pred))}</strong>
                                      </div>
                                      <div class="row-actions">
                                        <button class="ghost" type="button" data-review-focus="${outcomeIndex}" data-review-pred="${esc(pred._id)}">选中</button>
                                        <button class="ghost" type="button" data-review-remove="${outcomeIndex}" data-review-pred="${esc(pred._id)}">删掉误检</button>
                                      </div>
                                    </div>
                                    <div class="quick-review-fields">
                                      <input data-review-index="${outcomeIndex}" data-review-pred="${esc(pred._id)}" data-review-field="label" value="${esc(pred.label)}" placeholder="label" />
                                      <input data-review-index="${outcomeIndex}" data-review-pred="${esc(pred._id)}" data-review-field="text" value="${esc(pred.text || '')}" placeholder="text / OCR 输出" />
                                      <input data-review-index="${outcomeIndex}" data-review-pred="${esc(pred._id)}" data-review-field="score" type="number" min="0" max="1" step="0.01" value="${esc(Number(pred.score ?? 1).toFixed(2))}" />
                                      <input data-review-index="${outcomeIndex}" data-review-pred="${esc(pred._id)}" data-review-field="x1" type="number" step="1" value="${esc(String(pred.bbox?.[0] ?? 0))}" />
                                      <input data-review-index="${outcomeIndex}" data-review-pred="${esc(pred._id)}" data-review-field="y1" type="number" step="1" value="${esc(String(pred.bbox?.[1] ?? 0))}" />
                                      <input data-review-index="${outcomeIndex}" data-review-pred="${esc(pred._id)}" data-review-field="x2" type="number" step="1" value="${esc(String(pred.bbox?.[2] ?? 0))}" />
                                      <input data-review-index="${outcomeIndex}" data-review-pred="${esc(pred._id)}" data-review-field="y2" type="number" step="1" value="${esc(String(pred.bbox?.[3] ?? 0))}" />
                                    </div>
                                  </div>
                                  `).join('')
                                    : renderEmpty('当前没有检测框，可新增手工框')
                                }
                              </div>
                              <div class="row-actions">
                                <button class="ghost" type="button" data-review-draw="${outcomeIndex}">${item.drawMode ? '取消画框' : '开始画框'}</button>
                                <button class="ghost" type="button" data-review-add="${outcomeIndex}">新增手工框</button>
                                <button class="ghost" type="button" data-review-restore="${outcomeIndex}">恢复自动结果</button>
                                <button class="primary" type="button" data-review-save="${outcomeIndex}">${item.reviewDirty ? '保存修订' : '确认当前结果'}</button>
                              </div>
                            </div>
                          </div>
                        `
                    }
                    <div class="row-actions">
                      <button class="primary" type="button" data-open-quick-result="${esc(item.task.id)}">查看结果页</button>
                      <button class="ghost" type="button" data-open-quick-task="${esc(item.task.id)}">查看任务详情</button>
                    </div>
                  </article>
                `)
                .join('')}
            </div>
          </div>
        `;

        root.querySelectorAll('[data-open-quick-result]').forEach((btn) => {
          btn.addEventListener('click', () => ctx.navigate(`results/task/${btn.getAttribute('data-open-quick-result')}`));
        });
        root.querySelectorAll('[data-open-quick-task]').forEach((btn) => {
          btn.addEventListener('click', () => ctx.navigate(`tasks/${btn.getAttribute('data-open-quick-task')}`));
        });
        root.querySelectorAll('[data-toggle-quick-batch]').forEach((btn) => {
          btn.addEventListener('click', () => {
            const outcomeIndex = Number(btn.getAttribute('data-toggle-quick-batch'));
            const outcome = outcomes[outcomeIndex];
            if (!outcome) return;
            outcome.uiCollapsed = !outcome.uiCollapsed;
            renderQuickDetectBatchOutcome(outcomes);
          });
        });
        root.querySelectorAll('[data-review-field]').forEach((input) => {
          input.addEventListener('change', () => {
            const outcomeIndex = Number(input.getAttribute('data-review-index'));
            const predictionId = input.getAttribute('data-review-pred') || '';
            const field = input.getAttribute('data-review-field') || '';
            const outcome = outcomes[outcomeIndex];
            const prediction = outcome?.predictions?.find((item) => item._id === predictionId);
            if (!outcome || !prediction) return;
            outcome.activePredictionId = predictionId;
            const rawValue = input.value;
            if (field === 'label') prediction.label = rawValue;
            if (field === 'text') prediction.text = rawValue;
            if (field === 'score') prediction.score = rawValue === '' ? 1 : Number(rawValue);
            if (field === 'x1') prediction.bbox[0] = rawValue === '' ? 0 : Number.parseInt(rawValue, 10);
            if (field === 'y1') prediction.bbox[1] = rawValue === '' ? 0 : Number.parseInt(rawValue, 10);
            if (field === 'x2') prediction.bbox[2] = rawValue === '' ? prediction.bbox[0] + 1 : Number.parseInt(rawValue, 10);
            if (field === 'y2') prediction.bbox[3] = rawValue === '' ? prediction.bbox[1] + 1 : Number.parseInt(rawValue, 10);
            markQuickReviewDirty(outcome);
            renderQuickDetectBatchOutcome(outcomes);
          });
        });
        root.querySelectorAll('[data-review-focus]').forEach((button) => {
          button.addEventListener('click', () => {
            const outcomeIndex = Number(button.getAttribute('data-review-focus'));
            const predictionId = button.getAttribute('data-review-pred') || '';
            const outcome = outcomes[outcomeIndex];
            if (!outcome) return;
            outcome.activePredictionId = predictionId;
            renderQuickDetectBatchOutcome(outcomes);
          });
        });
        root.querySelectorAll('[data-review-remove]').forEach((button) => {
          button.addEventListener('click', () => {
            const outcomeIndex = Number(button.getAttribute('data-review-remove'));
            const predictionId = button.getAttribute('data-review-pred') || '';
            const outcome = outcomes[outcomeIndex];
            if (!outcome) return;
            outcome.predictions = (outcome.predictions || []).filter((item) => item._id !== predictionId);
            if (outcome.activePredictionId === predictionId) {
              outcome.activePredictionId = outcome.predictions[0]?._id || null;
            }
            markQuickReviewDirty(outcome);
            renderQuickDetectBatchOutcome(outcomes);
          });
        });
        root.querySelectorAll('[data-review-add]').forEach((button) => {
          button.addEventListener('click', () => {
            const outcomeIndex = Number(button.getAttribute('data-review-add'));
            const outcome = outcomes[outcomeIndex];
            if (!outcome) return;
            const nextPrediction = makeReviewPrediction(
              {
                label: outcome.prompt || 'object',
                text: '',
                score: 1,
                bbox: [24, 24, 160, 160],
                attributes: { review_source: 'manual' },
                source: 'manual',
              },
              outcome.prompt,
            );
            outcome.predictions = [
              ...(outcome.predictions || []),
              nextPrediction,
            ];
            outcome.activePredictionId = nextPrediction._id;
            markQuickReviewDirty(outcome);
            renderQuickDetectBatchOutcome(outcomes);
          });
        });
        root.querySelectorAll('[data-review-draw]').forEach((button) => {
          button.addEventListener('click', () => {
            const outcomeIndex = Number(button.getAttribute('data-review-draw'));
            outcomes.forEach((item, index) => {
              item.drawMode = index === outcomeIndex ? !item.drawMode : false;
              item.draftPrediction = null;
            });
            renderQuickDetectBatchOutcome(outcomes);
          });
        });
        root.querySelectorAll('[data-review-restore]').forEach((button) => {
          button.addEventListener('click', () => {
            const outcomeIndex = Number(button.getAttribute('data-review-restore'));
            const outcome = outcomes[outcomeIndex];
            if (!outcome) return;
            outcome.predictions = (outcome.autoPredictions || []).map((prediction) => makeReviewPrediction(prediction, outcome.prompt));
            outcome.activePredictionId = outcome.predictions[0]?._id || null;
            markQuickReviewDirty(outcome);
            renderQuickDetectBatchOutcome(outcomes);
          });
        });
        root.querySelectorAll('[data-review-save]').forEach((button) => {
          button.addEventListener('click', async () => {
            const outcomeIndex = Number(button.getAttribute('data-review-save'));
            button.disabled = true;
            quickDetectMsg.textContent = '';
            try {
              await saveQuickDetectReview(outcomes, outcomeIndex);
              quickDetectMsg.textContent = `已保存修订：${outcomes[outcomeIndex]?.task?.id || '-'}`;
              ctx.toast('标注修订已保存');
              renderQuickDetectBatchOutcome(outcomes);
            } catch (error) {
              quickDetectMsg.textContent = error.message || '修订保存失败';
              ctx.toast(error.message || '修订保存失败', 'error');
            } finally {
              button.disabled = false;
            }
          });
        });
        bindQuickReviewPreviewMeasurements(outcomes);
        bindQuickReviewDrawing(outcomes);
        bindQuickReviewDragResize(outcomes);
        root.querySelector('#quickDetectExportDatasetBtn')?.addEventListener('click', async () => {
          const exportBtn = root.querySelector('#quickDetectExportDatasetBtn');
          const datasetLabelEl = root.querySelector('#quickDetectDatasetLabel');
          const purposeEl = root.querySelector('#quickDetectDatasetPurpose');
          const includeEl = root.querySelector('#quickDetectIncludeScreenshots');
          exportBtn.disabled = true;
          quickDetectMsg.textContent = '';
          try {
            if (outcomes.some((item) => item.reviewDirty)) {
              throw new Error('请先保存所有未提交的修订，再导出数据集版本');
            }
            const datasetLabel = String(datasetLabelEl?.value || '').trim();
          if (!datasetLabel) throw new Error('请输入数据集标签');
            quickDatasetExport = await ctx.post('/results/export-dataset', {
              task_ids: quickBatchTaskIds,
              dataset_label: datasetLabel,
              asset_purpose: String(purposeEl?.value || 'training').trim() || 'training',
              include_screenshots: includeEl?.checked !== false,
            });
            localStorage.setItem(STORAGE_KEYS.prefillTrainingAssetIds, quickDatasetExport.asset.id);
            localStorage.setItem(STORAGE_KEYS.prefillTrainingDatasetLabel, datasetLabel);
            if (quickDatasetExport.dataset_version?.id) localStorage.setItem(STORAGE_KEYS.prefillTrainingDatasetVersionId, quickDatasetExport.dataset_version.id);
            localStorage.setItem(STORAGE_KEYS.prefillTrainingTargetModelCode, outcomes[0]?.taskType || 'object_detect');
            quickDetectMsg.textContent = `已生成数据集资产：${quickDatasetExport.asset.id}${quickDatasetExport.dataset_version?.version ? ` · ${quickDatasetExport.dataset_version.version}` : ''}`;
            ctx.toast('结果已打包为数据集版本');
            renderQuickDetectBatchOutcome(outcomes);
          } catch (error) {
            quickDetectMsg.textContent = error.message || '结果打包失败';
            ctx.toast(error.message || '结果打包失败', 'error');
          } finally {
            exportBtn.disabled = false;
          }
        });
        root.querySelector('#openQuickDatasetTraining')?.addEventListener('click', () => ctx.navigate('training'));
        root.querySelector('#openQuickDatasetAssets')?.addEventListener('click', () => ctx.navigate('assets'));
      }

      async function runQuickPreflightItem({ file, existingAssetId, prompt, deviceCode, index, total }) {
        let uploadedAsset = null;
        let assetId = existingAssetId;
        if (file) {
          const uploadForm = new FormData();
          uploadForm.set('file', file);
          uploadForm.set('asset_purpose', 'inference');
          uploadForm.set('sensitivity_level', 'L2');
          uploadForm.set('dataset_label', `quick-detect-${prompt || 'preflight'}`);
          uploadForm.set('use_case', 'quick-detect-preflight');
          uploadForm.set('intended_model_code', inferQuickDetectTaskType(prompt));
          quickDetectResult.innerHTML = renderLoading(`正在上传资产 ${index + 1}/${total} ...`);
          uploadedAsset = await ctx.postForm('/assets/upload', uploadForm);
          assetId = uploadedAsset.id;
        }
        quickDetectResult.innerHTML = renderLoading(`正在预检扫描 ${index + 1}/${total} ...`);
        const preflight = await ctx.post('/tasks/preflight-inspect', {
          asset_id: assetId,
          device_code: deviceCode,
          prompt_hint: prompt || null,
        });
        return hydrateQuickPreflightOutcome({
          uploadedAsset: uploadedAsset || assistAssets.find((row) => row.id === assetId) || { id: assetId, file_name: assetId, asset_type: '' },
          assetId,
          prompt,
          deviceCode,
          preflight,
          candidates: preflight?.candidates || [],
          selectedCandidate: preflight?.selected_candidate || preflight?.candidates?.[0] || null,
        });
      }

      async function runQuickDetectItem({ file, existingAssetId, prompt, deviceCode, index, total, uploadedAsset = null, forcedTaskType = null, forcedModel = null, alternatives = [] }) {
        let assetId = existingAssetId;
        const requestedTaskType = forcedTaskType || inferQuickDetectTaskType(prompt);
        if (file) {
          const uploadForm = new FormData();
          uploadForm.set('file', file);
          uploadForm.set('asset_purpose', 'inference');
          uploadForm.set('sensitivity_level', 'L2');
          uploadForm.set('dataset_label', `quick-detect-${prompt}`);
          uploadForm.set('use_case', 'quick-detect');
          uploadForm.set('intended_model_code', requestedTaskType);
          quickDetectResult.innerHTML = renderLoading(`正在上传资产 ${index + 1}/${total} ...`);
          uploadedAsset = await ctx.postForm('/assets/upload', uploadForm);
          assetId = uploadedAsset.id;
        }

        let recommendation = null;
        let selectedModel = forcedModel;
        if (selectedModel?.id) {
          quickDetectResult.innerHTML = renderLoading(`正在使用指定模型 ${index + 1}/${total} ...`);
          recommendation = {
            engine: 'manual-selection',
            requested_task_type: requestedTaskType,
            inferred_task_type: selectedModel.task_type || requestedTaskType,
            confidence: 'manual',
            summary: `已显式选择模型 ${selectedModel.model_code}:${selectedModel.version}`,
            selected_model: serializeQuickDetectModel(selectedModel),
            alternatives: alternatives.map((row) => serializeQuickDetectModel(row)).filter(Boolean),
          };
        } else {
          quickDetectResult.innerHTML = renderLoading(`正在自动选模 ${index + 1}/${total} ...`);
          recommendation = await ctx.post('/tasks/recommend-model', {
            asset_id: assetId,
            task_type: requestedTaskType,
            device_code: deviceCode,
            intent_text: prompt,
            limit: 3,
          });
          if (!recommendation?.selected_model?.model_id) {
            throw new Error('当前没有可用于快速识别的已发布模型');
          }
        }
        const resolvedTaskType = recommendation?.inferred_task_type || recommendation?.selected_model?.task_type || requestedTaskType || 'object_detect';
        const quickContext = resolvedTaskType === 'object_detect' ? { object_prompt: prompt } : {};
        const quickOptions = resolvedTaskType === 'object_detect' ? { object_prompt: prompt } : {};

        quickDetectResult.innerHTML = renderLoading(`正在执行快速识别 ${index + 1}/${total} ...`);
        const task = await ctx.post('/tasks/create', {
          model_id: recommendation?.selected_model?.model_id || null,
          asset_id: assetId,
          task_type: resolvedTaskType,
          device_code: deviceCode,
          use_master_scheduler: false,
          intent_text: prompt,
          context: quickContext,
          options: quickOptions,
          policy: {
            upload_raw_video: false,
            upload_frames: true,
            desensitize_frames: false,
            retention_days: 30,
            quick_detect: { object_prompt: prompt, requested_task_type: requestedTaskType, resolved_task_type: resolvedTaskType },
          },
        });
        localStorage.setItem(STORAGE_KEYS.lastTaskId, task.id);
        const settled = await waitForQuickDetect(task.id);
        return buildQuickDetectOutcome({
          uploadedAsset,
          recommendation,
          task: settled.task,
          rows: settled.rows,
          prompt,
        });
      }

      async function loadTasks() {
        tableWrap.innerHTML = renderLoading('加载任务列表...');
        try {
          const rows = await ctx.get('/tasks');
          const focusedTaskId = String(localStorage.getItem(STORAGE_KEYS.lastTaskId) || '').trim();
          const orderedRows = [...rows].sort((left, right) => {
            const leftFocused = left.id === focusedTaskId ? 1 : 0;
            const rightFocused = right.id === focusedTaskId ? 1 : 0;
            if (leftFocused !== rightFocused) return rightFocused - leftFocused;
            return String(right.created_at || '').localeCompare(String(left.created_at || ''));
          });
          if (!orderedRows.length) {
            tableWrap.innerHTML = renderEmpty('暂无任务，可先去资产中心上传资产，再回到这里创建推理任务');
            return;
          }
          tableWrap.innerHTML = `
            <div class="task-list">
              ${orderedRows.map((row) => `
                <article class="task-list-card ${row.id === focusedTaskId ? 'active-row' : ''}">
                  <div class="task-list-head">
                    <div class="task-list-title">
                      <strong class="mono" title="${esc(row.id)}">${esc(truncateMiddle(row.id, 12, 10))}</strong>
                      <span>${esc(enumText('task_type', row.task_type))}</span>
                    </div>
                    <div class="quick-review-statuses">
                      <span class="badge">${esc(enumText('task_status', row.status))}</span>
                      ${row.device_code ? `<span class="badge">${esc(row.device_code)}</span>` : ''}
                    </div>
                  </div>
                  <div class="keyvals compact">
                    <div><span>创建时间</span><strong>${formatDateTime(row.created_at)}</strong></div>
                    <div><span>执行方式</span><strong>${esc(row.model_id ? '显式模型' : row.pipeline_id ? '流水线' : '自动调度')}</strong></div>
                    <div><span>结果入口</span><strong>${esc(['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(String(row.status || '')) ? '可直接查看' : '等待执行完成')}</strong></div>
                    <div><span>当前设备</span><strong>${esc(row.device_code || '-')}</strong></div>
                  </div>
                  ${row.error_message ? `<div class="quick-detect-recommend">${esc(row.error_message)}</div>` : `<div class="hint">当前任务可查看详情、查看结果，或等待执行完成后再进入结果页。</div>`}
                  <details class="inline-details">
                    <summary>技术详情</summary>
                    <div class="details-panel">
                      <div class="keyvals compact">
                        <div><span>资产编号</span><strong class="mono" title="${esc(row.asset_id || '-')}">${esc(truncateMiddle(row.asset_id || '-', 10, 8))}</strong></div>
                        <div><span>模型编号</span><strong class="mono" title="${esc(row.model_id || '-')}">${esc(truncateMiddle(row.model_id || '-', 10, 8))}</strong></div>
                        <div><span>流水线编号</span><strong class="mono" title="${esc(row.pipeline_id || '-')}">${esc(truncateMiddle(row.pipeline_id || '-', 10, 8))}</strong></div>
                        <div><span>任务编号</span><strong class="mono" title="${esc(row.id)}">${esc(truncateMiddle(row.id, 12, 10))}</strong></div>
                      </div>
                    </div>
                  </details>
                  <div class="row-actions">
                    <button class="primary" data-task-detail="${esc(row.id)}">详情</button>
                    <button class="ghost" data-task-results="${esc(row.id)}">结果</button>
                    <button class="ghost" data-task-wait="${esc(row.id)}">等待完成并打开结果</button>
                  </div>
                </article>
              `).join('')}
            </div>
          `;
          tableWrap.querySelectorAll('[data-task-detail]').forEach((btn) => {
            btn.addEventListener('click', () => ctx.navigate(`tasks/${btn.getAttribute('data-task-detail')}`));
          });
          tableWrap.querySelectorAll('[data-task-results]').forEach((btn) => {
            btn.addEventListener('click', () => ctx.navigate(`results/task/${btn.getAttribute('data-task-results')}`));
          });
          tableWrap.querySelectorAll('[data-task-wait]').forEach((btn) => {
            btn.addEventListener('click', async () => {
              const taskId = btn.getAttribute('data-task-wait') || '';
              btn.disabled = true;
              try {
                await waitForTaskTerminal(taskId);
                ctx.navigate(`results/task/${taskId}`);
              } catch (error) {
                ctx.toast(error.message || '任务执行失败', 'error');
              } finally {
                btn.disabled = false;
              }
            });
          });
        } catch (error) {
          tableWrap.innerHTML = renderError(error.message);
        }
      }

      quickDetectFile?.addEventListener('change', renderQuickPreview);
      quickDetectFile?.addEventListener('change', () => {
        quickPreflightOutcomes = [];
        revokeQuickUrls();
        renderQuickDetectModelOptions();
      });
      quickDetectAssetInput?.addEventListener('input', () => {
        quickPreflightOutcomes = [];
        revokeQuickUrls();
        renderQuickDetectModelOptions();
        if (!quickDetectFile?.files?.length) renderQuickPreview();
      });
      quickDetectDeviceCode?.addEventListener('input', () => {
        quickPreflightOutcomes = [];
        revokeQuickUrls();
      });
      quickDetectPrompt?.addEventListener('input', () => {
        quickPreflightOutcomes = [];
        revokeQuickUrls();
        renderQuickIntentOptions();
        renderQuickDetectModelOptions();
      });
      root.querySelectorAll('[data-quick-prompt]').forEach((btn) => {
        btn.addEventListener('click', () => {
          if (quickDetectPrompt) quickDetectPrompt.value = btn.getAttribute('data-quick-prompt') || '';
          renderQuickIntentOptions();
          renderQuickDetectModelOptions();
        });
      });

      async function performQuickPreflight() {
        const { prompt, items } = currentQuickWorkItems();
        if (!items.length) {
          throw new Error('请上传图片/视频，或填写已有资产编号');
        }
        revokeQuickUrls();
        quickBatchTaskIds = [];
        quickDatasetExport = null;
        quickPreflightOutcomes = [];
        const outcomes = [];
        for (let index = 0; index < items.length; index += 1) {
          outcomes.push(await runQuickPreflightItem({ ...items[index], prompt, index, total: items.length }));
        }
        renderQuickPreflightOutcomes(outcomes);
        quickDetectMsg.textContent = `预检完成：${outcomes.length} 条`;
        ctx.toast('预检完成');
      }

      quickDetectPreflightBtn?.addEventListener('click', async () => {
        quickDetectMsg.textContent = '';
        quickDetectPreflightBtn.disabled = true;
        const submitBtn = quickDetectForm?.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.disabled = true;
        quickDetectResult.innerHTML = renderLoading('正在预检扫描...');
        try {
          await performQuickPreflight();
        } catch (error) {
          quickDetectMsg.textContent = error.message || '预检失败';
          quickDetectResult.innerHTML = renderError(error.message || '预检失败');
        } finally {
          quickDetectPreflightBtn.disabled = false;
          if (submitBtn) submitBtn.disabled = false;
        }
      });

      quickDetectForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        quickDetectMsg.textContent = '';
        const submitBtn = quickDetectForm.querySelector('button[type="submit"]');
        const preflightBtn = quickDetectPreflightBtn;
        submitBtn.disabled = true;
        if (preflightBtn) preflightBtn.disabled = true;
        quickDetectResult.innerHTML = renderLoading('正在准备快速识别...');
        try {
          const { prompt, items, files, existingAssetIds } = currentQuickWorkItems();
          if (!prompt) throw new Error('请输入要识别的对象');
          if (!items.length) throw new Error('请上传图片/视频，或填写已有资产编号');

          const quickIntent = resolveQuickDetectIntent(prompt);
          const directModels = quickDetectModelCandidates(prompt);
          const directModel = directModels.find((row) => row.id === quickSelectedModelId) || directModels[0] || null;

          if (quickIntent.explicit && directModel) {
            quickPreflightOutcomes = [];
            const outcomes = [];
            for (let index = 0; index < items.length; index += 1) {
              outcomes.push(await runQuickDetectItem({
                ...items[index],
                prompt,
                index,
                total: items.length,
                forcedTaskType: quickIntent.taskType,
                forcedModel: directModel,
                alternatives: directModels,
              }));
            }

            if (quickDetectAssetInput && files.length && !existingAssetIds.length && outcomes.length === 1) {
              quickDetectAssetInput.value = outcomes[0]?.uploadedAsset?.id || quickDetectAssetInput.value;
            }

            renderQuickDetectBatchOutcome(outcomes);
            quickDetectMsg.textContent = `已按 ${directModel.model_code}:${directModel.version} 完成 ${outcomes.length} 条快速识别`;
            ctx.toast('快速识别完成');
            await Promise.all([loadTasks(), loadAssistData()]);
            return;
          }

          if (!quickPreflightOutcomes.length) {
            await performQuickPreflight();
            quickDetectMsg.textContent = '预检已完成，请先从候选建议里选择一个方向继续';
            return;
          }

          const outcomes = [];
          for (let index = 0; index < quickPreflightOutcomes.length; index += 1) {
            const preflightOutcome = quickPreflightOutcomes[index];
            if (preflightOutcome?.completedOutcome?.task?.id) {
              outcomes.push(preflightOutcome.completedOutcome);
              continue;
            }
            const candidate = selectedQuickPreflightCandidate(preflightOutcome);
            outcomes.push(await runQuickDetectItem({
              file: null,
              existingAssetId: preflightOutcome.assetId,
              prompt: candidate?.recommended_prompt || prompt,
              deviceCode: preflightOutcome.deviceCode,
              index,
              total: quickPreflightOutcomes.length,
              uploadedAsset: preflightOutcome.uploadedAsset,
              forcedTaskType: candidate?.task_type || null,
            }));
          }

          if (quickDetectAssetInput && files.length && !existingAssetIds.length && outcomes.length === 1) {
            quickDetectAssetInput.value = outcomes[0]?.uploadedAsset?.id || quickDetectAssetInput.value;
          }

          renderQuickDetectBatchOutcome(outcomes);
          quickDetectMsg.textContent = `快速识别完成：${outcomes.length} 条`;
          ctx.toast('快速识别完成');
          await Promise.all([loadTasks(), loadAssistData()]);
        } catch (error) {
          quickDetectMsg.textContent = error.message || '快速识别失败';
          quickDetectResult.innerHTML = renderError(error.message || '快速识别失败');
        } finally {
          submitBtn.disabled = false;
          if (preflightBtn) preflightBtn.disabled = false;
        }
      });

      createForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        createMsg.textContent = '';
        const submitBtn = createForm.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        try {
          const fd = new FormData(createForm);
          const payload = {
            pipeline_id: String(fd.get('pipeline_id') || '').trim() || null,
            model_id: String(fd.get('model_id') || '').trim() || null,
            asset_id: String(fd.get('asset_id') || '').trim(),
            task_type: String(fd.get('task_type') || '').trim() || null,
            device_code: String(fd.get('device_code') || '').trim() || null,
            use_master_scheduler: fd.get('use_master_scheduler') === 'on',
            intent_text: String(fd.get('intent_text') || '').trim() || null,
            context: {},
            options: {},
          };
          const created = await ctx.post('/tasks/create', payload);
          createMsg.textContent = '创建成功';
          createResult.innerHTML = `
            <div class="selection-summary task-create-success">
              <strong>任务已创建</strong>
              <span>${esc(`系统已生成 ${enumText('task_type', created.task_type)} 任务，可直接等待执行完成后打开结果页。`)}</span>
            </div>
            <div class="keyvals">
              <div><span>任务编号</span><strong class="mono">${esc(created.id)}</strong></div>
              <div><span>状态</span><strong>${esc(enumText('task_status', created.status))}</strong></div>
              <div><span>任务类型</span><strong>${esc(enumText('task_type', created.task_type))}</strong></div>
            </div>
            <div class="row-actions">
              <button class="primary" id="openTaskDetail">查看任务详情</button>
              <button class="ghost" id="openTaskResults">查看任务结果</button>
              <button class="ghost" id="waitTaskResults">等待执行并打开结果页</button>
            </div>
          `;
          setTaskPanel('list');
          root.querySelector('#openTaskDetail')?.addEventListener('click', () => ctx.navigate(`tasks/${created.id}`));
          root.querySelector('#openTaskResults')?.addEventListener('click', () => ctx.navigate(`results/task/${created.id}`));
          root.querySelector('#waitTaskResults')?.addEventListener('click', async (event) => {
            const button = event.currentTarget;
            button.disabled = true;
            createMsg.textContent = '等待任务执行完成...';
            try {
              await waitForTaskTerminal(created.id);
              createMsg.textContent = `任务 ${created.id} 已完成，正在打开结果页`;
              ctx.navigate(`results/task/${created.id}`);
            } catch (error) {
              createMsg.textContent = error.message || '任务执行失败';
              ctx.toast(error.message || '任务执行失败', 'error');
            } finally {
              button.disabled = false;
            }
          });
          localStorage.setItem(STORAGE_KEYS.lastTaskId, created.id);
          renderTaskCreateAssist();
          await loadTasks();
        } catch (error) {
          createMsg.textContent = error.message || '创建失败';
        } finally {
          submitBtn.disabled = false;
        }
      });

      taskModelSearch?.addEventListener('input', () => {
        taskModelQuery = taskModelSearch.value || '';
        renderTaskModelLibrary();
      });
      taskPanelTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setTaskPanel(button.getAttribute('data-task-panel-tab') || 'quick');
        });
      });
      createForm?.querySelector('select[name="task_type"]')?.addEventListener('change', renderTaskModelLibrary);
      createForm?.querySelector('input[name="use_master_scheduler"]')?.addEventListener('change', renderTaskModelLibrary);
      createForm?.querySelectorAll('input, select').forEach((input) => {
        input.addEventListener('input', renderTaskCreateAssist);
        input.addEventListener('change', renderTaskCreateAssist);
      });

      renderTaskCreateAssist();
      setTaskPanel('quick');

      await Promise.all([loadTasks(), loadAssistData()]);
    },
  };
}

function pageTaskDetail(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const taskId = route.params?.task_id;
  return {
    html: `
      ${renderPageHero({
        eyebrow: '任务执行追踪',
        title: '任务详情',
        summary: '先看执行结论、识别摘要和结果入口；原始任务字段与执行上下文后置到技术详情。',
        highlights: ['执行结论优先', '可直接去结果页', '技术字段按需展开'],
        actions: [
          { path: 'tasks', label: '返回任务中心' },
          { path: `results/task/${taskId}`, label: '打开结果页', primary: true },
        ],
      })}
      <section class="card" id="taskDetailWrap">${renderLoading('加载任务详情...')}</section>
    `,
    async mount(root) {
      bindPageNavButtons(root, ctx);
      const wrap = root.querySelector('#taskDetailWrap');
      async function waitForDetailTaskTerminal(id, { timeoutMs = 90_000 } = {}) {
        const deadline = Date.now() + timeoutMs;
        while (Date.now() < deadline) {
          const task = await ctx.get(`/tasks/${id}`);
          const status = String(task?.status || '');
          if (status === 'SUCCEEDED') return task;
          if (['FAILED', 'CANCELLED'].includes(status)) {
            throw new Error(normalizeUiErrorMessage(task?.error_message || `任务执行失败：${status}`));
          }
          await new Promise((resolve) => window.setTimeout(resolve, 2000));
        }
        throw new Error(`任务 ${id} 等待超时，请稍后刷新重试`);
      }
      try {
        const [data, rows] = await Promise.all([
          ctx.get(`/tasks/${taskId}`),
          ctx.get(`/results${toQuery({ task_id: taskId })}`).catch(() => []),
        ]);
        const summaries = (rows || []).map((row) => summarizeResultRow(row));
        const totalObjects = summaries.reduce((sum, item) => sum + Number(item.objectCount || 0), 0);
        const recognizedTexts = [...new Set(summaries.flatMap((item) => item.recognizedTexts || []).filter(Boolean))];
        wrap.innerHTML = `
          <section class="card">
            <div class="workspace-switcher">
              <button class="ghost" type="button" data-task-detail-panel-tab="summary">执行结论</button>
              <button class="ghost" type="button" data-task-detail-panel-tab="actions">下一步动作</button>
              <button class="ghost" type="button" data-task-detail-panel-tab="tech">技术详情</button>
            </div>
            <div id="taskDetailPanelMeta" class="hint">默认先看执行结论；需要继续追踪结果时再切到下一步动作，原始字段和 JSON 放到技术详情。</div>
          </section>
          <section class="card" data-task-detail-panel="summary">
            <div class="task-list-card">
              <div class="task-list-head">
                <div class="task-list-title">
                  <strong class="mono" title="${esc(data.id)}">${esc(truncateMiddle(data.id, 12, 10))}</strong>
                  <span>${esc(enumText('task_type', data.task_type))}</span>
                </div>
                <div class="quick-review-statuses">
                  <span class="badge">${esc(enumText('task_status', data.status))}</span>
                  ${data.device_code ? `<span class="badge">${esc(data.device_code)}</span>` : ''}
                </div>
              </div>
              <div class="keyvals compact result-summary-keyvals">
                <div><span>结果条数</span><strong>${esc(String((rows || []).length))}</strong></div>
                <div><span>创建时间</span><strong>${formatDateTime(data.created_at)}</strong></div>
                <div><span>开始时间</span><strong>${formatDateTime(data.started_at)}</strong></div>
                <div><span>完成时间</span><strong>${formatDateTime(data.finished_at)}</strong></div>
              </div>
              ${data.error_message ? `<div class="quick-detect-recommend">${esc(data.error_message)}</div>` : '<div class="hint">如果任务还在执行中，可切到“下一步动作”直接等待完成并打开结果页。</div>'}
            </div>
            <div class="selection-summary task-detail-summary">
              <strong>执行摘要</strong>
              <span>${esc(`当前已回查到 ${(rows || []).length} 条结果，累计命中 ${totalObjects} 个对象 / 文本。`)}</span>
              <span>${esc(recognizedTexts.length ? `识别文本：${recognizedTexts.slice(0, 6).join(' / ')}` : '当前还没有 OCR 文本摘要。')}</span>
            </div>
            ${recognizedTexts.length ? `<div class="result-text-ribbon task-detail-ribbon">${recognizedTexts.slice(0, 10).map((text) => `<span class="badge">${esc(text)}</span>`).join('')}</div>` : ''}
          </section>
          <section class="card" data-task-detail-panel="actions" hidden>
            <div class="selection-summary">
              <strong>继续处理这条任务</strong>
              <span>${esc(data.status === 'SUCCEEDED' ? '任务已经完成，可以直接查看结果或回到任务中心继续创建新任务。' : '任务还在执行中，可以等待完成后直接打开结果页。')}</span>
            </div>
            <div class="row-actions">
              <button class="ghost" id="backTaskList">返回任务中心</button>
              <button class="primary" id="goTaskResult">查看结果</button>
              <button class="ghost" id="waitTaskResult">等待完成并打开结果页</button>
            </div>
          </section>
          <section class="card" data-task-detail-panel="tech" hidden>
            <details class="inline-details" open>
              <summary>技术详情</summary>
              <div class="keyvals compact result-tech-keyvals">
                <div><span>资产编号</span><strong class="mono" title="${esc(data.asset_id || '-')}">${esc(truncateMiddle(data.asset_id || '-', 10, 8))}</strong></div>
                <div><span>模型编号</span><strong class="mono" title="${esc(data.model_id || '-')}">${esc(truncateMiddle(data.model_id || '-', 10, 8))}</strong></div>
                <div><span>流水线编号</span><strong class="mono" title="${esc(data.pipeline_id || '-')}">${esc(truncateMiddle(data.pipeline_id || '-', 10, 8))}</strong></div>
              </div>
              <pre>${esc(safeJson(data))}</pre>
            </details>
          </section>
        `;
        const taskDetailPanelMeta = root.querySelector('#taskDetailPanelMeta');
        const taskDetailPanelTabs = Array.from(root.querySelectorAll('[data-task-detail-panel-tab]'));
        const taskDetailPanels = Array.from(root.querySelectorAll('[data-task-detail-panel]'));
        let activeTaskDetailPanel = 'summary';
        function setTaskDetailPanel(panel) {
          activeTaskDetailPanel = panel;
          taskDetailPanelTabs.forEach((btn) => {
            const active = btn.getAttribute('data-task-detail-panel-tab') === panel;
            btn.classList.toggle('primary', active);
            btn.classList.toggle('ghost', !active);
          });
          taskDetailPanels.forEach((section) => {
            section.hidden = section.getAttribute('data-task-detail-panel') !== panel;
          });
          if (taskDetailPanelMeta) {
            taskDetailPanelMeta.textContent = ({
              summary: '先看任务状态、识别摘要和当前结果概况。',
              actions: '在这里决定是返回任务中心、直接查看结果，还是等待任务完成。',
              tech: '只有排障或核对原始字段时再看这里的技术详情。',
            })[panel] || '按当前分区继续查看。';
          }
        }
        taskDetailPanelTabs.forEach((btn) => {
          btn.addEventListener('click', () => {
            setTaskDetailPanel(btn.getAttribute('data-task-detail-panel-tab') || 'summary');
          });
        });
        setTaskDetailPanel(activeTaskDetailPanel);
        root.querySelector('#backTaskList')?.addEventListener('click', () => ctx.navigate('tasks'));
        root.querySelector('#goTaskResult')?.addEventListener('click', () => ctx.navigate(`results/task/${taskId}`));
        root.querySelector('#waitTaskResult')?.addEventListener('click', async (event) => {
          const button = event.currentTarget;
          button.disabled = true;
          try {
            await waitForDetailTaskTerminal(taskId);
            ctx.navigate(`results/task/${taskId}`);
          } catch (error) {
            ctx.toast(error.message || '任务执行失败', 'error');
          } finally {
            button.disabled = false;
          }
        });
      } catch (error) {
        wrap.innerHTML = renderError(error.message);
      }
    },
  };
}

function buildResultListHtml(rows, modelInsights = {}) {
  if (!rows.length) return renderEmpty('暂无结果，请确认任务已执行完成，或返回任务中心重新创建任务');
  const summaries = rows.map((row) => summarizeResultRow(row));
  const allTexts = [...new Set(summaries.flatMap((item) => item.recognizedTexts))];
  const uniqueModelIds = [...new Set(rows.map((row) => String(row.model_id || '').trim()).filter(Boolean))];

  return `
    <section class="card">
      <div class="workspace-switcher">
        <button class="ghost" type="button" data-result-list-panel-tab="overview">结果概览</button>
        <button class="ghost" type="button" data-result-list-panel-tab="models">模型表现</button>
        <button class="ghost" type="button" data-result-list-panel-tab="items">单条结果</button>
      </div>
      <div id="resultListPanelMeta" class="hint">默认先看整体结论；需要核对模型表现或逐条复核时再进入对应分区。</div>
    </section>
    <section data-result-list-panel="overview">
      ${renderResultOverviewCards(rows, summaries)}
      ${
        allTexts.length
          ? `<section class="result-text-ribbon">${allTexts.slice(0, 12).map((text) => `<span class="badge">${esc(text)}</span>`).join('')}</section>`
          : ''
      }
      ${renderResultValidationConclusion(rows, summaries, modelInsights)}
    </section>
    <section data-result-list-panel="models" hidden>
      ${
        uniqueModelIds.length
          ? `
              <section class="result-model-insights">
                ${uniqueModelIds
                  .map((modelId) => renderModelInsightBlock(modelId, modelInsights[modelId]))
                  .filter(Boolean)
                  .join('')}
              </section>
            `
          : renderEmpty('当前结果没有关联模型表现摘要。')
      }
    </section>
    <section data-result-list-panel="items" hidden>
      <div class="result-list">
      ${summaries.map((item) => {
        const row = item.row;
        const labelCloud = renderResultLabelCloud(item);
        const readiness = modelInsights[row.model_id] || null;
        const validationMetrics = readiness?.validation_report?.metrics || {};
        return `
          <article class="result-card">
            <div class="result-head">
              <div>
                <strong>${esc(renderResultCardTitle(item))}</strong>
                <p class="muted">${esc(`${resultStageLabel(item.stage)} · ${formatDateTime(row.created_at)}`)}</p>
              </div>
              <div class="quick-review-statuses">
                ${String(row.alert_level || 'INFO').toUpperCase() !== 'INFO' ? `<span class="badge">${esc(row.alert_level || 'INFO')}</span>` : ''}
                ${item.ocrRiskLabel ? `<span class="badge">${esc(item.ocrRiskLabel)}</span>` : ''}
              </div>
            </div>
            ${renderResultSummaryStats(item, validationMetrics)}
            ${
              item.recognizedTexts.length
                ? `
                    <div class="quick-detect-text-panel">
                      <strong>识别文本</strong>
                      <div class="quick-detect-texts">${item.recognizedTexts.map((text) => `<span class="badge">${esc(text)}</span>`).join('')}</div>
                    </div>
                  `
                : ''
            }
            ${renderResultOcrSignal(item)}
            <div class="result-card-grid">
              ${
                row._screenshot_preview_url
                  ? `
                      <section class="result-card-panel result-shot-panel">
                        <div class="result-panel-head">
                          <strong>截图预览</strong>
                          <span>点击可放大</span>
                        </div>
                        <button class="result-shot-link" type="button" data-open-shot-url="${esc(row._screenshot_preview_url)}" title="打开结果截图">
                          <img src="${esc(row._screenshot_preview_url)}" alt="结果截图预览" loading="lazy" />
                        </button>
                      </section>
                    `
                  : ''
              }
              <section class="result-card-panel">
                <div class="result-panel-head">
                  <strong>${esc(labelCloud.title)}</strong>
                  <span>${esc(labelCloud.headerLabel)}</span>
                </div>
                ${labelCloud.html}
              </section>
              <section class="result-card-panel">
                <div class="result-panel-head">
                  <strong>置信度分布</strong>
                  <span>${esc(item.predictions.length ? `${item.predictions.length} 条预测` : '暂无')}</span>
                </div>
                ${renderResultConfidenceBars(item.predictions)}
              </section>
            </div>
            <div class="row-actions">
              ${
                row._screenshot_preview_url
                  ? `<button class="ghost" type="button" data-open-shot-url="${esc(row._screenshot_preview_url)}">在新窗口打开截图</button>`
                  : row.screenshot_uri
                    ? `<button class="ghost" type="button" data-open-shot="${esc(row.id)}">查看截图</button>`
                    : '<span class="hint">无截图</span>'
              }
              <details class="inline-details">
                <summary>技术详情</summary>
                <div class="details-panel">
                  <div class="keyvals compact result-tech-keyvals">
                    <div><span>结果编号</span><strong class="mono">${esc(row.id)}</strong></div>
                    <div><span>模型编号</span><strong class="mono">${esc(truncateMiddle(row.model_id || '-', 10, 8))}</strong></div>
                    <div><span>告警级别</span><strong>${esc(row.alert_level || 'INFO')}</strong></div>
                    <div><span>结果阶段</span><strong>${esc(item.stage)}</strong></div>
                  </div>
                  <details open>
                    <summary>原始结果数据</summary>
                    <pre>${esc(safeJson(row.result_json))}</pre>
                  </details>
                  ${readiness ? `<details><summary>模型验证详情</summary><pre>${esc(safeJson(readiness.validation_report || {}))}</pre></details>` : ''}
                </div>
              </details>
            </div>
          </article>
        `;
      }).join('')}
      </div>
    </section>
  `;
}

function pageResults(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const role = primaryRole(ctx.state.user);
  const defaultTaskId = route.params?.task_id || localStorage.getItem(STORAGE_KEYS.lastTaskId) || '';
  const heroSummary = role.startsWith('buyer_')
    ? '按任务编号回查结构化结果、截图摘要和导出信息，支撑客户验收与复核。'
    : role.startsWith('platform_')
      ? '统一查看执行结果、导出摘要和截图证据，验证模型交付与任务产出。'
      : '查看任务输出、截图摘要与导出信息。';
  return {
    html: `
      ${renderPageHero({
        eyebrow: '结果复核与训练数据',
        title: '结果中心',
        summary: heroSummary,
        highlights: ['先看验证结论', '低置信度优先复核', '确认后可转成训练数据'],
        actions: [
          { path: 'tasks', label: '返回任务中心' },
          { path: 'training', label: '去训练中心', primary: true },
        ],
      })}
      <section class="card">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-result-panel-tab="query">查询结果</button>
          <button class="ghost" type="button" data-result-panel-tab="actions">下一步动作</button>
          <button class="ghost" type="button" data-result-panel-tab="dataset">变成训练数据</button>
          <button class="ghost" type="button" data-result-panel-tab="list">结果列表</button>
        </div>
        <div id="resultPanelMeta" class="hint">${esc(defaultTaskId ? '默认先看结果列表；要继续处理时再切到下一步动作或训练数据。' : '默认先查询结果；查到任务后再继续看下一步动作和训练数据。')}</div>
      </section>
      <section class="card" data-result-panel="query">
        <form id="resultQueryForm" class="inline-form">
          <input id="resultTaskId" name="task_id" placeholder="输入任务编号" value="${esc(defaultTaskId)}" required />
          <button class="primary" type="submit">查询结果</button>
          <button class="ghost" id="resultBackTasksBtn" type="button">返回任务中心</button>
          <button class="ghost" id="resultOpenTaskBtn" type="button">打开任务详情</button>
          <button class="ghost" id="resultExportBtn" type="button">导出摘要</button>
        </form>
        <div id="resultMeta" class="hint">${esc(defaultTaskId ? '' : '训练成功后，可先去任务中心挑 1 张真实图片验证；任务完成后再回这里看结果与下一步建议。')}</div>
      </section>
      <section class="card" data-result-panel="actions" hidden>
        <h3>下一步动作</h3>
        <div id="resultActionWorkbench">${defaultTaskId ? renderLoading('正在生成下一步建议...') : renderEmpty('查询到结果后，这里会根据当前状态给出下一步建议。')}</div>
      </section>
      <section class="card" data-result-panel="dataset" hidden>
        <h3>把确认结果变成训练数据</h3>
        <div id="resultDatasetWorkbench">${defaultTaskId ? renderLoading('正在准备训练数据导出区...') : renderEmpty('先查询一条 task 结果，再把当前确认结果整理成训练或验证数据。')}</div>
      </section>
      <section class="card" data-result-panel="list" hidden>
        <div id="resultListWrap">${defaultTaskId ? renderLoading('加载结果...') : renderEmpty('请输入任务编号查询，或先在任务中心创建并执行任务')}</div>
      </section>
    `,
    async mount(root) {
      bindPageNavButtons(root, ctx);
      const resultPanelMeta = root.querySelector('#resultPanelMeta');
      const resultPanelTabs = [...root.querySelectorAll('[data-result-panel-tab]')];
      const resultPanels = [...root.querySelectorAll('[data-result-panel]')];
      const queryForm = root.querySelector('#resultQueryForm');
      const taskInput = root.querySelector('#resultTaskId');
      const resultMeta = root.querySelector('#resultMeta');
      const actionWorkbench = root.querySelector('#resultActionWorkbench');
      const datasetWorkbench = root.querySelector('#resultDatasetWorkbench');
      const listWrap = root.querySelector('#resultListWrap');
      const exportBtn = root.querySelector('#resultExportBtn');
      const backTasksBtn = root.querySelector('#resultBackTasksBtn');
      const openTaskBtn = root.querySelector('#resultOpenTaskBtn');
      let resultBlobUrls = [];
      let currentRows = [];
      let currentSummaries = [];
      let currentDatasetExport = null;
      let activeResultPanel = defaultTaskId ? 'list' : 'query';

      function setResultPanel(panel) {
        activeResultPanel = ['query', 'actions', 'dataset', 'list'].includes(panel) ? panel : (defaultTaskId ? 'list' : 'query');
        resultPanels.forEach((section) => {
          section.hidden = section.getAttribute('data-result-panel') !== activeResultPanel;
        });
        resultPanelTabs.forEach((button) => {
          const active = button.getAttribute('data-result-panel-tab') === activeResultPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (resultPanelMeta) {
          resultPanelMeta.textContent = {
            query: '先输入任务编号，确认要查看哪一次执行结果。',
            actions: '先看系统给出的下一步建议，再决定回任务中心、去训练中心还是继续复核。',
            dataset: '把确认结果整理成训练或验证数据，再带去训练中心继续使用。',
            list: '统一查看当前任务的结果、截图和技术详情。',
          }[activeResultPanel];
        }
      }

      function dominantTaskType(summaries) {
        const counts = new Map();
        (Array.isArray(summaries) ? summaries : []).forEach((item) => {
          const key = String(item?.taskType || '').trim();
          if (!key) return;
          counts.set(key, (counts.get(key) || 0) + 1);
        });
        return [...counts.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] || '';
      }

      function buildResultDatasetLabel(taskId, summaries) {
        const dominant = dominantTaskType(summaries) || 'result-review';
        const shortTask = String(taskId || '').trim().slice(0, 8) || 'task';
        return `${dominant}-review-${shortTask}`;
      }

      function prefillTrainingFromResultExport(exported, assetPurpose, taskType) {
        if (!exported?.asset?.id) return;
        if (assetPurpose === 'validation') {
          localStorage.setItem(STORAGE_KEYS.prefillTrainingValidationAssetIds, exported.asset.id);
        } else {
          localStorage.setItem(STORAGE_KEYS.prefillTrainingAssetIds, exported.asset.id);
        }
        if (exported.dataset_version?.id) localStorage.setItem(STORAGE_KEYS.prefillTrainingDatasetVersionId, exported.dataset_version.id);
        if (exported.dataset_version?.dataset_label) localStorage.setItem(STORAGE_KEYS.prefillTrainingDatasetLabel, exported.dataset_version.dataset_label);
        if (taskType) localStorage.setItem(STORAGE_KEYS.prefillTrainingTargetModelCode, taskType);
      }

      function renderResultDatasetWorkbench(taskId, summaries, exported = null) {
        if (!taskId) {
          return renderEmpty('先查询一条 task 结果，再把当前确认结果整理成训练或验证数据。');
        }
        if (!Array.isArray(summaries) || !summaries.length) {
          return renderEmpty('当前任务还没有可导出的结果。先等待任务完成，或回到任务中心确认执行状态。');
        }
        const taskType = dominantTaskType(summaries) || 'object_detect';
        const lowConfidenceCount = summaries.filter((item) => item?.taskType === 'car_number_ocr' && (!Number.isFinite(item.ocrConfidence) || item.ocrConfidence < 0.8 || item.ocrRisk !== 'stable')).length;
        const suggestedPurpose = taskType === 'car_number_ocr' && lowConfidenceCount === 0 ? 'training' : 'validation';
        const defaultLabel = exported?.dataset_version?.dataset_label || buildResultDatasetLabel(taskId, summaries);
        const taskTypeText = enumText('task_type', taskType);
        return `
          <div class="result-dataset-workbench">
            <div class="result-panel-head">
              <div>
                <strong>把当前确认结果整理成训练数据</strong>
                <p>${esc(taskType === 'car_number_ocr'
                  ? (lowConfidenceCount
                    ? `当前有 ${lowConfidenceCount} 条低置信度 OCR 结果，建议先整理成验证数据，再继续复核。`
                    : '当前 OCR 结果已经比较稳定，可优先整理成训练数据。')
                  : '当前结果适合整理成结构化样本包，再在训练中心继续筛选或复用。')}</p>
              </div>
              <span class="badge">${esc(taskTypeText)}</span>
            </div>
            <div class="form-grid result-dataset-form">
              <label>
                <span>数据集标签</span>
                <input id="resultDatasetLabel" value="${esc(defaultLabel)}" placeholder="例如：车号识别-复核样本" />
              </label>
              <label>
                <span>用途</span>
                <select id="resultDatasetPurpose">
                  <option value="training" ${suggestedPurpose === 'training' ? 'selected' : ''}>训练</option>
                  <option value="validation" ${suggestedPurpose === 'validation' ? 'selected' : ''}>验证</option>
                  <option value="finetune">微调</option>
                </select>
              </label>
              <label class="checkbox-row">
                <input id="resultDatasetIncludeScreenshots" type="checkbox" checked />
                携带标注截图一起导出
              </label>
            </div>
            <div class="row-actions">
              <button class="primary" type="button" data-result-export-dataset>整理好并带去训练中心</button>
              <button class="ghost" type="button" data-result-export-assets>只整理成数据集</button>
              ${exported?.asset?.id ? '<button class="ghost" type="button" data-open-result-training>打开训练页</button>' : ''}
            </div>
            ${
              exported?.asset?.id
                ? `
                    <div class="keyvals compact">
                      <div><span>数据集资产编号</span><strong class="mono">${esc(exported.asset.id)}</strong></div>
                      <div><span>数据集版本</span><strong>${esc(`${exported.dataset_version?.dataset_label || '-'}:${exported.dataset_version?.version || '-'}`)}</strong></div>
                      <div><span>任务类型</span><strong>${esc(taskTypeText)}</strong></div>
                      <div><span>样本数</span><strong>${esc(formatMetricValue(exported.summary?.task_count))}</strong></div>
                    </div>
                  `
                : `
                    <div class="hint">
                      当前会直接按任务编号 ${esc(taskId)} 整理。完成后会自动把训练页需要的数据集版本和资产编号预填好。
                    </div>
                  `
            }
          </div>
        `;
      }

      function revokeResultBlobUrls() {
        resultBlobUrls.forEach((url) => URL.revokeObjectURL(url));
        resultBlobUrls = [];
      }

      async function openScreenshot(resultId) {
        try {
          const resp = await fetch(`/api/results/${resultId}/screenshot`, {
            headers: { Authorization: `Bearer ${ctx.token}` },
          });
          if (!resp.ok) throw new Error(normalizeUiErrorMessage(`HTTP ${resp.status}`, resp.status));
          const blob = await resp.blob();
          const objectUrl = URL.createObjectURL(blob);
          window.open(objectUrl, '_blank');
        } catch (error) {
          ctx.toast(`截图打开失败：${error.message}`, 'error');
        }
      }

      async function bindScreenshotButtons() {
        listWrap.querySelectorAll('[data-open-shot]').forEach((btn) => {
          btn.addEventListener('click', async () => {
            const resultId = btn.getAttribute('data-open-shot');
            await openScreenshot(resultId);
          });
        });
        listWrap.querySelectorAll('[data-open-shot-url]').forEach((btn) => {
          btn.addEventListener('click', () => {
            const url = btn.getAttribute('data-open-shot-url') || '';
            if (!url) return;
            window.open(url, '_blank');
          });
        });
      }

      function bindResultListPanels() {
        const resultListPanelMeta = listWrap.querySelector('#resultListPanelMeta');
        const resultListPanelTabs = Array.from(listWrap.querySelectorAll('[data-result-list-panel-tab]'));
        const resultListPanels = Array.from(listWrap.querySelectorAll('[data-result-list-panel]'));
        if (!resultListPanelTabs.length || !resultListPanels.length) return;
        function setResultListPanel(panel) {
          resultListPanelTabs.forEach((btn) => {
            const active = btn.getAttribute('data-result-list-panel-tab') === panel;
            btn.classList.toggle('primary', active);
            btn.classList.toggle('ghost', !active);
          });
          resultListPanels.forEach((section) => {
            section.hidden = section.getAttribute('data-result-list-panel') !== panel;
          });
          if (resultListPanelMeta) {
            resultListPanelMeta.textContent = ({
              overview: '先看当前任务的整体结论、OCR 文本和验证建议。',
              models: '在这里核对关联模型的验证表现和验证门禁摘要。',
              items: '需要逐条看截图、框和技术详情时，再进入单条结果。',
            })[panel] || '按当前分区继续查看。';
          }
        }
        resultListPanelTabs.forEach((btn) => {
          btn.addEventListener('click', () => {
            setResultListPanel(btn.getAttribute('data-result-list-panel-tab') || 'overview');
          });
        });
        setResultListPanel('overview');
      }

      function bindResultActionWorkbench(taskId) {
        if (!actionWorkbench || !taskId) return;
        actionWorkbench.querySelector('[data-result-action="open-training"]')?.addEventListener('click', () => {
          if (currentDatasetExport?.asset?.id) {
            ctx.navigate('training');
            return;
          }
          setResultPanel('dataset');
          actionWorkbench.scrollIntoView({ block: 'center', behavior: 'smooth' });
          datasetWorkbench?.scrollIntoView({ block: 'center', behavior: 'smooth' });
          const exportBtn = datasetWorkbench?.querySelector('[data-result-export-dataset]');
          exportBtn?.focus();
        });
        actionWorkbench.querySelector('[data-result-action="open-task-detail"]')?.addEventListener('click', () => {
          localStorage.setItem(STORAGE_KEYS.lastTaskId, taskId);
          ctx.navigate(`tasks/${taskId}`);
        });
        actionWorkbench.querySelector('[data-result-action="back-tasks"]')?.addEventListener('click', () => {
          localStorage.setItem(STORAGE_KEYS.lastTaskId, taskId);
          ctx.navigate('tasks');
        });
      }

      function bindResultDatasetWorkbench(taskId) {
        if (!datasetWorkbench || !taskId) return;
        datasetWorkbench.querySelector('[data-open-result-training]')?.addEventListener('click', () => ctx.navigate('training'));
        datasetWorkbench.querySelector('[data-result-export-assets]')?.addEventListener('click', async (event) => {
          const button = event.currentTarget;
          const labelInput = datasetWorkbench.querySelector('#resultDatasetLabel');
          const purposeInput = datasetWorkbench.querySelector('#resultDatasetPurpose');
          const screenshotInput = datasetWorkbench.querySelector('#resultDatasetIncludeScreenshots');
          const datasetLabel = String(labelInput?.value || '').trim();
          if (!datasetLabel) {
            ctx.toast('请先填写数据集标签', 'error');
            return;
          }
          button.disabled = true;
          try {
            currentDatasetExport = await ctx.post('/results/export-dataset', {
              task_ids: [taskId],
              dataset_label: datasetLabel,
              asset_purpose: String(purposeInput?.value || 'training'),
              include_screenshots: screenshotInput?.checked !== false,
            });
            if (actionWorkbench) {
              actionWorkbench.innerHTML = renderResultActionWorkbench(taskId, currentSummaries, currentDatasetExport);
              bindResultActionWorkbench(taskId);
            }
            datasetWorkbench.innerHTML = renderResultDatasetWorkbench(taskId, currentSummaries, currentDatasetExport);
            bindResultDatasetWorkbench(taskId);
            setResultPanel('dataset');
            resultMeta.textContent = `已导出数据集版本：${currentDatasetExport.dataset_version?.dataset_label || '-'}:${currentDatasetExport.dataset_version?.version || '-'} · 数据集资产编号 ${currentDatasetExport.asset?.id || '-'}`;
            ctx.toast('结果数据集版本已导出');
          } catch (error) {
            ctx.toast(error.message || '结果数据集导出失败', 'error');
          } finally {
            button.disabled = false;
          }
        });
        datasetWorkbench.querySelector('[data-result-export-dataset]')?.addEventListener('click', async (event) => {
          const button = event.currentTarget;
          const labelInput = datasetWorkbench.querySelector('#resultDatasetLabel');
          const purposeInput = datasetWorkbench.querySelector('#resultDatasetPurpose');
          const screenshotInput = datasetWorkbench.querySelector('#resultDatasetIncludeScreenshots');
          const datasetLabel = String(labelInput?.value || '').trim();
          if (!datasetLabel) {
            ctx.toast('请先填写数据集标签', 'error');
            return;
          }
          button.disabled = true;
          try {
            currentDatasetExport = await ctx.post('/results/export-dataset', {
              task_ids: [taskId],
              dataset_label: datasetLabel,
              asset_purpose: String(purposeInput?.value || 'training'),
              include_screenshots: screenshotInput?.checked !== false,
            });
            const taskType = dominantTaskType(currentSummaries) || 'object_detect';
            prefillTrainingFromResultExport(currentDatasetExport, String(purposeInput?.value || 'training'), taskType);
            if (actionWorkbench) {
              actionWorkbench.innerHTML = renderResultActionWorkbench(taskId, currentSummaries, currentDatasetExport);
              bindResultActionWorkbench(taskId);
            }
            datasetWorkbench.innerHTML = renderResultDatasetWorkbench(taskId, currentSummaries, currentDatasetExport);
            bindResultDatasetWorkbench(taskId);
            setResultPanel('dataset');
            ctx.toast('已导出并预填训练中心');
            ctx.navigate('training');
          } catch (error) {
            ctx.toast(error.message || '结果数据集导出失败', 'error');
          } finally {
            button.disabled = false;
          }
        });
      }

      async function loadModelInsights(rows) {
        const modelIds = [...new Set((rows || []).map((row) => String(row.model_id || '').trim()).filter(Boolean))];
        const entries = await Promise.all(modelIds.map(async (modelId) => {
          try {
            const data = await ctx.get(`/models/${modelId}/readiness`);
            return [modelId, data];
          } catch {
            return [modelId, null];
          }
        }));
        return Object.fromEntries(entries.filter(([, value]) => value));
      }

      async function enrichRowsWithScreenshots(rows) {
        revokeResultBlobUrls();
        return Promise.all((rows || []).map(async (row) => {
          if (!row?.screenshot_uri) return row;
          try {
            const previewUrl = await fetchAuthorizedBlobUrl(`/results/${row.id}/screenshot`, ctx.token);
            if (previewUrl) resultBlobUrls.push(previewUrl);
            return { ...row, _screenshot_preview_url: previewUrl || '' };
          } catch {
            return { ...row, _screenshot_preview_url: '' };
          }
        }));
      }

      async function loadByTaskId(taskId) {
        const clean = String(taskId || '').trim();
        if (!clean) {
          revokeResultBlobUrls();
          listWrap.innerHTML = renderEmpty('请输入任务编号，或先在任务中心创建并执行任务');
          resultMeta.textContent = '';
          if (actionWorkbench) actionWorkbench.innerHTML = renderEmpty('查询到结果后，这里会根据当前状态给出下一步建议。');
          if (datasetWorkbench) datasetWorkbench.innerHTML = renderEmpty('先查询一条 task 结果，再把当前复核结果导出成训练/验证数据集版本。');
          currentRows = [];
          currentSummaries = [];
          currentDatasetExport = null;
          return;
        }
        listWrap.innerHTML = renderLoading('加载结果...');
        if (actionWorkbench) actionWorkbench.innerHTML = renderLoading('正在生成下一步建议...');
        if (datasetWorkbench) datasetWorkbench.innerHTML = renderLoading('正在准备结果回灌工作台...');
        resultMeta.textContent = '';
        try {
          const rows = await ctx.get(`/results${toQuery({ task_id: clean })}`);
          const enrichedRows = await enrichRowsWithScreenshots(rows || []);
          const modelInsights = await loadModelInsights(enrichedRows || []);
          currentRows = enrichedRows || [];
          currentSummaries = currentRows.map(summarizeResultRow);
          currentDatasetExport = null;
          listWrap.innerHTML = buildResultListHtml(enrichedRows || [], modelInsights);
          bindResultListPanels();
          if (actionWorkbench) {
            actionWorkbench.innerHTML = renderResultActionWorkbench(clean, currentSummaries, currentDatasetExport);
            bindResultActionWorkbench(clean);
          }
          if (datasetWorkbench) {
            datasetWorkbench.innerHTML = renderResultDatasetWorkbench(clean, currentSummaries, currentDatasetExport);
            bindResultDatasetWorkbench(clean);
          }
          const modelCount = [...new Set((enrichedRows || []).map((row) => String(row.model_id || '').trim()).filter(Boolean))].length;
          const recognizedTexts = [...new Set(currentSummaries.flatMap((item) => item.recognizedTexts || []).filter(Boolean))];
          resultMeta.textContent = recognizedTexts.length
            ? `当前查询到 ${enrichedRows.length} 条结果 · 关联模型 ${modelCount} 个 · 识别文本 ${recognizedTexts.slice(0, 3).join(' / ')}`
            : `当前查询到 ${enrichedRows.length} 条结果 · 关联模型 ${modelCount} 个`;
          localStorage.setItem(STORAGE_KEYS.lastTaskId, clean);
          setResultPanel('list');
          await bindScreenshotButtons();
        } catch (error) {
          listWrap.innerHTML = renderError(error.message);
          if (actionWorkbench) actionWorkbench.innerHTML = renderError(error.message);
          if (datasetWorkbench) datasetWorkbench.innerHTML = renderError(error.message);
        }
      }

      queryForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        await loadByTaskId(taskInput?.value || '');
      });
      resultPanelTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setResultPanel(button.getAttribute('data-result-panel-tab') || 'query');
        });
      });

      backTasksBtn?.addEventListener('click', () => {
        const taskId = String(taskInput?.value || '').trim();
        if (taskId) localStorage.setItem(STORAGE_KEYS.lastTaskId, taskId);
        ctx.navigate('tasks');
      });

      openTaskBtn?.addEventListener('click', () => {
        const taskId = String(taskInput?.value || '').trim();
        if (!taskId) {
          ctx.toast('请先输入任务编号', 'error');
          return;
        }
        localStorage.setItem(STORAGE_KEYS.lastTaskId, taskId);
        ctx.navigate(`tasks/${taskId}`);
      });

      exportBtn?.addEventListener('click', async () => {
        const taskId = String(taskInput?.value || '').trim();
        if (!taskId) {
          ctx.toast('请先输入任务编号', 'error');
          return;
        }
        try {
          const data = await ctx.get(`/results/export${toQuery({ task_id: taskId })}`);
          ctx.toast(`导出成功：${data.count} 条`);
          const preview = safeJson(data).slice(0, 1200);
          resultMeta.textContent = `导出成功：count=${data.count}`;
          listWrap.insertAdjacentHTML('beforeend', `<details><summary>导出摘要（预览）</summary><pre>${esc(preview)}</pre></details>`);
        } catch (error) {
          ctx.toast(error.message, 'error');
        }
      });

      setResultPanel(activeResultPanel);
      if (defaultTaskId) await loadByTaskId(defaultTaskId);
    },
  };
}

function pageAudit(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  return {
    html: `
      ${renderPageHero({
        eyebrow: '证据与留痕',
        title: '审计中心',
        summary: '统一核对模型审批发布、训练拉取、任务创建、结果导出和设备执行证据。',
        highlights: ['按动作查找', '按资源回溯', '用于交付留痕'],
        actions: [
          { path: 'models', label: '查看模型审批' },
          { path: 'devices', label: '查看设备状态', primary: true },
        ],
      })}
      <section class="card">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-audit-panel-tab="overview">审计总览</button>
          <button class="ghost" type="button" data-audit-panel-tab="search">检索日志</button>
        </div>
        <div id="auditPanelMeta" class="hint">默认先看审计总览；按需展开检索日志。</div>
      </section>
      <section class="card" data-audit-panel="overview">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-audit-overview-tab="workbench">工作台概览</button>
          <button class="ghost" type="button" data-audit-overview-tab="recent">最近动作</button>
        </div>
        <div id="auditOverviewPanelMeta" class="hint">默认先看审计工作台概览；需要浏览最近动作时再切进去。</div>
      </section>
      <section class="card" data-audit-panel="overview" data-audit-overview-panel="workbench" hidden>
        <div id="auditOverviewWrap">${renderLoading('加载审计概览...')}</div>
      </section>
      <section class="card" data-audit-panel="overview" data-audit-overview-panel="recent" hidden>
        <div id="auditRecentWrap">${renderLoading('加载最近动作...')}</div>
      </section>
      <section class="card" data-audit-panel="search" hidden>
        <form id="auditFilterForm" class="inline-form">
          <input name="action" placeholder="action(动作)，例如 MODEL_RELEASE" />
          <input name="resource_type" placeholder="resource_type(资源类型)，例如 task" />
          <input name="resource_id" placeholder="resource_id(资源ID)" />
          <input name="actor_username" placeholder="actor_username(操作者账号)" />
          <button class="primary" type="submit">查询</button>
        </form>
        <div id="auditTableWrap">${renderLoading('加载审计日志...')}</div>
      </section>
    `,
    async mount(root) {
      bindPageNavButtons(root, ctx);
      const auditPanelMeta = root.querySelector('#auditPanelMeta');
      const auditPanelTabs = [...root.querySelectorAll('[data-audit-panel-tab]')];
      const auditPanels = [...root.querySelectorAll('[data-audit-panel]')];
      const auditOverviewPanelMeta = root.querySelector('#auditOverviewPanelMeta');
      const auditOverviewTabs = [...root.querySelectorAll('[data-audit-overview-tab]')];
      const auditOverviewPanels = [...root.querySelectorAll('[data-audit-overview-panel]')];
      const overviewWrap = root.querySelector('#auditOverviewWrap');
      const recentWrap = root.querySelector('#auditRecentWrap');
      const filterForm = root.querySelector('#auditFilterForm');
      const tableWrap = root.querySelector('#auditTableWrap');
      let activeAuditPanel = 'overview';
      let activeAuditOverviewPanel = 'workbench';

      function setAuditOverviewPanel(panel) {
        activeAuditOverviewPanel = ['workbench', 'recent'].includes(panel) ? panel : 'workbench';
        auditOverviewPanels.forEach((section) => {
          section.hidden = section.getAttribute('data-audit-overview-panel') !== activeAuditOverviewPanel || activeAuditPanel !== 'overview';
        });
        auditOverviewTabs.forEach((button) => {
          const active = button.getAttribute('data-audit-overview-tab') === activeAuditOverviewPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (auditOverviewPanelMeta) {
          auditOverviewPanelMeta.textContent = activeAuditOverviewPanel === 'workbench'
            ? '先看留痕规模、动作类型和推荐下一步动作。'
            : '需要浏览最近发生的审批、训练、任务和结果事件时，再进入最近动作。';
        }
      }

      function setAuditPanel(panel) {
        activeAuditPanel = ['overview', 'search'].includes(panel) ? panel : 'overview';
        auditPanels.forEach((section) => {
          const panelName = section.getAttribute('data-audit-panel');
          if (panelName !== activeAuditPanel) {
            section.hidden = true;
            return;
          }
          if (panelName === 'overview' && section.hasAttribute('data-audit-overview-panel')) return;
          section.hidden = false;
        });
        auditPanelTabs.forEach((button) => {
          const active = button.getAttribute('data-audit-panel-tab') === activeAuditPanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (auditPanelMeta) {
          auditPanelMeta.textContent = activeAuditPanel === 'overview'
            ? '先看审计总量、最近动作和资源类型分布。'
            : '按动作、资源或操作者检索完整留痕。';
        }
        if (activeAuditPanel === 'overview') setAuditOverviewPanel(activeAuditOverviewPanel);
      }

      async function loadAudit() {
        tableWrap.innerHTML = renderLoading('加载审计日志...');
        if (overviewWrap) overviewWrap.innerHTML = renderLoading('加载审计概览...');
        if (recentWrap) recentWrap.innerHTML = renderLoading('加载最近动作...');
        try {
          const fd = new FormData(filterForm);
          const query = toQuery({
            action: fd.get('action'),
            resource_type: fd.get('resource_type'),
            resource_id: fd.get('resource_id'),
            actor_username: fd.get('actor_username'),
            limit: 100,
          });
          const rows = await ctx.get(`/audit${query}`);
          if (overviewWrap) {
            const actionKinds = new Set(rows.map((row) => String(row.action || '').trim()).filter(Boolean)).size;
            const resourceKinds = new Set(rows.map((row) => String(row.resource_type || '').trim()).filter(Boolean)).size;
            overviewWrap.innerHTML = renderWorkbenchOverview({
              title: '审计总览',
              summary: '统一查看模型审批发布、训练执行、任务创建和结果导出的留痕。',
              metrics: [
                { label: '日志条数', value: rows.length, note: '当前检索结果' },
                { label: '动作类型', value: actionKinds, note: 'action' },
                { label: '资源类型', value: resourceKinds, note: 'resource_type' },
              ],
              actions: [
                { id: 'audit-open-search', label: '打开检索日志', primary: true },
                { id: 'audit-open-devices', label: '查看设备状态' },
              ],
            });
            overviewWrap.querySelector('[data-workbench-action="audit-open-search"]')?.addEventListener('click', () => {
              setAuditPanel('search');
              filterForm?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
            overviewWrap.querySelector('[data-workbench-action="audit-open-devices"]')?.addEventListener('click', () => {
              ctx.navigate('devices');
            });
          }
          if (recentWrap) {
            recentWrap.innerHTML = rows.length
              ? `
                  <div class="selection-grid">
                    ${rows.slice(0, 8).map((row) => `
                      <article class="selection-card">
                        <div class="selection-card-head selection-card-head--stack">
                          <div class="selection-card-title">
                            <strong>${esc(row.action)}</strong>
                            <span class="selection-card-subtitle">${formatDateTime(row.created_at)}</span>
                          </div>
                          <span class="badge">${esc(row.resource_type || '-')}</span>
                        </div>
                        <div class="selection-card-meta selection-card-meta--compact">
                          <span>操作者</span><strong>${esc(row.actor_username || row.actor_role || '-')}</strong>
                          <span>资源ID</span><strong class="mono">${esc(truncateMiddle(row.resource_id || '-', 10, 8))}</strong>
                          <span>影响</span><strong>${esc(row.detail?.status || row.detail?.decision || '已留痕')}</strong>
                          <span>下一步</span><strong>${esc(row.resource_type === 'model' ? '去模型中心' : row.resource_type === 'task' ? '去任务中心' : '继续检索')}</strong>
                        </div>
                      </article>
                    `).join('')}
                  </div>
                `
              : renderEmpty('当前还没有可展示的最近动作。');
          }
          if (!rows.length) {
            tableWrap.innerHTML = renderEmpty('暂无审计日志。完成模型审批、任务创建、结果导出或设备拉取后会在这里留痕');
            return;
          }
          tableWrap.innerHTML = `
            <div class="selection-grid">
              ${rows.map((row) => `
                <article class="selection-card">
                  <div class="selection-card-head selection-card-head--stack">
                    <div class="selection-card-title">
                      <strong>${esc(row.action)}</strong>
                      <span class="selection-card-subtitle">${formatDateTime(row.created_at)}</span>
                    </div>
                    <span class="badge">${esc(row.resource_type || '-')}</span>
                  </div>
                  <div class="selection-card-meta selection-card-meta--compact">
                    <span>操作者</span><strong>${esc(row.actor_username || row.actor_role || '-')}</strong>
                    <span>资源</span><strong>${esc(row.resource_type || '-')}</strong>
                    <span>资源ID</span><strong class="mono">${esc(truncateMiddle(row.resource_id || '-', 10, 8))}</strong>
                    <span>影响</span><strong>${esc(row.detail?.status || row.detail?.decision || '已留痕')}</strong>
                  </div>
                  <details class="inline-details">
                    <summary>查看详情</summary>
                    <div class="details-panel">
                      <pre>${esc(safeJson(row.detail))}</pre>
                    </div>
                  </details>
                </article>
              `).join('')}
            </div>
          `;
        } catch (error) {
          tableWrap.innerHTML = renderError(error.message);
        }
      }

      filterForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        await loadAudit();
      });

      auditPanelTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setAuditPanel(button.getAttribute('data-audit-panel-tab') || 'overview');
        });
      });
      auditOverviewTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setAuditOverviewPanel(button.getAttribute('data-audit-overview-tab') || 'workbench');
        });
      });
      setAuditPanel('overview');
      await loadAudit();
    },
  };
}

function pageDevices(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const role = primaryRole(ctx.state.user);
  const heroSummary = role.startsWith('buyer_')
    ? '查看已授权边缘设备的在线状态、最近心跳和 Agent 版本，确认设备可执行范围。'
    : '查看设备授权、在线状态、最近心跳和 Agent 版本，核对边缘运行面。';
  return {
    html: `
      ${renderPageHero({
        eyebrow: '设备与运行面',
        title: '设备中心',
        summary: heroSummary,
        highlights: ['在线状态', '最近心跳', 'Agent 版本'],
        actions: [
          { path: 'audit', label: '查看审计' },
          { path: 'tasks', label: '去任务中心', primary: true },
        ],
      })}
      <section class="card">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-device-panel-tab="overview">设备总览</button>
          <button class="ghost" type="button" data-device-panel-tab="list">设备列表</button>
        </div>
        <div id="devicePanelMeta" class="hint">默认先看设备总览；按需展开设备列表。</div>
      </section>
      <section class="card" data-device-panel="overview">
        <div id="devicesOverviewWrap">${renderLoading('加载设备概览...')}</div>
      </section>
      <section class="card" data-device-panel="list" hidden>
        <div id="devicesTableWrap">${renderLoading('加载设备列表...')}</div>
      </section>
    `,
    async mount(root) {
      bindPageNavButtons(root, ctx);
      const devicePanelMeta = root.querySelector('#devicePanelMeta');
      const devicePanelTabs = [...root.querySelectorAll('[data-device-panel-tab]')];
      const devicePanels = [...root.querySelectorAll('[data-device-panel]')];
      const overviewWrap = root.querySelector('#devicesOverviewWrap');
      const wrap = root.querySelector('#devicesTableWrap');
      let activeDevicePanel = 'overview';

      function setDevicePanel(panel) {
        activeDevicePanel = ['overview', 'list'].includes(panel) ? panel : 'overview';
        devicePanels.forEach((section) => {
          section.hidden = section.getAttribute('data-device-panel') !== activeDevicePanel;
        });
        devicePanelTabs.forEach((button) => {
          const active = button.getAttribute('data-device-panel-tab') === activeDevicePanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (devicePanelMeta) {
          devicePanelMeta.textContent = activeDevicePanel === 'overview'
            ? '先看在线状态、最近心跳和设备规模。'
            : '展开完整设备列表查看 buyer、状态和 Agent 版本。';
        }
      }
      devicePanelTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setDevicePanel(button.getAttribute('data-device-panel-tab') || 'overview');
        });
      });
      setDevicePanel('overview');
      try {
        const rows = await ctx.get('/devices');
        if (!rows.length) {
          if (overviewWrap) overviewWrap.innerHTML = renderEmpty('暂无设备概览。');
          wrap.innerHTML = renderEmpty('暂无设备。请先接入边缘 Agent，或确认当前角色拥有设备查看权限');
          return;
        }
        if (overviewWrap) {
          const online = rows.filter((row) => String(row.status || '').toUpperCase() === 'ONLINE').length;
          const buyers = new Set(rows.map((row) => String(row.buyer || '').trim()).filter(Boolean)).size;
          const latestHeartbeat = rows
            .map((row) => row.last_heartbeat)
            .filter(Boolean)
            .sort((a, b) => String(b).localeCompare(String(a)))[0];
          overviewWrap.innerHTML = renderWorkbenchOverview({
            title: '设备总览',
            summary: '统一查看当前授权设备的在线状态、客户范围和最近心跳。',
            metrics: [
              { label: '设备总数', value: rows.length, note: '当前可见' },
              { label: '在线设备', value: online, note: rows.length ? `${Math.round((online / rows.length) * 100)}%` : '-' },
              { label: '买家范围', value: buyers, note: latestHeartbeat ? `最近心跳 ${formatDateTime(latestHeartbeat)}` : '暂无心跳' },
            ],
            actions: [
              { id: 'device-open-list', label: '打开设备列表', primary: true },
              { id: 'device-open-audit', label: '查看审计' },
            ],
          });
          overviewWrap.querySelector('[data-workbench-action="device-open-list"]')?.addEventListener('click', () => {
            setDevicePanel('list');
            wrap?.scrollIntoView({ behavior: 'smooth', block: 'start' });
          });
          overviewWrap.querySelector('[data-workbench-action="device-open-audit"]')?.addEventListener('click', () => {
            ctx.navigate('audit');
          });
        }
        wrap.innerHTML = `
          <div class="selection-grid">
            ${rows.map((row) => `
              <article class="selection-card">
                <div class="selection-card-head selection-card-head--stack">
                  <div class="selection-card-title">
                    <strong>${esc(row.device_id)}</strong>
                    <span class="selection-card-subtitle">${esc(row.buyer || '-')}</span>
                  </div>
                  <span class="badge">${esc(enumText('device_status', row.status))}</span>
                </div>
                <div class="selection-card-meta selection-card-meta--compact">
                  <span>最近心跳</span><strong>${formatDateTime(row.last_heartbeat)}</strong>
                  <span>Agent</span><strong>${esc(row.agent_version || '-')}</strong>
                  <span>客户</span><strong>${esc(row.buyer || '-')}</strong>
                  <span>状态</span><strong>${esc(enumText('device_status', row.status))}</strong>
                </div>
              </article>
            `).join('')}
          </div>
        `;
      } catch (error) {
        if (String(error.message || '').includes('404')) {
          if (overviewWrap) overviewWrap.innerHTML = renderEmpty('设备概览暂不可用。');
          wrap.innerHTML = renderEmpty('设备接口尚未接通，请先确认中心端 /devices 接口状态');
          return;
        }
        if (overviewWrap) overviewWrap.innerHTML = renderError(error.message);
        wrap.innerHTML = renderError(error.message);
      }
    },
  };
}

function pageSettings(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  return {
    html: `
      ${renderPageHero({
        eyebrow: '身份与权限',
        title: '设置',
        summary: '核对当前登录身份、租户边界、权限能力和默认角色路径。',
        highlights: ['账号信息', '角色权限', '默认操作路径'],
        actions: [
          { path: 'dashboard', label: '返回工作台', primary: true },
          { path: 'guide', label: '查看使用指南' },
        ],
      })}
      <section class="card">
        <div class="workspace-switcher">
          <button class="ghost" type="button" data-settings-panel-tab="overview">账号总览</button>
          <button class="ghost" type="button" data-settings-panel-tab="access">权限范围</button>
          <button class="ghost" type="button" data-settings-panel-tab="governance">数据治理</button>
          <button class="ghost" type="button" data-settings-panel-tab="tech">技术详情</button>
        </div>
        <div id="settingsPanelMeta" class="hint">默认先看账号总览；权限、数据治理和技术细节按工作区展开。</div>
      </section>
      <section class="card" data-settings-panel="overview">
        <div id="settingsOverviewWrap">${renderLoading('加载账号总览...')}</div>
      </section>
      <section class="card" data-settings-panel="access" hidden>
        <div id="settingsAccessWrap">${renderLoading('加载权限范围...')}</div>
      </section>
      <section class="card" data-settings-panel="governance" hidden>
        <div id="settingsGovernanceWrap">${renderLoading('加载数据治理预览...')}</div>
      </section>
      <section class="card" data-settings-panel="tech" hidden>
        <div id="settingsTechWrap">${renderLoading('加载技术详情...')}</div>
      </section>
    `,
    async mount(root) {
      bindPageNavButtons(root, ctx);
      const panelMeta = root.querySelector('#settingsPanelMeta');
      const panelTabs = [...root.querySelectorAll('[data-settings-panel-tab]')];
      const panels = [...root.querySelectorAll('[data-settings-panel]')];
      const overviewWrap = root.querySelector('#settingsOverviewWrap');
      const accessWrap = root.querySelector('#settingsAccessWrap');
      const governanceWrap = root.querySelector('#settingsGovernanceWrap');
      const techWrap = root.querySelector('#settingsTechWrap');
      let activePanel = 'overview';
      let governanceKeepLatest = 3;
      let governanceData = null;
      let governanceBusyAction = '';
      let governanceLastResult = '';

      function normalizeGovernanceAction(action) {
        return String(action || '').trim();
      }

      function renderGovernanceMetrics(summary = {}) {
        const entries = Object.entries(summary || {}).filter(([, value]) => value !== undefined && value !== null);
        if (!entries.length) return '<div class="hint">当前没有可展示的治理摘要。</div>';
        return `
          <div class="keyvals compact">
            ${entries.map(([key, value]) => `<div><span>${esc(key)}</span><strong>${esc(typeof value === 'number' ? formatMetricValue(value) : String(value))}</strong></div>`).join('')}
          </div>
        `;
      }

      function renderGovernanceRowList(rows = [], emptyText = '当前没有可预览的样本。') {
        if (!rows.length) return `<div class="hint">${esc(emptyText)}</div>`;
        return `
          <div class="page-hero-highlights">
            ${rows.map((row) => {
              const label = row.label || row.file_name || row.id || row.pipeline_id || row.task_id || '-';
              const reason = row.reason || row.asset_type || row.storage_uri || '';
              return `<span class="page-hero-pill" title="${esc(reason || label)}">${esc(reason ? `${label} · ${reason}` : label)}</span>`;
            }).join('')}
          </div>
        `;
      }

      function governanceActionTitle(action) {
        if (action === 'keep_demo_chain') return '只保留当前车号演示主链';
        if (action === 'cleanup_synthetic_runtime') return '清理 synthetic 运行残留';
        if (action === 'prune_ocr_exports') return '裁剪旧 OCR 导出历史';
        return action || '数据治理动作';
      }

      function governanceActionDescription(action) {
        if (action === 'keep_demo_chain') return '保留当前车号识别样例主链与当前目标检测模型，其余确认无用的历史数据会被清走。';
        if (action === 'cleanup_synthetic_runtime') return '清理 API 回归和 synthetic 运行残留，避免历史临时文件继续污染控制台。';
        if (action === 'prune_ocr_exports') return '只保留最近几版 OCR 导出历史，删除没有继续使用价值的旧导出记录。';
        return '查看并执行当前数据治理动作。';
      }

      function renderGovernanceActionCard(item, canExecute) {
        const action = normalizeGovernanceAction(item?.action);
        const isBusy = governanceBusyAction === action;
        const summary = item?.summary || {};
        const previewRows = action === 'keep_demo_chain'
          ? [
              ...(item?.keep_preview?.models || []),
              ...(item?.keep_preview?.training_jobs || []),
              ...(item?.delete_preview?.assets || []),
            ]
          : action === 'prune_ocr_exports'
            ? (item?.rows_preview || [])
            : (summary?.paths?.assets || []).map((path) => ({ label: path }));
        return `
          <article class="selection-card">
            <div class="selection-card-head selection-card-head--stack">
              <div class="selection-card-title">
                <strong>${esc(item?.title || governanceActionTitle(action))}</strong>
                <span class="selection-card-subtitle">${esc(governanceActionDescription(action))}</span>
              </div>
              <span class="badge">${esc(canExecute ? '可执行' : '仅预览')}</span>
            </div>
            ${renderGovernanceMetrics(summary)}
            <details class="inline-details">
              <summary>查看预览样本</summary>
              <div class="details-panel">
                ${renderGovernanceRowList(previewRows, '当前动作没有更多预览项。')}
              </div>
            </details>
            <div class="page-hero-actions">
              <button class="ghost" type="button" data-governance-refresh="${esc(action)}">刷新预览</button>
              <button class="${canExecute ? 'primary' : 'ghost'}" type="button" data-governance-run="${esc(action)}" ${canExecute ? '' : 'disabled'}>
                ${isBusy ? '执行中...' : '立即执行'}
              </button>
            </div>
          </article>
        `;
      }

      function renderGovernancePanel() {
        if (!governanceWrap) return;
        if (!governanceData) {
          governanceWrap.innerHTML = renderLoading('加载数据治理预览...');
          return;
        }
        const actions = Array.isArray(governanceData.actions) ? governanceData.actions : [];
        governanceWrap.innerHTML = `
          ${renderWorkbenchOverview({
            title: '数据治理',
            summary: '先预览，再执行。把“保留当前车号演示主链”“清理 synthetic 残留”“裁剪旧 OCR 导出历史”收进同一入口。',
            status: governanceData.can_execute ? '可执行治理' : '只读预览',
            metrics: [
              { label: '治理动作', value: actions.length, note: '当前可用' },
              { label: '保留 OCR 历史', value: governanceData.keep_latest, note: '按版本链裁剪' },
              { label: '执行权限', value: governanceData.can_execute ? '平台管理员' : '只读角色', note: governanceData.generated_at ? `预览时间 ${formatDateTime(governanceData.generated_at)}` : '刚刚加载' },
            ],
            actions: [
              { id: 'governance-refresh-all', label: '刷新全部预览', primary: true },
              { id: 'governance-open-tech', label: '查看技术详情' },
            ],
          })}
          <div class="selection-summary">
            <label>
              保留最近几版 OCR 导出历史
              <input id="governanceKeepLatest" type="number" min="1" max="20" value="${esc(governanceKeepLatest)}" />
            </label>
            <div class="hint">先按预览确认范围，再决定是否执行。平台管理员可直接从这里触发治理动作。</div>
            ${governanceLastResult ? `<div class="hint">${esc(governanceLastResult)}</div>` : ''}
          </div>
          <div class="selection-grid">
            ${actions.map((item) => renderGovernanceActionCard(item, Boolean(governanceData.can_execute))).join('')}
          </div>
        `;
        governanceWrap.querySelector('[data-workbench-action="governance-refresh-all"]')?.addEventListener('click', () => {
          loadGovernancePreview();
        });
        governanceWrap.querySelector('[data-workbench-action="governance-open-tech"]')?.addEventListener('click', () => {
          setSettingsPanel('tech');
        });
        governanceWrap.querySelector('#governanceKeepLatest')?.addEventListener('change', async (event) => {
          const nextValue = Math.max(1, Math.min(20, Number(event.target.value) || 3));
          governanceKeepLatest = nextValue;
          await loadGovernancePreview();
        });
        governanceWrap.querySelectorAll('[data-governance-refresh]').forEach((button) => {
          button.addEventListener('click', () => loadGovernancePreview());
        });
        governanceWrap.querySelectorAll('[data-governance-run]').forEach((button) => {
          button.addEventListener('click', async () => {
            const action = button.getAttribute('data-governance-run') || '';
            governanceBusyAction = action;
            renderGovernancePanel();
            try {
              const result = await ctx.post('/settings/data-governance/run', {
                action,
                keep_latest: governanceKeepLatest,
                note: `settings_governance_${action}`,
              });
              governanceLastResult = `${governanceActionTitle(action)}已执行完成。执行时间：${formatDateTime(result.executed_at || new Date().toISOString())}`;
              await loadGovernancePreview();
            } catch (error) {
              governanceBusyAction = '';
              governanceLastResult = error.message || '数据治理执行失败';
              renderGovernancePanel();
            }
          });
        });
      }

      async function loadGovernancePreview() {
        if (!governanceWrap) return;
        governanceWrap.innerHTML = renderLoading('加载数据治理预览...');
        try {
          governanceData = await ctx.get(`/settings/data-governance${toQuery({ keep_latest: governanceKeepLatest })}`);
          governanceBusyAction = '';
          renderGovernancePanel();
        } catch (error) {
          governanceBusyAction = '';
          governanceWrap.innerHTML = renderError(error.message);
        }
      }

      function setSettingsPanel(panel) {
        activePanel = ['overview', 'access', 'governance', 'tech'].includes(panel) ? panel : 'overview';
        panels.forEach((section) => {
          section.hidden = section.getAttribute('data-settings-panel') !== activePanel;
        });
        panelTabs.forEach((button) => {
          const active = button.getAttribute('data-settings-panel-tab') === activePanel;
          button.classList.toggle('primary', active);
          button.classList.toggle('ghost', !active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (panelMeta) {
          panelMeta.textContent = activePanel === 'overview'
            ? '先看当前账号、租户边界和默认工作路径。'
            : activePanel === 'access'
              ? '查看当前角色可执行范围和能力标签。'
              : activePanel === 'governance'
                ? '先预览系统准备保留或清理的内容，再决定是否执行数据治理。'
                : '仅在排障或核对权限细项时查看原始技术信息。';
        }
      }

      panelTabs.forEach((button) => {
        button.addEventListener('click', () => {
          setSettingsPanel(button.getAttribute('data-settings-panel-tab') || 'overview');
        });
      });
      try {
        const me = await ctx.get('/users/me');
        const preset = rolePreset(me);
        const roleNames = (me.roles || []).map((item) => roleLabel(item)).filter(Boolean);
        const permissions = Array.isArray(me.permissions) ? me.permissions.filter(Boolean) : [];
        const capabilities = me.capabilities && typeof me.capabilities === 'object' ? me.capabilities : {};
        const enabledCapabilities = Object.entries(capabilities).filter(([, value]) => value).map(([key]) => key);
        overviewWrap.innerHTML = `
          ${renderWorkbenchOverview({
            title: '账号总览',
            summary: '先确认当前是谁、归属哪个租户、默认应该从哪个工作区开始操作。',
            status: roleNames[0] || '未识别角色',
            metrics: [
              { label: '当前账号', value: me.username || '-', note: '登录身份' },
              { label: '租户边界', value: me.tenant_code || me.tenant_id || '-', note: me.tenant_type || 'tenant' },
              { label: '角色数量', value: roleNames.length || 0, note: roleNames.join(' / ') || '无角色' },
              { label: '默认路径', value: preset.pathHint || '-', note: '推荐从这里开始' },
            ],
            actions: [
              { id: 'settings-open-dashboard', label: '返回工作台', primary: true },
              { id: 'settings-open-guide', label: '查看使用指南' },
              { id: 'settings-open-access', label: '查看权限范围' },
            ],
          })}
          <div class="selection-grid">
            <article class="selection-card">
              <div class="selection-card-head selection-card-head--stack">
                <div class="selection-card-title">
                  <strong>${esc(me.username || '-')}</strong>
                  <span class="selection-card-subtitle">${esc(roleNames.join(' / ') || '未分配角色')}</span>
                </div>
                <span class="badge">${esc(me.tenant_type || 'tenant')}</span>
              </div>
              <div class="selection-card-meta selection-card-meta--compact">
                <span>租户编码</span><strong>${esc(me.tenant_code || '-')}</strong>
                <span>默认入口</span><strong>${esc(preset.title || '-')}</strong>
                <span>权限条数</span><strong>${permissions.length}</strong>
                <span>能力标签</span><strong>${enabledCapabilities.length}</strong>
              </div>
            </article>
          </div>
        `;
        overviewWrap.querySelector('[data-workbench-action="settings-open-dashboard"]')?.addEventListener('click', () => ctx.navigate('dashboard'));
        overviewWrap.querySelector('[data-workbench-action="settings-open-guide"]')?.addEventListener('click', () => ctx.navigate('guide'));
        overviewWrap.querySelector('[data-workbench-action="settings-open-access"]')?.addEventListener('click', () => setSettingsPanel('access'));

        accessWrap.innerHTML = `
          <div class="selection-grid">
            <article class="selection-card">
              <div class="selection-card-head">
                <strong>角色范围</strong>
              </div>
              <div class="page-hero-highlights">
                ${roleNames.length ? roleNames.map((item) => `<span class="page-hero-pill">${esc(item)}</span>`).join('') : '<span class="page-hero-pill">暂无角色</span>'}
              </div>
            </article>
            <article class="selection-card">
              <div class="selection-card-head">
                <strong>能力标签</strong>
              </div>
              <div class="page-hero-highlights">
                ${enabledCapabilities.length ? enabledCapabilities.slice(0, 12).map((item) => `<span class="page-hero-pill">${esc(item)}</span>`).join('') : '<span class="page-hero-pill">暂无能力标签</span>'}
              </div>
              <div class="hint">已启用 ${enabledCapabilities.length} 项能力；完整明细见技术详情。</div>
            </article>
            <article class="selection-card">
              <div class="selection-card-head">
                <strong>权限摘要</strong>
              </div>
              <div class="selection-card-meta selection-card-meta--compact">
                <span>权限总数</span><strong>${permissions.length}</strong>
                <span>高频入口</span><strong>${esc(preset.pathHint || '-')}</strong>
                <span>推荐动作</span><strong>${esc((preset.actions || []).map((item) => item.label).slice(0, 2).join(' / ') || '返回工作台')}</strong>
                <span>权限预览</span><strong>${esc(permissions.slice(0, 3).join(' / ') || '无')}</strong>
              </div>
            </article>
          </div>
          <details class="inline-details">
            <summary>查看全部权限</summary>
            <div class="details-panel">
              <div class="page-hero-highlights">
                ${permissions.length ? permissions.map((item) => `<span class="page-hero-pill mono">${esc(item)}</span>`).join('') : '<span class="page-hero-pill">暂无权限</span>'}
              </div>
            </div>
          </details>
        `;

        techWrap.innerHTML = `
          <details class="inline-details" open>
            <summary>账号原始信息</summary>
            <div class="details-panel">
              <div class="keyvals compact">
                <div><span>username</span><strong>${esc(me.username)}</strong></div>
                <div><span>tenant_code</span><strong>${esc(me.tenant_code || '-')}</strong></div>
                <div><span>tenant_type</span><strong>${esc(me.tenant_type || '-')}</strong></div>
                <div><span>tenant_id</span><strong class="mono">${esc(me.tenant_id || '-')}</strong></div>
              </div>
            </div>
          </details>
          <details class="inline-details">
            <summary>permissions</summary>
            <div class="details-panel">
              <pre>${esc(safeJson(permissions))}</pre>
            </div>
          </details>
          <details class="inline-details">
            <summary>capabilities</summary>
            <div class="details-panel">
              <pre>${esc(safeJson(capabilities))}</pre>
            </div>
          </details>
        `;
        await loadGovernancePreview();
        setSettingsPanel('overview');
      } catch (error) {
        overviewWrap.innerHTML = renderError(error.message);
        accessWrap.innerHTML = renderError(error.message);
        if (governanceWrap) governanceWrap.innerHTML = renderError(error.message);
        techWrap.innerHTML = renderError(error.message);
      }
    },
  };
}

const factories = {
  login: pageLogin,
  dashboard: pageDashboard,
  guide: pageGuide,
  assets: pageAssets,
  models: pageModels,
  training: pageTraining,
  carNumberLabeling: pageCarNumberLabeling,
  pipelines: pagePipelines,
  tasks: pageTasks,
  taskDetail: pageTaskDetail,
  results: pageResults,
  resultTask: pageResults,
  audit: pageAudit,
  devices: pageDevices,
  settings: pageSettings,
  403: page403,
  404: page404,
};

export function getPage(route, ctx) {
  const handler = factories[route.name] || factories['404'];
  return handler(route, ctx);
}
