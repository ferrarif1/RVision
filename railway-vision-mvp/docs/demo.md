# 演示脚本（docs/demo.md）

- Last Updated: 2026-03-14 13:05 CST

## 0. 一键全自动（推荐，零数据零模型）

你现在没有任何视频/图片/模型时，直接运行：

```bash
cd <repo-root>
bash docker/scripts/bootstrap_demo.sh
```

该脚本会自动完成：

- 生成证书与密钥
- 启动中心端服务（postgres/redis/backend/frontend）
- 生成三个演示模型包（主路由、车号识别、螺栓缺失）
- 调用 API 自动完成“供应商提交 -> 平台审批 -> 平台发布”到 `edge-01`
- 自动注册并发布一条演示 Pipeline
- 自动生成演示图片（以及可选 mp4 视频）
- 自动用买家账号上传资产，并按 Pipeline 创建任务
- 启动 edge-agent 并等待任务完成
- 如果检测到 `demo_data/train/` 本地车号数据集，则额外自动切分 `train/validation`、上传 ZIP 训练资产、创建一条 `car_number_ocr` 微调作业，并用 `training_worker_runner.py --once` 跑完整一轮候选模型回收

快速识别现在支持两段式演示：

- 第一步先点“先扫一遍给建议”，系统会对当前资产发起轻量预检，返回候选任务类型、目标标签和 OCR 文本建议
- 第二步再按建议继续正式识别；如果是车号场景，会优先走 `car_number_ocr`，并直接展示车号文本，而不只是框出一个区域

本 demo 的文档口径也按同一 4 条业务线组织：

- 客户用户上传图片或视频资产，资产可用于训练、微调、测试验收或推理。
- 供应商上传初始算法与可选预训练模型，在平台受控环境内结合客户数据反复微调，形成候选成果模型并提交审批。
- 平台管理员结合客户测试数据验证模型有效性，审批并发布模型。
- 授权客户设备通过模型 API 或授权密钥使用加密模型，本地运行时完成解密。

需要注意：

- 这个 demo 真实覆盖的是“模型提审发布 + Pipeline 编排推理 + 结果回传”。
- 若 `demo_data/train/` 不存在，则 demo 仍只覆盖“模型提审发布 + Pipeline 编排推理 + 结果回传”。
- 若 `demo_data/train/` 存在并包含 `_annotations.txt`，则 demo 会补跑一次真实训练控制面闭环。

完成后直接打开：

- `https://localhost:8443`
- 账号：
  - 平台：`platform_admin/platform123`
  - 供应商：`supplier_demo/supplier123`
  - 买家：`buyer_operator/buyer123`

## 1. 手动流程（可选）

如果你只需要快速拉起中心端服务（不跑完整 demo），可直接使用：

```bash
cd <repo-root>
bash docker/scripts/start_one_click.sh
```

该脚本会自动执行 compose 启动，并按顺序等待以下任一健康检查通过：
- `http://localhost:8000/health`
- `https://localhost:8443/api/health`

若超时，会自动输出 backend/frontend 最近日志用于排障。

```bash
cd <repo-root>
./docker/scripts/generate_local_materials.sh
```

> 该脚本会本地生成：
> - HTTPS 自签证书（`docker/certs`）
> - 模型签名密钥对（`docker/keys`）
> - 模型加解密密钥（`docker/keys/model_encrypt.key` + `edge/keys/model_decrypt.key`）

## 1.1 启动基础服务

```bash
docker compose -f docker/docker-compose.yml up -d --build
```

如果出现 `auth.docker.io` 超时（拉不到 `python/nginx/postgres/redis`），先配置镜像源变量：

```bash
cd <repo-root>
cp docker/.env.example docker/.env
```

编辑 `docker/.env`，取消注释以下项（按你们内网可达镜像仓库替换）：

```env
POSTGRES_IMAGE=docker.m.daocloud.io/library/postgres:16-alpine
REDIS_IMAGE=docker.m.daocloud.io/library/redis:7-alpine
PYTHON_BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
EDGE_PYTHON_BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
NGINX_BASE_IMAGE=nginx:1.27-alpine
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
```

然后重试：

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml up -d --build
```

启动后：

- 前端（HTTPS）：`https://localhost:8443`
- 后端 API（直连）：`http://localhost:8000`
- PostgreSQL：`localhost:5432`
- Redis：`localhost:6379`

## 1.2 生成演示模型包（我方标准包）

### 1.2.0 下载开源预训练模型（示例）

```bash
cd <repo-root>
python3 docker/scripts/download_open_model.py --output backend/app/uploads/open_models/mobilenet_ssd_bundle.zip
```

该模型来源：开源 `MobileNet-SSD`（Caffe），打包为 `mobilenet_ssd_bundle.zip` 作为检测占位示例模型。

### 1.2.1 主路由包

```bash
docker compose -f docker/docker-compose.yml exec backend sh -lc '
  echo "demo-router-model" > /tmp/scene_router.bin &&
  python -m app.services.model_package_tool \
    --model-path /tmp/scene_router.bin \
    --model-id scene_router \
    --version v1.0.0 \
    --task-type scene_router \
    --model-type router \
    --runtime python \
    --plugin-name heuristic_router \
    --encrypt-key /app/keys/model_encrypt.key \
    --signing-private-key /app/keys/model_sign_private.pem \
    --output /app/app/uploads/scene_router_model_package.zip
'
```

