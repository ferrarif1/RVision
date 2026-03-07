# Product Track

## Mission

Product 轨道负责把复杂的平台能力收敛成用户一眼能懂、30 秒能完成第一次关键任务的产品体验。这里的核心是问题定义、用户路径、成功指标和发布质量。

## Product North Star

- 首次使用：用户 30 秒内看懂先做什么、再做什么、最后得到什么。
- 任一页面：只有 1 个主按钮，次按钮不超过 2 个。
- 角色清晰：客户、供应商、平台管理员、授权设备四条业务线不混淆。
- 数据可信：任何用户都知道当前看的数据来自哪里、下一步去哪。

## Current Product Truth

- 当前前端已经具备 `模型 / 流水线 / 资产 / 执行 / 结果 / 审计` 的基础页与角色收敛。
- 当前推理闭环已真实可跑。
- 当前训练 / 微调已形成“资产与模型治理流”的产品能力，并在持续增强可运营的训练能力。
- 产品文档必须明确区分“已实现能力”和“目标架构”。

## Required Product Artifacts

| Artifact | Purpose | Trigger |
|---|---|---|
| Problem Brief | 定义机会、痛点、范围和成功条件 | 新方向、新角色、新业务线 |
| PRD | 定义需求、路径、非目标、成功指标 | 进入开发排期前 |
| Success Metrics Plan | 明确北极星、守护指标、事件埋点 | 涉及新流程或改版 |
| Launch Brief | 定义发布对象、风险、支持节奏 | 进入上线窗口前 |
| Post-launch Review | 验证效果、问题与后续迭代 | 上线后一周/一个周期 |

## Product Quality Bar

一份可进入开发的产品文档至少要满足：

- 只写必须解决的问题，不把技术实现细节混成需求。
- 有明确用户、角色、场景和最短路径。
- 写清默认路径与兼容路径，不能全部并列暴露给用户。
- 有 success metrics 和 fail conditions。
- 有非目标，防止 scope 漂移。

## Product Operating Model

建议的工作顺序：

1. 先定义角色与任务，再收敛接口与实现。
2. 先定义最短路径，再定义高级能力放哪。
3. 先定义默认值、空状态、错误状态，再进入视觉与实现。
4. 发布前用真实账号按角色走一遍关键路径。

## Core Concerns For This Project

- 客户用户：数据上传后是否明确知道下一步去执行。
- 供应商：模型提交后是否明确知道当前状态、审批进度与要求。
- 平台管理员：验证、审批、发布是否是一条连续路径。
- 授权设备：授权方式与调用方式是否被清楚解释且不暴露底层实现噪音。


## Latest Plan & Execution

- [platform_user_centric_implementation_v1.md](./platform_user_centric_implementation_v1.md)
  用户视角目标态完整实现方案（V1）。
- [platform_user_centric_execution_backlog_v1.md](./platform_user_centric_execution_backlog_v1.md)
  按周执行清单与验收标准（V1）。
- [vistral_positioning_and_role_onboarding.md](./vistral_positioning_and_role_onboarding.md)
  Vistral 的产品定位、核心能力、角色价值和首条上手路径。

## Recommended Deliverables

- [../templates/prd_template.md](../templates/prd_template.md)
- [../templates/phase_report_template.md](../templates/phase_report_template.md)
- [../company_responsibilities.md](../company_responsibilities.md)
- [../business_data_flow.md](../business_data_flow.md)

## Review Questions

- 用户是否不用读说明文档也能完成主路径。
- 是否只保留了当前阶段真正要推给用户的默认路径。
- 文案是否直接表达业务动作，并清楚说明系统带来的业务价值。
- 这次改动是否让首页和关键流程更短、更清楚。
