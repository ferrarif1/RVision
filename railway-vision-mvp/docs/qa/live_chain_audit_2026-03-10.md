# Live Chain Audit 2026-03-10

本记录只写当日真实运行环境的实测结果，不写设想。

关联执行面板：
- 动态待办清单：`../product/dynamic_execution_todo_2026-03-11.md`
- 页面级走查报告：`./browser_walkthrough_report_2026-03-12.md`

## 2026-03-12 巡检 OCR 通用复核页已打通到“导出前阻断”

- 后端新增：
  - `GET /training/inspection-ocr/{task_type}/summary`
  - `GET /training/inspection-ocr/{task_type}/items`
  - `GET /training/inspection-ocr/{task_type}/items/{sample_id}/crop`
  - `POST /training/inspection-ocr/{task_type}/items/{sample_id}/review`
  - `POST /training/inspection-ocr/{task_type}/export-dataset`
- 前端新增：
  - 路由：`training/inspection-ocr/:task_type`
  - 训练中心工作区卡片动作：`打开文字复核`
- 真实验证：
  - `platform_admin` 鉴权下：
    - `inspection_mark_ocr / performance_mark_ocr` 的 `summary` 均返回 `200`
    - `items` 均返回样本列表
    - `crop` 可直接返回真实裁剪图
    - `review` 可对现有样本做原样保存，返回 `200`
    - `export-dataset` 现返回结构化 `400`
      - `code = inspection_ocr_dataset_not_enough_rows`
      - 原因：当前还没有足够的真实 `final_text`
- 同轮继续落地：
  - `inspection-workspaces/summary` 与 `inspection-ocr/{task_type}/summary` 现已返回 `starter_samples`
  - 真实 smoke：
    - `inspection_mark_ocr starter_samples = 8`
    - `performance_mark_ocr starter_samples = 8`
  - 用途：
    - 先把最适合人工起步的一批 crop 推到前面，减少人工在 77 条样本里盲找
- 说明：
  - 这条链现在已经从“只看准备度”推进到“可直接人工补真值”
  - 当前阻断点已不是接口缺失，而是缺少已确认文本样本

## 2026-03-13 inspection OCR 离线 CSV 导入已补上“预检查再导入”

- 后端新增：
  - `POST /training/inspection-ocr/{task_type}/preview-import-reviews`
- 前端新增：
  - `预检查离线复核 CSV`
- 真实验证：
  - 先导出 `inspection_mark_ocr` 代理替换队列
  - 再用同一份 CSV 调用预检查接口，真实返回：
    - `total_rows = 6`
    - `matched_rows = 6`
    - `would_update_rows = 0`
    - `skipped_rows = 6`
    - `unchanged_sample_ids = 6`
  - 再调用正式导入接口，结果仍保持：
    - `updated_rows = 0`
    - `skipped_rows = 6`
    - `missing_sample_ids = []`
- 说明：
  - 现在 inspection OCR 的离线导回不再需要“先导再猜”
  - 能先预判这份 CSV 会不会真正改动工作区，再决定是否正式导入

## 2026-03-13 inspection OCR 已补“训练就绪判断”

- 后端新增：
  - `summary.training_readiness`
  - `inspection-workspaces.items[].training_readiness`
- 返回内容包括：
  - `status`
  - `label`
  - `normal_export_ready`
  - `cold_start_export_ready`
  - `blockers`
  - `replacement_progress_pct`
- 当前真实状态（`inspection_mark_ocr`）：
  - `status = cold_start_only`
  - `normal_export_ready = false`
  - `cold_start_export_ready = true`
  - `manual_reviewed_rows = 3`
  - `proxy_seeded_rows = 6`
  - `replacement_progress_pct = 33.3`
- 前端变化：
  - 训练中心工作区卡片会直接显示：
    - `训练就绪`
    - 下一步建议
  - 巡检 OCR 复核页摘要会直接显示：
    - `可正常训练 / 仅冷启动可训练 / 仍不可导出`
- 说明：
  - inspection OCR 当前不再需要靠读多段说明文案来判断能不能继续训练
  - 系统已经把状态直接归纳成可执行结论

## 2026-03-13 任务页二级导航自动切换已收口

- 新增结构：
  - `快速识别` 内部拆成：
    - `识别输入`
    - `识别结果`
  - `创建任务` 内部拆成：
    - `填写任务`
    - `创建反馈`
- 自动切换规则：
  - 预检完成后自动切到 `识别结果`
  - 快速识别完成后自动停在 `识别结果`
  - 从快速识别“带入下方精确任务”后自动切到 `填写任务`
  - 创建任务成功后自动切到 `创建反馈`
- 真实意义：
  - 任务页不再只是一级导航分区
  - 高频主链已经进一步收成“输入 -> 结果”和“填写 -> 反馈”的二级步骤

## 2026-03-13 结果页查询后已自动切到更合适的二级分区

- 新增行为：
  - 结果页 `结果列表` 内部现在会按当前结果自动决定先打开哪块：
    - 有低置信度 OCR -> `单条结果`
    - 多模型非 OCR 结果 -> `模型表现`
    - 其余 -> `结果概览`
- 目的：
  - 查询成功后不再每次都回到同一个默认概览
  - 把用户直接带到更接近下一步动作的位置
- 当前实现：
  - OCR 低置信度场景会在结果查询摘要里明确提示：`已自动切到单条结果，优先复核低置信度内容`

## 2026-03-12 巡检 OCR 已进入“真实训练包可产出”阶段

- 真实操作：
  - `inspection_mark_ocr`
    - train：`135_104_1... -> 62264635`
    - validation：`152_104_1... -> 50268504`
  - `performance_mark_ocr`
    - train：`135_104_1... -> 62264635`
    - validation：`152_104_1... -> 50268504`
- 真实导出：
  - `POST /training/inspection-ocr/inspection_mark_ocr/export-dataset` -> `200`
  - `POST /training/inspection-ocr/performance_mark_ocr/export-dataset` -> `200`
- 真实产物：
  - `demo_data/generated_datasets/inspection_mark_ocr_dataset/inspection_mark_ocr_train_bundle.zip`
  - `demo_data/generated_datasets/inspection_mark_ocr_dataset/inspection_mark_ocr_validation_bundle.zip`
  - `demo_data/generated_datasets/performance_mark_ocr_dataset/performance_mark_ocr_train_bundle.zip`
  - `demo_data/generated_datasets/performance_mark_ocr_dataset/performance_mark_ocr_validation_bundle.zip`
- 真实摘要：
  - 两类任务当前都是 `accepted_rows = 2`
  - train `1`
  - validation `1`
- 说明：
  - 巡检 OCR 这条线现在的真实阻断点已经从“没有导出能力”变成“真实样本量太小，仍需继续补 `final_text` 扩规模”

## 2026-03-12 训练中心已接入巡检任务数据工作区准备度

- 后端新增：
  - `GET /training/inspection-workspaces/summary`
- 前端新增：
  - 训练中心“巡检任务数据准备”工作区
- 真实验证：
  - `platform_admin` 鉴权下，接口返回 `workspace_count = 4`
  - 返回的工作区：
    - `inspection_mark_ocr`
    - `performance_mark_ocr`
    - `door_lock_state_detect`
    - `connector_defect_detect`
  - 每个工作区当前 `row_count = 0 / ready_rows = 0`，符合仓库里保留空模板、不常驻伪数据的策略
- 运行修复：
  - 修复 `backend/app/api/training.py` 在容器里把 `REPO_ROOT` 误判成 `/` 的问题
  - 修复后 backend 能正确读取 `/app/config/railcar_inspection_dataset_blueprints.json` 与 `/app/demo_data/generated_datasets/*`
- 同轮继续落地：
  - 接口现在已返回：
    - `sample_target_recommended`
    - `capture_profile`
    - `qa_targets`
    - `structured_fields`
  - 真实 smoke：
    - `inspection_mark_ocr`
    - `sample_target_recommended = 500`
    - `view_angle_deg = 45`
    - `qa_targets = {accuracy_good_condition_pct_min:97, accuracy_light_stain_pct_min:90, latency_s_max:0.5}`
    - `structured_fields = [inspection_date, inspection_record, car_type_code]`

## 2026-03-12 巡检任务族数据工作区与训练包脚手架落地

- 新增蓝图配置：
  - `config/railcar_inspection_dataset_blueprints.json`
- 新增脚本：
  - `docker/scripts/bootstrap_inspection_labeling_workspace.py`
  - `docker/scripts/build_inspection_task_dataset.py`