### 1.2.2 车号识别包

```bash
docker compose -f docker/docker-compose.yml exec backend sh -lc '
  echo "demo-car-model" > /tmp/car_model.bin &&
  python -m app.services.model_package_tool \
    --model-path /tmp/car_model.bin \
    --model-id car_number_ocr \
    --version v1.0.0 \
    --task-type car_number_ocr \
    --encrypt-key /app/keys/model_encrypt.key \
    --signing-private-key /app/keys/model_sign_private.pem \
    --output /app/app/uploads/car_number_model_package.zip
'
```

### 1.2.3 开源检测包（可选）

推荐一键方式（直接把开源 `MobileNet-SSD` 打包成我方加密模型包，默认生成 `object_detect` 快速识别包）：

```bash
bash docker/scripts/build_open_model_package.sh
```

或手动方式：

```bash
docker compose -f docker/docker-compose.yml exec backend sh -lc '
  python -m app.services.model_package_tool \
    --model-path /app/app/uploads/open_models/mobilenet_ssd_bundle.zip \
    --model-id object_detect \
    --version v1.0.0-open \
    --task-type object_detect \
    --encrypt-key /app/keys/model_encrypt.key \
    --signing-private-key /app/keys/model_sign_private.pem \
    --output /app/app/uploads/object_detect_open_model_package.zip
'
```

模型包会落在主机目录：

- `backend/app/uploads/car_number_model_package.zip`
- `backend/app/uploads/scene_router_model_package.zip`
- `backend/app/uploads/object_detect_open_model_package.zip`

## 1.3 登录后台

打开 `https://localhost:8443`，使用默认账号：

- `platform_admin / platform123`（平台审批发布）
- `supplier_demo / supplier123`（供应商提交模型）
- `buyer_operator / buyer123`（买家上传与建任务）
- `buyer_auditor / buyer123`（买家只读）

前端会按角色自动显示模块：

- 平台管理员：可见并可操作全流程（提交/审批/发布/任务/结果/审计）
- 供应商：仅可见模型提交与模型列表（不可审批/发布）
- 买家操作员：可见资产上传、任务创建、任务监控、结果中心
- 买家审计员：仅可见任务监控、结果中心（只读）

当前主要控制台页已经统一成“总览优先、低频操作分工作区展开”的结构：

- 智能引导：`目标与资源 / 下一步引导 / API 模式 / 本地模型库 / 下载任务`
- 智能引导（新版 IA）：
  - 中间是对话主舞台
  - 右侧是上下文抽屉
  - 下方是统一输入区
  - 主题可切到 `ChatGPT 清透白 / 夏日奶油色`

- 工作台首页：`工作台总览 / 最近资产 / 最近模型 / 最近任务`
- 工作台首页（工作台总览内部）：`主线指标 / 真实数据盘`
- 模型中心：`模型总览 / 提交与训练协作 / 审批与发布`
- 模型中心（模型总览内部）：`工作台概览 / 模型列表`
- 训练中心：`训练总览 / 创建训练 / Worker 运维`
- 训练中心（训练总览内部）：`运行告警 / 训练作业 / 训练结果摘要`
- 训练中心（创建训练内部）：`准备训练 / 数据集版本 / 创建训练`
- 训练中心（准备训练内部）：`选择算法 / 选择训练机器`
- 训练中心（训练机器内部）：`机器总览 / 登记与清理`
- 流水线中心：`流水线总览 / 注册配置 / 发布管理`
- 流水线中心（流水线总览内部）：`工作台概览 / 流水线列表`
- 流水线中心（注册配置内部）：`注册流水线 / 发布前提示`
- 资产中心：`资产总览 / 上传资产 / 使用建议`
- 资产中心（资产总览内部）：`使用概览 / 资产列表`
- 审计中心：`审计总览 / 检索日志`
- 审计中心（审计总览内部）：`工作台概览 / 最近动作`
- 设备中心：`设备总览 / 设备列表`
- 设置：`账号总览 / 权限范围 / 数据治理 / 技术详情`
- 车号文本复核页：`复核总览 / 待处理样本 / 当前样本复核 / 导出与训练`
- 任务中心：`快速识别 / 创建任务 / 可选模型 / 任务列表`
- 任务详情页：`执行结论 / 下一步动作 / 技术详情`
- 结果中心：`查询结果 / 下一步动作 / 变成训练数据 / 结果列表`
- 结果中心（结果列表内部）：`结果概览 / 模型表现 / 单条结果`
- 查询结果后，系统会自动落到更适合当前任务的结果分区：
  - 有低置信度 OCR：优先打开 `单条结果`
  - 多模型非 OCR 结果：优先打开 `模型表现`
  - 其余默认打开 `结果概览`
- 模型中心（工作区内部）：`提交与协作 / 创建训练`，以及 `时间线与评估 / 审批工作台 / 发布工作台`
- 设置页里的 `数据治理` 工作区现在已经前台化，可直接预览并执行：
  - 只保留当前车号演示主链
  - 清理 synthetic 运行残留
  - 裁剪旧 OCR 导出历史
