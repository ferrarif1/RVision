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

function splitCsv(value) {
  return String(value || '')
    .split(/[\n,，\s]+/)
    .map((v) => v.trim())
    .filter(Boolean);
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
                  </div>
                  <div class="form-grid">
                    <label>base_model_id(基础模型ID，可选)</label>
                    <input name="base_model_id" list="trainingModelsDatalist" placeholder="model-id" />
                    <label>target_model_code(目标模型编码)</label>
                    <input name="target_model_code" placeholder="car_number_ocr" required />
                    <label>target_version(目标版本)</label>
                    <input name="target_version" placeholder="v2.0.0" required />
                  </div>
                </div>
                <datalist id="trainingAssetsDatalist"></datalist>
                <datalist id="trainingModelsDatalist"></datalist>
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
                    <th>job_code(作业编码)</th><th>status(状态)</th><th>kind(类型)</th><th>train/val(资产数)</th><th>base_model(基础模型)</th><th>candidate_model(候选模型)</th><th>worker(执行节点)</th><th>创建时间</th>
                  </tr>
                </thead>
                <tbody>
                  ${rows.map((row) => `
                    <tr>
                      <td class="mono">${esc(row.job_code)}</td>
                      <td>${esc(enumText('training_status', row.status))}</td>
                      <td>${esc(enumText('training_kind', row.training_kind))}</td>
                      <td>${esc(`${row.asset_count ?? 0}/${row.validation_asset_count ?? 0}`)}</td>
                      <td class="mono">${esc(row.base_model?.id || '-')}</td>
                      <td class="mono">${esc(row.candidate_model?.id || '-')}</td>
                      <td>${esc(row.assigned_worker_code || '-')}</td>
                      <td>${formatDateTime(row.created_at)}</td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          `;
        } catch (error) {
          jobsWrap.innerHTML = renderError(error.message);
        }
      }

      async function loadWorkers() {
        workersWrap.innerHTML = renderLoading('加载 worker...');
        try {
          const rows = await ctx.get('/training/workers');
          if (!rows.length) {
            workersWrap.innerHTML = renderEmpty('暂无 Worker，请先接入训练执行节点或在下方注册 Worker');
            return;
          }
          workersWrap.innerHTML = `
            <div class="table-wrap">
              <table class="table">
                <thead><tr><th>worker_code(Worker 编码)</th><th>status(状态)</th><th>host(主机)</th><th>outstanding(待处理)</th><th>last_seen(最近心跳)</th><th>resources(资源)</th></tr></thead>
                <tbody>
                  ${rows.map((row) => `
                    <tr>
                      <td class="mono">${esc(row.worker_code)}</td>
                      <td>${esc(enumText('worker_status', row.status))}</td>
                      <td>${esc(row.host || '-')}</td>
                      <td>${esc(row.outstanding_jobs ?? 0)}</td>
                      <td>${formatDateTime(row.last_seen_at)}</td>
                      <td><details><summary>查看</summary><pre>${esc(safeJson(row.resources || {}))}</pre></details></td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          `;
        } catch (error) {
          if (String(error.message || '').includes('403')) {
            workersWrap.innerHTML = renderEmpty('当前角色无 Worker 查看权限');
            return;
          }
          workersWrap.innerHTML = renderError(error.message);
        }
      }

      async function loadFormAssistData() {
        if (!createForm) return;
        try {
          const [assets, models] = await Promise.all([
            ctx.get('/assets?limit=200'),
            ctx.get('/models'),
          ]);
          assetsDatalist.innerHTML = (assets || []).map((row) => `<option value="${esc(row.id)}">${esc(row.file_name)}</option>`).join('');
          modelsDatalist.innerHTML = (models || []).map((row) => `<option value="${esc(row.id)}">${esc(row.model_code)}:${esc(row.version)}</option>`).join('');
        } catch {
          // Ignore assist data failure; main form still works.
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
          const payload = {
            training_kind: String(fd.get('training_kind') || 'finetune'),
            asset_ids: splitCsv(fd.get('asset_ids')),
            validation_asset_ids: splitCsv(fd.get('validation_asset_ids')),
            base_model_id: String(fd.get('base_model_id') || '').trim() || null,
            target_model_code: String(fd.get('target_model_code') || '').trim(),
            target_version: String(fd.get('target_version') || '').trim(),
            worker_selector: {},
            spec: {},
          };
          const result = await ctx.post('/training/jobs', payload);
          createMsg.textContent = `创建成功：${result.job_code}`;
          ctx.toast('训练作业创建成功');
          await loadJobTable();
        } catch (error) {
          createMsg.textContent = error.message || '创建失败';
        } finally {
          submitBtn.disabled = false;
        }
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
          <input id="quickDetectFile" type="file" accept=".jpg,.jpeg,.png,.bmp,.mp4,.avi,.mov" />
          <div class="hint">上传一张图片或一个短视频；如果资产已经在平台内，也可以直接填写 asset_id。</div>
          <label>asset_id(已有资产ID，可选)</label>
          <input name="asset_id" id="quickDetectAssetInput" list="taskAssetsDatalist" placeholder="已有 asset_id，可空" />
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
          <div id="quickDetectResult">${renderEmpty('上传一张图或视频，输入要识别的对象后，VisionHub 会自动选模、创建任务并回传标注图。')}</div>
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
      let quickResultScreenshotUrl = '';

      function revokeQuickUrls() {
        if (quickPreviewUrl) {
          URL.revokeObjectURL(quickPreviewUrl);
          quickPreviewUrl = '';
        }
        if (quickResultScreenshotUrl) {
          URL.revokeObjectURL(quickResultScreenshotUrl);
          quickResultScreenshotUrl = '';
        }
      }

      function renderQuickPreview() {
        const file = quickDetectFile?.files?.[0];
        revokeQuickUrls();
        if (!file) {
          if (quickDetectAssetInput?.value.trim()) {
            quickDetectPreview.className = 'quick-detect-preview';
            quickDetectPreview.innerHTML = `
              <div class="quick-detect-preview-meta">
                <strong>已有资产</strong>
                <span class="mono">${esc(quickDetectAssetInput.value.trim())}</span>
              </div>
            `;
            return;
          }
          quickDetectPreview.className = 'quick-detect-preview state empty';
          quickDetectPreview.textContent = '选择图片后会在这里显示预览；如果选择视频或已有资产，会显示摘要信息。';
          return;
        }

        quickPreviewUrl = URL.createObjectURL(file);
        quickDetectPreview.className = 'quick-detect-preview';
        if (String(file.type || '').startsWith('image/')) {
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
            <strong>${esc(file.name)}</strong>
            <span>${esc(file.type || 'video/*')} · ${esc(`${Math.max(1, Math.round(file.size / 1024))} KB`)}</span>
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

      async function renderQuickDetectOutcome({ uploadedAsset, recommendation, task, rows, prompt }) {
        const focus = pickQuickDetectResult(rows);
        const predictions = Array.isArray(focus?.result_json?.predictions) ? focus.result_json.predictions : [];
        const promptSupported = focus?.result_json?.prompt_supported;

        if (quickResultScreenshotUrl) {
          URL.revokeObjectURL(quickResultScreenshotUrl);
          quickResultScreenshotUrl = '';
        }
        if (focus?.id) {
          try {
            quickResultScreenshotUrl = await fetchAuthorizedBlobUrl(`/results/${focus.id}/screenshot`, ctx.token);
          } catch {
            quickResultScreenshotUrl = '';
          }
        }

        quickDetectResult.innerHTML = `
          <div class="quick-detect-result">
            <div class="keyvals">
              <div><span>asset_id</span><strong class="mono">${esc(uploadedAsset?.id || task.asset_id || '-')}</strong></div>
              <div><span>task_id</span><strong class="mono">${esc(task.id)}</strong></div>
              <div><span>query</span><strong>${esc(prompt)}</strong></div>
              <div><span>selected_model</span><strong>${esc(`${recommendation?.selected_model?.model_code || task.model_code || '-'}:${recommendation?.selected_model?.version || '-'}`)}</strong></div>
              <div><span>status</span><strong>${esc(enumText('task_status', task.status))}</strong></div>
              <div><span>object_count</span><strong>${esc(String(focus?.result_json?.object_count ?? predictions.length ?? 0))}</strong></div>
            </div>
            <div class="quick-detect-recommend">${esc(recommendation?.summary || '已完成自动选模并执行快速识别')}</div>
            ${
              quickResultScreenshotUrl
                ? `<div class="quick-detect-shot"><img src="${quickResultScreenshotUrl}" alt="快速识别标注图" /></div>`
                : renderEmpty('当前结果暂无可用标注图')
            }
            <div class="quick-detect-preds">
              ${
                predictions.length
                  ? predictions
                      .slice(0, 8)
                      .map((pred) => `<span class="badge">${esc(`${pred.label}:${Number(pred.score || 0).toFixed(2)}`)}</span>`)
                      .join('')
                  : `<span class="hint">${esc(promptSupported === false ? '当前提示词不在模型可识别标签内，建议尝试 car / person / train / bus。' : '已完成执行，但当前图片中没有匹配到目标。')}</span>`
              }
            </div>
            <div class="row-actions">
              <button class="primary" id="openQuickDetectResult">查看结果页</button>
              <button class="ghost" id="openQuickDetectTask">查看任务详情</button>
            </div>
          </div>
        `;
        root.querySelector('#openQuickDetectResult')?.addEventListener('click', () => ctx.navigate(`results/task/${task.id}`));
        root.querySelector('#openQuickDetectTask')?.addEventListener('click', () => ctx.navigate(`tasks/${task.id}`));
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
          const existingAssetId = String(quickDetectAssetInput?.value || '').trim();
          const file = quickDetectFile?.files?.[0];
          if (!prompt) {
            throw new Error('请输入要识别的对象');
          }
          if (!file && !existingAssetId) {
            throw new Error('请上传图片/视频，或填写已有 asset_id');
          }

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
            quickDetectResult.innerHTML = renderLoading('正在上传资产...');
            uploadedAsset = await ctx.postForm('/assets/upload', uploadForm);
            assetId = uploadedAsset.id;
            if (quickDetectAssetInput) quickDetectAssetInput.value = assetId;
          }

          quickDetectResult.innerHTML = renderLoading('正在推荐模型...');
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

          quickDetectResult.innerHTML = renderLoading('已选中模型，正在创建任务并等待结果...');
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
          await renderQuickDetectOutcome({
            uploadedAsset,
            recommendation,
            task: settled.task,
            rows: settled.rows,
            prompt,
          });
          quickDetectMsg.textContent = `快速识别完成：${task.id}`;
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