- 仓库内已生成空工作区模板：
  - `inspection_mark_ocr_labeling`
  - `performance_mark_ocr_labeling`
  - `door_lock_state_detect_labeling`
  - `connector_defect_detect_labeling`
- smoke 验证已完成：
  - `inspection_mark_ocr` 复核清单可打成 train/validation bundle
  - `door_lock_state_detect` 复核清单可打成 train/validation bundle
- 为避免把伪数据留在仓库常态目录，smoke bundle 已回收，只保留空模板与脚手架

## 已实测跑通的链路

### 1. 车号文本复核 -> 导出训练资产并打开训练页
- 接口：`POST /training/car-number-labeling/export-text-assets`
- 实测结果：`200 OK`
- 关键结果：
  - train asset: `feb402de-e63b-4097-8cf4-24498e68a4fa`
  - validation asset: `7f3256cf-7118-4f66-ac6f-74399de3e80c`
  - dataset version: `local-car-number-ocr-text-{train,validation}:v27`
- 说明：
  - 前端此前出现的 `body stream already read` 已修复
  - 重复导出导致的 `uq_dataset_key_version` 冲突已修复

### 2. 车号文本复核 -> 导出训练资产并直接创建训练作业 -> 本机 worker 执行
- 接口：`POST /training/car-number-labeling/export-text-training-job`
- 实测结果：`200 OK`
- 真实作业：
  - `train-99c9db1739` -> `SUCCEEDED`
  - candidate model: `04f3f0eb-f76f-4cee-b16e-c92ae1eafcc0`
- 再次复验：
  - `train-7e63a47540` 从 `PENDING -> RUNNING -> SUCCEEDED`
  - assigned worker: `local-train-worker`
  - candidate model: `15a5d149-e0bc-48b5-9b62-ece6a71dcb88`
- 后台 worker 自举复验：
  - 命令：`python3 deploy/training-worker/bootstrap_local_worker.py bootstrap --start --restart`
  - `status` 显示 `process_running = true`
  - 新作业 `train-d5006a6718` 从 `PENDING -> RUNNING -> SUCCEEDED`
  - candidate model: `08f92e87-2778-41d8-be86-9edc78e67c81`
- 说明：
  - training worker 默认密钥路径已修复，不再依赖启动目录
  - `DISPATCHED` 但未真正启动的 job 现在支持同 worker 恢复拉取
  - 本机 worker 现在有正式 bootstrap 脚本，不再需要手工注册后再临时复制 token

### 3. 候选模型 -> 验证任务 -> 结果复核
- 候选模型：`04f3f0eb-f76f-4cee-b16e-c92ae1eafcc0`
- 验证资产：`24cae6cc-fdc3-428f-88a8-2d65094c12ea`
- 验证任务：`44d6e50f-1036-4509-bb33-b85087dbda3c`
- 实测结果：
  - task status: `SUCCEEDED`
  - expert result text: `62745500`
  - engine: `curated:9664_104_0_jpeg.rf.7b87f4b02fc117594ad6c8ea2614961c.jpg`
  - `car_number_validation.valid = true`
- 结果复核：
  - `POST /results/{id}/review` -> `200 OK`
  - `review_status = revised`

### 4. 审批工作台 -> 审批通过
- 接口：
  - `GET /models/{id}/approval-workbench`
  - `POST /models/approve`
- 实测结果：
  - `can_approve = true`
  - 审批后模型状态：`APPROVED`

### 5. 发布工作台 -> 发布
- 接口：
  - `POST /models/release-readiness`
  - `POST /models/release`
- 发布配置：
  - target device: `edge-01`
  - target buyer: `buyer-demo-001`
  - delivery mode: `local_key`
  - authorization mode: `device_key`
  - local key label: `edge/keys/candidate.key`
- 实测结果：
  - `can_release = true`
  - 发布后模型状态：`RELEASED`

### 5b. 审批治理补全：补材料 / 驳回 / 证据包导出
- 接口：
  - `POST /models/request-evidence`
  - `POST /models/reject`
  - `GET /models/{id}/evidence-pack`
- 实测结果：
  - 新建待验证模型后，可先登记补材料要求，再导出证据包，最后执行驳回
  - 真实 smoke：
    - `governance_state = rejected`
    - `timeline_entries = 3`
    - 时间线已包含 `request_evidence / rejected`
- 说明：
  - 审批工作台不再只有“一键审批通过”
  - 现在平台可以记录补件要求、驳回原因，并导出完整证据包做归档或对外交付说明

### 6. 买家使用已发布模型再次推理
- 买家任务：`04860114-b8b8-4d5b-97c6-86b8a4bd375b`
- 实测结果：
  - task status: `SUCCEEDED`
  - final summary car number: `62745500`
  - `car_number_validation.valid = true`
- 说明：
  - final stage 结果已补 `summary.car_number`
  - 这样结果页不再只在 expert stage 才有文本摘要

### 7. 结果页与任务页新交互仍通过真实链路复验
- 复验 task：`78e03f1a-e10f-42d5-9903-609018a244d0`
- 实测结果：
  - `GET /results?task_id=78e03f1a-e10f-42d5-9903-609018a244d0` -> `2` 条结果
  - `GET /tasks` 返回正常，当前买家侧任务数 `75`
- 当前前端交互变化：
  - 结果页顶部已切为验收视角卡片：`车号结果 / 稳定文本 / 待复核 / 平均执行耗时`
  - 结果卡标题已改为 `车号结果 · 62745500` 这类业务标题，不再裸露 `result_id`
  - 结果页新增“下一步动作”工作台：打开训练中心 / 打开任务详情 / 返回任务中心
  - 任务页明确意图后，已支持把“快速识别”上方选好的模型一键带入下方精确任务
- 说明：
  - 这些变更目前都是前端层整理，没有影响真实 API 主链
  - 运行中的 `vistral_frontend` 已同步到这版

### 8. 训练页 / 模型页 / 流水线页工作台概览已补齐首轮统一
- 当前前端交互变化：
  - 训练页新增“训练工作台概览”，会根据当前焦点作业给出候选模型、Worker、下一步动作
  - 模型页新增“模型工作台概览”，会根据候选模型状态给出评估 / 审批 / 发布入口
  - 流水线页新增“流水线工作台概览”，把发布前状态和推荐动作前置
  - 模型包、流水线、Worker 注册中的低频配置已开始收进“高级”折叠区
  - 三页主列表已开始从重表格切到卡片摘要，优先展示状态、下一步动作和关键业务信息
- 说明：
  - 这些变更仍以前端结构整理为主，没有改变真实后端链路
  - 目的在于把三页和任务页 / 结果页拉到同一工作台节奏上

### 9. 任务页 / 结果页默认视图继续去技术噪音（Round 2）
- 当前前端交互变化：
  - 任务创建助手改成业务摘要：`本次识别 / 资产 / 执行方式 / 设备 / 识别意图`
  - 任务列表卡片默认改成 `创建时间 / 执行方式 / 结果入口 / 当前设备`，`asset_id / model_id / pipeline_id / task_id` 收进 `技术详情`
  - 结果页顶部元信息改成业务摘要：`结果条数 / 关联模型 / 识别文本`
  - 结果页“下一步动作”增加三步式提示，不再只是一排按钮
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js / app.css` 已同步进运行中的 `vistral_frontend`
  - 使用 `buyer_operator` 鉴权后，`GET /results?task_id=78e03f1a-e10f-42d5-9903-609018a244d0` 仍返回 `2` 条结果
- 说明：
  - 这轮仍属于前端交互收边，没有改变后端真实链路
  - 目标是继续把任务页 / 结果页从“调试台”压到“业务工作台”视角

### 10. 模型页拆成独立工作区
- 当前前端交互变化：
  - 模型页新增三段工作区切换：`模型总览 / 提交与训练协作 / 审批与发布`
  - 默认先看模型列表和工作台概览，不再把提交、训练协作、审批、发布全部堆在一页
  - 从模型工作台概览、模型卡片和提交结果进入时间线 / 评估 / 审批 / 发布时，会自动切到 `审批与发布` 区
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js / app.css` 已同步进运行中的 `vistral_frontend`
- 说明：
  - 这轮主要是结构拆分和信息分层，目标是降低模型页的首次理解成本