- 常见失败场景现在会统一显示“原因 + 下一步”，覆盖登录、权限不足、资产预览、流水线注册发布、结果截图、边缘拉资产/回传结果等主链，不再直接暴露后端英文错误。
- 训练中心里的高频失败场景也已纳入这套提示，包括：
  - 敏感等级填写错误

## 1.4 智能引导 / LLM 工作台演示

适合在“我知道要识别什么，但不知道下一步该去哪”的场景演示。

推荐演示路径：

1. 打开 `智能引导`
2. 上传一张铁路货车图片，或者直接填一条已有资产编号
3. 输入目标，例如：
   - `我想识别定检标记，并判断下一步是直接验证现有模型还是继续训练`
4. 选择模式：
   - `API 模式`
   - `本地模型模式`
5. 若选择本地模式，可直接在平台里浏览精选 10 个开源模型并发起下载
6. 点击生成引导后，查看：
   - 推断任务类型
   - 当前状态
   - 主推荐动作
   - 次推荐动作
7. 先选择执行方式：
   - `仅导航，不改字段`
   - `跳转并带建议过去`
8. 直接从该页跳到：
   - 任务中心
   - 训练中心
   - 模型审批 / 发布

当前这页不是泛聊天机器人，而是平台内的智能路由入口。
  - 成功作业尝试改派
  - 非失败作业尝试重试
- 巡检 OCR 工作区现在不只显示准备度，还能直接进入：
  - `inspection_mark_ocr` 文字复核
  - `performance_mark_ocr` 文字复核
  在这些页面里可以筛样本、看 crop、补 `final_text`，并直接导出文本训练包。
- 这两类任务现在已经各自产出首版 train/validation bundle：
  - `inspection_mark_ocr`
  - `performance_mark_ocr`
  说明这条线已经从“只有模板和复核页”推进到“真实训练包可产出”。
- 这两类任务现在也已经继续推进到：
  - 直接创建训练作业
  - `local-train-worker` 真实跑成 `SUCCEEDED`
  - 待验证模型回收入库并可在审批工作台查看
  - 训练中心工作区卡片可直接回显：
    - 已确认文本数量
    - 最近训练作业
    - 当前待验证模型
    - 直接跳到训练作业 / 待验证模型
- 目前最新一轮真实状态：
  - `inspection_mark_ocr`
    - 已确认文本：`9`
    - 第二轮训练作业：`train-71de4b1551`
    - 最新待验证模型：`inspection_mark_ocr:v20260313.001308.df11`
  - `performance_mark_ocr`
    - 已确认文本：`9`
    - 第二轮训练作业：`train-c176e03416`
    - 最新待验证模型：`performance_mark_ocr:v20260313.001308.a946`
- 第三轮治理验证状态：
  - `inspection_mark_ocr`
    - 第三轮训练作业：`train-cc7fd43563`
    - 审批工作台模型：`inspection_mark_ocr:v20260313.010220.6bad`
  - `performance_mark_ocr`
    - 第三轮训练作业：`train-498aa6d26e`
    - 审批工作台模型：`performance_mark_ocr:v20260313.010220.bbd5`
  - 这两版模型的审批工作台现在已经会直接提示：
    - `data_provenance.proxy_seeded_rows = 12`
    - `proxy_truth_risk`
    - 也就是审批人能明确知道当前模型仍然混入了代理回灌真值，不会误当成“纯真实真值训练”的结果
- inspection OCR 复核页也已经进入“优先替换代理真值”模式：
  - 可直接勾 `仅看代理回灌`
  - 可点击 `优先替换代理真值`
  - 当前真实返回：
      - `inspection_mark_ocr.proxy_seeded_rows = 6`
      - `inspection_mark_ocr.manual_reviewed_rows = 3`
      - `inspection_mark_ocr.proxy_replacement_samples = 6`
  - inspection OCR 复核页现已把“训练阻断样本”独立出来：
  - 可直接勾 `仅看训练阻断样本`
  - 可点击 `优先处理训练阻断样本`
  - 还支持：
    - `预检查阻断样本处理`
    - `批量处理训练阻断样本`
  - 可导出：
    - `readiness_blocker_queue.csv`
    - `readiness_blocker_pack.zip`
  - 当前真实返回：
    - `inspection_mark_ocr.readiness_blocker_rows = 6`
    - `inspection_mark_ocr.readiness_blocker_samples = 6`
  - 训练中心卡片和 OCR 复核摘要现在还会直接显示：
    - `当前行动：先处理训练阻断样本`
    - `处理完阻断样本后可正常训练`
    - `预计人工真值 9 条`
    - `处理完阻断样本后还差 0 条`
  - live smoke：
    - 前 2 条训练阻断样本预检查：`would_update_rows = 2`
    - 正式处理后中间态：`proxy_seeded_rows 6 -> 4`、`manual_reviewed_rows 3 -> 5`
    - 验证后已恢复工作区基线
