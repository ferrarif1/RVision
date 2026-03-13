# Live Chain Audit 2026-03-13

本记录只写当前真实运行环境的实测结果，不写设想。

- Last Updated: 2026-03-13 17:10 CST

关联执行面板：

- 动态待办清单：`../product/dynamic_execution_todo_2026-03-11.md`
- 页面级走查报告：`./browser_walkthrough_report_2026-03-12.md`

## 当前环境状态

- Backend health：`https://localhost:8443/api/health -> ok`
- Frontend：运行中的 `vistral_frontend` 已同步最新导航、工作台和 inspection OCR 复核入口
- 当前执行基准：
  - 主链已可运行
  - 当前持续主线为 inspection / performance OCR 的真实真值替换

## 已实测跑通的主链

### 1. 车号文本复核 -> 导出训练资产 -> 创建训练作业

- `POST /training/car-number-labeling/export-text-assets` -> `200`
- `POST /training/car-number-labeling/export-text-training-job` -> `200`
- 训练作业真实跑成 `SUCCEEDED`
- 待验证模型真实回收入库

### 2. 候选模型 -> 验证任务 -> 结果复核

- 候选模型可做任务级授权验证
- 真实任务可到 `SUCCEEDED`
- 结果复核可保存，`review_status = revised`

### 3. 审批工作台 -> 审批通过 -> 发布工作台 -> 发布

- 审批工作台可真实读取 readiness、timeline、验证结果
- 可执行：
  - 审批通过
  - 要求补材料
  - 驳回模型
  - 导出证据包
- 发布工作台可真实完成发布

### 4. 数据治理

- `GET /settings/data-governance` -> `200`
- `POST /settings/data-governance/run` -> `200`
- `buyer_operator` 调用执行端点会得到结构化 `403`

## inspection / performance OCR 当前实测状态

### 1. 工作区准备度

真实返回的关键数值：

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
  - `training_readiness.status = cold_start_only`

### 2. inspection OCR 人工替换工具链

已真实打通：

- `GET /training/inspection-ocr/{task_type}/summary`
- `GET /training/inspection-ocr/{task_type}/items`
- `GET /training/inspection-ocr/{task_type}/items/{sample_id}/crop`
- `GET /training/inspection-ocr/{task_type}/items/{sample_id}/source`
- `POST /training/inspection-ocr/{task_type}/items/{sample_id}/review`
- `GET /training/inspection-ocr/{task_type}/export-proxy-queue`
- `GET /training/inspection-ocr/{task_type}/export-high-quality-queue`
- `GET /training/inspection-ocr/{task_type}/export-review-pack`
- `GET /training/inspection-ocr/{task_type}/export-high-quality-pack`
- `POST /training/inspection-ocr/{task_type}/preview-accept-high-quality`
- `POST /training/inspection-ocr/{task_type}/accept-high-quality`
- `POST /training/inspection-ocr/{task_type}/preview-import-reviews`
- `POST /training/inspection-ocr/{task_type}/import-reviews`

高质量建议批量确认已真实 smoke：

- `preview-accept-high-quality`
  - `would_update_rows = 1`
- `accept-high-quality`
  - `updated_rows = 1`
- 验证后已恢复工作区文件并刷新摘要，未污染当前真实数据状态

真实验证结果：

- `export-proxy-queue` -> `200 text/csv`
- `export-high-quality-queue` -> `200 text/csv`
- `export-review-pack` -> `200 application/zip`
- `export-high-quality-pack` -> `200 application/zip`
- `preview-import-reviews`
  - `total_rows = 6`
  - `matched_rows = 6`
  - `would_update_rows = 0`
  - `skipped_rows = 6`
- `import-reviews`
  - `updated_rows = 0`
  - `skipped_rows = 6`
  - `missing_sample_ids = []`

并且工作区摘要已补正式刷新脚本：

- `python3 docker/scripts/refresh_inspection_workspace_summaries.py`

真实刷新后：

- `inspection_mark_ocr.summary.json`
  - `suggestion_rows = 59`
  - `final_text_rows = 9`
