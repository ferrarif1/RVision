# 演示脚本（docs/demo.md）

## 0. 一键全自动（推荐，零数据零模型）

你现在没有任何视频/图片/模型时，直接运行：

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
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

本 demo 的文档口径也按同一 4 条业务线组织：

- 客户用户上传图片或视频资产，资产可用于训练、微调、测试验收或推理。
- 供应商上传初始算法与可选预训练模型，在平台受控环境内结合客户数据反复微调，形成候选成果模型并提交审批。
- 平台管理员结合客户测试数据验证模型有效性，审批并发布模型。
- 授权客户设备通过模型 API 或授权密钥使用加密模型，本地运行时完成解密。

需要注意：

- 这个 demo 真实覆盖的是“模型提审发布 + Pipeline 编排推理 + 结果回传”。
- 它不会在 demo 过程中真的执行一次训练或微调作业。
- `training / finetune` 在当前 demo 中体现为资产与模型治理语义，而不是训练引擎。

完成后直接打开：

- `https://localhost:8443`
- 账号：
  - 平台：`platform_admin/platform123`
  - 供应商：`supplier_demo/supplier123`
  - 买家：`buyer_operator/buyer123`

## 1. 手动流程（可选）

如果你只需要快速拉起中心端服务（不跑完整 demo），可直接使用：

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
bash docker/scripts/start_one_click.sh
```

该脚本会自动执行 compose 启动，并按顺序等待以下任一健康检查通过：
- `http://localhost:8000/health`
- `https://localhost:8443/api/health`

若超时，会自动输出 backend/frontend 最近日志用于排障。

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
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
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
cp docker/.env.example docker/.env
```

编辑 `docker/.env`，取消注释以下项（按你们内网可达镜像仓库替换）：

```env
POSTGRES_IMAGE=docker.m.daocloud.io/library/postgres:16-alpine
REDIS_IMAGE=docker.m.daocloud.io/library/redis:7-alpine
PYTHON_BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
EDGE_PYTHON_BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
NGINX_BASE_IMAGE=docker.m.daocloud.io/library/nginx:1.27-alpine
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
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
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

## 1.4 模型提交、审批、编排与发布（三方流程）

1. 先用 `supplier_demo` 登录，进入“模型中心”上传主路由包、初始算法包、预训练模型包或微调候选模型包。
2. 如需完整演示验证审批链，可先用买家账号上传一份测试验收资产，记录 `asset_id`。
3. 再用 `platform_admin` 登录，进入“模型中心”点击“审批模型”，可填写测试数据资产 ID 和验证结论。
4. 点击“发布模型”，设备填 `edge-01`，买家填 `buyer-demo-001`，按需要选择 `API`、`本地解密` 或 `混合` 交付方式。
5. 进入“流水线注册表”，用主路由和专家模型注册一条 Pipeline，再按 `edge-01 / buyer-demo-001` 发布。
6. 刷新模型列表和流水线列表，确认状态从 `SUBMITTED -> APPROVED -> RELEASED`，流水线状态为 `RELEASED`。

## 1.5 上传视频/图片

1. 在“上传资产”区域上传 `mp4` 或 `jpg/png`。
2. 选择数据用途，支持 `training`、`finetune`、`validation`、`inference`；本 demo 的任务演示通常选择 `inference`。
3. 选择敏感级别（推荐 `L2`）。
4. 上传成功后记录 `asset_id`。

## 1.6 创建任务

推荐路径：

1. 执行入口选择“Pipeline 编排（推荐）”。
2. 选择已发布的 Pipeline，填入 `asset_id`，设备保持 `edge-01`。
3. 录入 `scene_hint / camera_id / device_type`，例如：
   - `wagon-side / cam-yard-01 / edge-gpu-box`
   - `bogie-close-up / cam-bogie-02 / edge-gpu-box`
4. 任务类型可保持“自动识别”，点击“创建任务”。
5. 创建后在任务详情里确认已经写入 `pipeline_id / pipeline_version / run summary`。

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
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
bash docker/scripts/quality_gate.sh
```

脚本会执行：

- 后端/边缘 compile 检查
- 推理插件 golden fixture 回归检查
- 运行中服务健康检查（可选）

## 1.13 发布 GO/NO-GO 检查

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
bash docker/scripts/go_no_go.sh
```

该检查会额外执行：
- 角色权限矩阵 parity 校验（`/auth/login` 与 `/users/me`）
- 任务/结果接口契约校验
- `RESULT_EXPORT` 审计痕迹校验

并在 `docs/qa/reports/` 下生成门禁 JSON 报告。