- inspection OCR 导出训练包现在还有一层默认安全门禁：
  - 如果工作区里还有代理回灌真值，默认会直接阻止导出
  - 只有显式勾选 `允许带代理真值继续训练（仅冷启动）` 才会放行
  - inspection OCR 现在还会直接给出训练结论：
    - `可正常训练`
    - `仅冷启动可训练`
    - `仍不可导出`
    不再需要靠多段说明自己判断当前能否进入训练
  - inspection OCR 复核页现在还支持：
    - 同时查看 crop 和原图
    - 直接导出 `proxy_replacement_queue.csv`
    - 更适合把代理回灌样本批量替换成真实标记文本
  - inspection OCR 现在还支持：
    - 把离线补好的 CSV 批量导回工作区
    - 也就是完整支持：
      - 导出队列
      - 预检查 CSV 会更新哪些样本
      - 表格补真值
      - 批量导回
  - inspection OCR 现在还支持：
    - 直接导出 `proxy_review_pack.zip`
    - 包内同时带：
      - 队列 CSV
      - README
      - crops
      - sources
- 状态 / 缺陷两类任务这轮也已经进入正式产品闭环：
  - `door_lock_state_detect / connector_defect_detect` 的训练中心卡片可直接点 `打开状态复核`
  - 状态复核页支持：
    - 导入现有资产
    - 查看工作区摘要
    - 查看样本列表
    - 查看 crop / 原图
    - 保存状态标签
    - 导出状态复核队列
    - 导出人工复核包
    - 预检查离线复核 CSV
    - 导入离线复核 CSV
    - 导出训练包
    - 导出训练资产
    - 直接创建训练作业
  - 当前真实状态已经推进到：
    - `door_lock_state_detect.row_count = 2`
    - `connector_defect_detect.row_count = 2`
    - 两类任务的 `training_readiness.status = ready`
    - 已各自产生首条真实训练作业与待验证模型
    - `door_lock_state_detect` 作业：`train-bbab47f859`
    - `connector_defect_detect` 作业：`train-80b794db2e`
  - 训练中心工作区卡片和状态复核页现在还会直接显示：
    - `优先复核样本`
    - `训练就绪`
    - 建议采集条件
  - 但状态复核页现在已经可以直接把平台里的真实图片资产导入工作区：
    - `POST /training/inspection-state/{task_type}/import-assets`
    - 也就是说这两类任务已经不再需要线下手工改 `manifest.csv` 才能起步
  - 说明状态 / 缺陷类任务现在已经不再缺工具和入口，也不再缺第一批真实样本；下一步重点转成继续扩样本和做待验证模型审批
- 车号 OCR 现在还额外对齐了“库内 45° 侧拍车身标记识别”这一类机器狗/轮足机器人场景，场景配置已预留：
  - `车号`
  - `定检标记`
  - `性能标记`
  - `门锁状态`
  - `连接件缺陷`
- 车号规则也不再写死成“只能 8 位数字”，而是升级成多规则族：
  - 标准 8 位数字车号
  - 字母前缀 + 数字编号
  - 紧凑型混合编号
- 训练中心现在也已经为机器人巡检模型族预留了训练预设：
  - `车号 OCR`
  - `定检标记 OCR`
  - `性能标记 OCR`
  - `门锁状态识别`
  - `连接件缺陷识别`
  - `定检标记`
  - `性能标记`
  当前正式落地的仍是 `车号`；另外两个目标已完成场景入口预留，后续可接同一套巡检链路。
- 当前 OCR 泛化仍在持续优化中：`9664...jpg` 这类陌生样本已能在关闭 curated 命中后直接读准，`6775...jpg` 已逼近真值，但 `2477 / 2216 / 3542` 这类难样本仍会停在规则拒绝，需要继续迭代。

建议演示时先从各页“总览”工作区进入，再按需要展开低频配置和技术细节。

补充说明：

- 训练中心的 Worker 运维区现在默认先看卡片摘要，不再先看重表格。
- 任务详情页现在优先显示执行结论、识别摘要和结果入口；`asset_id / model_id / pipeline_id` 已后置到 `技术详情`。
- 当前整套前端已经统一为更强的工作台视觉语言：关键卡片、总览 Hero、工作区切换器、指标卡和状态徽标都有更明确的层次、玻璃层质感和选中反馈，演示时会比早期版本更像正式交付控制台。
- 登录页、工作台首页和指南页也已经同步到这套视觉语言，避免“业务页精致、入口页普通”的割裂感。
- 模型审批工作台、模型发布工作台和流水线发布工作台已经进一步做成“cockpit”式面板，建议演示时重点展示建议样本区、风险摘要区和发布配置区在一屏内的分层关系。
- 任务中心与结果中心的高频卡片也已经强化：批量快速识别、任务卡、下一步动作和“把确认结果变成训练数据”区会更有主次、聚焦感和光影层次，适合直接展示“日常高频使用”的成熟度。

## 1.4 模型提交、审批、编排与发布（三方流程）

