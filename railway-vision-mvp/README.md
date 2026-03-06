# railway-vision-mvp

三方（平台/供应商/买家）模型托管训练与交付平台 MVP。  
目标是把 **代码主权、数据主权、模型发布权、收费权** 固定在平台方手里，供应商仅提供算法能力。

当前产品按 4 条业务线组织：

- 客户用户上传图片或视频资产，资产可用于训练、微调、测试验收或推理。
- 供应商上传初始算法与可选预训练模型，在平台受控环境内结合客户数据反复微调，形成候选成果模型并提交审批。
- 平台管理员结合客户测试数据验证模型有效性，审批并发布模型。
- 授权客户设备通过模型 API 或授权密钥使用加密模型，本地运行时完成解密。

当前实现与目标态要明确区分：

- 当前已实装：边缘推理、Pipeline 编排、模型提交审批发布、结果回传、审计留痕。
- 当前已部分实装：训练控制面最小闭环，包含训练作业对象、worker 注册、心跳、拉取作业、受控拉取训练资产/基线模型、候选模型自动回收入库、状态回传。
- 当前已新增：`docker/scripts/training_worker_runner.py`，可在 worker 侧执行“拉作业→拉资产/基线模型→本地训练命令→打包候选→回传状态”的MVP执行闭环。
- 当前未实装：真正的训练执行引擎、自动验证晋级、完整分布式调度与容量治理。
- 目标态：平台部署在 `server1` 作为控制面，通过网络分配其他主机资源进行训练与微调。

## 1. 当前实现状态（MVP）

### 已实现

- 中心端一键部署：`FastAPI + PostgreSQL + Redis + Nginx(frontend)`（Docker Compose）
- 边缘端 Agent：拉任务、拉模型、验签、解密、推理、回传、断网补传
- 边缘推理插件化：内置插件注册表（车号OCR、螺栓缺失），支持外部插件模块按环境变量加载
- 身份与权限：JWT + RBAC（`platform_* / supplier_* / buyer_*`）
- 前后端权限一致：后端 `/auth/login`、`/users/me` 返回 `capabilities`，前端按能力动态显示模块
- 前端控制台已分页面重构：
  - 工作台 / 模型中心 / 流水线注册表 / 资产上传 / 任务创建 / 任务监控 / 结果中心 / 审计日志
  - 不同角色登录后仅显示对应功能页面
  - 所有结果以业务 UI 卡片、表格、截图、详情抽屉展示，不直接暴露原始 JSON
  - 前端资源拆分为 `frontend/index.html + frontend/assets/app.css + frontend/src/*`（模块化 SPA）
  - 模型中心已支持主路由模型 / 专家模型元数据、插件协议、审批时间线、版本对比、发布交付板
  - 流水线注册表已支持 Router + Experts + Thresholds + Fusion + Human Review 配置与发布
  - 任务创建页已支持 pipeline-first：默认调用 Pipeline，也兼容主模型调度与手动模型
  - 结果中心已支持任务级概览、告警聚合、焦点截图、结果卡片与摘要导出
  - 任务监控支持手动查询、任务队列分页筛选、10 秒自动刷新
  - 审计中心支持按 action / 操作人 / 资源类型 / 资源ID / 时间范围筛选，并显示摘要指标
- 多租户骨架：平台/供应商/买家租户隔离过滤（模型、资产、任务、结果）
- 模型供应链闭环：
  - 供应商提交 `model_package.zip`
  - 平台审批 `/models/approve`
  - 平台发布 `/models/release`（可指定设备、买家）
- 模型包安全：
  - 固定包结构：`manifest.json + model.enc + signature.sig + README.txt`
  - 中心端入库验签、哈希校验
  - 边缘端拉取后二次验签、哈希校验、解密加载
- 数据流与敏感级别：
  - 资产上传（图片/视频，支持训练/微调/测试/推理用途）
  - 任务创建与策略下发（支持主模型调度、小模型推荐，默认 `upload_raw_video=false`）
  - 结果落库 + 截图（L2）回传
- 训练与交付语义：
  - 资产上传支持用途、数据批次、业务场景、目标模型标记
  - 模型提交支持 router/expert 类型、统一输入输出协议、插件标识、运行时、显存与时延元数据
  - 流水线支持主路由、专家映射、阈值版本、融合规则、人工复核规则、灰度发布范围
  - 模型审批支持记录测试数据资产与验证结论
  - 模型发布支持记录交付方式（API / 本地解密 / 混合）与授权信息
- 训练当前状态说明：
  - 当前 MVP 已支持训练/微调相关资产用途与模型提审元数据
  - 当前 MVP 已实现训练作业、远程 worker 接入、训练资产/基线模型受控分发、候选模型自动回收
  - 当前 MVP 尚未实现真正的训练执行、自动验证晋级与容量调度
  - 相关目标架构见 `docs/cto/adr-0003-remote-training-control-plane.md`
- 推理演示能力：
  - `car_number_ocr`：车号识别占位（EasyOCR可选 + 规则回退）
  - `bolt_missing_detect`：OpenCV MobileNet-SSD/回退检测逻辑
