# 铁路货车巡检任务数据工作区说明（2026-03-12）

- Owner: Engineering / Product
- Status: In Progress
- Last Updated: 2026-03-13
- Scope:
  - 说明机器人库内巡检任务族的数据工作区模板、字段设计、训练包生成方式，以及训练中心里的准备度展示
- Non-goals:
  - 本文不代表这些任务已经具备真实规模数据
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

## 2. 数据蓝图来源

核心蓝图配置：

- [config/railcar_inspection_dataset_blueprints.json](../../config/railcar_inspection_dataset_blueprints.json)

蓝图里已经写入：

- 起步样本量
- 建议样本量
- 场景采集约束
- 首版验收目标
- 结构化字段建议
- 推荐字段与标签枚举

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

## 3. 工作区模板

初始化脚本：

- [docker/scripts/bootstrap_inspection_labeling_workspace.py](../../docker/scripts/bootstrap_inspection_labeling_workspace.py)

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

OCR 任务额外支持代理裁剪脚本：

- [docker/scripts/prepare_inspection_ocr_proxy_crops.py](../../docker/scripts/prepare_inspection_ocr_proxy_crops.py)
- [docker/scripts/generate_inspection_ocr_suggestions.py](../../docker/scripts/generate_inspection_ocr_suggestions.py)

工作区 README 会直接写出：

- 场景采集约束
- 推荐字段
- 推荐结构化字段
- 首版验收目标
- 标注建议

## 4. 训练 / 验证包生成

统一打包脚本：

- [docker/scripts/build_inspection_task_dataset.py](../../docker/scripts/build_inspection_task_dataset.py)

支持两类任务：

### 4.1 OCR 类

- 读取 `final_text`
- 可选回退 `ocr_suggestion`
- 输出 `text / text_source / bbox`

### 4.2 状态 / 缺陷类

- 读取 `label_value / final_label / label_class`
- 按蓝图枚举校验
- 输出 `label / label_source / bbox`

输出产物：

- `<task_type>_train_bundle.zip`
- `<task_type>_validation_bundle.zip`
- `<task_type>_dataset_summary.json`

## 5. 训练中心现在能看到什么

训练中心新增了“巡检任务数据准备”工作区，后端接口：

- `GET /training/inspection-workspaces/summary`

当前会展示：

- 任务名称
- 任务编码
- 起步目标 / 建议规模
- 已裁剪候选区域
- 已有文字建议
- 当前已准备样本
- 待处理 / 需复核 / 已完成
- 建议场景
- 拍摄距离 / 角度 / 图像要求
- 首版验收目标
- 结构化字段建议
- 工作区路径
- 清单路径
- 训练包输出目录
- 生成工作区 / 生成训练包命令

这意味着后续推进 `inspection_mark_ocr` 与 `door_lock_state_detect` 时，不再需要只靠 README 和终端命令定位当前准备度。

真实运行环境已验证：

- `workspace_count = 4`
- `inspection_mark_ocr.sample_target_recommended = 500`
- `inspection_mark_ocr.capture_profile.view_angle_deg = 45`
- `inspection_mark_ocr.qa_targets = {accuracy_good_condition_pct_min:97, accuracy_light_stain_pct_min:90, latency_s_max:0.5}`
- `inspection_mark_ocr.structured_fields = [inspection_date, inspection_record, car_type_code]`
- `inspection_mark_ocr.crop_ready_rows = 77`
- `performance_mark_ocr.crop_ready_rows = 77`
- `inspection_mark_ocr.suggestion_rows = 59`
- `performance_mark_ocr.suggestion_rows = 57`
- `inspection_mark_ocr.high_quality_suggestion_rows = 51`
- `performance_mark_ocr.high_quality_suggestion_rows = 45`

## 6. 当前真实状态

当前这 4 个工作区不再只是空模板：

- `inspection_mark_ocr`
  - `row_count = 80`
  - `crop_ready_rows = 77`
  - `needs_check_rows = 77`
  - `pending_rows = 3`
- `performance_mark_ocr`
  - `row_count = 80`
  - `crop_ready_rows = 77`
  - `needs_check_rows = 77`
  - `pending_rows = 3`
- `door_lock_state_detect`
  - `row_count = 0`
- `connector_defect_detect`
  - `row_count = 0`

说明：