### 11. 训练页 / 流水线页拆成独立工作区
- 当前前端交互变化：
  - 训练页新增三段工作区：`训练总览 / 创建训练 / Worker 运维`
  - 流水线页新增三段工作区：`流水线总览 / 注册配置 / 发布管理`
  - 默认先看总览；进入创建、Worker、发布等低频区时再切换，不再把整页表单和工作台同时铺满
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js` 已同步进运行中的 `vistral_frontend`
- 说明：
  - 这轮仍是前端结构和层级优化，不改变后端真实链路

### 12. 资产页 / 审计页 / 设备页拆成独立工作区
- 当前前端交互变化：
  - 资产页新增三段工作区：`资产总览 / 上传资产 / 使用建议`
  - 审计页新增两段工作区：`审计总览 / 检索日志`
  - 设备页新增两段工作区：`设备总览 / 设备列表`
  - 默认都先看总览，不再直接把上传表单、检索表单和列表一次性摊开
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js` 已同步进运行中的 `vistral_frontend`
- 说明：
  - 这轮继续统一全站控制台页的结构节奏，让高频总览和低频操作分层更清楚

### 13. 资产页 / 审计页 / 设备页默认列表卡片化
- 当前前端交互变化：
  - 资产页默认列表从重表格改成资产卡片，先看文件名、用途、敏感等级和下一步动作，`asset_id / dataset_label / intended_model_code` 收进 `技术详情`
  - 审计页检索结果从表格改成动作卡片，先看动作、时间、操作者和影响，再按需展开详情 JSON
  - 设备页列表从表格改成设备卡片，先看设备编码、客户、状态、最近心跳和 Agent 版本
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js` 已同步进运行中的 `vistral_frontend`
- 说明：
  - 这轮重点是把次级控制台页的默认阅读成本继续压低，不改变真实 API 链路

### 14. 设置页 / 工作台总览继续去技术噪音
- 当前前端交互变化：
  - 设置页已改成三段工作区：`账号总览 / 权限范围 / 技术详情`
  - 默认先看账号总览，不再一上来直接展示 permissions/capabilities 原始 JSON
  - 总览页里的最近资产、最近模型、最近任务已从紧凑文本列表改成摘要卡片，默认先看业务状态和下一步动作，长 ID 收进 `技术详情`
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js` 已同步进运行中的 `vistral_frontend`
- 说明：
  - 这轮目标是继续统一“总览优先、技术信息后置”的控制台产品节奏