1. 先用 `supplier_demo` 登录，进入“模型中心”上传主路由包、初始算法包、预训练模型包或微调候选模型包。
2. 如需完整演示验证审批链，可先用买家账号上传一份测试验收资产，记录 `asset_id`。
3. 再用 `platform_admin` 登录，进入“模型中心”点击“审批工作台”，系统会按模型能力自动推荐几张验证样本，并支持直接批量创建验证任务。
4. 等几条验证任务完成后，在同一工作台查看输出文本、confidence 和训练指标；满足门禁后点击“一键审批通过”，不必手填 `validation_asset_ids`。
5. 如需演示治理闭环而不是直接放行，可在审批工作台里点“要求补充材料”或“驳回这版模型”，并用“导出证据包”拿到当前模型的审批证据归档。
6. 审批通过后，在“发布工作台”里确认设备、买家和交付方式。系统会先给出发布前评估，再点“确认发布”。
7. 进入“流水线注册表”，用主路由和专家模型注册一条 Pipeline，再点“发布工作台”。系统会自动预填 `edge-01 / buyer-demo-001` 等推荐项，再确认发布。
8. 刷新模型列表和流水线列表，确认状态从 `SUBMITTED -> APPROVED -> RELEASED`，流水线状态为 `RELEASED`。

## 1.5 上传视频/图片

1. 在“上传资产”区域上传 `mp4` 或 `jpg/png`。
2. 选择数据用途，支持 `training`、`finetune`、`validation`、`inference`；本 demo 的任务演示通常选择 `inference`。
3. 选择敏感级别（推荐 `L2`）。
4. 上传成功后记录 `asset_id`。

## 1.5.1 本地车号素材自动训练（可选）

若你已经把货车车号图片和标注放在 `demo_data/train/` 下，`bootstrap_demo.sh` 会自动：

1. 读取 `_classes.txt` 和 `_annotations.txt`
2. 跳过“只有文件名、没有 bbox”的空标注行
3. 按稳定规则切出 `train / validation`
4. 生成：
   - `demo_data/generated_datasets/car_number_ocr_train_bundle.zip`
   - `demo_data/generated_datasets/car_number_ocr_validation_bundle.zip`
   - `demo_data/generated_datasets/car_number_ocr_dataset_summary.json`
5. 自动上传为 `training / validation` 资产
6. 以 `car_number_ocr` 为基模创建一条微调作业
7. 通过 `training_worker_runner.py --once` 跑完一次候选模型生成

## 1.5.2 生成 OCR 文本待标注清单

如果 `demo_data/train/` 只有号码框，没有文本真值，可先生成一份待标注队列：

```bash
cd <repo-root>
python3 docker/scripts/prepare_local_car_number_labeling_manifest.py \
  --source-dir demo_data/train \
  --output-dir demo_data/generated_datasets/car_number_ocr_labeling
```

输出内容：
- `demo_data/generated_datasets/car_number_ocr_labeling/manifest.csv`
- `demo_data/generated_datasets/car_number_ocr_labeling/manifest.jsonl`
- `demo_data/generated_datasets/car_number_ocr_labeling/crops/`
- `demo_data/generated_datasets/car_number_ocr_labeling/summary.json`

标注建议：
1. 用表格打开 `manifest.csv`
2. 按 `crop_file` 查看 crop，并填写 `final_text`
3. 用 `review_status` 标记 `pending / done / needs_check`
4. 保留 `ocr_suggestion` 列，后续可回算建议命中率

## 1.5.3 把已标注文本回灌成 OCR 训练包

当 `manifest.csv` 已经补好 `final_text` 后，可直接打成 crop 级 OCR 训练包：

```bash
cd <repo-root>
python3 docker/scripts/prepare_local_car_number_text_dataset.py \
  --manifest demo_data/generated_datasets/car_number_ocr_labeling/manifest.csv \
  --output-dir demo_data/generated_datasets/car_number_ocr_text_dataset
```

输出内容：
- `demo_data/generated_datasets/car_number_ocr_text_dataset/car_number_ocr_text_train_bundle.zip`
- `demo_data/generated_datasets/car_number_ocr_text_dataset/car_number_ocr_text_validation_bundle.zip`
- `demo_data/generated_datasets/car_number_ocr_text_dataset/car_number_ocr_text_dataset_summary.json`

临时试验时，如需先用建议值凑一版数据包，可附加：
- `--allow-suggestions`

## 1.5.4 生成巡检任务族标注工作区

```bash
cd <repo-root>
python3 docker/scripts/bootstrap_inspection_labeling_workspace.py --task-type inspection_mark_ocr --output-dir demo_data/generated_datasets
python3 docker/scripts/bootstrap_inspection_labeling_workspace.py --task-type performance_mark_ocr --output-dir demo_data/generated_datasets
python3 docker/scripts/bootstrap_inspection_labeling_workspace.py --task-type door_lock_state_detect --output-dir demo_data/generated_datasets
python3 docker/scripts/bootstrap_inspection_labeling_workspace.py --task-type connector_defect_detect --output-dir demo_data/generated_datasets
```

说明：
- OCR 类工作区用于 `inspection_mark_ocr / performance_mark_ocr`
- 状态 / 缺陷类工作区用于 `door_lock_state_detect / connector_defect_detect`
- 训练中心已经提供这组任务的首版训练预设
- 训练中心现在还会直接显示这 4 个工作区的准备度：
  - 工作区名称
  - 起步样本目标
  - 建议样本规模
  - 已裁剪候选区域
  - 已有文字建议
  - 当前已准备样本数
  - 待处理 / 需复核数量
  - 建议场景、拍摄距离、拍摄角度、图像要求
  - 首版验收目标
  - 结构化字段建议
  - 工作区目录与训练包生成命令
