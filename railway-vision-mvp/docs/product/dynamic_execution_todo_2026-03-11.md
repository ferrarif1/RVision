# 动态待办清单（2026-03-11）

- Owner: Engineering
- Status: In Execution
- Last Updated: 2026-03-13 13:54 CST
- Scope: 当前持续推进的真实执行面板。只保留“仍未完成 / 正在推进 / 已验证完成”的事项，不保留重复里程碑和过时状态。
- Source of Truth:
  - 当前真实执行盘点：[current_execution_backlog_2026-03-10.md](./current_execution_backlog_2026-03-10.md)
  - 真实运行审计：[../qa/live_chain_audit_2026-03-10.md](../qa/live_chain_audit_2026-03-10.md)
  - 页面级走查清单：[../qa/browser_walkthrough_checklist_2026-03-11.md](../qa/browser_walkthrough_checklist_2026-03-11.md)
  - 巡检任务数据工作区：[railcar_inspection_data_workspace_2026-03-12.md](./railcar_inspection_data_workspace_2026-03-12.md)

## 使用规则

- 新需求先记入本文件，再决定是否插队。
- 每完成一段独立工作，主动收口：
  - 更新本清单
  - 更新相关业务/QA文档
  - 标记完成项为删除线
- 只记录真实落地能力，不把目标态写成已完成。

## 1. 当前主状态

- 平台主链已可运行：
  - 资产
  - 任务
  - 结果
  - 训练
  - 待验证模型
  - 审批
  - 发布
- 高复杂页面已完成“页内导航 + 默认视图减负 + 技术详情后置”。
- 高优先级错误提示模板已完成结构化统一。
- 数据治理已前台化。
- 审批治理已补齐“补材料 / 驳回 / 证据包”。
- 当前唯一持续中的核心主线：`T5 OCR 真实泛化继续推进`。

## 2. 已完成的核心任务

### ~~T1. 全站控制台页继续去技术噪音~~

- Priority: P0
- Status: Done
- Why:
  - 高复杂页面原先存在整页平铺、多功能堆叠、技术字段默认暴露的问题。
- Done:
  - ~~训练 / 模型 / 流水线 / 任务 / 结果 / 资产 / 审计 / 首页 / 车号文本复核完成页内导航化~~
  - ~~默认视图优先显示状态、下一步动作、业务摘要~~
  - ~~长 ID / hash / 内部状态后置到 `技术详情`~~
  - ~~统一玻璃层、渐变光晕、悬停反馈和选中态~~
- Evidence:
  - `frontend/src/pages/index.js`
  - `frontend/assets/app.css`
  - `docs/demo.md`
  - `docs/qa/browser_walkthrough_report_2026-03-12.md`

### ~~T2. 页面级人工走查制度化~~

- Priority: P0
- Status: Done
- Why:
  - 需要把“感觉页面顺了”变成正式 QA 证据。
- Done:
  - ~~关键页走查清单建立~~
  - ~~首轮走查报告沉淀~~
- Evidence:
  - `docs/qa/browser_walkthrough_checklist_2026-03-11.md`
  - `docs/qa/browser_walkthrough_report_2026-03-12.md`

### ~~T2b. 新用户视角的术语与流程减负~~

- Priority: P0
- Status: Done
- Why:
  - 默认可见区过去有大量平台内部术语，新用户不容易理解。
- Done:
  - ~~高频页面默认术语改成人话~~
  - ~~主路径尽量收成单一路径~~
  - ~~`asset_id / task_id / worker / model_id` 等默认转为业务语言~~
- Evidence:
  - `docs/product/novice_user_usability_audit_2026-03-11.md`
  - `frontend/src/pages/index.js`
  - `docs/demo.md`

### ~~T3. 任务页 / 结果页页面级收边~~

- Priority: P1
- Status: Done
- Why:
  - 这是最常用的入口，最容易暴露体验问题。
- Done:
  - ~~任务页拆成“快速识别 / 创建任务 / 可选模型 / 任务列表”~~
  - ~~结果页拆成“查询结果 / 下一步动作 / 变成训练数据 / 结果列表”~~
  - ~~任务页和结果页进一步完成二级导航自动切换~~
  - ~~长文本、长版本号、长 ID 溢出系统性修复~~
- Evidence:
  - `frontend/src/pages/index.js`
  - `frontend/assets/app.css`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### ~~T4. 统一错误提示模板~~

- Priority: P1
- Status: Done
- Why:
  - 主链大量原始英文错误会直接暴露给用户。
- Done:
  - ~~任务 / 结果 / 训练 / 模型 / 流水线 / 资产 / 边缘执行主链统一结构化错误~~
  - ~~前端统一按 `code / message / next_step` 展示~~
- Evidence:
  - `backend/app/core/ui_errors.py`
  - `frontend/src/core/api.js`
  - `backend/app/api/results.py`
  - `backend/app/api/edge.py`
  - `backend/app/api/training.py`
  - `backend/app/api/tasks.py`
  - `backend/app/api/models.py`
  - `backend/app/api/assets.py`