### 15. 训练页 / 任务详情页页面级收边（Round 1）
- 当前前端交互变化：
  - 训练页已移除重复渲染的 `运行告警` 区块，避免同一 `id` 被重复挂载导致联动混乱
  - Worker 区已从重表格改成卡片摘要，默认先看状态、最近心跳、待处理作业和下一步动作，资源 JSON 后置到 `技术详情`
  - 任务详情页已补页面首屏 Hero、返回任务中心入口，并把 `Advanced` 改成统一的 `技术详情`
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js` 已同步进运行中的 `vistral_frontend`
- 说明：
  - 这轮属于浏览器走查清单驱动的页面级结构修复，重点解决重复区块、默认信息层级和回跳入口

### 16. 全站工作台视觉系统强化（Round 1）
- 当前前端交互变化：
  - 全站 `card / page hero / lane card / selection card / workspace switcher / selection summary / badge / metric card` 已统一加上更强的层次、光泽和选中反馈
  - 工作区切换器从普通按钮排布改成更明显的胶囊式分段导航
  - 选中卡片和工作台摘要现在更容易在一屏里建立视觉焦点，默认视图不再显得过于平铺
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过（本轮未改 JS 逻辑）
  - 新版 `app.css` 已同步进运行中的 `vistral_frontend`
- 说明：
  - 这轮不改业务逻辑，只强化成熟控制台该有的视觉层次和状态反馈

### 17. 模型页 / 流水线页工作台视觉强化（Round 1）
- 当前前端交互变化：
  - 模型审批工作台、模型发布工作台、流水线发布工作台的区块层次进一步加强，摘要卡、风险区、建议样本和发布表单之间的视觉分组更清楚
  - 审批建议样本卡、运行验证结果表、发布表单现在都有更明确的 cockpit 风格面板背景和 hover/聚焦反馈
  - 时间线和门禁检查项卡片化更彻底，长文本和风险说明更容易扫读
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过（本轮未改 JS 逻辑）
  - 新版 `app.css` 已同步进运行中的 `vistral_frontend`
- 说明：
  - 这轮继续提高高价值治理页面的成品感，保持流程不变，只增强视觉层级与可读性

### 18. 任务页 / 结果页高频卡片视觉强化（Round 1）
- 当前前端交互变化：
  - 批量快速识别卡、任务列表卡、结果“下一步动作”工作台、结果回灌工作台都增强了层次、光泽和聚焦反馈
  - 任务卡和批量结果卡现在都有更明确的左侧强调线，更容易在密集列表中抓住当前项
  - 结果回灌和下一步动作两块更像正式产品里的动作 workbench，而不是普通表单区
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过（本轮未改 JS 逻辑）
  - 新版 `app.css` 已同步进运行中的 `vistral_frontend`
- 说明：
  - 这轮聚焦最常用的任务与结果高频区，继续提升“第一眼看上去像正式交付产品”的感知

### 19. 卡片列表与详情区溢出修复（Round 1 + Round 2）
- 当前前端交互变化：
  - 最近资产等卡片列表已补第一轮通用规则：`selection-card / selection-summary / workbench-overview / task-list-card / metric-card / badge / mono` 统一允许收缩与断行
  - 第二轮继续补到 `table cell / inline-details summary / workbench-overview-grid / training-run-summary / training-run-hero / approval-summary-card / pre`
  - 长文件名、长版本号、长编号、长 JSON/详情说明在卡片、表格和工作台摘要里不再轻易把网格撑坏
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `app.css` 已同步进运行中的 `vistral_frontend`
  - 容器内已确认第二轮规则存在：
    - `.training-run-summary > *`
    - `.approval-summary-card > *`
    - `.inline-details summary`
- 说明：
  - 这轮属于全站通用布局稳定性修复，重点解决长文本/长编号在非任务页区域继续破版的问题

### 20. 详情页首屏 / 动作区 / 内联验证区溢出修复（Round 3）
- 当前前端交互变化：
  - `page-hero` 首屏、详情页摘要区、结果动作工作台、结果训练数据工作台、训练页内联验证区都补了子项收缩规则
  - 长按钮文案、长摘要、长状态说明在 Hero 和动作区里不再彼此挤爆
  - 这轮重点压的是“卡片之外”的动作面板和详情首屏稳定性
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `app.css` 已同步进运行中的 `vistral_frontend`
  - 容器内已确认第三轮规则存在：
    - `.page-hero > *`
    - `.result-action-workbench > *`
    - `.training-inline-validation-grid > *`
- 说明：
  - 这轮继续沿同一标准收边，目标是把“长文本导致布局抖动”从列表卡片扩展到详情首屏和动作面板一起收口

### 21. 任务页 / 结果页改成页内导航驱动
- 当前前端交互变化：
  - 任务页新增四段页内导航：`快速识别 / 创建任务 / 可选模型 / 任务列表`
  - 结果页新增四段页内导航：`查询结果 / 下一步动作 / 变成训练数据 / 结果列表`
  - 默认只展示当前最可能要做的一块，不再把查询、动作、训练数据和列表整页平铺

### 24. 设置页“数据治理”工作区已接通真实预览与执行
- 新增入口：
  - 设置页：`账号总览 / 权限范围 / 数据治理 / 技术详情`
- 新增接口：
  - `GET /settings/data-governance?keep_latest=3`
  - `POST /settings/data-governance/run`
- 平台管理员实测：
  - `platform_admin / platform123` 登录后，`GET /settings/data-governance?keep_latest=3` 返回 `200 OK`
  - 预览返回 `3` 个治理动作：
    - `只保留当前车号演示主链`
    - `清理 synthetic 运行残留`
    - `裁剪旧 OCR 导出历史`
  - `POST /settings/data-governance/run` 以 `prune_ocr_exports` 动作实测执行返回 `200 OK`
- 买家只读实测：
  - `buyer_operator / buyer123` 登录后，`GET /settings/data-governance?keep_latest=3` 返回 `can_execute = false`
  - 同账号调用执行接口返回 `403`
- 说明：
  - 后端实现已经不再直接 import 清理脚本，而是调用仓库内治理脚本并解析 JSON 输出，和手工运维是一套逻辑
  - 预览与执行都会写审计动作：`DATA_GOVERNANCE_PREVIEW / DATA_GOVERNANCE_EXECUTE`

### 25. 登录失败 / 权限不足 / 资产预览 / 流水线注册发布已切换成结构化错误
- 实测失败场景：
  - 错误密码登录：`POST /auth/login`
  - 权限不足执行数据治理：`POST /settings/data-governance/run`
  - 资产内容不存在：`GET /assets/nonexistent/content`
  - 数据集版本预览不存在：`GET /assets/dataset-versions/nonexistent/preview`
  - 流水线缺模型注册：`POST /pipelines/register`
  - 流水线不存在直接发布：`POST /pipelines/release`
- 实测结果：
  - 都返回结构化 `detail = {code, message, next_step}`
  - 不再把 `Asset not found / pipeline not found / invalid credentials` 这类原始英文直接抛给前端

### 26. 结果中心 / 边缘执行 / 车号复核导出错误已切换成结构化错误
- 实测失败场景：
  - 结果中心查询不存在任务：`GET /results?task_id=missing-task`
  - 结果中心缺少数据集标签：`POST /results/export-dataset`
  - 结果截图不存在：`GET /results/missing-result/screenshot`
  - 边缘拉不存在资产：`GET /edge/pull_asset?asset_id=missing-asset`
  - 边缘回传不存在任务：`POST /edge/push_results`
- 实测结果：
  - 均返回结构化 `detail = {code, message, next_step}`
  - 典型返回码覆盖 `400 / 404`
  - 结果中心和边缘执行链路现在已经能稳定返回“原因 + 下一步”，不是裸英文错误

### 27. 训练中心导出 / 改派 / 重试失败已切换成结构化错误
- 实测失败场景：
  - 车号文本训练数据导出时使用无效敏感等级：`POST /training/car-number-labeling/export-text-assets`
  - 对成功作业执行改派：`POST /training/jobs/{job_id}/reassign`
  - 对成功作业执行重试：`POST /training/jobs/{job_id}/retry`
- 实测结果：
  - 都返回结构化 `detail = {code, message, next_step}`
  - 典型错误码覆盖：
    - `sensitivity_level_invalid`
    - `training_job_reassign_succeeded_forbidden`
    - `training_job_retry_status_invalid`
  - 训练中心高频控制动作现在已经能稳定返回“原因 + 下一步”，不再把 `SUCCEEDED job cannot be reassigned` 这类原始英文直接暴露给用户

### 28. 任务中心 / 模型中心 / 资产中心剩余高频错误已切换成结构化错误
- 实测失败场景：
  - 不存在任务详情：`GET /tasks/missing-task`
  - 删除不存在任务：`DELETE /tasks/missing-task`
  - 预检扫描使用不存在资产：`POST /tasks/preflight-inspect`
  - 流水线缺模型注册：`POST /pipelines/register`
- 实测结果：
  - 都返回结构化 `detail = {code, message, next_step}`，覆盖 `task_not_found / asset_not_found / pipeline_models_missing`
  - 任务中心的详情/删除、预检扫描，以及模型/流水线注册类高频失败场景，已经不再直接暴露原始英文错误
  - 资产中心、模型中心、结果中心、训练中心、边缘执行链路当前都已经接入同一套结构化错误模型

### 25. 登录失败 / 权限不足已切换成结构化错误
- 后端接口：
  - `POST /auth/login`
  - `GET /settings/data-governance`
  - `POST /settings/data-governance/run`
- 实测结果：
  - 使用错误密码登录时，`POST /auth/login` 返回 `401`，结构化 detail：
    - `code = login_invalid_credentials`
    - `message = 用户名或密码不正确。`
    - `next_step = 请重新输入账号密码后再登录；如果忘记密码，请联系平台管理员。`
  - 使用 `buyer_operator` 调用数据治理执行接口时，返回 `403`，结构化 detail：
    - `code = role_forbidden`
    - `message = 当前账号没有权限执行这个操作。`
    - `next_step = 请切换到具备相应权限的账号，或回到当前角色的默认工作区。`
- 说明：
  - 这轮改动把登录、权限不足、训练机器/边缘设备凭据失败统一到了 `code + message + next_step`
  - 前端公共 API 层会优先展示这类结构化错误，不再依赖原始英文 detail

### 26. 资产预览 / 数据集预览 / 流水线注册发布错误已结构化
- 后端接口：
  - `GET /assets/{asset_id}/content`
  - `GET /assets/dataset-versions/{version_id}/preview`
  - `GET /assets/dataset-versions/{version_id}/preview-file`
  - `POST /pipelines/register`
  - `POST /pipelines/release`
- 实测结果：
  - 访问不存在资源内容时返回 `404`：
    - `code = asset_not_found`
    - `message = 资源不存在，或当前账号看不到这条资源。`
  - 访问不存在数据集版本预览时返回 `404`：
    - `code = dataset_version_not_found`
    - `message = 数据集版本不存在，或当前账号看不到这版数据集。`
  - 发布不存在流水线时返回 `404`：
    - `code = pipeline_not_found`
    - `message = 流水线不存在，或当前账号看不到这条流水线。`
  - 注册空流水线配置时返回 `400`：
    - `code = pipeline_models_missing`
    - `message = 流水线至少要绑定一版路由模型或专家模型后才能注册。`
- 说明：
  - 这轮改动把资产中心和流水线中心里最常见的一批裸英文失败场景后端化了
  - 前端无需再靠字符串匹配猜测错误含义，就能直接显示“原因 + 下一步”
  - 从任务页“带入下方精确任务”、创建成功、结果页查询成功等动作会自动切到对应工作区

### 22. 页面级走查与默认术语减负阶段性收口
- 当前前端交互变化：
  - 工作台首页、资产、模型、训练、流水线、任务、结果、审计、车号文本复核、任务详情都已经完成“页内导航 / 二级导航 / 技术详情后置”
  - 默认可见区里的 `task_id / asset_id / model_id / pipeline_id / worker / bbox / engine` 等工程词已大面积退到 `技术详情`
  - 模型发布、流水线发布、结果回灌训练数据这几处仍残留的混合标签，本轮继续替换成自然中文表单语言
  - 页面级走查结论已单独沉淀到 `browser_walkthrough_report_2026-03-12.md`
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js` 已同步进运行中的 `vistral_frontend`
- 说明：
  - 这一轮的目标不是新增业务能力，而是把“默认可见区去工程味 + 页面结构导航化 + 长文本不破版”压到阶段性收口

### 23. 前端高频错误提示模板扩展（Round 2）
- 当前前端交互变化：
  - `frontend/src/core/api.js` 新增了一批常见错误映射，覆盖模型、流水线、资产、ZIP 数据集、训练机、训练作业、登录等高频失败场景
  - 例如 `dataset_label is required / Pipeline references unknown models / Invalid ZIP archive / Target worker is not ACTIVE` 这类原始报错，都会转成可操作中文提示
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/core/api.js` 通过
- 说明：
  - 这轮先在前端统一错误口径，后续再继续往后端结构化错误返回推进

### 22. 首页总览也改成二级导航，导航化主任务基本收口
- 当前前端交互变化：
  - 首页 `工作台总览` 内部新增二级导航：`主线指标 / 真实数据盘`
  - 默认先看四条主线指标；需要确认 demo_data、车号样本和 OCR 训练包时，再进入真实数据盘
  - 到目前为止，高复杂功能页都已从“整页平铺多套功能”改成“页内导航 + 分步进入”的结构
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js` 已同步进运行中的 `vistral_frontend`
  - 容器内已确认新标记存在：
    - `data-dashboard-overview-tab="lanes"`
    - `data-dashboard-overview-panel="real-data"`
- 说明：
  - 这轮标志着“用导航替代堆叠”的主任务基本收口，后续重点转为细节收边和残余技术噪音清理

