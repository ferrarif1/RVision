# CTO Track

## Mission

CTO 轨道负责把平台从“能跑 demo”提升到“能稳定扩展、可审计、可交付、可回滚”。这里的文档不是技术说明书，而是架构治理与发布决策依据。

## Current Truth

当前阶段的技术事实必须统一：

- 推理执行已经落地，位置在边缘 Agent 与推理运行时。
- Pipeline-first、Router/Expert 插件协议、结果与审计链路已经可运行。
- 训练 / 微调已经具备最小控制面骨架：训练作业、worker 注册、心跳、拉取作业、状态回传。
- 未来仍应演进为 `server1 control plane + remote training workers + real trainers`，当前仓库尚未实现真实训练执行与产物晋级。

## What CTO Documents Must Answer

每一份 CTO 轨道文档都至少要回答以下问题：

- 这项能力解决什么架构问题，为什么现在必须做。
- 当前实现状态、目标态和明确非目标分别是什么。
- 数据、权限、模型、密钥、审计边界如何控制。
- 运行失败时如何降级、回滚、止损。
- 发布后如何监控、验证和持续运营。

## Required Artifacts

| Artifact | Purpose | Trigger |
|---|---|---|
| ADR | 记录关键架构决策与替代方案 | 引入新子系统、存储、协议、运行时 |
| ORR | 发布前确认运维准备度 | 新服务上线、核心链路重构 |
| Threat / Trust Boundary Note | 识别密钥、数据、模型边界 | 新的数据流、外部依赖、第三方接入 |
| Migration & Rollback Plan | 保证变更可回退 | 改 schema、改 API、改运行路径 |
| Capacity / Reliability Note | 说明性能与稳定性假设 | 引入调度、并发、缓存、队列 |

## Architecture Review Bar

通过评审至少要满足：

- 有明确的 decision drivers：安全、合规、成本、时延、复杂度、可维护性。
- 有 current vs target 的分层表达，避免把 roadmap 写成现状。
- 有可执行 rollout plan，而不是“后续再补”。
- 有 rollback trigger、rollback owner 和 rollback steps。
- 有最小可验证证据：脚本、日志、回归、门禁或观测指标。

## Operating Model

推荐的技术治理节奏：

1. 问题定义：先写一页架构问题定义或 ADR 草案。
2. 方案评审：评估至少两个备选方案，记录 trade-off。
3. 落地前：补 ORR、迁移方案、观测与告警方案。
4. 上线后：保留 evidence，进入 QA gate 与 phase report。

## Directory Contract

- `adr-*.md`
  关键决策记录，禁止只写结论不写取舍。
- `README.md`
  当前轨道标准与工件索引。

当前重点文档：

- [adr-0002-edge-plugin-runtime.md](./adr-0002-edge-plugin-runtime.md)
- [adr-0003-remote-training-control-plane.md](./adr-0003-remote-training-control-plane.md)
- [../architecture.md](../architecture.md)
- [../templates/adr_template.md](../templates/adr_template.md)
- [../templates/orr_template.md](../templates/orr_template.md)

## CTO Review Checklist

- 这项设计是否强化了平台对数据、模型、发布与收费的控制权。
- 这项设计是否让系统更容易测试、审计、回滚。
- 这项设计是否把“当前实现”和“目标态”分开写清楚。
- 这项设计是否会无意中把平台变成手工运维系统。
