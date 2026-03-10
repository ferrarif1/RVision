# Vistral

Vistral 是一个面向铁路、政企内网和受监管环境的模型托管、受控训练协作、审批发布与边缘安全交付平台。

Vistral 把资产准备、供应商协作、模型治理、任务执行、结果回传和审计闭环统一放在一个控制面中，帮助平台方稳定掌握 **代码主权、数据主权、模型发布权、收费权**。

## 核心价值

- 平台控权：平台掌握模型审批、签名、发布、回滚和商业分发节奏。
- 数据主权：客户资产在平台控制面内完成上传、训练准备、验证与推理。
- 受控协作：供应商提交算法能力、参与微调和候选模型迭代，平台统一收口成果交付。
- 边缘安全交付：授权设备拉取加密模型，在本地完成验签、解密、推理、补传和审计闭环。

## 面向的角色

| 角色 | 核心收益 | 默认路径 |
|---|---|---|
| 平台方 | 掌握模型、密钥、发布、审计和授权控制面 | 模型审批 -> 发布授权 -> 审计追踪 |
| 供应商 | 在受控环境内提交算法能力、协作训练、交付候选模型 | 提交模型 -> 训练协作 -> 候选交付 |
| 买家 | 在数据不出域前提下上传资产、执行任务、查看结果 | 上传资产 -> 创建任务 -> 查看结果 |
| 授权设备 | 获得可验证、可补传、可长期运行的交付链路 | 拉取授权 -> 本地执行 -> 回传结果 |

## 四条业务主线

1. 客户用户上传图片、视频或 ZIP 数据集包，资产可用于训练、微调、测试验收或推理。
2. 供应商上传初始算法与可选预训练模型，在平台受控环境内结合客户数据反复微调，形成候选成果模型并提交审批。
3. 平台管理员结合客户测试数据验证模型有效性，审批并发布模型。
4. 授权客户设备通过模型 API 或授权密钥使用加密模型，本地运行时完成解密。

## 核心能力矩阵

- 中心端一键部署：`FastAPI + PostgreSQL + Redis + Nginx(frontend)`（Docker Compose）
- 身份与权限：JWT + RBAC（`platform_* / supplier_* / buyer_*`），前后端权限口径一致
- 资产中心：支持图片、视频、ZIP 数据集包上传，支持训练/微调/验证/推理用途标记
- 快速识别：上传单张或多张图片/短视频后可先做一轮预检扫描，自动给出候选目标标签 / 任务类型 / OCR 文本建议；确认方向后平台自动选模、创建任务并返回标注结果。结果支持删误检、手工补框、拖动缩放修订框、修订 OCR 文本、保存修订，并把结果导出成可预览、可版本对比的数据集版本
- 模型中心：支持模型包提交、自动验证门禁、发布前风险摘要、审批、发布、时间线查看和交付元数据管理
- 流水线中心：支持 `Router + Experts + Thresholds + Fusion + Human Review` 的 pipeline 编排与发布
- 训练控制面：支持训练作业、worker 注册/心跳、受控拉取训练资产和基线模型、候选模型自动回收，以及作业取消 / 重试 / 改派 / 超时回收；训练中心会把基础模型、数据规模、关键指标、epoch 曲线、best checkpoint、运行告警和后续动作集中展示
- 边缘执行链路：支持拉任务、拉模型、验签、解密、推理、回传、断网补传
- 审计闭环：登录、上传、建任务、训练拉取、模型提交/审批/发布/下载、结果导出、边缘回传均有留痕
- 运行时硬化：真实登录校验、流式上传、重复资产复用、空文件/非法类型拦截、Agent 版本上报
- 版本化数据库迁移：`schema_migrations + backend/app/db/migrations/versions/*.sql`

## 已验证的最小闭环