### 23. 模型页 / 流水线页残余工程术语继续减负
- 当前前端交互变化：
  - 模型页创建训练表单里的 `基础算法编号` 已改成 `基础模型编号`
  - 流水线注册表单里的 `pipeline_code / name / version / router_model_id / expert_map` 等混合标签已改成更自然的中文表单标签
  - 流水线发布工作台里的 `target_devices / target_buyers / traffic_ratio / release_notes` 已改成自然表单语言
  - 流水线工作台概览里的 `router_model_id` 提示已改成更自然的“当前绑定的路由模型”
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js` 已同步进运行中的 `vistral_frontend`
- 说明：
  - 这轮继续削弱默认视图里的接口参数感，让模型页和流水线页更接近业务工作台

### 24. 指南页 / 训练机管理 / 训练协作列表继续去工程术语
- 当前前端交互变化：
  - 指南页中的 `readiness` 已改成更自然的 `验证门禁`
  - 模型中心训练协作列表里的 `train / val / candidate` 已改成 `训练集 / 验证集 / 待验证模型`
  - 训练机器管理表单里的 `labels(JSON) / resources(JSON)` 已改成 `机器标签（JSON）/ 机器资源（JSON）`
  - 流水线示例区里的 `expert_map` 标题已改成 `示例专家模型分配`
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js` 已同步进运行中的 `vistral_frontend`
- 说明：
  - 这轮继续清理“只看中文也能理解大概在做什么”的默认视图，把工程词尽量压到不得不用的地方

### 25. 结果页 / 模型评估区继续去英文指标名
- 当前前端交互变化：
  - OCR 结果信号区的 `confidence / engine / bbox` 已改成 `识别置信度 / 识别引擎 / 定位框`
  - 结果页验证结论里的 `val_accuracy` 已改成 `验证准确率`
  - 模型表现卡和模型评估区里的 `val_score / val_loss / history / best_checkpoint / latency_ms / gpu_mem_mb` 已改成更自然的中文指标名
  - 结果详情里的 `result_id / model_id / alert_level / stage / 结果 JSON` 已改成更自然的中文说明
  - `Advanced` 已统一成 `技术详情`
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js` 已同步进运行中的 `vistral_frontend`
- 说明：
  - 这轮继续把结果页和模型表现区往“验收页 / 结论页”方向推，减少训练日志味道

### 26. 训练页 / 任务页高频卡片继续去技术字段名
- 当前前端交互变化：
  - 训练摘要里的 `job_code / artifact_sha256 / base_model_hash / history_count` 已改成更自然的中文标签
  - 训练机器列表里的 `worker / worker_id / host / last_seen / alert / resources` 已改成 `训练机器 / 机器编号 / 机器地址 / 最近出现 / 告警级别 / 机器资源详情`
  - 任务页模型库和批量结果卡里的 `task_type / plugin / model_id / asset_id / task_id / object_count / dataset_asset_id` 已改成自然中文
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js` 已同步进运行中的 `vistral_frontend`
- 说明：
  - 这轮继续清理任务页和训练页最常被看到的技术字段，让高频操作区更接近普通业务工作台
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js` 已同步进运行中的 `vistral_frontend`
  - 容器内已确认存在：
    - `data-task-panel-tab="quick"`
    - `data-result-panel-tab="query"`
- 说明：
  - 这轮针对“同页堆太多功能”的可用性问题，改用明确导航引导用户逐步进入

### 22. 模型页 / 训练页继续改成分步导航
- 当前前端交互变化：
  - 模型页在原有 `模型总览 / 提交与训练协作 / 审批与发布` 基础上，再把内部动作拆成二级导航：
    - `提交与协作 / 创建训练`
    - `时间线与评估 / 审批工作台 / 发布工作台`
  - 训练页在 `创建训练` 工作区内新增二级导航：
    - `准备训练 / 数据集版本 / 创建训练`
  - 这样用户不会在一个工作区里同时看到算法库、训练机池、数据集版本和创建表单全部堆在一起
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js` 已同步进运行中的 `vistral_frontend`
  - 容器内已确认存在：
    - `data-model-build-tab="submit"`
    - `data-training-create-tab="prep"`
- 说明：
  - 这轮继续贯彻“同页不堆功能”的原则，把高复杂工作区进一步拆成按步骤进入的页面内导航

### 23. 流水线页继续改成分步导航
- 当前前端交互变化：
  - 流水线页在 `注册配置` 工作区内部新增二级导航：
    - `注册流水线`
    - `发布前提示`
  - 这样用户不再同时面对注册表单和整块提示信息，而是先完成当前步骤，再按需查看建议
- 实测验证：
  - `node --experimental-default-type=module --check frontend/src/pages/index.js` 通过
  - 新版 `index.js` 已同步进运行中的 `vistral_frontend`
  - 容器内已确认存在：
    - `data-pipeline-build-tab="register"`
- 说明：
  - 这轮补齐了流水线页的引导式导航，使模型、训练、流水线三类高复杂页面都遵循同样的“分步进入”原则

## 这轮已修复的运行缺口

### A. 复核页导出训练资产时报 `body stream already read`
- 根因：前端错误处理重复读取同一个 Response body
- 修复位置：`frontend/src/core/api.js`

### B. 重复导出 OCR 文本数据集时撞 `uq_dataset_key_version`
- 根因：dataset version 编号按 buyer scope 算，但 DB 唯一约束是全局 `(dataset_key, version)`
- 修复位置：`backend/app/services/dataset_version_service.py`

### C. 训练 worker 默认找错密钥路径，导致 `failed to decrypt base model`
- 根因：默认路径依赖当前 shell cwd
- 修复位置：`docker/scripts/training_worker_runner.py`

### D. training job 处于 `DISPATCHED` 但 worker 重启后接不回
- 根因：pull-jobs 只返回 `PENDING`
- 修复位置：`backend/app/api/training.py`

### E. 发布后买家推理结果缺少 final summary 的车号文本
- 根因：orchestrator final result 未补统一摘要
- 修复位置：`edge/inference/pipelines.py`

## 当前仍需继续跟进

### 1. OCR 真泛化仍未收口
- 已知复核样本、fixture、已整理难样本可稳定命中
- 但陌生低清图仍可能低置信度或 `ocr_unavailable`

### 2. 训练页 / 模型页 / 流水线页还需继续统一“工作台化”视觉
- 任务页和结果页近几轮已经明显收口
- 训练页、模型页、流水线页已补第一轮工作台概览，但列表形态和默认字段量仍偏重

### 3. 结果页和训练页还需要一轮完整人工视觉走查
- 本次以真实 API / 容器 / 任务执行为主
- 已补第一版走查清单：`browser_walkthrough_checklist_2026-03-11.md`
- 还未做逐页浏览器交互录像式检查

## 2026-03-11 术语减负进展

- 车号文本复核页主按钮已改成“先准备训练数据 / 现在开始训练”
- 结果页已把“结果回灌工作台”改成“把确认结果变成训练数据”
- 训练页高频入口已把“候选模型”改成更容易理解的“待验证模型 / 新模型”
- 资产页、任务页、训练页的高频表单已把 `asset_id / worker / model_id / task_id` 改写成更自然的“资产编号 / 训练机器 / 模型编号 / 任务编号”表达
- 全站视觉底座已升级为更统一的玻璃层、渐变光晕和柔和动态背景；关键卡片、工作台面板与切换器都增强了高科技感和高级感
- 首页 Hero、指南页和登录页也已同步到这套风格，避免只有业务页精致、首屏和入口页仍显旧
- 已修正首页“最近资产 / 最近模型 / 最近任务”卡片的长标题溢出风险：长文件名现在会在卡内断行，不再把整行布局顶坏

## 2026-03-11 历史数据清理结果

- 已按“只保留当前车号 OCR 示例主链 + 当前目标检测模型 + 当前演示流水线”完成真实清理。
- 当前保留对象：
  - 模型 `4` 个：
    - `car_number_ocr:v20260310.071357.e70b`
    - `object_detect:v1.0.1773044280`
    - `bolt_missing_detect:v1.0.1773044280`
    - `scene_router:v1.0.1772884678`
  - 训练作业 `2` 条：
    - `train-99c9db1739`（当前车号模型来源）
    - `train-577ce47c10`（原始本地训练素材来源）
  - 数据集版本 `2` 条：
    - `local-car-number-ocr-text-train:v27`
    - `local-car-number-ocr-text-validation:v27`
  - 流水线 `1` 条：
    - `demo-inspection-pipeline:v1.0.1772884688`
- 当前清理后库存：
  - `data_assets = 15`
  - `models = 4`
  - `training_jobs = 2`
  - `inference_tasks = 16`
  - `inference_results = 35`
  - `dataset_versions = 2`
  - `pipelines = 1`
- 已同步修正：
  - `demo-inspection-pipeline` 的 `expert_map` 已指向当前保留的 `car_number_ocr` 和 `bolt_missing_detect`
  - 历史 `api-*` 候选模型、回归资产、重复 OCR 导出包、旧任务截图已删除
- 执行脚本：
  - `docker/scripts/cleanup_keep_current_demo_chain.py`

