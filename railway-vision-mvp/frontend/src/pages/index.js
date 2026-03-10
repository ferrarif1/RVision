import { api, apiForm, apiPost, formatDateTime, toQuery } from '../core/api.js';
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
            <strong>Best Checkpoint</strong>
            <p>${esc(String(trainer || '受控训练 Worker'))}</p>
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
          <strong>Best Checkpoint</strong>
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
  const ocrRisk = taskType !== 'car_number_ocr'
    ? null
    : !ocrText
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
      ? '当前没有稳定 OCR 文本，建议人工框选或重新复核。'
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
        <div><span>confidence</span><strong>${esc(formatMetricValue(item.ocrConfidence, { percent: true }))}</strong></div>
        <div><span>engine</span><strong>${esc(item.ocrEngine || '-')}</strong></div>
        <div><span>bbox</span><strong>${esc(item.ocrBBox?.join(', ') || '-')}</strong></div>
      </div>
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
          <strong>${esc(`关联模型 · ${modelId}`)}</strong>
          <p>${esc(validationReport.summary || '当前结果使用的模型验证信息')}</p>
        </div>
        <div class="quick-review-statuses">
          <span class="badge">${esc(validationReport.decision || '-')}</span>
          ${trainingJob?.job_code ? `<span class="badge">${esc(trainingJob.job_code)}</span>` : ''}
        </div>
      </div>
      <div class="keyvals compact">
        <div><span>val_score</span><strong>${esc(formatMetricValue(metrics.val_score, { percent: true }))}</strong></div>
        <div><span>val_accuracy</span><strong>${esc(formatMetricValue(metrics.val_accuracy, { percent: true }))}</strong></div>
        <div><span>val_loss</span><strong>${esc(formatMetricValue(metrics.val_loss))}</strong></div>
        <div><span>history</span><strong>${esc(formatMetricValue(metrics.history_count ?? history.length))}</strong></div>
        <div><span>latency_ms</span><strong>${esc(formatMetricValue(metrics.latency_ms))}</strong></div>
        <div><span>gpu_mem_mb</span><strong>${esc(formatMetricValue(metrics.gpu_mem_mb))}</strong></div>
      </div>
      ${
        history.length
          ? `
              <div class="grid-two training-history-grid-wrap result-model-history-grid">
                ${renderTrainingHistoryChart({
                  title: 'Accuracy Curve',
                  description: '复用训练作业回写的 epoch 历史，快速判断该识别结果背后的模型泛化水平。',
                  history,
                  percent: true,
                  lines: [
                    { key: 'train_accuracy', label: 'train_accuracy', className: 'train-line' },
                    { key: 'val_accuracy', label: 'val_accuracy', className: 'validation-line' },
                  ],
                })}
                ${renderTrainingHistoryChart({
                  title: 'Loss Curve',
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
    </section>
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
    subtitle: '优先处理候选模型、训练作业与设备授权，确保成果模型只在受控范围内交付。',
    focus: ['待审模型与候选训练结果', '租户 / 设备授权范围', '审计证据与结果追溯'],
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
    focus: ['资产准备与任务执行状态', '候选模型协同与发布准备', '客户联调与结果回查'],
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
    title: '提交算法能力并跟踪受控训练与候选交付',
    subtitle: '在受控环境里提交模型、参与微调协作，并持续跟踪候选模型和审批反馈。',
    focus: ['模型提交与版本状态', '训练协作与候选回收', '审批反馈与补充说明'],
    pathHint: '提交模型 -> 训练协作 -> 候选交付',
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
    throw new Error(`HTTP ${resp.status}`);
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
      <section class="lane-grid" id="laneGrid">${renderLoading('加载主线指标...')}</section>
      <section class="lane-grid" id="realDataGrid">${renderLoading('加载真实数据来源...')}</section>
      <section class="grid-two">
        <div class="card">
          <h3>最近资产</h3>
          <div id="recentAssets">${renderLoading()}</div>
        </div>
        <div class="card">
          <h3>最近模型</h3>
          <div id="recentModels">${renderLoading()}</div>
        </div>
      </section>
      <section class="card">
        <h3>最近任务</h3>
        <div id="recentTasks">${renderLoading()}</div>
      </section>
    `,
    async mount(root) {
      root.querySelectorAll('[data-dashboard-nav]').forEach((btn) => {
        btn.addEventListener('click', () => ctx.navigate(btn.getAttribute('data-dashboard-nav')));
      });
      const laneGrid = root.querySelector('#laneGrid');
      const realDataGrid = root.querySelector('#realDataGrid');
      const recentAssets = root.querySelector('#recentAssets');
      const recentModels = root.querySelector('#recentModels');
      const recentTasks = root.querySelector('#recentTasks');
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
          ? `<ul class="compact-list">${assets.map((row) => `<li><strong>${esc(row.file_name)}</strong><span>${esc(row.asset_type)} · ${formatDateTime(row.created_at)}</span></li>`).join('')}</ul>`
          : renderEmpty('暂无资产');
        recentModels.innerHTML = models.length
          ? `<ul class="compact-list">${models.map((row) => `<li><strong>${esc(row.model_code)}:${esc(row.version)}</strong><span>${esc(enumText('model_status', row.status))} · ${formatDateTime(row.created_at)}</span></li>`).join('')}</ul>`
          : renderEmpty('暂无模型');
        recentTasks.innerHTML = tasks.length
          ? `<ul class="compact-list">${tasks.map((row) => `<li><strong>${esc(row.id)}</strong><span>${esc(enumText('task_type', row.task_type))} · ${esc(enumText('task_status', row.status))} · ${formatDateTime(row.created_at)}</span></li>`).join('')}</ul>`
          : renderEmpty('暂无任务');
      } catch (error) {
        laneGrid.innerHTML = renderError(error.message);
        recentAssets.innerHTML = renderError(error.message);
        recentModels.innerHTML = renderError(error.message);
        recentTasks.innerHTML = renderError(error.message);
      }
    },
  };
}