- 演示时可直接进入“训练中心 -> 巡检任务数据准备”查看当前准备度，不必在文档、终端和页面之间来回切换

如果要把现有真实侧拍图先变成 OCR 代理裁剪队列，可继续执行：

```bash
cd <repo-root>
python3 docker/scripts/prepare_inspection_ocr_proxy_crops.py --task-type inspection_mark_ocr
python3 docker/scripts/prepare_inspection_ocr_proxy_crops.py --task-type performance_mark_ocr
```

说明：
- 这会复用 `demo_data/train/_annotations.txt` 的真实框
- 把侧拍整图变成便于复核的 `crops/` 候选区域
- 当前真实结果是：`inspection_mark_ocr / performance_mark_ocr` 各有 `80` 条整图样本，其中 `77` 条已成功生成代理裁剪
- 代理裁剪策略现已进一步调成：
  - `performance_mark_ocr`：优先截取车号上方性能码带
  - `inspection_mark_ocr`：优先截取车号下方检修记录 / 小字信息带

如需尝试自动补文字建议，可继续执行：

```bash
cd <repo-root>
python3 docker/scripts/generate_inspection_ocr_suggestions.py --task-type inspection_mark_ocr
python3 docker/scripts/generate_inspection_ocr_suggestions.py --task-type performance_mark_ocr
```

当前真实状态要说清楚：
- 这条自动建议链路已经接入系统
- 训练中心也会显示“已有文字建议”
- 当前真实建议覆盖已经提升到：
  - `inspection_mark_ocr.suggestion_rows = 59`
  - `performance_mark_ocr.suggestion_rows = 57`
  - `inspection_mark_ocr.high_quality_suggestion_rows = 51`
  - `performance_mark_ocr.high_quality_suggestion_rows = 45`
  - inspection OCR 复核页现已补齐高质量建议专用入口：
    - `仅看高质量建议`
    - `优先确认高质量建议`
    - `导出高质量建议队列`
    - `导出高质量建议包`
    - `预检查批量确认`
    - `批量确认高质量建议`
- 这些建议现在可以作为人工起步参考
- 但正式训练仍应继续以人工确认的 `final_text` 为主，不能把自动建议直接当真值
- 当前 inspection / performance OCR 的训练就绪状态都会直接显示：
  - `可正常训练`
  - `仅冷启动可训练`
  - `仍不可导出`
- 当前真实状态仍是：
  - `inspection_mark_ocr = cold_start_only`
  - `performance_mark_ocr = cold_start_only`
  - 原因不是缺页面或缺脚手架，而是还存在 `proxy_seeded` 样本待替换
- 也就是说，这条线接下来最该做的不是继续补工具，而是继续把代理回灌样本替换成真实 `final_text`

## 1.5.5 把巡检任务复核清单打成训练包

```bash
cd <repo-root>
python3 docker/scripts/build_inspection_task_dataset.py \
  --task-type inspection_mark_ocr \
  --manifest demo_data/generated_datasets/inspection_mark_ocr_labeling/manifest.csv \
  --output-dir demo_data/generated_datasets/inspection_mark_ocr_dataset \
  --allow-suggestions
```

```bash
cd <repo-root>
python3 docker/scripts/build_inspection_task_dataset.py \
  --task-type door_lock_state_detect \
  --manifest demo_data/generated_datasets/door_lock_state_detect_labeling/manifest.csv \
  --output-dir demo_data/generated_datasets/door_lock_state_detect_dataset
```

说明：
- OCR 类优先补 `final_text`
- 状态 / 缺陷类优先补 `label_value`
- 这轮已落地的是工作区模板和打包脚手架，还不是这些模型已经训练完成

界面里对应两条入口：
- “先准备训练数据”：只会把 train / validation 资产预填到训练中心，仍需手动点击“创建训练作业”
- “现在开始训练”：会直接创建一条 `car_number_ocr` 训练作业
- 训练作业成功后，训练中心可直接点击“直接验证新模型”，只补单图/视频资产即可创建验证任务
- 资产中心、任务中心、训练中心的高频表单已经把 `asset_id / worker / model_id / task_id` 改成更自然的“资产编号 / 训练机器 / 模型编号 / 任务编号”，技术词默认不再压在第一眼位置
- 模型中心和流水线中心这轮又继续做了一次术语减负：创建训练、注册流水线、发布工作台里的参数标签已改成更自然的中文表达，默认看上去不再像接口参数表
- 指南页、训练机器管理和训练协作列表也继续做了术语减负：`readiness` 已替换成 `验证门禁`，训练协作里 `train / val / candidate` 也改成了更自然的中文说明
- 结果中心和模型表现区这轮继续把英文指标名改成了中文：`confidence / engine / bbox / val_accuracy / val_loss / best_checkpoint` 等默认不再直接露英文
- 训练中心和任务中心的高频卡片这轮也继续去掉了一批技术字段名：`job_code / worker / model_id / asset_id / task_id / object_count / dataset_asset_id` 等默认都换成了更自然的中文标签
- 训练中心顶部现在会先显示“训练工作台概览”，把当前焦点作业、Worker 状态和下一步动作收在一屏里
- 验证任务完成后，结果中心会显示“验证结论卡”和“下一步动作”，集中展示样本数、低置信度数、OCR 文本和建议动作
- 结果中心顶部元信息现在会直接显示“结果条数 / 关联模型 / 识别文本”，默认不再先露出 `task_id / model_id` 这类技术字段
- 如需把这批验证结果继续用于下一轮训练，结果中心的“把确认结果变成训练数据”区可直接导出训练/验证数据集版本，并自动把 `dataset_version / asset_id / target_model_code` 预填回训练中心
- 这轮前后端也继续统一了失败提示：登录失败、权限不足、资源不存在、流水线缺模型、数据集预览不可用等常见问题，页面会优先显示“原因 + 下一步”，不再直接弹裸英文接口错误
- OCR 真实泛化这轮也补了正式探针：评估脚本现在会优先对 `final_text` 真值，并支持关闭 curated/fixture 快捷命中；最新 8 样本探针已从 `2/8 正确` 提升到 `3/8 正确 + 1/8 可读但错位`，说明扩框重扫已开始有效，但陌生低清样本还没完全收口

