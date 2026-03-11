# Live Chain Audit 2026-03-10

本记录只写当日真实运行环境的实测结果，不写设想。

关联执行面板：
- 动态待办清单：`../product/dynamic_execution_todo_2026-03-11.md`

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
