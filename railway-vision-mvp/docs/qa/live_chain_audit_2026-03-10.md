# Live Chain Audit 2026-03-10

本记录只写当日真实运行环境的实测结果，不写设想。

关联执行面板：
- 动态待办清单：`../product/dynamic_execution_todo_2026-03-11.md`
- 页面级走查报告：`./browser_walkthrough_report_2026-03-12.md`

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
