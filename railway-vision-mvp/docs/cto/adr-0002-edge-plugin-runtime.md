# ADR-0002: Edge Inference Plugin Runtime

- Date: 2026-02-27
- Status: Accepted
- Owner: Platform CTO

## 1. Decision Statement

边缘推理运行时改为插件注册模型，不再通过硬编码 `if/else` 分发任务类型，以便在保持平台控制权的前提下，让 Router 与 Expert 模型按统一协议接入 Orchestrator。

## 2. Context

### Current State

- 早期边缘推理逻辑通过 `if task_type == ...` 硬编码在单文件中。
- 新算法接入要改主流程代码，回归风险高，且不利于供应商算法隔离。
- 平台已经引入 Pipeline-first 的执行模型，需要统一 router / expert 的运行接口。

### Decision Drivers

- 降低新算法接入成本
- 保证主流程稳定，减少回归面
- 让 Orchestrator 能按统一协议拉起不同模型
- 保留平台对任务流、审计流、发布流的控制权

## 3. Options Considered

| Option | Summary | Pros | Cons | Why Not Chosen |
|---|---|---|---|---|
| A | 继续使用 `if/else` 分发 | 代码改动小 | 可扩展性差，回归面大 | 无法支撑多模型编排 |
| B | 边缘插件注册运行时 | 接入标准化，便于治理 | 需要定义协议与注册机制 | Chosen |
| C | 每个模型独立起一个服务 | 隔离强 | 复杂度与运维成本过高 | 对 MVP 不经济 |

## 4. Decision

- 引入插件注册运行时：
  - 插件协议：`run(ModelExecutionContext)`
  - 标准输入：`image / frames + context + options`
  - 标准输出：`predictions[] + artifacts[] + metrics`
  - router 额外输出：`scene_id / scene_score / tasks[] / task_scores[]`
- 内置插件：
  - `heuristic_router`
  - `object_detect`
  - `car_number_ocr`
  - `bolt_missing_detect`
- 外部插件通过 `EDGE_PLUGIN_MODULES` 指定模块加载。
- `run_inference()` 统一通过插件注册表分发，由 Orchestrator 先跑 router，再按 Pipeline 选择专家并融合。

## 5. Consequences

### Positive

- 新增算法无需改主流程，只需新增插件并注册。
- Router 与 Expert 使用统一协议，便于 Pipeline 即插即用。
- 平台仍保留任务编排、审计与发布的控制权。
- golden checks 可以快速发现关键算法回归。

### Trade-offs

- 插件注册失败会让初始化阶段更早暴露错误。
- 仍需要补充真实供应商插件压测与长稳验证。

## 6. Security / Data / Audit Impact

- 没有改变数据主权边界。
- 需要继续保证插件不能绕过统一审计与结果结构。
- 结果输出需继续附带模型版本和关键信息，便于追责与回放。

## 7. Operational Impact

- 需要 golden fixture 回归作为常规门禁。
- 需要外部插件加载失败时的清晰日志与启动失败信号。

## 8. Migration and Rollback

1. 将内置算法封装为插件并注册。
2. 增加外部插件入口与示例模块。
3. 增加 `quality_gate.sh` 执行 compile + golden checks。
4. 如插件运行时异常，可临时回退到上一版镜像和上一版内置插件集合。

## 9. Evidence Required

- [x] 内置任务通过插件运行
- [x] 支持外部插件模块加载
- [x] 质量门禁脚本可执行并通过
- [ ] 至少一个真实供应商插件通过压测与验收
