# RVision 前端高效率重构任务书

你是资深 AI 产品架构师、前端架构师、全栈工程师。  
请基于当前仓库 **ferrarif1/RVision** 的现状，执行一次 **“高效率、低推翻率、以 LLM 为入口的整体交互重构”**。

最重要‼️：
根据https://github.com/alibaba/page-agent去实现llm接入 重构项目交互
---

## 0. 执行原则

这次不是推倒重来，也不是单纯补几个导航按钮。  
目标是：**在尽量复用现有功能和接口的前提下，把产品入口范式从传统控制台改成“LLM 对话驱动 + 专家模式兜底”的双模式 AI 控制台，两者可自由互相切换。**

必须遵守以下原则：

1. **优先复用，避免推翻**
  - 保留现有后端接口、RBAC、capabilities、业务对象、数据结构
  - 保留现有页面能力，不要把已完成模块做丢
  - 优先重构“入口、路由、编排层、布局层”，再复用原页面
2. **先做真流程，再做真智能**
  - 先把“LLM 首页 + workflow 状态机 + 页面跳转与引导”做好
  - 当前阶段可先用 mock / rule-based intent parser
  - 不要求你先接真实大模型后端，先把交互架构搭好
3. **优先用户路径，不优先技术炫技**
  - 用户一登录，应先看到“告诉我你想完成什么”
  - 不应先看到复杂 Dashboard、大量参数表单、过深菜单
  - 高级参数默认折叠，仅在需要时展开
4. **不允许只做表面聊天框**
  - 聊天框不能是装饰，必须成为业务流程入口
  - 用户输入需求后，系统必须能引导到上传、训练、选模、发布、结果查看、排障等下一步动作

---

## 1. 你必须先理解的当前项目现状

请基于当前仓库代码现状工作，不要臆想系统从零开始。

### 1.1 当前已具备且必须复用的能力

本项目已经具备以下核心能力，请复用而不是重写：

- 中心端一键部署、边缘 Agent、模型提交/审批/发布、结果回传、审计闭环
- JWT + RBAC，前后端通过 `/auth/login`、`/users/me` 和 `capabilities` 对齐权限
- 前端控制台已有模块：
  - Dashboard / 工作台
  - Assets / 资产上传
  - Tasks / 任务创建与任务监控
  - Results / 结果中心
  - Models / 模型中心
  - Pipelines / 流水线注册表
  - Audit / 审计日志
- 训练控制面已有最小闭环：
  - Job
  - worker 注册/心跳
  - 受控拉取训练资产/基线模型
  - 候选模型自动回收入库
  - 状态回传
- 但尚未完成生产级真实训练引擎、完整调度治理、长日志流等，因此不要把“全自动智能训练平台”误做成已完成

### 1.2 当前前端与实现约束

你必须尽量遵守当前项目已有前端约束：

- 不引入 React/Vue 等大框架，除非你确认当前代码已完全不适合维护，且必须说明收益
- 优先沿用当前轻前端结构
- 优先沿用：
  - `frontend/index.html`
  - `frontend/assets/app.js`
  - `frontend/assets/app.css`
- 路由优先使用 hash router（`location.hash`）
- 权限控制继续使用 capabilities 驱动导航和页面访问

### 1.3 当前交互问题（你要解决的核心）

当前项目虽然功能闭环已经比较完整，但交互范式仍偏“传统后台”：

- 用户进入后仍需理解菜单结构，才能知道先做什么
- 页面入口较分散，用户路径偏深
- “先干什么、后干什么”不够清晰
- 高阶操作（训练、发布、验证、回灌）仍然偏专业控制台思路
- 缺乏真正的“智能入口”
- 旧的 UI 重构方向主要解决导航完整性，但还没有升级成“LLM 驱动入口页”的未来应用形态

所以本次重构目标不是“小修小补”，而是：

> **让首页成为智能入口页，让现有页面成为被 AI 调用或人工进入的专家能力页。**

---

## 2. 本次重构的总目标

请将系统改造成一个 **双模式 AI 控制台**：

### 模式 A：AI Workspace（默认首页）

登录后默认进入 AI Workspace，而不是传统 Dashboard。

AI Workspace 必须具备：

- 一个醒目的主对话框，作为整个产品的主入口
- 用户可直接输入需求，例如：
  - 帮我训练一个车号识别模型
  - 上传这批图片并生成标注任务
  - 用最新模型跑一下这批图片
  - 把最新审批通过的模型发布到 buyer A
  - 看一下最近失败的任务
  - 为什么训练作业还没开始
- 系统识别意图后，生成下一步引导动作
- 引导动作必须能打通现有业务模块，而不是只回复文本

### 模式 B：Expert Console（手动专家模式）

保留传统控制台，但降级为第二入口。

要求：

