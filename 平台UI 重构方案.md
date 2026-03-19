# RVision 全站 AI 化重构任务书（全页面统一 ChatGPT 风格版）

你是资深 AI 产品架构师、前端架构师、全栈工程师、AI 应用工程师。  
请基于当前仓库 **ferrarif1/RVision** 的现状，执行一次 **“全站统一风格 + LLM 驱动交互 + 专家模式兜底 + 可接入本地/远程大模型”** 的高质量重构。

---

## 0. 本次重构的唯一核心目标

把 RVision 从“传统后台式模型平台”，重构成一个真正的 **AI Native 应用**：

- 不只是首页像 ChatGPT
- 而是**整个产品的所有页面**
  - 视觉风格一致
  - 文案风格一致
  - 交互节奏一致
  - 信息密度一致
  - 操作逻辑一致

最终目标不是“做一个像 ChatGPT 首页的壳子”，  
而是把整个 RVision 做成一个 **类似 ChatGPT 产品范式的 AI 工作台**：

- 首页是 AI 入口
- 各业务页面是 AI 流程节点
- 配置页支持接入用户自己的本地模型或 API Key
- 系统说明文档可作为 LLM 的工作上下文
- 用户与系统的主要交互方式，逐渐从“找菜单”升级为“说需求”

---

## 1. 必须实现的产品定位

重构后的 RVision 必须满足：

### 1.1 产品形态
它不是传统后台，不是大盘系统，不是 admin template 换皮。  
它是一个：

- **AI 驱动的模型工作台**
- **对话优先的任务入口**
- **流程化的业务执行界面**
- **手动专家模式兜底的专业控制台**

### 1.2 用户体验目标
用户进入系统后，应当感受到：

- 整个产品像一个统一的 AI 应用，而不是多个页面拼起来的系统
- 不需要先理解菜单结构
- 不需要先理解所有模块
- 只要告诉系统想做什么，系统就能理解、引导、执行
- 即使进入配置页、任务页、结果页、模型页，也仍然能明显感觉到这是同一个产品语言体系

---

## 2. 最高优先级要求：不是只有首页，全站都要统一

### 2.1 全站统一风格原则
以下要求适用于所有页面，而不是只有首页：

- 首页
- 资产页
- 任务页
- 结果页
- 模型页
- 流水线页
- 审计页
- 设置页
- AI 对话页
- workflow 页面
- expert console 页面
- 空状态、错误页、登录页、403/404

### 2.2 必须统一的 5 个层面

#### A. 视觉风格统一
所有页面都必须遵守统一设计语言：

- 极简
- 大留白
- 低噪声
- 弱装饰
- 中性配色为主
- 轻边框、轻阴影
- 信息不过载
- 字体清楚、行高舒展、排版克制

#### B. 文案风格统一
所有页面文案必须统一成同一套产品语气：

- 简短
- 清楚
- 自然
- 产品化
- 对用户友好
- 不像技术文档
- 不像售前方案
- 不像 PPT
- 不像后台说明书

禁止出现：
- 大段说明文字
- 官话
- 套话
- 过度技术术语堆砌
- 让用户自己理解系统结构的描述

#### C. 交互风格统一
所有页面都必须遵守：

- 渐进展开，而不是一次性暴露全部内容
- 先给用户主任务，再给高级参数
- 主操作永远清楚
- 次要操作弱化
- 支持从任何业务页回到 AI 入口
- 支持从 AI 入口跳到具体业务页
- 让用户始终感觉是在被系统引导，而不是自己在后台里摸索

#### D. 页面结构统一
每个页面都必须有一致的页面框架语言：

- 顶部区域
- 页面主标题
- 一句短说明（如有必要）
- 主内容区
- 次级操作区
- 返回路径明确
- 当前任务上下文明确
- 空状态 / 加载状态 / 错误状态风格统一

#### E. 组件语言统一
所有卡片、按钮、输入框、弹窗、抽屉、标签、列表、表单、步骤条、对话气泡，都必须来自同一套组件风格系统。

---

## 3. 首页不是唯一重点，整个产品要“ChatGPT 化”

### 3.1 首页要求
首页仍然是默认入口，路由 `#/ai`

首页要做到：

- 视觉中心只有一个大号输入框
- 让用户第一反应就是“直接告诉系统我要做什么”
- 有 prompt chips
- 有 Recent actions
- 有 Pending confirmations
- 但这些都不能喧宾夺主

