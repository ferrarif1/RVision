# ADR-0003: Remote Training Control Plane

- Date: 2026-03-04
- Status: Proposed
- Owner: Platform CTO

## 1. Decision Statement

将来如果平台要真正承担受控训练 / 微调能力，应采用“中心控制面 + 远程训练 worker”架构：`server1` 负责作业编排、权限、审计和产物晋级，远程主机只作为受控计算资源执行训练。

## 2. Context

### Current State

- 当前平台已经支持：
  - 资产上传，并标记 `training / finetune / validation / inference`
  - 模型提交、审批、发布、交付
  - 边缘推理、结果回传、审计
- 当前平台尚未支持：
  - 训练作业创建 / 调度 / 重试
  - 远程训练主机注册与心跳
  - 训练产物自动回收与模型注册晋级
  - 训练期资源队列、容量控制、成本核算

### Decision Drivers

- 平台必须掌握客户数据、训练过程、成果模型和发布权
- 需要把训练资源与平台控制面分离，便于扩容
- 需要可审计、可回滚、可复现的训练链路
- 需要避免把边缘推理平面和训练平面混成一套系统

## 3. Options Considered

| Option | Summary | Pros | Cons | Why Not Chosen |
|---|---|---|---|---|
| A | 继续只做模型提交与治理，不做训练执行 | 简单 | 无法真正承接受控训练业务 | 仅适合当前 MVP |
| B | `server1` 控制面 + remote workers | 控制权集中，可扩展，可审计 | 需要新增调度和 worker 体系 | Chosen |
| C | 供应商自有训练后只回传模型 | 平台投入小 | 违背数据与成果控制权目标 | 不符合平台战略 |

## 4. Decision

目标态采用双平面架构：

- Control Plane on `server1`
  - Training Job API
  - Scheduler / Queue
  - Dataset / Artifact metadata
  - Audit / policy / approval
- Worker Plane on remote hosts
  - 训练 worker agent
  - 受控拉取训练数据与基线模型
  - 执行训练 / 微调 / 验证
  - 上传产物、日志和指标

关键约束：

- 远程主机不拥有发布权
- 成果模型必须回到平台模型仓库
- 训练数据访问要按租户、用途和生命周期控制
- 训练日志和产物摘要必须写入审计和运行记录

## 5. Consequences

### Positive

- 平台可以把训练资源扩展到多台主机而不失去控制权。
- 训练和推理职责清晰分离，更利于扩容与治理。
- 可以形成完整的“数据 -> 训练 -> 验证 -> 审批 -> 发布”闭环。

### Trade-offs

- 需要新增 scheduler、worker、artifact store、capacity management。
- 运维复杂度、容量治理和成本核算都会显著上升。

## 6. Security / Data / Audit Impact

- 训练数据需要受控拉取或受控挂载，禁止裸共享。
- 远程 worker 需要最小权限与短期凭证。
- 训练作业要记录：
  - dataset version
  - base model
  - hyperparameters summary
  - artifact hash
  - operator / approver

## 7. Operational Impact

必须补齐：

- worker registration / heartbeat
- job queue / retry / timeout
- resource scheduling
- artifact retention
- runbook / alerting / rollback

## 8. Migration and Rollback

建议按阶段推进：

1. Phase 0: 保持当前治理流，不承诺真实训练
2. Phase 1: 单机受控训练 worker
3. Phase 2: 多 worker 调度与资源配额
4. Phase 3: 训练产物自动进入验证 / 审批 / 发布链路

如果任一阶段稳定性不足，应回退到前一阶段，不影响现有推理与交付链路。

## 9. Evidence Required

- [ ] 训练作业 API 与 job state machine
- [ ] 至少一个 remote worker 成功注册并执行训练
- [ ] 训练产物可回收到模型仓库
- [ ] 数据、权限、审计边界通过验证
- [ ] ORR 与 rollback 文档齐备