- `inspection_mark_ocr / performance_mark_ocr` 的 `80` 条样本来自仓库内现有真实车身侧拍图。
- 其中 `77` 条已经根据 `demo_data/train/_annotations.txt` 的真实框生成了代理裁剪图，方便直接进入人工复核。
- 还剩 `3` 条图片在 `_annotations.txt` 里没有可复用 anchor，所以暂时保留整图待处理。
- `door_lock_state_detect / connector_defect_detect` 仍然只有采集计划模板，仓库里还没有符合要求的近景真实图像。

## 6.1 代理裁剪怎么生成

```bash
cd <repo-root>
python3 docker/scripts/prepare_inspection_ocr_proxy_crops.py --task-type inspection_mark_ocr
python3 docker/scripts/prepare_inspection_ocr_proxy_crops.py --task-type performance_mark_ocr
```

作用：

- 复用 `demo_data/train/_annotations.txt` 的真实框
- 结合蓝图里的 `proxy_crop_profile` 生成候选文字区域
- 写入各自工作区的 `crops/`
- 回填 `manifest.csv / manifest.jsonl`
- 将对应行提升到 `needs_check`

如果要尝试自动补 OCR 建议，可继续执行：

```bash
cd <repo-root>
python3 docker/scripts/generate_inspection_ocr_suggestions.py --task-type inspection_mark_ocr
python3 docker/scripts/generate_inspection_ocr_suggestions.py --task-type performance_mark_ocr
```

当前真实结果：

- 两个任务都已完成全量尝试
- `inspection_mark_ocr.suggestion_rows = 59`
- `performance_mark_ocr.suggestion_rows = 57`
- `inspection_mark_ocr.high_quality_suggestion_rows = 51`
- `performance_mark_ocr.high_quality_suggestion_rows = 45`
- 说明重新调整后的代理裁剪已经能产出大量可读建议，足够作为人工起步参考
- 但这些建议仍然不能直接当真值；正式训练仍应优先补 `final_text`

这批自动建议现在还会回写元数据：

- `ocr_suggestion_confidence`
- `ocr_suggestion_quality`
- `ocr_suggestion_engine`

所以 inspection/performance OCR 复核已经可以按“高质量建议 / 中质量建议 / 低质量建议”做人工优先级，而不是只看有没有建议。

这轮代理裁剪的关键变化是：

- `performance_mark_ocr`：从“围绕车号框扩张”改成“车号上方性能码带”
- `inspection_mark_ocr`：改成“车号下方检修记录 / 小字信息带”

对应配置在：

- [config/railcar_inspection_dataset_blueprints.json](../../config/railcar_inspection_dataset_blueprints.json)

对应脚本在：

- [docker/scripts/prepare_inspection_ocr_proxy_crops.py](../../docker/scripts/prepare_inspection_ocr_proxy_crops.py)

## 6.2 通用文字复核页已接入

现在 `inspection_mark_ocr / performance_mark_ocr` 不需要只靠命令行改 CSV：

- 训练中心“巡检任务数据准备”卡片里可以直接点 `打开文字复核`
- 页面路由：
  - `training/inspection-ocr/inspection_mark_ocr`
  - `training/inspection-ocr/performance_mark_ocr`

当前复核页支持：

- 查看工作区摘要
- 筛选样本
- 打开 crop 预览
- 保存 `final_text`
- 导出文本训练包
- 自动给出一批“优先起步样本”
- 直接显示 `建议质量 / 建议置信度 / 建议引擎`
- 列表默认优先展示 `needs_check + 代理回灌 + 高质量建议` 的样本

真实状态已经验证：

- `summary / items / crop / review` 都已打通
- `export-dataset` 也已打通，但当前会被真实阻断：
  - `inspection_ocr_dataset_not_enough_rows`
  - 原因不是脚手架缺失，而是还没有足够的已确认文本
- `inspection_mark_ocr / performance_mark_ocr` 的摘要里现在都会返回 `starter_samples`
  - 用现有 `bbox` 尺寸和 crop 是否存在做排序
  - 目的不是断定真值，而是先把最适合人工起步的一批样本推到前面

## 6.3 首版 train / validation bundle 已产出

当前已经不再停留在“可复核但导不出训练包”的状态。

真实运行环境里，已完成这批首版 seed：