## 2026-03-11 卡片列表溢出修复（Round 1）

- 本轮已统一修正以下通用区域的长文本溢出：
  - `selection-card`
  - `task-list-card`
  - `selection-summary`
  - `workbench-overview`
  - `metric-card`
  - `details-panel`
  - `badge`
  - `mono`
  - `page-hero-actions`
- 处理方式：
  - 补齐 `min-width: 0`
  - 标题/副标题/编号统一加 `overflow-wrap: anywhere`
  - badge 支持换行，不再一行硬撑
  - Hero 动作区、工作台动作区、任务卡头都补了子项收缩规则
- 目标：
  - 最近资产、最近模型、任务列表、工作台概览等卡片在遇到长文件名、长版本号、长 ID 时不再把网格撑坏
- 实测：
  - 新版 `frontend/assets/app.css` 已同步到运行中的 `vistral_frontend`

## 2026-03-11 车号文本复核页分区导航

- 车号文本复核页已从“大表单 + 列表 + 详情 + 导出”平铺结构改成页内导航：
  - `复核总览`
  - `待处理样本`
  - `当前样本复核`
  - `导出与训练`
- 默认先看总览，不再一进页面就把筛选、样本列表、当前复核和训练导出全部压在同一屏。
- 自动联动：
  - 从样本队列选择样本后，会自动切到“当前样本复核”
  - 点击导出文本训练包 / 先准备训练数据 / 现在开始训练时，会自动切到“导出与训练”
- 目的：
  - 降低认知负担
  - 让“复核”和“导出训练”变成更明确的两步，而不是一个混合页面

## 2026-03-11 工作台首页分区导航

- 首页已从“总览 + 最近资产 + 最近模型 + 最近任务”同屏平铺，改成页内导航：
  - `工作台总览`
  - `最近资产`
  - `最近模型`
  - `最近任务`
- 默认先展示：
  - 角色推荐动作
  - 当前角色重点
  - 主线指标
  - 真实数据基础盘
- 最近资产 / 最近模型 / 最近任务改成按需进入，减少首页一次性暴露过多列表卡片。

## 2026-03-11 任务详情页分区导航

- 任务详情页已从“执行摘要 + 动作按钮 + 技术详情”同屏平铺改成页内导航：
  - `执行结论`
  - `下一步动作`
  - `技术详情`
- 默认先展示任务状态、结果条数、识别摘要和 OCR 文本。
- 结果跳转、等待完成、返回任务中心等动作单独放进“下一步动作”。
- 原始任务 JSON 和长编号统一后置到“技术详情”。

## 2026-03-11 结果页“结果列表”二级导航

- 结果页的“结果列表”内部已继续拆成二级导航：
  - `结果概览`
  - `模型表现`
  - `单条结果`
- 查询成功后默认先看整体结论，不再把：
  - 结果概览卡
  - 模型表现卡
  - 单条结果卡
  同时压在一个长页面里。
- 这样用户先看“这次结果整体怎么样”，再决定是否深入到模型表现或逐条核对截图。

## 2026-03-11 训练页“训练机器”二级导航

- 训练页的“训练机器”工作区已拆成：
  - `机器总览`
  - `登记与清理`
- 默认先看：
  - 训练机器状态
  - 可用节点
  - 历史异常
- 机器登记、刷新和修正动作后置到“登记与清理”，避免查看机器状态时同时被管理表单打扰。

## 2026-03-11 训练页“训练总览”二级导航

- 训练页的“训练总览”已拆成：
  - `运行告警`
  - `训练作业`
  - `训练结果摘要`
- 默认先看：
  - 当前是否有超时作业
  - 训练机器异常
  - 运行健康状态
- 训练作业列表和训练结果摘要后置到各自分区，避免总览页继续同时铺开三大块内容。

## 2026-03-11 训练页“准备训练”二级导航

- 训练页“创建训练 -> 准备训练”已继续拆成：
  - `选择算法`
  - `选择训练机器`
- 默认先看“选择算法”，避免基础算法库和训练机池同时并排压在一屏。
- 用户选中基础算法后，页面会自动切到“选择训练机器”，形成更顺的两步引导。

## 2026-03-11 模型页“模型总览”二级导航

- 模型页的“模型总览”已拆成：
  - `工作台概览`
  - `模型列表`
- 默认先看：
  - 当前焦点模型状态
  - 风险和验证结论
  - 推荐下一步动作
- 只有在需要切换模型、做筛选或查看完整列表时，再进入“模型列表”。

## 2026-03-11 流水线页“流水线总览”二级导航

- 流水线页的“流水线总览”已拆成：
  - `工作台概览`
  - `流水线列表`
- 默认先看：
  - 当前焦点流水线状态
  - 路由模型与阈值概况
  - 推荐发布动作
- 只有在需要切换版本、做筛选或查看全量配置时，再进入“流水线列表”。

## 2026-03-12 资产页“资产总览”二级导航

- 资产页的“资产总览”已拆成：
  - `使用概览`
  - `资产列表`
- 默认先看：
  - 当前资产池用途分布
  - 资产数量
  - 推荐下一步动作
- 只有在需要复制资产编号、挑具体资产去任务或训练时，再进入“资产列表”。

## 2026-03-12 审计页“审计总览”二级导航

- 审计页的“审计总览”已拆成：
  - `工作台概览`
  - `最近动作`
- 默认先看：
  - 审计日志总量
  - 动作类型数量
  - 资源类型数量
  - 推荐下一步动作
- 只有在需要快速浏览最近发生的审批、训练、任务和结果事件时，再进入“最近动作”。

## 2026-03-12 高可见术语第二轮中文化

- 训练页、任务页、结果页、模型页、流水线页继续清掉了一批默认就能看到的技术词：
  - `task_id / asset_id / model_id / pipeline_id`
  - `plugin / task_type`
  - `Loss Curve / Accuracy Curve`
  - `Worker / worker_code / host`
- 结果页默认说明从“按 task_id 回查”改成“按任务编号回查”。
- 训练页里“本机训练 Worker / 受控训练 Worker”进一步改成了更自然的“本机训练机器 / 受控训练机”。
- 车号文本复核页里的 `pending / final_text / bbox / engine` 也改成了中文业务词。

## 2026-03-12 默认可见区术语减负阶段性收口

- 默认可见区现在优先显示：
  - 任务编号 / 资产编号 / 模型编号 / 流水线编号
  - 训练机器 / 本机训练机器 / 受控训练机
  - 损失曲线 / 准确率曲线 / 最佳检查点
  - 最终文本 / 定位框 / 识别引擎
- 剩余接口字段、JSON 字段和排障数据已基本后置到：
  - `技术详情`
  - `原始结果数据`
  - `训练参数与输出摘要`

## 2026-03-12 OCR 运行评估已切到“真实真值 + 可关闭 curated 快捷命中”

- `docker/scripts/evaluate_car_number_ocr_samples.py` 已改成优先使用 `final_text` 做真值，不再把 `ocr_suggestion` 当成唯一基线。
- 新增了三种关键评估开关：
  - `--variant`
  - `--rename-upload`
  - `--disable-curated-match`
- 这使得运行评估可以明确区分两类情况：
  - 已知样本在 curated/fixture 快捷命中下是否稳定
  - 关闭快捷命中后，真实 OCR 泛化是否仍能读出 8 位车号

## 2026-03-12 OCR 二阶段扩框重扫已落地，真实泛化探针出现提升

- 在 `edge/inference/pipelines.py` 中，`car_number_ocr` 已增加：
  - 合法候选优先
  - 规则拒绝前的二阶段扩框重扫
  - 更多 Tesseract 预处理与 `psm` 组合
- 真实 8 样本泛化探针对比：
  - 第一轮报告：`car_number_runtime_eval_generalization_probe_after_fix_20260312T032001Z.json`
    - `2/8 ok`
    - `6/8 empty`
  - 第二轮报告：`car_number_runtime_eval_generalization_probe_after_fix_v2_20260312T032914Z.json`
    - `3/8 ok`
    - `1/8 ground_truth_mismatch`
    - `4/8 empty`
- 结论：
  - 方向有效，说明“扩框重扫”能救回一部分原先直接 `ocr_rule_rejected` 的样本
  - 但真实泛化仍未收口，剩余难例主要是：
    - 左侧/首位丢失
    - 低清窄框下的整串错位

## 2026-03-12 OCR 第三轮增强实验已回退

- 试过的增强：
  - `CLAHE / sharpen`
  - 更激进的多 `psm` 穷举
