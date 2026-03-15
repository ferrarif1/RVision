# 铁路货车巡检任务数据工作区说明（2026-03-14）

- Owner: Engineering / Product
- Status: In Progress
- Last Updated: 2026-03-14 11:10 CST
- Scope:
  - 说明机器人库内巡检任务族的数据工作区模板、字段设计、训练包生成方式、人工替换流程，以及训练中心里的准备度展示
- Non-goals:
  - 本文不代表这些任务已经具备正式规模数据
  - 本文不替代现场采集 SOP 和正式验收方案

## 1. 目标

把《铁路货车轮足式机器人库内智能巡检应用技术方案》里的识别对象，从“概念任务”推进成可执行的数据准备入口：

- 定检标记识别 `inspection_mark_ocr`
- 性能标记识别 `performance_mark_ocr`
- 门锁状态识别 `door_lock_state_detect`
- 连接件缺陷识别 `connector_defect_detect`

当前目标不是直接交付最终模型，而是先把这 4 个任务统一收进：

1. 仓库内可复用的工作区模板
2. 统一的数据蓝图
3. 可打包的训练 / 验证 bundle 脚手架
4. 训练中心可视化准备度
5. OCR 类任务的人工替换与质量门禁

## 2. 数据蓝图来源

核心蓝图配置：

- [config/railcar_inspection_dataset_blueprints.json](../../config/railcar_inspection_dataset_blueprints.json)

蓝图中已写入：

- 起步样本量
- 建议样本量
- 场景采集约束
- 首版验收目标
- 结构化字段建议
- 推荐字段与标签枚举
- OCR 代理裁剪配置 `proxy_crop_profile`

当前按文档方案落地的关键约束包括：

- OCR 类任务：
  - 建议拍摄距离 `1.5m-2.0m`
  - 建议拍摄角度 `45°`
  - 图像质量 `>=1080P`
  - 首版准确率目标：
    - 清晰工况 `>=97%`
    - 轻污渍工况 `>=90%`
  - 单张耗时目标 `<=0.5s`
- 门锁 / 连接件类任务：
  - 建议近景距离 `0.8m-1.8m`
  - 首版明显状态 / 明显缺陷准确率 `>=90%`
  - 单张耗时目标 `<=1.0s`

## 3. 工作区模板与脚手架

初始化脚本：

- [docker/scripts/bootstrap_inspection_labeling_workspace.py](../../docker/scripts/bootstrap_inspection_labeling_workspace.py)

统一打包脚本：

- [docker/scripts/build_inspection_task_dataset.py](../../docker/scripts/build_inspection_task_dataset.py)

OCR 任务额外脚本：

- [docker/scripts/prepare_inspection_ocr_proxy_crops.py](../../docker/scripts/prepare_inspection_ocr_proxy_crops.py)
- [docker/scripts/generate_inspection_ocr_suggestions.py](../../docker/scripts/generate_inspection_ocr_suggestions.py)
- [docker/scripts/seed_inspection_ocr_from_car_number_truth.py](../../docker/scripts/seed_inspection_ocr_from_car_number_truth.py)
- [docker/scripts/refresh_inspection_workspace_summaries.py](../../docker/scripts/refresh_inspection_workspace_summaries.py)

当前仓库里已生成 4 个模板工作区：

- [inspection_mark_ocr_labeling](../../demo_data/generated_datasets/inspection_mark_ocr_labeling)
- [performance_mark_ocr_labeling](../../demo_data/generated_datasets/performance_mark_ocr_labeling)
- [door_lock_state_detect_labeling](../../demo_data/generated_datasets/door_lock_state_detect_labeling)
- [connector_defect_detect_labeling](../../demo_data/generated_datasets/connector_defect_detect_labeling)

每个工作区默认包含：

- `manifest.csv`
- `manifest.jsonl`
- `summary.json`
- `README.md`
- `crops/`
- `capture_plan.csv`

## 4. 训练中心现在能看到什么

训练中心“巡检任务数据准备”工作区对应后端接口：

- `GET /training/inspection-workspaces/summary`

当前会展示：

- 任务名称 / 任务编码
- 起步目标 / 建议规模
- 已裁剪候选区域
- 已有文字建议
- 高质量建议数量
- 当前已确认文本
- 待处理 / 需复核 / 已完成
- 建议场景
- 拍摄距离 / 角度 / 图像要求
- 首版验收目标
- 结构化字段建议
- 工作区路径 / 清单路径 / 输出目录
- 最近训练作业
- 当前待验证模型
- 当前训练就绪状态

## 5. 当前真实状态

### 5.1 OCR 两类任务