- `inspection_mark_ocr`
  - train：`135_104_1... -> 62264635`
  - validation：`152_104_1... -> 50268504`
- `performance_mark_ocr`
  - train：`135_104_1... -> 62264635`
  - validation：`152_104_1... -> 50268504`

真实导出结果：

- [inspection_mark_ocr_dataset_summary.json](../../demo_data/generated_datasets/inspection_mark_ocr_dataset/inspection_mark_ocr_dataset_summary.json)
  - `accepted_rows = 2`
  - train `1`
  - validation `1`

## 6.4 第二轮代理真值扩样与再训练已完成

当前又往前推进了一轮，不再停在 `1 train + 1 validation` 的种子状态。

新增桥接脚本：

- [docker/scripts/seed_inspection_ocr_from_car_number_truth.py](../../docker/scripts/seed_inspection_ocr_from_car_number_truth.py)

作用：

- 读取 `car_number_ocr_labeling/manifest.csv` 中已人工确认且 `review_status = done` 的真值
- 按 `source_file basename` 对齐到 `inspection_mark_ocr / performance_mark_ocr`
- 将同图已复核车号文本写回巡检 OCR 工作区，作为首版代理真值

当前真实结果：

- `inspection_mark_ocr`
  - `reviewed_rows = 9`
  - train `7`
  - validation `2`
  - 第二轮训练作业：`train-71de4b1551`
  - 新待验证模型：`inspection_mark_ocr:v20260313.001308.df11`
- `performance_mark_ocr`
  - `reviewed_rows = 9`
  - train `7`
  - validation `2`
  - 第二轮训练作业：`train-c176e03416`
  - 新待验证模型：`performance_mark_ocr:v20260313.001308.a946`

训练中心当前也已同步回显：

- `reviewed_rows`
- `latest_training_job`
- `latest_candidate_model`

这意味着训练中心现在能直接告诉用户：

1. 这类巡检 OCR 当前补了多少真实/代理真值
2. 最近一次训练跑到了哪一步
3. 当前是否已有可进入审批工作台的待验证模型
- [performance_mark_ocr_dataset_summary.json](../../demo_data/generated_datasets/performance_mark_ocr_dataset/performance_mark_ocr_dataset_summary.json)
  - `accepted_rows = 2`
  - train `1`
  - validation `1`

说明：

- 这只是首版 seed bundle，不代表数据规模已经达到训练上线标准。
- 但它证明了这两类任务已经从“模板 / 代理裁剪 / 复核页”推进到“真实训练包可产出”。

## 6.4 首版训练作业与待验证模型已完成

现在这两类 OCR 任务已经不只停在“能导出训练包”。

真实运行环境里，已继续走完：

- 导出训练资产
- 直接创建训练作业
- `local-train-worker` 真实执行
- 待验证模型回收入库
- 审批工作台可见

真实结果：

- `inspection_mark_ocr`
  - 训练作业：`train-4f1de3303e`
  - 状态：`SUCCEEDED`
  - 待验证模型：
    - `inspection_mark_ocr:v20260312.154741.13db`
    - `model_id = 81c6fe9f-83fb-435d-87c1-376ef620b4fb`
    - `status = SUBMITTED`
- `performance_mark_ocr`
  - 训练作业：`train-796e22cd0c`
  - 状态：`SUCCEEDED`
  - 待验证模型：
    - `performance_mark_ocr:v20260312.154742.a773`
    - `model_id = b1027db7-e0c5-4de6-9ee8-4f6141706de9`
    - `status = SUBMITTED`

审批工作台现状：

- 两个模型都已能读取：
  - `readiness.validation_report`
  - `timeline`
  - `can_approve = true`

这说明当前这两类任务已经进入下一阶段：

- 不是继续补脚手架
- 而是继续补更多真实 `final_text`
- 让这两版待验证模型具备更真实的业务泛化意义

## 6.5 第三轮已将代理真值风险显式打到审批工作台

第二轮闭环解决的是“能训练、能出候选模型”。第三轮解决的是另一个更关键的问题：  
这些候选模型里到底有多少是由代理真值训练出来的，审批人必须一眼看见。

真实结果：

- 重新导出后的训练资产 metadata 已包含：
  - `reviewer_counts = {proxy_from_car_number_truth: 6, platform_admin: 3}`
  - `proxy_seeded_rows = 6`