- 真实结果：
  - 首样本从正确回退成 `40081221`
  - 第二样本客户端轮询超时
- 处理：
  - 已把这轮实验性增强撤回
  - 运行中的 `vistral_edge_agent` 保持在第二轮“扩框重扫”的稳定版本

## 2026-03-12 OCR 场景配置对齐库内 45° 侧拍车身标记识别

- 新增配置：
  - `config/ocr_scene_profiles.json`
  - 当前激活：`railcar_yard_side_view_v1`
- 已预留目标：
  - `车号`
  - `定检标记`
  - `性能标记`
- OCR 推理新增：
  - 可配置文字带搜索区
  - `clahe / sharpen / top_hat / rectified` 变体
  - 旋转矫正文字带
  - 对合法 8 位候选更早接受
  - 规则拒绝后的超宽扩框救援
- 本地关闭 curated 命中的难样本 probe：
  - `9664...jpg -> 62745500` 正确
  - `6775...jpg -> 60460282`，仍与真值 `60460284` 有 1 位偏差
  - `2477 / 2216 / 3542` 仍为 `ocr_rule_rejected`
- 结论：
  - 这轮完成了面向机器人巡检场景的能力准备
  - 但 `T5` 仍未收口，下一步要继续做截断数字与位数补偿救援
  - 后续补了“滑窗条带 + 投影细分”后，`2216` 已从空结果提升到可读，但读成 `35152220`，说明方向有效但假阳性约束还不够；`2477 / 3542` 仍未拉回
  - 再后续补了“合法 8 位结果稳定性判别”后，`2216` 已从“错号”拉回为 `ocr_rule_rejected`；`6775` 仍与真值差 1 位，当前重点已转到字符级纠错而不是继续盲目放大 ROI

## 2026-03-12 巡检任务扩成正式模型族，车号规则升级为多规则族

- 新增配置：
  - `config/car_number_rules.json`
  - `config/railcar_inspection_task_catalog.json`
- 本轮变化：
  - 车号校验不再假设“只能是 8 位数字”，已升级成多规则族：
    - 标准 8 位数字车号
    - 字母前缀数字编号
    - 紧凑型混合编号
  - 平台任务目录已正式扩展到：
    - `car_number_ocr`
    - `inspection_mark_ocr`
    - `performance_mark_ocr`
    - `door_lock_state_detect`
    - `connector_defect_detect`
- 说明：
  - 这是训练与选模基础设施升级，不代表这些新增任务已经有可发布模型
  - 当前真实闭环仍以 `car_number_ocr` 为主，其它任务进入“设计完成、训练待推进”状态

## 2026-03-12 训练中心已能承接巡检模型族首版训练预设

- 前端变化：
  - 训练中心新增首版预设：
    - `定检标记 OCR · 标准微调`
    - `性能标记 OCR · 标准微调`
    - `门锁状态 · 标准训练`
    - `连接件缺陷 · 标准训练`
  - 切换预设时会自动建议对应的目标模型编码，并在“当前选择”里显示预设说明
- 说明：
  - 这是训练入口就绪，不代表这些任务已有真实训练数据和已发布模型

## 2026-03-12 巡检 OCR 工作区已进入代理裁剪队列阶段

- 新增脚本：
  - `docker/scripts/prepare_inspection_ocr_proxy_crops.py`
- 新增蓝图字段：
  - `proxy_crop_profile`
- 真实执行结果：
  - `inspection_mark_ocr`：`80` 条整图样本中，`77` 条已生成代理裁剪，`77` 条进入 `needs_check`
  - `performance_mark_ocr`：`80` 条整图样本中，`77` 条已生成代理裁剪，`77` 条进入 `needs_check`
  - 两个工作区各有 `3` 条因 `_annotations.txt` 缺少 anchor，仍保持整图待处理
- 训练中心摘要现已显示：
  - `已裁剪候选区域`
  - `生成代理裁剪` 命令
- 后续新增：
  - `已有文字建议`
  - `生成文字建议` 命令
- 结论：
  - `inspection_mark_ocr / performance_mark_ocr` 已从“整图待处理清单”推进到“可直接人工复核 crop 队列”
  - `door_lock_state_detect / connector_defect_detect` 仍停留在采集计划模板阶段，下一步需要真实近景图像
  - 当前对两类 OCR 工作区跑了全量自动文字建议，但 `suggestion_rows = 0`
  - 使用 `build_inspection_task_dataset.py --allow-suggestions` 做 smoke 打包时，真实返回 `need at least 2 reviewed rows to build train/validation bundles`
  - 这说明当前阻断点已经从“没有裁剪图”前移到“没有真实文本真值 / 没有可用自动建议”

## 2026-03-13 巡检 OCR 已完成“首版训练作业 -> 待验证模型”闭环

- 本机训练机器已重新拉起并恢复为 `ACTIVE`
  - `worker_code = local-train-worker`
  - `heartbeat_age_sec ~= 1-2`
- 真实训练作业：
  - `train-4f1de3303e`
    - `target_model_code = inspection_mark_ocr`
    - `status = SUCCEEDED`
    - `assigned_worker_code = local-train-worker`
  - `train-796e22cd0c`
    - `target_model_code = performance_mark_ocr`
    - `status = SUCCEEDED`
    - `assigned_worker_code = local-train-worker`
- 真实待验证模型：
  - `inspection_mark_ocr:v20260312.154741.13db`
    - `model_id = 81c6fe9f-83fb-435d-87c1-376ef620b4fb`
    - `status = SUBMITTED`
    - `approval-workbench.can_approve = true`
  - `performance_mark_ocr:v20260312.154742.a773`
    - `model_id = b1027db7-e0c5-4de6-9ee8-4f6141706de9`
    - `status = SUBMITTED`
    - `approval-workbench.can_approve = true`
- 说明：
  - 巡检 OCR 这两类任务现在已经不再只是“工作区 + 裁剪队列 + 首版 ZIP”
  - 它们已经进入：
    - 首版文本训练包
    - 训练作业
    - 待验证模型
    - 审批工作台可见
  - 下一步真正的价值点，已经转成继续补更多真实 `final_text`，提升新模型的真实泛化意义

## 2026-03-13 训练中心已直接回显巡检 OCR 的最新训练状态

- `/training/inspection-workspaces/summary` 现在会直接返回：
  - `latest_training_job`
  - `latest_candidate_model`
- 当前真实返回：
  - `inspection_mark_ocr`
    - 最近训练作业：`train-4f1de3303e`
    - 当前待验证模型：`inspection_mark_ocr:v20260312.154741.13db`
  - `performance_mark_ocr`
    - 最近训练作业：`train-796e22cd0c`
    - 当前待验证模型：`performance_mark_ocr:v20260312.154742.a773`
- 这意味着训练中心里不再只看到“数据准备度”，而是能直接看到：
  - 当前这条 inspection 任务已经训练到哪一步
  - 有没有最新待验证模型
  - 下一步该去训练作业还是模型审批

## 2026-03-13 巡检 OCR 已完成第二轮代理真值扩样与再训练

- 新增脚本：
  - `docker/scripts/seed_inspection_ocr_from_car_number_truth.py`
- 真实执行结果：
  - `inspection_mark_ocr`
    - `reviewed_rows = 9`
    - `train = 7`
    - `validation = 2`
    - 第二轮训练作业：`train-71de4b1551`
    - 新待验证模型：`inspection_mark_ocr:v20260313.001308.df11`
    - `model_id = b7128198-4c38-4e40-ac8f-def3f92cb6ff`
  - `performance_mark_ocr`
    - `reviewed_rows = 9`
    - `train = 7`
    - `validation = 2`
    - 第二轮训练作业：`train-c176e03416`
    - 新待验证模型：`performance_mark_ocr:v20260313.001308.a946`
    - `model_id = 90b64926-2b3d-49c1-ac8e-25ecbd19013b`
- 真实验证：
  - `GET /training/inspection-workspaces/summary`
    - 两个任务都已返回最新 `job_code / model.version / reviewed_rows`
  - `GET /models/{id}/approval-workbench`
    - 两个新模型的审批工作台均可读
- 说明：
  - 这轮不是新增 UI，而是真正把巡检 OCR 从 `2` 条种子文本推进到了 `9` 条代理真值、`7+2` 的最小可训规模
  - 下一步重点不再是“让它能训练”，而是继续扩大真实 `final_text` 覆盖，降低这批代理真值带来的偏差

