# ADR-0002: Edge Inference Plugin Runtime

- Date: 2026-02-27
- Status: Accepted
- Owner: Platform CTO

## Context
- 当前边缘推理逻辑通过 `if task_type == ...` 硬编码在单文件中。
- 新算法接入会修改主流程代码，存在回归风险，且与“供应商仅提供算法插件”的治理目标不一致。
- 需要在保持 MVP 可演示性的前提下，建立低成本扩展机制。

## Decision
- 在 `edge/inference` 引入插件注册运行时：
  - 插件协议：`plugin_names + run(ModelExecutionContext)`。
  - 标准输入：`image/frames + context + options`。
  - 标准输出：`predictions[] + artifacts[] + metrics`；router 额外输出 `scene_id / scene_score / tasks[] / task_scores[]`。
  - 内置插件：`heuristic_router`、`car_number_ocr`、`bolt_missing_detect`。
  - 外部插件加载：通过 `EDGE_PLUGIN_MODULES` 指定模块，支持：
    - `register_plugins(register_fn)`；
    - 或单一 `PLUGIN` 对象。
- `run_inference()` 统一通过插件注册表分发，由 Orchestrator 先跑 router，再按 Pipeline 选择专家模型并融合结果。
- 增加 golden fixture 检查脚本，作为发布前质量门禁的一部分。

## Consequences
### Positive
- 新增算法无需改主流程，只需新增插件模块并注册。
- router 与 expert 共享统一协议，便于在 Pipeline 中即插即用。
- 供应商可提供受控插件，平台保留任务流/审计流/发布流控制权。
- golden checks 可快速发现关键算法回归。

### Trade-offs
- 插件模块加载失败将导致推理初始化失败（配置错误需尽早暴露）。
- 当前 golden check 是轻量校验，仍需补充真实场景压测与人工验收。

## Rollout Plan
1. 将内置算法封装为插件并注册。
2. 增加外部插件入口与示例模块。
3. 增加 `quality_gate.sh` 执行 compile + golden checks。
4. 在下一阶段引入真实供应商插件并做并行验证。

## Acceptance Criteria
- [x] 内置两类任务通过插件运行。
- [x] 支持外部插件模块加载。
- [x] 质量门禁脚本可执行并通过。
- [ ] 引入至少一个真实供应商插件并通过压测验收。
