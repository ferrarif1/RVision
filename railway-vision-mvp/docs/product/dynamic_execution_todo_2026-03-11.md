# 动态待办清单（2026-03-11）

- Owner: Engineering
- Status: In Execution
- Last Updated: 2026-03-12 10:22 CST
- Scope: 作为当前持续推进的动态执行面板，记录“正在做 / 下一步 / 排队中 / 已完成”，并允许随时插入新需求
- Source of Truth:
  - 当前真实执行盘点：[current_execution_backlog_2026-03-10.md](./current_execution_backlog_2026-03-10.md)
  - 真实运行审计：[../qa/live_chain_audit_2026-03-10.md](../qa/live_chain_audit_2026-03-10.md)
  - 浏览器走查清单：[../qa/browser_walkthrough_checklist_2026-03-11.md](../qa/browser_walkthrough_checklist_2026-03-11.md)
  - 新用户可用性审查：[novice_user_usability_audit_2026-03-11.md](./novice_user_usability_audit_2026-03-11.md)

## 使用规则

- 新需求进入后，先落到本文件，再决定是否插队。
- 每项任务都要记录：
  - `Priority`
  - `Status`
  - `Why`
  - `Done When`
  - `Evidence`
- 一轮代码变更完成后，必须同步更新：
  - 本清单状态
  - 相关业务/QA 文档

## 1. 正在执行

### ~~T1. 全站控制台页继续去技术噪音~~

- Priority: P0
- Status: Done
- Why:
  - 高复杂页面的“整页平铺”问题已经基本收口，但默认视图里仍有少量技术字段和工程味，需要继续做页面级收边。
- Done When:
  - ~~训练 / 模型 / 流水线三页默认视图都优先呈现“当前状态 + 下一步动作 + 关键摘要”~~
  - ~~长 ID / hash / 内部状态只出现在 `技术详情`~~
  - ~~关键列表和工作台之间的视觉节奏一致~~
  - ~~全站关键页面建立统一的高科技玻璃层、渐变光晕和顺滑 hover / 切换反馈~~
  - ~~高复杂功能页不再把多套功能直接堆在同一屏，而是通过页内导航或二级导航引导进入~~
- Evidence:
  - `frontend/src/pages/index.js`
  - `frontend/assets/app.css`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### ~~T2. 页面级人工走查制度化~~

- Priority: P0
- Status: Done
- Why:
  - 当前已有多轮真实 API smoke test，但还缺正式的页面级视觉与交互证据。
- Done When:
  - ~~至少完成任务页、结果页、训练页、模型页、流水线页的一轮逐项走查~~
  - ~~走查结果以文档形式沉淀，而不是口头描述~~
- Evidence:
  - `docs/qa/browser_walkthrough_checklist_2026-03-11.md`
  - `docs/qa/browser_walkthrough_report_2026-03-12.md`

### ~~T2b. 新用户视角的术语与流程减负~~

- Priority: P0
- Status: Done
- Why:
  - 虽然页面结构已经清楚很多，但从只懂少量概念的用户视角看，仍然存在术语负担和流程分叉过多的问题。
- Done When:
  - ~~高频页面默认视图里进一步减少平台内部术语~~
  - ~~上传资产 -> 识别 -> 复核 -> 训练 -> 验证 -> 审批 -> 发布 形成更明显的单一路径~~
  - ~~“把确认结果变成训练数据 / 待验证模型 / 审批 / 发布”等概念在 UI 中可自解释~~
  - ~~高频表单里的 `asset_id / worker / model_id / task_id` 默认改写成更自然的用户语言，技术词退到括号或技术详情~~
- Evidence:
  - `docs/product/novice_user_usability_audit_2026-03-11.md`
  - `frontend/src/pages/index.js`
  - `frontend/assets/app.css`
  - `docs/demo.md`

## 2. 下一步自动执行

### ~~T3. 任务页 / 结果页继续做页面级收边~~

- Priority: P1
- Status: Done
- Why:
  - 这是当前最常用的业务入口，任何长文本、折叠区、回跳问题都会直接影响感知。
