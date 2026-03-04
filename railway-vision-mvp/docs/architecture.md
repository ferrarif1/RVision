# railway-vision-mvp 总体架构与数据流（第1步）

## 1. 目标与边界

- 部署场景：铁路内网，**无公网依赖**，所有服务可离线运行。
- 交付形态：中心端 + 边缘端 + 我方模型包规范。
- 安全原则：最小权限、可审计、数据分级、模型与数据主权在我方。
- 硬约束：
  - 原始视频（L3）默认不离开边缘端。
  - 模型权重只允许加密存储与传输。
  - 下载模型/发布模型/导出结果必须审计留痕。

## 1.1 当前实现与目标态

为了避免架构文档误导实现，先明确当前状态：

- 当前已实装：
  - 中心端模型注册、流水线注册、审批发布、审计
  - 边缘 Agent 拉任务、拉模型、验签、解密、推理、回传
  - Router / Expert 插件协议与 Orchestrator 编排
- 当前未实装：
  - 训练作业控制面
  - 远程训练 worker 编排
  - 分布式训练产物自动回收入库
- 因此本文中“训练环境 / 托管训练”相关内容应理解为目标态架构方向；当前 MVP 主要落地的是训练治理语义，而不是训练执行系统。

## 2. 总体组件架构

当前业务按四段推进，平台内部按 `Model Registry + Pipeline Registry + Orchestrator + Result Store/Audit` 组织：

1. 客户用户上传图片或视频资产，资产可用于训练、微调、测试验收或推理。
2. 供应商上传初始算法与可选预训练模型，在平台受控环境内结合客户数据反复微调，形成候选成果模型并提交审批。
3. 平台管理员结合客户测试数据验证模型有效性，审批并发布模型。
4. 授权客户设备通过模型 API 或授权密钥使用加密模型，本地运行时完成解密。

```text
                ┌────────────────────────────────────────────────┐
                │                中心端（内网）                  │
                │                                                │
                │  ┌──────────────┐    ┌──────────────────────┐ │
用户浏览器 ───HTTPS─► Frontend UI  ├────► FastAPI Backend      │ │
                │  └──────────────┘    │ - Auth/JWT/RBAC       │ │
                │                      │ - Task/API/Audit      │ │
                │                      │ - Pipeline Orchestrator│ │
                │                      │ - Model Registry      │ │
                │                      │ - Pipeline Registry   │ │
                │                      └─────────┬─────────────┘ │
                │                                │               │
                │   ┌──────────────┐   ┌────────▼────────────┐  │
                │   │ PostgreSQL   │   │ Redis               │  │
                │   │ 业务+审计库   │   │ 队列/缓存/状态       │  │
                │   └──────────────┘   └──────────────────────┘  │
                │                                │               │
                │                     ┌──────────▼───────────┐   │
                │                     │ Models Repo (加密)    │   │
                │                     │ Assets Metadata       │   │
                │                     └───────────────────────┘   │
                └────────────────────────────────────────────────┘
                                   ▲
                                   │ 内网HTTPS + 签名校验
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           边缘端（工控机/GPU）                         │
│ ┌────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐ │
│ │ Edge Agent         │  │ Inference Runtime    │  │ Edge Cache        │ │
│ │ - pull tasks       │  │ - OCR/YOLO 占位模型  │  │ - 断网补传         │ │
│ │ - pull model       │  │ - 视频抽帧 + 推理     │  │ - 本地结果队列     │ │
│ │ - push results     │  │ - 脱敏截图生成        │  │ - 本地资产索引     │ │
│ └────────────────────┘  └──────────────────────┘  └──────────────────┘ │
│   本地视频存储(L3默认仅本地)      临时解密目录(可加固)                  │
└─────────────────────────────────────────────────────────────────────────┘
```

## 3. 模型与插件协议

平台统一把主路由模型和专家模型都纳入 `Model Registry`，模型类型为：

- `expert`：检测、分割、OCR 等专家模型
- `router`：主路由模型，输出 `scene_id / scene_score / tasks[] / task_scores[]`

统一插件协议：

- 输入：
  - `image` 或 `frames`
  - `context`: `scene_hint / device_type / camera_id / job_id / timestamp`
  - `options`: `thresholds / max_experts / return_intermediate`
- 输出：
  - `predictions[]`: `label / score / bbox / mask / text / attributes`
  - `artifacts[]`: 可选中间产物，如 `preview_frame / roi_crop / heatmap / feature_summary`
  - `metrics`: `duration_ms / gpu_mem_mb / version / calibration`

这样新专家模型接入时，只要满足统一协议，Orchestrator 就能直接编排执行。

## 4. 模型包规范（我方统一格式）

```text
model_package.zip
  ├── manifest.json   # 模型ID/版本/hash/输入输出/schema/发布信息
  ├── model.enc       # 加密权重（ONNX/PT）
  ├── signature.sig   # 对 manifest + model.enc 的RSA签名
  └── README.txt
```

### 3.1 模型主权与供应商隔离

- 供应商仅提供：算法代码、训练脚本、参数建议或镜像。
- 训练执行的目标态是在我方受控环境内完成，数据不出域。
- 最终权重入我方模型仓库，由我方加密、签名、发布。
- 推理结果强制附带 `model_id + model_hash + release_id`（轻量指纹追责）。