- 供应商提交模型 -> 平台审批发布 -> 买家上传资产 -> 边缘执行推理 -> 结果回传 -> 前端查询 -> 审计可查
- 训练作业创建 -> worker 拉取训练资产/基线模型 -> 生成候选模型 -> 平台自动回收入库 -> 前端集中展示关键指标、数据规模与候选模型入口
- ZIP 数据集包上传 -> 资源计数与层级分析 -> worker 解包 -> 多资源训练输入
- 快速识别 -> 预检扫描（候选标签 / 任务类型 / OCR 文本） -> 自动选模 -> 边缘检测 / OCR -> 标注图回传 -> 轻量修订（删误检/补框/拖拽缩放/修订文本） -> 数据集版本生成 -> 样本级差异对比、筛选、回滚与缩略图预览 -> 训练中心直接选用；“导出训练资产并打开训练页”只做预填，不会自动创建训练作业
- 候选模型回收 -> 自动验证门禁（验证资产 / 指标 / best checkpoint / runtime 契约） -> 审批工作台自动推荐验证样本、批量创建验证任务、汇总运行结果 -> 发布工作台预填设备/买家/交付方式并先做风险评估 -> 流水线发布工作台预填设备/买家并确认发布 -> 平台审批与授权发布

训练后验证现在也支持更短路径：

- 训练中心可直接从候选模型发起“直接验证候选模型”，只需补 1-3 张单图/视频资产，不必先手动切到任务中心再录入 `model_id`
- 结果中心会额外展示“验证结论卡”，汇总样本数、低置信度数、建议动作，方便判断是否继续审批/发布
- 结果中心还支持“结果回灌工作台”：基于当前 `task_id` 一键导出训练/验证数据集版本，并自动预填训练中心，不必再手抄 `asset_id / dataset_version_id`

## 当前项目状态

当前仓库已经具备“可真实运行的最小控制面和交付闭环”，并在以下方向稳定交付价值：

- 已稳定落地：边缘推理、Pipeline 编排、模型提交审批发布、结果回传、审计留痕
- 已具备最小执行闭环：训练作业对象、worker 接入、受控资产/基线模型分发、候选模型自动回收
- 已补齐工程防线：运行时硬化、质量门禁、GO/NO-GO 报告、版本化迁移

当前持续增强方向：

- 真实训练执行引擎与运行中中止协议
- 自动验证晋级与审批编排
- 完整分布式调度、容量治理与训练日志流

训练能力边界需要明确：

- 已完成：训练控制面 MVP、worker 执行闭环、候选模型回收、验证门禁、发布 readiness
- 未完成：生产级分布式训练平台、长日志流、容量治理和多机协同调度

## 系统概览

```text
供应商(初始算法/初始模型)
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│ 平台中心端（我方控制）                                 │
│ Frontend + FastAPI + Postgres + Redis + 模型仓库       │
│ 1) Model Registry 2) Pipeline Registry 3) Orchestrator 4) 审计 │
└─────────────────────────────────────────────────────────┘
        │                         ▲
        │ 发布(model.enc+sig)     │ 结果(L1/L2)
        ▼                         │
┌─────────────────────────────────────────────────────────┐
│ 买家运行侧（边缘设备）                                 │
│ Edge Agent: 拉任务、拉模型、验签、解密、推理、补传     │
│ 原始视频L3默认仅本地，不回传中心                         │
└─────────────────────────────────────────────────────────┘
```

## 文档入口

- 架构与数据流：[docs/architecture.md](docs/architecture.md)
- 边缘终端接入说明：[docs/edge_terminal_access.md](docs/edge_terminal_access.md)
- 业务流转图：[docs/business_data_flow.md](docs/business_data_flow.md)
- 项目组织图：[docs/project_organization.md](docs/project_organization.md)
- 训练控制面：[docs/training_control_plane.md](docs/training_control_plane.md)
- 职责权力清单：[docs/company_responsibilities.md](docs/company_responsibilities.md)
- 模型包规范：[docs/model_package.md](docs/model_package.md)
- 前端设计语言：[docs/frontend_design_language.md](docs/frontend_design_language.md)
- 产品定位与角色上手：[docs/product/vistral_positioning_and_role_onboarding.md](docs/product/vistral_positioning_and_role_onboarding.md)
- 演示脚本：[docs/demo.md](docs/demo.md)
- 研发路线图（ctxport方法）：[docs/roadmap_ctxport_based.md](docs/roadmap_ctxport_based.md)
- 文档导航与模板：[docs/README.md](docs/README.md)