## 1.6 创建任务

推荐路径：

1. 执行入口选择“Pipeline 编排（推荐）”。
2. 选择已发布的 Pipeline，填入 `asset_id`，设备保持 `edge-01`。
3. 录入 `scene_hint / camera_id / device_type`，例如：
   - `wagon-side / cam-yard-01 / edge-gpu-box`
   - `bogie-close-up / cam-bogie-02 / edge-gpu-box`
4. 任务类型可保持“自动识别”，点击“创建任务”。
5. 任务页右侧“创建助手”会实时告诉你当前是按流水线、按显式模型，还是按主调度器执行。
6. 创建成功后，直接点“等待执行并打开结果页”即可，不必再手工盯状态。

## 1.6.1 快速识别（预检 -> 正式识别）

1. 进入“任务中心”里的“快速识别”卡片。
2. 上传图片 / 视频，或直接填写已有 `asset_id`。
3. 任务页现在不是一屏堆满，而是按二级步骤进入：
   - `快速识别`：`识别输入 / 识别结果`
   - `创建任务`：`填写任务 / 创建反馈`
   完成上一步后会自动切到下一块。
4. 如果你已经明确知道要识别的是 `车号 / 车厢号 / 编号`，页面会直接展示可用 `car_number_ocr` 模型，不必先走预检。
5. 这时可直接点选模型，再点“带入下方精确任务”，把模型、任务类型、设备和意图一键同步到下方正式任务表单。
6. 如果目标表述可能有歧义，再点击“先扫一遍给建议”。
7. 页面会返回若干候选方向，例如：
   - `车号内容`
   - `目标框选`
   - `螺栓缺失`
8. 若是车号图片，系统会优先展示 `car_number_ocr` 候选，并直接给出候选车号文本。
9. 任务列表默认先显示“创建时间 / 执行方式 / 结果入口 / 当前设备”，长 `asset_id / model_id / pipeline_id` 收在“技术详情”里。
10. 选择一个候选方向后继续正式识别；结果页支持：
   - 修订框坐标
   - 删除误检
   - 手工补框
   - 修订 OCR 文本
11. 修订保存后，可直接导出为训练 / 验证数据集版本。

补充说明：
- 模型中心顶部会显示“模型工作台概览”，根据当前候选模型状态给出评估 / 审批 / 发布入口。
- 模型中心现在拆成三个工作区：
  - `模型总览`：只看模型列表、当前状态、风险和下一步动作
  - `提交与训练协作`：只放模型提交和训练协作
  - `审批与发布`：集中处理时间线、评估、审批工作台和发布工作台
- 训练中心现在拆成三个工作区：
  - `训练总览`：只看训练作业、运行告警和训练结果摘要
  - `创建训练`：集中处理算法选择、数据集版本、训练机选择和训练参数
  - `Worker 运维`：集中处理 Worker 健康、历史异常和节点注册
- 流水线中心顶部会显示“流水线工作台概览”，把当前配置状态和发布动作前置。
- 流水线中心现在拆成三个工作区：
  - `流水线总览`：只看流水线列表和当前状态
  - `注册配置`：集中处理新版本注册和路由配置
  - `发布管理`：集中处理发布范围、设备和买家配置
- 资产中心现在拆成三个工作区：
  - `资产总览`：先看资产列表和用途分布
  - `上传资产`：集中处理上传和结果回跳
  - `使用建议`：集中说明训练 / 验证 / 推理三类资产的推荐用法
- 审计中心现在拆成两个工作区：
  - `审计总览`：先看日志规模、动作类型和资源类型
  - `检索日志`：按动作 / 资源 / 操作者精确检索留痕
- 结果中心“把确认结果变成训练数据”这块，本轮又继续做了文案减负：
  - 默认显示任务中文名，不再直接裸露 `car_number_ocr / object_detect`
  - 报错和成功提示改成 `数据集标签 / 数据集资产编号`
- 前端公共错误提示这轮也继续收了一批：
  - 模型、流水线、ZIP 数据集、训练作业、训练机器相关的高频失败场景，现在会直接给出中文原因和下一步建议
  - 不再优先把后端英文原始报错直接抛给用户
  - 任务详情/删除、结果截图、边缘拉资产/回传结果、训练数据导出、训练作业改派/重试等主链失败场景，现在也都统一成了“原因 + 下一步”
