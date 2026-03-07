import { api, apiForm, apiPost, formatDateTime, toQuery } from '../core/api.js';

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
    score: Number(prediction?.score ?? 1),
    bbox,
    attributes: cloneJson(prediction?.attributes || {}) || {},
    source: String(prediction?.source || prediction?.attributes?.review_source || 'auto'),
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

const QUICK_DETECT_PROMPTS = ['car', 'person', 'train', 'bus'];

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
    eyebrow: 'VisionHub 控制面',
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
        <div class="login-brand"><span class="brand-mark"></span><span>VISIONHUB</span></div>
        <section class="login-card">
          <h2>进入 VisionHub</h2>
          <p class="login-subtitle">面向铁路与政企内网的模型主权、数据主权、受控协作与边缘安全交付控制台</p>
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
      const recentAssets = root.querySelector('#recentAssets');
      const recentModels = root.querySelector('#recentModels');
      const recentTasks = root.querySelector('#recentTasks');
      try {
        const data = await ctx.get('/dashboard/summary');
        const lanes = data?.lanes || {};
        laneGrid.innerHTML = `
          <article class="lane-card">
            <h4>主线1 资产输入</h4>
            <p class="metric">${lanes.line1_assets?.total_assets ?? 0}</p>
            <p class="muted">可用于训练 / 验证 / 推理的资产总量</p>
          </article>
          <article class="lane-card">
            <h4>主线2 模型交付与微调</h4>
            <p class="metric">${lanes.line2_models_training?.models_submitted ?? 0} / ${lanes.line2_models_training?.models_released ?? 0}</p>
            <p class="muted">待审模型 / 已发布模型</p>
          </article>
          <article class="lane-card">
            <h4>主线3 验证与执行</h4>
            <p class="metric">${lanes.line3_execution?.tasks_succeeded ?? 0}</p>
            <p class="muted">成功任务数（累计）</p>
          </article>
          <article class="lane-card">
            <h4>主线4 授权设备运行</h4>
            <p class="metric">${lanes.line4_governance_delivery?.devices_online ?? 0} / ${lanes.line4_governance_delivery?.devices_total ?? 0}</p>
            <p class="muted">在线设备 / 设备总数</p>
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

      function prefillTrainingAssets(assetIds) {
        const merged = [...new Set([...splitCsv(localStorage.getItem('rv_prefill_training_asset_ids') || ''), ...assetIds])];
        localStorage.setItem('rv_prefill_training_asset_ids', merged.join(', '));
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
          const rows = await ctx.get(`/assets${query}`);
          if (!rows.length) {
            tableWrap.innerHTML = renderEmpty('暂无资产。建议先上传一条单图 / 单视频资产用于推理，或上传 ZIP 数据集包用于训练准备');
            return;
          }
          tableWrap.innerHTML = `
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>asset_id(资产ID)</th><th>file_name(文件名)</th><th>type(类型)</th><th>resource_count(资源数)</th><th>purpose(用途)</th><th>sensitivity(敏感等级)</th><th>创建时间</th><th>操作</th></tr></thead>
                <tbody>
                  ${rows.map((row) => `
                    <tr>
                      <td class="mono">${esc(row.id)}</td>
                      <td>${esc(row.file_name)}</td>
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
                  `).join('')}
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
              localStorage.setItem('rv_prefill_asset_id', btn.getAttribute('data-use-asset') || '');
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
              localStorage.setItem('rv_quick_detect_asset_id', btn.getAttribute('data-quick-detect-asset') || '');
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
          uploadResult.innerHTML = `
            <div class="keyvals">
              <div><span>asset_id</span><strong class="mono">${esc(data.id)}</strong></div>
              <div><span>file_name</span><strong>${esc(data.file_name)}</strong></div>
              <div><span>asset_type</span><strong>${esc(enumText('asset_type', data.asset_type))}</strong></div>
              <div><span>sensitivity</span><strong>${esc(enumText('sensitivity_level', data.sensitivity_level))}</strong></div>
              ${
                archiveResourceCount(data.meta || {})
                  ? `<div><span>resource_count</span><strong>${archiveResourceCount(data.meta || {})}</strong></div>`
                  : ''
              }
            </div>
            <div class="row-actions">
              <button class="ghost" id="copyAssetIdBtn">复制资产ID</button>
              ${isTaskAsset(data) ? `<button class="primary" id="gotoQuickDetectFromAsset">快速识别</button>` : ''}
              ${isTaskAsset(data) ? `<button class="primary" id="gotoTaskFromAsset">用该资产创建任务</button>` : ''}
              <button class="ghost" id="gotoTrainingFromAsset">用于训练</button>
            </div>
          `;
          root.querySelector('#copyAssetIdBtn')?.addEventListener('click', async () => {
            try {
              await navigator.clipboard.writeText(String(data.id || ''));
              ctx.toast('资产ID已复制');
            } catch {
              ctx.toast(`资产ID: ${data.id}`);
            }
          });
          root.querySelector('#gotoTaskFromAsset')?.addEventListener('click', () => {
            localStorage.setItem('rv_prefill_asset_id', data.id);
            ctx.navigate('tasks');
          });
          root.querySelector('#gotoQuickDetectFromAsset')?.addEventListener('click', () => {
            localStorage.setItem('rv_quick_detect_asset_id', data.id);
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
        </form>
        <section class="card">
          <h3>模型时间线</h3>
          <div id="modelTimelineWrap">${renderEmpty('在模型列表点击“时间线”，查看提交、审批、发布和回收轨迹')}</div>
        </section>
      </section>
      <section class="card">
        <h3>模型列表</h3>
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
      const timelineWrap = root.querySelector('#modelTimelineWrap');
      const trainingJobsWrap = root.querySelector('#trainingJobsWrap');
      const trainingJobForm = root.querySelector('#trainingJobForm');
      const trainingJobMsg = root.querySelector('#trainingJobMsg');
      let cachedModels = [];

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

      async function loadModels() {
        modelsWrap.innerHTML = renderLoading('加载模型列表...');
        try {
          const rows = await ctx.get('/models');
          cachedModels = rows || [];
          if (!rows.length) {
            modelsWrap.innerHTML = renderEmpty('暂无模型，可先提交一个模型包，或等待供应商交付候选模型');
            return;
          }
          modelsWrap.innerHTML = `
            <div class="table-wrap">
              <table class="table">
                <thead>
                  <tr>
                    <th>model_code(模型编码)</th><th>version(版本)</th><th>status(状态)</th><th>source(来源)</th><th>hash(摘要)</th><th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  ${rows.map((row) => `
                    <tr>
                      <td>${esc(row.model_code)}</td>
                      <td>${esc(row.version)}</td>
                      <td>${esc(enumText('model_status', row.status))}</td>
                      <td>${esc(enumText('model_source_type', (row.platform_meta || {}).model_source_type || '-'))}</td>
                      <td class="mono">${esc((row.model_hash || '').slice(0, 16))}...</td>
                      <td class="row-actions">
                        <button class="ghost" data-model-timeline="${esc(row.id)}">时间线</button>
                        ${canApprove && row.status === 'SUBMITTED' ? `<button class="ghost" data-model-approve="${esc(row.id)}">审批通过</button>` : ''}
                        ${canRelease && ['APPROVED', 'RELEASED'].includes(row.status) ? `<button class="ghost" data-model-release="${esc(row.id)}">发布</button>` : ''}
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
            });
          });

          modelsWrap.querySelectorAll('[data-model-approve]').forEach((btn) => {
            btn.addEventListener('click', async () => {
              const modelId = btn.getAttribute('data-model-approve');
              const validationSummary = window.prompt('审批说明（可空）', '自动验收通过');
              try {
                await ctx.post('/models/approve', {
                  model_id: modelId,
                  validation_asset_ids: [],
                  validation_result: 'passed',
                  validation_summary: validationSummary || null,
                });
                ctx.toast('模型已审批通过');
                await loadModels();
              } catch (error) {
                ctx.toast(error.message, 'error');
              }
            });
          });

          modelsWrap.querySelectorAll('[data-model-release]').forEach((btn) => {
            btn.addEventListener('click', async () => {
              const modelId = btn.getAttribute('data-model-release');
              const targetDevices = splitCsv(window.prompt('目标设备（逗号分隔，可空）', 'edge-01'));
              const targetBuyers = splitCsv(window.prompt('目标买家 tenant_code（逗号分隔，可空）', 'buyer-demo-001'));
              try {
                await ctx.post('/models/release', {
                  model_id: modelId,
                  target_devices: targetDevices,
                  target_buyers: targetBuyers,
                  delivery_mode: 'local_key',
                  authorization_mode: 'device_key',
                  runtime_encryption: true,
                });
                ctx.toast('模型已发布');
                await loadModels();
              } catch (error) {
                ctx.toast(error.message, 'error');
              }
            });
          });
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
      ${
        canCreateTrainingJob
          ? `
            <section class="card">
              <h3>创建训练作业</h3>
              <div class="grid-two">
                <section class="lane-card">
                  <h4>供应商算法库</h4>
                  <p class="hint">从已发布给当前租户的算法里直接选一个基础模型，系统会自动带入供应商归属信息。</p>
                  <div id="trainingModelLibrary">${renderLoading('加载供应商算法...')}</div>
                </section>
                <section class="lane-card">
                  <h4>训练机池</h4>
                  <p class="hint">选择要执行训练的机器。可按 worker_code、host 或 IP 精确派发到指定节点。</p>
                  <div id="trainingWorkerPool">${renderLoading('加载训练机...')}</div>
                </section>
              </div>
              <section class="lane-card">
                <h4>训练数据集版本</h4>
                <p class="hint">快速识别导出的数据集会自动形成版本记录。可直接把某个版本放入训练集或验证集，不必手工回填资产 ID。</p>
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
      const jobsWrap = root.querySelector('#trainingJobsTableWrap');
      const workersWrap = root.querySelector('#trainingWorkersWrap');
      const filterForm = root.querySelector('#trainingFilterForm');
      const registerWorkerForm = root.querySelector('#registerWorkerForm');
      const registerWorkerMsg = root.querySelector('#registerWorkerMsg');
      const createForm = root.querySelector('#trainingCreateForm');
      const createMsg = root.querySelector('#trainingCreateMsg');
      const assetsDatalist = root.querySelector('#trainingAssetsDatalist');
      const modelsDatalist = root.querySelector('#trainingModelsDatalist');
      const workerCodesDatalist = root.querySelector('#trainingWorkersCodeDatalist');
      const workerHostsDatalist = root.querySelector('#trainingWorkersHostDatalist');
      const modelLibrary = root.querySelector('#trainingModelLibrary');
      const workerPool = root.querySelector('#trainingWorkerPool');
      const datasetVersionLibrary = root.querySelector('#trainingDatasetVersionLibrary');
      const datasetCompareWrap = root.querySelector('#trainingDatasetCompareWrap');
      const datasetPreviewWrap = root.querySelector('#trainingDatasetPreviewWrap');
      const selectionSummary = root.querySelector('#trainingSelectionSummary');
      const prefillTrainingAssetIds = localStorage.getItem('rv_prefill_training_asset_ids');
      const prefillTrainingDatasetLabel = localStorage.getItem('rv_prefill_training_dataset_label');
      const prefillTrainingDatasetVersionId = localStorage.getItem('rv_prefill_training_dataset_version_id');
      const prefillTrainingTargetModelCode = localStorage.getItem('rv_prefill_training_target_model_code');
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
      let activeDatasetPreview = null;
      let datasetCompareBlobUrls = [];
      let datasetPreviewBlobUrls = [];

      if (createForm && (prefillTrainingAssetIds || prefillTrainingDatasetVersionId)) {
        if (assetIdsInput && prefillTrainingAssetIds) assetIdsInput.value = prefillTrainingAssetIds;
        if (targetModelCodeInput && prefillTrainingTargetModelCode) targetModelCodeInput.value = prefillTrainingTargetModelCode;
        if (createMsg) {
          createMsg.textContent = `已预填来自快速识别的数据集资产：${prefillTrainingAssetIds || '-'}${prefillTrainingDatasetLabel ? ` · ${prefillTrainingDatasetLabel}` : ''}${prefillTrainingDatasetVersionId ? ` · ${prefillTrainingDatasetVersionId}` : ''}`;
        }
        localStorage.removeItem('rv_prefill_training_asset_ids');
        localStorage.removeItem('rv_prefill_training_dataset_label');
        localStorage.removeItem('rv_prefill_training_dataset_version_id');
        localStorage.removeItem('rv_prefill_training_target_model_code');
      }

      async function loadJobTable() {
        jobsWrap.innerHTML = renderLoading('加载训练作业...');
        try {
          const fd = new FormData(filterForm);
          const query = toQuery({
            status: fd.get('status'),
            training_kind: fd.get('training_kind'),
          });
          const rows = await ctx.get(`/training/jobs${query}`);
          if (!rows.length) {
            jobsWrap.innerHTML = renderEmpty('暂无训练作业，可从模型中心或本页下方创建一条训练 / 微调作业');
            return;
          }
          jobsWrap.innerHTML = `
            <div class="table-wrap">
              <table class="table">
                <thead>
                  <tr>
                    <th>job_code(作业编码)</th><th>status(状态)</th><th>kind(类型)</th><th>train/val(资产数)</th><th>base_model(基础模型)</th><th>candidate_model(候选模型)</th><th>worker(执行节点)</th><th>创建时间</th><th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  ${rows.map((row) => `
                    <tr>
                      <td class="mono">${esc(row.job_code)}</td>
                      <td>${esc(enumText('training_status', row.status))}</td>
                      <td>${esc(enumText('training_kind', row.training_kind))}</td>
                      <td>${esc(`${row.asset_count ?? 0}/${row.validation_asset_count ?? 0}`)}</td>
                      <td class="mono">${esc(row.base_model ? `${row.base_model.model_code}:${row.base_model.version}` : '-')}</td>
                      <td class="mono">${esc(row.candidate_model ? `${row.candidate_model.model_code}:${row.candidate_model.version}` : '-')}</td>
                      <td>${esc(row.assigned_worker_code || row.worker_selector?.host || row.worker_selector?.hosts?.[0] || '-')}</td>
                      <td>${formatDateTime(row.created_at)}</td>
                      <td>
                        <div class="row-actions">
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
        } catch (error) {
          jobsWrap.innerHTML = renderError(error.message);
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
            return;
          }
          workersWrap.innerHTML = `
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>worker_code(Worker 编码)</th><th>status(状态)</th><th>host(主机)</th><th>outstanding(待处理)</th><th>last_seen(最近心跳)</th><th>resources(资源)</th><th>操作</th></tr></thead>
                <tbody>
                  ${rows.map((row) => `
                    <tr>
                      <td class="mono">${esc(row.worker_code)}</td>
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
          workersWrap.querySelectorAll('[data-pick-worker]').forEach((button) => {
            button.addEventListener('click', () => fillWorkerSelection(button.getAttribute('data-pick-worker') || ''));
          });
        } catch (error) {
          if (String(error.message || '').includes('403')) {
            workersWrap.innerHTML = renderEmpty('当前角色无 Worker 查看权限');
            if (workerPool) workerPool.innerHTML = renderEmpty('当前角色无训练机查看权限');
            return;
          }
          workersWrap.innerHTML = renderError(error.message);
          if (workerPool) workerPool.innerHTML = renderError(error.message);
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
        const rows = assistModels.filter((row) => row.model_type === 'expert');
        const currentModelId = String(baseModelInput?.value || '').trim();
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
        const sorted = [...assistWorkers].sort((left, right) => {
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
        datasetVersionLibrary.innerHTML = `
          <div class="selection-grid">
            ${assistDatasetVersions.map((row) => {
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
                    </div>
                  </div>
                  <div class="selection-card-meta">
                    <span>asset_id</span><strong class="mono">${esc(row.asset_id)}</strong>
                    <span>来源</span><strong>${esc(row.source_type || '-')}</strong>
                    <span>样本数</span><strong>${esc(String(summary.task_count ?? summary.source_result_count ?? meta.archive_resource_count ?? 0))}</strong>
                    <span>标签</span><strong>${esc((summary.label_vocab || meta.label_vocab || []).slice(0, 6).join(', ') || '-')}</strong>
                  </div>
                  <div class="row-actions">
                    <button class="primary" type="button" data-pick-dataset-training="${esc(row.asset_id)}" data-dataset-version-id="${esc(row.id)}">加入训练集</button>
                    <button class="ghost" type="button" data-pick-dataset-validation="${esc(row.asset_id)}" data-dataset-version-id="${esc(row.id)}">加入验证集</button>
                    <button class="ghost" type="button" data-recommend-dataset-version="${esc(row.id)}">设为推荐</button>
                    <button class="ghost" type="button" data-compare-dataset-version="${esc(row.id)}">对比上一版</button>
                    <button class="ghost" type="button" data-preview-dataset-version="${esc(row.id)}">查看内容</button>
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
            button.disabled = true;
            try {
              await ctx.post(`/assets/dataset-versions/${versionId}/recommend`, { asset_purpose: 'training', note: 'training_page_recommended' });
              ctx.toast('已标记为推荐训练集');
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
            await compareWithPreviousDatasetVersion(versionId);
          });
        });
        datasetVersionLibrary.querySelectorAll('[data-preview-dataset-version]').forEach((button) => {
          button.addEventListener('click', async () => {
            const versionId = button.getAttribute('data-preview-dataset-version') || '';
            await previewDatasetVersion(versionId);
          });
        });
        renderDatasetCompare();
        renderDatasetPreview();
      }

      function renderDatasetCompare() {
        if (!datasetCompareWrap) return;
        if (!activeDatasetCompare) {
          datasetCompareWrap.innerHTML = renderEmpty('选择某个数据集版本后，可在这里查看与上一版的差异，或设为推荐训练集。');
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
          <div class="keyvals">
            <div><span>样本变化</span><strong>${esc(String(diff.task_count_delta ?? 0))}</strong></div>
            <div><span>资源变化</span><strong>${esc(String(diff.resource_count_delta ?? 0))}</strong></div>
            <div><span>已复核变化</span><strong>${esc(String(diff.reviewed_task_count_delta ?? 0))}</strong></div>
            <div><span>同一数据集</span><strong>${esc(diff.same_dataset_key ? '是' : '否')}</strong></div>
            <div><span>新增样本</span><strong>${esc(String(diff.sample_added_count ?? 0))}</strong></div>
            <div><span>移除样本</span><strong>${esc(String(diff.sample_removed_count ?? 0))}</strong></div>
            <div><span>变更样本</span><strong>${esc(String(diff.sample_changed_count ?? 0))}</strong></div>
            <div><span>样本净变化</span><strong>${esc(String(diff.sample_task_count_delta ?? 0))}</strong></div>
          </div>
          <span>新增标签：${esc((diff.labels_added || []).join(', ') || '-')}</span>
          <span>移除标签：${esc((diff.labels_removed || []).join(', ') || '-')}</span>
          ${renderSampleRows('新增样本', diff.added_samples || [], 'added')}
          ${renderSampleRows('移除样本', diff.removed_samples || [], 'removed')}
          ${renderSampleRows('变更样本', diff.changed_samples || [], 'changed')}
        `;
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
            },
          };
          renderDatasetCompare();
          return;
        }
        datasetCompareWrap.innerHTML = renderLoading('加载版本对比...');
        try {
          const payload = await ctx.get(`/assets/dataset-versions/compare${toQuery({ left_id: previous.id, right_id: current.id, sample_limit: 6 })}`);
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
          assistAssets = assets || [];
          assistModels = models || [];
          assistDatasetVersions = [...(datasetVersions || [])].sort((left, right) => {
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
        } catch {
          if (modelLibrary) modelLibrary.innerHTML = renderEmpty('供应商算法加载失败，请稍后刷新');
          if (datasetVersionLibrary) datasetVersionLibrary.innerHTML = renderEmpty('数据集版本加载失败，请稍后刷新');
          if (datasetCompareWrap) datasetCompareWrap.innerHTML = renderEmpty('数据集版本对比不可用，请稍后刷新');
          if (datasetPreviewWrap) datasetPreviewWrap.innerHTML = renderEmpty('数据集版本预览不可用，请稍后刷新');
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

      await Promise.all([loadJobTable(), loadWorkers(), loadFormAssistData()]);
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
          <label>object_prompt(要识别什么)</label>
          <input name="object_prompt" id="quickDetectPrompt" placeholder="例如 car / person / train / bus" required />
          <div class="chip-row" id="quickDetectPromptChips">
            ${QUICK_DETECT_PROMPTS.map((item) => `<button type="button" class="ghost chip-btn" data-quick-prompt="${esc(item)}">${esc(item)}</button>`).join('')}
          </div>
          <label>device_code(设备编码)</label>
          <input name="device_code" id="quickDetectDeviceCode" value="edge-01" />
          <button class="primary" type="submit">开始快速识别</button>
          <div id="quickDetectMsg" class="hint"></div>
          <div id="quickDetectPreview" class="quick-detect-preview state empty">选择图片后会在这里显示预览；如果选择视频或已有资产，会显示摘要信息。</div>
        </form>
        <section class="card">
          <h3>快速识别结果</h3>
          <div id="quickDetectResult">${renderEmpty('上传一张或多张图片 / 视频，输入要识别的对象后，VisionHub 会自动选模、创建任务、回传标注图，并支持把本次结果直接打包为训练 / 验证数据集。')}</div>
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
        <h3>任务列表</h3>
        <div id="tasksTableWrap">${renderLoading('加载任务列表...')}</div>
      </section>
    `,
    async mount(root) {
      const quickDetectForm = root.querySelector('#quickDetectForm');
      const quickDetectFile = root.querySelector('#quickDetectFile');
      const quickDetectAssetInput = root.querySelector('#quickDetectAssetInput');
      const quickDetectPrompt = root.querySelector('#quickDetectPrompt');
      const quickDetectDeviceCode = root.querySelector('#quickDetectDeviceCode');
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
      let quickPreviewUrl = '';
      let quickResultScreenshotUrls = [];
      let quickAssetPreviewUrls = [];
      let quickBatchTaskIds = [];
      let quickDatasetExport = null;
      let assistAssets = [];

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

      const prefillAsset = localStorage.getItem('rv_prefill_asset_id');
      if (prefillAsset) {
        const assetInput = root.querySelector('#taskAssetInput');
        if (assetInput) assetInput.value = prefillAsset;
        localStorage.removeItem('rv_prefill_asset_id');
      }
      const quickPrefillAsset = localStorage.getItem('rv_quick_detect_asset_id');
      if (quickPrefillAsset && quickDetectAssetInput) {
        quickDetectAssetInput.value = quickPrefillAsset;
        localStorage.removeItem('rv_quick_detect_asset_id');
      }
      renderQuickPreview();

      async function loadAssistData() {
        try {
          const [assets, pipelines, models] = await Promise.all([
            ctx.get('/assets?limit=200'),
            ctx.get('/pipelines'),
            ctx.get('/models'),
          ]);
          assistAssets = assets || [];
          assetsDatalist.innerHTML = (assets || []).map((row) => `<option value="${esc(row.id)}">${esc(row.file_name)}</option>`).join('');
          pipelinesDatalist.innerHTML = (pipelines || []).map((row) => `<option value="${esc(row.id)}">${esc(row.pipeline_code)}:${esc(row.version)}</option>`).join('');
          modelsDatalist.innerHTML = (models || []).map((row) => `<option value="${esc(row.id)}">${esc(row.model_code)}:${esc(row.version)}</option>`).join('');
        } catch {
          // Ignore suggestion loading failure.
        }
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
        resultJson.predictions = serializedPredictions;
        resultJson.object_count = editablePredictions.length;
        resultJson.matched_labels = matchedLabels;
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
          score: Number.isFinite(Number(next.score)) ? Number(Number(next.score).toFixed(4)) : 1,
          bbox,
          attributes: {
            ...(cloneJson(next.attributes || {}) || {}),
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
            return `
              <div
                class="quick-review-box ${prediction.source === 'manual' ? 'manual' : ''} ${prediction.source === 'draft' ? 'draft' : ''} ${prediction._id === outcome.activePredictionId ? 'selected' : ''}"
                style="left:${left}%;top:${top}%;width:${width}%;height:${height}%;"
                data-review-box="${esc(prediction._id)}"
                data-review-index="${esc(String(outcome._index ?? 0))}"
                data-review-pred="${esc(prediction._id)}"
              >
                <span>${esc(`${prediction.label} ${score}`)}</span>
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
            outcome.draftPrediction = makeReviewPrediction({ label: outcome.prompt || 'object', score: 1, bbox: [0, 0, 1, 1], source: 'draft' }, outcome.prompt);
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
        });
        quickBatchTaskIds = outcomes.map((item) => item.task.id);
        const totalObjects = outcomes.reduce(
          (sum, item) => sum + Number(item?.predictions?.length ?? item?.focus?.result_json?.object_count ?? 0),
          0,
        );
        const uniqueLabels = [...new Set(outcomes.flatMap((item) => item.predictions.map((pred) => String(pred.label || '').trim()).filter(Boolean)))];
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
            <div class="quick-detect-recommend">本次快速识别已完成。你可以删掉误检、补手工框并保存修订，然后把整批结果打包为训练 / 验证数据集版本。</div>
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
                      <div><span>selected_model</span><strong>${esc(`${item.recommendation?.selected_model?.model_code || '-'}:${item.recommendation?.selected_model?.version || '-'}`)}</strong></div>
                      <div><span>object_count</span><strong>${esc(String(item.predictions.length))}</strong></div>
                    </div>
                    <div class="quick-detect-recommend">${esc(item.recommendation?.summary || '已完成自动选模并执行快速识别')}</div>
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
                                  .map((pred) => `<span class="badge">${esc(`${pred.label}:${Number(pred.score || 0).toFixed(2)}`)}</span>`)
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
            localStorage.setItem('rv_prefill_training_asset_ids', quickDatasetExport.asset.id);
            localStorage.setItem('rv_prefill_training_dataset_label', datasetLabel);
            if (quickDatasetExport.dataset_version?.id) localStorage.setItem('rv_prefill_training_dataset_version_id', quickDatasetExport.dataset_version.id);
            localStorage.setItem('rv_prefill_training_target_model_code', 'object_detect');
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

      async function runQuickDetectItem({ file, existingAssetId, prompt, deviceCode, index, total }) {
        let uploadedAsset = null;
        let assetId = existingAssetId;
        if (file) {
          const uploadForm = new FormData();
          uploadForm.set('file', file);
          uploadForm.set('asset_purpose', 'inference');
          uploadForm.set('sensitivity_level', 'L2');
          uploadForm.set('dataset_label', `quick-detect-${prompt}`);
          uploadForm.set('use_case', 'quick-detect');
          uploadForm.set('intended_model_code', 'object_detect');
          quickDetectResult.innerHTML = renderLoading(`正在上传资产 ${index + 1}/${total} ...`);
          uploadedAsset = await ctx.postForm('/assets/upload', uploadForm);
          assetId = uploadedAsset.id;
        }

        quickDetectResult.innerHTML = renderLoading(`正在自动选模 ${index + 1}/${total} ...`);
        const recommendation = await ctx.post('/tasks/recommend-model', {
          asset_id: assetId,
          task_type: 'object_detect',
          device_code: deviceCode,
          intent_text: prompt,
          limit: 3,
        });
        if (!recommendation?.selected_model?.model_id) {
          throw new Error('当前没有可用于快速识别的已发布模型');
        }

        quickDetectResult.innerHTML = renderLoading(`正在执行快速识别 ${index + 1}/${total} ...`);
        const task = await ctx.post('/tasks/create', {
          asset_id: assetId,
          task_type: 'object_detect',
          device_code: deviceCode,
          use_master_scheduler: true,
          intent_text: prompt,
          context: { object_prompt: prompt },
          options: { object_prompt: prompt },
          policy: {
            upload_raw_video: false,
            upload_frames: true,
            desensitize_frames: false,
            retention_days: 30,
            quick_detect: { object_prompt: prompt },
          },
        });
        localStorage.setItem('rv_last_task_id', task.id);
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
      quickDetectAssetInput?.addEventListener('input', () => {
        if (!quickDetectFile?.files?.length) renderQuickPreview();
      });
      root.querySelectorAll('[data-quick-prompt]').forEach((btn) => {
        btn.addEventListener('click', () => {
          if (quickDetectPrompt) quickDetectPrompt.value = btn.getAttribute('data-quick-prompt') || '';
        });
      });

      quickDetectForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        quickDetectMsg.textContent = '';
        const submitBtn = quickDetectForm.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        quickDetectResult.innerHTML = renderLoading('正在准备快速识别...');
        try {
          const prompt = String(quickDetectPrompt?.value || '').trim();
          const deviceCode = String(quickDetectDeviceCode?.value || 'edge-01').trim() || 'edge-01';
          const existingAssetIds = splitCsv(quickDetectAssetInput?.value || '');
          const files = Array.from(quickDetectFile?.files || []);
          if (!prompt) {
            throw new Error('请输入要识别的对象');
          }
          if (!files.length && !existingAssetIds.length) {
            throw new Error('请上传图片/视频，或填写已有 asset_id');
          }

          revokeQuickUrls();
          quickBatchTaskIds = [];
          quickDatasetExport = null;
          const workItems = [
            ...files.map((file) => ({ file, existingAssetId: '', prompt, deviceCode })),
            ...existingAssetIds.map((assetId) => ({ file: null, existingAssetId: assetId, prompt, deviceCode })),
          ];
          const outcomes = [];
          for (let index = 0; index < workItems.length; index += 1) {
            const outcome = await runQuickDetectItem({ ...workItems[index], index, total: workItems.length });
            outcomes.push(outcome);
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
            </div>
          `;
          root.querySelector('#openTaskDetail')?.addEventListener('click', () => ctx.navigate(`tasks/${created.id}`));
          root.querySelector('#openTaskResults')?.addEventListener('click', () => ctx.navigate(`results/task/${created.id}`));
          localStorage.setItem('rv_last_task_id', created.id);
          await loadTasks();
        } catch (error) {
          createMsg.textContent = error.message || '创建失败';
        } finally {
          submitBtn.disabled = false;
        }
      });

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

function buildResultListHtml(rows) {
  if (!rows.length) return renderEmpty('暂无结果，请确认任务已执行完成，或返回任务中心重新创建任务');
  return `
    <div class="result-list">
      ${rows.map((row) => `
        <article class="result-card">
          <div class="result-head">
            <strong>${esc(row.id)}</strong>
            <span class="badge">${esc(row.alert_level)}</span>
          </div>
          <p class="muted">model_id: ${esc(row.model_id || '-')} · duration: ${esc(row.duration_ms ?? '-')}ms · created: ${formatDateTime(row.created_at)}</p>
          <details>
            <summary>结果 JSON</summary>
            <pre>${esc(safeJson(row.result_json))}</pre>
          </details>
          ${row.screenshot_uri ? `<button class="ghost" data-open-shot="${esc(row.id)}">查看截图</button>` : '<p class="muted">无截图</p>'}
        </article>
      `).join('')}
    </div>
  `;
}

function pageResults(route, rawCtx) {
  const ctx = makeContext(route, rawCtx);
  const role = primaryRole(ctx.state.user);
  const defaultTaskId = route.params?.task_id || localStorage.getItem('rv_last_task_id') || '';
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
        <div id="resultMeta" class="hint"></div>
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
      }

      async function loadByTaskId(taskId) {
        const clean = String(taskId || '').trim();
        if (!clean) {
          listWrap.innerHTML = renderEmpty('请输入 task_id，或先在任务中心创建并执行任务');
          resultMeta.textContent = '';
          return;
        }
        listWrap.innerHTML = renderLoading('加载结果...');
        resultMeta.textContent = '';
        try {
          const rows = await ctx.get(`/results${toQuery({ task_id: clean })}`);
          listWrap.innerHTML = buildResultListHtml(rows || []);
          resultMeta.textContent = `task_id=${clean} · 结果条数=${rows.length}`;
          localStorage.setItem('rv_last_task_id', clean);
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