## 快速开始

### 方式A：一键演示（推荐）

```bash
cd <repo-root>
bash docker/scripts/bootstrap_demo.sh
```

该脚本会自动完成：密钥证书生成、服务启动、开源示例模型下载并打包、模型提审发、演示资产生成、任务创建、边缘执行；如果检测到 `demo_data/train` 下存在本地车号数据集，还会自动切分 `train/validation`、上传训练资产并跑一条 `car_number_ocr` 微调作业。

### 方式B：手动启动

```bash
cd <repo-root>
./docker/scripts/generate_local_materials.sh
docker compose -f docker/docker-compose.yml up -d --build
```

若内网无法直连 Docker Hub/PyPI，使用镜像代理：

```bash
cp docker/.env.example docker/.env
docker compose --env-file docker/.env -f docker/docker-compose.yml up -d --build
```

### 方式B2：一键启动脚本（开发/联调推荐）

```bash
cd <repo-root>
bash docker/scripts/start_one_click.sh
```

该脚本会自动处理：
- `docker/.env` 检查与初始化（缺失时从 `.env.example` 复制）
- `docker compose up -d --build`
- 后端健康检查等待（按顺序探测 `http://localhost:8000/health`、`https://localhost:8443/api/health`）
- 后端启动时自动执行版本化数据库迁移
- 若超时，自动打印 backend/frontend 最近日志，便于快速定位问题

### 方式C：质量门禁检查（推荐发布前执行）

```bash
cd <repo-root>
bash docker/scripts/quality_gate.sh
```

该脚本会执行：
- 后端/边缘代码编译检查
- 数据库 schema 快照守卫（`backend/app/db/schema.sql` 必须与最新 snapshot migration 一致）
- 边缘推理 golden fixture 回归检查
- 运行时健康检查（若容器已启动）
- 运行时硬化 smoke（认证拒绝、空文件拒绝、非法类型拒绝、重复上传复用）
- 后端 API 自动化回归（`auth / assets / tasks / results / edge / training`）
- 快速识别 smoke（上传样例图、提示 `bus`、自动选模、边缘检测、标注结果校验、结果打包为数据集资产）
- 训练/验证数据集包支持：ZIP 嵌套目录、多资源计数、0-n 训练资产列表
- 训练控制面 smoke 检查，并归档 `docs/qa/reports/training_control_plane_latest.json`

如需单独运行后端 API 自动化回归：

```bash
cd <repo-root>
bash docker/scripts/api_regression.sh
```

### 方式C2：运行训练 Worker MVP 执行器

```bash
cd <repo-root>
python3 deploy/training-worker/bootstrap_local_worker.py bootstrap --start --restart
```

worker 独立部署物料已统一放到 `deploy/training-worker/`：

- `bootstrap_local_worker.py`：本机一键注册 / 写入 `worker.env` / 启动 worker
- `run_worker.sh`：worker 启动入口
- `worker.env.example`：环境变量模板
- `requirements.txt`：最小依赖
- `build_bundle.py`：生成独立可下发 bundle

如果只想手工启动已有配置：

```bash
cd <repo-root>
bash deploy/training-worker/run_worker.sh --once
```

如果需要把 worker 下发到远端训练机：

```bash
cd <repo-root>
python3 deploy/training-worker/build_bundle.py
```

输出目录：

- `deploy/training-worker/dist/vistral-training-worker/`

该目录可直接复制到远端机器；真实训练仍可通过 `--trainer-cmd` 接入。

外部训练命令契约已固化为 `Vistral external trainer v1`：

- 命令占位变量：`{job_dir} {train_manifest} {val_manifest} {base_model_path} {output_model_path} {job_json} {metrics_json}`
- 退出码分类：
  - `10`：配置错误，不可重试
  - `11`：输入契约错误，不可重试
  - `12`：数据错误，不可重试
  - `20`：训练运行时错误，可重试
  - `21`：依赖不可用，可重试
  - `22`：中断退出，可重试