- `performance_mark_ocr.summary.json`
  - `suggestion_rows = 57`
  - `final_text_rows = 9`

### 3. inspection / performance OCR 训练门禁

当前默认行为已验证：

- 当工作区仍含代理真值时：
  - `POST /training/inspection-ocr/{task_type}/export-dataset`
  - 默认返回 `400 inspection_ocr_proxy_truth_present`
- 显式 `allow_proxy_seeded = true` 后：
  - 返回 `200`
  - 允许仅冷启动继续训练

### 4. inspection / performance OCR 训练闭环

当前已真实走过至少一轮闭环：

- 导出训练包
- 注册训练 / 验证资产
- 创建训练作业
- `local-train-worker` 执行到 `SUCCEEDED`
- 待验证模型回收入库
- 审批工作台可见

并且审批治理已暴露训练数据来源风险：

- `readiness.validation_report.data_provenance.proxy_seeded_rows`
- `checks` 中存在 `proxy_truth_risk`

## 当前唯一真正阻断点

inspection / performance OCR 现在不再缺工具链，也不再缺训练入口。

当前唯一真正阻断它继续迈进的，是：

- 还需要把 `proxy_seeded` 样本替换成真实 `final_text`
- 让 `training_readiness.status` 从 `cold_start_only` 推进到 `ready`

## 结论

当前运行环境已经从“只有模型族设计和页面入口”推进到了：

- inspection / performance OCR 有真实工作区
- 有代理裁剪
- 有自动建议
- 有高质量建议优先复核
- 有人工替换工具链
- 有训练包导出
- 有训练作业闭环
- 有待验证模型
- 有审批风险暴露

后续主线工作不再是继续补脚手架，而是继续用真实 `final_text` 替换代理回灌样本，并进入下一轮训练和审批验证。

## door_lock_state_detect / connector_defect_detect 当前实测状态

### 1. 状态复核链路

这两类任务现在已经具备正式状态复核与训练入口，不再只是工作区模板：

- `GET /training/inspection-state/{task_type}/summary`
- `GET /training/inspection-state/{task_type}/items`
- `GET /training/inspection-state/{task_type}/items/{sample_id}/crop`
- `GET /training/inspection-state/{task_type}/items/{sample_id}/source`
- `POST /training/inspection-state/{task_type}/items/{sample_id}/review`
- `GET /training/inspection-state/{task_type}/export-review-queue`
- `GET /training/inspection-state/{task_type}/export-review-pack`
- `POST /training/inspection-state/{task_type}/preview-import-reviews`
- `POST /training/inspection-state/{task_type}/import-reviews`
- `POST /training/inspection-state/{task_type}/export-dataset`
- `POST /training/inspection-state/{task_type}/export-assets`
- `POST /training/inspection-state/{task_type}/export-training-job`

### 2. 当前真实结果

- `door_lock_state_detect`
  - `row_count = 2`
  - `reviewed_rows = 2`
  - `training_readiness.status = ready`
  - 首条真实训练作业：`train-bbab47f859`
  - 状态：`SUCCEEDED`
  - 待验证模型：
    - `door_lock_state_detect:v20260313.085312.fb88`
    - `model_id = bb35ba09-6cfe-4d12-93cd-6c34cbe579fd`
- `connector_defect_detect`
  - `row_count = 2`
  - `reviewed_rows = 2`
  - `training_readiness.status = ready`
  - 首条真实训练作业：`train-80b794db2e`
  - 状态：`SUCCEEDED`
  - 待验证模型：
    - `connector_defect_detect:v20260313.085554.827f`
    - `model_id = cf51846a-f7a1-4f23-a570-87353aa2d4f2`

### 3. 结论

这两类状态 / 缺陷任务已经跨过“只有工具链”的阶段，进入了真实训练闭环：

- 已保留首批真实样本
- 已补标签
- 已导出训练 / 验证资产
- 已创建并跑通首条真实训练作业
- 已回收待验证模型