### 3.2 非首页页面也必须 ChatGPT 化
不要求所有页面都长得像聊天页，  
但要求所有页面都遵守和 ChatGPT 产品同类的设计哲学：

- 清爽
- 克制
- 逻辑简单
- 页面主任务清晰
- 少而准的信息呈现
- 强调输入与操作，而不是信息堆砌
- 看起来像现代 AI 应用，而不是企业后台

### 3.3 不能出现“首页很高级，子页面很乱”的情况
禁止出现这种断裂感：

- 首页极简
- 进入模型页后变成传统后台
- 进入任务页后按钮满天飞
- 进入配置页后像运维面板
- 进入结果页后像旧式 admin 表格系统

必须做到：

> 首页、流程页、专家页、设置页，虽然职责不同，但都属于同一产品语言体系。

---

## 4. 核心双模式架构

### 模式 A：AI Workspace（默认）
路由：
- `#/ai`
- `#/ai/chat/:sessionId`
- `#/ai/workflow/...`

这是用户默认工作入口。

### 模式 B：Expert Console（兜底）
路由：
- `#/dashboard`
- `#/assets`
- `#/tasks`
- `#/results`
- `#/models`
- `#/pipelines`
- `#/devices`
- `#/audit`
- `#/settings`

这是专业用户手动操作入口。

### 双向互通必须做到
- AI 推荐动作后，可一键进入专家页深度编辑
- 专家页中可一键“交给 AI 继续”
- 用户在任意业务页都能回到 AI Workspace
- AI workflow 中可随时切换到 Expert Console
- 所有流程上下文应尽量保留，不要切换后丢状态

---

## 5. 必须新增：真正可配置的 LLM 接入能力

这部分是硬要求，必须做进系统，而不是留一句 TODO。

### 5.1 设置页必须支持用户自由配置模型来源
在 `#/settings` 中新增 **LLM Settings / AI Settings** 模块。

至少支持以下接入方式：

#### A. 本地大模型接入
允许用户配置本地兼容接口，例如：

- Ollama
- Local OpenAI-compatible server
- vLLM / LM Studio / Anything exposing OpenAI-style API
- 企业内网模型服务

配置字段建议包括：

- Provider name
- Base URL
- Model name
- API path（如有）
- API format type（OpenAI-compatible / custom）
- 是否启用流式输出
- timeout
- temperature / max_tokens 等默认参数
- 连接测试按钮

#### B. 第三方 API Key 接入
允许用户配置外部 API 服务，例如：

- OpenAI-compatible API
- Anthropic-compatible gateway（如采用适配层）
- 其他第三方模型服务
- 企业私有网关

配置字段建议包括：

- Provider
- API Key
- Base URL
- Model name
- Organization / Project（可选）
- 请求超时
- 默认 system prompt 选项
- 测试连接

#### C. 多配置共存
必须支持：

- 保存多个 provider 配置
- 选择默认 provider
- 按场景选择 provider
- 后续允许 workflow 指定使用哪个模型
- 区分管理员级配置与用户级配置（如果现有权限体系允许）

### 5.2 模型接入层必须抽象
不要把 LLM 调用写死在前端某一页。  
必须抽出统一 AI Provider Adapter 层，例如：

- provider registry
- request adapter
- response normalizer
- stream handler
- model capability descriptor

未来可以替换不同模型来源，而不推翻 UI。

---

## 6. 必须新增：系统说明文档注入机制

这部分是实现“真正 AI 化应用交互”的关键，必须做。

### 6.1 为什么必须做
如果没有系统说明文档 / 产品说明文档 / 能力边界说明给 LLM，  
那聊天框只会变成普通问答框，无法真正理解系统能做什么、该怎么引导用户。

所以系统必须支持把产品知识提供给 LLM，包括但不限于：

- 平台支持哪些能力
- 哪些页面能做什么
- 哪些角色有什么权限
- 哪些 workflow 可用
- 当前系统哪些功能已完成、哪些未完成
- 训练、发布、结果、审批、审计等流程逻辑
- 参数解释与业务含义
- 典型任务模板

### 6.2 必须支持的文档来源
至少支持以下两类：

#### A. 内置系统文档
由开发者维护的文档，例如：

- `docs/system_overview.md`
- `docs/capabilities.md`
- `docs/workflows.md`
- `docs/llm_operating_manual.md`

#### B. 管理员上传 / 配置文档
在设置页或管理页支持添加：