### ~~T6. 数据保留策略产品化~~

- Priority: P2
- Status: Done
- Why:
  - 历史噪音和 synthetic 残留清理原先只靠脚本。
- Done:
  - ~~设置页新增 `数据治理` 工作区~~
  - ~~支持预览、执行、权限和审计~~
- Evidence:
  - `backend/app/api/settings.py`
  - `backend/app/services/data_governance_service.py`
  - `frontend/src/pages/index.js`

### ~~T7. 审批治理补全~~

- Priority: P2
- Status: Done
- Why:
  - 原先审批只剩“通过”，没有治理闭环。
- Done:
  - ~~要求补材料~~
  - ~~驳回模型~~
  - ~~导出证据包~~
- Evidence:
  - `backend/app/api/models.py`
  - `frontend/src/pages/index.js`
  - `backend/tests/api_regression/test_models_release_gate.py`

## 3. 当前唯一持续主线

### T5. OCR 真实泛化继续推进

- Priority: P1
- Status: In Progress
- Why:
  - 这是当前最影响业务价值的核心能力缺口。
  - 车号不再能简单假设成固定 8 位数字。
  - 识别内容也不只限车号，已扩成正式巡检模型族。

#### 3.1 已经做完的部分

- 车号规则已从单一 `8 位数字` 升级成规则族：
  - 标准 8 位数字
  - 字母前缀数字编号
  - 紧凑型混合编号
- 巡检任务族已落地：
  - `car_number_ocr`
  - `inspection_mark_ocr`
  - `performance_mark_ocr`
  - `door_lock_state_detect`
  - `connector_defect_detect`
- 训练中心已接入巡检任务数据工作区：
  - 建议样本量
  - 拍摄距离 / 角度 / 图像要求
  - 验收目标
  - 结构化字段建议
- inspection/performance OCR 已具备：
  - 工作区模板
  - 代理裁剪
  - 自动建议
  - 通用复核页
  - 训练包导出
  - 导出训练资产
  - 直接创建训练作业
  - 待验证模型回收
  - 审批工作台可见
- inspection/performance OCR 风险治理已到位：
  - 审批工作台暴露 `proxy_truth_risk`
  - 默认阻止带代理真值继续正式训练
  - 只有显式允许“仅冷启动继续训练”才放行
- inspection OCR 人工替换工具链已补齐：
  - 原图联看
  - 代理替换队列 CSV 导出
  - 预检查 CSV 导入
  - CSV 导回
  - 人工替换工作包 ZIP
- inspection/performance OCR 自动建议已进入“高质量建议优先复核”阶段：
  - `仅看高质量建议`
  - `优先确认高质量建议`
  - `导出高质量建议队列`
  - `导出高质量建议包`

#### 3.2 当前真实状态

- `inspection_mark_ocr`
  - `row_count = 80`
  - `crop_ready_rows = 77`
  - `suggestion_rows = 59`
  - `high_quality_suggestion_rows = 51`
  - `high_quality_review_candidate_rows = 51`
  - `reviewed_rows = 9`
  - `manual_reviewed_rows = 3`
  - `proxy_seeded_rows = 6`
  - `training_readiness.status = cold_start_only`
- `performance_mark_ocr`
  - `row_count = 80`
  - `crop_ready_rows = 77`
  - `suggestion_rows = 57`
  - `high_quality_suggestion_rows = 45`
  - `reviewed_rows = 9`
  - `manual_reviewed_rows = 3`
  - `proxy_seeded_rows = 6`
- inspection/performance OCR 已完成至少一轮真实训练闭环：
  - 训练作业 `SUCCEEDED`
  - 新模型 `SUBMITTED`
  - 审批工作台可见

#### 3.3 当前真正阻断点

- inspection/performance OCR 不再缺：
  - 页面
  - 接口
  - 导出
  - 训练入口
  - 审批入口
- 当前真正阻断点只剩：
  - 还需要把 `proxy_seeded` 样本替换成真实 `final_text`
  - 让 inspection/performance OCR 从“仅冷启动可训练”推进到“可正常训练”

#### 3.4 这一主线的完成标准

- 陌生低清车号图的 `ocr_unavailable` 和低置信度比例继续下降
- 形成稳定 runtime eval 和难例桶
- `inspection_mark_ocr / performance_mark_ocr` 的真实人工真值继续增长
- `proxy_seeded_rows` 显著下降
- `training_readiness.status` 从 `cold_start_only` 推进到 `ready`
- 再跑出至少一轮更高真实真值占比的新训练作业与待验证模型

#### 3.5 证据