- `inspection_mark_ocr`
  - `row_count = 80`
  - `crop_ready_rows = 77`
  - `suggestion_rows = 59`
  - `high_quality_suggestion_rows = 51`
  - `high_quality_review_candidate_rows = 51`
  - `readiness_action_plan.title = 先处理训练阻断样本`
  - `readiness_action_plan.projected_status_after_blockers = ready`
  - `readiness_action_plan.projected_manual_reviewed_rows = 9`
  - `reviewed_rows = 9`
  - `manual_reviewed_rows = 3`
  - `proxy_seeded_rows = 6`
  - `proxy_replacement_samples = 6`
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

### 5.2 检测两类任务

- `door_lock_state_detect`
  - `row_count = 2`
  - `reviewed_rows = 2`
  - `training_readiness.status = ready`
  - 首条真实训练作业：`train-bbab47f859`
  - 待验证模型：`door_lock_state_detect:v20260313.085312.fb88`
- `connector_defect_detect`
  - `row_count = 2`
  - `reviewed_rows = 2`
  - `training_readiness.status = ready`
  - 首条真实训练作业：`train-80b794db2e`
  - 待验证模型：`connector_defect_detect:v20260313.085554.827f`

说明：

- `inspection_mark_ocr / performance_mark_ocr` 的 `80` 条样本来自仓库内现有真实车身侧拍图。
- 其中 `77` 条已根据 `demo_data/train/_annotations.txt` 的真实框生成代理裁剪图。
- `door_lock_state_detect / connector_defect_detect` 已经不再停留在“只有入口”：
  - 已保留首批真实图片样本
  - 已补 `label_value`
  - 已具备 `starter_samples / training_readiness`
  - 已各自产生一条真实训练作业
  - 已各自回收一版待验证模型

## 6. inspection / performance OCR 已具备的闭环

### 6.1 代理裁剪

当前裁剪策略已经从“车号框盲扩张”改成更贴近真实标记区域：

- `performance_mark_ocr`：优先截取车号上方性能码带
- `inspection_mark_ocr`：优先截取车号下方检修记录 / 小字信息带

真实结果：

- `inspection_mark_ocr.suggestion_rows = 59`
- `performance_mark_ocr.suggestion_rows = 57`

### 6.2 自动建议与质量分层

自动建议会回写：

- `ocr_suggestion`
- `ocr_suggestion_confidence`
- `ocr_suggestion_quality`
- `ocr_suggestion_engine`

当前高质量建议统计：

- `inspection_mark_ocr.high_quality_suggestion_rows = 51`
- `performance_mark_ocr.high_quality_suggestion_rows = 45`

当前训练阻断样本统计：

- `inspection_mark_ocr.readiness_blocker_rows = 6`
- `performance_mark_ocr.readiness_blocker_rows = 6`

### 6.3 通用复核页

当前 inspection/performance OCR 均可进入统一复核页，支持：

- 查看工作区摘要
- 查看 crop
- 打开原图
- 保存 `final_text`
- 仅看代理回灌
- 仅看高质量建议
- 优先替换代理真值
- 优先确认高质量建议

### 6.4 离线人工替换工具链

当前已具备：

- 导出代理替换队列 CSV
- 导出高质量建议队列 CSV
- 导出训练阻断样本队列 CSV
- 导出 review pack ZIP
- 导出训练阻断样本 pack ZIP
- 高质量建议批量预检查
- 高质量建议批量确认
- 预检查 CSV 导入
- CSV 批量导回

当前 inspection OCR 复核页支持把“当前筛选结果里的高质量建议”成批写回 `final_text`：

1. 先点 `预检查批量确认`
2. 看本次会更新多少条
3. 再点 `批量确认高质量建议`

这样 inspection/performance OCR 不再只能逐条点保存，可以先把高质量建议队列快速转成首批人工确认真值。

### 6.4.1 训练阻断样本工作流

当前 inspection/performance OCR 复核页已经把“真正阻断正式训练的样本”独立成正式工作流：

- `仅看训练阻断样本`
- `优先处理训练阻断样本`
- `导出训练阻断队列`
- `导出训练阻断包`

后端同时提供：

- `GET /training/inspection-ocr/{task_type}/export-readiness-blocker-queue`
- `GET /training/inspection-ocr/{task_type}/export-readiness-blocker-pack`

这批样本当前主要对应 `proxy_seeded_truth`，也就是仍带代理回灌真值、会直接阻断“可正常训练”的样本。

### 6.4.2 训练就绪行动计划

当前 inspection/performance OCR 摘要区和训练中心工作区卡片不再只显示 `cold_start_only`，还会直接给出行动计划：

- 当前最优先做什么
- 处理完训练阻断样本后，预计会不会进入 `ready`
- 预计人工真值会提升到多少
- 处理完阻断样本后还差多少条人工真值

`inspection_mark_ocr` 当前真实返回：