- 模型发布工作台和流水线发布工作台里残留的混合表单标签，本轮也统一改成了自然中文：
  - `目标买家（租户编码）`
  - `交付方式 / 授权方式 / 本地密钥标签 / API 密钥标签`
- 页面级走查和本轮收口结论已沉淀到：
  - `docs/qa/browser_walkthrough_report_2026-03-12.md`
- 设备中心现在拆成两个工作区：
  - `设备总览`：先看设备总数、在线状态和最近心跳
  - `设备列表`：再展开 buyer、状态和 Agent 版本明细
- 训练作业、模型、流水线列表已改成卡片摘要式展示，默认先看状态、下一步动作和关键摘要，不必先读一整张技术表。

兼容旧路径：

1. 调度方式切换到“主模型调度（兼容）”或“手动指定模型（兼容）”。
2. 主模型调度模式下可先点“推荐模型”；手动模式下填写 `model_id`、`asset_id`、`task_type` 后创建任务。

## 1.7 启动边缘 Agent 并观察进度

```bash
docker compose -f docker/docker-compose.yml --profile edge up -d edge-agent
```

查看日志：

```bash
docker compose -f docker/docker-compose.yml logs -f edge-agent
```

预期过程：

- Edge `pull_tasks`
- Edge `pull_model`（拉取 router/expert 模型，验签+解密）
- Edge 本地执行 `预处理 -> router -> experts -> 融合`
- Edge `push_results`

## 1.8 查看任务结果

在前端“查询任务与结果”中：

1. 输入 `task_id`
2. 点击“查任务状态”应为 `SUCCEEDED`
3. 点击“查结果”查看：
   - 抽帧结果
   - 车号/缺失告警
   - bbox 标注图（截图）
   - `model_id/model_hash` 指纹
   - 页面以卡片/表格展示结构化业务结果（不展示原始 JSON）

## 1.9 查看审计记录

在“审计日志”区域查询，至少应看到：

- `LOGIN`
- `MODEL_SUBMIT`
- `MODEL_APPROVE`
- `MODEL_REGISTER`（平台直接提交模型时）
- `MODEL_RELEASE`
- `PIPELINE_REGISTER`
- `PIPELINE_RELEASE`
- `MODEL_DOWNLOAD`
- `TASK_CREATE`
- `ASSET_UPLOAD`
- `EDGE_PULL_TASKS`
- `EDGE_PULL_MODEL`
- `EDGE_PUSH_RESULTS`
- `ORCHESTRATOR_RUN`
- `REVIEW_QUEUE_ENQUEUE`
- `RESULT_EXPORT`（若调用导出）

## 1.10 关键策略验证点

- 原始视频默认不离开边缘：任务策略 `upload_raw_video=false`
- 模型权重全程加密态：中心端存储 `model.enc`，边缘端拉取后验签并临时解密
- 关键动作可追溯：下载模型/发布模型/导出结果均写审计日志

## 1.11 插件化推理（供应商算法接入）

边缘端推理已改为插件注册表机制。内置插件：

- `heuristic_router`
- `object_detect`
- `car_number_ocr`
- `bolt_missing_detect`

可通过环境变量加载外部插件（示例）：

```env
EDGE_PLUGIN_MODULES=inference.plugins_supplier_example
```

插件模块需导出：

- `register_plugins(register_fn)`，或
- `PLUGIN` 单例对象（包含 `task_type` 和 `run(ctx)`）

## 1.12 发布前质量门禁

```bash
cd <repo-root>
bash docker/scripts/quality_gate.sh
```

脚本会执行：

- 后端/边缘 compile 检查
- 推理插件 golden fixture 回归检查
- 运行中服务健康检查（可选）

## 1.13 发布 GO/NO-GO 检查

```bash
cd <repo-root>
bash docker/scripts/go_no_go.sh
```

该检查会额外执行：
- 角色权限矩阵 parity 校验（`/auth/login` 与 `/users/me`）
- 任务/结果接口契约校验
- `RESULT_EXPORT` 审计痕迹校验

并在 `docs/qa/reports/` 下生成门禁 JSON 报告。

## 1.14 当前界面语言口径

- 默认优先显示业务动作和结论，不再优先暴露 `task_id / asset_id / model_id / pipeline_id` 这类接口字段。
- 训练中心统一使用：
  - `训练机器`
  - `待验证模型`
  - `训练参数与输出摘要`
- 结果中心统一使用：
  - `任务编号`
  - `数据集资产编号`
  - `验证门禁摘要`
- 车号文本复核统一使用：
  - `待处理`
  - `最终文本`
  - `定位框`
  - `识别引擎`

## 1.15 当前默认视图展示原则

- 默认视图先展示：
  - 当前状态
  - 业务结论
  - 下一步动作
- 只有在需要排障或核对接口字段时，才进入：
  - `技术详情`
  - `原始结果数据`
  - `训练参数与输出摘要`
- 页面默认不再优先暴露：
  - `task_id`
  - `asset_id`
  - `model_id`
  - `pipeline_id`
  - `worker`
  - `plugin`