- 第三轮训练作业：
  - `inspection_mark_ocr`
    - `train-cc7fd43563`
    - `inspection_mark_ocr:v20260313.010220.6bad`
  - `performance_mark_ocr`
    - `train-498aa6d26e`
    - `performance_mark_ocr:v20260313.010220.bbd5`
- 第三轮新模型审批工作台显示：
  - `data_provenance.asset_count = 2`
  - `data_provenance.proxy_seeded_rows = 12`
  - `checks` 中出现 `proxy_truth_risk`

这意味着审批人现在不只知道：

1. 这版模型训练成功了  
2. 有验证指标  

还会明确知道：

3. 训练/验证数据里仍有多少条代理回灌文本  
4. 当前审批是“带代理真值风险”的结论，不是纯真实真值闭环

所以后续真正要继续推进的，不再是继续补脚手架，而是：

- 继续补 `inspection_mark_ocr / performance_mark_ocr` 的真实 `final_text`
- 逐步降低 `proxy_seeded_rows`
- 再产出下一轮待验证模型，让审批风险从“代理真值风险”逐步回落

训练中心中的“巡检任务数据准备”卡片也已同步显示：

- 最近训练作业
- 当前待验证模型
- 查看训练作业
- 查看待验证模型

所以现在不需要再靠人工记忆：

- 这类任务有没有开始训练
- 训练有没有成功
- 候选模型有没有回收出来

## 6.6 已进入“优先替换代理真值”阶段

现在 inspection OCR 这条线已经不再缺页面或接口，而是进入一个更明确的阶段：

- 先把代理回灌样本筛出来
- 优先替换成真实标记真值
- 再继续导出训练包和进入下一轮训练

已经落地的能力：

- inspection OCR 复核页支持：
  - `仅看代理回灌`
  - `优先替换代理真值`
- 训练中心工作区卡片支持显示：
  - `manual_reviewed_rows`
  - `proxy_replacement_samples`

当前真实验证：

- `inspection_mark_ocr`
  - `proxy_seeded_rows = 6`
  - `manual_reviewed_rows = 3`
  - `proxy_replacement_samples = 6`

这意味着当前唯一真正的主线工作已经收敛为：

- 把这 6 条代理回灌文本逐步替换成真实标记真值
- 再跑下一轮 bundle / 训练 / 待验证模型 / 审批治理

## 6.7 已加“代理真值默认阻断”门禁

现在 inspection OCR 工作区在还有代理回灌文本时，默认不会直接继续往训练闭环走。

真实行为：

- 默认导出训练包：
  - `400 inspection_ocr_proxy_truth_present`
- 只有显式允许“带代理真值继续训练（仅冷启动）”时才放行：
  - 当前真实返回 `accepted_rows = 9`
  - `train_rows = 7`

这一步的意义是：

- 系统不会把当前带代理真值的数据误当成默认正常训练路径
- 只有在你明确知道自己是在做冷启动验证时，才会继续往下走

## 6.8 已补“原图联看 + 代理替换队列导出”

现在 inspection OCR 的人工真值替换，不再只能盯着 crop 小图做判断。

新增能力：

- 原图联看
  - 接口：`GET /training/inspection-ocr/{task_type}/items/{sample_id}/source`
  - 复核页现在能同时查看：
    - crop
    - 原图
- 代理替换队列导出
  - 接口：`GET /training/inspection-ocr/{task_type}/export-proxy-queue`
  - 可直接导出 `proxy_replacement_queue.csv`
  - 便于离线分发给人工逐条替换代理回灌真值

真实验证：

- `source -> 200 image/jpeg`
- `proxy-queue -> 200 text/csv`

这一步的意义：

- 人工替换代理真值时，不必只靠 crop 小图猜测文本
- inspection OCR 的剩余主线工作更聚焦到“补真实 final_text”，而不是继续补查看工具

## 6.9 已补“离线复核 CSV 批量导回”

现在 inspection OCR 的人工复核，不再只能在线逐条保存。

新增能力：

- 批量导回接口
  - `POST /training/inspection-ocr/{task_type}/import-reviews`
- 支持字段
  - `sample_id`
  - `final_text`
  - `review_status`
  - `reviewer`
  - `notes`

推荐用法：

1. 先导出 `proxy_replacement_queue.csv`
2. 在表格里逐条补 `final_text`
3. 再用“导入离线复核 CSV”批量导回