## 5. Pipeline Registry 与编排执行

平台主入口不再是“直接调用某个模型”，而是“调用某条 Pipeline”。

一条 Pipeline 至少包含：

- `router`: 使用哪个主路由模型，是否配置场景白名单/黑名单、fallback 和 per-task threshold
- `experts`: 每个 task 对应哪些专家模型，支持多对多和优先级
- `pre/post`: 预处理和后处理，例如裁剪、去噪、曝光补偿、畸变矫正
- `fusion`: 投票、优先级、NMS、置信度校准
- `human_review`: 哪些条件进入人工复核队列

运行时流程：

1. 按 `camera_id / scene_hint` 做基础预处理。
2. 先跑 router，得到 `scene_id + tasks[]`。
3. 按映射表选择专家模型集合，支持 topK 和并行。
4. 可选先跑 ROI 专家，再跑缺陷专家。
5. 融合输出并做告警 / 复核判定。
6. 写入 `inference_runs` 与审计，记录输入哈希、模型版本、阈值版本、耗时和输出摘要。

## 6. 数据分级与流转策略

- **L1 低敏**：推理JSON、bbox、统计指标（默认可上传中心端）。
- **L2 中敏**：抽帧截图/告警截图（支持脱敏开关，按策略上传）。
- **L3 高敏**：原始视频（默认留在边缘端，不上传；需审批开关才可传）。

策略由中心端配置下发到任务：

- `upload_raw_video=false`（默认）
- `upload_frames=true/false`
- `desensitize_frames=true/false`
- `retention_days`（边缘和中心分别执行）

## 7. 关键数据流

### 5.1 模型提交、审批与发布流

1. 供应商在平台上传 `model_package.zip` 到中心端（状态=`SUBMITTED`），并附带来源类型、基线模型、微调轮次、训练数据批次等元数据；当前 MVP 记录这些治理信息，但不直接执行训练作业。
2. Backend 校验包结构、manifest、hash、RSA签名。
3. 通过后将 `model.enc` 存储到模型仓库（仅加密态），先写 `models`。
4. 平台管理员用客户测试数据验证模型有效性，审批模型（状态=`APPROVED`）。
5. 平台按设备/买家/交付方式发布模型（状态=`RELEASED`），支持 `api`、`local_key`、`hybrid` 三种交付模式，对应模型 API、授权密钥、本地解密运行等交付方式。
6. 发布时写 `model_releases`，并记录审计日志：`MODEL_SUBMIT`、`MODEL_APPROVE`、`MODEL_RELEASE`。
7. 边缘端按任务拉取模型，先验签后解密，加载推理。

### 7.2 任务推理与结果回传流

1. 买家 `buyer_operator` 上传图片/视频资产（训练/微调/测试验收/推理用途之一），也可以先请求一次模型推荐。
2. Backend 默认按 `pipeline_id` 下发编排策略；兼容路径下也可先做主模型调度 / 小模型推荐。
3. Backend 将 `pipeline_version + threshold_version + data policy + context/options` 一并固化到任务策略。
4. Edge Agent 拉任务，按 Orchestrator 执行 router 和专家模型。
5. 按策略回传 L1/L2，L3 默认不回传。
6. Backend 落库 `inference_tasks`/`inference_results`/`inference_runs`/`review_queue`/`data_assets`，写审计。

### 7.3 断网缓存与补传流

1. 边缘端无法连中心时，任务结果先写本地缓存队列。
2. 网络恢复后按时间顺序补传，幂等键防重复入库。
3. 补传过程完整审计：`EDGE_RESULT_RETRY_PUSH`。

## 8. 认证、权限、审计骨架

- 认证：本地账号 + JWT。
- RBAC：
  - 平台角色：`platform_admin`、`platform_operator`、`platform_auditor`
  - 供应商角色：`supplier_engineer`（仅提交模型与协作，不可发布）
  - 买家角色：`buyer_operator`、`buyer_auditor`
- 审计覆盖（MVP必做）：登录、上传、创建任务、下载模型、发布模型、发布流水线、编排执行、复核入队、删除、导出结果。
- 日志分离：应用日志与审计日志分表/分文件。
- 租户隔离：按 `tenant(PLATFORM/SUPPLIER/BUYER)` 对模型、资产、任务、结果进行范围过滤。

## 9. 合规落地点（实验版）

- 最小权限：API 逐路由绑定角色；边缘端token最小scope。
- 防篡改：模型包签名验签 + 哈希校验。
- 防泄露：模型全程加密态存储传输；边缘仅临时解密（后续可接HSM/国密机）。
- 可追溯：模型发布记录 + 结果携带模型指纹 + 审计日志闭环。

## 10. 实验版实现状态

- 已完成：目录结构、compose、后端接口骨架、边缘Agent、前端最小闭环、演示文档。
- 待增强（后续迭代）：
  - 对接 HSM/国密机替代本地密钥文件
  - 细化审批流（L3上传开关、导出审批）
  - 建设真正的训练控制面与远程 worker 调度能力
  - 接入供应商正式模型与训练流水线