- `metrics_json` 现在要求稳定 JSON object schema，支持：
  - 顶层指标：`epochs / learning_rate / train_loss / val_loss / train_accuracy / val_accuracy / final_loss / val_score`
  - 历史曲线：`history: [{epoch, train_loss, val_loss, train_accuracy, val_accuracy, learning_rate, duration_sec}]`
  - 最优 checkpoint：`best_checkpoint: {epoch, metric, value, path}`

训练中心现在会直接消费这些字段：

- 在作业执行中展示 epoch 级 loss / accuracy 曲线
- 在完成后展示 best checkpoint、收敛趋势和当前最优轮次
- 不再只停留在终态摘要卡

### 方式C3：使用本地车号素材生成训练包

如果你已经把货车车号图片和标注放在 `demo_data/train/` 下，可直接生成训练/验证 ZIP：

```bash
cd <repo-root>
python3 docker/scripts/prepare_local_car_number_dataset.py \
  --source-dir demo_data/train \
  --output-dir demo_data/generated_datasets
```

输出内容：
- `demo_data/generated_datasets/car_number_ocr_train_bundle.zip`
- `demo_data/generated_datasets/car_number_ocr_validation_bundle.zip`
- `demo_data/generated_datasets/car_number_ocr_dataset_summary.json`

当前脚本兼容两类原始标注行：
- `image.jpg x1,y1,x2,y2,0`
- `image.jpg`（无框样本，打包时会跳过其空标注）

### 方式C4：生成 OCR 文本待标注清单

如果 `demo_data/train/` 里目前只有 bbox、还没有车号文本真值，可先把它转成待标注队列：

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

说明：
- 每条 bbox 会被裁成单独 crop，便于人工补 `final_text`
- `split_hint` 会沿用当前稳定的 train / validation 切分规则
- 如果当前 Python 环境具备边缘 OCR 依赖，脚本会尝试预填 `ocr_suggestion`

### 方式C5：把已标注文本回灌成 OCR 训练包

当 `manifest.csv` 中已经补好 `final_text` 后，可直接打成 crop 级 OCR 训练/验证 ZIP：

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

可选：
- `--allow-suggestions`：在 `final_text` 为空时，临时使用 `ocr_suggestion` 先生成试验包

### 方式D：发布 GO/NO-GO 门禁

```bash
cd <repo-root>
bash docker/scripts/go_no_go.sh
```

该脚本会串行执行：
- `quality_gate.sh`
- `parity_regression.py`（权限矩阵、任务/结果接口契约、审计痕迹）

并自动归档门禁报告到：
- `docs/qa/reports/go_no_go_YYYYMMDD_HHMMSS.json`
- `docs/qa/reports/latest_go_no_go.json`

可选 CI（手动触发）：
- `.github/workflows/release-gate.yml`

### 方式E：运行时清理（安全 housekeeping）

```bash
cd <repo-root>
python3 docker/scripts/cleanup_runtime_housekeeping.py
python3 docker/scripts/cleanup_runtime_housekeeping.py --apply
```

该脚本默认 `dry-run`，仅清理两类低风险产物：
- `docs/qa/reports/*.json` 中超过保留期的历史报告（保留最新别名）
- `backend/app/uploads/.upload-*` 异常中断残留的临时上传文件

不会删除正式资产、模型仓库或数据库记录对应文件。

### 方式F：数据库迁移状态 / 手动补跑

```bash
cd <repo-root>
python3 docker/scripts/db_migrate.py
python3 docker/scripts/db_migrate.py --apply
```

说明：
- 服务启动时会自动执行待迁移版本
- `db_migrate.py` 优先在 `vistral_backend` 容器内执行，用于手动查看 `schema_migrations` 状态或在离线维护时补跑迁移
- 当前迁移文件目录为 `backend/app/db/migrations/versions/`
- 当前采用 snapshot-at-tip 策略：最新迁移文件必须是 `*_schema.sql` 或 `*_snapshot.sql`，用于表达当前完整 schema
- `python3 docker/scripts/db_migrate.py --apply` 成功后会自动同步 `backend/app/db/schema.sql`
- 如需只补跑迁移而不改写本地 schema 快照，可额外传 `--no-sync-schema`