- 审计留痕：登录、上传、建任务、主模型路由、小模型推荐、模型提交/审批/发布/下载、结果导出、边缘拉取回传
- 编排执行闭环：
  - Pipeline Registry：一条 Pipeline = Router + Experts + Thresholds + Fusion + Human Review
  - Orchestrator：按 router 输出动态拉起专家模型，可并行执行并输出融合结果
  - Result Store / Audit：保存 pipeline 版本、阈值版本、输入哈希、输出摘要、耗时和审计哈希

### 已跑通的最小闭环

- 供应商提交模型 -> 平台审批发布 -> 买家上传图片 -> 边缘推理 -> 结果回传 -> 前端查询 -> 审计可查

### 当前不应误判为已完成的能力

- 真实训练执行与失败重试
- 训练数据分发与下载鉴权
- 训练产物自动回收入库与晋级

## 2. 架构总览

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

详细文档：

- 架构与数据流：[docs/architecture.md](docs/architecture.md)
- 边缘终端接入说明：[docs/edge_terminal_access.md](docs/edge_terminal_access.md)
- 业务流转图：[docs/business_data_flow.md](docs/business_data_flow.md)
- 项目组织图：[docs/project_organization.md](docs/project_organization.md)
- 训练控制面：[docs/training_control_plane.md](docs/training_control_plane.md)
- 职责权力清单：[docs/company_responsibilities.md](docs/company_responsibilities.md)
- 模型包规范：[docs/model_package.md](docs/model_package.md)
- 前端设计语言：[docs/frontend_design_language.md](docs/frontend_design_language.md)
- 演示脚本：[docs/demo.md](docs/demo.md)
- 研发路线图（ctxport方法）：[docs/roadmap_ctxport_based.md](docs/roadmap_ctxport_based.md)
- 文档导航与模板：[docs/README.md](docs/README.md)

## 3. 快速开始

### 方式A：一键演示（推荐）

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
bash docker/scripts/bootstrap_demo.sh
```

该脚本会自动完成：密钥证书生成、服务启动、开源示例模型下载并打包、模型提审发、演示资产生成、任务创建、边缘执行。

### 方式B：手动启动

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
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
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
bash docker/scripts/start_one_click.sh
```

该脚本会自动处理：
- `docker/.env` 检查与初始化（缺失时从 `.env.example` 复制）
- `docker compose up -d --build`
- 后端健康检查等待（按顺序探测 `http://localhost:8000/health`、`https://localhost:8443/api/health`）
- 若超时，自动打印 backend/frontend 最近日志，便于快速定位问题

### 方式C：质量门禁检查（推荐发布前执行）

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
bash docker/scripts/quality_gate.sh
```

该脚本会执行：
- 后端/边缘代码编译检查
- 边缘推理 golden fixture 回归检查
- 运行时健康检查（若容器已启动）
- 训练控制面 smoke 检查，并归档 `docs/qa/reports/training_control_plane_latest.json`

### 方式C2：运行训练 Worker MVP 执行器

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
python docker/scripts/training_worker_runner.py \
  --backend-base-url http://localhost:8000 \
  --worker-token trainwk_xxx \
  --backend-root ./backend \
  --model-encrypt-key ./docker/keys/model_encrypt.key \
  --model-sign-private-key ./docker/keys/model_sign_private.pem \
  --once
```

该脚本用于把训练控制面 API 串成可执行链路；真实训练可通过 `--trainer-cmd` 接入。

### 方式D：发布 GO/NO-GO 门禁

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
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

## 4. 默认账号

- `platform_admin / platform123`
- `platform_operator / platform123`
- `platform_auditor / platform123`
- `supplier_demo / supplier123` 
- `buyer_operator / buyer123`
- `buyer_auditor / buyer123`

兼容旧账号：`admin/admin123`、`operator/operator123`、`auditor/auditor123`

## 5. 当前接口覆盖

中心端：

- `POST /auth/login`
- `GET /users/me`
- `GET /models`
- `POST /models/register`
- `POST /models/approve`
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

## 6. 安全与合规骨架（已落地）

- 模型加密存储与传输（`model.enc`）
- 模型签名校验（RSA-SHA256）
- 平台掌控签名私钥与发布权限（供应商无发布权限）
- 原始视频默认不离开边缘（策略默认值）
- 关键动作审计可追溯（含模型下载/发布/结果导出）
- 日志骨架：审计日志独立表，应用日志通过容器日志输出

## 7. 下一步计划（建议）

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

## 8. 无训练硬件还能不能做这门业务？

可以做，但业务模式要调整，结论是：

- **能做“模型交易 + 托管交付 + 推理运营”**（短期可跑）
- **要做“数据驱动的高频定制训练”则必须补算力能力**（中期刚需）

可行路径（按推荐顺序）：

1. **租赁算力但控制权在我方**：第三方机房/云专有主机，账号、密钥、审计归我方；供应商仅临时受控访问。  
2. **先做推理与发布平台**：优先跑“供应商初始模型 + 买家侧推理交付”，把训练需求先收敛为小规模微调。  
3. **建立混合训练策略**：共性模型由供应商预训练，个性化部分在我方受控环境做增量微调。  

硬约束不变：  
数据不外流、最终权重入我方仓库、签名与发布仅平台执行、全程审计可追溯。
