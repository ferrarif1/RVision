# 动态待办清单（2026-03-11）

- Owner: Engineering
- Status: In Execution
- Last Updated: 2026-03-11 08:52 CST
- Scope: 作为当前持续推进的动态执行面板，记录“正在做 / 下一步 / 排队中 / 已完成”，并允许随时插入新需求
- Source of Truth:
  - 当前真实执行盘点：[current_execution_backlog_2026-03-10.md](./current_execution_backlog_2026-03-10.md)
  - 真实运行审计：[../qa/live_chain_audit_2026-03-10.md](../qa/live_chain_audit_2026-03-10.md)
  - 浏览器走查清单：[../qa/browser_walkthrough_checklist_2026-03-11.md](../qa/browser_walkthrough_checklist_2026-03-11.md)

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

### T1. 全站控制台页继续去技术噪音

- Priority: P0
- Status: In Progress
- Why:
  - 任务页、结果页已经收得较好；训练、模型、流水线三页虽然已经补工作台概览和卡片摘要，但默认视图里仍有技术字段和工程味。
- Done When:
  - 训练 / 模型 / 流水线三页默认视图都优先呈现“当前状态 + 下一步动作 + 关键摘要”
  - 长 ID / hash / 内部状态只出现在 `技术详情`
  - 关键列表和工作台之间的视觉节奏一致
- Evidence:
  - `frontend/src/pages/index.js`
  - `frontend/assets/app.css`
  - `docs/demo.md`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### T2. 页面级人工走查制度化

- Priority: P0
- Status: In Progress
- Why:
  - 当前已有多轮真实 API smoke test，但还缺正式的页面级视觉与交互证据。
- Done When:
  - 至少完成任务页、结果页、训练页、模型页、流水线页的一轮逐项走查
  - 走查结果以文档形式沉淀，而不是口头描述
- Evidence:
  - `docs/qa/browser_walkthrough_checklist_2026-03-11.md`

## 2. 下一步自动执行

### T3. 任务页 / 结果页继续做页面级收边

- Priority: P1
- Status: In Progress
- Why:
  - 这是当前最常用的业务入口，任何长文本、折叠区、回跳问题都会直接影响感知。
- Done When:
  - 回跳链路、批量结果展开、长文本、技术详情折叠都按走查清单验证并修一轮
- Evidence:
  - `frontend/src/pages/index.js`
  - `docs/qa/browser_walkthrough_checklist_2026-03-11.md`

### T4. 统一错误提示模板

- Priority: P1
- Status: Ready
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

### T6. 数据保留策略产品化

- Priority: P2
- Status: Queued
- Why:
  - 目前有脚本，没有统一入口和清理策略展示。
- Done When:
  - 至少形成统一入口、预览、执行、审计四件套
- Evidence:
  - `docker/scripts/cleanup_*`
  - `docs/product/current_execution_backlog_2026-03-10.md`

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
