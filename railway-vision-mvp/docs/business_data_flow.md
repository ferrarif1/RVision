# 算法交易与托管训练平台 业务流程与数据流转图（成熟版）

> 目标：用统一视图说明“客户上传数据资产 + 供应商提供初始算法 + 平台受控微调审批 + Pipeline 编排交付运行”场景下的全流程数据流、控制流与审计流。

> 当前状态说明：本文中的训练链路已有最小控制面闭环落地。当前 MVP 已经支持训练作业对象、worker 注册、心跳、拉取作业、受控拉取训练资产/基线模型、候选模型回收入库和状态回传；但真正的训练执行、自动验证晋级与容量治理仍是后续阶段。

当前 MVP 在产品与接口层按 4 条业务线落地：

- 客户用户上传图片或视频资产，资产可用于训练、微调、测试验收或推理。
- 供应商上传初始算法与可选预训练模型，在平台受控环境内结合客户数据反复微调，形成候选成果模型并提交审批。
- 平台管理员结合客户测试数据验证模型有效性，审批并发布模型。
- 授权客户设备通过模型 API 或授权密钥使用加密模型，本地运行时完成解密。

## 1. 全局业务数据流（L0）

```mermaid
flowchart LR
    %% External actors
    A[买家/业务方数据源] -->|原始视频/图片/日志数据 L3| B[(甲方数据湖/资产库)]
    V[供应商算法团队] -->|初始算法/初始模型 + 训练代码/参数建议| T[甲方托管训练环境]
    U[使用方/客户] -->|采购授权| UI

    %% Core platform
    subgraph P1[甲方中心端平台（内网）]
        UI[Web前端]
        API[后端API<br/>Auth/RBAC/Task/Model/Pipeline/Audit]
        DB[(PostgreSQL)]
        R[(Redis)]
        MR[(Model Registry<br/>model.enc + manifest + signature)]
        PR[(Pipeline Registry)]
        ORC[Orchestrator]
        AL[(审计日志库)]
    end

    %% Edge
    subgraph P2[使用侧运行端（边缘设备/业务系统）]
        EA[Edge Agent]
        INF[推理引擎 OCR/检测]
        EC[(边缘缓存)]
        EV[(边缘原始视频存储 L3)]
    end

    %% Training and release
    B -->|脱敏/标注后训练集| T
    T -->|候选模型权重| API
    API -->|加密/签名/入库| MR
    API -->|注册/发布 Pipeline| PR
    API -->|模型发布策略| DB

    %% Inference runtime
    UI --> API
    API -->|下发 Pipeline 任务+策略| EA
    EA -->|拉取模型包| API
    API -->|model.enc + signature + manifest| EA
    EA -->|本地验签+解密| INF
    EV --> INF
    INF -->|推理结果 L1| EA
    INF -->|截图 L2 可脱敏| EA
    EA -->|断网缓存| EC
    EA -->|在线回传 L1/L2| API
    API --> DB

    %% High sensitivity rule
    EV -.默认不上传.-> API

    %% Audit
    UI -->|登录/上传/建任务/导出| API
    API -->|关键动作审计| AL
    EA -->|拉任务/拉模型/回传审计| API

    %% Optional export
    API -->|审批后导出| X[监管/运维报告]
    API -->|付费授权分发| U
    U -->|下载并使用授权模型/服务| P2
```

## 2. 训练与模型治理流（L1-Train）

> 注：本节描述的是“当前最小控制面 + 目标态执行面”的合并视图。当前仓库里已经支持训练/微调资产语义、模型提交审批发布、训练作业与 worker 闭环，以及候选模型回收入库；尚未支持真实训练执行。

```mermaid
flowchart TB
    S1[买家提供 L3 原始数据] --> S2[甲方数据治理\n清洗/脱敏/标注/质检]
    S2 --> S3[(训练数据集版本库\ndataset_id + version)]

    S4[供应商提交初始算法与可选预训练模型\n代码/容器/参数建议] --> S5[甲方内网受控训练执行/微调\n目标态]
    S3 --> S5

    S5 --> S6[训练产物评估\n精度/稳定性/鲁棒性]
    S6 -->|通过| S7[模型打包\nmanifest + model.enc + signature]
    S6 -->|不通过| S5

    S7 --> S8[甲方验签+哈希校验+入库]
    S8 --> S9[(模型仓库)]
    S8 --> S10[(发布记录\nmodel_releases)]

    S11[甲方管理员审批发布] --> S10
    S10 --> S12[按设备灰度发布]

    S13[(审计日志)]:::audit
    S4 --> S13
    S5 --> S13
    S8 --> S13
    S11 --> S13

    classDef audit fill:#fff3cd,stroke:#d39e00,color:#7a5d00;
```

## 3. 任务推理与结果回传流（L1-Infer）

> 注：这一节是当前已落地并可运行的真实链路。

