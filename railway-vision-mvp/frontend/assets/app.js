      const API_BASE = "/api";
      const PERMISSIONS = {
        MODEL_VIEW: "model.view",
        MODEL_SUBMIT: "model.submit",
        MODEL_APPROVE: "model.approve",
        MODEL_RELEASE: "model.release",
        ASSET_UPLOAD: "asset.upload",
        TASK_CREATE: "task.create",
        RESULT_READ: "result.read",
        AUDIT_READ: "audit.read",
        DATA_L3_READ: "data.l3.read",
      };
      const SENSITIVE_FIELDS = new Set([
        "source_uri",
        "sourceUri",
        "storage_uri",
        "asset_path",
        "frame_path",
        "preview_uri",
        "raw_video_uri",
        "payload",
        "content",
        "image_base64",
      ]);
      const DEFAULT_ACCOUNTS = {
        platform_admin: { username: "platform_admin", password: "platform123" },
        supplier_demo: { username: "supplier_demo", password: "supplier123" },
        buyer_operator: { username: "buyer_operator", password: "buyer123" },
        buyer_auditor: { username: "buyer_auditor", password: "buyer123" },
      };

      const PAGES = [
        { id: "dashboard", label: "开始", perm: null },
        { id: "models", label: "模型", perm: PERMISSIONS.MODEL_VIEW },
        { id: "pipelines", label: "流水线", perm: PERMISSIONS.MODEL_VIEW },
        { id: "assets", label: "资产", perm: PERMISSIONS.ASSET_UPLOAD },
        { id: "tasks", label: "执行", perm: PERMISSIONS.TASK_CREATE },
        { id: "task-monitor", label: "任务监控", perm: PERMISSIONS.RESULT_READ },
        { id: "results", label: "结果", perm: PERMISSIONS.RESULT_READ },
        { id: "audit", label: "审计", perm: PERMISSIONS.AUDIT_READ },
      ];

      const PRIMARY_NAV_IDS = ["dashboard", "models", "assets", "tasks", "results"];
      const SECONDARY_NAV_IDS = ["pipelines", "task-monitor", "audit"];

      const PAGE_META = {
        dashboard: {
          title: "开始",
          desc: "先完成当前角色最常见的 3 步。",
          steps: [
            { title: "看清路径", desc: "先看当前角色最常见的 3 步。" },
            { title: "进入操作", desc: "从常用入口进入模型、资产、执行或结果页面。" },
          ],
        },
        models: {
          title: "模型",
          desc: "提交、审批和发布模型。",
          steps: [
            { title: "提交模型包", desc: "先提交候选模型或主路由模型。" },
            { title: "审批与发布", desc: "验证通过后再发布。" },
            { title: "查看状态", desc: "从列表确认版本和状态。" },
          ],
        },
        pipelines: {
          title: "流水线",
          desc: "配置主路由、专家和发布范围。",
          steps: [
            { title: "选择主路由", desc: "指定 router 和基础策略。" },
            { title: "绑定专家", desc: "配置专家、阈值和融合规则。" },
            { title: "发布流水线", desc: "按客户和设备发布。" },
          ],
        },
        assets: {
          title: "资产",
          desc: "上传图片或视频并生成资产 ID。",
          steps: [
            { title: "选择文件", desc: "支持图片或视频。" },
            { title: "设置用途", desc: "选择训练、微调、测试或推理。" },
            { title: "得到资产 ID", desc: "上传成功后直接去执行。" },
          ],
        },
        tasks: {
          title: "执行",
          desc: "选择流水线并创建一次执行任务。",
          steps: [
            { title: "选择流水线", desc: "默认使用 Pipeline。" },
            { title: "填写关键输入", desc: "只填资产、场景和设备。" },
            { title: "创建任务", desc: "系统会固化版本和策略。" },
          ],
        },
        "task-monitor": {
          title: "任务监控",
          desc: "查看任务状态和执行进度。",
          steps: [
            { title: "输入任务 ID", desc: "定位一条具体任务。" },
            { title: "查看状态", desc: "判断是否完成或失败。" },
            { title: "进入结果", desc: "完成后再看结果输出。" },
          ],
        },
        results: {
          title: "结果",
          desc: "查看结构化结果和截图。",
          steps: [
            { title: "输入任务 ID", desc: "任务 ID 可从执行页回填。" },
            { title: "查看结果", desc: "核对结构化输出和截图。" },
            { title: "导出摘要", desc: "需要留痕时再导出。" },
          ],
        },
        audit: {
          title: "审计",
          desc: "查询关键操作日志。",
          steps: [
            { title: "输入条件", desc: "按动作、人和资源筛选。" },
            { title: "核对事件", desc: "重点看时间、人和资源。" },
            { title: "完成回查", desc: "确认关键动作已留痕。" },
          ],
        },
      };

      const FLOW_STEPS = [
        { id: "dashboard", code: "00", title: "开始", desc: "看清 3 步主路径" },
        { id: "models", code: "01", title: "模型", desc: "提交、审批和发布模型" },
        { id: "pipelines", code: "02", title: "流水线", desc: "配置编排和发布范围" },
        { id: "assets", code: "03", title: "资产", desc: "上传资产并生成 ID" },
        { id: "tasks", code: "04", title: "执行", desc: "选择流水线并创建任务" },
        { id: "task-monitor", code: "05", title: "任务监控", desc: "跟踪任务状态" },
        { id: "results", code: "06", title: "结果", desc: "查看结果和截图" },
        { id: "audit", code: "07", title: "审计", desc: "查询关键日志" },
      ];

      const NAV_GROUPS = [
        { title: "常用", pages: PRIMARY_NAV_IDS },
        { title: "更多", pages: SECONDARY_NAV_IDS },
      ];

      const state = {
        token: localStorage.getItem("rv_token") || "",
        user: null,
        permissions: new Set(),
        page: "dashboard",
        pendingApi: 0,
        models: [],
        pipelines: [],
        tasks: [],
        currentTask: null,
        resultRows: [],
        visibleAuditRows: [],
        modelTimeline: null,
        lastAssetId: "",
        lastTaskId: "",
        auditRows: [],
        taskMonitorAuto: false,
        taskMonitorTimer: null,
        modelPage: 1,
        drawerLastFocus: null,
      };

      function hasPermission(permission) {
        if (!permission) return true;
        return state.permissions.has(permission);
      }

      function setTopLoading(active) {
        const bar = document.getElementById("topLoadingValue");
        if (!bar) return;
        if (active) {
          bar.style.width = "70%";
          return;
        }
        bar.style.width = "100%";
        setTimeout(() => {
          if (state.pendingApi === 0) bar.style.width = "0";
        }, 140);
      }

      function updateTaskMonitorBadge() {
        const btn = document.getElementById("btnTaskAutoRefresh");
        const status = document.getElementById("taskMonitorStatus");
        if (btn) btn.textContent = state.taskMonitorAuto ? "关闭自动刷新" : "开启自动刷新";
        if (status) status.textContent = state.taskMonitorAuto ? "自动刷新中" : "自动刷新关闭";
        if (state.page === "task-monitor") {
          renderPageCommandBar("task-monitor");
        }
      }

      function stopTaskMonitorAuto() {
        if (state.taskMonitorTimer) {
          window.clearInterval(state.taskMonitorTimer);
          state.taskMonitorTimer = null;
        }
        state.taskMonitorAuto = false;
        updateTaskMonitorBadge();
      }

      function toast(msg, kind = "") {
        const root = document.getElementById("toastRoot");
        const t = document.createElement("div");
        t.className = `toast ${kind}`;
        t.innerHTML = `<div class="toast-row"><span>${escapeHtml(msg)}</span></div>`;
        root.appendChild(t);
        setTimeout(() => {
          if (t.parentNode) t.parentNode.removeChild(t);
        }, 3000);
      }

      async function api(path, opts = {}, isForm = false) {
        state.pendingApi += 1;
        setTopLoading(true);
        const headers = opts.headers || {};
        if (state.token) headers.Authorization = `Bearer ${state.token}`;
        if (!isForm && opts.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";

        try {
          const resp = await fetch(`${API_BASE}${path}`, { ...opts, headers });
          const text = await resp.text();
          let data;
          try {
            data = JSON.parse(text);
          } catch {
            data = text;
          }
          if (!resp.ok) {
            const detail = typeof data === "string" ? data : data?.detail || data?.message || `请求失败(${resp.status})`;
            throw new Error(detail);
          }
          return data;
        } finally {
          state.pendingApi = Math.max(0, state.pendingApi - 1);
          if (state.pendingApi === 0) setTopLoading(false);
        }
      }

      function useAccount(roleKey) {
        const account = DEFAULT_ACCOUNTS[roleKey];
        if (!account) return;
        document.getElementById("username").value = account.username;
        document.getElementById("password").value = account.password;
        setFieldError("username", "");
        setFieldError("password", "");
        toast(`已填充：${account.username}`);
      }

      function roleText(user) {
        return (user?.roles || []).join(", ") || "-";
      }

      function primaryRole() {
        return state.user?.roles?.[0] || "";
      }

      function actionButtonHtml(label, action) {
        return `<button class="ghost btn-auto" onclick="${action}">${escapeHtml(label)}</button>`;
      }

      function primaryActionButtonHtml(label, action) {
        return `<button class="btn-auto" onclick="${action}">${escapeHtml(label)}</button>`;
      }

      function stateActionButtonHtml(label, action, primary = false) {
        return `<button class="${primary ? "btn-auto" : "ghost btn-auto"}" onclick="${action}">${escapeHtml(label)}</button>`;
      }

      function stateActionsHtml(actions = []) {
        return actions
          .filter((item) => item && item.label && item.action)
          .map((item) => stateActionButtonHtml(item.label, item.action, !!item.primary))
          .join("");
      }

      function pageConfig(pageId) {
        return PAGES.find((item) => item.id === pageId) || PAGES[0];
      }

      function flowStep(pageId) {
        return FLOW_STEPS.find((item) => item.id === pageId) || FLOW_STEPS[0];
      }

      function roleFamily(role = primaryRole()) {
        if (String(role || "").startsWith("supplier")) return "supplier";
        if (String(role || "").startsWith("buyer")) return "buyer";
        return "platform";
      }

      function nextAllowedPage(pageId = state.page) {
        const index = FLOW_STEPS.findIndex((item) => item.id === pageId);
        if (index < 0) return "";
        for (let i = index + 1; i < FLOW_STEPS.length; i += 1) {
          const nextPage = pageConfig(FLOW_STEPS[i].id);
          if (hasPermission(nextPage?.perm)) return nextPage.id;
        }
        return "";
      }

      function focusField(id) {
        const el = document.getElementById(id);
        if (!el) return;
        el.focus();
        if (typeof el.select === "function") {
          el.select();
        }
      }

      function renderSidebarContext(pageId) {
        const root = document.getElementById("sidebarNote");
        if (!root) return;
        const meta = PAGE_META[pageId] || PAGE_META.dashboard;
        const stage = flowStep(pageId);
        const nextId = nextAllowedPage(pageId);
        const next = nextId ? flowStep(nextId) : null;

        root.innerHTML = `
          <div class="sidebar-note-kicker">当前页面 · ${escapeHtml(stage.code)}</div>
          <strong>${escapeHtml(stage.title)}</strong>
          <p>${escapeHtml(meta.desc)}</p>
          ${next ? `<div class="sidebar-note-tail">下一步：${escapeHtml(next.title)}</div>` : ""}`;
      }

      function renderPageCommandBar(pageId) {
        const root = document.getElementById("pageCommandBar");
        if (!root) return;

        if (pageId === "dashboard" || PRIMARY_NAV_IDS.includes(pageId)) {
          root.classList.add("hidden");
          return;
        }
        root.classList.remove("hidden");

        const stage = flowStep(pageId);
        const meta = PAGE_META[pageId] || PAGE_META.dashboard;
        const actionConfig = {
          pipelines: {
            primary: hasPermission(PERMISSIONS.MODEL_RELEASE)
              ? primaryActionButtonHtml("注册流水线", "focusField('pipelineCode')")
              : primaryActionButtonHtml("刷新流水线", "loadPipelines()"),
            secondary: [hasPermission(PERMISSIONS.TASK_CREATE) ? actionButtonHtml("回到执行", "switchPage('tasks')") : ""],
          },
          "task-monitor": {
            primary: primaryActionButtonHtml("查询任务", "document.getElementById('btnTaskQuery').click()"),
            secondary: [actionButtonHtml(state.taskMonitorAuto ? "关闭自动刷新" : "开启自动刷新", "toggleTaskMonitorAuto()")],
          },
          audit: {
            primary: primaryActionButtonHtml("查询审计", "document.getElementById('btnAuditQuery').click()"),
            secondary: [actionButtonHtml("筛选动作", "focusField('auditAction')")],
          },
        }[pageId] || { primary: "", secondary: [] };

        writeOutput(
          "pageCommandBar",
          `<div class="command-bar">
            <div class="command-copy">
              <div class="command-kicker">${escapeHtml(stage.code)}</div>
              <h3 class="command-title">${escapeHtml(meta.title)}</h3>
              <p class="command-desc">${escapeHtml(meta.desc)}</p>
            </div>
            <div class="action-strip">${[actionConfig.primary, ...(actionConfig.secondary || [])].filter(Boolean).join("")}</div>
          </div>`
        );
      }

      function currentModelSelectionId() {
        return document.getElementById("modelId")?.value.trim() || state.models?.[0]?.id || "";
      }

      function currentModelRecord() {
        const modelId = currentModelSelectionId();
        return (state.models || []).find((row) => String(row.id) === String(modelId)) || state.models?.[0] || null;
      }

      function renderModelSummary() {
        const root = document.getElementById("modelSummary");
        if (!root) return;
        const rows = Array.isArray(state.models) ? state.models : [];
        const submitted = rows.filter((row) => String(row.status || "") === "SUBMITTED").length;
        const approved = rows.filter((row) => String(row.status || "") === "APPROVED").length;
        const released = rows.filter((row) => String(row.status || "") === "RELEASED").length;
        const selected = currentModelRecord();

        root.innerHTML = `
          <div class="metric"><div class="metric-label">提交中</div><div class="metric-value">${submitted}</div></div>
          <div class="metric"><div class="metric-label">已审批</div><div class="metric-value">${approved}</div></div>
          <div class="metric"><div class="metric-label">已发布</div><div class="metric-value">${released}</div></div>
          <div class="metric"><div class="metric-label">当前选择</div><div class="metric-value">${escapeHtml(selected ? safe(selected.model_code || selected.id).slice(0, 12) : "-")}</div></div>
        `;
      }

      function renderModelLifecycle() {
        const root = document.getElementById("modelLifecycle");
        if (!root) return;
        const selected = currentModelRecord();
        if (!selected) {
          renderEmpty("modelLifecycle", "暂无模型生命周期数据");
          return;
        }

        const status = String(selected.status || "");
        const activeIndex = status === "RELEASED" ? 3 : status === "APPROVED" ? 2 : 1;
        const stages = [
          { title: "提交", desc: "上传标准模型包。", tail: "输入：manifest + model.enc + signature" },
          { title: "审核", desc: "检查版本、任务类型和来源。", tail: "状态：SUBMITTED / APPROVED" },
          { title: "发布", desc: "发布到目标设备和租户。", tail: "输出：设备范围和租户范围" },
          { title: "使用", desc: "在任务中使用已发布模型。", tail: "关联：任务、结果、日志" },
        ];

        writeOutput(
          "modelLifecycle",
          `<div class="banner"><div class="banner-title">模型生命周期 · ${escapeHtml(safe(selected.model_code || selected.id))}</div><div class="banner-sub">当前状态 ${escapeHtml(status)}。</div></div>
          <div class="flow-grid">
            ${stages
              .map(
                (stage, index) => `<article class="flow-stage ${index <= activeIndex ? "active" : ""}">
                  <div class="flow-index">${index + 1}</div>
                  <div class="flow-title">${escapeHtml(stage.title)}</div>
                  <div class="flow-desc">${escapeHtml(stage.desc)}</div>
                  <div class="flow-tail">${escapeHtml(stage.tail)}</div>
                </article>`
              )
              .join("")}
          </div>`
        );
      }

      function timelineTagHtml(label, value, mono = false) {
        const content = mono ? `<span class="mono">${escapeHtml(safe(value))}</span>` : escapeHtml(safe(value));
        return `<span class="timeline-tag">${escapeHtml(label)}：${content}</span>`;
      }

      function renderModelVersionCompare() {
        const root = document.getElementById("modelVersionCompare");
        if (!root) return;

        const selected = currentModelRecord();
        if (!selected) {
          renderEmpty("modelVersionCompare", "当前模型暂无版本对比数据");
          return;
        }

        const siblings = (state.models || [])
          .filter((row) => String(row.model_code || "") === String(selected.model_code || ""))
          .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
        const currentIndex = siblings.findIndex((row) => String(row.id) === String(selected.id));
        const previous = currentIndex >= 0 ? siblings[currentIndex + 1] || null : null;
        const newer = currentIndex > 0 ? siblings[currentIndex - 1] || null : null;
        const releaseCount = Array.isArray(state.modelTimeline?.releases) ? state.modelTimeline.releases.length : 0;

        writeOutput(
          "modelVersionCompare",
          `<div class="banner"><div class="banner-title">版本对比</div><div class="banner-sub">用于判断当前版本是否应继续发布、回滚或进入下一轮优化。</div></div>
          <article class="compare-card">
            <div class="compare-head">
              <div>
                <div class="compare-title">${escapeHtml(safe(selected.model_code || selected.id))}</div>
                <div class="compare-desc">当前选中版本 ${escapeHtml(safe(selected.version || "-"))}，状态 ${escapeHtml(safe(selected.status || "-"))}，已记录发布批次 ${releaseCount} 次。</div>
              </div>
              ${statusTag(selected.status || "-")}
            </div>
            <div class="compare-grid">
              <section class="compare-cell">
                <div class="compare-kicker">当前版本</div>
                <h4>${escapeHtml(safe(selected.version || "-"))}</h4>
                <p>哈希 ${escapeHtml(safe(selected.model_hash || "-")).slice(0, 24)}${selected.model_hash ? "..." : ""}</p>
                ${kvGrid([
                  { label: "创建时间", value: formatTime(selected.created_at) },
                  { label: "发布状态", value: selected.status || "-" },
                ])}
              </section>
              <section class="compare-cell">
                <div class="compare-kicker">上一版本</div>
                <h4>${escapeHtml(safe(previous?.version || "无更早版本"))}</h4>
                <p>${previous ? `哈希 ${escapeHtml(safe(previous.model_hash)).slice(0, 24)}...` : "当前版本是该模型编码下的首个版本。"} </p>
                ${kvGrid([
                  { label: "创建时间", value: previous ? formatTime(previous.created_at) : "-" },
                  { label: "发布状态", value: previous?.status || "-" },
                ])}
              </section>
            </div>
            <div class="timeline-tags">
              <span class="timeline-tag">同编码版本数：${siblings.length}</span>
              <span class="timeline-tag">是否发生哈希变化：${previous ? (previous.model_hash !== selected.model_hash ? "是" : "否") : "首版"}</span>
              <span class="timeline-tag">是否存在更新版本：${newer ? "是" : "否"}</span>
            </div>
          </article>`
        );
      }

      function renderModelTimelinePanels(data = null) {
        const timelineRoot = document.getElementById("modelTimelinePanel");
        const releaseRoot = document.getElementById("modelReleaseBoard");
        if (!timelineRoot || !releaseRoot) return;

        const payload = data || state.modelTimeline;
        if (!payload?.model) {
          renderEmpty("modelTimelinePanel", "当前模型暂无审批时间线");
          renderEmpty("modelReleaseBoard", "当前模型暂无发布记录");
          return;
        }

        const model = payload.model || {};
        const timeline = Array.isArray(payload.timeline) ? payload.timeline : [];
        const releases = Array.isArray(payload.releases) ? payload.releases : [];
        const latestRelease = releases[0] || null;

        if (!timeline.length) {
          renderEmpty("modelTimelinePanel", "当前模型暂无审批时间线");
        } else {
          writeOutput(
            "modelTimelinePanel",
            `<div class="banner"><div class="banner-title">审批时间线</div><div class="banner-sub">查看当前模型的操作记录。</div></div>
            <div class="timeline-list">
              ${timeline
                .map((item) => {
                  const meta = item.meta || {};
                  const tags = [];
                  if (meta.version) tags.push(timelineTagHtml("版本", meta.version));
                  if (meta.task_type) tags.push(timelineTagHtml("任务", meta.task_type));
                  if (meta.release_id) tags.push(timelineTagHtml("发布ID", meta.release_id, true));
                  if (Array.isArray(meta.target_devices) && meta.target_devices.length) tags.push(timelineTagHtml("设备", meta.target_devices.join(" / ")));
                  if (Array.isArray(meta.target_buyers) && meta.target_buyers.length) tags.push(timelineTagHtml("客户", meta.target_buyers.join(" / ")));
                  return `<article class="timeline-item">
                    <div class="timeline-dot"></div>
                    <div class="timeline-head">
                      <div>
                        <div class="timeline-title">${escapeHtml(item.title || "-")}</div>
                        <div class="timeline-meta">${escapeHtml(formatTime(item.created_at))} · ${escapeHtml(safe(item.actor_username || "-"))}</div>
                      </div>
                      ${statusTag(item.status || "DONE")}
                    </div>
                    <div class="timeline-summary">${escapeHtml(safe(item.summary || "-"))}</div>
                    ${tags.length ? `<div class="timeline-tags">${tags.join("")}</div>` : ""}
                  </article>`;
                })
                .join("")}
            </div>`
          );
        }

        writeOutput(
          "modelReleaseBoard",
          `<div class="banner"><div class="banner-title">发布记录</div><div class="banner-sub">查看发布状态、设备范围和客户范围。</div></div>
          <div class="release-stack">
            <article class="release-hero">
              <div class="spotlight-kicker">发布范围</div>
              <h3>${escapeHtml(safe(model.model_code || model.id))}</h3>
              <p>当前状态 ${escapeHtml(safe(model.status || "-"))}，任务类型 ${escapeHtml(safe(model.task_type || "-"))}。${latestRelease ? "当前已有发布记录。" : "当前尚未发布。"} </p>
              <div class="release-pills">
                <span class="release-pill">版本 ${escapeHtml(safe(model.version || "-"))}</span>
                <span class="release-pill">发布次数 ${releases.length}</span>
                <span class="release-pill">签名状态 ${latestRelease ? "已生成" : "待生成"}</span>
              </div>
            </article>
            ${
              latestRelease
                ? `<div class="release-grid">
                    <article class="release-item">
                      <h4>最新发布</h4>
                      <p>发布时间 ${escapeHtml(formatTime(latestRelease.created_at))} · 发布人 ${escapeHtml(safe(latestRelease.released_by || "-"))}</p>
                      ${kvGrid([
                        { label: "发布ID", value: latestRelease.release_id || "-", mono: true },
                        { label: "状态", value: latestRelease.status || "-" },
                        { label: "设备数量", value: Array.isArray(latestRelease.target_devices) ? latestRelease.target_devices.length : 0 },
                        { label: "客户数量", value: Array.isArray(latestRelease.target_buyers) ? latestRelease.target_buyers.length : 0 },
                      ])}
                      <div class="release-pills">
                        ${(latestRelease.target_devices || []).map((item) => `<span class="release-pill">设备 ${escapeHtml(item)}</span>`).join("")}
                        ${(latestRelease.target_buyers || []).map((item) => `<span class="release-pill">客户 ${escapeHtml(item)}</span>`).join("")}
                      </div>
                    </article>
                    ${
                      releases.length > 1
                        ? `<article class="release-item">
                            <h4>历史发布批次</h4>
                            <p>查看最近批次记录。</p>
                            <div class="release-pills">
                              ${releases
                                .slice(0, 4)
                                .map(
                                  (item, index) =>
                                    `<span class="release-pill">#${index + 1} ${escapeHtml(formatTime(item.created_at))} · ${(item.target_devices || []).length} 设备 / ${(item.target_buyers || []).length} 客户</span>`
                                )
                                .join("")}
                            </div>
                          </article>`
                        : ""
                    }
                  </div>`
                : `<article class="release-item">
                    <h4>尚未发布</h4>
                    <p>当前模型还没有发布记录。</p>
                    <div class="action-strip">
                      ${hasPermission(PERMISSIONS.MODEL_APPROVE) ? actionButtonHtml("去发布", "focusField('modelId')") : ""}
                      ${hasPermission(PERMISSIONS.AUDIT_READ) ? actionButtonHtml("查看日志", "switchPage('audit')") : ""}
                    </div>
                  </article>`
            }
          </div>`
        );
      }

      async function loadModelTimeline(modelIdOverride = "") {
        const hasTimelinePanels =
          !!document.getElementById("modelVersionCompare") || !!document.getElementById("modelTimelinePanel") || !!document.getElementById("modelReleaseBoard");
        if (!hasTimelinePanels) {
          state.modelTimeline = null;
          return;
        }

        const modelId = modelIdOverride || currentModelSelectionId();
        if (!modelId || !hasPermission(PERMISSIONS.MODEL_VIEW)) {
          state.modelTimeline = null;
          renderModelVersionCompare();
          renderModelTimelinePanels(null);
          return;
        }

        setPanelLoading("modelVersionCompare", true);
        setPanelLoading("modelTimelinePanel", true);
        setPanelLoading("modelReleaseBoard", true);
        try {
          const data = await api(`/models/${encodeURIComponent(modelId)}/timeline`);
          state.modelTimeline = sanitizeForView(data, "modelListMaskTip");
          renderModelVersionCompare();
          renderModelTimelinePanels(state.modelTimeline);
        } catch (e) {
          state.modelTimeline = null;
          renderEmpty("modelVersionCompare", `版本对比加载失败：${e.message}`);
          renderEmpty("modelTimelinePanel", `审批时间线加载失败：${e.message}`);
          renderEmpty("modelReleaseBoard", `发布交付板加载失败：${e.message}`);
        } finally {
          document.getElementById("modelVersionCompare")?.classList.remove("loading");
          document.getElementById("modelTimelinePanel")?.classList.remove("loading");
          document.getElementById("modelReleaseBoard")?.classList.remove("loading");
        }
      }

      function setTheme(theme) {
        const t = theme === "dark" ? "dark" : "light";
        document.body.setAttribute("data-theme", t);
        localStorage.setItem("rv_theme", t);
      }

      function toggleTheme() {
        const current = document.body.getAttribute("data-theme") === "dark" ? "dark" : "light";
        setTheme(current === "dark" ? "light" : "dark");
      }

      function setButtonLoading(btn, loading, text = "处理中") {
        if (!btn) return;
        if (loading) {
          btn.dataset.origin = btn.textContent;
          btn.textContent = text;
          btn.classList.add("loading-btn");
          btn.disabled = true;
        } else {
          btn.textContent = btn.dataset.origin || btn.textContent;
          btn.classList.remove("loading-btn");
          btn.disabled = false;
        }
      }

      function setPanelLoading(id, loading) {
        const el = document.getElementById(id);
        if (!el) return;
        if (loading) {
          el.classList.add("loading");
          el.setAttribute("aria-busy", "true");
          el.innerHTML = `<div class="loading-copy">正在加载...</div>`;
        } else {
          el.classList.remove("loading");
          el.removeAttribute("aria-busy");
        }
      }

      function setFieldError(id, message) {
        const input = document.getElementById(id);
        if (!input) return;
        let err = document.getElementById(`${id}Err`);
        if (!err) {
          err = document.createElement("div");
          err.id = `${id}Err`;
          err.className = "field-error hidden";
          input.insertAdjacentElement("afterend", err);
        }
        if (message) {
          input.classList.add("input-invalid");
          err.textContent = message;
          err.classList.remove("hidden");
        } else {
          input.classList.remove("input-invalid");
          err.textContent = "";
          err.classList.add("hidden");
        }
      }

      function clearFieldError(id) {
        setFieldError(id, "");
      }

      function validateRequiredField(id, message) {
        const input = document.getElementById(id);
        if (!input) return true;
        const isFile = input.type === "file";
        const value = isFile ? input.files?.length : String(input.value || "").trim();
        const valid = !!value;
        setFieldError(id, valid ? "" : message);
        if (!valid) focusField(id);
        return valid;
      }

      function escapeHtml(text) {
        return String(text ?? "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/\"/g, "&quot;")
          .replace(/'/g, "&#39;");
      }

      function safe(v) {
        if (v === null || v === undefined || v === "") return "-";
        return String(v);
      }

      function formatTime(v) {
        if (!v) return "-";
        const d = new Date(v);
        if (Number.isNaN(d.getTime())) return safe(v);
        return d.toLocaleString("zh-CN", { hour12: false });
      }

      function taskTypeLabel(v) {
        if (!v) return "-";
        const value = String(v);
        if (value === "car_number_ocr") return "车号识别";
        if (value === "bolt_missing_detect") return "螺栓缺失";
        if (value === "pipeline_orchestrated") return "流水线编排";
        return value;
      }

      function assetPurposeLabel(v) {
        const value = String(v || "");
        if (value === "training") return "训练数据";
        if (value === "finetune") return "微调数据";
        if (value === "validation") return "测试/验收数据";
        if (value === "inference") return "推理数据";
        return value || "-";
      }

      function modelSourceTypeLabel(v) {
        const value = String(v || "");
        if (value === "initial_algorithm") return "初始算法";
        if (value === "pretrained_seed") return "预训练模型";
        if (value === "finetuned_candidate") return "微调候选";
        if (value === "delivery_candidate") return "交付候选";
        return value || "-";
      }

      function deliveryModeLabel(v) {
        const value = String(v || "");
        if (value === "api") return "模型 API";
        if (value === "local_key") return "本地解密";
        if (value === "hybrid") return "API + 本地解密";
        return value || "-";
      }

      function authorizationModeLabel(v) {
        const value = String(v || "");
        if (value === "api_token") return "API 令牌";
        if (value === "device_key") return "设备密钥";
        if (value === "hybrid") return "双通道授权";
        return value || "-";
      }

      function modelTypeLabel(v) {
        const value = String(v || "");
        if (value === "router") return "主路由模型";
        if (value === "expert") return "专家模型";
        return value || "-";
      }

      function updateModelTypeHints() {
        const type = document.getElementById("modelType")?.value || "expert";
        const pluginInput = document.getElementById("modelPluginName");
        const outputsInput = document.getElementById("modelOutputsJson");
        if (!outputsInput) return;
        const currentOutput = outputsInput.value.trim();
        const routerOutput = '{"scene_id":"string","scene_score":"float","tasks":"list[string]","task_scores":"list[float]"}';
        const expertOutput =
          '{"predictions":["label","score","bbox","mask","text","attributes"],"artifacts":["preview_frame","roi_crop","heatmap","feature_summary"],"metrics":["duration_ms","gpu_mem_mb","version","calibration"]}';
        if (type === "router") {
          if (!pluginInput?.value.trim()) pluginInput.value = "heuristic_router";
          if (!currentOutput || currentOutput === expertOutput) outputsInput.value = routerOutput;
          return;
        }
        if (currentOutput === routerOutput) outputsInput.value = expertOutput;
      }

      function pipelineDisplayName(pipeline) {
        return pipeline?.name || pipeline?.pipeline_code || pipeline?.id || "-";
      }

      function parseJsonInput(id, label) {
        const raw = document.getElementById(id)?.value || "";
        clearFieldError(id);
        if (!raw.trim()) return {};
        try {
          return JSON.parse(raw);
        } catch {
          setFieldError(id, `${label} JSON 格式错误`);
          focusField(id);
          throw new Error(`${label} JSON 格式错误`);
        }
      }

      function parseCommaList(value) {
        return String(value || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean);
      }

      function statusClass(v) {
        const s = String(v || "").toUpperCase();
        if (["SUCCEEDED", "APPROVED", "RELEASED", "INFO", "OK", "ACTIVE"].includes(s)) return "ok";
        if (["FAILED", "ERROR", "ALERT", "DENIED"].includes(s)) return "err";
        if (["PENDING", "DISPATCHED", "SUBMITTED", "WARN"].includes(s)) return "warn";
        return "neutral";
      }

      function statusTag(v) {
        return `<span class="status ${statusClass(v)}">${escapeHtml(safe(v))}</span>`;
      }

      function maskBySensitivity(data, parentL3 = false) {
        let masked = false;
        if (Array.isArray(data)) {
          const out = data.map((x) => {
            const inner = maskBySensitivity(x, parentL3);
            masked = masked || inner.masked;
            return inner.value;
          });
          return { value: out, masked };
        }
        if (!data || typeof data !== "object") return { value: data, masked: false };

        const ownL3 = parentL3 || data.sensitivity_level === "L3" || data.sensitivityLevel === "L3";
        const out = {};
        for (const [key, value] of Object.entries(data)) {
          if (ownL3 && (SENSITIVE_FIELDS.has(key) || /(uri|path|raw|frame|video)/i.test(key))) {
            out[key] = "***";
            masked = true;
            continue;
          }
          const inner = maskBySensitivity(value, ownL3);
          out[key] = inner.value;
          masked = masked || inner.masked;
        }
        return { value: out, masked };
      }

      function sanitizeForView(data, tipId) {
        let payload = data;
        let masked = false;
        if (!hasPermission(PERMISSIONS.DATA_L3_READ)) {
          const m = maskBySensitivity(data);
          payload = m.value;
          masked = m.masked;
        }
        const tip = document.getElementById(tipId);
        if (tip) tip.classList.toggle("hidden", !masked);
        return payload;
      }

      function kvGrid(fields) {
        if (!fields || !fields.length) return "";
        return `<div class="kv-grid">${fields
          .map((f) => {
            const value = f.mono ? `<span class="mono">${escapeHtml(safe(f.value))}</span>` : escapeHtml(safe(f.value));
            return `<div class="kv-item"><div class="kv-label">${escapeHtml(f.label)}</div><div class="kv-value">${value}</div></div>`;
          })
          .join("")}</div>`;
      }

      function writeOutput(id, html) {
        const el = document.getElementById(id);
        if (!el) return;
        el.classList.remove("loading");
        el.removeAttribute("aria-busy");
        el.innerHTML = html;
      }

      function renderStatePanel(id, { tone = "empty", title = "", message = "", tip = "", actions = [] }) {
        const actionHtml = stateActionsHtml(actions);
        const toneClass = tone === "err" ? " is-error" : tone === "warn" ? " is-warn" : "";
        writeOutput(
          id,
          `<div class="empty state-panel${toneClass}">
            <div class="empty-illus"></div>
            ${title ? `<div class="empty-title">${escapeHtml(title)}</div>` : ""}
            ${message ? `<div class="empty-desc">${escapeHtml(message)}</div>` : ""}
            ${tip ? `<div class="empty-tip">${escapeHtml(tip)}</div>` : ""}
            ${actionHtml ? `<div class="empty-actions">${actionHtml}</div>` : ""}
          </div>`
        );
      }

      function renderEmpty(id, message, title = "", actions = [], tip = "") {
        renderStatePanel(id, { title, message, tip, actions });
      }

      function renderErrorState(id, title, message, actions = [], tip = "") {
        renderStatePanel(id, { tone: "err", title, message, tip, actions });
      }

      function formatDetailValue(value) {
        if (value === null || value === undefined || value === "") return "-";
        if (Array.isArray(value)) {
          if (!value.length) return "-";
          if (value.every((item) => typeof item !== "object")) return value.join(" / ");
          return `${value.length} 项`;
        }
        if (typeof value === "object") return "[对象]";
        return String(value);
      }

      function fieldsFromObject(obj, keys = []) {
        return keys
          .filter((key) => key in (obj || {}))
          .map((key) => ({
            label: key,
            value: formatDetailValue(obj[key]),
            mono: /(id|hash|version|checksum|code|ip|signature)/i.test(key),
          }));
      }

      function renderStepFlow(status) {
        const current = String(status || "").toUpperCase();
        const steps = [
          { key: "PENDING", title: "已创建", desc: "任务进入平台队列" },
          { key: "DISPATCHED", title: "已下发", desc: "任务已下发到边缘端" },
          { key: "RUNNING", title: "执行中", desc: "边缘端抽帧与推理" },
          { key: "SUCCEEDED", title: "已完成", desc: "结果与截图回传" },
        ];
        const activeIndex = (() => {
          if (["FAILED", "ERROR"].includes(current)) return 2;
          const idx = steps.findIndex((step) => step.key === current);
          return idx >= 0 ? idx : 0;
        })();

        return `<div class="step-flow">${steps
          .map(
            (step, index) => `<div class="step-node ${index <= activeIndex ? "active" : ""}">
              <div class="step-index">${index + 1}</div>
              <div class="step-title">${escapeHtml(step.title)}</div>
              <div class="step-desc">${escapeHtml(step.desc)}</div>
            </div>`
          )
          .join("")}</div>`;
      }

      function openDrawer({ title, subtitle = "", body = "" }) {
        const root = document.getElementById("detailDrawer");
        state.drawerLastFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        document.getElementById("drawerTitle").textContent = title || "详情";
        document.getElementById("drawerSubtitle").textContent = subtitle || "-";
        document.getElementById("drawerBody").innerHTML = body || `<div class="drawer-section"><div class="drawer-note">暂无内容</div></div>`;
        root.classList.remove("hidden");
        root.setAttribute("aria-hidden", "false");
        document.body.classList.add("drawer-open");
        window.setTimeout(() => {
          document.getElementById("drawerCloseBtn")?.focus();
        }, 0);
      }

      function closeDrawer() {
        const root = document.getElementById("detailDrawer");
        root.classList.add("hidden");
        root.setAttribute("aria-hidden", "true");
        document.body.classList.remove("drawer-open");
        if (state.drawerLastFocus && typeof state.drawerLastFocus.focus === "function") {
          state.drawerLastFocus.focus();
        }
        state.drawerLastFocus = null;
      }

      function showModelDetail(modelId) {
        const model = (state.models || []).find((item) => String(item.id) === String(modelId));
        if (!model) {
          toast("未找到模型详情", "warn");
          return;
        }
        const payload = sanitizeForView(model, "modelListMaskTip");
        const meta = payload.platform_meta || {};
        openDrawer({
          title: `模型详情 · ${safe(payload.model_code)}`,
          subtitle: `模型ID ${safe(payload.id)}`,
          body: `
            <section class="drawer-section">
              <h4>核心信息</h4>
              ${kvGrid(
                fieldsFromObject(payload, [
                  "id",
                  "model_code",
                  "version",
                  "model_type",
                  "task_type",
                  "runtime",
                  "plugin_name",
                  "gpu_mem_mb",
                  "latency_ms",
                  "status",
                  "model_hash",
                  "created_at",
                  "created_by",
                ])
              )}
            </section>
            <section class="drawer-section">
              <h4>训练与交付信息</h4>
              ${kvGrid([
                { label: "来源类型", value: modelSourceTypeLabel(meta.model_source_type) },
                { label: "基线模型", value: meta.base_model_ref || "-" },
                { label: "微调轮次", value: meta.training_round || "-" },
                { label: "训练数据批次", value: meta.dataset_label || "-" },
                { label: "训练说明", value: meta.training_summary || "-" },
              ])}
            </section>
            <section class="drawer-section">
              <h4>追溯信息</h4>
              <div class="drawer-note">模型 ID 和模型哈希可用于核对版本来源。</div>
            </section>`,
        });
      }

      function showTaskDetail(taskId) {
        const task =
          (state.tasks || []).find((item) => String(item.id) === String(taskId)) ||
          (state.currentTask && String(state.currentTask.id) === String(taskId) ? state.currentTask : null);
        if (!task) {
          toast("未找到任务详情", "warn");
          return;
        }
        const payload = sanitizeForView(task, "taskStatusOutMaskTip");
        openDrawer({
          title: `任务详情 · ${safe(payload.task_type)}`,
          subtitle: `任务ID ${safe(payload.id)}`,
          body: `
            <section class="drawer-section">
              <h4>任务进度</h4>
              ${renderStepFlow(payload.status)}
            </section>
            <section class="drawer-section">
              <h4>任务摘要</h4>
              ${kvGrid(
                fieldsFromObject(payload, [
                  "id",
                  "status",
                  "task_type",
                  "model_id",
                  "pipeline_id",
                  "asset_id",
                  "device_code",
                  "result_count",
                  "created_at",
                  "started_at",
                  "finished_at",
                  "error_message",
                ])
              )}
              ${payload.run ? `<div class="drawer-note">输入哈希 ${escapeHtml(safe(payload.run.input_hash || "-"))} / 审计哈希 ${escapeHtml(safe(payload.run.audit_hash || "-"))}</div>` : ""}
            </section>`,
        });
      }

      function showResultDetail(resultId) {
        const row = (state.resultRows || []).find((item) => String(item.id) === String(resultId));
        if (!row) {
          toast("未找到结果详情", "warn");
          return;
        }
        const payload = sanitizeForView(row, "resultOutMaskTip");
        const fields = resultFields(payload.result_json || {});
        openDrawer({
          title: `结果详情 · ${safe(payload.alert_level)}`,
          subtitle: `结果ID ${safe(payload.id)}`,
          body: `
            <section class="drawer-section">
              <h4>结果摘要</h4>
              ${kvGrid(
                fieldsFromObject(payload, ["id", "task_id", "model_id", "model_hash", "alert_level", "duration_ms", "created_at"])
              )}
            </section>
            <section class="drawer-section">
              <h4>业务输出</h4>
              ${kvGrid(fields)}
              ${
                payload.run
                  ? `<div class="drawer-note">运行版本 ${escapeHtml(safe(payload.run.pipeline_version || "-"))} / 审计哈希 ${escapeHtml(
                      safe(payload.run.audit_hash || "-")
                    )}</div>`
                  : ""
              }
            </section>`,
        });
      }

      function showAuditDetail(index) {
        const row = (state.visibleAuditRows || [])[index];
        if (!row) {
          toast("未找到审计详情", "warn");
          return;
        }
        const payload = sanitizeForView(row, "auditOutMaskTip");
        const detail = payload.detail && typeof payload.detail === "object" ? payload.detail : {};
        openDrawer({
          title: `审计详情 · ${safe(payload.action)}`,
          subtitle: `操作人 ${safe(payload.actor_username)} · ${formatTime(payload.created_at)}`,
          body: `
            <section class="drawer-section">
              <h4>日志摘要</h4>
              ${kvGrid(
                fieldsFromObject(payload, [
                  "created_at",
                  "actor_username",
                  "actor_role",
                  "action",
                  "resource_type",
                  "resource_id",
                  "ip_address",
                ])
              )}
            </section>
            <section class="drawer-section">
              <h4>请求详情</h4>
              ${Object.keys(detail).length ? kvGrid(fieldsFromObject(detail, Object.keys(detail).slice(0, 12))) : `<div class="drawer-note">无更多明细字段</div>`}
            </section>`,
        });
      }

      function permissionsFromUser(user) {
        if (Array.isArray(user?.permissions)) return new Set(user.permissions);
        const caps = user?.capabilities;
        const out = new Set();
        if (!caps || typeof caps !== "object") return out;
        if (caps.model_view) out.add(PERMISSIONS.MODEL_VIEW);
        if (caps.model_submit) out.add(PERMISSIONS.MODEL_SUBMIT);
        if (caps.model_approve) out.add(PERMISSIONS.MODEL_APPROVE);
        if (caps.model_release) out.add(PERMISSIONS.MODEL_RELEASE);
        if (caps.asset_upload) out.add(PERMISSIONS.ASSET_UPLOAD);
        if (caps.task_create) out.add(PERMISSIONS.TASK_CREATE);
        if (caps.result_read) out.add(PERMISSIONS.RESULT_READ);
        if (caps.audit_read) out.add(PERMISSIONS.AUDIT_READ);
        return out;
      }

      function allowedPages() {
        return PAGES.filter((p) => hasPermission(p.perm));
      }

      function currentHashPage() {
        const raw = (window.location.hash || "").replace(/^#\/?/, "").trim();
        if (!raw) return "dashboard";
        return raw;
      }

      function syncHash(pageId) {
        const next = `#/${pageId}`;
        if (window.location.hash !== next) {
          window.location.hash = next;
        }
      }

      function updateContentChrome(pageId) {
        const meta = PAGE_META[pageId] || PAGE_META.dashboard;
        const roleMap = {
          platform_admin: "平台侧",
          platform_auditor: "平台审计",
          supplier_engineer: "供应商侧",
          buyer_operator: "客户侧",
          buyer_auditor: "客户审计",
        };
        const firstRole = state.user?.roles?.[0] || "";
        const roleLabel = roleMap[firstRole] || "控制台";

        const breadcrumbRole = document.getElementById("breadcrumbRole");
        const breadcrumbPage = document.getElementById("breadcrumbPage");
        const contentTitle = document.getElementById("contentTitle");
        const contentDesc = document.getElementById("contentDesc");

        if (breadcrumbRole) breadcrumbRole.textContent = roleLabel;
        if (breadcrumbPage) breadcrumbPage.textContent = meta.title;
        if (contentTitle) contentTitle.textContent = meta.title;
        if (contentDesc) contentDesc.textContent = meta.desc;
      }

      function switchPage(pageId, options = {}) {
        const { updateHash = true } = options;
        const allowed = allowedPages().map((x) => x.id);
        if (!allowed.includes(pageId)) {
          if (state.user && pageId && allowed[0] && pageId !== allowed[0]) {
            toast("当前角色没有该页面权限", "warn");
          }
          pageId = allowed[0] || "dashboard";
        }
        if (state.page === "task-monitor" && pageId !== "task-monitor" && state.taskMonitorAuto) {
          stopTaskMonitorAuto();
        }
        state.page = pageId;

        document.querySelectorAll(".page").forEach((el) => el.classList.remove("active"));
        document.querySelectorAll(".page").forEach((el) => el.setAttribute("aria-hidden", "true"));
        const page = document.getElementById(`page-${pageId}`);
        if (page) {
          page.classList.add("active");
          page.setAttribute("aria-hidden", "false");
        }

        document.querySelectorAll(".nav-btn, .minimal-nav-btn").forEach((el) => {
          el.classList.toggle("active", el.dataset.page === pageId);
          el.setAttribute("aria-current", el.dataset.page === pageId ? "page" : "false");
        });

        document.body.classList.toggle(
          "assets-minimal-page",
          pageId === "dashboard" ||
            pageId === "models" ||
            pageId === "pipelines" ||
            pageId === "assets" ||
            pageId === "tasks" ||
            pageId === "task-monitor" ||
            pageId === "results" ||
            pageId === "audit"
        );

        updateContentChrome(pageId);
        renderSidebarContext(pageId);
        renderPageCommandBar(pageId);
        if (updateHash) syncHash(pageId);

        if (pageId === "dashboard") refreshDashboard();
        if (pageId === "models" || pageId === "pipelines") loadModels();
        if (pageId === "pipelines" || pageId === "tasks") loadPipelines();
        if (pageId === "task-monitor") updateTaskMonitorBadge();
      }

      function buildNav() {
        const nav = document.getElementById("navList");
        if (nav) nav.innerHTML = "";

        if (nav) {
          nav.innerHTML = NAV_GROUPS.map((group) => {
            const pages = group.pages.filter((pageId) => hasPermission(pageConfig(pageId)?.perm));
            if (!pages.length) return "";
            return `<section class="nav-group">
              <div class="nav-group-title">${escapeHtml(group.title)}</div>
              ${pages
                .map((pageId) => {
                  const page = pageConfig(pageId);
                  const step = flowStep(pageId);
                  return `<button class="nav-btn" type="button" data-page="${pageId}" aria-current="false" aria-label="${escapeHtml(page.label)}">
                    <span class="nav-btn-code">${escapeHtml(step.code)}</span>
                    <span class="nav-btn-copy">
                      <span class="nav-btn-title">${escapeHtml(page.label)}</span>
                      <span class="nav-btn-desc">${escapeHtml(step.desc)}</span>
                    </span>
                  </button>`;
                })
                .join("")}
            </section>`;
          }).join("");
          nav.querySelectorAll(".nav-btn").forEach((btn) => {
            btn.onclick = () => switchPage(btn.dataset.page, { updateHash: true });
          });
        }
        const target = currentHashPage() || state.page;
        switchPage(target, { updateHash: !window.location.hash });
      }

      function renderStarterStates() {
        const canSubmitModel = hasPermission(PERMISSIONS.MODEL_SUBMIT);
        const canReleasePipeline = hasPermission(PERMISSIONS.MODEL_RELEASE);

        renderEmpty(
          "modelOps",
          canSubmitModel ? "提交成功后会返回模型 ID、版本和当前状态。" : "输入模型 ID 后可以查看审批和发布结果。",
          canSubmitModel ? "先提交一个模型包" : "先定位一个模型",
          [
            canSubmitModel ? { label: "选择模型包", action: "focusField('modelPackage')", primary: true } : { label: "输入模型ID", action: "focusField('modelId')", primary: true },
            { label: "刷新模型列表", action: "loadModels()" },
          ],
          canSubmitModel ? "没有历史数据时，先提交一版候选模型。" : "当前角色主要用于查看模型状态。"
        );

        renderEmpty(
          "modelList",
          "首次进入先刷新一次，确认当前账号能看到哪些模型。",
          "模型列表还没有加载",
          [
            { label: "刷新模型列表", action: "loadModels()", primary: true },
            canSubmitModel ? { label: "提交模型包", action: "focusField('modelPackage')" } : null,
          ]
        );

        renderEmpty(
          "pipelineOps",
          canReleasePipeline ? "注册后可以继续发布给设备和客户。" : "当前角色只能查看已可见流水线。",
          canReleasePipeline ? "先注册一条流水线" : "先查看可用流水线",
          [
            canReleasePipeline ? { label: "填写流水线编码", action: "focusField('pipelineCode')", primary: true } : { label: "刷新流水线", action: "loadPipelines()", primary: true },
            canReleasePipeline ? { label: "刷新流水线", action: "loadPipelines()" } : null,
          ],
          canReleasePipeline ? "没有可用流水线时，先选择主路由和专家映射。" : ""
        );

        renderEmpty(
          "pipelineList",
          "刷新后会显示当前设备和账号可调用的流水线。",
          "流水线列表还没有加载",
          [
            { label: "刷新流水线", action: "loadPipelines()", primary: true },
            canReleasePipeline ? { label: "新建流水线", action: "focusField('pipelineCode')" } : null,
          ]
        );
      }

      function clampPage(page, totalPages) {
        if (totalPages <= 0) return 1;
        return Math.max(1, Math.min(page, totalPages));
      }

      function paginateRows(rows, page, pageSize) {
        const safeSize = Math.max(1, Number(pageSize || 10));
        const total = rows.length;
        const totalPages = Math.max(1, Math.ceil(total / safeSize));
        const current = clampPage(page, totalPages);
        const start = (current - 1) * safeSize;
        const sliced = rows.slice(start, start + safeSize);
        return { rows: sliced, total, totalPages, current, pageSize: safeSize };
      }

      function applyRoleUI() {
        document.getElementById("userBadge").textContent = `用户：${state.user?.username || "-"}`;
        document.getElementById("roleBadge").textContent = `角色：${roleText(state.user)}`;

        const canSubmit = hasPermission(PERMISSIONS.MODEL_SUBMIT);
        const canApprove = hasPermission(PERMISSIONS.MODEL_APPROVE);
        const canRelease = hasPermission(PERMISSIONS.MODEL_RELEASE);

        document.getElementById("modelSubmitCard").classList.toggle("hidden", !canSubmit);
        document.getElementById("modelReleaseCard").classList.toggle("hidden", !(canApprove || canRelease));
        document.getElementById("modelReadonlyCard").classList.toggle("hidden", canSubmit || canApprove || canRelease);
        document.getElementById("pipelineRegisterCard")?.classList.toggle("hidden", !canRelease);
        document.getElementById("pipelineReleaseCard")?.classList.toggle("hidden", !canRelease);
        document.getElementById("pipelineReadonlyCard")?.classList.toggle("hidden", !!canRelease);

        const healthBadge = document.getElementById("healthBadge");
        healthBadge.textContent = "系统就绪";
        updateContentChrome(state.page);
        renderStarterStates();
      }

      async function checkHealth() {
        try {
          const data = await fetch(`${API_BASE}/health`).then((r) => r.json());
          document.getElementById("healthBadge").textContent = data.status === "ok" ? "系统健康：正常" : "系统健康：异常";
        } catch {
          document.getElementById("healthBadge").textContent = "系统健康：异常";
        }
      }

      async function login(button) {
        setButtonLoading(button, true, "登录中");
        try {
          const username = document.getElementById("username").value.trim();
          const password = document.getElementById("password").value;
          if (!username) {
            setFieldError("username", "请输入账号");
            throw new Error("请输入账号");
          }
          if (!password) {
            setFieldError("password", "请输入密码");
            throw new Error("请输入密码");
          }

          const loginResp = await api("/auth/login", {
            method: "POST",
            body: JSON.stringify({ username, password }),
          });
          state.token = loginResp.access_token;
          localStorage.setItem("rv_token", state.token);
          state.user = await api("/users/me");
          if (!Array.isArray(state.user.permissions) && Array.isArray(loginResp.permissions)) {
            state.user.permissions = loginResp.permissions;
          }
          state.permissions = permissionsFromUser(state.user);

          document.getElementById("loginStatus").textContent = `登录成功：${state.user.username}`;
          document.getElementById("loginView").classList.add("hidden");
          document.getElementById("mainView").classList.remove("hidden");
          applyRoleUI();
          buildNav();
          await checkHealth();
          await refreshDashboard();
          toast("登录成功", "ok");
        } catch (e) {
          document.getElementById("loginStatus").textContent = `登录失败：${e.message}`;
          toast(`登录失败：${e.message}`, "err");
        } finally {
          setButtonLoading(button, false);
        }
      }

      function logout() {
        stopTaskMonitorAuto();
        state.token = "";
        state.user = null;
        state.permissions = new Set();
        state.models = [];
        state.pipelines = [];
        state.tasks = [];
        state.currentTask = null;
        state.resultRows = [];
        state.visibleAuditRows = [];
        state.lastAssetId = "";
        state.lastTaskId = "";
        localStorage.removeItem("rv_token");
        history.replaceState(null, "", window.location.pathname + window.location.search);
        closeDrawer();

        document.getElementById("mainView").classList.add("hidden");
        document.getElementById("loginView").classList.remove("hidden");
        document.getElementById("loginStatus").textContent = "已退出登录";
        toast("已退出登录");
      }

      function selectModelForTask(modelId) {
        const mode = document.getElementById("schedulerMode");
        if (mode) mode.value = "manual";
        document.getElementById("taskModelId").value = modelId;
        document.getElementById("modelId").value = modelId;
        updateTaskSchedulerMode();
        renderModelSummary();
        renderModelLifecycle();
        renderModelVersionCompare();
        loadModelTimeline(modelId);
        toast("已回填模型ID到任务页");
      }

      function syncTaskIdInputs(taskId) {
        ["monitorTaskId", "resultTaskId"].forEach((id) => {
          const el = document.getElementById(id);
          if (el) el.value = taskId || "";
        });
      }

      function focusGlobalSearch() {
        if (!state.user) return;
        const input = document.getElementById("globalSearch");
        if (!input) return;
        input.focus();
        input.select();
      }

      function performGlobalSearch() {
        const input = document.getElementById("globalSearch");
        const keyword = input?.value.trim();
        if (!keyword) return;

        const normalized = keyword.toLowerCase();
        const page = PAGES.find((p) => p.id === normalized || p.label === keyword);
        if (page && hasPermission(page.perm)) {
          switchPage(page.id);
          toast(`已跳转到${page.label}`);
          return;
        }

        const modelMatch = (state.models || []).find(
          (x) => String(x.id).toLowerCase().includes(normalized) || String(x.model_code || "").toLowerCase().includes(normalized)
        );
        if (modelMatch) {
          selectModelForTask(modelMatch.id);
          switchPage(hasPermission(PERMISSIONS.MODEL_VIEW) ? "models" : "tasks");
          toast("已定位模型并回填模型ID");
          return;
        }

        const pipelineMatch = (state.pipelines || []).find(
          (x) =>
            String(x.id).toLowerCase().includes(normalized) ||
            String(x.pipeline_code || "").toLowerCase().includes(normalized) ||
            String(x.name || "").toLowerCase().includes(normalized)
        );
        if (pipelineMatch) {
          selectPipelineForTask(pipelineMatch.id);
          switchPage(hasPermission(PERMISSIONS.MODEL_VIEW) ? "pipelines" : "tasks");
          toast("已定位流水线并回填到任务页");
          return;
        }

        const taskMatch = (state.tasks || []).find((x) => String(x.id).toLowerCase().includes(normalized));
        if (taskMatch) {
          syncTaskIdInputs(taskMatch.id);
          state.lastTaskId = taskMatch.id;
          switchPage("task-monitor");
          toast("已定位任务并回填到任务监控页");
          return;
        }

        if (state.lastAssetId && state.lastAssetId.toLowerCase().includes(normalized)) {
          document.getElementById("assetId").value = state.lastAssetId;
          switchPage("tasks");
          toast("已定位最近上传资产");
          return;
        }

        const knownAuditActions = [
          "model_release",
          "model_download",
          "result_export",
          "task_create",
          "asset_upload",
          "pipeline_register",
          "pipeline_release",
          "orchestrator_run",
          "review_queue_enqueue",
        ];
        const auditMatch = knownAuditActions.find((x) => x.includes(normalized));
        if (auditMatch && hasPermission(PERMISSIONS.AUDIT_READ)) {
          document.getElementById("auditAction").value = auditMatch.toUpperCase();
          switchPage("audit");
          toast("已带入审计动作筛选");
          return;
        }

        toast("未命中模型、任务、资产或页面", "warn");
      }

      function attachGlobalShortcuts() {
        const input = document.getElementById("globalSearch");
        input?.addEventListener("keydown", (event) => {
          if (event.key === "Enter") {
            performGlobalSearch();
          }
        });

        window.addEventListener("keydown", (event) => {
          if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
            event.preventDefault();
            focusGlobalSearch();
          }
          if (event.key === "Tab") {
            const drawer = document.getElementById("detailDrawer");
            if (!drawer?.classList.contains("hidden")) {
              const focusables = drawer.querySelectorAll(
                'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
              );
              if (focusables.length) {
                const first = focusables[0];
                const last = focusables[focusables.length - 1];
                if (event.shiftKey && document.activeElement === first) {
                  event.preventDefault();
                  last.focus();
                } else if (!event.shiftKey && document.activeElement === last) {
                  event.preventDefault();
                  first.focus();
                }
              }
            }
          }
          if (event.key === "Escape") {
            closeDrawer();
          }
        });

        window.addEventListener("hashchange", () => {
          if (!state.user) return;
          switchPage(currentHashPage(), { updateHash: false });
        });
      }

      function attachPageControls() {
        const modelControls = ["modelSearch", "modelStatusFilter", "modelSort", "modelPageSize"];
        modelControls.forEach((id) => {
          document.getElementById(id)?.addEventListener("input", () => {
            state.modelPage = 1;
            renderModelList(state.models);
          });
          document.getElementById(id)?.addEventListener("change", () => {
            state.modelPage = 1;
            renderModelList(state.models);
          });
        });

        document.getElementById("modelPrevBtn")?.addEventListener("click", () => {
          state.modelPage = Math.max(1, state.modelPage - 1);
          renderModelList(state.models);
        });
        document.getElementById("modelNextBtn")?.addEventListener("click", () => {
          state.modelPage += 1;
          renderModelList(state.models);
        });

        document.getElementById("modelId")?.addEventListener("input", () => {
          renderModelSummary();
          renderModelLifecycle();
          renderModelVersionCompare();
          loadModelTimeline();
        });

        ["pipelineSearch", "pipelineStatusFilter"].forEach((id) => {
          document.getElementById(id)?.addEventListener("input", () => renderPipelineList(state.pipelines));
          document.getElementById(id)?.addEventListener("change", () => renderPipelineList(state.pipelines));
        });

        document.getElementById("deviceCode")?.addEventListener("change", () => {
          loadPipelines();
        });
        document.getElementById("modelType")?.addEventListener("change", updateModelTypeHints);

      }

      function renderModelOps(data, kind = "ok") {
        const payload = sanitizeForView(data, "modelOpsMaskTip");
        const meta = payload.platform_meta || {};
        const fields = [
          { label: "模型ID", value: payload.model_id || payload.id || "-", mono: true },
          { label: "版本", value: payload.version || "-" },
          { label: "发布ID", value: payload.release_id || "-", mono: true },
          { label: "状态", value: payload.status || "-" },
          payload.model_type ? { label: "模型类型", value: modelTypeLabel(payload.model_type) } : null,
          payload.task_type ? { label: "任务类型", value: taskTypeLabel(payload.task_type) } : null,
          payload.runtime ? { label: "运行时", value: payload.runtime } : null,
          payload.plugin_name ? { label: "插件标识", value: payload.plugin_name } : null,
          payload.gpu_mem_mb ? { label: "显存需求(MB)", value: payload.gpu_mem_mb } : null,
          payload.latency_ms ? { label: "基线耗时(ms)", value: payload.latency_ms } : null,
          meta.model_source_type ? { label: "来源类型", value: modelSourceTypeLabel(meta.model_source_type) } : null,
          meta.training_round ? { label: "微调轮次", value: meta.training_round } : null,
          meta.dataset_label ? { label: "训练数据批次", value: meta.dataset_label } : null,
          payload.validation_result ? { label: "验证结论", value: payload.validation_result } : null,
          payload.validation_summary ? { label: "验证摘要", value: payload.validation_summary } : null,
          payload.delivery_mode ? { label: "交付方式", value: deliveryModeLabel(payload.delivery_mode) } : null,
          payload.authorization_mode ? { label: "授权方式", value: authorizationModeLabel(payload.authorization_mode) } : null,
          payload.api_access_key_preview ? { label: "API 密钥", value: payload.api_access_key_preview, mono: true } : null,
          payload.local_key_label ? { label: "本地解密密钥", value: payload.local_key_label } : null,
        ].filter((x) => x.value !== "-");
        const modelId = payload.model_id || payload.id || "";
        const actionStrip =
          kind === "ok"
            ? `<div class="action-strip">
                ${actionButtonHtml("刷新模型列表", "loadModels()")}
                ${modelId ? actionButtonHtml("查看详情", `showModelDetail('${escapeHtml(safe(modelId))}')`) : ""}
                ${modelId && hasPermission(PERMISSIONS.TASK_CREATE) ? actionButtonHtml("用于创建任务", `selectModelForTask('${escapeHtml(safe(modelId))}'); switchPage('tasks')`) : ""}
              </div>`
            : "";

        if (kind === "err") {
          const msg = payload.error || payload.detail || payload.status || payload.message || "操作失败";
          writeOutput(
            "modelOps",
            `<div class="banner err"><div class="banner-title">模型操作失败</div><div class="banner-sub">${escapeHtml(safe(msg))}</div></div>`
          );
          return;
        }

        writeOutput("modelOps", `${kvGrid(fields)}${actionStrip}`);
      }

      function renderModelList(data) {
        const rows = sanitizeForView(Array.isArray(data) ? data : [], "modelListMaskTip");
        if (!rows.length) {
          document.getElementById("modelPagerMeta").textContent = "0 / 0";
          document.getElementById("modelPrevBtn").disabled = true;
          document.getElementById("modelNextBtn").disabled = true;
          renderEmpty(
            "modelList",
            hasPermission(PERMISSIONS.MODEL_SUBMIT) ? "当前还没有模型。先提交一个候选模型，再回来刷新列表。" : "当前账号还看不到模型数据。",
            "暂无模型数据",
            [
              { label: "刷新模型列表", action: "loadModels()", primary: true },
              hasPermission(PERMISSIONS.MODEL_SUBMIT) ? { label: "提交模型包", action: "focusField('modelPackage')" } : null,
            ]
          );
          return;
        }

        const search = document.getElementById("modelSearch").value.trim().toLowerCase();
        const statusFilter = document.getElementById("modelStatusFilter").value.trim();
        const sort = document.getElementById("modelSort")?.value || "created_desc";
        const pageSize = Number(document.getElementById("modelPageSize").value || "10");

        let filtered = rows.filter((row) => {
          const hitSearch =
            !search ||
            String(row.id || "").toLowerCase().includes(search) ||
            String(row.model_code || "").toLowerCase().includes(search) ||
            String(row.version || "").toLowerCase().includes(search);
          const hitStatus = !statusFilter || String(row.status || "") === statusFilter;
          return hitSearch && hitStatus;
        });

        filtered = filtered.sort((a, b) => {
          if (sort === "created_asc") return String(a.created_at || "").localeCompare(String(b.created_at || ""));
          if (sort === "code_asc") return String(a.model_code || "").localeCompare(String(b.model_code || ""));
          if (sort === "status_asc") return String(a.status || "").localeCompare(String(b.status || ""));
          return String(b.created_at || "").localeCompare(String(a.created_at || ""));
        });

        const paged = paginateRows(filtered, state.modelPage, pageSize);
        state.modelPage = paged.current;
        document.getElementById("modelPagerMeta").textContent = `第 ${paged.current} / ${paged.totalPages} 页 · 共 ${paged.total} 条`;
        document.getElementById("modelPrevBtn").disabled = paged.current <= 1;
        document.getElementById("modelNextBtn").disabled = paged.current >= paged.totalPages;

        if (!paged.rows.length) {
          renderEmpty(
            "modelList",
            "换一个搜索词或状态筛选后再试。",
            "当前筛选条件下无模型数据",
            [
              { label: "清空筛选", action: "document.getElementById('modelSearch').value='';document.getElementById('modelStatusFilter').value='';state.modelPage=1;renderModelList(state.models)", primary: true },
              { label: "刷新模型列表", action: "loadModels()" },
            ]
          );
          return;
        }

        const cards = paged.rows
          .map(
            (row) => {
              const meta = row.platform_meta || {};
              const source = modelSourceTypeLabel(meta.model_source_type);
              const dataset = meta.dataset_label ? `<div class="muted-note">数据批次：${escapeHtml(safe(meta.dataset_label))}</div>` : "";
              const round = meta.training_round ? `<div class="muted-note">微调轮次：${escapeHtml(safe(meta.training_round))}</div>` : "";
              return `<article class="minimal-item">
            <div class="minimal-head">
              <div>
                <div class="minimal-kicker">模型</div>
                <h3 class="minimal-title">${escapeHtml(safe(row.model_code || row.id || "-"))}</h3>
              </div>
              ${statusTag(row.status)}
            </div>
            <div class="minimal-sub mono">${escapeHtml(safe(row.id))}</div>
            <div class="minimal-meta">${escapeHtml(modelTypeLabel(row.model_type))} · ${escapeHtml(source)} · ${escapeHtml(taskTypeLabel(row.task_type))} · v${escapeHtml(safe(row.version || "-"))}</div>
            <div class="muted-note">${escapeHtml(safe(row.plugin_name || "-"))} · ${escapeHtml(safe(row.runtime || "-"))}</div>
            ${dataset}
            ${round}
            <div class="inline-actions">
                <button class="ghost btn-auto" onclick="showModelDetail('${escapeHtml(safe(row.id))}')">详情</button>
                <button class="ghost btn-auto" onclick="selectModelForTask('${escapeHtml(safe(row.id))}')">用于任务</button>
              </div>
          </article>`;
            }
          )
          .join("");

        writeOutput(
          "modelList",
          `<div class="minimal-section-head"><span>模型列表</span><span>${paged.total} 个模型</span></div><div class="minimal-list">${cards}</div>`
        );
      }

      async function loadModels() {
        if (!hasPermission(PERMISSIONS.MODEL_VIEW)) return;
        const hasTimelinePanels =
          !!document.getElementById("modelVersionCompare") || !!document.getElementById("modelTimelinePanel") || !!document.getElementById("modelReleaseBoard");
        setPanelLoading("modelList", true);
        if (hasTimelinePanels) setPanelLoading("modelVersionCompare", true);
        try {
          const data = await api("/models");
          state.models = Array.isArray(data) ? data : [];
          populateModelSelectors();
          renderModelList(state.models);
          if (state.models[0]) {
            document.getElementById("modelId").value = state.models[0].id;
            if (!document.getElementById("taskModelId").value) {
              document.getElementById("taskModelId").value = state.models[0].id;
            }
          }
          if (document.getElementById("modelSummary")) renderModelSummary();
          if (document.getElementById("modelLifecycle")) renderModelLifecycle();
          if (hasTimelinePanels) {
            renderModelVersionCompare();
            await loadModelTimeline();
          }
        } catch (e) {
          renderErrorState(
            "modelList",
            "模型加载失败",
            e.message,
            [
              { label: "重新加载", action: "loadModels()", primary: true },
              hasPermission(PERMISSIONS.MODEL_SUBMIT) ? { label: "提交模型包", action: "focusField('modelPackage')" } : null,
            ]
          );
          if (hasTimelinePanels) {
            renderErrorState("modelVersionCompare", "版本对比加载失败", e.message, [{ label: "重新加载", action: "loadModels()", primary: true }]);
            renderErrorState("modelTimelinePanel", "审批时间线加载失败", e.message, [{ label: "重新加载", action: "loadModels()", primary: true }]);
            renderErrorState("modelReleaseBoard", "发布记录加载失败", e.message, [{ label: "重新加载", action: "loadModels()", primary: true }]);
          }
          if (document.getElementById("modelLifecycle")) renderErrorState("modelLifecycle", "模型生命周期加载失败", e.message, [{ label: "重新加载", action: "loadModels()", primary: true }]);
          toast("模型加载失败", "warn");
        } finally {
          setPanelLoading("modelList", false);
        }
      }

      async function registerModel(button) {
        setButtonLoading(button, true, "提交中");
        setPanelLoading("modelOps", true);
        try {
          const file = document.getElementById("modelPackage").files[0];
          if (!file) throw new Error("请先选择模型包 zip");
          const fd = new FormData();
          fd.append("package", file);
          fd.append("model_source_type", document.getElementById("modelSourceType").value);
          fd.append("base_model_ref", document.getElementById("baseModelRef").value.trim());
          fd.append("training_round", document.getElementById("trainingRound").value.trim());
          fd.append("dataset_label", document.getElementById("trainingDataset").value.trim());
          fd.append("training_summary", document.getElementById("trainingSummary").value.trim());
          fd.append("model_type", document.getElementById("modelType").value);
          fd.append("runtime", document.getElementById("modelRuntime").value);
          fd.append("plugin_name", document.getElementById("modelPluginName").value.trim());
          fd.append("inputs_json", document.getElementById("modelInputsJson").value.trim());
          fd.append("outputs_json", document.getElementById("modelOutputsJson").value.trim());
          fd.append("gpu_mem_mb", document.getElementById("modelGpuMemMb").value.trim());
          fd.append("latency_ms", document.getElementById("modelLatencyMs").value.trim());
          const data = await api("/models/register", { method: "POST", body: fd }, true);
          renderModelOps(data, "ok");
          document.getElementById("modelId").value = data.id;
          document.getElementById("taskModelId").value = data.id;
          toast("模型提交成功", "ok");
          await loadModels();
          await loadPipelines();
          switchPage("models");
        } catch (e) {
          renderModelOps({ error: e.message }, "err");
          toast(`模型提交失败：${e.message}`, "err");
        } finally {
          setButtonLoading(button, false);
          setPanelLoading("modelOps", false);
        }
      }

      async function approveModel(button) {
        setButtonLoading(button, true, "审批中");
        setPanelLoading("modelOps", true);
        try {
          const modelId = document.getElementById("modelId").value.trim();
          if (!modelId) throw new Error("请输入模型ID");
          const validationAssetIds = parseCommaList(document.getElementById("validationAssetIds").value);
          const data = await api("/models/approve", {
            method: "POST",
            body: JSON.stringify({
              model_id: modelId,
              validation_asset_ids: validationAssetIds,
              validation_result: document.getElementById("validationResult").value,
              validation_summary: document.getElementById("validationSummary").value.trim() || null,
            }),
          });
          renderModelOps(data, "ok");
          toast("模型审批成功", "ok");
          await loadModels();
        } catch (e) {
          renderModelOps({ error: e.message }, "err");
          toast(`模型审批失败：${e.message}`, "err");
        } finally {
          setButtonLoading(button, false);
          setPanelLoading("modelOps", false);
        }
      }

      async function releaseModel(button) {
        setButtonLoading(button, true, "发布中");
        setPanelLoading("modelOps", true);
        try {
          const modelId = document.getElementById("modelId").value.trim();
          if (!modelId) throw new Error("请输入模型ID");
          const targetDevices = document
            .getElementById("releaseDevices")
            .value.split(",")
            .map((x) => x.trim())
            .filter(Boolean);
          const targetBuyers = document
            .getElementById("releaseBuyers")
            .value.split(",")
            .map((x) => x.trim())
            .filter(Boolean);
          const data = await api("/models/release", {
            method: "POST",
            body: JSON.stringify({
              model_id: modelId,
              target_devices: targetDevices,
              target_buyers: targetBuyers,
              delivery_mode: document.getElementById("deliveryMode").value,
              authorization_mode: document.getElementById("authorizationMode").value,
              api_access_key_label: document.getElementById("apiAccessKeyLabel").value.trim() || null,
              local_key_label: document.getElementById("localKeyLabel").value.trim() || null,
              runtime_encryption: true,
            }),
          });
          renderModelOps(data, "ok");
          toast("模型发布成功", "ok");
          await loadModels();
          await loadPipelines();
        } catch (e) {
          renderModelOps({ error: e.message }, "err");
          toast(`模型发布失败：${e.message}`, "err");
        } finally {
          setButtonLoading(button, false);
          setPanelLoading("modelOps", false);
        }
      }

      function defaultRouterModel() {
        return (state.models || []).find((row) => String(row.model_type || "") === "router") || null;
      }

      function defaultExpertModelForTask(taskKey) {
        return (
          (state.models || []).find(
            (row) => String(row.model_type || "expert") === "expert" && String(row.task_type || "") === String(taskKey || "")
          ) || null
        );
      }

      function hydrateExpertMap(expertMap) {
        const source = expertMap && typeof expertMap === "object" ? expertMap : {};
        const out = {};
        Object.entries(source).forEach(([taskKey, bindings]) => {
          const items = Array.isArray(bindings) ? bindings : [];
          const normalized = items
            .map((item, index) => {
              if (typeof item === "string") {
                return item.trim() ? { model_id: item.trim(), priority: index + 1 } : null;
              }
              if (!item || typeof item !== "object") return null;
              const defaultModel = defaultExpertModelForTask(taskKey);
              return {
                ...item,
                model_id: String(item.model_id || defaultModel?.id || "").trim(),
                priority: Number(item.priority || index + 1),
              };
            })
            .filter((item) => item && item.model_id);
          if (normalized.length) out[taskKey] = normalized;
        });
        return out;
      }

      function populateModelSelectors() {
        const routerSelect = document.getElementById("pipelineRouterModelId");
        if (routerSelect) {
          const current = routerSelect.value;
          const routerModels = (state.models || []).filter((row) => String(row.model_type || "") === "router");
          routerSelect.innerHTML = [`<option value="">无主路由</option>`]
            .concat(
              routerModels.map(
                (row) =>
                  `<option value="${escapeHtml(safe(row.id))}">${escapeHtml(safe(row.model_code || row.id))} · ${escapeHtml(
                    safe(row.version || "-")
                  )}</option>`
              )
            )
            .join("");
          const fallback = current || defaultRouterModel()?.id || "";
          if (fallback) routerSelect.value = fallback;
        }
      }

      function populateTaskPipelineOptions() {
        const select = document.getElementById("taskPipelineId");
        if (!select) return;
        const current = select.value;
        const rows = Array.isArray(state.pipelines) ? state.pipelines : [];
        select.disabled = !rows.length;
        select.innerHTML = rows.length
          ? [`<option value="">选择可调用流水线</option>`]
              .concat(
                rows.map(
                  (row) =>
                    `<option value="${escapeHtml(safe(row.id))}">${escapeHtml(pipelineDisplayName(row))} · ${escapeHtml(
                      safe(row.version || "-")
                    )}</option>`
                )
              )
              .join("")
          : `<option value="">当前没有可调用流水线</option>`;
        const fallback = current || rows.find((row) => String(row.status || "") === "RELEASED")?.id || rows[0]?.id || "";
        if (fallback) select.value = fallback;
        updateTaskSchedulerMode();
      }

      function renderPipelineOps(data, kind = "ok") {
        const payload = sanitizeForView(data);
        if (kind === "err") {
          const msg = payload.error || payload.detail || payload.message || "操作失败";
          writeOutput(
            "pipelineOps",
            `<div class="banner err"><div class="banner-title">流水线操作失败</div><div class="banner-sub">${escapeHtml(safe(msg))}</div></div>`
          );
          return;
        }
        const fields = [
          { label: "流水线ID", value: payload.id || "-", mono: true },
          { label: "流水线编码", value: payload.pipeline_code || "-" },
          { label: "名称", value: payload.name || "-" },
          { label: "版本", value: payload.version || "-" },
          { label: "状态", value: payload.status || "-" },
          { label: "主路由模型", value: payload.router_model_code || payload.router_model_id || "-" },
          { label: "专家任务数", value: Object.keys(payload.expert_map || {}).length || 0 },
          { label: "灰度比例", value: payload.traffic_ratio ?? 100 },
        ];
        writeOutput(
          "pipelineOps",
          `${kvGrid(fields)}<div class="action-strip">
            ${actionButtonHtml("刷新流水线列表", "loadPipelines()")}
            ${payload.id ? actionButtonHtml("查看详情", `showPipelineDetail('${escapeHtml(safe(payload.id))}')`) : ""}
            ${payload.id && hasPermission(PERMISSIONS.TASK_CREATE) ? actionButtonHtml("用于创建任务", `selectPipelineForTask('${escapeHtml(safe(payload.id))}'); switchPage('tasks')`) : ""}
          </div>`
        );
      }

      function renderPipelineList(data) {
        const rows = sanitizeForView(Array.isArray(data) ? data : []);
        if (!rows.length) {
          renderEmpty(
            "pipelineList",
            hasPermission(PERMISSIONS.MODEL_RELEASE) ? "先注册并发布一条流水线，执行页才会出现可选项。" : "当前账号还没有可见流水线。",
            "暂无流水线数据",
            [
              { label: "刷新流水线", action: "loadPipelines()", primary: true },
              hasPermission(PERMISSIONS.MODEL_RELEASE) ? { label: "新建流水线", action: "focusField('pipelineCode')" } : null,
            ]
          );
          return;
        }
        const search = document.getElementById("pipelineSearch")?.value.trim().toLowerCase() || "";
        const statusFilter = document.getElementById("pipelineStatusFilter")?.value.trim() || "";
        const filtered = rows.filter((row) => {
          const hitSearch =
            !search ||
            String(row.id || "").toLowerCase().includes(search) ||
            String(row.pipeline_code || "").toLowerCase().includes(search) ||
            String(row.name || "").toLowerCase().includes(search);
          const hitStatus = !statusFilter || String(row.status || "") === statusFilter;
          return hitSearch && hitStatus;
        });
        if (!filtered.length) {
          renderEmpty(
            "pipelineList",
            "清空搜索词或状态筛选后再试。",
            "当前筛选条件下无流水线数据",
            [
              {
                label: "清空筛选",
                action:
                  "document.getElementById('pipelineSearch').value='';document.getElementById('pipelineStatusFilter').value='';renderPipelineList(state.pipelines)",
                primary: true,
              },
              { label: "刷新流水线", action: "loadPipelines()" },
            ]
          );
          return;
        }
        const cards = filtered
          .map((row) => {
            const taskCount = Object.keys(row.expert_map || {}).length;
            const releaseInfo = `设备 ${((row.target_devices || []).length && row.target_devices.join(", ")) || "全部"} / 客户 ${((row.target_buyers || []).length && row.target_buyers.join(", ")) || "全部"}`;
            const modelCount = Array.isArray(row.models) ? row.models.length : 0;
            return `<article class="minimal-item">
              <div class="minimal-head">
                <div>
                  <div class="minimal-kicker">流水线</div>
                  <h3 class="minimal-title">${escapeHtml(safe(pipelineDisplayName(row)))}</h3>
                </div>
                ${statusTag(row.status)}
              </div>
              <div class="minimal-sub mono">${escapeHtml(safe(row.id))}</div>
              <div class="minimal-meta">${escapeHtml(safe(row.pipeline_code || "-"))} · v${escapeHtml(safe(row.version || "-"))} · ${taskCount} 个任务映射</div>
              <div class="muted-note">主路由：${escapeHtml(safe(row.router_model_code || row.router_model_id || "无"))} · 已绑定 ${modelCount} 个模型</div>
              <div class="muted-note">${escapeHtml(releaseInfo)} · 灰度 ${escapeHtml(safe(row.traffic_ratio ?? 100))}%</div>
              <div class="inline-actions">
                <button class="ghost btn-auto" onclick="showPipelineDetail('${escapeHtml(safe(row.id))}')">详情</button>
                <button class="ghost btn-auto" onclick="selectPipelineForTask('${escapeHtml(safe(row.id))}')">用于任务</button>
              </div>
            </article>`;
          })
          .join("");
        writeOutput("pipelineList", `<div class="minimal-section-head"><span>流水线列表</span><span>${filtered.length} 条</span></div><div class="minimal-list">${cards}</div>`);
      }

      function showPipelineDetail(pipelineId) {
        const pipeline = (state.pipelines || []).find((item) => String(item.id) === String(pipelineId));
        if (!pipeline) {
          toast("未找到流水线详情", "warn");
          return;
        }
        const payload = sanitizeForView(pipeline);
        const expertMap = payload.expert_map || {};
        const models = Array.isArray(payload.models) ? payload.models : [];
        openDrawer({
          title: `流水线详情 · ${safe(pipelineDisplayName(payload))}`,
          subtitle: `流水线ID ${safe(payload.id)}`,
          body: `
            <section class="drawer-section">
              <h4>核心信息</h4>
              ${kvGrid([
                { label: "流水线编码", value: payload.pipeline_code || "-" },
                { label: "版本", value: payload.version || "-" },
                { label: "状态", value: payload.status || "-" },
                { label: "主路由模型", value: payload.router_model_code || payload.router_model_id || "-" },
                { label: "灰度比例", value: payload.traffic_ratio ?? 100 },
              ])}
            </section>
            <section class="drawer-section">
              <h4>任务映射</h4>
              ${
                Object.keys(expertMap).length
                  ? kvGrid(
                      Object.entries(expertMap).map(([taskKey, bindings]) => ({
                        label: taskTypeLabel(taskKey),
                        value: (Array.isArray(bindings) ? bindings : [])
                          .map((item) => item.model_id || "-")
                          .join(" / "),
                      }))
                    )
                  : `<div class="drawer-note">当前未配置专家映射</div>`
              }
            </section>
            <section class="drawer-section">
              <h4>规则与模型</h4>
              ${kvGrid([
                { label: "阈值版本", value: payload.config?.threshold_version || "-" },
                { label: "融合策略", value: payload.fusion_rules?.strategy || payload.config?.fusion?.strategy || "-" },
                { label: "人工复核", value: payload.config?.human_review?.enabled === false ? "关闭" : "开启" },
                { label: "发布范围", value: `设备 ${((payload.target_devices || []).join(", ") || "全部")} / 客户 ${((payload.target_buyers || []).join(", ") || "全部")}` },
              ])}
              ${
                models.length
                  ? `<div class="drawer-note">模型清单：${models
                      .map((item) => `${safe(item.model_code)}(${modelTypeLabel(item.model_type)})`)
                      .join(" / ")}</div>`
                  : `<div class="drawer-note">当前未读取到绑定模型</div>`
              }
            </section>`,
        });
      }

      function selectPipelineForTask(pipelineId) {
        const mode = document.getElementById("schedulerMode");
        const select = document.getElementById("taskPipelineId");
        if (mode) mode.value = "pipeline";
        if (select) select.value = pipelineId || "";
        const pipeline = (state.pipelines || []).find((item) => String(item.id) === String(pipelineId));
        const releaseIdInput = document.getElementById("pipelineId");
        if (releaseIdInput && pipelineId) releaseIdInput.value = pipelineId;
        if (pipeline && !document.getElementById("taskIntent").value.trim()) {
          document.getElementById("taskIntent").value = `${pipelineDisplayName(pipeline)} 推理任务`;
        }
        updateTaskSchedulerMode();
        toast("已回填流水线到任务页");
      }

      async function loadPipelines() {
        if (!hasPermission(PERMISSIONS.MODEL_VIEW)) return;
        setPanelLoading("pipelineList", true);
        try {
          const deviceCode = document.getElementById("deviceCode")?.value.trim() || "";
          const query = deviceCode ? `?device_code=${encodeURIComponent(deviceCode)}` : "";
          const data = await api(`/pipelines${query}`);
          state.pipelines = Array.isArray(data) ? data : [];
          renderPipelineList(state.pipelines);
          populateTaskPipelineOptions();
          populateModelSelectors();
        } catch (e) {
          renderErrorState(
            "pipelineList",
            "流水线加载失败",
            e.message,
            [
              { label: "重新加载", action: "loadPipelines()", primary: true },
              hasPermission(PERMISSIONS.MODEL_RELEASE) ? { label: "填写流水线编码", action: "focusField('pipelineCode')" } : null,
            ]
          );
          toast("流水线加载失败", "warn");
        } finally {
          document.getElementById("pipelineList")?.classList.remove("loading");
        }
      }

      async function registerPipeline(button) {
        setButtonLoading(button, true, "注册中");
        setPanelLoading("pipelineOps", true);
        try {
          const routerModelId = document.getElementById("pipelineRouterModelId").value.trim() || null;
          const expertMap = hydrateExpertMap(parseJsonInput("pipelineExpertMapJson", "专家映射"));
          const payload = {
            pipeline_code: document.getElementById("pipelineCode").value.trim(),
            name: document.getElementById("pipelineName").value.trim(),
            version: document.getElementById("pipelineVersion").value.trim(),
            router_model_id: routerModelId,
            expert_map: expertMap,
            thresholds: parseJsonInput("pipelineThresholdsJson", "任务阈值"),
            fusion_rules: parseJsonInput("pipelineFusionJson", "融合规则"),
            config: parseJsonInput("pipelineConfigJson", "完整配置"),
          };
          if (!payload.pipeline_code) throw new Error("流水线编码不能为空");
          if (!payload.name) throw new Error("流水线名称不能为空");
          if (!payload.version) throw new Error("流水线版本不能为空");
          if (!Object.keys(payload.expert_map || {}).length) throw new Error("至少绑定一个专家任务");
          const data = await api("/pipelines/register", { method: "POST", body: JSON.stringify(payload) });
          renderPipelineOps(data, "ok");
          document.getElementById("pipelineId").value = data.id;
          populateTaskPipelineOptions();
          toast("流水线注册成功", "ok");
          await loadPipelines();
        } catch (e) {
          renderPipelineOps({ error: e.message }, "err");
          toast(`流水线注册失败：${e.message}`, "err");
        } finally {
          setButtonLoading(button, false);
          setPanelLoading("pipelineOps", false);
        }
      }

      async function releasePipeline(button) {
        setButtonLoading(button, true, "发布中");
        setPanelLoading("pipelineOps", true);
        try {
          const pipelineId = document.getElementById("pipelineId").value.trim();
          if (!pipelineId) throw new Error("请输入流水线ID");
          const data = await api("/pipelines/release", {
            method: "POST",
            body: JSON.stringify({
              pipeline_id: pipelineId,
              target_devices: parseCommaList(document.getElementById("pipelineReleaseDevices").value),
              target_buyers: parseCommaList(document.getElementById("pipelineReleaseBuyers").value),
              traffic_ratio: Number(document.getElementById("pipelineTrafficRatio").value || "100"),
              release_notes: document.getElementById("pipelineReleaseNotes").value.trim() || null,
            }),
          });
          renderPipelineOps(data, "ok");
          toast("流水线发布成功", "ok");
          await loadPipelines();
        } catch (e) {
          renderPipelineOps({ error: e.message }, "err");
          toast(`流水线发布失败：${e.message}`, "err");
        } finally {
          setButtonLoading(button, false);
          setPanelLoading("pipelineOps", false);
        }
      }

      function renderAssetOut(data, kind = "ok") {
        const payload = sanitizeForView(data, "assetOutMaskTip");
        const section = document.getElementById("assetResultSection");
        if (section) section.classList.remove("hidden");
        const assetId = payload.id || "";
        const meta = payload.meta || {};
        const purpose = assetPurposeLabel(meta.asset_purpose);
        const canCreateTask = hasPermission(PERMISSIONS.TASK_CREATE) && ["inference", "validation"].includes(String(meta.asset_purpose || ""));
        if (kind === "err") {
          renderErrorState(
            "assetOut",
            "上传失败",
            payload.error || "-",
            [
              { label: "重新选择文件", action: "focusField('assetFile')", primary: true },
              { label: "检查用途", action: "focusField('assetPurpose')" },
            ],
            "确认文件已选择，且用途与场景信息填写正确。"
          );
          return;
        }
        writeOutput(
          "assetOut",
          `<div class="asset-result-card">
            ${
              kind === "ok" && assetId
                ? `${kvGrid([
                    { label: "资产ID", value: assetId, mono: true },
                    { label: "用途", value: purpose },
                    { label: "数据批次", value: meta.dataset_label || "-" },
                    { label: "业务场景", value: meta.use_case || "-" },
                    { label: "目标模型", value: meta.intended_model_code || "-" },
                  ])}
                  <div class="asset-result-meta">
                    <div class="asset-result-label">资产ID</div>
                    <div class="asset-result-value mono">${escapeHtml(safe(assetId))}</div>
                  </div>
                  ${
                    canCreateTask
                      ? `<div class="action-strip">
                          <button class="btn-auto" onclick="document.getElementById('assetId').value='${escapeHtml(safe(assetId))}'; switchPage('tasks')">去创建任务</button>
                        </div>`
                      : ""
                  }`
                : ""
            }
          </div>`
        );
      }

      async function uploadAsset(button) {
        setButtonLoading(button, true, "上传中");
        const section = document.getElementById("assetResultSection");
        if (section) section.classList.remove("hidden");
        setPanelLoading("assetOut", true);
        try {
          if (!validateRequiredField("assetFile", "请选择资产文件")) throw new Error("请选择资产文件");
          const file = document.getElementById("assetFile").files[0];
          const fd = new FormData();
          fd.append("file", file);
          fd.append("asset_purpose", document.getElementById("assetPurpose").value);
          fd.append("dataset_label", document.getElementById("datasetLabel").value.trim());
          fd.append("use_case", document.getElementById("assetUseCase").value.trim());
          fd.append("intended_model_code", document.getElementById("intendedModelCode").value.trim());
          fd.append("sensitivity_level", document.getElementById("sensitivity").value);
          const sourceUriInput = document.getElementById("sourceUri");
          if (sourceUriInput && sourceUriInput.value) {
            fd.append("source_uri", sourceUriInput.value);
          }
          const data = await api("/assets/upload", { method: "POST", body: fd }, true);
          renderAssetOut(data, "ok");
          const assetIdInput = document.getElementById("assetId");
          if (assetIdInput) assetIdInput.value = data.id;
          state.lastAssetId = data.id;
          toast("资产上传成功", "ok");
        } catch (e) {
          renderAssetOut({ error: e.message }, "err");
          toast(`资产上传失败：${e.message}`, "err");
        } finally {
          setButtonLoading(button, false);
          setPanelLoading("assetOut", false);
        }
      }

      function renderTaskOut(data, kind = "ok") {
        const payload = sanitizeForView(data, "taskOutMaskTip");
        const section = document.getElementById("taskResultSection");
        if (section) section.classList.remove("hidden");
        const taskId = payload.id || "";
        const scheduler = payload.scheduler || {};
        const selectedModel = scheduler.selected_model || {};
        const isPipelineTask = !!payload.pipeline_id;
        const summaryCards = [
          { label: "任务ID", value: taskId, mono: true },
          { label: "任务类型", value: taskTypeLabel(payload.task_type || scheduler.inferred_task_type) },
          isPipelineTask ? { label: "执行入口", value: "Pipeline 编排" } : { label: "执行入口", value: scheduler.enabled ? "主模型调度" : "手动模型" },
          payload.pipeline_code ? { label: "流水线", value: `${payload.pipeline_code} · ${payload.pipeline_version || "-"}` } : null,
          payload.pipeline_id ? { label: "流水线ID", value: payload.pipeline_id, mono: true } : null,
          { label: "模型代码", value: payload.model_code || selectedModel.model_code || "-" },
          { label: "模型ID", value: payload.model_id || selectedModel.model_id || "-", mono: true },
          scheduler.enabled ? { label: "调度置信度", value: scheduler.confidence || "-" } : null,
        ].filter(Boolean);

        if (kind === "err") {
          renderErrorState(
            "taskOut",
            "任务创建失败",
            payload.error || "-",
            [
              { label: "回到任务表单", action: "focusField('assetId')", primary: true },
              { label: "检查执行入口", action: "focusField('schedulerMode')" },
            ],
            "先确认资产 ID、执行入口和流水线或模型是否匹配。"
          );
          return;
        }

        writeOutput(
          "taskOut",
          `<div class="asset-result-card">
          ${
            kind === "ok" && taskId
              ? `${isPipelineTask ? `<div class="banner ok">
                  <div class="banner-title">Pipeline 编排任务已创建</div>
                  <div class="banner-sub">${escapeHtml(safe(`${payload.pipeline_code || "pipeline"} ${payload.pipeline_version || ""}`))}</div>
                </div>` : ""}
                ${scheduler.enabled ? `<div class="banner ok">
                  <div class="banner-title">主模型调度已生效</div>
                  <div class="banner-sub">${escapeHtml(safe(scheduler.summary || "已将调度决策写入任务策略"))}</div>
                </div>` : ""}
                <div class="kv-grid">
                  ${summaryCards
                    .map(
                      (item) => `<div class="kv-item">
                        <div class="kv-label">${escapeHtml(item.label)}</div>
                        <div class="kv-value${item.mono ? " mono" : ""}">${escapeHtml(safe(item.value))}</div>
                      </div>`
                    )
                    .join("")}
                </div>
                <div class="action-strip">
                  ${
                    hasPermission(PERMISSIONS.RESULT_READ)
                      ? `<button class="btn-auto" onclick="syncTaskIdInputs('${escapeHtml(safe(taskId))}'); switchPage('task-monitor')">查看任务状态</button>`
                      : ""
                  }
                </div>`
              : ""
          }</div>`
        );
      }

      function updateTaskSchedulerMode() {
        const mode = document.getElementById("schedulerMode")?.value || "pipeline";
        const modelInput = document.getElementById("taskModelId");
        const modelField = document.getElementById("taskModelField");
        const pipelineField = document.getElementById("taskPipelineField");
        const recommendBtn = document.getElementById("btnTaskRecommend");
        const hint = document.getElementById("taskSchedulerHint");
        const pipelineCount = Array.isArray(state.pipelines) ? state.pipelines.length : 0;
        if (modelField) modelField.classList.toggle("hidden", mode !== "manual");
        if (pipelineField) pipelineField.classList.toggle("hidden", mode !== "pipeline");
        if (recommendBtn) recommendBtn.classList.toggle("hidden", mode !== "master");
        if (modelInput) {
          modelInput.readOnly = mode !== "manual";
          modelInput.placeholder =
            mode === "manual"
              ? "手动模式下填写模型ID"
              : mode === "master"
              ? "自动调度会选择模型，也可先查看推荐结果"
              : "Pipeline 编排模式下不需要填写模型ID";
        }
        if (hint) {
          hint.textContent =
            mode === "pipeline"
              ? pipelineCount
                ? "当前为 Pipeline 编排模式。先选流水线，再填资产 ID 和场景信息。"
                : "当前还没有可调用流水线。先到“更多 > 流水线”发布一条，再回来创建任务。"
              : mode === "master"
              ? "当前为主模型调度兼容模式。建议先生成推荐结果，再创建任务。"
              : "当前为手动模型兼容模式。请直接填写模型 ID。";
        }
      }

      function renderTaskRecommendation(data, kind = "ok") {
        const payload = sanitizeForView(data);
        const section = document.getElementById("taskRecommendSection");
        if (section) section.classList.remove("hidden");
        const selectedModel = payload.selected_model || null;
        const alternatives = Array.isArray(payload.alternatives) ? payload.alternatives : [];
        const fallbackBannerClass = selectedModel ? "ok" : "warn";
        const extraCandidates = alternatives.filter((item) => item && item.model_id !== selectedModel?.model_id);
        const summaryFields = [
          { label: "调度引擎", value: payload.engine || "-" },
          { label: "请求任务类型", value: taskTypeLabel(payload.requested_task_type) },
          { label: "推断任务类型", value: taskTypeLabel(payload.inferred_task_type || selectedModel?.task_type) },
          { label: "置信度", value: payload.confidence || "-" },
        ];

        const candidateCard = (candidate, title) => {
          if (!candidate) return "";
          const targetDevices = Array.isArray(candidate.target_devices) && candidate.target_devices.length ? candidate.target_devices.join(", ") : "全部";
          const targetBuyers = Array.isArray(candidate.target_buyers) && candidate.target_buyers.length ? candidate.target_buyers.join(", ") : "全部";
          const reasons = Array.isArray(candidate.reasons) && candidate.reasons.length ? candidate.reasons : ["默认按发布范围和版本新鲜度排序"];
          return `<div class="kv-item">
            <div class="kv-label">${escapeHtml(title)}</div>
            <div class="kv-value">${escapeHtml(safe(candidate.model_code || "-"))} ${escapeHtml(safe(candidate.version || ""))}</div>
            <div class="muted-note">${escapeHtml(taskTypeLabel(candidate.task_type))} · 分数 ${escapeHtml(safe(candidate.score ?? "-"))}</div>
            <div class="muted-note mono">${escapeHtml(safe(candidate.model_id || "-"))}</div>
            <div class="muted-note">设备范围：${escapeHtml(targetDevices)} / 客户范围：${escapeHtml(targetBuyers)}</div>
            <div class="muted-note">${reasons.map((item) => escapeHtml(safe(item))).join(" · ")}</div>
          </div>`;
        };

        if (kind === "err") {
          renderErrorState(
            "taskRecommendOut",
            "推荐失败",
            payload.error || "-",
            [
              { label: "检查资产ID", action: "focusField('assetId')", primary: true },
              { label: "补充业务描述", action: "focusField('taskIntent')" },
            ],
            "推荐模型只用于主模型调度兼容模式。"
          );
          return;
        }

        if (!selectedModel && !extraCandidates.length) {
          renderStatePanel("taskRecommendOut", {
            tone: "warn",
            title: "当前没有可调度模型",
            message: payload.summary || "请检查资产、任务类型或发布范围。",
            tip: "可以先补充业务描述，或改用 Pipeline 编排模式。",
            actions: [
              { label: "补充业务描述", action: "focusField('taskIntent')", primary: true },
              { label: "切回 Pipeline", action: "document.getElementById('schedulerMode').value='pipeline';updateTaskSchedulerMode();focusField('taskPipelineId')" },
            ],
          });
          return;
        }

        writeOutput(
          "taskRecommendOut",
          `<div class="asset-result-card">
            <div class="banner ${fallbackBannerClass}">
              <div class="banner-title">${selectedModel ? "已生成推荐结果" : "当前没有可调度模型"}</div>
              <div class="banner-sub">${escapeHtml(safe(payload.summary || "请检查资产、任务类型或发布范围"))}</div>
            </div>
            ${`<div class="kv-grid">
                    ${summaryFields
                      .map(
                        (item) => `<div class="kv-item">
                          <div class="kv-label">${escapeHtml(item.label)}</div>
                          <div class="kv-value">${escapeHtml(safe(item.value))}</div>
                        </div>`
                      )
                      .join("")}
                  </div>
                  ${
                    Array.isArray(payload.signals) && payload.signals.length
                      ? `<div class="muted-note">${payload.signals.map((item) => escapeHtml(safe(item))).join(" / ")}</div>`
                      : ""
                  }
                  ${
                    selectedModel || extraCandidates.length
                      ? `<div class="kv-grid">
                          ${selectedModel ? candidateCard(selectedModel, "主推荐模型") : ""}
                          ${extraCandidates.slice(0, 2).map((item, index) => candidateCard(item, `备选 ${index + 1}`)).join("")}
                        </div>`
                      : ""
                  }`}
          </div>`
        );
      }

      async function recommendTaskModel(button) {
        const section = document.getElementById("taskRecommendSection");
        if (section) section.classList.remove("hidden");
        setButtonLoading(button, true, "推荐中");
        setPanelLoading("taskRecommendOut", true);
        try {
          const schedulerMode = document.getElementById("schedulerMode").value;
          if (schedulerMode !== "master") throw new Error("推荐模型仅用于主模型调度兼容模式");
          if (!validateRequiredField("assetId", "请输入资产ID")) throw new Error("资产ID不能为空");
          const assetId = document.getElementById("assetId").value.trim();

          const payload = {
            asset_id: assetId,
            task_type: document.getElementById("taskType").value || null,
            device_code: document.getElementById("deviceCode").value.trim() || null,
            intent_text: document.getElementById("taskIntent").value.trim() || null,
            limit: 3,
          };
          const data = await api("/tasks/recommend-model", { method: "POST", body: JSON.stringify(payload) });
          renderTaskRecommendation(data, "ok");

          const selectedModel = data.selected_model || null;
          if (selectedModel?.model_id) {
            document.getElementById("taskModelId").value = selectedModel.model_id;
          }
          const resolvedTaskType = data.inferred_task_type || selectedModel?.task_type || "";
          if (resolvedTaskType) {
            document.getElementById("taskType").value = resolvedTaskType;
          }
          updateTaskSchedulerMode();
          toast(selectedModel ? "已生成推荐结果" : "未找到匹配模型", selectedModel ? "ok" : "warn");
        } catch (e) {
          renderTaskRecommendation({ error: e.message }, "err");
          toast(`推荐模型失败：${e.message}`, "err");
        } finally {
          setButtonLoading(button, false);
          setPanelLoading("taskRecommendOut", false);
        }
      }

      async function createTask(button) {
        setButtonLoading(button, true, "创建中");
        const section = document.getElementById("taskResultSection");
        if (section) section.classList.remove("hidden");
        setPanelLoading("taskOut", true);
        try {
          const schedulerMode = document.getElementById("schedulerMode").value;
          const pipelineId = document.getElementById("taskPipelineId").value.trim();
          const modelId = document.getElementById("taskModelId").value.trim();
          const assetId = document.getElementById("assetId").value.trim();
          const taskType = document.getElementById("taskType").value || null;
          const taskIntent = document.getElementById("taskIntent").value.trim();
          clearFieldError("taskPipelineId");
          clearFieldError("taskModelId");
          if (!validateRequiredField("assetId", "请输入资产ID")) throw new Error("资产ID不能为空");
          if (schedulerMode === "pipeline" && !pipelineId) {
            setFieldError("taskPipelineId", "请选择流水线");
            focusField("taskPipelineId");
            throw new Error("请选择流水线");
          }
          if (schedulerMode === "manual" && !modelId) {
            setFieldError("taskModelId", "手动模式下请输入模型ID");
            focusField("taskModelId");
            throw new Error("手动模式下模型ID不能为空");
          }

          const policy = parseJsonInput("policyJson", "数据策略");
          const context = {
            ...parseJsonInput("taskContextJson", "上下文"),
            scene_hint: document.getElementById("taskSceneHint").value.trim() || undefined,
            device_type: document.getElementById("taskDeviceType").value.trim() || undefined,
            camera_id: document.getElementById("taskCameraId").value.trim() || undefined,
          };
          const options = parseJsonInput("taskOptionsJson", "执行选项");
          Object.keys(context).forEach((key) => {
            if (context[key] === undefined || context[key] === "") delete context[key];
          });
          if (!context.timestamp) context.timestamp = new Date().toISOString();
          if (!context.job_id) context.job_id = `job-${Date.now()}`;

          const payload = {
            pipeline_id: schedulerMode === "pipeline" ? pipelineId : null,
            model_id: schedulerMode === "manual" ? modelId : null,
            asset_id: assetId,
            task_type: taskType,
            device_code: document.getElementById("deviceCode").value.trim() || null,
            policy,
            use_master_scheduler: schedulerMode === "master",
            intent_text: taskIntent || null,
            context,
            options,
          };
          const data = await api("/tasks/create", { method: "POST", body: JSON.stringify(payload) });
          renderTaskOut(data, "ok");
          syncTaskIdInputs(data.id);
          state.lastTaskId = data.id;
          toast("任务创建成功", "ok");
        } catch (e) {
          renderTaskOut({ error: e.message }, "err");
          toast(`任务创建失败：${e.message}`, "err");
        } finally {
          setButtonLoading(button, false);
          setPanelLoading("taskOut", false);
        }
      }

      function renderTaskStatus(data, kind = "ok") {
        const payload = sanitizeForView(data, "taskStatusOutMaskTip");
        const section = document.getElementById("taskStatusSection");
        if (section) section.classList.remove("hidden");
        if (kind === "err") {
          renderErrorState(
            "taskStatusOut",
            "任务查询失败",
            payload.error || "-",
            [
              { label: "重新输入任务ID", action: "focusField('monitorTaskId')", primary: true },
              state.lastTaskId ? { label: "带入最近任务", action: `document.getElementById('monitorTaskId').value='${escapeHtml(safe(state.lastTaskId))}'` } : null,
            ],
            "任务创建后可从执行页直接跳到这里。"
          );
          return;
        }
        const run = payload.run || {};
        const reviewQueue = Array.isArray(payload.review_queue) ? payload.review_queue : [];
        const fields = [
          { label: "任务类型", value: taskTypeLabel(payload.task_type) },
          payload.pipeline_id ? { label: "流水线ID", value: payload.pipeline_id, mono: true } : null,
          payload.scheduler?.summary ? { label: "调度摘要", value: payload.scheduler.summary } : null,
          payload.orchestrator?.pipeline?.pipeline_code
            ? { label: "Pipeline", value: `${payload.orchestrator.pipeline.pipeline_code} · ${payload.orchestrator.pipeline.version || "-"}` }
            : null,
          payload.model_code ? { label: "模型代码", value: payload.model_code } : null,
          { label: "模型ID", value: payload.model_id || "-", mono: true },
          { label: "资产ID", value: payload.asset_id || "-", mono: true },
          { label: "结果条数", value: payload.result_count ?? "-" },
          run.input_hash ? { label: "输入哈希", value: run.input_hash, mono: true } : null,
          run.pipeline_version ? { label: "运行版本", value: run.pipeline_version } : null,
          run.audit_hash ? { label: "审计哈希", value: run.audit_hash, mono: true } : null,
          { label: "创建时间", value: formatTime(payload.created_at) },
          payload.finished_at ? { label: "结束时间", value: formatTime(payload.finished_at) } : null,
          payload.error_message ? { label: "错误信息", value: payload.error_message } : null,
        ].filter(Boolean);
        const runSummary =
          run && Object.keys(run).length
            ? `<div class="muted-note">运行摘要：router ${escapeHtml(safe(run.timings?.router_ms ?? "-"))} ms / 总耗时 ${escapeHtml(
                safe(run.timings?.total_ms ?? "-")
              )} ms / 阈值版本 ${escapeHtml(safe(run.threshold_version || "-"))}</div>`
            : "";
        const reviewSummary = reviewQueue.length
          ? `<div class="muted-note">复核队列：${reviewQueue
              .map((item) => `${safe(item.reason)}(${safe(item.status)})`)
              .join(" / ")}</div>`
          : "";
        writeOutput(
          "taskStatusOut",
          `<div class="asset-result-card">
            <div class="banner ${statusClass(payload.status)}">
              <div class="banner-title">任务状态 ${statusTag(payload.status)}</div>
            </div>
            <div class="asset-result-meta">
              <div class="asset-result-label">任务ID</div>
              <div class="asset-result-value mono">${escapeHtml(safe(payload.id))}</div>
            </div>
            ${kvGrid(fields)}
            ${runSummary}
            ${reviewSummary}
            ${
              String(payload.status || "").toUpperCase() === "SUCCEEDED" && hasPermission(PERMISSIONS.RESULT_READ)
                ? `<div class="action-strip">
                    ${actionButtonHtml("查看结果", `syncTaskIdInputs('${escapeHtml(safe(payload.id))}'); switchPage('results')`)}
                  </div>`
                : ""
            }
          </div>`
        );
      }

      async function fetchTaskStatus(taskId) {
        if (!taskId) throw new Error("请输入任务ID");
        const data = await api(`/tasks/${taskId}`);
        state.currentTask = data;
        state.lastTaskId = taskId;
        syncTaskIdInputs(taskId);
        renderTaskStatus(data, "ok");
        return data;
      }

      async function refreshTaskMonitorSilently() {
        if (state.page !== "task-monitor") return;
        const taskId = document.getElementById("monitorTaskId").value.trim();
        const status = document.getElementById("taskMonitorStatus");
        try {
          if (!taskId) {
            if (status && state.taskMonitorAuto) {
              status.textContent = "请输入任务ID";
            }
            return;
          }
          await fetchTaskStatus(taskId);
          if (status && state.taskMonitorAuto) {
            status.textContent = `已更新 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
          }
        } catch {
          if (status && state.taskMonitorAuto) {
            status.textContent = "刷新失败";
          }
        }
      }

      function toggleTaskMonitorAuto() {
        if (state.taskMonitorAuto) {
          stopTaskMonitorAuto();
          toast("任务监控自动刷新已关闭");
          return;
        }

        state.taskMonitorAuto = true;
        updateTaskMonitorBadge();
        refreshTaskMonitorSilently();
        state.taskMonitorTimer = window.setInterval(() => {
          refreshTaskMonitorSilently();
        }, 10000);
        toast("任务监控自动刷新已开启", "ok");
      }

      function summarizeResultMetrics(items) {
        const list = Array.isArray(items) ? items : [];
        const count = list.length;
        const alerts = list.filter((item) => String(item.alert_level || "").toUpperCase() !== "INFO").length;
        const screenshots = list.filter((item) => item.screenshot_uri).length;
        const avgLatency = count
          ? Math.round(
              list
                .map((item) => Number(item.duration_ms || 0))
                .reduce((a, b) => a + b, 0) / count
            )
          : 0;
        return { count, alerts, screenshots, avgLatency };
      }

      function resultFields(resultJson) {
        const t = resultJson?.task_type || "";
        if (t === "car_number_ocr") {
          return [
            { label: "识别车号", value: resultJson.car_number || "-" },
            { label: "置信度", value: typeof resultJson.confidence === "number" ? resultJson.confidence.toFixed(3) : "-" },
            { label: "识别引擎", value: resultJson.engine || "-" },
          ];
        }
        if (t === "bolt_missing_detect") {
          return [
            { label: "螺栓数量", value: resultJson.bolt_count ?? "-" },
            { label: "缺失告警", value: resultJson.missing ? "是" : "否" },
            { label: "检测器", value: resultJson.detector || "-" },
          ];
        }
        return Object.entries(resultJson || {})
          .slice(0, 4)
          .map(([k, v]) => ({ label: k, value: Array.isArray(v) ? v.join(",") : typeof v === "object" ? "[对象]" : v }));
      }

      async function loadPreviewImage(resultId, imgId, placeholderId) {
        const img = document.getElementById(imgId);
        const placeholder = document.getElementById(placeholderId);
        if (!img || !placeholder || !state.token) return;
        try {
          const resp = await fetch(`${API_BASE}/results/${encodeURIComponent(resultId)}/screenshot`, {
            headers: { Authorization: `Bearer ${state.token}` },
          });
          if (!resp.ok) throw new Error("无法读取截图");
          const blob = await resp.blob();
          const url = URL.createObjectURL(blob);
          img.src = url;
          img.classList.remove("hidden");
          placeholder.classList.add("hidden");
        } catch {
          placeholder.textContent = "截图不可用或按策略未上传";
        }
      }

      async function loadResultImage(resultId) {
        return loadPreviewImage(resultId, `img-${resultId}`, `ph-${resultId}`);
      }

      function renderResults(items, kind = "ok", errMsg = "") {
        state.resultRows = sanitizeForView(Array.isArray(items) ? items : [], "resultOutMaskTip");
        const section = document.getElementById("resultResultSection");
        if (section) section.classList.remove("hidden");
        const rows = Array.isArray(state.resultRows) ? state.resultRows : [];
        if (!rows.length) {
          if (kind === "err") {
            renderErrorState(
              "resultOut",
              "结果查询失败",
              errMsg || "请重试",
              [
                { label: "重新输入任务ID", action: "focusField('resultTaskId')", primary: true },
                { label: "去任务监控", action: "switchPage('task-monitor')" },
              ],
              "先确认任务已经执行完成。"
            );
          } else {
            renderStatePanel("resultOut", {
              tone: "warn",
              title: "当前还没有结果",
              message: "该任务暂时没有可展示结果。",
              tip: "可以先到任务监控查看状态，成功后再回来查询。",
              actions: [
                { label: "查看任务监控", action: "switchPage('task-monitor')", primary: true },
                { label: "重新查询", action: "queryResults(document.getElementById('btnResultQuery'))" },
              ],
            });
          }
          return;
        }

        const metrics = summarizeResultMetrics(rows);
        const run = rows[0]?.run || null;
        const cards = rows
          .map((row) => {
            const fields = resultFields(row.result_json || {});
            return `<article class="result-item">
              <div class="result-head">
                <div class="result-title">结果ID <span class="mono">${escapeHtml(safe(row.id))}</span></div>
                <div class="inline-actions">
                  ${statusTag(row.alert_level)}
                  <button class="ghost btn-auto" onclick="showResultDetail('${escapeHtml(safe(row.id))}')">详情</button>
                </div>
              </div>
              ${kvGrid([
                { label: "模型ID", value: row.model_id || "-", mono: true },
                { label: "任务类型", value: taskTypeLabel(row.result_json?.task_type) },
                { label: "阶段", value: row.result_json?.stage || "-" },
                { label: "Pipeline", value: row.result_json?.pipeline_code || row.run?.pipeline_version || "-" },
                { label: "耗时(ms)", value: row.duration_ms ?? "-" },
                { label: "时间", value: formatTime(row.created_at) },
              ])}
              ${kvGrid(fields)}
              <img id="img-${escapeHtml(safe(row.id))}" class="thumb hidden" alt="推理截图" />
              <div id="ph-${escapeHtml(safe(row.id))}" class="thumb-placeholder">加载截图中...</div>
            </article>`;
          })
          .join("");

        writeOutput(
          "resultOut",
          `<div class="asset-result-card">
            ${kvGrid([
              { label: "结果条数", value: metrics.count },
              { label: "告警条数", value: metrics.alerts },
              { label: "平均耗时(ms)", value: metrics.avgLatency },
            ])}
            ${
              run
                ? `<div class="muted-note">运行摘要：pipeline ${escapeHtml(safe(run.pipeline_version || "-"))} / 审计哈希 ${escapeHtml(
                    safe(run.audit_hash || "-")
                  )} / 总耗时 ${escapeHtml(safe(run.timings?.total_ms ?? "-"))} ms</div>`
                : ""
            }
            <div class="action-strip">
              <button class="ghost btn-auto" onclick="exportResults(this)">导出结果摘要</button>
            </div>
            <div class="result-list">${cards}</div>
          </div>`
        );

        rows.forEach((row) => {
          loadResultImage(row.id);
        });
      }

      function renderDashboardHeroActions() {
        const root = document.getElementById("dashboardHeroActions");
        if (!root) return;
        const blueprint = dashboardBlueprint();
        const enabledSteps = blueprint.steps.filter((item) => item.enabled);
        const seenPages = new Set();
        const actions = enabledSteps
          .filter((item) => {
            if (seenPages.has(item.page)) return false;
            seenPages.add(item.page);
            return true;
          })
          .slice(0, 3)
          .map((item, index) => ({
            label: item.action,
            page: item.page,
            primary: index === 0,
          }));

        root.innerHTML = actions
          .map(
            (item) =>
              `<button class="${item.primary ? "btn-auto" : "ghost btn-auto"}" onclick="switchPage('${item.page}')">${escapeHtml(item.label)}</button>`
          )
          .join("");
      }

      function dashboardBlueprint() {
        const role = primaryRole();
        const blueprints = {
          platform_admin: {
            title: "先准备能力，再发布，再验证结果。",
            desc: "今天最短路径：审批模型，发布流水线，然后验证一次真实执行结果。",
            steps: [
              { code: "01", title: "审批模型", desc: "先确认候选模型可发布。", action: "进入模型", page: "models", enabled: hasPermission(PERMISSIONS.MODEL_VIEW) },
              { code: "02", title: "发布流水线", desc: "把主路由、专家和规则发布给客户与设备。", action: "进入流水线", page: "pipelines", enabled: hasPermission(PERMISSIONS.MODEL_VIEW) },
              { code: "03", title: "验证结果", desc: "用结果和审计确认交付是否生效。", action: "查看结果", page: "results", enabled: hasPermission(PERMISSIONS.RESULT_READ) },
            ],
            extras: ["audit", "assets"],
          },
          supplier_engineer: {
            title: "先提交模型，再等审批，再看状态。",
            desc: "今天最短路径：准备模型包，提交模型，然后确认状态是否进入审批。",
            steps: [
              { code: "01", title: "准备模型包", desc: "确认模型包和版本信息完整。", action: "进入模型", page: "models", enabled: hasPermission(PERMISSIONS.MODEL_VIEW) },
              { code: "02", title: "提交模型", desc: "提交候选模型或主路由模型。", action: "提交模型", page: "models", enabled: hasPermission(PERMISSIONS.MODEL_VIEW) },
              { code: "03", title: "查看状态", desc: "确认模型已进入审批或发布流程。", action: "查看模型", page: "models", enabled: hasPermission(PERMISSIONS.MODEL_VIEW) },
            ],
            extras: [],
          },
          buyer_operator: {
            title: "先上传资产，再执行，最后查看结果。",
            desc: "今天最短路径：上传一次资产，选择流水线创建任务，然后查看结果。",
            steps: [
              { code: "01", title: "上传资产", desc: "上传图片或视频并得到资产 ID。", action: "上传资产", page: "assets", enabled: hasPermission(PERMISSIONS.ASSET_UPLOAD) },
              { code: "02", title: "创建任务", desc: "选择流水线并发起执行。", action: "去执行", page: "tasks", enabled: hasPermission(PERMISSIONS.TASK_CREATE) },
              { code: "03", title: "查看结果", desc: "查看结构化结果和截图。", action: "查看结果", page: "results", enabled: hasPermission(PERMISSIONS.RESULT_READ) },
            ],
            extras: ["pipelines", "task-monitor"],
          },
          buyer_auditor: {
            title: "先定位任务，再看结果，再查留痕。",
            desc: "今天最短路径：查询任务状态，查看结果，然后到审计确认关键动作。",
            steps: [
              { code: "01", title: "定位任务", desc: "先找到要复核的任务。", action: "任务监控", page: "task-monitor", enabled: hasPermission(PERMISSIONS.RESULT_READ) },
              { code: "02", title: "查看结果", desc: "核对结果、截图和摘要。", action: "查看结果", page: "results", enabled: hasPermission(PERMISSIONS.RESULT_READ) },
              { code: "03", title: "查询审计", desc: "回查导出、发布和执行留痕。", action: "查看审计", page: "audit", enabled: hasPermission(PERMISSIONS.AUDIT_READ) },
            ],
            extras: [],
          },
        };

        return blueprints[role] || {
          title: "先完成常用 3 步，再进入更多页面。",
          desc: "从这里进入最常见的操作路径。",
          steps: [
            { code: "01", title: "查看模型", desc: "确认当前可用模型。", action: "进入模型", page: "models", enabled: hasPermission(PERMISSIONS.MODEL_VIEW) },
            { code: "02", title: "创建任务", desc: "选择资产和执行方式。", action: "去执行", page: "tasks", enabled: hasPermission(PERMISSIONS.TASK_CREATE) },
            { code: "03", title: "查看结果", desc: "确认输出是否符合预期。", action: "查看结果", page: "results", enabled: hasPermission(PERMISSIONS.RESULT_READ) },
          ],
          extras: SECONDARY_NAV_IDS,
        };
      }

      function renderDashboardHeroCopy() {
        const blueprint = dashboardBlueprint();
        const title = document.getElementById("dashboardHeroTitle");
        const desc = document.getElementById("dashboardHeroDesc");
        if (title) title.textContent = blueprint.title;
        if (desc) desc.textContent = blueprint.desc;
      }

      function renderDashboardBusinessLanes() {
        const root = document.getElementById("dashboardLanes");
        if (!root) return;
        const lanes = dashboardBlueprint().steps;

        root.innerHTML = lanes
          .map(
            (item) => `<article class="stacking-path-card business-lane-card">
              <div class="stacking-card-kicker">步骤 ${escapeHtml(item.code)}</div>
              <h3>${escapeHtml(item.title)}</h3>
              <p>${escapeHtml(item.desc)}</p>
              <button class="ghost btn-auto" ${item.enabled ? `onclick="switchPage('${item.page}')"` : "disabled"}>${escapeHtml(item.enabled ? item.action : "当前角色不可操作")}</button>
            </article>`
          )
          .join("");
      }

      function renderDashboardQuickActions() {
        const quick = document.getElementById("dashboardQuick");
        if (!quick) return;
        const selected = (dashboardBlueprint().extras || [])
          .filter((id) => hasPermission(pageConfig(id)?.perm))
          .map((id) => ({
            id,
            code: flowStep(id).code,
            title: pageConfig(id).label,
            desc: PAGE_META[id]?.desc || flowStep(id).desc,
            action: `进入${pageConfig(id).label}`,
          }));

        if (!selected.length) {
          renderEmpty("dashboardQuick", "当前角色没有额外入口。");
          return;
        }

        quick.innerHTML = selected
          .map(
            (item, index) => `<article class="stacking-path-card">
            <div class="stacking-card-kicker">第 ${index + 1} 步 / ${escapeHtml(item.code)}</div>
            <h3>${escapeHtml(item.title)}</h3>
            <p>${escapeHtml(item.desc)}</p>
            <button class="ghost btn-auto" onclick="switchPage('${item.id}')">${escapeHtml(item.action)}</button>
          </article>`
          )
          .join("");
      }

      function renderDashboardRecentTasks() {
        const tasks = Array.isArray(state.tasks) ? state.tasks.slice(0, 5) : [];
        const root = document.getElementById("dashboardRecent");
        if (!root) return;
        if (!tasks.length) {
          if (hasPermission(PERMISSIONS.ASSET_UPLOAD)) {
            writeOutput(
              "dashboardRecent",
              `<div class="empty"><div class="empty-illus"></div>当前还没有任务记录。<div class="banner-gap"></div>${primaryActionButtonHtml(
                "上传资产",
                "switchPage('assets')"
              )}</div>`
            );
          } else {
            renderEmpty("dashboardRecent", "当前还没有任务记录。");
          }
          return;
        }

        const cards = tasks
          .map(
            (task) => `<article class="minimal-item">
            <div class="minimal-head">
              <div>
                <div class="minimal-kicker">任务</div>
                <h3 class="minimal-title mono">${escapeHtml(safe(task.id))}</h3>
              </div>
              ${statusTag(task.status)}
            </div>
            <div class="minimal-meta">${escapeHtml(taskTypeLabel(task.task_type))} · ${escapeHtml(formatTime(task.created_at))}</div>
            <div class="inline-actions">
                <button class="ghost btn-auto" onclick="openTaskFromDashboard('${escapeHtml(safe(task.id))}')">任务监控</button>
                <button class="ghost btn-auto" onclick="syncTaskIdInputs('${escapeHtml(safe(task.id))}'); switchPage('results')">查看结果</button>
              </div>
          </article>`
          )
          .join("");

        writeOutput("dashboardRecent", `<div class="minimal-list">${cards}</div>`);
      }

      function openTaskFromDashboard(taskId) {
        syncTaskIdInputs(taskId);
        state.lastTaskId = taskId;
        switchPage("task-monitor");
        toast("已从工作台打开任务监控页");
      }

      async function queryTask(button) {
        const section = document.getElementById("taskStatusSection");
        if (section) section.classList.remove("hidden");
        setButtonLoading(button, true, "查询中");
        setPanelLoading("taskStatusOut", true);
        try {
          if (!validateRequiredField("monitorTaskId", "请输入任务ID")) throw new Error("请输入任务ID");
          const taskId = document.getElementById("monitorTaskId").value.trim();
          const data = await fetchTaskStatus(taskId);
          if (data.status === "SUCCEEDED") {
            toast("任务已成功，可查询结果", "ok");
          } else {
            toast(`任务状态：${data.status}`, "warn");
          }
        } catch (e) {
          renderTaskStatus({ error: e.message }, "err");
          toast(`任务查询失败：${e.message}`, "err");
        } finally {
          setButtonLoading(button, false);
          setPanelLoading("taskStatusOut", false);
        }
      }

      async function queryResults(button) {
        const resultSection = document.getElementById("resultResultSection");
        if (resultSection) resultSection.classList.remove("hidden");
        const exportSection = document.getElementById("resultExportSection");
        if (exportSection) exportSection.classList.add("hidden");
        setButtonLoading(button, true, "查询中");
        setPanelLoading("resultOut", true);
        try {
          if (!validateRequiredField("resultTaskId", "请输入任务ID")) throw new Error("请输入任务ID");
          const taskId = document.getElementById("resultTaskId").value.trim();
          state.lastTaskId = taskId;
          syncTaskIdInputs(taskId);
          const data = await api(`/results?task_id=${encodeURIComponent(taskId)}`);
          renderResults(data, "ok");
          toast("结果查询成功", "ok");
        } catch (e) {
          renderResults([], "err", e.message);
          toast(`结果查询失败：${e.message}`, "err");
        } finally {
          setButtonLoading(button, false);
          setPanelLoading("resultOut", false);
        }
      }

      function renderResultExport(data, kind = "ok") {
        const payload = sanitizeForView(data, "resultExportOutMaskTip");
        const section = document.getElementById("resultExportSection");
        if (section) section.classList.remove("hidden");
        if (kind === "err") {
          renderErrorState(
            "resultExportOut",
            "结果导出失败",
            payload.error || "-",
            [
              { label: "重新查询结果", action: "queryResults(document.getElementById('btnResultQuery'))", primary: true },
              { label: "查看审计", action: "switchPage('audit')" },
            ]
          );
          return;
        }

        writeOutput(
          "resultExportOut",
          `<div class="asset-result-card">
            <div class="banner ok">
              <div class="banner-title">结果导出已生成</div>
            </div>
            ${kvGrid([
              { label: "任务ID", value: payload.task_id || "-", mono: true },
              { label: "导出条数", value: payload.count ?? "-" },
            ])}
            <div class="action-strip">
              ${actionButtonHtml("查看审计", `document.getElementById('auditAction').value='RESULT_EXPORT'; switchPage('audit')`)}
              ${actionButtonHtml("继续看结果", `switchPage('results')`)}
            </div>
          </div>`
        );
      }

      async function exportResults(button) {
        const section = document.getElementById("resultExportSection");
        if (section) section.classList.remove("hidden");
        setButtonLoading(button, true, "导出中");
        setPanelLoading("resultExportOut", true);
        try {
          if (!validateRequiredField("resultTaskId", "请输入任务ID")) throw new Error("请输入任务ID");
          const taskId = document.getElementById("resultTaskId").value.trim();
          const data = await api(`/results/export?task_id=${encodeURIComponent(taskId)}`);
          renderResultExport(data, "ok");
          toast("结果导出成功，已写审计", "ok");
        } catch (e) {
          renderResultExport({ error: e.message }, "err");
          toast(`结果导出失败：${e.message}`, "err");
        } finally {
          setButtonLoading(button, false);
          setPanelLoading("resultExportOut", false);
        }
      }

      function summarizeAuditDetail(detail) {
        if (!detail || typeof detail !== "object") return "-";
        return Object.entries(detail)
          .slice(0, 4)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join("|") : typeof v === "object" ? "[对象]" : safe(v)}`)
          .join("；");
      }

      function summarizeAuditRows(rows) {
        const list = Array.isArray(rows) ? rows : [];
        const actors = new Set(list.map((row) => row.actor_username).filter(Boolean));
        const keyOps = list.filter((row) =>
          ["MODEL_RELEASE", "MODEL_DOWNLOAD", "RESULT_EXPORT", "PIPELINE_RELEASE", "ORCHESTRATOR_RUN"].includes(
            String(row.action || "").toUpperCase()
          )
        ).length;
        return {
          count: list.length,
          actors: actors.size,
          keyOps,
        };
      }

      function renderAudit(rows, kind = "ok", errMsg = "") {
        const section = document.getElementById("auditResultSection");
        if (section) section.classList.remove("hidden");
        const data = sanitizeForView(Array.isArray(rows) ? rows : [], "auditOutMaskTip");
        if (!data.length) {
          state.visibleAuditRows = [];
          if (kind === "err") {
            renderErrorState(
              "auditOut",
              "审计查询失败",
              errMsg || "-",
              [
                { label: "重新查询", action: "queryAudit(document.getElementById('btnAuditQuery'))", primary: true },
                { label: "检查筛选条件", action: "focusField('auditAction')" },
              ]
            );
          } else {
            renderStatePanel("auditOut", {
              tone: "warn",
              title: "没有匹配的审计记录",
              message: "当前筛选条件下没有结果。",
              tip: "可以清空动作或资源筛选后再查一次。",
              actions: [
                {
                  label: "清空筛选",
                  action:
                    "document.getElementById('auditAction').value='';document.getElementById('auditActorServer').value='';document.getElementById('auditResourceType').value='';document.getElementById('auditResourceId').value='';document.getElementById('auditStartTime').value='';document.getElementById('auditEndTime').value='';",
                  primary: true,
                },
                { label: "重新查询", action: "queryAudit(document.getElementById('btnAuditQuery'))" },
              ],
            });
          }
          return;
        }

        const metrics = summarizeAuditRows(data);
        state.visibleAuditRows = data;
        const cards = data
          .map(
            (row, index) => `<article class="audit-item">
              <div class="result-head">
                <div class="result-title"><span class="mono">${escapeHtml(safe(row.action))}</span></div>
                <div class="inline-actions">
                  <span class="status neutral">${escapeHtml(safe(row.resource_type || "-"))}</span>
                  <button class="ghost btn-auto" onclick="showAuditDetail(${index})">详情</button>
                </div>
              </div>
              ${kvGrid([
                { label: "时间", value: formatTime(row.created_at) },
                { label: "操作人", value: row.actor_username || "-" },
                { label: "资源ID", value: row.resource_id || "-", mono: true },
                { label: "摘要", value: summarizeAuditDetail(row.detail) || "-" },
              ])}
            </article>`
          )
          .join("");

        writeOutput(
          "auditOut",
          `<div class="asset-result-card">
            ${kvGrid([
              { label: "日志总数", value: metrics.count },
              { label: "操作人数量", value: metrics.actors },
              { label: "关键动作", value: metrics.keyOps },
            ])}
            <div class="audit-list">${cards}</div>
          </div>`
        );
      }

      async function queryAudit(button) {
        const section = document.getElementById("auditResultSection");
        if (section) section.classList.remove("hidden");
        setButtonLoading(button, true, "查询中");
        setPanelLoading("auditOut", true);
        try {
          const action = document.getElementById("auditAction").value.trim();
          const actorUsername = document.getElementById("auditActorServer").value.trim();
          const resourceType = document.getElementById("auditResourceType").value.trim();
          const resourceId = document.getElementById("auditResourceId").value.trim();
          const startTime = document.getElementById("auditStartTime").value.trim();
          const endTime = document.getElementById("auditEndTime").value.trim();
          const limit = document.getElementById("auditLimit").value.trim() || "50";
          clearFieldError("auditLimit");
          const params = new URLSearchParams({ limit });
          if (startTime && Number.isNaN(new Date(startTime).getTime())) throw new Error("开始时间格式错误");
          if (endTime && Number.isNaN(new Date(endTime).getTime())) throw new Error("结束时间格式错误");
          if (!/^\d+$/.test(limit) || Number(limit) <= 0) {
            setFieldError("auditLimit", "返回条数必须是正整数");
            focusField("auditLimit");
            throw new Error("返回条数必须是正整数");
          }
          if (action) params.set("action", action);
          if (actorUsername) params.set("actor_username", actorUsername);
          if (resourceType) params.set("resource_type", resourceType);
          if (resourceId) params.set("resource_id", resourceId);
          if (startTime) params.set("start_time", new Date(startTime).toISOString());
          if (endTime) params.set("end_time", new Date(endTime).toISOString());
          const data = await api(`/audit?${params.toString()}`);
          state.auditRows = Array.isArray(data) ? data : [];
          renderAudit(state.auditRows, "ok");
          toast("审计查询成功", "ok");
        } catch (e) {
          state.auditRows = [];
          renderAudit([], "err", e.message);
          toast(`审计查询失败：${e.message}`, "err");
        } finally {
          setButtonLoading(button, false);
          setPanelLoading("auditOut", false);
        }
      }

      async function refreshDashboard() {
        const statusEl = document.getElementById("dashboardStatus");
        if (statusEl) statusEl.textContent = "加载中...";
        let modelCount = "-";
        let taskCount = "-";
        let succeeded = "-";
        let alerts = "-";

        try {
          if (hasPermission(PERMISSIONS.MODEL_VIEW)) {
            const models = await api("/models");
            state.models = Array.isArray(models) ? models : [];
            modelCount = String(state.models.length);
            const pipelines = await api("/pipelines");
            state.pipelines = Array.isArray(pipelines) ? pipelines : [];
          }

          if (hasPermission(PERMISSIONS.RESULT_READ) || hasPermission(PERMISSIONS.TASK_CREATE)) {
            const tasks = await api("/tasks");
            state.tasks = Array.isArray(tasks) ? tasks : [];
            taskCount = String(state.tasks.length);
            succeeded = String(state.tasks.filter((x) => x.status === "SUCCEEDED").length);

            if (hasPermission(PERMISSIONS.RESULT_READ) && state.tasks[0]?.id) {
              const latestResults = await api(`/results?task_id=${encodeURIComponent(state.tasks[0].id)}`);
              alerts = String((Array.isArray(latestResults) ? latestResults : []).filter((x) => x.alert_level && x.alert_level !== "INFO").length);
            } else {
              alerts = "0";
            }
          }

          if (statusEl) statusEl.textContent = "指标已更新。";
        } catch (e) {
          if (statusEl) statusEl.textContent = `指标加载部分失败：${e.message}`;
        }

        document.getElementById("mModels").textContent = modelCount;
        document.getElementById("mTasks").textContent = taskCount;
        document.getElementById("mSucceeded").textContent = succeeded;
        document.getElementById("mAlerts").textContent = alerts;
        renderDashboardHeroCopy();
        renderDashboardHeroActions();
        renderDashboardBusinessLanes();
        renderDashboardQuickActions();
        renderDashboardRecentTasks();
      }

      function initializeGuidanceStates() {
        renderEmpty(
          "assetOut",
          "上传成功后，这里会返回资产 ID、用途和下一步入口。",
          "还没有上传资产",
          [
            { label: "选择文件", action: "focusField('assetFile')", primary: true },
            { label: "检查用途", action: "focusField('assetPurpose')" },
          ]
        );
        renderEmpty(
          "taskRecommendOut",
          "只有在主模型调度兼容模式下才需要这一步。",
          "需要时再生成推荐结果",
          [
            { label: "切换为主模型调度", action: "document.getElementById('schedulerMode').value='master';updateTaskSchedulerMode();focusField('taskIntent')", primary: true },
            { label: "继续填写任务", action: "focusField('assetId')" },
          ]
        );
        renderEmpty(
          "taskOut",
          "填好资产 ID 和执行入口后，创建结果会显示在这里。",
          "还没有创建任务",
          [
            { label: "填写资产ID", action: "focusField('assetId')", primary: true },
            { label: "选择执行入口", action: "focusField('schedulerMode')" },
          ]
        );
        renderEmpty(
          "taskStatusOut",
          "输入任务 ID 后即可查看执行状态和下一步入口。",
          "还没有查询任务",
          [
            { label: "输入任务ID", action: "focusField('monitorTaskId')", primary: true },
            state.lastTaskId ? { label: "带入最近任务", action: `document.getElementById('monitorTaskId').value='${escapeHtml(safe(state.lastTaskId))}'` } : null,
          ]
        );
        renderEmpty(
          "resultOut",
          "任务成功后，结构化结果和截图会显示在这里。",
          "还没有查询结果",
          [
            { label: "输入任务ID", action: "focusField('resultTaskId')", primary: true },
            { label: "查看任务监控", action: "switchPage('task-monitor')" },
          ]
        );
        renderEmpty(
          "resultExportOut",
          "需要留痕时，再从结果页导出摘要。",
          "还没有导出结果摘要",
          [
            { label: "先查询结果", action: "queryResults(document.getElementById('btnResultQuery'))", primary: true },
            { label: "查看审计", action: "switchPage('audit')" },
          ]
        );
        renderEmpty(
          "auditOut",
          "输入动作、人或资源条件后，查询结果会显示在这里。",
          "还没有查询审计日志",
          [
            { label: "输入动作", action: "focusField('auditAction')", primary: true },
            { label: "查询审计日志", action: "queryAudit(document.getElementById('btnAuditQuery'))" },
          ]
        );
      }

      function attachFieldValidation() {
        document.getElementById("username")?.addEventListener("blur", (e) => {
          setFieldError("username", e.target.value.trim() ? "" : "请输入账号");
        });
        document.getElementById("password")?.addEventListener("blur", (e) => {
          setFieldError("password", e.target.value ? "" : "请输入密码");
        });
      }

      async function bootstrap() {
        setTheme(localStorage.getItem("rv_theme") || "light");
        attachFieldValidation();
        attachGlobalShortcuts();
        attachPageControls();
        updateModelTypeHints();
        updateTaskSchedulerMode();
        updateTaskMonitorBadge();
        initializeGuidanceStates();

        if (!state.token) {
          await checkHealth();
          return;
        }

        try {
          state.user = await api("/users/me");
          state.permissions = permissionsFromUser(state.user);
          document.getElementById("loginView").classList.add("hidden");
          document.getElementById("mainView").classList.remove("hidden");
          applyRoleUI();
          buildNav();
          await checkHealth();
          await refreshDashboard();
          toast("已恢复登录会话", "ok");
        } catch {
          localStorage.removeItem("rv_token");
          state.token = "";
          state.user = null;
          state.permissions = new Set();
          await checkHealth();
        }
      }

      bootstrap();
