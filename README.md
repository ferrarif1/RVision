
# RVision · railway-vision-mvp

三方（**平台 / 供应商 / 买家**）参与的 **模型托管、训练与交付平台 MVP**。  

> 目标：把 **代码主权、数据主权、模型发布权、收费权** 固定在平台方手里；供应商仅提供算法能力，不掌握发布与交付控制权。

---

## 你能用它做什么

- **买家**：上传图片/视频资产，用于训练/微调/测试/推理；在边缘设备运行推理并回传结果。
- **供应商**：提交初始算法/可选预训练模型，在平台受控环境内微调，产出候选模型并提交审批。
- **平台**：基于客户测试数据验证模型有效性，审批并发布模型；向授权设备交付**加密模型**与授权策略。

---

## 核心原则

- **数据不外流**：原始视频（L3）默认仅保留边缘侧，不回传中心（策略默认 `upload_raw_video=false`）
- **模型权重归平台仓库**：最终权重与版本由平台托管入库
- **签名与发布仅平台执行**：供应商无发布权限，平台掌控签名私钥与发布流程
- **可审计可追溯**：关键动作全链路审计留痕（含下载/发布/导出）

---

## 架构总览

```text
供应商（初始算法/初始模型）
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│ 平台中心端（我方控制）                                  │
│ Frontend + FastAPI + Postgres + Redis + Model Registry  │
│ 1) Model Registry  2) Pipeline Registry  3) Orchestrator │
│ 4) Audit / Result Store / Auth (RBAC)                   │
└─────────────────────────────────────────────────────────┘
        │                         ▲
        │ 发布(model.enc + sig)   │ 结果(L1/L2)
        ▼                         │
┌─────────────────────────────────────────────────────────┐
│ 买家运行侧（边缘设备）                                  │
│ Edge Agent: 拉任务/拉模型/验签/解密/推理/补传            │
│ 原始视频L3默认仅本地，不回传中心                          │
└─────────────────────────────────────────────────────────┘
````

> 目标态：平台部署在 `server1` 作为控制面，通过网络分配其他主机资源进行训练与微调。

---

## 当前 MVP 状态

### ✅ 已实现（可演示、可闭环）

* 中心端一键部署：`FastAPI + PostgreSQL + Redis + Nginx(frontend)`（Docker Compose）
* 边缘端 Agent：拉任务、拉模型、验签、解密、推理、回传、断网补传
* 推理插件化：内置插件注册表（车号 OCR、螺栓缺失），支持外部插件模块按环境变量加载
* 身份与权限：JWT + RBAC（`platform_* / supplier_* / buyer_*`）
* 前后端权限一致：`/auth/login`、`/users/me` 返回 `capabilities`，前端按能力动态显示模块
* 前端控制台（按角色显示页面）：

  * 工作台 / 模型中心 / 流水线注册表 / 资产上传 / 任务创建 / 任务监控 / 结果中心 / 审计日志
  * 结果以业务 UI 卡片/表格/截图/详情抽屉展示，不直接暴露原始 JSON
* 多租户骨架：平台/供应商/买家隔离过滤（模型、资产、任务、结果）
* 模型供应链闭环：

  * 供应商提交 `model_package.zip`
  * 平台审批 `/models/approve`
  * 平台发布 `/models/release`（可指定设备、买家）
* 模型包安全：

  * 固定包结构：`manifest.json + model.enc + signature.sig + README.txt`
  * 中心端入库验签 + 哈希校验；边缘端二次验签 + 哈希校验 + 解密加载
* Pipeline 编排闭环：

  * Pipeline Registry：Router + Experts + Thresholds + Fusion + Human Review
  * Orchestrator：按 router 输出动态拉起专家模型，可并行执行并融合输出
  * Result Store / Audit：保存版本、阈值、输入哈希、摘要、耗时与审计哈希
* 推理演示插件：

  * `car_number_ocr`：车号识别占位（EasyOCR 可选 + 规则回退）
  * `bolt_missing_detect`：OpenCV MobileNet-SSD / 回退检测逻辑
* 审计留痕：登录、上传、建任务、主模型路由、小模型推荐、模型提交/审批/发布/下载、结果导出、边缘拉取回传

### 🟡 已部分实装（训练控制面最小闭环）

> 仅“控制面闭环”，尚未包含真正训练引擎与容量调度。

* 训练作业对象（Job）
* worker 注册、心跳
* worker 拉取作业
* 训练资产/基线模型受控拉取
* 候选模型自动回收入库
* 状态回传

相关目标架构：`docs/cto/adr-0003-remote-training-control-plane.md`

### ❌ 当前未实装（不要误判为已完成）

* 真正的训练执行引擎（训练/失败重试）
* 自动验证与晋级（auto evaluation / promotion）
* 完整分布式调度与容量治理（scheduler / quota / fair-share）

---

## 已跑通的最小闭环（MVP Demo）

```text
供应商提交模型
→ 平台审批发布
→ 买家上传图片
→ 边缘推理执行
→ 结果回传中心
→ 前端查询展示
→ 审计可追溯
```

---


## 文档导航（railway-vision-mvp/docs）

* 架构与数据流：`docs/architecture.md`
* 业务流转图：`docs/business_data_flow.md`
* 项目组织图：`docs/project_organization.md`
* 训练控制面：`docs/training_control_plane.md`
* 职责权力清单：`docs/company_responsibilities.md`
* 模型包规范：`docs/model_package.md`
* 前端设计语言：`docs/frontend_design_language.md`
* 演示脚本：`docs/demo.md`
* 研发路线图（ctxport）：`docs/roadmap_ctxport_based.md`
* 文档导航与模板：`docs/README.md`

---

## 快速开始

> 推荐在 `railway-vision-mvp/` 下执行。

### A. 一键演示（推荐）

```bash
cd railway-vision-mvp
bash docker/scripts/bootstrap_demo.sh
```

该脚本会自动完成：密钥证书生成、服务启动、开源示例模型下载并打包、模型提审发布、演示资产生成、任务创建、边缘执行。

### B. 手动启动

```bash
cd railway-vision-mvp
./docker/scripts/generate_local_materials.sh
docker compose -f docker/docker-compose.yml up -d --build
```

内网无法直连 Docker Hub/PyPI 时：

```bash
cp docker/.env.example docker/.env
docker compose --env-file docker/.env -f docker/docker-compose.yml up -d --build
```

### C. 质量门禁（推荐发布前）

```bash
cd railway-vision-mvp
bash docker/scripts/quality_gate.sh
```

### D. 发布 GO/NO-GO 门禁

```bash
cd railway-vision-mvp
bash docker/scripts/go_no_go.sh
```

门禁报告输出到：

* `docs/qa/reports/go_no_go_YYYYMMDD_HHMMSS.json`
* `docs/qa/reports/latest_go_no_go.json`

---

## 默认账号

| Role              | Username            | Password      |
| ----------------- | ------------------- | ------------- |
| Platform Admin    | `platform_admin`    | `platform123` |
| Platform Operator | `platform_operator` | `platform123` |
| Platform Auditor  | `platform_auditor`  | `platform123` |
| Supplier Demo     | `supplier_demo`     | `supplier123` |
| Buyer Operator    | `buyer_operator`    | `buyer123`    |
| Buyer Auditor     | `buyer_auditor`     | `buyer123`    |

兼容旧账号：`admin/admin123`、`operator/operator123`、`auditor/auditor123`

---

## API 覆盖（摘要）

### Center (Platform)

* Auth：`POST /auth/login`、`GET /users/me`
* Models：`GET /models`、`POST /models/register`、`POST /models/approve`、`POST /models/release`
* Pipelines：`GET /pipelines`、`POST /pipelines/register`、`POST /pipelines/release`
* Assets：`POST /assets/upload`
* Tasks：`POST /tasks/recommend-model`、`POST /tasks/create`、`GET /tasks/{id}`
* Results：`GET /results`、`GET /results/{id}/screenshot`、`GET /results/export`
* Audit：`GET /audit`
* Training control plane：`/training/*`（jobs/workers）

### Edge

* `GET /edge/ping`
* `POST /edge/pull_tasks`
* `POST /edge/pull_model`
* `GET /edge/pull_asset`
* `POST /edge/push_results`

---

## 安全与合规（已落地）

* 模型加密存储与传输（`model.enc`）
* RSA-SHA256 签名校验（中心端入库验签 + 边缘端二次验签）
* 平台掌控签名私钥与发布权限（供应商无发布权限）
* 原始视频默认不离开边缘（策略默认值）
* 关键动作审计可追溯（含模型下载/发布/结果导出）
* 审计日志独立表；应用日志通过容器日志输出

---

## Roadmap

### P1（可用性）

* 接入真实 OCR/缺陷检测生产模型（替换占位推理）
* 供应商算法按插件接入（`EDGE_PLUGIN_MODULES`），并纳入门禁回归
* 前端增加设备视图、任务看板、结果图像可视化优化
* 完成 RTSP 实时流任务管理与稳定性增强

### P2（安全合规）

* 密钥托管：本地文件 → HSM/KMS/国密设备
* 审批增强：L3 上传开关、导出审批、双人复核
* 全链路审计告警与报表（审计异常自动告警）

### P3（商业化）

* 计费引擎：按调用量/时长/设备数计费
* 授权策略：按买家、设备、期限、能力包授权
* 对账与分账：平台抽佣、供应商结算、买家账单

---