- markdown 文档
- 纯文本说明
- 简短知识条目
- 结构化 FAQ
- 操作指引
- 产品约束说明

### 6.3 文档如何参与 LLM 推理
必须实现一个基础机制，使 LLM 在回答和规划时，能拿到这些文档内容作为系统上下文。  
当前阶段不强求完整 RAG，但必须预留并实现最小可用结构：

- system prompt builder
- instruction pack loader
- context document loader
- per-workflow context assembly
- provider request payload composer

### 6.4 必须明确“功能边界”
系统文档中必须能告诉 LLM：

- 当前哪些功能是真实可执行的
- 哪些只是占位
- 哪些需要跳转专家页
- 哪些需要用户补充资料
- 哪些能力受权限限制

避免 LLM 胡乱承诺。

---

## 7. AI 不只是聊天，必须是“可执行交互”

### 7.1 禁止假 AI
禁止以下伪 AI 方案：

- 只有聊天框，没有动作能力
- 只会回答说明文字
- 不能跳转页面
- 不能预填参数
- 不能组织 workflow
- 不能结合系统文档理解真实业务
- 不能调用现有模块

### 7.2 真 AI 交互必须具备
用户输入一句话后，系统至少能：

- 识别意图
- 结合系统说明文档理解可执行路径
- 给出结构化动作结果
- 跳转到对应 workflow
- 预填表单
- 拉起确认卡片
- 调用已有业务页面
- 解释当前步骤为什么这样做
- 说明哪些需要用户确认

### 7.3 动作结果必须结构化
返回结果不能只有文本，必须支持：

- action cards
- confirmation cards
- workflow stepper
- parameter preview
- missing info request
- jump links
- retry / troubleshoot suggestions

---

## 8. 全站页面设计硬约束

### 8.1 视觉系统
全站统一：

- 主背景简洁
- 中性灰白黑为主
- 品牌色只做轻点缀
- 不要复杂渐变
- 不要企业大屏风
- 不要过重卡片风
- 不要过度图标化

### 8.2 排版系统
全站统一：

- 页面宽度与内容密度受控
- 标题层级清晰
- 行高足够
- 字号统一
- 保证文字清楚、舒适、不拥挤
- 说明文字控制长度
- 表单标签和帮助文案必须简洁

### 8.3 表单系统
所有表单页都要统一：

- 默认只展示核心字段
- 高级参数折叠
- 分组合理
- 字段说明简短清楚
- 支持 AI 推荐填充
- 支持用户手动修改

### 8.4 列表与表格系统
表格也要 AI 化和现代化：

- 优先突出“用户最关心的列”
- 支持自然语言筛选入口（后续可扩展）
- 操作按钮减少
- 行内动作简洁
- 不要把所有操作都平铺

---

## 9. 新的信息架构

### L1：AI Workspace
- `#/ai`
- `#/ai/chat/:sessionId`

### L2：AI Workflow
- `#/ai/workflow/upload`
- `#/ai/workflow/train`
- `#/ai/workflow/deploy`
- `#/ai/workflow/results`
- `#/ai/workflow/troubleshoot`

### L3：Expert Console
- `#/dashboard`
- `#/assets`
- `#/tasks`
- `#/results`
- `#/models`
- `#/pipelines`
- `#/devices`
- `#/audit`
- `#/settings`

### L4：System / States
- `#/login`
- `#/403`
- `#/404`

---

## 10. 设置页必须新增的内容

在 `#/settings` 中，除了原有内容外，至少新增以下分组：

### 10.1 AI Provider Settings
包括：

- 新增 provider
- 编辑 provider
- 删除 provider
- 设置默认 provider
- 测试连接
- 查看最近测试结果
- 选择请求格式类型
- 配置是否启用流式输出
- 配置默认模型参数

### 10.2 AI Knowledge Settings
包括：

- 系统说明文档列表
- 上传 / 编辑 / 删除文档
- 启用 / 停用某份文档
- 设置文档作用范围（全局 / 某 workflow）
- 文档更新时间
- 文档预览

### 10.3 AI Behavior Settings
包括：

- 默认 system prompt
- 是否启用“严格按系统文档回答”
- 是否允许自由生成建议
- 是否优先跳 workflow 而非纯文本
- 是否显示 AI 推理说明摘要
- 是否允许 AI 自动预填参数

---

## 11. 技术实现要求

### 11.1 保持当前项目约束
优先沿用现有：