- `readiness_action_plan.title = 先处理训练阻断样本`
- `readiness_action_plan.projected_status_after_blockers = ready`
- `readiness_action_plan.projected_manual_reviewed_rows = 9`
- `readiness_action_plan.remaining_manual_rows_after_blockers = 0`
- 训练阻断样本现在还支持一键批量处理：
  - `preview-resolve-readiness-blockers`
  - `resolve-readiness-blockers`
- live smoke：
  - 预检查前 2 条阻断样本：`would_update_rows = 2`
  - 正式处理后：`proxy_seeded_rows 6 -> 4`、`manual_reviewed_rows 3 -> 5`
  - 验证后已恢复工作区基线

这意味着当前主问题已经被系统压成单一路径：先处理完这 6 条阻断样本，再进入正式训练。

### 6.5 训练包与训练作业

inspection/performance OCR 已不再停留在“只能复核”，而是已走过至少一轮真实训练闭环：

- 训练包可导出
- 训练资产可注册
- 训练作业可由 `local-train-worker` 执行
- 新待验证模型可回收入库
- 审批工作台可见

### 6.6 风险治理

inspection/performance OCR 当前默认是“安全优先”：

- 只要工作区仍含 `proxy_seeded` 行，默认就不会继续走正式训练路径
- 必须显式勾选：
  - `允许带代理真值继续训练（仅冷启动）`
- 审批工作台会显式暴露：
  - `proxy_truth_risk`
  - `data_provenance.proxy_seeded_rows`

## 6.7 状态类任务当前已具备的闭环

`door_lock_state_detect / connector_defect_detect` 当前已经从“工具链完整”推进到“首批真实样本 + 首条真实训练作业”：

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

训练中心卡片现在可直接进入状态复核页，完成：

- 查看准备度
- 导入现有图片资产
- 查看样本列表
- 查看 crop / 原图
- 保存状态标签
- 导出状态复核队列
- 导出人工复核包（队列 CSV + README + 原图）
- 预检查离线复核 CSV
- 导入离线复核 CSV
- 导出训练包
- 导出训练资产
- 直接创建训练作业

当前真实结果是：

- `door_lock_state_detect`
  - `row_count = 2`
  - `reviewed_rows = 2`
  - `training_readiness.status = ready`
  - 首条真实训练作业：`train-bbab47f859`
  - 作业状态：`SUCCEEDED`
  - 待验证模型：`door_lock_state_detect:v20260313.085312.fb88`
- `connector_defect_detect`
  - `row_count = 2`
  - `reviewed_rows = 2`
  - `training_readiness.status = ready`
  - 首条真实训练作业：`train-80b794db2e`
  - 作业状态：`SUCCEEDED`
  - 待验证模型：`connector_defect_detect:v20260313.085554.827f`

所以这条线已经从“缺工具 / 缺真实样本”推进到了“已跑出首条真实训练闭环”。

## 7. 当前真正阻断点

这条线现在已经不再缺：

- 页面
- 接口
- 导出
- 训练入口
- 审批入口
- 人工替换工具

当前唯一真正阻断 inspection/performance OCR 继续往前推进的，只剩：

- 还需要把 `proxy_seeded` 样本替换成真实 `final_text`
- 让 `training_readiness.status` 从 `cold_start_only` 推进到 `ready`

## 8. 推荐执行顺序

在继续替换真实真值之前，建议先刷新工作区摘要，确保 `summary.json` 与 `manifest.csv` 同步：

```bash
cd <repo-root>
python3 docker/scripts/refresh_inspection_workspace_summaries.py
```

这一步已经用于把当前两类 OCR 工作区摘要刷新到真实状态：

- `inspection_mark_ocr.suggestion_rows = 59`
- `inspection_mark_ocr.final_text_rows = 9`
- `performance_mark_ocr.suggestion_rows = 57`
- `performance_mark_ocr.final_text_rows = 9`

### Step 1

- 先处理高质量建议和代理回灌样本：
  - 优先看 `high_quality_review_candidate_rows`
  - 优先看 `proxy_replacement_samples`

### Step 2

- 继续补真实 `final_text`
- 让 `manual_reviewed_rows` 上升、`proxy_seeded_rows` 下降

### Step 3

- 重新导出 train / validation bundle
- 再跑新一轮训练作业

### Step 4

- 在审批工作台验证：
  - `proxy_truth_risk` 是否下降
  - readiness 是否更接近可发布

## 9. 结论

inspection/performance OCR 这条线已经从“只有模板”推进到了：

- 有真实整图
- 有代理裁剪
- 有自动建议
- 有高质量建议优先复核
- 有人工替换工具链
- 有训练包导出
- 有训练作业闭环
- 有待验证模型
- 有审批风险暴露

当前剩下的主线，不再是继续补工具，而是继续用真实 `final_text` 替换代理回灌样本，把这条线从“仅冷启动可训练”推进到“可正常训练”。