- Done When:
  - ~~回跳链路、批量结果展开、长文本、技术详情折叠都按走查清单验证并修一轮~~
  - ~~首页与高频卡片里的长文件名、长版本号、长技术字段不会再把卡片或网格撑乱~~
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/qa/browser_walkthrough_checklist_2026-03-11.md`
  - `frontend/assets/app.css`
  - `docs/qa/browser_walkthrough_report_2026-03-12.md`

### T4. 统一错误提示模板

- Priority: P1
- Status: In Progress
- Why:
  - 仍有不少后端原始错误会直接露给用户，影响成熟度。
- Done When:
  - 任务创建 / 快速识别 / 训练 / 审批 / 发布 / 结果导出这几条主链都尽量显示“原因 + 影响 + 下一步”
- Evidence:
  - `backend/app/core/ui_errors.py`
  - `frontend/src/core/api.js`
  - `docs/product/current_execution_backlog_2026-03-10.md`

## 3. 排队中

### T5. OCR 真实泛化继续推进

- Priority: P1
- Status: Queued
- Why:
  - 这是最影响业务价值的核心能力缺口。
- Done When:
  - 陌生低清图的 `ocr_unavailable` 和低置信度比例继续下降
  - 形成更系统的 runtime eval 与难例桶
- Evidence:
  - `edge/inference/pipelines.py`
  - `docker/scripts/evaluate_car_number_ocr_samples.py`

### ~~T6. 数据保留策略产品化~~

- Priority: P2
- Status: Done
- Why:
  - 已完成一轮“仅保留车号 OCR 当前主链 + 当前目标检测模型”的实际清理，但仍然是脚本入口，还没有前台化。
- Done When:
  - ~~至少形成统一入口、预览、执行、审计四件套~~
- Evidence:
  - `backend/app/api/settings.py`
  - `backend/app/services/data_governance_service.py`
  - `frontend/src/pages/index.js`
  - `docker/scripts/cleanup_*`

### T7. 审批治理补全

- Priority: P2
- Status: Queued
- Why:
  - 当前审批更偏 demo 闭环，还缺拒绝、补材料、证据包导出。
- Done When:
  - 审批工作台支持拒绝 / 要求补材料 / 导出证据包
- Evidence:
  - `backend/app/api/models.py`
  - `frontend/src/pages/index.js`

## 4. 已完成（最近）

### D35. 页面级走查与默认术语减负阶段性收口

- Status: Done
- Scope:
  - 任务、结果、训练、模型、流水线、资产、审计、首页、车号文本复核都已完成“页内导航 + 默认视图减负 + 技术详情后置”
  - 高频默认术语已统一改成业务表达，工程词主要退到 `技术详情`
  - 页面级走查结果已形成正式报告，而不是只留在即时汇报里
- Evidence:
  - `docs/qa/browser_walkthrough_report_2026-03-12.md`
  - `frontend/src/pages/index.js`
  - `frontend/assets/app.css`
  - `docs/demo.md`

### D36. 前端高频错误提示模板扩展（Round 2）

- Status: Done
- Scope:
  - 将模型、流水线、资产、训练、数据集预览、ZIP 校验等高频后端原始报错，统一翻成可操作的中文提示
  - 保持“原因 + 建议下一步”语气，不再把接口原始英文直接暴露给用户
- Evidence:
  - `frontend/src/core/api.js`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D37. 设置页“数据治理”工作区与正式预览/执行接口

- Status: Done
- Scope:
  - 设置页新增 `数据治理` 工作区，统一承接“只保留当前车号演示主链 / 清理 synthetic 残留 / 裁剪旧 OCR 导出历史”
  - 后端新增 `/settings/data-governance` 预览接口和 `/settings/data-governance/run` 执行接口
  - 平台管理员可执行，买家等角色只读预览；两类操作都会写审计
- Evidence:
  - `backend/app/api/settings.py`
  - `backend/app/services/data_governance_service.py`
  - `frontend/src/pages/index.js`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D38. 登录失败 / 权限不足 / 训练机器鉴权失败改成结构化错误

- Status: Done
- Scope:
  - 登录失败、权限不足、训练机器/边缘设备凭据失败不再返回裸英文错误
  - 后端统一返回 `code + message + next_step`，前端可直接展示“原因 + 下一步”
- Evidence:
  - `backend/app/api/auth.py`
  - `backend/app/security/dependencies.py`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D1. 训练 / 模型 / 流水线页补统一工作台概览

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `frontend/assets/app.css`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D2. 三页主列表开始从重表格改成卡片摘要

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`