- 专业用户仍可进入 Models / Assets / Tasks / Results / Pipelines / Devices / Audit / Settings
- 专业用户仍可手动设置训练参数、任务参数、模型版本、目标设备等
- AI 模式与手动模式必须可双向跳转：
  - AI 推荐参数后，一键进入“高级参数页”
  - 手动页中也可点击“交给 AI 推荐”

---

## 3. 重构策略：必须按“高效率优先”执行

本次不要全面重写现有业务页面。  
请按如下优先级推进：

### Phase 1：先重构壳子与入口（最高优先级）

先完成：

1. 新的 App Shell
  - Sidebar
  - Topbar
  - Breadcrumb
  - 主内容区
  - 用户菜单与 Logout
  - 返回机制
  - 当前页高亮
  - 本地记忆上次访问页
2. 登录后默认进入 `#/ai`
  - 不再默认进入传统 Dashboard
  - Dashboard 成为 Expert Console 中的一个页面
3. 一级入口变成两个：
  - `AI Workspace`
  - `Expert Console`

### Phase 2：实现 AI Home + workflow 骨架

先做“假智能、真流程”：

1. 大号主对话框
2. Prompt chips
3. 意图识别（先 mock / rule-based）
4. Action card
5. Confirmation card
6. Workflow stepper
7. Pending confirmations 区
8. Recent actions 区

### Phase 3：把现有页面改造成“可被 AI 调用的流程节点”

优先接入以下能力：

1. 资产上传
2. 训练任务创建
3. 模型选择
4. 模型发布
5. 结果查看
6. 流程排障

要求：

- 不必重写底层业务逻辑
- 尽量通过轻量步骤页 / 抽屉 / 面板 / 预填表单复用现有页面
- 让 AI Home 成为这些流程的入口

### Phase 4：补齐专家模式、权限守卫与统一状态

完成：

- 403 / 404
- Devices 页面（即使暂时占位）
- Empty / Loading / Error 统一组件
- 所有页面可回到 AI Home 或 Expert Console
- 无权限时不崩溃

### Phase 5：预留真实 LLM orchestration 接口

最后再做：

- 可替换的 intent parser
- 可替换的 action planner
- 多轮上下文容器
- 未来真实 LLM API 接口占位

---

## 4. 新的信息架构（必须落实到代码）

请按下面结构重构：

### L1：AI Workspace

默认首页：`#/ai`

包含：

- 大型主对话框
- 对话历史（可选左侧窄栏）
- 推荐提示 chips
- 最近行动区
- 待确认事项区
- AI 推荐动作卡片

### L2：AI Workflow

路由示例：

- `#/ai/chat/:sessionId`
- `#/ai/workflow/upload`
- `#/ai/workflow/train`
- `#/ai/workflow/deploy`
- `#/ai/workflow/results`
- `#/ai/workflow/troubleshoot`

每个 workflow 都应是“轻量步骤式 UI”，而不是把用户直接扔进复杂后台页。

### L3：Expert Console

保留传统业务模块：

- `#/dashboard`
- `#/assets`
- `#/tasks`
- `#/results`
- `#/models`
- `#/pipelines`
- `#/devices`
- `#/audit`
- `#/settings`

---

## 5. 路由设计（必须实现）

请建立统一路由表，至少包括：

```js
const routes = [
  { path: '/login', component: LoginPage, public: true },

  { path: '/ai', component: AIHomePage, requiredCapabilities: [] },
  { path: '/ai/chat/:sessionId', component: AIChatPage, requiredCapabilities: [] },
  { path: '/ai/workflow/upload', component: AIUploadWorkflowPage, requiredCapabilities: [] },
  { path: '/ai/workflow/train', component: AITrainWorkflowPage, requiredCapabilities: [] },
  { path: '/ai/workflow/deploy', component: AIDeployWorkflowPage, requiredCapabilities: [] },
  { path: '/ai/workflow/results', component: AIResultsWorkflowPage, requiredCapabilities: [] },
  { path: '/ai/workflow/troubleshoot', component: AITroubleshootPage, requiredCapabilities: [] },

  { path: '/dashboard', component: DashboardPage, requiredCapabilities: [...] },
  { path: '/assets', component: AssetsPage, requiredCapabilities: [...] },
  { path: '/tasks', component: TasksPage, requiredCapabilities: [...] },
  { path: '/results', component: ResultsPage, requiredCapabilities: [...] },
  { path: '/models', component: ModelsPage, requiredCapabilities: [...] },
  { path: '/pipelines', component: PipelinesPage, requiredCapabilities: [...] },
  { path: '/devices', component: DevicesPage, requiredCapabilities: [...] },
  { path: '/audit', component: AuditPage, requiredCapabilities: [...] },
  { path: '/settings', component: SettingsPage, requiredCapabilities: [...] },

  { path: '/403', component: ForbiddenPage, public: true },
  { path: '/404', component: NotFoundPage, public: true },
]
```