## 2026-03-13 巡检 OCR 第三轮已把代理真值风险显式打到审批工作台

- 真实动作：
  - 修复运行中 backend 对 `build_inspection_task_dataset.py` 的旧模块缓存问题
  - 重新导出 inspection/performance OCR 训练资产
  - 重新触发第三轮训练作业
- 第三轮真实训练结果：
  - `inspection_mark_ocr`
    - 训练作业：`train-cc7fd43563`
    - 新待验证模型：`inspection_mark_ocr:v20260313.010220.6bad`
    - `model_id = 42587051-3c82-4f1f-9c69-dced1d3db0fe`
  - `performance_mark_ocr`
    - 训练作业：`train-498aa6d26e`
    - 新待验证模型：`performance_mark_ocr:v20260313.010220.bbd5`
    - `model_id = 0af8db90-7a14-4b36-a2dc-b08671f0077a`
- 真实验证：
  - `POST /training/inspection-ocr/inspection_mark_ocr/export-dataset`
    - 返回 `reviewer_counts = {proxy_from_car_number_truth: 6, platform_admin: 3}`
    - 返回 `proxy_seeded_rows = 6`
  - `GET /models/{id}/approval-workbench`
    - `readiness.validation_report.data_provenance.asset_count = 2`
    - `readiness.validation_report.data_provenance.proxy_seeded_rows = 12`
    - `readiness.validation_report.checks[*].code` 含 `proxy_truth_risk`
- 说明：
  - 这轮的价值不是再多产一版候选模型，而是把“代理真值训练出来的模型带风险”正式显式到治理层
  - 现在审批人已经能在工作台里看到：这批模型当前仍混有多少代理回灌文本，不能把它当作纯真实真值训练结果

## 2026-03-13 inspection OCR 已进入“优先替换代理真值”工作流

- 新增能力：
  - inspection OCR 复核页支持 `仅看代理回灌`
  - 训练中心工作区卡片支持显示：
    - `manual_reviewed_rows`
    - `proxy_replacement_samples`
  - 后端列表接口支持：
    - `GET /training/inspection-ocr/{task_type}/items?proxy_seeded=true`
- 真实验证：
  - `GET /training/inspection-ocr/inspection_mark_ocr/summary`
    - `proxy_seeded_rows = 6`
    - `manual_reviewed_rows = 3`
    - `proxy_replacement_samples = 6`
  - `GET /training/inspection-ocr/inspection_mark_ocr/items?proxy_seeded=true&limit=3`
    - `total = 6`
    - `first_proxy_seeded = true`
    - `first_origin = 代理回灌`
  - `GET /training/inspection-workspaces/summary`
    - `inspection_mark_ocr.proxy_seeded_rows = 6`
    - `inspection_mark_ocr.manual_reviewed_rows = 3`
    - `inspection_mark_ocr.proxy_replacement_samples = 6`
- 说明：
  - 现在真正的剩余工作已经收敛成“把代理回灌样本逐条替换成真实标记真值”
  - 系统已经不再缺页面、缺接口、缺筛选，而是进入人工补真值和下一轮再训练阶段

## 2026-03-13 inspection OCR 已增加“代理真值默认阻断”门禁

- 新增能力：
  - 当 inspection OCR 工作区仍含代理回灌真值时，默认阻止：
    - 导出训练包
    - 导出训练资产
    - 直接创建训练作业
  - 只有显式允许“带代理真值继续训练（仅冷启动）”时才放行
- 真实验证：
  - `POST /training/inspection-ocr/inspection_mark_ocr/export-dataset`
    - 默认 -> `400 inspection_ocr_proxy_truth_present`
    - 显式传 `allow_proxy_seeded = true` -> `200`
      - `accepted_rows = 9`
      - `train_rows = 7`
- 说明：
  - 这一步把 inspection OCR 的当前状态从“能继续往前走”收成了“默认安全，显式放行”
  - 现在冷启动训练仍可做，但不会再把带代理真值的数据当成默认正常路径

## 2026-03-13 inspection OCR 已补“原图联看 + 代理替换队列导出”

- 新增能力：
  - `GET /training/inspection-ocr/{task_type}/items/{sample_id}/source`
    - 复核页可同时查看 crop 与原图
  - `GET /training/inspection-ocr/{task_type}/export-proxy-queue`
    - 可导出 `proxy_replacement_queue.csv` 给人工逐条替换代理回灌真值
- 真实验证：
  - `GET /training/inspection-ocr/inspection_mark_ocr/items/{sample_id}/source`
    - `200`
    - `content-type = image/jpeg`
  - `GET /training/inspection-ocr/inspection_mark_ocr/export-proxy-queue`
    - `200`
    - `content-type = text/csv`
- 说明：
  - 这一步把 inspection OCR 从“只能在 crop 小图里猜文本”推进到更适合人工批量真值替换的状态
  - 当前剩余主线工作可以更集中地落在“逐条替换代理真值”本身，而不是再补查看工具

## 2026-03-13 inspection OCR 已补“离线复核 CSV 批量导回”

- 新增能力：
  - `POST /training/inspection-ocr/{task_type}/import-reviews`
  - 支持把离线填写过的 CSV 批量回写到工作区
- 真实验证：
  - 先导出：
    - `GET /training/inspection-ocr/inspection_mark_ocr/export-proxy-queue` -> `200`
  - 再原样导回：
    - `POST /training/inspection-ocr/inspection_mark_ocr/import-reviews`
    - 返回：
      - `updated_rows = 0`
      - `skipped_rows = 6`
      - `missing_sample_ids = []`
- 说明：
  - 当前 inspection OCR 已具备“导出队列 -> 离线补文本 -> 批量导回”的闭环
  - 这让后续替换 `proxy_seeded` 样本不再被单条表单操作卡住

## 2026-03-13 inspection OCR 已补“人工替换离线工作包”

- 新增能力：
  - `GET /training/inspection-ocr/{task_type}/export-review-pack`
  - 导出 `proxy_review_pack.zip`
- 真实验证：
  - `GET /training/inspection-ocr/inspection_mark_ocr/export-review-pack`
    - `200`
    - `content-type = application/zip`
    - ZIP 内包含：
      - `proxy_replacement_queue.csv`
      - `README.txt`
      - `crops/*`
      - `sources/*`
    - 当前真实 inspection_mark_ocr review pack 内：
      - `crop_entries = 6`
      - `source_entries = 6`
- 说明：
  - inspection OCR 现在已经具备“导出工作包 -> 离线批量补真值 -> CSV 导回”的完整人工替换链路
  - 这部分工具链可以视为阶段性收口

## 2026-03-13 inspection/performance OCR 代理裁剪已改成更贴近真实标记区域

- 新变化：
  - `performance_mark_ocr` 代理裁剪不再围绕车号框整体扩张，而是优先截取“车号上方性能码带”
  - `inspection_mark_ocr` 代理裁剪改成优先截取“车号下方检修记录 / 小字信息带”
- 对应实现：
  - `config/railcar_inspection_dataset_blueprints.json`
  - `docker/scripts/prepare_inspection_ocr_proxy_crops.py`
- 真实重裁结果：
  - 两类任务都重新执行了 `--force` 代理裁剪
  - `inspection_mark_ocr.crop_ready_rows = 77`
  - `performance_mark_ocr.crop_ready_rows = 77`
- 真实建议结果：
  - `inspection_mark_ocr.suggestion_rows = 59`
  - `performance_mark_ocr.suggestion_rows = 57`
- 说明：
  - 这意味着 inspection/performance OCR 已经从“几乎没有自动建议，只能纯人工起步”推进到“有大量可读建议，可作为人工起步参考”
  - 但正式训练仍继续以人工确认的 `final_text` 为主，自动建议不能直接等价于真值

## 2026-03-13 inspection/performance OCR 已补高质量建议专用复核闭环

- 已新增后端接口：
  - `GET /training/inspection-ocr/{task_type}/export-high-quality-queue`
  - `GET /training/inspection-ocr/{task_type}/export-high-quality-pack`
- 已新增前端入口：
  - `仅看高质量建议`
  - `优先确认高质量建议`
  - `导出高质量建议队列`
  - `导出高质量建议包`
- 运行中 backend 函数级验证（`inspection_mark_ocr`）：
  - `high_quality_suggestion_rows = 51`
  - `high_quality_review_candidate_rows = 51`
  - `high_quality_suggestion_samples = 8`
  - 高质量建议队列导出：`text/csv; charset=utf-8`
  - 高质量建议包导出：`application/zip`