function pageAssets(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const role = primaryRole(ctx.state.user);
  const introText = role.startsWith('buyer_')
    ? '上传图片、视频或 ZIP 数据集包，形成可直接用于训练、验证、微调和推理的受控资产记录。'
    : role.startsWith('platform_')
      ? '统一收口客户资产、用途标记和敏感等级，为训练、验证、推理和审批提供可信输入。'
      : '查看资产输入、用途标记和数据集包摘要。';
  return {
    html: `
      <section class="card">
        <h2>资产中心</h2>
        <p>${esc(introText)}</p>
      </section>
      <section class="grid-two">
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
          <label>dataset_label(数据集标签)</label>
          <input name="dataset_label" placeholder="demo-dataset-001" />
          <label>use_case(业务场景)</label>
          <input name="use_case" placeholder="railway-defect-inspection" />
          <label>intended_model_code(目标模型编码)</label>
          <input name="intended_model_code" placeholder="scene_router" />
          <button class="primary" type="submit">上传资产</button>
          <div id="assetUploadMsg" class="hint"></div>
        </form>
        <section class="card">
          <h3>上传结果</h3>
          <div id="assetUploadResult">${renderEmpty('上传后会生成 asset_id、资源摘要和下一步入口')}</div>
        </section>
      </section>
      <section class="card">
        <h3>使用建议</h3>
        <ul class="focus-list">
          <li>训练 / 微调 / 验证优先使用 ZIP 数据集包，便于一次性提交多层文件夹和多资源样本。</li>
          <li>上传成功后会固定生成 asset_id，后续训练作业、验证流程和任务执行都直接引用该记录。</li>
          <li>推理任务优先使用单图或单视频资产；训练链路可组合 0-n 个单文件资产或多个 ZIP 数据集包。</li>
        </ul>
      </section>
      <section class="card">
        <form id="assetFilterForm" class="inline-form">
          <input name="q" placeholder="搜索 file_name(文件名) / use_case(业务场景) / intended_model_code(目标模型编码)" />
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
      const uploadForm = root.querySelector('#assetUploadForm');
      const uploadMsg = root.querySelector('#assetUploadMsg');
      const uploadResult = root.querySelector('#assetUploadResult');
      const filterForm = root.querySelector('#assetFilterForm');
      const tableWrap = root.querySelector('#assetsTableWrap');
      const assetShowHistoryExports = root.querySelector('#assetShowHistoryExports');
      const assetListMeta = root.querySelector('#assetListMeta');
      const assetListFilters = { showExportHistory: false };

      function prefillTrainingAssets(assetIds) {
        const merged = [...new Set([...splitCsv(localStorage.getItem(STORAGE_KEYS.prefillTrainingAssetIds) || ''), ...assetIds])];
        localStorage.setItem(STORAGE_KEYS.prefillTrainingAssetIds, merged.join(', '));
      }

      async function loadAssets() {
        tableWrap.innerHTML = renderLoading('加载资产列表...');
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
          if (!visibleRows.length) {
            tableWrap.innerHTML = renderEmpty('暂无资产。建议先上传一条单图 / 单视频资产用于推理，或上传 ZIP 数据集包用于训练准备');
            return;
          }
          tableWrap.innerHTML = `
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>asset_id(资产ID)</th><th>file_name(文件名)</th><th>type(类型)</th><th>resource_count(资源数)</th><th>purpose(用途)</th><th>sensitivity(敏感等级)</th><th>创建时间</th><th>操作</th></tr></thead>
                <tbody>
                  ${visibleRows.map((row) => {
                    const datasetMeta = row.dataset_version_meta || null;
                    const datasetBadge = isCarNumberOcrExportAsset(row)
                      ? `<span class="badge">${esc(datasetMeta?.is_latest ? `OCR 最新 ${datasetMeta?.version || ''}`.trim() : `OCR 历史 ${datasetMeta?.version || ''}`.trim())}</span>`
                      : '';
                    return `
                    <tr>
                      <td class="mono">${esc(row.id)}</td>
                      <td>
                        ${esc(row.file_name)}
                        ${datasetBadge}
                      </td>
                      <td>${esc(enumText('asset_type', row.asset_type))}</td>
                      <td>${archiveResourceCount(row.meta || {}) || 1}</td>
                      <td>${esc(enumText('asset_purpose', (row.meta || {}).asset_purpose || '-'))}</td>
                      <td>${esc(enumText('sensitivity_level', row.sensitivity_level))}</td>
                      <td>${formatDateTime(row.created_at)}</td>
                      <td class="row-actions">
                        <button class="ghost" data-copy-asset="${esc(row.id)}">复制ID</button>
                        <button class="ghost" data-use-training-asset="${esc(row.id)}">用于训练</button>
                        ${isTaskAsset(row) ? `<button class="primary" data-quick-detect-asset="${esc(row.id)}">快速识别</button>` : ''}
                        ${isTaskAsset(row) ? `<button class="ghost" data-use-asset="${esc(row.id)}">用于任务</button>` : ''}
                      </td>
                    </tr>
                  `;
                  }).join('')}
                </tbody>
              </table>
            </div>
          `;
          tableWrap.querySelectorAll('[data-copy-asset]').forEach((btn) => {
            btn.addEventListener('click', async () => {
              const assetId = btn.getAttribute('data-copy-asset') || '';
              try {
                await navigator.clipboard.writeText(assetId);
                ctx.toast('资产ID已复制');
              } catch {
                ctx.toast(`资产ID: ${assetId}`);
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
              { label: 'asset_id', value: data.id, mono: true },
              { label: 'file_name', value: data.file_name },
              { label: 'asset_type', value: enumText('asset_type', data.asset_type) },
              { label: 'sensitivity', value: enumText('sensitivity_level', data.sensitivity_level) },
              archiveResourceCount(data.meta || {})
                ? { label: 'resource_count', value: archiveResourceCount(data.meta || {}) }
                : null,
            ],
            `
              <div class="row-actions">
                <button class="ghost" id="copyAssetIdBtn">复制资产ID</button>
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
  const introText = role.startsWith('supplier')
    ? '提交初始算法或候选模型，持续跟踪审批反馈与训练协作进度。'
    : role.startsWith('platform_')
      ? '审批候选模型、发布授权范围，并把成果模型收敛到受控交付链路。'
      : '查看已授权模型、候选状态与交付进度。';

  return {
    html: `
      <section class="card">
        <h2>模型中心</h2>
        <p>${esc(introText)}</p>
      </section>
      <section class="grid-two">
        <form id="modelRegisterForm" class="card form-grid">
          <h3>提交模型包</h3>
          <label>模型包(.zip)</label>
          <input type="file" name="package" accept=".zip" required />
          <label>model_source_type(模型来源类型)</label>
          <select name="model_source_type">
            <option value="delivery_candidate">${enumText('model_source_type', 'delivery_candidate')}</option>
            <option value="finetuned_candidate">${enumText('model_source_type', 'finetuned_candidate')}</option>
            <option value="initial_algorithm">${enumText('model_source_type', 'initial_algorithm')}</option>
            <option value="pretrained_seed">${enumText('model_source_type', 'pretrained_seed')}</option>
          </select>
          <label>model_type(模型类型)</label>
          <select name="model_type">
            <option value="expert">${enumText('model_type', 'expert')}</option>
            <option value="router">${enumText('model_type', 'router')}</option>
          </select>
          <label>plugin_name(插件名称)</label>
          <input name="plugin_name" placeholder="scene_router" />
          <label>training_round(训练轮次)</label>
          <input name="training_round" placeholder="round-1" />
          <label>dataset_label(数据集标签)</label>
          <input name="dataset_label" placeholder="buyer-demo-v1" />
          <label>training_summary(训练摘要)</label>
          <textarea name="training_summary" rows="2" placeholder="微调摘要"></textarea>
          <button class="primary" type="submit">提交模型</button>
          <div id="modelRegisterMsg" class="hint"></div>
          <div id="modelRegisterResult">${renderEmpty('提交模型后会在这里显示 model_id、版本和下一步动作')}</div>
        </form>
        <section class="card">
          <h3>模型时间线</h3>
          <div id="modelTimelineWrap">${renderEmpty('在模型列表点击“时间线”，查看提交、审批、发布和回收轨迹')}</div>
          <div class="readiness-block">
            <h3>评估与风险</h3>
            <div id="modelReadinessWrap">${renderEmpty('在模型列表点击“评估”，查看自动验证结论和发布前风险摘要')}</div>
          </div>
          <div class="readiness-block">
            <h3>审批工作台</h3>
            <div id="modelApprovalWorkbenchWrap">${renderEmpty('先在模型列表里选一版候选模型，这里会自动推荐验证样本、汇总验证结果，并在满足门禁后给出一键审批。')}</div>
          </div>
          <div class="readiness-block">
            <h3>发布工作台</h3>
            <div id="modelReleaseWorkbenchWrap">${renderEmpty('审批通过后，在这里选择设备、买家和交付方式。系统会先做发布前评估，再确认发布。')}</div>
          </div>
        </section>
      </section>
      <section class="card">
        <h3>模型列表</h3>
        <div class="section-toolbar">
          <input id="modelListSearch" placeholder="搜索 model_code / version / 插件 / 租户" />
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
      <section class="grid-two">
        <section class="card">
          <h3>训练作业协作</h3>
          <div id="trainingJobsWrap">${canViewTrainingJob ? renderLoading('加载训练作业...') : renderEmpty('当前角色无训练作业查看权限')}</div>
        </section>
        <section class="card">
          <h3>创建训练作业</h3>
          ${
            canCreateTrainingJob
              ? `
                <form id="trainingJobForm" class="form-grid">
                  <label>training_kind(训练类型)</label>
                  <select name="training_kind">
                    <option value="finetune">${enumText('training_kind', 'finetune')}</option>
                    <option value="train">${enumText('training_kind', 'train')}</option>
                    <option value="evaluate">${enumText('training_kind', 'evaluate')}</option>
                  </select>
                  <label>asset_ids(训练资产ID，0-n，支持逗号/空格分隔)</label>
                  <input name="asset_ids" placeholder="asset-1, asset-2" />
                  <div class="hint">支持单图/单视频资产，也支持 ZIP 数据集包；一个 ZIP 包对应 1 个 asset_id。</div>
                  <label>validation_asset_ids(验证资产ID，0-n，支持逗号/空格分隔)</label>
                  <input name="validation_asset_ids" placeholder="asset-3,asset-4" />
                  <label>base_model_id(基础模型ID，可选)</label>
                  <input name="base_model_id" placeholder="model-id" />
                  <label>target_model_code(目标模型编码)</label>
                  <input name="target_model_code" placeholder="car_number_ocr" required />
                  <label>target_version(目标版本)</label>
                  <input name="target_version" placeholder="v2.0.0" required />
                  <button class="primary" type="submit">创建训练作业</button>
                  <div id="trainingJobMsg" class="hint"></div>
                </form>
              `
              : renderEmpty('当前角色无训练作业创建权限')
          }
        </section>
      </section>
    `,
    async mount(root) {
      const modelsWrap = root.querySelector('#modelsTableWrap');
      const registerForm = root.querySelector('#modelRegisterForm');
      const registerMsg = root.querySelector('#modelRegisterMsg');
      const registerResult = root.querySelector('#modelRegisterResult');
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
      const modelListFilters = { q: '', status: '', source: '' };

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
            <div><span>val_score</span><strong>${esc(formatMetricValue(metrics.val_score, { digits: 4 }))}</strong></div>
            <div><span>val_accuracy</span><strong>${esc(formatMetricValue(metrics.val_accuracy, { percent: true, digits: 4 }))}</strong></div>
            <div><span>val_loss</span><strong>${esc(formatMetricValue(metrics.val_loss, { digits: 4 }))}</strong></div>
            <div><span>history</span><strong>${esc(metrics.history_count ?? 0)}</strong></div>
            <div><span>best_checkpoint</span><strong>${esc(metrics.best_checkpoint?.path || metrics.best_checkpoint?.metric || '-')}</strong></div>
            <div><span>latency_ms / gpu_mem_mb</span><strong>${esc(`${metrics.latency_ms ?? '-'} / ${metrics.gpu_mem_mb ?? '-'}`)}</strong></div>
          </div>
          ${renderReadinessChecks('审批门禁', validationReport)}
          ${renderReadinessChecks(releaseTitle, releaseRiskSummary)}
          <details><summary>Advanced</summary><pre>${esc(safeJson(data))}</pre></details>
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
                <label class="approval-inline-label">task_type</label>
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
                      <tr><th>任务</th><th>资产</th><th>状态</th><th>输出</th><th>confidence</th><th>操作</th></tr>
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
                  <label>target_devices(目标设备，逗号分隔)</label>
                  <input id="releaseTargetDevices" value="${esc(initialDevices)}" list="releaseDevicesDatalist" placeholder="edge-01" />
                  <label>target_buyers(目标买家，tenant_code，逗号分隔)</label>
                  <input id="releaseTargetBuyers" value="${esc(initialBuyers)}" list="releaseBuyersDatalist" placeholder="buyer-demo-001" />
                  <datalist id="releaseDevicesDatalist">
                    ${devices.map((row) => `<option value="${esc(row.code)}">${esc(row.name || row.code)}</option>`).join('')}
                  </datalist>
                  <datalist id="releaseBuyersDatalist">
                    ${buyers.map((row) => `<option value="${esc(row.tenant_code)}">${esc(row.name || row.tenant_code)}</option>`).join('')}
                  </datalist>
                </div>
                <div class="form-grid">
                  <label>delivery_mode(交付方式)</label>
                  <select id="releaseDeliveryMode">
                    <option value="local_key" ${recommended.delivery_mode === 'local_key' ? 'selected' : ''}>本地解密</option>
                    <option value="api" ${recommended.delivery_mode === 'api' ? 'selected' : ''}>API</option>
                    <option value="hybrid" ${recommended.delivery_mode === 'hybrid' ? 'selected' : ''}>混合</option>
                  </select>
                  <label>authorization_mode(授权方式)</label>
                  <select id="releaseAuthorizationMode">
                    <option value="device_key" ${recommended.authorization_mode === 'device_key' ? 'selected' : ''}>device_key</option>
                    <option value="api_token" ${recommended.authorization_mode === 'api_token' ? 'selected' : ''}>api_token</option>
                    <option value="hybrid" ${recommended.authorization_mode === 'hybrid' ? 'selected' : ''}>hybrid</option>
                  </select>
                  <label>local_key_label(本地密钥标签，可选)</label>
                  <input id="releaseLocalKeyLabel" value="${esc(recommended.local_key_label || '')}" placeholder="edge/keys/model_decrypt.key" />
                  <label>api_access_key_label(API 密钥标签，可选)</label>
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
                <details><summary>Advanced</summary><pre>${esc(safeJson(data))}</pre></details>
              `
            : renderEmpty('该模型暂无时间线数据');
        } catch (error) {
          timelineWrap.innerHTML = renderError(error.message);
        }
      }

      async function openModelReadiness(modelId, releasePayload = null) {
        activeModelId = modelId;
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
                  <span>${esc(enumText('training_kind', row.training_kind))} · ${esc(enumText('training_status', row.status))} · train=${esc(row.asset_count ?? 0)} · val=${esc(row.validation_asset_count ?? 0)} · candidate=${esc(row.candidate_model?.id || '-')}</span>
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
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th>model_code(模型编码)</th><th>version(版本)</th><th>status(状态)</th><th>validation(验证)</th><th>risk(最近风险)</th><th>source(来源)</th><th>hash(摘要)</th><th>操作</th>
                </tr>
              </thead>
              <tbody>
                ${filtered.map((row) => `
                  <tr data-model-row="${esc(row.id)}" class="${requestedFocusModelId === row.id ? 'active-row' : ''}">
                    <td>${esc(row.model_code)}</td>
                    <td>${esc(row.version)}</td>
                    <td>${esc(enumText('model_status', row.status))}</td>
                    <td>${row.validation_report?.decision ? `<span class="badge">${esc(row.validation_report.decision)}</span>` : '-'}</td>
                    <td>${row.latest_release_risk_summary?.decision ? `<span class="badge">${esc(row.latest_release_risk_summary.decision)}</span>` : '-'}</td>
                    <td>${esc(enumText('model_source_type', (row.platform_meta || {}).model_source_type || '-'))}</td>
                    <td class="mono">${esc((row.model_hash || '').slice(0, 16))}...</td>
                    <td>
                      <div class="row-actions">
                        <button class="ghost" data-model-timeline="${esc(row.id)}">时间线</button>
                        <button class="ghost" data-model-readiness="${esc(row.id)}">评估</button>
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
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `;

        modelsWrap.querySelectorAll('[data-model-timeline]').forEach((btn) => {
          btn.addEventListener('click', async () => {
            const modelId = btn.getAttribute('data-model-timeline');
            await openModelTimeline(modelId);
          });
        });

        modelsWrap.querySelectorAll('[data-model-readiness]').forEach((btn) => {
          btn.addEventListener('click', async () => {
            const modelId = btn.getAttribute('data-model-readiness');
            try {
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
              await openModelReleaseWorkbench(modelId);
              releaseWorkbenchWrap?.scrollIntoView({ block: 'center', behavior: 'smooth' });
            } catch (error) {
              ctx.toast(error.message || '发布工作台加载失败', 'error');
            }
          });
        });
      }

      async function loadModels() {
        modelsWrap.innerHTML = renderLoading('加载模型列表...');
        try {
          const rows = await ctx.get('/models');
          const visibleRows = filterBusinessModels(rows || []);
          cachedModels = visibleRows;
          if (!visibleRows.length) {
            modelsWrap.innerHTML = renderEmpty((rows || []).length ? '当前只有测试/占位模型，已自动隐藏' : '暂无模型，可先提交一个模型包，或等待供应商交付候选模型');
            return;
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
              { label: 'model_id', value: created.id, mono: true },
              { label: 'model_code', value: created.model_code },
              { label: 'version', value: created.version },
              { label: 'status', value: enumText('model_status', created.status || 'SUBMITTED') },
              { label: 'plugin', value: created.plugin_name || '-' },
              { label: 'model_type', value: enumText('model_type', created.model_type || '-') },
            ],
            `
              <div class="row-actions">
                <button class="ghost" type="button" id="copyModelIdBtn">复制模型ID</button>
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
            await openModelTimeline(created.id);
          });
          root.querySelector('#openModelReadinessBtn')?.addEventListener('click', async () => {
            try {
              await openModelReadiness(created.id);
            } catch (error) {
              ctx.toast(error.message || '模型评估失败', 'error');
            }
          });
          ctx.toast('模型提交成功');
          registerForm.reset();
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

      await Promise.all([loadModels(), loadTrainingJobs()]);
      if (cachedModels.length && trainingJobForm && !trainingJobForm.querySelector('[data-helper]')) {
        const hint = document.createElement('div');
        hint.className = 'hint';
        hint.setAttribute('data-helper', 'true');
        hint.textContent = `可选 base_model_id 示例：${cachedModels[0].id}`;
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
  const introText = role.startsWith('platform_')
    ? '统一查看训练作业、Worker 健康和候选模型回收状态，确保训练链路始终处于平台控制面内。'
    : '查看受控训练作业、候选模型回收状态和 Worker 运行情况。';
  return {
    html: `
      <section class="card">
        <h2>训练中心</h2>
        <p>${esc(introText)}</p>
        <div class="row-actions">
          <button id="openCarNumberLabeling" class="ghost" type="button">打开车号文本复核</button>
        </div>
      </section>
      <section class="card">
        <h3>运行告警</h3>
        <div id="trainingRuntimeAlertWrap">${renderLoading('加载训练运行健康状态...')}</div>
      </section>
      <section class="grid-two">
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
        <section class="card">
          <h3>训练 Worker</h3>
          <div id="trainingWorkersWrap">${renderLoading('加载 worker...')}</div>
          ${
            canManageWorkers
              ? `
                <form id="registerWorkerForm" class="form-grid">
                  <h4>注册/刷新 Worker</h4>
                  <label>worker_code(Worker 编码)</label><input name="worker_code" placeholder="train-worker-01" required />
                  <label>name(名称)</label><input name="name" placeholder="GPU Worker 01" required />
                  <label>host(主机地址)</label><input name="host" placeholder="10.0.0.31" />
                  <label>status(状态)</label>
                  <select name="status">
                    <option value="ACTIVE">${enumText('worker_status', 'ACTIVE')}</option>
                    <option value="INACTIVE">${enumText('worker_status', 'INACTIVE')}</option>
                    <option value="UNHEALTHY">${enumText('worker_status', 'UNHEALTHY')}</option>
                  </select>
                  <label>labels(JSON 标签)</label><textarea name="labels" rows="2">{}</textarea>
                  <label>resources(JSON 资源)</label><textarea name="resources" rows="2">{}</textarea>
                  <button class="primary" type="submit">注册 Worker</button>
                  <div id="registerWorkerMsg" class="hint"></div>
                </form>
              `
              : renderEmpty('当前角色无 worker 管理权限')
          }
        </section>
      </section>
      <section class="card">
        <h3>训练结果摘要</h3>
        <p class="hint">把基础模型、数据规模、关键指标和后续动作放在一屏里，方便快速判断这轮训练是否值得进入审批、发布或继续迭代。</p>
        <div id="trainingRunSummaryWrap">${renderLoading('加载训练摘要...')}</div>
      </section>
      ${
        canCreateTrainingJob
          ? `
            <section class="card">
              <h3>创建训练作业</h3>
              <div class="grid-two">
                <section class="lane-card">
                  <h4>供应商算法库</h4>
                  <p class="hint">从已发布给当前租户的算法里直接选一个基础模型，系统会自动带入供应商归属信息。</p>
                  <div class="section-toolbar compact">
                    <input id="trainingModelSearch" placeholder="搜索算法 / 供应商 / 任务类型" />
                    <div id="trainingModelMeta" class="hint"></div>
                  </div>
                  <div id="trainingModelLibrary">${renderLoading('加载供应商算法...')}</div>
                </section>
                <section class="lane-card">
                  <h4>训练机池</h4>
                  <p class="hint">选择要执行训练的机器。可按 worker_code、host 或 IP 精确派发到指定节点。</p>
                  <div class="section-toolbar compact">
                    <input id="trainingWorkerSearch" placeholder="搜索 worker_code / host / 状态" />
                    <label class="checkbox-row"><input id="trainingWorkerShowHistory" type="checkbox" /> 显示历史异常</label>
                    <div id="trainingWorkerMeta" class="hint"></div>
                  </div>
                  <div id="trainingWorkerPool">${renderLoading('加载训练机...')}</div>
                </section>
              </div>
              <section class="lane-card">
                <h4>训练数据集版本</h4>
                <p class="hint">快速识别导出的数据集会自动形成版本记录。可直接把某个版本放入训练集或验证集，不必手工回填资产 ID。</p>
                <div class="section-toolbar compact">
                  <input id="trainingDatasetSearch" placeholder="搜索 dataset_label / 标签 / source" />
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
                <div id="trainingDatasetPreviewWrap" class="selection-summary">${renderEmpty('选择某个数据集版本后，可在这里查看样本摘要、标签和复核状态。')}</div>
              </section>
              <form id="trainingCreateForm" class="form-grid">
                <div class="grid-two">
                  <div class="form-grid">
                    <label>training_kind(训练类型)</label>
                    <select name="training_kind">
                      <option value="finetune">${enumText('training_kind', 'finetune')}</option>
                      <option value="train">${enumText('training_kind', 'train')}</option>
                      <option value="evaluate">${enumText('training_kind', 'evaluate')}</option>
                    </select>
                    <label>asset_ids(训练资产ID，0-n，支持逗号/空格分隔)</label>
                    <input name="asset_ids" list="trainingAssetsDatalist" placeholder="asset-id-1, asset-id-2" />
                    <div class="hint">训练/验证资产可以为空，也可以引用多个单文件资产或多个 ZIP 数据集包。</div>
                    <label>validation_asset_ids(验证资产ID，0-n，支持逗号/空格分隔)</label>
                    <input name="validation_asset_ids" list="trainingAssetsDatalist" placeholder="asset-id-3" />
                    <label>target_model_code(目标模型编码)</label>
                    <input name="target_model_code" placeholder="railway-defect-ft" required />
                    <label>target_version(目标版本)</label>
                    <input name="target_version" placeholder="v20260306.1" required />
                  </div>
                  <div class="form-grid">
                    <label>base_model_id(供应商算法 / 基础模型 ID，可选)</label>
                    <input name="base_model_id" list="trainingModelsDatalist" placeholder="model-id" />
                    <div class="hint">建议先从上方“供应商算法库”选择，避免手工输入错误模型 ID。</div>
                    <label>worker_code(训练机编码，可选)</label>
                    <input name="worker_code" list="trainingWorkersCodeDatalist" placeholder="train-worker-01" />
                    <label>worker_host(IP / 主机地址，可选)</label>
                    <input name="worker_host" list="trainingWorkersHostDatalist" placeholder="10.0.0.31" />
                    <label>spec(JSON 训练参数，可选)</label>
                    <textarea name="spec" rows="4">{}</textarea>
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
              </form>
            </section>
          `
          : ''
      }
    `,
    async mount(root) {
      root.querySelector('#openCarNumberLabeling')?.addEventListener('click', () => ctx.navigate('training/car-number-labeling'));
      const jobsWrap = root.querySelector('#trainingJobsTableWrap');
      const workersWrap = root.querySelector('#trainingWorkersWrap');
      const filterForm = root.querySelector('#trainingFilterForm');
      const registerWorkerForm = root.querySelector('#registerWorkerForm');
      const registerWorkerMsg = root.querySelector('#registerWorkerMsg');
      const createForm = root.querySelector('#trainingCreateForm');
      const createMsg = root.querySelector('#trainingCreateMsg');
      const trainingRuntimeAlertWrap = root.querySelector('#trainingRuntimeAlertWrap');
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
      const specInput = createForm?.querySelector('textarea[name="spec"]');
      let assistAssets = [];
      let assistModels = [];
      let assistWorkers = [];
      let assistDatasetVersions = [];
      let activeDatasetCompare = null;
      let activeDatasetCompareVersionId = '';
      let datasetCompareFilters = defaultDatasetCompareFilters();
      let activeDatasetPreview = null;
      let datasetCompareBlobUrls = [];
      let datasetPreviewBlobUrls = [];
      let cachedTrainingJobs = [];
      let activeTrainingJobId = '';
      const trainingLibraryFilters = {
        modelQuery: '',
        workerQuery: '',
        workerShowHistory: false,
        datasetQuery: '',
        datasetPurpose: '',
        datasetRecommendedOnly: false,
        datasetShowHistory: false,
      };

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

      function compactValue(value) {
        if (value === null || value === undefined || value === '') return '未声明';
        if (Array.isArray(value)) return value.length ? value.join(', ') : '未声明';
        if (typeof value === 'object') {
          const keys = Object.keys(value);
          return keys.length ? keys.map((key) => `${key}=${value[key]}`).join(' · ') : '未声明';
        }
        return String(value);
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
          trainingRuntimeAlertWrap.innerHTML = renderEmpty('当前没有训练超时或 Worker 心跳异常告警。');
          return;
        }
        trainingRuntimeAlertWrap.innerHTML = `
          <div class="alert-grid">
            <article class="alert-card critical">
              <span>CRITICAL 作业</span>
              <strong>${esc(String(criticalJobs.length))}</strong>
              <small>${esc(criticalJobs[0]?.alert_reason || '运行中超时或 Worker 已失联')}</small>
            </article>
            <article class="alert-card warning">
              <span>WARNING 作业</span>
              <strong>${esc(String(warningJobs.length))}</strong>
              <small>${esc(warningJobs[0]?.alert_reason || '派发后长时间未开始')}</small>
            </article>
            <article class="alert-card">
              <span>异常 Worker</span>
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
                    ${unhealthyWorkers.slice(0, 2).map((row) => `<span>Worker ${esc(row.worker_code)} · ${esc(row.alert_reason || '心跳异常')}</span>`).join('')}
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
            ctx.toast(`已刷新训练运行健康状态：异常Worker ${result.counts?.unhealthy_worker_count || 0}，超时作业 ${result.counts?.timed_out_job_count || 0}`);
            await Promise.all([loadWorkers(), loadJobTable()]);
          } catch (error) {
            ctx.toast(error.message || '刷新健康状态失败', 'error');
          } finally {
            button.disabled = false;
          }
        });
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
        const trainer = output.trainer || job.spec?.trainer || '受控训练 Worker';
        const currentStage = output.stage || (job.status === 'SUCCEEDED' ? 'completed' : job.status === 'RUNNING' ? 'training' : '-');
        const candidateModel = job.candidate_model;
        const canCreateTask = hasPermission(ctx.state, 'task.create');
        const historyEpochCount = Number(output.epochs ?? 0) || history.length || Number(job.spec?.epochs ?? 0) || 0;
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
                      ? '训练正在执行中，当前摘要会随着 Worker 回写持续刷新。'
                      : '当前展示的是这条训练作业的最新状态，适合快速核对基础模型、数据规模和目标节点。'
                )}</p>
              </div>
              <div class="row-actions">
                <button class="ghost" type="button" data-copy-training-job="${esc(job.id)}">复制作业ID</button>
                ${
                  candidateModel?.id
                    ? `<button class="ghost" type="button" data-copy-candidate-model="${esc(candidateModel.id)}">复制候选模型ID</button>`
                    : ''
                }
                ${
                  candidateModel?.id
                    ? `<button class="primary" type="button" data-open-candidate-model="${esc(candidateModel.id)}">查看候选模型</button>`
                    : ''
                }
                ${
                  canCreateTask && candidateModel?.id
                    ? '<button class="ghost" type="button" data-create-candidate-validation>去任务中心验证候选模型</button>'
                    : canCreateTask
                      ? '<button class="ghost" type="button" data-go-training-task>去任务中心</button>'
                      : ''
                }
              </div>
            </section>
            <div class="keyvals">
              <div><span>job_code</span><strong class="mono">${esc(job.job_code)}</strong></div>
              <div><span>基础模型</span><strong>${esc(job.base_model ? `${job.base_model.model_code}:${job.base_model.version}` : '未指定')}</strong></div>
              <div><span>候选模型</span><strong>${esc(candidateModel ? `${candidateModel.model_code}:${candidateModel.version}` : '等待回收')}</strong></div>
              <div><span>执行节点</span><strong>${esc(job.assigned_worker_code || job.worker_selector?.host || job.worker_selector?.hosts?.[0] || '未派发')}</strong></div>
              <div><span>当前阶段</span><strong>${esc(currentStage)}</strong></div>
              <div><span>训练时长</span><strong>${esc(formatDurationWindow(job.started_at, job.finished_at, output.duration_sec))}</strong></div>
              <div><span>创建时间</span><strong>${esc(formatDateTime(job.created_at))}</strong></div>
              <div><span>完成时间</span><strong>${esc(formatDateTime(job.finished_at))}</strong></div>
              <div><span>供应商</span><strong>${esc(job.owner_tenant_code || '-')}</strong></div>
              <div><span>买家租户</span><strong>${esc(job.buyer_tenant_code || '-')}</strong></div>
              <div><span>artifact_sha256</span><strong class="mono">${esc(truncateMiddle(output.artifact_sha256, 10, 8))}</strong></div>
              <div><span>base_model_hash</span><strong class="mono">${esc(truncateMiddle(output.base_model_hash, 10, 8))}</strong></div>
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
                title: 'Loss Curve',
                description: '按 epoch 查看 train / val loss，判断是否出现发散或过拟合。',
                history,
                lowerIsBetter: true,
                lines: [
                  { key: 'train_loss', label: 'train_loss', className: 'train-line' },
                  { key: 'val_loss', label: 'val_loss', className: 'validation-line' },
                ],
              })}
              ${renderTrainingHistoryChart({
                title: 'Accuracy Curve',
                description: '按 epoch 查看 train / val accuracy，适合快速判断收敛与泛化。',
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
                  <span>${esc(`history_count=${output.history_count ?? history.length}`)}</span>
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
                <p>${esc(`asset=${job.asset_count ?? 0} · samples=${output.train_samples ?? '-'}`)}</p>
              </article>
              <article class="training-run-split-card validation">
                <div class="training-run-split-head">
                  <span>验证集</span>
                  <strong>${esc(validationShare)}</strong>
                </div>
                <div class="training-run-split-value">${esc(String(validationResources))}</div>
                <p>${esc(`asset=${job.validation_asset_count ?? 0} · samples=${output.val_samples ?? '-'}`)}</p>
              </article>
            </section>
            <div class="grid-two">
              <section class="selection-summary">
                <strong>训练配置</strong>
                <span>训练器：${esc(String(trainer))}</span>
                <span>预处理：${esc(compactValue(job.spec?.preprocessing || job.spec?.preprocess || job.spec?.resize))}</span>
                <span>增强：${esc(compactValue(job.spec?.augmentations || job.spec?.augmentation))}</span>
                <span>特征说明：${esc(compactValue(output.feature_spec || job.spec?.feature_spec))}</span>
                <details><summary>spec / output_summary</summary><pre>${esc(safeJson({ spec: job.spec || {}, output_summary: output }))}</pre></details>
              </section>
              <section class="selection-summary">
                <strong>数据来源</strong>
                <span>目标版本：${esc(`${job.target_model_code}:${job.target_version}`)}</span>
                <span>训练资产：${esc(trainRefs.length ? trainRefs.map((row) => row.version ? `${row.version.dataset_label}:${row.version.version}` : row.asset?.file_name || row.assetId).join(' / ') : '未绑定')}</span>
                <span>验证资产：${esc(validationRefs.length ? validationRefs.map((row) => row.version ? `${row.version.dataset_label}:${row.version.version}` : row.asset?.file_name || row.assetId).join(' / ') : '未绑定')}</span>
                ${candidateModel?.id ? '<span>下一步：候选模型已回收后，可点上方“去任务中心验证候选模型”，任务页会自动预填模型/任务类型/设备，但仍需选择一张单图或视频资产；训练用 ZIP 数据集不能直接做在线验证。</span>' : '<span>下一步：候选模型回收后，任务页可直接拿候选模型做验证。</span>'}
                ${job.error_message ? `<span>错误摘要：${esc(job.error_message)}</span>` : '<span>错误摘要：无</span>'}
              </section>
            </div>
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
      }

      function renderTrainingJobTable(rows) {
        if (!rows.length) {
          jobsWrap.innerHTML = renderEmpty('暂无训练作业，可从模型中心或本页下方创建一条训练 / 微调作业');
          renderTrainingRunSummary();
          return;
        }
        jobsWrap.innerHTML = `
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th>job_code(作业编码)</th><th>alert(告警)</th><th>status(状态)</th><th>kind(类型)</th><th>train/val(资产数)</th><th>base_model(基础模型)</th><th>candidate_model(候选模型)</th><th>worker(执行节点)</th><th>创建时间</th><th>操作</th>
                </tr>
              </thead>
              <tbody>
                ${rows.map((row) => `
                  <tr class="${activeTrainingJobId === row.id ? 'active-row' : ''}">
                    <td class="mono">${esc(row.job_code)}</td>
                    <td>${row.alert_level ? `<span class="badge">${esc(row.alert_level)}</span>` : '-'}</td>
                    <td>${esc(enumText('training_status', row.status))}</td>
                    <td>${esc(enumText('training_kind', row.training_kind))}</td>
                    <td>${esc(`${row.asset_count ?? 0}/${row.validation_asset_count ?? 0}`)}</td>
                    <td class="mono">${esc(row.base_model ? `${row.base_model.model_code}:${row.base_model.version}` : '-')}</td>
                    <td class="mono">${esc(row.candidate_model ? `${row.candidate_model.model_code}:${row.candidate_model.version}` : '-')}</td>
                    <td>${esc(row.assigned_worker_code || row.worker_selector?.host || row.worker_selector?.hosts?.[0] || '-')}</td>
                    <td>${formatDateTime(row.created_at)}</td>
                    <td>
                      <div class="row-actions">
                        <button class="ghost" type="button" data-training-open-summary="${esc(row.id)}">摘要</button>
                        ${row.can_cancel ? `<button class="ghost" type="button" data-training-cancel="${esc(row.id)}">取消</button>` : ''}
                        ${row.can_retry ? `<button class="ghost" type="button" data-training-retry="${esc(row.id)}">重试</button>` : ''}
                        ${row.can_reassign ? `<button class="ghost" type="button" data-training-reassign="${esc(row.id)}">改派到当前训练机</button>` : ''}
                      </div>
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `;
        jobsWrap.querySelectorAll('[data-training-open-summary]').forEach((button) => {
          button.addEventListener('click', () => {
            activeTrainingJobId = button.getAttribute('data-training-open-summary') || '';
            renderTrainingJobTable(cachedTrainingJobs);
            renderTrainingRunSummary();
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
        } catch (error) {
          jobsWrap.innerHTML = renderError(error.message);
          if (trainingRunSummaryWrap) trainingRunSummaryWrap.innerHTML = renderError(error.message);
          renderTrainingRuntimeAlerts();
        }
      }

      async function loadWorkers() {
        workersWrap.innerHTML = renderLoading('加载 worker...');
        try {
          const rows = await ctx.get('/training/workers');
          assistWorkers = rows || [];
          if (!rows.length) {
            workersWrap.innerHTML = renderEmpty('暂无 Worker，请先接入训练执行节点或在下方注册 Worker');
            if (workerPool) workerPool.innerHTML = renderEmpty('当前没有可用于训练分配的机器');
            if (workerCodesDatalist) workerCodesDatalist.innerHTML = '';
            if (workerHostsDatalist) workerHostsDatalist.innerHTML = '';
            renderTrainingRuntimeAlerts();
            return;
          }
          const activeRows = rows.filter((row) => row.status === 'ACTIVE');
          const archivedRows = rows.filter((row) => row.status !== 'ACTIVE');
          const visibleRows = trainingLibraryFilters.workerShowHistory ? rows : activeRows;
          workersWrap.innerHTML = `
            <div class="hint">默认仅展示活跃 Worker。历史异常/失联记录 ${archivedRows.length} 条，可在训练机池里勾选“显示历史异常”查看。</div>
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>worker_code(Worker 编码)</th><th>alert(告警)</th><th>status(状态)</th><th>host(主机)</th><th>outstanding(待处理)</th><th>last_seen(最近心跳)</th><th>resources(资源)</th><th>操作</th></tr></thead>
                <tbody>
                  ${visibleRows.map((row) => `
                    <tr>
                      <td class="mono">${esc(row.worker_code)}</td>
                      <td>${row.alert_level ? `<span class="badge">${esc(row.alert_level)}</span>` : '-'}</td>
                      <td>${esc(enumText('worker_status', row.status))}</td>
                      <td>${esc(row.host || '-')}</td>
                      <td>${esc(row.outstanding_jobs ?? 0)}</td>
                      <td>${formatDateTime(row.last_seen_at)}</td>
                      <td><details><summary>查看</summary><pre>${esc(safeJson(row.resources || {}))}</pre></details></td>
                      <td><button class="ghost" type="button" data-pick-worker="${esc(row.worker_code)}">选为训练机</button></td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
            ${!visibleRows.length && archivedRows.length ? renderEmpty('当前没有活跃 Worker；如需排查历史失联节点，请勾选“显示历史异常”') : ''}
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
          renderWorkerPool();
          renderTrainingRuntimeAlerts();
          workersWrap.querySelectorAll('[data-pick-worker]').forEach((button) => {
            button.addEventListener('click', () => fillWorkerSelection(button.getAttribute('data-pick-worker') || ''));
          });
        } catch (error) {
          if (String(error.message || '').includes('403')) {
            workersWrap.innerHTML = renderEmpty('当前角色无 Worker 查看权限');
            if (workerPool) workerPool.innerHTML = renderEmpty('当前角色无训练机查看权限');
            renderTrainingRuntimeAlerts();
            return;
          }
          workersWrap.innerHTML = renderError(error.message);
          if (workerPool) workerPool.innerHTML = renderError(error.message);
          renderTrainingRuntimeAlerts();
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

      function refreshSelectionSummary() {
        if (!selectionSummary) return;
        const model = selectedModel();
        const worker = selectedWorker();
        const trainAssetIds = splitCsv(assetIdsInput?.value || '');
        const validationAssetIds = splitCsv(validationAssetIdsInput?.value || '');
        const selectedTrainVersions = assistDatasetVersions.filter((row) => trainAssetIds.includes(row.asset_id));
        const selectedValidationVersions = assistDatasetVersions.filter((row) => validationAssetIds.includes(row.asset_id));
        selectionSummary.innerHTML = `
          <strong>当前选择</strong>
          <span>供应商算法：${esc(model ? `${model.model_code}:${model.version} · ${model.owner_tenant_name || model.owner_tenant_code || '供应商'}` : '未选择')}</span>
          <span>训练机：${esc(worker ? `${worker.worker_code}${worker.host ? ` · ${worker.host}` : ''}` : '未选择')}</span>
          <span>训练集版本：${esc(selectedTrainVersions.length ? selectedTrainVersions.map((row) => `${row.dataset_label}:${row.version}`).join(' / ') : `${trainAssetIds.length} 个资产`)}</span>
          <span>验证集版本：${esc(selectedValidationVersions.length ? selectedValidationVersions.map((row) => `${row.dataset_label}:${row.version}`).join(' / ') : `${validationAssetIds.length} 个资产`)}</span>
        `;
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
        if (targetModelCodeInput && !String(targetModelCodeInput.value || '').trim()) {
          targetModelCodeInput.value = `${model.model_code}-ft`;
        }
        if (targetVersionInput && !String(targetVersionInput.value || '').trim()) {
          const stamp = new Date().toISOString().slice(0, 10).replaceAll('-', '');
          targetVersionInput.value = `v${stamp}.1`;
        }
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
        if (!assistWorkers.length) {
          workerPool.innerHTML = renderEmpty('当前没有训练机可供分配');
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
                    <span>worker_code</span><strong class="mono">${esc(row.worker_code)}</strong>
                    <span>host / IP</span><strong class="mono">${esc(row.host || '-')}</strong>
                    <span>待处理</span><strong>${esc(row.outstanding_jobs ?? 0)}</strong>
                    <span>GPU</span><strong>${esc(`${(row.resources || {}).gpu_count || 0} / ${(row.resources || {}).gpu_mem_mb || 0} MB`)}</strong>
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
                    <span>asset_id</span><strong class="mono">${esc(row.asset_id)}</strong>
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
            const note = window.prompt('回滚说明（可空）', 'training_page_rollback');
            button.disabled = true;
            try {
              const result = await ctx.post(`/assets/dataset-versions/${versionId}/rollback`, { asset_purpose: 'training', note: note || null });
              const newVersionId = result.dataset_version?.id || '';
              if (newVersionId) {
                prefillTrainingDatasetVersionId = newVersionId;
              }
              ctx.toast(`已生成回滚版本：${result.dataset_version?.version || '-'}`);
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
        });
        renderDatasetCompare();
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
          registerWorkerMsg.textContent = `注册成功，bootstrap_token: ${result.bootstrap_token || '-'}`;
          ctx.toast('训练 Worker 注册成功');
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
          const workerCode = String(fd.get('worker_code') || '').trim();
          const workerHost = String(fd.get('worker_host') || '').trim();
          const model = assistModels.find((row) => row.id === baseModelId) || null;
          const workerSelector = {};
          if (workerCode) workerSelector.worker_codes = [workerCode];
          if (workerHost) workerSelector.hosts = [workerHost];
          const payload = {
            training_kind: String(fd.get('training_kind') || 'finetune'),
            asset_ids: splitCsv(fd.get('asset_ids')),
            validation_asset_ids: splitCsv(fd.get('validation_asset_ids')),
            base_model_id: baseModelId,
            owner_tenant_id: model?.owner_tenant_id || null,
            target_model_code: String(fd.get('target_model_code') || '').trim(),
            target_version: String(fd.get('target_version') || '').trim(),
            worker_selector: workerSelector,
            spec: JSON.parse(String(fd.get('spec') || '{}') || '{}'),
          };
          const result = await ctx.post('/training/jobs', payload);
          createMsg.textContent = `创建成功：${result.job_code}${result.assigned_worker_code ? ` · ${result.assigned_worker_code}` : workerHost ? ` · ${workerHost}` : ''}`;
          ctx.toast('训练作业创建成功');
          await loadJobTable();
        } catch (error) {
          createMsg.textContent = error.message || '创建失败';
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
      assetIdsInput?.addEventListener('change', () => {
        refreshSelectionSummary();
        renderDatasetVersionLibrary();
      });
      validationAssetIdsInput?.addEventListener('change', () => {
        refreshSelectionSummary();
        renderDatasetVersionLibrary();
      });
      specInput?.addEventListener('blur', () => {
        if (!String(specInput.value || '').trim()) specInput.value = '{}';
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

      await Promise.all([loadJobTable(), loadWorkers(), loadFormAssistData()]);
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
        <form id="carNumberLabelingFilterForm" class="section-toolbar compact">
          <input id="carNumberLabelingSearch" name="q" placeholder="搜索 sample_id / 源文件 / 建议文本" />
          <select id="carNumberLabelingStatus" name="review_status">
            <option value="">全部状态</option>
            <option value="pending">pending</option>
            <option value="done">done</option>
            <option value="needs_check">needs_check</option>
          </select>
          <select id="carNumberLabelingSplit" name="split_hint">
            <option value="">全部切分</option>
            <option value="train">train</option>
            <option value="validation">validation</option>
          </select>
          <label class="checkbox-row"><input id="carNumberOnlyMissingFinal" type="checkbox" /> 仅看未补 final_text</label>
          <label class="checkbox-row"><input id="carNumberOnlyWithSuggestion" type="checkbox" /> 仅看有建议</label>
          <button class="ghost" type="submit">刷新列表</button>
        </form>
        <div class="row-actions review-toolbar">
          <button id="presetCarNumberTodo" class="ghost" type="button">只看待处理</button>
          <button id="presetCarNumberNeedsCheck" class="ghost" type="button">只看 needs_check</button>
          <button id="presetCarNumberReset" class="ghost" type="button">重置筛选</button>
        </div>
        <div class="row-actions review-toolbar">
          <label class="checkbox-row"><input id="carNumberAllowSuggestionsExport" type="checkbox" /> 导出时允许建议值补空</label>
          <button id="exportCarNumberTextDataset" class="ghost" type="button">导出 OCR 文本训练包</button>
          <button id="exportCarNumberTextAssets" class="primary" type="button">导出训练资产并打开训练页</button>
          <button id="exportCarNumberTrainingJob" class="ghost" type="button">导出训练资产并直接创建训练作业</button>
          <span class="hint">快捷键：<code>Ctrl/Cmd+S</code> 保存，<code>Alt+↑/↓</code> 切换上一条/下一条。前者只预填训练页，不会自动创建作业。</span>
        </div>
        <div id="carNumberLabelingExportMsg" class="hint"></div>
        <div id="carNumberLabelingSummaryWrap">${renderLoading('加载复核摘要...')}</div>
      </section>
      <section class="grid-two">
        <section class="card">
          <div id="carNumberLabelingListMeta" class="hint"></div>
          <div id="carNumberLabelingListWrap">${renderLoading('加载待复核样本...')}</div>
        </section>
        <section class="card">
          <div id="carNumberLabelingDetailWrap">${renderEmpty('从左侧选择一个样本开始复核')}</div>
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
      let selectedSampleId = '';
      let currentItems = [];
      let currentPreviewUrl = '';
      let activeSaveRequest = null;

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

      function renderSummary(summary) {
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
              <h4>复核状态</h4>
              <p class="metric">${esc(reviewCounts.done ?? 0)}</p>
              <span>${esc(`pending ${reviewCounts.pending ?? 0} / needs_check ${reviewCounts.needs_check ?? 0}`)}</span>
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
                <div><span>split</span><strong>${esc(item.split_hint || '-')}</strong></div>
                <div><span>review_status</span><strong>${esc(item.review_status || '-')}</strong></div>
                <div><span>bbox</span><strong>${esc((item.bbox || []).join(', ') || '-')}</strong></div>
                <div><span>engine</span><strong>${esc(item.ocr_suggestion_engine || '-')}</strong></div>
              </div>
              <label>ocr_suggestion(模型建议)</label>
              <input value="${esc(item.ocr_suggestion || '')}" disabled />
              <div class="hint">confidence=${esc(item.ocr_suggestion_confidence || '-')} · quality=${esc(item.ocr_suggestion_quality || '-')}</div>
              <label>final_text(人工确认文本)</label>
              <input id="carNumberFinalText" name="final_text" value="${esc(item.final_text || '')}" placeholder="输入最终车号文本" />
              <label>review_status(复核状态)</label>
              <select name="review_status">
                <option value="pending" ${item.review_status === 'pending' ? 'selected' : ''}>pending</option>
                <option value="done" ${item.review_status === 'done' ? 'selected' : ''}>done</option>
                <option value="needs_check" ${item.review_status === 'needs_check' ? 'selected' : ''}>needs_check</option>
              </select>
              <label>reviewer(复核人)</label>
              <input name="reviewer" value="${esc(item.reviewer || ctx.state.user?.username || '')}" />
              <label>notes(备注)</label>
              <textarea name="notes" rows="3" placeholder="记录特殊情况、模糊字符、需要复查的原因">${esc(item.notes || '')}</textarea>
              <div class="row-actions">
                <button id="acceptCarNumberSuggestion" class="ghost" type="button" ${item.ocr_suggestion ? '' : 'disabled'}>采用建议</button>
                <button id="clearCarNumberFinalText" class="ghost" type="button">清空 final_text</button>
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

      async function selectItem(sampleId) {
        selectedSampleId = sampleId;
        const item = currentItems.find((row) => row.sample_id === sampleId) || null;
        renderDetail(item);
        if (!item) return;
        await loadPreview(sampleId);
        if (selectedSampleId === sampleId) renderDetail(item);
        listWrap.innerHTML = renderList({ items: currentItems });
        bindListClicks();
      }

      function bindListClicks() {
        listWrap.querySelectorAll('[data-labeling-sample]').forEach((btn) => {
          btn.addEventListener('click', async () => {
            await selectItem(btn.getAttribute('data-labeling-sample') || '');
          });
        });
      }

      async function selectRelativeItem(step) {
        if (!currentItems.length) return;
        const currentIndex = currentItems.findIndex((item) => item.sample_id === selectedSampleId);
        const baseIndex = currentIndex >= 0 ? currentIndex : 0;
        const nextIndex = (baseIndex + step + currentItems.length) % currentItems.length;
        const nextItem = currentItems[nextIndex];
        if (nextItem) await selectItem(nextItem.sample_id);
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
            await selectItem(nextSampleId);
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
            if (nextItem) await selectItem(nextItem.sample_id);
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
          exportMsg.textContent = `已注册训练资产 ${payload?.training_asset?.asset_id || '-'} / 验证资产 ${payload?.validation_asset?.asset_id || '-'}。训练页已预填这些资产，但还需要你手动点“创建训练作业”。`;
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
      root.focus();
    },
  };
}

function pagePipelines(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const role = primaryRole(ctx.state.user);
  const canRelease = hasPermission(ctx.state, 'model.release');
  const introText = role.startsWith('platform_')
    ? '把路由模型、专家模型和阈值规则收敛成可发布的执行方案，并在发布前完成验证。'
    : '查看和维护推理编排方案，确保任务执行时使用正确的模型组合和规则。';
  return {
    html: `
      <section class="card">
        <h2>流水线中心</h2>
        <p>${esc(introText)}</p>
      </section>
      <section class="grid-two">
        <form id="pipelineRegisterForm" class="card form-grid">
          <h3>注册流水线</h3>
          <label>pipeline_code(流水线编码)</label><input name="pipeline_code" placeholder="railway-mainline" required />
          <label>name(名称)</label><input name="name" placeholder="主线路由流水线" required />
          <label>version(版本)</label><input name="version" placeholder="v1.0.0" required />
          <label>router_model_id(路由模型ID，可选)</label><input name="router_model_id" placeholder="router-model-id" />
          <label>expert_map(JSON 专家路由表)</label><textarea name="expert_map" rows="3">{}</textarea>
          <label>thresholds(JSON 阈值配置)</label><textarea name="thresholds" rows="2">{}</textarea>
          <label>fusion_rules(JSON 融合规则)</label><textarea name="fusion_rules" rows="2">{}</textarea>
          <label>config(JSON 扩展配置，可空)</label><textarea name="config" rows="4">{}</textarea>
          <button class="primary" type="submit">注册流水线</button>
          <div id="pipelineRegisterMsg" class="hint"></div>
        </form>
        <section class="card">
          <h3>发布前检查</h3>
          <ul class="focus-list">
            <li>先确认路由模型、专家模型和阈值规则已经齐备，再生成正式流水线版本。</li>
            <li>注册后建议先去任务中心创建一次验证任务，确认结果符合预期，再执行发布。</li>
            <li>发布时限定目标租户和设备范围，逐步放量，而不是一次性全量下发。</li>
          </ul>
          <details>
            <summary>示例 expert_map</summary>
            <pre>{
  "car_number_ocr": {"model_id": "your-model-id"}
}</pre>
          </details>
        </section>
      </section>
      <section class="card">
        <h3>流水线列表</h3>
        <div id="pipelinesTableWrap">${renderLoading('加载流水线列表...')}</div>
      </section>
    `,
    async mount(root) {
      const registerForm = root.querySelector('#pipelineRegisterForm');
      const registerMsg = root.querySelector('#pipelineRegisterMsg');
      const tableWrap = root.querySelector('#pipelinesTableWrap');

      async function loadPipelines() {
        tableWrap.innerHTML = renderLoading('加载流水线列表...');
        try {
          const rows = await ctx.get('/pipelines');
          if (!rows.length) {
            tableWrap.innerHTML = renderEmpty('暂无流水线。建议先准备路由模型和专家模型，再注册一条用于验证的流水线');
            return;
          }
          tableWrap.innerHTML = `
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>pipeline_code(流水线编码)</th><th>version(版本)</th><th>status(状态)</th><th>router_model_id(路由模型ID)</th><th>threshold_version(阈值版本)</th><th>操作</th></tr></thead>
                <tbody>
                  ${rows.map((row) => `
                    <tr>
                      <td>${esc(row.pipeline_code)}</td>
                      <td>${esc(row.version)}</td>
                      <td>${esc(enumText('pipeline_status', row.status))}</td>
                      <td class="mono">${esc(row.router_model_id || '-')}</td>
                      <td>${esc(row.threshold_version || '-')}</td>
                      <td>
                        ${canRelease ? `<button class="ghost" data-release-pipeline="${esc(row.id)}">发布</button>` : '-'}
                      </td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          `;
          if (canRelease) {
            tableWrap.querySelectorAll('[data-release-pipeline]').forEach((btn) => {
              btn.addEventListener('click', async () => {
                const pipelineId = btn.getAttribute('data-release-pipeline');
                const targetDevices = splitCsv(window.prompt('目标设备（逗号分隔，可空）', 'edge-01'));
                const targetBuyers = splitCsv(window.prompt('目标买家（tenant_code，逗号分隔，可空）', 'buyer-demo-001'));
                try {
                  await ctx.post('/pipelines/release', {
                    pipeline_id: pipelineId,
                    target_devices: targetDevices,
                    target_buyers: targetBuyers,
                    traffic_ratio: 100,
                    release_notes: 'console release',
                  });
                  ctx.toast('流水线已发布');
                  await loadPipelines();
                } catch (error) {
                  ctx.toast(error.message, 'error');
                }
              });
            });
          }
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
          await loadPipelines();
        } catch (error) {
          registerMsg.textContent = error.message || '注册失败';
        } finally {
          submitBtn.disabled = false;
        }
      });

      await loadPipelines();
    },
  };
}

function pageTasks(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const role = primaryRole(ctx.state.user);
  const introText = role.startsWith('buyer_')
    ? '上传一张图或视频后直接输入要识别的对象，或选择已准备好的资产和授权模型 / 流水线创建任务。'
    : role.startsWith('platform_')
      ? '统一创建和跟踪推理任务，既支持一键快速识别，也支持核对模型、流水线、设备与结果的交付状态。'
      : '查看任务执行状态与结果回查入口。';
  return {
    html: `
      <section class="card">
        <h2>任务中心</h2>
        <p>${esc(introText)}</p>
      </section>
      <section class="grid-two">
        <form id="quickDetectForm" class="card form-grid">
          <h3>快速识别</h3>
          <label>file(上传图片 / 视频，可选)</label>
          <input id="quickDetectFile" type="file" accept=".jpg,.jpeg,.png,.bmp,.mp4,.avi,.mov" multiple />
          <div class="hint">支持单图/短视频，也支持一次上传多张图片或多个短视频；如果资产已经在平台内，也可以直接填写 1-n 个 asset_id。</div>
          <label>asset_id(已有资产ID，可选，支持 1-n)</label>
          <input name="asset_id" id="quickDetectAssetInput" list="taskAssetsDatalist" placeholder="asset-id-1, asset-id-2" />
          <label>object_prompt / intent_text(要识别什么)</label>
          <input name="object_prompt" id="quickDetectPrompt" placeholder="例如 车号 / car / person / train / bus" required />
          <div class="chip-row" id="quickDetectPromptChips">
            ${QUICK_DETECT_PROMPTS.map((item) => `<button type="button" class="ghost chip-btn" data-quick-prompt="${esc(item)}">${esc(item)}</button>`).join('')}
          </div>
          <div id="quickDetectIntentOptions" class="quick-intent-grid"></div>
          <div class="hint">系统会先按你的描述归一化意图并选模。输入“车号 / 车厢号 / 车皮号 / 编号”都会优先走车号 OCR，并直接输出文本。</div>
          <label>device_code(设备编码)</label>
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
      <section class="grid-two">
        <form id="taskCreateForm" class="card form-grid">
          <h3>创建任务</h3>
          <label>asset_id(资产ID)</label>
          <input name="asset_id" id="taskAssetInput" list="taskAssetsDatalist" placeholder="asset-id" required />
          <label>pipeline_id(流水线ID，优先)</label>
          <input name="pipeline_id" id="taskPipelineInput" list="taskPipelinesDatalist" placeholder="pipeline-id，可空" />
          <label>model_id(模型ID，无 pipeline 时使用)</label>
          <input name="model_id" id="taskModelInput" list="taskModelsDatalist" placeholder="model-id，可空" />
          <label>task_type(任务类型，可选)</label>
          <select name="task_type">
            <option value="">自动选择</option>
            <option value="pipeline_orchestrated">${enumText('task_type', 'pipeline_orchestrated')}</option>
            <option value="object_detect">${enumText('task_type', 'object_detect')}</option>
            <option value="car_number_ocr">${enumText('task_type', 'car_number_ocr')}</option>
            <option value="bolt_missing_detect">${enumText('task_type', 'bolt_missing_detect')}</option>
          </select>
          <label>device_code(设备编码)</label>
          <input name="device_code" value="edge-01" />
          <label>intent_text(意图描述)</label>
          <input name="intent_text" placeholder="例如：优先识别车号" />
          <label class="checkbox-row"><input type="checkbox" name="use_master_scheduler" /> 启用主调度器自动选模</label>
          <div class="hint">如果你已经明确知道要用哪一版模型，建议直接从下方“可选模型”里点选，避免手输 model_id。</div>
          <datalist id="taskAssetsDatalist"></datalist>
          <datalist id="taskPipelinesDatalist"></datalist>
          <datalist id="taskModelsDatalist"></datalist>
          <button class="primary" type="submit">创建任务</button>
          <div id="taskCreateMsg" class="hint"></div>
        </form>
        <section class="card">
          <h3>创建结果</h3>
          <div id="taskCreateResult">${renderEmpty('创建成功后会显示 task_id，并提供结果页直达入口')}</div>
        </section>
      </section>
      <section class="card">
        <h3>可选模型</h3>
        <div class="section-toolbar compact">
          <input id="taskModelSearch" placeholder="搜索 model_code / version / task_type / 来源" />
          <div id="taskModelMeta" class="hint"></div>
        </div>
        <div id="taskModelLibrary">${renderLoading('加载可选模型...')}</div>
      </section>
      <section class="card">
        <h3>任务列表</h3>
        <div id="tasksTableWrap">${renderLoading('加载任务列表...')}</div>
      </section>
    `,
    async mount(root) {
      const quickDetectForm = root.querySelector('#quickDetectForm');
      const quickDetectFile = root.querySelector('#quickDetectFile');
      const quickDetectAssetInput = root.querySelector('#quickDetectAssetInput');
      const quickDetectPrompt = root.querySelector('#quickDetectPrompt');
      const quickDetectIntentOptions = root.querySelector('#quickDetectIntentOptions');
      const quickDetectDeviceCode = root.querySelector('#quickDetectDeviceCode');
      const quickDetectPreflightBtn = root.querySelector('#quickDetectPreflightBtn');
      const quickDetectMsg = root.querySelector('#quickDetectMsg');
      const quickDetectPreview = root.querySelector('#quickDetectPreview');
      const quickDetectResult = root.querySelector('#quickDetectResult');
      const createForm = root.querySelector('#taskCreateForm');
      const createMsg = root.querySelector('#taskCreateMsg');
      const createResult = root.querySelector('#taskCreateResult');
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
      let assistAssets = [];
      let assistModels = [];
      let taskModelQuery = '';

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
                <span>共 ${esc(String(assetIds.length))} 个 asset_id</span>
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
          });
        });
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
                    <div><span>asset_id</span><strong class="mono">${esc(item.assetId || '-')}</strong></div>
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
        const taskTypeInput = createForm.querySelector('input[name="task_type"]');
        const deviceCodeInput = createForm.querySelector('input[name="device_code"]');
        if (modelInput && prefillTaskModelId) modelInput.value = prefillTaskModelId;
        if (assetInput && prefillTaskAssetId) assetInput.value = prefillTaskAssetId;
        if (taskTypeInput && prefillTaskType) taskTypeInput.value = prefillTaskType;
        if (deviceCodeInput && prefillTaskDeviceCode) deviceCodeInput.value = prefillTaskDeviceCode;
        if (createMsg) {
          createMsg.textContent = prefillTaskHint
            || `已预填验证任务：model ${prefillTaskModelId || '-'} · task_type ${prefillTaskType || '-'} · device ${prefillTaskDeviceCode || '-'}`;
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
        } catch {
          // Ignore suggestion loading failure.
        }
      }

      function taskCreateInputs() {
        return {
          modelInput: createForm?.querySelector('input[name="model_id"]'),
          taskTypeInput: createForm?.querySelector('select[name="task_type"]'),
          schedulerInput: createForm?.querySelector('input[name="use_master_scheduler"]'),
          intentInput: createForm?.querySelector('input[name="intent_text"]'),
        };
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
        renderTaskModelLibrary();
      }

      function renderTaskModelLibrary() {
        if (!taskModelLibrary) return;
        const { modelInput, taskTypeInput, schedulerInput } = taskCreateInputs();
        const currentModelId = String(modelInput?.value || '').trim();
        const requestedTaskType = String(taskTypeInput?.value || '').trim();
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
        taskModelLibrary.innerHTML = `
          <div class="selection-grid">
            ${filtered.map((row) => `
              <article class="selection-card ${currentModelId === row.id ? 'selected' : ''}">
                <div class="selection-card-head">
                  <strong>${esc(row.model_code)}:${esc(row.version)}</strong>
                  <span class="badge">${esc(enumText('model_status', row.status || '-'))}</span>
                </div>
                <div class="selection-card-meta">
                  <span>task_type</span><strong>${esc(row.task_type || row.plugin_name || '-')}</strong>
                  <span>来源</span><strong>${esc(enumText('model_source_type', (row.platform_meta || {}).model_source_type || '-'))}</strong>
                  <span>plugin</span><strong>${esc(row.plugin_name || '-')}</strong>
                  <span>model_id</span><strong class="mono">${esc(truncateMiddle(row.id, 8, 6))}</strong>
                </div>
                <div class="row-actions">
                  <button class="primary" type="button" data-pick-task-model="${esc(row.id)}">选这版模型</button>
                </div>
              </article>
            `).join('')}
          </div>
        `;
        taskModelLibrary.querySelectorAll('[data-pick-task-model]').forEach((button) => {
          button.addEventListener('click', () => fillTaskModelSelection(button.getAttribute('data-pick-task-model') || ''));
        });
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
            throw new Error(task?.error_message || `任务执行失败：${task?.status}`);
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
            throw new Error(task?.error_message || `任务执行失败：${status}`);
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
              <div><span>task_ids</span><strong>${esc(String(outcomes.length))} 条</strong></div>
              <div><span>object_count</span><strong>${esc(String(totalObjects))}</strong></div>
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
                        <div><span>dataset_asset_id</span><strong class="mono">${esc(quickDatasetExport.asset.id)}</strong></div>
                        <div><span>dataset_version</span><strong>${esc(`${quickDatasetExport.dataset_version?.dataset_label || '-'}:${quickDatasetExport.dataset_version?.version || '-'}`)}</strong></div>
                        <div><span>archive_resource_count</span><strong>${esc(String(quickDatasetExport.asset.meta?.archive_resource_count || 0))}</strong></div>
                        <div><span>label_vocab</span><strong>${esc((quickDatasetExport.asset.meta?.label_vocab || []).join(', ') || '-')}</strong></div>
                        <div><span>asset_purpose</span><strong>${esc(quickDatasetExport.asset.meta?.asset_purpose || '-')}</strong></div>
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
                      <strong>${esc(item.uploadedAsset?.file_name || item.focus?.result_json?.source_file_name || item.task.id)}</strong>
                      <div class="quick-review-statuses">
                        <span class="badge">${esc(enumText('task_status', item.task.status))}</span>
                        <span class="badge">${esc(item.reviewDirty ? '修订未保存' : item.reviewStatus === 'revised' ? '已确认' : '自动结果')}</span>
                      </div>
                    </div>
                    <div class="keyvals">
                      <div><span>asset_id</span><strong class="mono">${esc(item.uploadedAsset?.id || item.task.asset_id || '-')}</strong></div>
                      <div><span>task_id</span><strong class="mono">${esc(item.task.id)}</strong></div>
                      <div><span>task_type</span><strong>${esc(enumText('task_type', item.taskType || item.task.task_type || '-'))}</strong></div>
                      <div><span>selected_model</span><strong>${esc(`${item.recommendation?.selected_model?.model_code || '-'}:${item.recommendation?.selected_model?.version || '-'}`)}</strong></div>
                      <div><span>object_count</span><strong>${esc(String(item.predictions.length))}</strong></div>
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
                    <div class="quick-review-stage">
                      ${
                        item.previewUrl
                          ? `
                              <div class="quick-review-canvas ${item.previewSource === 'screenshot' ? 'screenshot' : 'asset'} ${item.drawMode ? 'draw-active' : ''}" data-review-canvas="${outcomeIndex}">
                                <img data-review-preview-index="${outcomeIndex}" class="quick-review-stage-image" src="${item.previewUrl}" alt="快速识别预览" />
                                <div class="quick-review-overlay">${quickReviewBoxes(item)}</div>
                              </div>
                              <div class="hint">${esc(item.drawMode ? '拖拽图片区域即可新增手工框，松开鼠标后会写入修订列表。' : (item.previewSource === 'asset' ? '当前预览使用原始图片。可直接拖动框体移动，拖右下角缩放。' : '当前预览使用任务标注图。若原始资产不可预览，修订框会叠加显示在标注图上，并支持拖动/缩放。'))}</div>
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
                                    <div class="quick-review-fields">
                                      <input data-review-index="${outcomeIndex}" data-review-pred="${esc(pred._id)}" data-review-field="label" value="${esc(pred.label)}" placeholder="label" />
                                      <input data-review-index="${outcomeIndex}" data-review-pred="${esc(pred._id)}" data-review-field="text" value="${esc(pred.text || '')}" placeholder="text / OCR 输出" />
                                      <input data-review-index="${outcomeIndex}" data-review-pred="${esc(pred._id)}" data-review-field="score" type="number" min="0" max="1" step="0.01" value="${esc(Number(pred.score ?? 1).toFixed(2))}" />
                                      <input data-review-index="${outcomeIndex}" data-review-pred="${esc(pred._id)}" data-review-field="x1" type="number" step="1" value="${esc(String(pred.bbox?.[0] ?? 0))}" />
                                      <input data-review-index="${outcomeIndex}" data-review-pred="${esc(pred._id)}" data-review-field="y1" type="number" step="1" value="${esc(String(pred.bbox?.[1] ?? 0))}" />
                                      <input data-review-index="${outcomeIndex}" data-review-pred="${esc(pred._id)}" data-review-field="x2" type="number" step="1" value="${esc(String(pred.bbox?.[2] ?? 0))}" />
                                      <input data-review-index="${outcomeIndex}" data-review-pred="${esc(pred._id)}" data-review-field="y2" type="number" step="1" value="${esc(String(pred.bbox?.[3] ?? 0))}" />
                                    </div>
                                    <div class="row-actions">
                                      <span class="badge">${esc(pred.source === 'manual' ? 'manual' : 'auto')}</span>
                                      <button class="ghost" type="button" data-review-focus="${outcomeIndex}" data-review-pred="${esc(pred._id)}">选中</button>
                                      <button class="ghost" type="button" data-review-remove="${outcomeIndex}" data-review-pred="${esc(pred._id)}">删掉误检</button>
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
            if (!datasetLabel) throw new Error('请输入 dataset_label');
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

      async function runQuickDetectItem({ file, existingAssetId, prompt, deviceCode, index, total, uploadedAsset = null, forcedTaskType = null }) {
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

        quickDetectResult.innerHTML = renderLoading(`正在自动选模 ${index + 1}/${total} ...`);
        const recommendation = await ctx.post('/tasks/recommend-model', {
          asset_id: assetId,
          task_type: requestedTaskType,
          device_code: deviceCode,
          intent_text: prompt,
          limit: 3,
        });
        if (!recommendation?.selected_model?.model_id) {
          throw new Error('当前没有可用于快速识别的已发布模型');
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
          if (!rows.length) {
            tableWrap.innerHTML = renderEmpty('暂无任务，可先去资产中心上传资产，再回到这里创建推理任务');
            return;
          }
          tableWrap.innerHTML = `
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>task_id(任务ID)</th><th>task_type(任务类型)</th><th>status(状态)</th><th>pipeline_id(流水线ID)</th><th>device(设备)</th><th>创建时间</th><th>操作</th></tr></thead>
                <tbody>
                  ${rows.map((row) => `
                    <tr>
                      <td class="mono">${esc(row.id)}</td>
                      <td>${esc(enumText('task_type', row.task_type))}</td>
                      <td>${esc(enumText('task_status', row.status))}</td>
                      <td class="mono">${esc(row.pipeline_id || '-')}</td>
                      <td>${esc(row.device_code || '-')}</td>
                      <td>${formatDateTime(row.created_at)}</td>
                      <td>
                        <button class="ghost" data-task-detail="${esc(row.id)}">详情</button>
                        <button class="ghost" data-task-results="${esc(row.id)}">结果</button>
                      </td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          `;
          tableWrap.querySelectorAll('[data-task-detail]').forEach((btn) => {
            btn.addEventListener('click', () => ctx.navigate(`tasks/${btn.getAttribute('data-task-detail')}`));
          });
          tableWrap.querySelectorAll('[data-task-results]').forEach((btn) => {
            btn.addEventListener('click', () => ctx.navigate(`results/task/${btn.getAttribute('data-task-results')}`));
          });
        } catch (error) {
          tableWrap.innerHTML = renderError(error.message);
        }
      }

      quickDetectFile?.addEventListener('change', renderQuickPreview);
      quickDetectFile?.addEventListener('change', () => {
        quickPreflightOutcomes = [];
        revokeQuickUrls();
      });
      quickDetectAssetInput?.addEventListener('input', () => {
        quickPreflightOutcomes = [];
        revokeQuickUrls();
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
      });
      root.querySelectorAll('[data-quick-prompt]').forEach((btn) => {
        btn.addEventListener('click', () => {
          if (quickDetectPrompt) quickDetectPrompt.value = btn.getAttribute('data-quick-prompt') || '';
          renderQuickIntentOptions();
        });
      });

      async function performQuickPreflight() {
        const { prompt, items } = currentQuickWorkItems();
        if (!items.length) {
          throw new Error('请上传图片/视频，或填写已有 asset_id');
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
          if (!items.length) throw new Error('请上传图片/视频，或填写已有 asset_id');

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
            <div class="keyvals">
              <div><span>task_id</span><strong class="mono">${esc(created.id)}</strong></div>
              <div><span>status</span><strong>${esc(enumText('task_status', created.status))}</strong></div>
              <div><span>task_type</span><strong>${esc(enumText('task_type', created.task_type))}</strong></div>
            </div>
            <div class="row-actions">
              <button class="primary" id="openTaskDetail">查看任务详情</button>
              <button class="ghost" id="openTaskResults">查看任务结果</button>
              <button class="ghost" id="waitTaskResults">等待执行并打开结果页</button>
            </div>
          `;
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
      createForm?.querySelector('select[name="task_type"]')?.addEventListener('change', renderTaskModelLibrary);
      createForm?.querySelector('input[name="use_master_scheduler"]')?.addEventListener('change', renderTaskModelLibrary);

      await Promise.all([loadTasks(), loadAssistData()]);
    },
  };
}

function pageTaskDetail(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const taskId = route.params?.task_id;
  return {
    html: `
      <section class="card">
        <h2>任务详情</h2>
        <p class="mono">${esc(taskId)}</p>
      </section>
      <section class="card" id="taskDetailWrap">${renderLoading('加载任务详情...')}</section>
    `,
    async mount(root) {
      const wrap = root.querySelector('#taskDetailWrap');
      try {
        const data = await ctx.get(`/tasks/${taskId}`);
        wrap.innerHTML = `
          <div class="keyvals">
            <div><span>task_id</span><strong class="mono">${esc(data.id)}</strong></div>
            <div><span>status</span><strong>${esc(enumText('task_status', data.status))}</strong></div>
            <div><span>task_type</span><strong>${esc(enumText('task_type', data.task_type))}</strong></div>
            <div><span>model_id</span><strong class="mono">${esc(data.model_id || '-')}</strong></div>
            <div><span>pipeline_id</span><strong class="mono">${esc(data.pipeline_id || '-')}</strong></div>
            <div><span>created_at</span><strong>${formatDateTime(data.created_at)}</strong></div>
            <div><span>started_at</span><strong>${formatDateTime(data.started_at)}</strong></div>
            <div><span>finished_at</span><strong>${formatDateTime(data.finished_at)}</strong></div>
            <div><span>error_message</span><strong>${esc(data.error_message || '-')}</strong></div>
          </div>
          <div class="row-actions">
            <button class="primary" id="goTaskResult">查看结果</button>
          </div>
          <details><summary>Advanced</summary><pre>${esc(safeJson(data))}</pre></details>
        `;
        root.querySelector('#goTaskResult')?.addEventListener('click', () => ctx.navigate(`results/task/${taskId}`));
      } catch (error) {
        wrap.innerHTML = renderError(error.message);
      }
    },
  };
}

function buildResultListHtml(rows, modelInsights = {}) {
  if (!rows.length) return renderEmpty('暂无结果，请确认任务已执行完成，或返回任务中心重新创建任务');
  const summaries = rows.map((row) => summarizeResultRow(row));
  const totalObjects = summaries.reduce((sum, item) => sum + item.objectCount, 0);
  const durations = summaries.map((item) => item.durationMs).filter((value) => Number.isFinite(value));
  const avgDuration = durations.length ? Math.round(durations.reduce((sum, value) => sum + value, 0) / durations.length) : null;
  const allTexts = [...new Set(summaries.flatMap((item) => item.recognizedTexts))];
  const uniqueModelIds = [...new Set(rows.map((row) => String(row.model_id || '').trim()).filter(Boolean))];

  return `
    <div class="result-overview-grid">
      <article class="metric-card">
        <h4>结果条数</h4>
        <p class="metric">${esc(rows.length)}</p>
        <span>当前 task_id 下已回查到的结果记录</span>
      </article>
      <article class="metric-card">
        <h4>识别对象</h4>
        <p class="metric">${esc(totalObjects)}</p>
        <span>累计命中的框 / 文本结果数量</span>
      </article>
      <article class="metric-card">
        <h4>平均耗时</h4>
        <p class="metric">${esc(avgDuration ?? '-')}</p>
        <span>${esc(avgDuration != null ? 'ms' : '当前结果未回写 duration_ms')}</span>
      </article>
      <article class="metric-card">
        <h4>识别文本</h4>
        <p class="metric">${esc(allTexts.length)}</p>
        <span>${esc(allTexts.slice(0, 3).join(' / ') || '暂无 OCR 文本')}</span>
      </article>
    </div>
    ${
      allTexts.length
        ? `<section class="result-text-ribbon">${allTexts.slice(0, 12).map((text) => `<span class="badge">${esc(text)}</span>`).join('')}</section>`
        : ''
    }
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
        : ''
    }
    <div class="result-list">
      ${summaries.map((item) => {
        const row = item.row;
        const labels = Object.entries(item.labelCounts)
          .sort((left, right) => right[1] - left[1])
          .slice(0, 6);
        const readiness = modelInsights[row.model_id] || null;
        const validationMetrics = readiness?.validation_report?.metrics || {};
        return `
          <article class="result-card">
            <div class="result-head">
              <div>
                <strong>${esc(row.id)}</strong>
                <p class="muted">${esc(`${item.taskType} · ${item.stage} · ${formatDateTime(row.created_at)}`)}</p>
              </div>
              <div class="quick-review-statuses">
                <span class="badge">${esc(row.alert_level || 'INFO')}</span>
                ${row.model_id ? `<span class="badge mono">${esc(truncateMiddle(row.model_id, 8, 6))}</span>` : ''}
              </div>
            </div>
            <div class="keyvals compact">
              <div><span>duration_ms</span><strong>${esc(formatMetricValue(item.durationMs))}</strong></div>
              <div><span>object_count</span><strong>${esc(formatMetricValue(item.objectCount))}</strong></div>
              <div><span>avg_score</span><strong>${esc(formatMetricValue(item.avgScore, { percent: true }))}</strong></div>
              <div><span>model_val_accuracy</span><strong>${esc(formatMetricValue(validationMetrics.val_accuracy, { percent: true }))}</strong></div>
            </div>
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
                  <strong>命中标签</strong>
                  <span>${esc(labels.length ? `${labels.length} 类` : '暂无')}</span>
                </div>
                ${
                  labels.length
                    ? `<div class="result-label-cloud">${labels.map(([label, count]) => `<span class="badge">${esc(`${label} · ${count}`)}</span>`).join('')}</div>`
                    : '<div class="training-history-empty">当前结果没有结构化标签命中。</div>'
                }
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
                <summary>更多详情</summary>
                <div class="details-panel">
                  <details open>
                    <summary>结果 JSON</summary>
                    <pre>${esc(safeJson(row.result_json))}</pre>
                  </details>
                  ${readiness ? `<details><summary>模型验证摘要</summary><pre>${esc(safeJson(readiness.validation_report || {}))}</pre></details>` : ''}
                </div>
              </details>
            </div>
          </article>
        `;
      }).join('')}
    </div>
  `;
}

function pageResults(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const role = primaryRole(ctx.state.user);
  const defaultTaskId = route.params?.task_id || localStorage.getItem(STORAGE_KEYS.lastTaskId) || '';
  const introText = role.startsWith('buyer_')
    ? '按 task_id 回查结构化结果、截图摘要和导出信息，支撑客户验收与复核。'
    : role.startsWith('platform_')
      ? '统一查看执行结果、导出摘要和截图证据，验证模型交付与任务产出。'
      : '查看任务输出、截图摘要与导出信息。';
  return {
    html: `
      <section class="card">
        <h2>结果中心</h2>
        <p>${esc(introText)}</p>
      </section>
      <section class="card">
        <form id="resultQueryForm" class="inline-form">
          <input id="resultTaskId" name="task_id" placeholder="输入 task_id" value="${esc(defaultTaskId)}" required />
          <button class="primary" type="submit">查询结果</button>
          <button class="ghost" id="resultExportBtn" type="button">导出摘要</button>
        </form>
        <div id="resultMeta" class="hint">${esc(defaultTaskId ? '' : '训练后验证时，可从训练页点击“去任务中心验证候选模型”，再在任务创建成功后点击“等待执行并打开结果页”。')}</div>
      </section>
      <section class="card">
        <div id="resultListWrap">${defaultTaskId ? renderLoading('加载结果...') : renderEmpty('请输入 task_id 查询，或先在任务中心创建并执行任务')}</div>
      </section>
    `,
    async mount(root) {
      const queryForm = root.querySelector('#resultQueryForm');
      const taskInput = root.querySelector('#resultTaskId');
      const resultMeta = root.querySelector('#resultMeta');
      const listWrap = root.querySelector('#resultListWrap');
      const exportBtn = root.querySelector('#resultExportBtn');
      let resultBlobUrls = [];

      function revokeResultBlobUrls() {
        resultBlobUrls.forEach((url) => URL.revokeObjectURL(url));
        resultBlobUrls = [];
      }

      async function openScreenshot(resultId) {
        try {
          const resp = await fetch(`/api/results/${resultId}/screenshot`, {
            headers: { Authorization: `Bearer ${ctx.token}` },
          });
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
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
          listWrap.innerHTML = renderEmpty('请输入 task_id，或先在任务中心创建并执行任务');
          resultMeta.textContent = '';
          return;
        }
        listWrap.innerHTML = renderLoading('加载结果...');
        resultMeta.textContent = '';
        try {
          const rows = await ctx.get(`/results${toQuery({ task_id: clean })}`);
          const enrichedRows = await enrichRowsWithScreenshots(rows || []);
          const modelInsights = await loadModelInsights(enrichedRows || []);
          listWrap.innerHTML = buildResultListHtml(enrichedRows || [], modelInsights);
          const modelCount = [...new Set((enrichedRows || []).map((row) => String(row.model_id || '').trim()).filter(Boolean))].length;
          resultMeta.textContent = `task_id=${clean} · 结果条数=${enrichedRows.length} · 关联模型=${modelCount}`;
          localStorage.setItem(STORAGE_KEYS.lastTaskId, clean);
          await bindScreenshotButtons();
        } catch (error) {
          listWrap.innerHTML = renderError(error.message);
        }
      }

      queryForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        await loadByTaskId(taskInput?.value || '');
      });

      exportBtn?.addEventListener('click', async () => {
        const taskId = String(taskInput?.value || '').trim();
        if (!taskId) {
          ctx.toast('请先输入 task_id', 'error');
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

      if (defaultTaskId) await loadByTaskId(defaultTaskId);
    },
  };
}

function pageAudit(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  return {
    html: `
      <section class="card">
        <h2>审计中心</h2>
        <p>统一核对模型审批发布、训练拉取、任务创建、结果导出和设备执行证据。</p>
      </section>
      <section class="card">
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
      const filterForm = root.querySelector('#auditFilterForm');
      const tableWrap = root.querySelector('#auditTableWrap');

      async function loadAudit() {
        tableWrap.innerHTML = renderLoading('加载审计日志...');
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
          if (!rows.length) {
            tableWrap.innerHTML = renderEmpty('暂无审计日志。完成模型审批、任务创建、结果导出或设备拉取后会在这里留痕');
            return;
          }
          tableWrap.innerHTML = `
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>时间</th><th>action(动作)</th><th>actor(操作者)</th><th>resource(资源)</th><th>detail(详情)</th></tr></thead>
                <tbody>
                  ${rows.map((row) => `
                    <tr>
                      <td>${formatDateTime(row.created_at)}</td>
                      <td>${esc(row.action)}</td>
                      <td>${esc(row.actor_username || row.actor_role || '-')}</td>
                      <td>${esc(row.resource_type)} / <span class="mono">${esc(row.resource_id || '-')}</span></td>
                      <td><details><summary>查看</summary><pre>${esc(safeJson(row.detail))}</pre></details></td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
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

      await loadAudit();
    },
  };
}

function pageDevices(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const role = primaryRole(ctx.state.user);
  const introText = role.startsWith('buyer_')
    ? '查看已授权边缘设备的在线状态、最近心跳和 Agent 版本，确认设备可执行范围。'
    : '查看设备授权、在线状态、最近心跳和 Agent 版本，核对边缘运行面。';
  return {
    html: `
      <section class="card">
        <h2>设备中心</h2>
        <p>${esc(introText)}</p>
      </section>
      <section class="card">
        <div id="devicesTableWrap">${renderLoading('加载设备列表...')}</div>
      </section>
    `,
    async mount(root) {
      const wrap = root.querySelector('#devicesTableWrap');
      try {
        const rows = await ctx.get('/devices');
        if (!rows.length) {
          wrap.innerHTML = renderEmpty('暂无设备。请先接入边缘 Agent，或确认当前角色拥有设备查看权限');
          return;
        }
        wrap.innerHTML = `
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>device_id(设备ID)</th><th>buyer(客户)</th><th>status(状态)</th><th>last_heartbeat(最近心跳)</th><th>agent_version(Agent 版本)</th></tr></thead>
              <tbody>
                ${rows.map((row) => `
                  <tr>
                    <td class="mono">${esc(row.device_id)}</td>
                    <td>${esc(row.buyer || '-')}</td>
                    <td>${esc(enumText('device_status', row.status))}</td>
                    <td>${formatDateTime(row.last_heartbeat)}</td>
                    <td>${esc(row.agent_version || '-')}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `;
      } catch (error) {
        if (String(error.message || '').includes('404')) {
          wrap.innerHTML = renderEmpty('设备接口尚未接通，请先确认中心端 /devices 接口状态');
          return;
        }
        wrap.innerHTML = renderError(error.message);
      }
    },
  };
}

function pageSettings(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  return {
    html: `
      <section class="card">
        <h2>设置</h2>
        <p>核对当前登录身份、租户边界、权限能力和默认角色路径。</p>
      </section>
      <section class="card" id="settingsWrap">${renderLoading('加载用户信息...')}</section>
    `,
    async mount(root) {
      const wrap = root.querySelector('#settingsWrap');
      try {
        const me = await ctx.get('/users/me');
        const preset = rolePreset(me);
        wrap.innerHTML = `
          <div class="keyvals">
            <div><span>username</span><strong>${esc(me.username)}</strong></div>
            <div><span>roles</span><strong>${esc((me.roles || []).map((item) => roleLabel(item)).join(' / '))}</strong></div>
            <div><span>tenant_code</span><strong>${esc(me.tenant_code || '-')}</strong></div>
            <div><span>tenant_type</span><strong>${esc(me.tenant_type || '-')}</strong></div>
          </div>
          <div class="hint">默认路径：${esc(preset.pathHint)}</div>
          <details open>
            <summary>permissions</summary>
            <pre>${esc(safeJson(me.permissions || []))}</pre>
          </details>
          <details>
            <summary>capabilities</summary>
            <pre>${esc(safeJson(me.capabilities || {}))}</pre>
          </details>
        `;
      } catch (error) {
        wrap.innerHTML = renderError(error.message);
      }
    },
  };
}

const factories = {
  login: pageLogin,
  dashboard: pageDashboard,
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