### D3. 页面级浏览器走查清单已建立

- Status: Done
- Evidence:
  - `docs/qa/browser_walkthrough_checklist_2026-03-11.md`
  - `docs/README.md`

### D4. 任务页 / 结果页默认视图继续去技术噪音

- Status: Done (Round 2)
- Evidence:
  - `frontend/src/pages/index.js`
  - `frontend/assets/app.css`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D5. 模型页拆成独立工作区

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `frontend/assets/app.css`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D6. 训练页 / 流水线页拆成独立工作区

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D7. 资产页 / 审计页 / 设备页拆成独立工作区

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D8. 资产页 / 审计页 / 设备页默认列表卡片化

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D9. 设置页 / 工作台总览继续去技术噪音

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D10. 训练页 / 任务详情页页面级收边（Round 1）

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/qa/browser_walkthrough_checklist_2026-03-11.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D13. 卡片列表长标题 / 长版本号 / 长编号系统性收边（Round 1）

- Status: Done
- Evidence:
  - `frontend/assets/app.css`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D14. 表格 / 工作台摘要 / 详情区长文本溢出修复（Round 2）

- Status: Done
- Evidence:
  - `frontend/assets/app.css`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D15. 详情页首屏 / 动作区 / 内联验证区溢出修复（Round 3）

- Status: Done
- Evidence:
  - `frontend/assets/app.css`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D30. 高复杂功能页导航化主任务基本收口

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D31. 模型页 / 流水线页残余工程术语继续减负

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D32. 指南页 / 训练机管理 / 训练协作列表继续去工程术语

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D33. 结果页 / 模型评估区继续去英文指标名

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D34. 训练页 / 任务页高频卡片继续去技术字段名

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D16. 任务页 / 结果页改成页内导航驱动

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D17. 模型页 / 训练页继续改成分步导航

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D18. 流水线页继续改成分步导航

- Status: Done
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D11. 全站工作台视觉系统强化（Round 1）

- Status: Done
- Evidence:
  - `frontend/assets/app.css`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D12. 历史数据按“当前车号示例主链”完成一轮真实清理

- Status: Done
- Scope:
  - 仅保留当前已发布 `car_number_ocr / object_detect / bolt_missing_detect / scene_router`
  - 仅保留车号 OCR 当前训练来源、原始本地训练素材、当前演示流水线
  - 删除旧候选模型、旧训练作业、历史重复 OCR 导出、`api-*` 回归残留、重复任务与截图
- Result:
  - `models: 30 -> 4`
  - `training_jobs: 28 -> 2`
  - `data_assets: 256 -> 15`
  - `dataset_versions: 52 -> 2`
  - `inference_tasks: 238 -> 16`
  - `inference_results: 35`（清理后）
- Evidence:
  - `docker/scripts/cleanup_keep_current_demo_chain.py`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D13. 卡片列表长标题 / 长版本号 / 长编号系统性收边（Round 1）

- Status: Done
- Scope:
  - 统一补齐 `selection-card / task-list-card / selection-summary / workbench-overview / metric-card / badge / mono / details-panel / page-hero-actions`
  - 目标是长文件名、长版本号、长 ID 不再把卡片、按钮区和 Hero 动作区撑坏
- Evidence:
  - `frontend/assets/app.css`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D12. 模型页 / 流水线页工作台视觉强化（Round 1）

- Status: Done
- Evidence:
  - `frontend/assets/app.css`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D13. 任务页 / 结果页高频卡片视觉强化（Round 1）

- Status: Done
- Evidence:
  - `frontend/assets/app.css`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D14. 新用户可用性审查已建立

- Status: Done
- Evidence:
  - `docs/product/novice_user_usability_audit_2026-03-11.md`

### D19. 车号文本复核页改成导航式工作区

- Status: Done
- Scope:
  - 将原本堆在一页里的筛选、样本队列、当前复核、导出训练四块拆成页内导航
  - 默认先看复核总览；选中样本后自动切到“当前样本复核”
  - 导出训练数据或直接开始训练时自动切到“导出与训练”
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D20. 工作台首页改成导航式入口