- `edge/inference/pipelines.py`
- `config/car_number_rules.json`
- `config/ocr_scene_profiles.json`
- `config/railcar_inspection_task_catalog.json`
- `config/railcar_inspection_dataset_blueprints.json`
- `backend/app/api/training.py`
- `frontend/src/pages/index.js`
- `docker/scripts/prepare_inspection_ocr_proxy_crops.py`
- `docker/scripts/generate_inspection_ocr_suggestions.py`
- `docker/scripts/bootstrap_inspection_labeling_workspace.py`
- `docker/scripts/build_inspection_task_dataset.py`
- `docker/scripts/seed_inspection_ocr_from_car_number_truth.py`
- `docs/product/railcar_robot_inspection_model_family_2026-03-12.md`
- `docs/product/railcar_inspection_data_workspace_2026-03-12.md`
- `docs/qa/ocr_generalization_iteration_2026-03-12.md`
- `docs/qa/live_chain_audit_2026-03-10.md`

## 4. 下一步自动执行

### N1. inspection/performance OCR 真实真值替换

- Priority: P1
- Status: Next
- Why:
  - 当前唯一真正阻断 inspection/performance OCR 继续迈进的就是 `proxy_seeded` 样本仍未替换完。
- Done When:
  - `inspection_mark_ocr.proxy_seeded_rows < 6`
  - `performance_mark_ocr.proxy_seeded_rows < 6`
  - `manual_reviewed_rows` 明显上升
  - 至少完成一轮新的真实 `final_text` 导入
- Evidence:
  - `demo_data/generated_datasets/inspection_mark_ocr_labeling/manifest.csv`
  - `demo_data/generated_datasets/performance_mark_ocr_labeling/manifest.csv`
  - `backend/app/api/training.py`

### N2. inspection/performance OCR 下一轮训练与审批验证

- Priority: P1
- Status: Next
- Why:
  - 只有替换真值后重新训练，才能验证风险是否真正下降。
- Done When:
  - 新训练作业 `SUCCEEDED`
  - 新待验证模型入库
  - 审批工作台里 `proxy_truth_risk` 弱化或数据比例下降
- Evidence:
  - `docs/qa/live_chain_audit_2026-03-10.md`
  - `docs/product/railcar_inspection_data_workspace_2026-03-12.md`

### N3. door_lock_state_detect / connector_defect_detect 进入真实样本闭环

- Priority: P2
- Status: Queued
- Why:
  - 这两类任务现在仍主要停在模板和准备度阶段。
- Done When:
  - 各自产出一版真实工作区样本
  - 各自产出一版 train/validation bundle
  - 至少一条训练作业闭环
- Evidence:
  - `demo_data/generated_datasets/door_lock_state_detect_labeling/`
  - `demo_data/generated_datasets/connector_defect_detect_labeling/`

## 5. 最近完成（保留最近一段）

### D68. inspection/performance OCR 代理裁剪与自动建议覆盖率提升

- Status: Done
- Result:
  - `inspection_mark_ocr.suggestion_rows = 59`
  - `performance_mark_ocr.suggestion_rows = 57`
- Evidence:
  - `config/railcar_inspection_dataset_blueprints.json`
  - `docker/scripts/prepare_inspection_ocr_proxy_crops.py`
  - `docker/scripts/generate_inspection_ocr_suggestions.py`

### D69. inspection/performance OCR 建议质量分层与优先复核队列

- Status: Done
- Result:
  - `inspection_mark_ocr.high_quality_suggestion_rows = 51`
  - `performance_mark_ocr.high_quality_suggestion_rows = 45`
- Evidence:
  - `backend/app/api/training.py`
  - `frontend/src/pages/index.js`

### D70. inspection/performance OCR 高质量建议导出与优先筛选闭环

- Status: Done
- Result:
  - 新增高质量建议专用导出接口
  - 复核页新增高质量建议专用入口
  - summary 新增 `high_quality_review_candidate_rows`
- Evidence:
  - `backend/app/api/training.py`
  - `frontend/src/pages/index.js`
  - `docs/qa/live_chain_audit_2026-03-10.md`

### D71. inspection OCR 训练前判断产品化

- Status: Done
- Result:
  - summary / workspace summary 已返回：
    - `ready`
    - `cold_start_only`
    - `blocked`
  - 前端直接显示：
    - `可正常训练`
    - `仅冷启动可训练`
    - `仍不可导出`
- Evidence:
  - `backend/app/api/training.py`
  - `frontend/src/pages/index.js`

### D72. inspection OCR 人工替换工具链收口

- Status: Done
- Result:
  - 原图联看
  - 代理替换队列导出
  - 预检查 CSV
  - CSV 导回
  - review pack 导出
- Evidence:
  - `backend/app/api/training.py`
  - `frontend/src/pages/index.js`
  - `docs/product/railcar_inspection_data_workspace_2026-03-12.md`

## 6. 执行原则

- 优先做真实阻断，不优先做新的展示层花样。
- 优先把 inspection/performance OCR 从“有工具”推进到“有真实真值、可正常训练”。
- 完成一段就主动收口：
  - 更新本清单
  - 更新相关文档
  - 删除线标记完成项
