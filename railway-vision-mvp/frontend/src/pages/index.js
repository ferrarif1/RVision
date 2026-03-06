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
    ocr: '文字识别',
    detect: '目标检测',
  },
};

function enumText(group, value) {
  const rendered = String(value ?? '-');
  const label = ENUM_ZH[group]?.[rendered];
  return label ? `${rendered}(${label})` : rendered;
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
          <h2>Welcome to VisionHub</h2>
          <p class="login-subtitle">The secure way to ship vision models</p>
          <div class="init-account-box">
            <div class="init-account-title">初始账户（用户名 / 密码）</div>
            <ul class="init-account-list">
              <li><span class="mono">platform_admin</span><span class="mono">platform123</span></li>
              <li><span class="mono">supplier_demo</span><span class="mono">supplier123</span></li>
              <li><span class="mono">buyer_operator</span><span class="mono">buyer123</span></li>
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
  return {
    html: `
      <section class="card">
        <h2>四主线工作台</h2>
        <p>资产上传 -> 模型迭代 -> 审批发布 -> 设备授权执行</p>
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
  return {
    html: `
      <section class="card">
        <h2>资产中心</h2>
        <p>上传图片、视频或 ZIP 数据集包，支持训练、验证、微调、推理等用途。</p>
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
          <div id="assetUploadResult">${renderEmpty('上传后显示资产ID和摘要')}</div>
        </section>
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
            tableWrap.innerHTML = renderEmpty('暂无资产，可先上传一条用于后续任务创建');
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
  const canApprove = hasPermission(ctx.state, 'model.approve');
  const canRelease = hasPermission(ctx.state, 'model.release');
  const canCreateTrainingJob = hasPermission(ctx.state, 'training.job.create');
  const canViewTrainingJob = hasPermission(ctx.state, 'training.job.view');

  return {
    html: `
      <section class="card">
        <h2>模型中心</h2>
        <p>供应商提交模型包，平台审批并发布到授权设备。</p>
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
          <div id="modelTimelineWrap">${renderEmpty('在模型列表点击“时间线”查看')}</div>
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
            trainingJobsWrap.innerHTML = renderEmpty('暂无训练作业');
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
            modelsWrap.innerHTML = renderEmpty('暂无模型，可先提交一个模型包');
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
  const canCreateTrainingJob = hasPermission(ctx.state, 'training.job.create');
  const canManageWorkers = hasPermission(ctx.state, 'training.worker.manage');
  return {
    html: `
      <section class="card">
        <h2>训练中心</h2>
        <p>作业调度、worker 健康、候选模型回收。</p>
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
            jobsWrap.innerHTML = renderEmpty('暂无训练作业');
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
            workersWrap.innerHTML = renderEmpty('暂无 Worker');
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
  const canRelease = hasPermission(ctx.state, 'model.release');
  return {
    html: `
      <section class="card">
        <h2>流水线中心</h2>
        <p>编排路由模型与专家模型，发布后可直接用于任务执行。</p>
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
          <h3>说明</h3>
          <p>默认可先使用空 JSON；复杂编排可在 Advanced 中编辑。</p>
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
            tableWrap.innerHTML = renderEmpty('暂无流水线，先注册一条');
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
  return {
    html: `
      <section class="card">
        <h2>任务中心</h2>
        <p>选择资产与模型/流水线，创建推理任务并跟踪状态。</p>
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
            <option value="ocr">${enumText('task_type', 'ocr')}</option>
            <option value="detect">${enumText('task_type', 'detect')}</option>
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
          <div id="taskCreateResult">${renderEmpty('创建成功后显示 task_id')}</div>
        </section>
      </section>
      <section class="card">
        <h3>任务列表</h3>
        <div id="tasksTableWrap">${renderLoading('加载任务列表...')}</div>
      </section>
    `,
    async mount(root) {
      const createForm = root.querySelector('#taskCreateForm');
      const createMsg = root.querySelector('#taskCreateMsg');
      const createResult = root.querySelector('#taskCreateResult');
      const tableWrap = root.querySelector('#tasksTableWrap');
      const assetsDatalist = root.querySelector('#taskAssetsDatalist');
      const pipelinesDatalist = root.querySelector('#taskPipelinesDatalist');
      const modelsDatalist = root.querySelector('#taskModelsDatalist');
      const prefillAsset = localStorage.getItem('rv_prefill_asset_id');
      if (prefillAsset) {
        const assetInput = root.querySelector('#taskAssetInput');
        if (assetInput) assetInput.value = prefillAsset;
        localStorage.removeItem('rv_prefill_asset_id');
      }

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

      async function loadTasks() {
        tableWrap.innerHTML = renderLoading('加载任务列表...');
        try {
          const rows = await ctx.get('/tasks');
          if (!rows.length) {
            tableWrap.innerHTML = renderEmpty('暂无任务');
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
  if (!rows.length) return renderEmpty('暂无结果');
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
  const defaultTaskId = route.params?.task_id || localStorage.getItem('rv_last_task_id') || '';
  return {
    html: `
      <section class="card">
        <h2>结果中心</h2>
        <p>按 task_id 查询结构化结果，可导出审计摘要。</p>
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
        <div id="resultListWrap">${defaultTaskId ? renderLoading('加载结果...') : renderEmpty('请输入 task_id 查询')}</div>
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
          listWrap.innerHTML = renderEmpty('请输入 task_id');
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
        <p>关键动作可追溯：模型审批发布、任务创建、结果导出、设备拉取等。</p>
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
            tableWrap.innerHTML = renderEmpty('暂无审计日志');
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
  return {
    html: `
      <section class="card">
        <h2>设备中心</h2>
        <p>展示授权边缘设备运行状态与最近心跳。</p>
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
          wrap.innerHTML = renderEmpty('暂无设备或当前角色无可见设备');
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
          wrap.innerHTML = renderEmpty('后端接口待接入：/devices');
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
        <p>查看当前登录身份、租户和权限能力。</p>
      </section>
      <section class="card" id="settingsWrap">${renderLoading('加载用户信息...')}</section>
    `,
    async mount(root) {
      const wrap = root.querySelector('#settingsWrap');
      try {
        const me = await ctx.get('/users/me');
        wrap.innerHTML = `
          <div class="keyvals">
            <div><span>username</span><strong>${esc(me.username)}</strong></div>
            <div><span>roles</span><strong>${esc((me.roles || []).join(','))}</strong></div>
            <div><span>tenant_code</span><strong>${esc(me.tenant_code || '-')}</strong></div>
            <div><span>tenant_type</span><strong>${esc(me.tenant_type || '-')}</strong></div>
          </div>
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