- `frontend/index.html`
- `frontend/assets/app.js`
- `frontend/assets/app.css`
- hash router
- capabilities 权限体系

### 11.2 抽象出的新增模块
至少抽出以下模块：

#### UI / Layout
- `AppShell`
- `Sidebar`
- `Topbar`
- `PageHeader`
- `PromptComposer`
- `PromptChips`
- `ActionCard`
- `ConfirmationCard`
- `WorkflowStepper`
- `EmptyState`
- `LoadingState`
- `ErrorState`

#### AI Runtime
- `AIProviderRegistry`
- `AIProviderAdapter`
- `AIRequestBuilder`
- `AIResponseNormalizer`
- `AIContextAssembler`
- `AIDocumentStore`
- `AISessionStore`
- `AIIntentParser`
- `AIActionPlanner`

#### Settings / Docs
- `ProviderSettingsPanel`
- `KnowledgeSettingsPanel`
- `BehaviorSettingsPanel`
- `DocumentEditor`
- `DocumentPreview`
- `ConnectionTestPanel`

### 11.3 先做真流程，再接真模型
当前阶段可以先：

- 用 mock / rule-based intent parser
- 用 mock provider adapter
- 先打通配置结构和调用结构
- 再让真实 provider 接入

但注意：

> 前端交互和架构必须从一开始就按“未来真实 LLM 应用”来设计，不允许做成演示型假架构。

---

## 12. 明确禁止事项

禁止以下情况：

1. 只把首页改得像 ChatGPT，其他页面仍是旧后台
2. 只加聊天框，不做动作能力
3. 设置页不支持用户自由配置本地模型或 API Key
4. 没有系统说明文档注入机制
5. LLM 不知道系统能做什么却直接回答
6. 页面风格不统一，首页高级、子页混乱
7. 配置页做成复杂运维面板，难以上手
8. 子页面信息过密、按钮过多、解释过长
9. UI 看起来像传统 admin 模板
10. AI 模式和专家模式不能互通
11. 把现有业务能力做丢
12. 对未完成能力做虚假承诺

---

## 13. 实施顺序（必须遵守）

### Phase 1
先做：
- 全站设计语言统一
- App Shell
- 默认路由改为 `#/ai`
- 全站导航结构统一
- 首页 AI Workspace

### Phase 2
再做：
- AI chat / workflow 骨架
- action cards
- confirmation cards
- stepper
- Recent actions
- Pending confirmations

### Phase 3
再做：
- 资产、训练、部署、结果、排障等流程接入
- AI 与 Expert Console 双向跳转
- 统一空状态 / 错误状态 / 加载状态

### Phase 4
再做：
- `#/settings` 中的 AI Provider Settings
- AI Knowledge Settings
- AI Behavior Settings
- 文档注入机制
- provider adapter 机制
- connection test

### Phase 5
最后做：
- 真正的 provider 调用接入
- 多轮上下文
- 更完整的 action planner
- 后续 RAG / 检索增强预留

---

## 14. 最终交付要求

你最终必须输出：

### 14.1 代码改动
直接修改前端代码，完成全站统一风格与 AI 化交互重构

### 14.2 变更说明
列出：

- 改了哪些文件
- 新增了哪些组件
- 新增了哪些路由
- 哪些旧页面被复用
- AI Provider 是如何抽象的
- 系统说明文档如何接入
- AI 如何触发 workflow
- Expert Console 如何与 AI 互通

### 14.3 自检清单
必须逐项检查：

- 是否不是只有首页，而是全站风格统一
- 首页是否为真正 AI 入口
- 所有页面是否保持一致的产品语言
- 设置页是否支持本地模型 / API Key 接入
- 是否支持系统说明文档注入 LLM
- AI 是否能给出结构化动作而不是纯文本
- AI 与 Expert Console 是否双向互通
- 旧业务能力是否保留
- capabilities 是否仍有效
- 是否避免了传统后台化和假 AI 化

---

## 15. 成功标准

如果你做对了，最终产品应该具备这些特征：

- 用户登录后进入的是 AI Workspace，而不是传统后台
- 不只是首页，所有页面都能看出属于同一个 AI 产品
- 页面之间没有明显风格断裂
- 用户可自由接入本地大模型或第三方 API Key
- LLM 能结合系统说明文档理解系统真实能力
- AI 不只是聊天，而是真正能驱动业务流程
- 手动专家模式仍然存在，但不再是唯一入口
- 整个产品从“功能后台”升级为“AI Native 工作台”