```mermaid
sequenceDiagram
    participant OP as Operator(甲方)
    participant UI as Web前端
    participant API as 中心端API
    participant AG as Edge Agent
    participant IF as 边缘推理引擎
    participant DB as 业务库/审计库

    OP->>UI: 上传推理/验收资产并创建任务
    UI->>API: /assets/upload(asset_purpose/数据批次) + /tasks/create(pipeline_id)
    API->>API: 读取 Pipeline Registry + Orchestrator 配置
    API->>DB: 写 assets/tasks + 审计(ASSET_UPLOAD,TASK_CREATE)

    AG->>API: /edge/pull_tasks
    API->>DB: 任务状态更新 + 审计(EDGE_PULL_TASKS)
    API-->>AG: 任务+Pipeline+模型注册表+策略(upload_raw_video=false)

    AG->>API: /edge/pull_model
    API->>DB: 审计(MODEL_DOWNLOAD,EDGE_PULL_MODEL)
    API-->>AG: manifest + model.enc + signature

    AG->>AG: 验签+哈希校验+本地解密
    AG->>IF: 预处理 -> router -> experts -> 融合 -> 复核判定
    IF-->>AG: router/expert/final 结果L1 + 截图L2(按策略脱敏)

    AG->>API: /edge/push_results
    API->>DB: 写 results + inference_runs + review_queue + 审计(EDGE_PUSH_RESULTS,ORCHESTRATOR_RUN,REVIEW_QUEUE_ENQUEUE)

    Note over AG,API: 原始视频L3默认不回传中心端
    Note over AG: 断网时写本地缓存，恢复后补传
```

## 4. 持续运营回流流（L1-Feedback）

```mermaid
flowchart LR
    R1[(线上结果与告警)] --> R2[误报/漏报筛选]
    R2 --> R3[(难例池 hard_case_pool)]
    R3 --> R4[复标注与质检]
    R4 --> R5[(新训练集版本)]
    R5 --> R6[周期复训]
    R6 --> R7[新模型验收]
    R7 -->|通过| R8[灰度替换线上模型]
    R7 -->|不通过| R6

    R9[(审计与评估报告)]
    R1 --> R9
    R8 --> R9
```

## 5. 数据分级与控制点（用于评审）

| 数据级别 | 示例 | 默认流转策略 | 关键控制 |
|---|---|---|---|
| L1 低敏 | 推理JSON、bbox、统计指标 | 可回传中心端并落库 | API鉴权、结果审计、导出审计 |
| L2 中敏 | 抽帧截图/告警截图 | 按策略回传，可选脱敏 | 脱敏开关、访问控制、导出审批 |
| L3 高敏 | 原始视频 | 默认仅留边缘，不上传 | 审批开关、最小权限、强审计 |

## 6. 关键审计事件（必须覆盖）

- 用户侧：`LOGIN`、`ASSET_UPLOAD`、`MODEL_RECOMMEND`、`TASK_ROUTE`、`TASK_CREATE`、`RESULT_EXPORT`
- 模型侧：`MODEL_SUBMIT`、`MODEL_APPROVE`、`MODEL_REGISTER`、`MODEL_RELEASE`、`MODEL_DOWNLOAD`
- 流水线侧：`PIPELINE_REGISTER`、`PIPELINE_RELEASE`、`ORCHESTRATOR_RUN`、`REVIEW_QUEUE_ENQUEUE`
- 边缘侧：`EDGE_PULL_TASKS`、`EDGE_PULL_MODEL`、`EDGE_PUSH_RESULTS`

补充字段口径：

- 资产：`asset_purpose`、`dataset_label`、`use_case`、`intended_model_code`
- 模型提交：`model_source_type`、`model_type(router/expert)`、`runtime`、`plugin_name`、`inputs`、`outputs`
- 模型审批：`validation_asset_ids`、`validation_result`、`validation_summary`
- 模型发布：`delivery_mode`、`authorization_mode`、`api_access_key_preview`、`local_key_label`
- 流水线：`router_model_id`、`expert_map`、`thresholds`、`fusion_rules`、`threshold_version`
- 运行记录：`pipeline_version`、`models_versions`、`input_hash`、`result_summary`、`audit_hash`

## 7. 解释口径（对外统一）

- 压测：指边缘负载压力测试（并发/长稳/断网恢复），不是漏洞扫描。
- 难例池：线上误报漏报样本沉淀池，用于复训和回归。
- 主权边界：代码、数据、模型、密钥、发布权均在甲方；乙方提供算法能力但不掌控成果。
- 第 2 条业务线的默认前提：供应商可以参与调参与迭代，但客户数据与最终成果模型始终留在平台受控环境内。
- 当前实现提醒：平台已具备训练控制面最小闭环，但仍不应对外表述为“已具备完整分布式训练平台”。
- 商业边界：模型授权与收费由甲方统一执行；乙方仅提供技术支持，不直接向使用方分发或收费。