## 默认账号

- `platform_admin / platform123`
- `platform_operator / platform123`
- `platform_auditor / platform123`
- `supplier_demo / supplier123` 
- `buyer_operator / buyer123`
- `buyer_auditor / buyer123`

兼容旧账号：`admin/admin123`、`operator/operator123`、`auditor/auditor123`

## 当前接口覆盖

中心端：

- `POST /auth/login`
- `GET /users/me`
- `GET /models`
- `POST /models/register`
- `GET /models/{id}/readiness`
- `POST /models/approve`
- `POST /models/release-readiness`
- `POST /models/release`
- `GET /pipelines`
- `GET /pipelines/{id}`
- `POST /pipelines/register`
- `POST /pipelines/release`
- `POST /assets/upload`
- `POST /tasks/recommend-model`
- `POST /tasks/create`
- `GET /tasks/{id}`
- `GET /results?task_id=`
- `GET /results/{result_id}/screenshot`
- `GET /results/export?task_id=`
- `POST /results/export-dataset`
- `GET /audit`
- `POST /training/jobs`
- `GET /training/jobs`
- `GET /training/jobs/{job_id}`
- `POST /training/workers/register`
- `GET /training/workers`
- `POST /training/workers/heartbeat`
- `POST /training/workers/pull-jobs`
- `GET /training/workers/pull-asset`
- `POST /training/workers/pull-base-model`
- `POST /training/workers/upload-candidate`
- `POST /training/workers/push-update`

边缘端：

- `GET /edge/ping`
- `POST /edge/pull_tasks`
- `POST /edge/pull_model`
- `GET /edge/pull_asset`
- `POST /edge/push_results`

## 安全与合规骨架（已落地）

- 模型加密存储与传输（`model.enc`）
- 模型签名校验（RSA-SHA256）
- 平台掌控签名私钥与发布权限（供应商无发布权限）
- 原始视频默认不离开边缘（策略默认值）
- 关键动作审计可追溯（含模型下载/发布/结果导出）
- 日志骨架：审计日志独立表，应用日志通过容器日志输出

## 后续演进方向

### P1（可用性）

- 接入真实 OCR/缺陷检测生产模型（替换占位推理）
- 将供应商算法按插件接入（`EDGE_PLUGIN_MODULES`），并纳入门禁回归
- 前端增加设备视图、任务看板、结果图像可视化优化
- 完成 RTSP 实时流任务管理与稳定性增强

### P2（安全合规）

- 密钥托管从本地文件升级到 HSM/KMS/国密设备
- 审批流增强：L3 上传开关、导出审批、双人复核
- 全链路审计告警与报表（审计异常自动告警）

### P3（商业化）

- 计费引擎：按调用量/时长/设备数计费
- 授权策略：按买家、设备、期限、能力包授权
- 对账与分账（平台抽佣、供应商结算、买家账单）

## 算力建设建议

Vistral 支持先以“模型交付 + 推理运营 + 受控微调”模式启动，再逐步补足训练算力。推荐按以下顺序推进：

- **先建立受控交付能力**：以模型审批、发布、授权、边缘推理和审计闭环形成可运营基础
- **再补充受控训练能力**：把个性化训练、验证和候选模型回收纳入平台控制面
- **最终建设稳定训练基础设施**：形成可审计、可扩容、可回滚的训练算力池

推荐路径：

1. **租赁算力但控制权在我方**：第三方机房/云专有主机，账号、密钥、审计归我方；供应商仅临时受控访问。  
2. **先做推理与发布平台**：优先跑“供应商初始模型 + 买家侧推理交付”，把训练需求先收敛为小规模微调。  
3. **建立混合训练策略**：共性模型由供应商预训练，个性化部分在我方受控环境做增量微调。  

长期约束：  
数据不外流、最终权重入我方仓库、签名与发布仅平台执行、全程审计可追溯。