- Status: Done
- Scope:
  - 将首页“最近资产 / 最近模型 / 最近任务”从同屏平铺改成页内导航
  - 首页当前只默认展示工作台总览，其他最近数据按需进入
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D21. 任务详情页改成导航式详情页

- Status: Done
- Scope:
  - 将任务详情拆成 `执行结论 / 下一步动作 / 技术详情`
  - 默认先看执行结论，避免任务摘要、按钮区、原始 JSON 同屏平铺
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D22. 结果页“结果列表”改成二级导航

- Status: Done
- Scope:
  - 将结果列表内部拆成 `结果概览 / 模型表现 / 单条结果`
  - 查询成功后默认先看整体结论，不再把概览、模型表现和单条结果卡同时摊开
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D23. 训练页“训练机器”工作区改成二级导航

- Status: Done
- Scope:
  - 将训练页的“训练机器”拆成 `机器总览 / 登记与清理`
  - 默认先看节点健康和可用机器，管理动作后置
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D24. 训练页“训练总览”改成二级导航

- Status: Done
- Scope:
  - 将训练总览拆成 `运行告警 / 训练作业 / 训练结果摘要`
  - 默认先看运行告警；查看作业和训练摘要按需进入
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D25. 训练页“准备训练”改成二级导航

- Status: Done
- Scope:
  - 将“准备训练”拆成 `选择算法 / 选择训练机器`
  - 默认先选算法；选中算法后自动引导到训练机器
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D26. 模型页“模型总览”改成二级导航

- Status: Done
- Scope:
  - 将模型总览拆成 `工作台概览 / 模型列表`
  - 默认先看当前焦点模型的判断，再按需进入完整模型列表
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D27. 流水线页“流水线总览”改成二级导航

- Status: Done
- Scope:
  - 将流水线总览拆成 `工作台概览 / 流水线列表`
  - 默认先看当前焦点流水线的判断，再按需进入完整列表
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D28. 资产页“资产总览”改成二级导航

- Status: Done
- Scope:
  - 将资产总览拆成 `使用概览 / 资产列表`
  - 默认先看用途分布和推荐下一步动作，再按需进入完整资产列表
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D29. 审计页“审计总览”改成二级导航

- Status: Done
- Scope:
  - 将审计总览拆成 `工作台概览 / 最近动作`
  - 默认先看留痕摘要，浏览最近动作按需进入
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D30. 高可见术语继续中文化并降低工程味

- Status: Done
- Scope:
  - 继续清理训练页、任务页、结果页、模型页、流水线页里高频可见的技术术语
  - 将 `task_id / asset_id / model_id / pipeline_id / plugin / task_type / Worker / Loss Curve / Accuracy Curve`
    等用户默认可见文案替换成更自然的中文表达
  - 同步把结果导出、训练内联验证、车号文本复核和最近数据卡的提示语改得更接近业务动作
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D31. 默认可见区术语减负阶段性收口

- Status: Done
- Scope:
  - 将默认视图里高频出现的工程术语进一步替换为业务表达
  - 覆盖训练中心、任务中心、结果中心、模型中心、流水线中心、资产中心、车号文本复核
  - 将默认提示语、占位文案、成功提示和按钮文案改得更接近普通用户语言
- Done definition:
  - 高复杂页面默认视图不再优先暴露 `task_id / asset_id / model_id / pipeline_id / worker / plugin / bbox / engine / final_text`
  - 这类词保留在技术详情、代码内部或接口契约中
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

## 5. 插入新需求的规则

- 如果新需求直接阻断真实主链：
  - 插到 `正在执行`
- 如果新需求改善高频体验但不阻断主链：
  - 插到 `下一步自动执行`
- 如果新需求偏治理、自动化、后续增强：
  - 插到 `排队中`

## 6. 当前自动执行顺序

1. 继续收任务页 / 结果页的页面级细节，按 QA checklist 一项项修。
2. 回到训练 / 模型 / 流水线页，继续削弱默认技术字段和次级噪音。
3. 扩统一错误模板到更多高频链路。
4. 再继续推进 OCR 真实泛化。