真实验证：

- 原样导出再导回：
  - `updated_rows = 0`
  - `skipped_rows = 6`
  - `missing_sample_ids = []`

这意味着：

- inspection OCR 已具备“导出队列 -> 离线补文本 -> 批量导回”的完整闭环
- 后续真正的主线工作可以直接落在“继续补真实真值并降低 proxy_seeded_rows”

## 6.10 已补“人工替换离线工作包”

现在 inspection OCR 的代理真值替换，不再需要人工自己凑图片和清单。

新增能力：

- 导出接口
  - `GET /training/inspection-ocr/{task_type}/export-review-pack`
- 输出内容
  - `proxy_replacement_queue.csv`
  - `README.txt`
  - `crops/`
  - `sources/`

这意味着人工替换可以直接拿到：

- 队列清单
- 裁剪图
- 原图
- 操作说明

真实验证：

- `inspection_mark_ocr review pack`
  - `content-type = application/zip`
  - `crop_entries = 6`
  - `source_entries = 6`

到这里，inspection OCR 的人工替换工具链已经阶段性收齐：

1. 导出代理替换队列
2. 原图联看
3. 离线 CSV 批量导回
4. 人工替换离线工作包

## 6.11 已补“预检查离线复核 CSV”

现在 inspection OCR 的离线 CSV 导回，不再需要“直接导入后再看有没有生效”。

新增能力：

- 预检查接口
  - `POST /training/inspection-ocr/{task_type}/preview-import-reviews`
- 返回摘要
  - `total_rows`
  - `matched_rows`
  - `would_update_rows`
  - `skipped_rows`
  - `missing_sample_ids`
  - `unchanged_sample_ids`

前端复核页也已经新增：

- `预检查离线复核 CSV`

推荐顺序：

1. 导出代理替换队列
2. 线下补 `final_text`
3. 先点 `预检查离线复核 CSV`
4. 确认会更新的条数合理后，再正式导入

真实 smoke：

- `inspection_mark_ocr`
  - `total_rows = 6`
  - `matched_rows = 6`
  - `would_update_rows = 0`
  - `skipped_rows = 6`
  - `unchanged_sample_ids = 6`

## 6.12 已补“训练就绪判断”

inspection OCR 当前不再需要靠多段文案判断“现在能不能训练”。

后端 summary 现已返回：

- `training_readiness.status`
- `training_readiness.label`
- `training_readiness.normal_export_ready`
- `training_readiness.cold_start_export_ready`
- `training_readiness.blockers`
- `training_readiness.replacement_progress_pct`

前端显示：

- 训练中心工作区卡片
- 巡检 OCR 复核页摘要

都会直接展示：

- `可正常训练`
- `仅冷启动可训练`
- `仍不可导出`

当前真实 smoke（`inspection_mark_ocr`）：

- `status = cold_start_only`
- `normal_export_ready = false`
- `cold_start_export_ready = true`
- `manual_reviewed_rows = 3`
- `proxy_seeded_rows = 6`
- `replacement_progress_pct = 33.3`
- `suggestion_rows = 59`
- `high_quality_suggestion_rows = 51`
- `high_quality_review_candidate_rows = 51`

这意味着：

- 当前这批数据可以继续做冷启动验证
- 但正式训练仍建议先把 `proxy_seeded` 样本继续替换成真实标记真值
- 已经可以把“高质量建议”单独拉出来优先处理，而不必在整份待处理样本里逐条盲找

## 6.9 高质量建议优先复核

inspection OCR 复核页现在已补齐高质量建议专用工作流：

- `仅看高质量建议`
- `优先确认高质量建议`
- `导出高质量建议队列`
- `导出高质量建议包`

当前约定：

- `high_quality_suggestion_rows`
  - 表示累计高质量建议数
- `high_quality_review_candidate_rows`
  - 表示当前仍待人工确认的高质量建议数

这两者故意分开，避免“累计已有很多高质量建议”却误以为“当前还有很多未处理样本”。

## 7. 下一步

1. 继续补 `inspection_mark_ocr / performance_mark_ocr` 的 `final_text`
2. 再补 `door_lock_state_detect` 的状态标签数据
3. 扩大真实 train / validation bundle 规模
4. 用更多真实样本重新生成待验证模型
5. 再推进验证、审批和发布闭环
