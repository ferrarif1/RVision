# Docs Index

## Documentation Standard

这套文档是项目的控制面。所有文档都要满足以下要求：

- 真实反映当前实现，不把目标态写成已落地能力。
- 对业务、技术、发布、验收使用同一套术语。
- 每个关键决策都要能回答：为什么做、现在做到哪、怎么验证、失败如何回滚。
- 文档要直接驱动评审、开发、测试、上线，并为发布决策提供证据。

建议所有新文档至少包含以下元信息：

- Owner
- Status
- Last Updated
- Scope / Non-goals
- Decision / Next Step
- Evidence / Links

## Current Truth

当前仓库的真实状态需要在所有轨道中保持一致：

- 推理执行链路已实装，运行位置在边缘 Agent / 推理运行时。
- Pipeline Registry、Orchestrator、Result Store / Audit 已可运行，并支撑 demo 与回归。
- 训练 / 微调在当前 MVP 中已具备最小控制面骨架：训练作业对象、worker 注册、心跳、作业拉取和状态回传。
- 完整的训练执行、数据分发、产物晋级和容量治理仍未落地；`server1` 统一调度远程训练主机仍处于下一阶段演进中。

## Unified Business Thread

以下文档统一使用同一套 4 条业务线口径：

- 客户用户上传图片或视频资产，资产可用于训练、微调、测试验收或推理。
- 供应商上传初始算法与可选预训练模型，在平台受控环境内结合客户数据反复微调，形成候选成果模型并提交审批。
- 平台管理员结合客户测试数据验证模型有效性，审批并发布模型。
- 授权客户设备通过模型 API 或授权密钥使用加密模型，本地运行时完成解密。

## Unified Technical Thread

以下文档统一使用同一套平台技术主线：

- `Model Registry`：统一管理 `router / expert` 模型元数据、插件协议、运行时、版本和哈希。
- `Pipeline Registry`：一条 Pipeline = 主路由 + 专家映射 + 阈值 + 融合规则 + 人工复核规则。
- `Orchestrator`：按 router 输出动态拉起专家推理，融合结果并写入运行记录。
- `Result Store / Audit`：保存 pipeline 版本、阈值版本、输入摘要、输出摘要、耗时、哈希和审计记录。
- `Training Control Plane`：当前已具备最小骨架，负责训练作业对象、远程 worker 接入与状态流转；完整训练执行、产物回收与模型晋级仍是后续阶段。

## Track Responsibilities

- [ceo/README.md](./ceo/README.md)
  商业模型、定价、合作边界、经营指标和对外叙事。
- [cto/README.md](./cto/README.md)
  架构治理、ADR、可运维性、安全边界、迁移与回滚。
- [product/README.md](./product/README.md)
  问题定义、用户路径、PRD、成功指标、发布节奏。
- [interaction/README.md](./interaction/README.md)
  用户流程、状态设计、交互规格、文案与边界行为。
- [ui/README.md](./ui/README.md)
  设计系统、组件规范、无障碍、视觉一致性。
- [qa/README.md](./qa/README.md)
  测试策略、质量门禁、证据归档、发布决策。

## Core Documents

- [architecture.md](./architecture.md)
  平台总体架构、当前能力与目标态边界。
- [edge_terminal_access.md](./edge_terminal_access.md)
  边缘终端接入流程、参数、接口契约与排障手册。
- [business_data_flow.md](./business_data_flow.md)
  业务流、控制流、审计流与数据分级。
- [training_control_plane.md](./training_control_plane.md)
  训练控制面的当前最小实现与后续缺口。
- [company_responsibilities.md](./company_responsibilities.md)
  平台、供应商、客户三方职责边界。
- [model_package.md](./model_package.md)
  模型包结构、签名、加密、验签与发布要求。
- [demo.md](./demo.md)
  demo 运行手册与验证路径。
- [platform_access_and_feature_guide.md](./platform_access_and_feature_guide.md)
  面向商业交付的接入与功能使用指南，覆盖角色上手、核心流程和推荐路径。
- [roadmap_ctxport_based.md](./roadmap_ctxport_based.md)
  分阶段路线图与能力演进顺序。
- [product/platform_user_centric_implementation_v1.md](./product/platform_user_centric_implementation_v1.md)
  用户视角目标态完整实现方案（V1）。
- [product/platform_user_centric_execution_backlog_v1.md](./product/platform_user_centric_execution_backlog_v1.md)
  对应执行清单与阶段验收标准（V1）。
- [product/current_execution_backlog_2026-03-10.md](./product/current_execution_backlog_2026-03-10.md)
  当前真实执行清单：已完成、半完成、中断项与下一步顺序。
- [product/dynamic_execution_todo_2026-03-11.md](./product/dynamic_execution_todo_2026-03-11.md)
  动态维护的执行面板：记录当前正在做、下一步、排队中和最近完成项，供持续迭代时实时更新。
- [product/novice_user_usability_audit_2026-03-11.md](./product/novice_user_usability_audit_2026-03-11.md)
  从“只懂少量概念的新用户”视角记录哪里不好用、哪里不明白，以及后续该优先优化什么。
- [product/railcar_robot_inspection_model_family_2026-03-12.md](./product/railcar_robot_inspection_model_family_2026-03-12.md)
  将《铁路货车轮足式机器人库内智能巡检应用技术方案》收敛成可执行的巡检模型族、训练优先级和数据采集建议。
- [product/railcar_inspection_data_workspace_2026-03-12.md](./product/railcar_inspection_data_workspace_2026-03-12.md)
  巡检任务族的数据工作区、标注模板与训练/验证包生成脚手架说明。
- [product/vistral_positioning_and_role_onboarding.md](./product/vistral_positioning_and_role_onboarding.md)
  Vistral 的产品定位、核心价值和角色上手路径。
- [project_organization.md](./project_organization.md)
  项目目录、职责边界与建议的下一步重构顺序。
- [qa/release_gate_runbook.md](./qa/release_gate_runbook.md)
  发布 GO/NO-GO 执行手册。
- [qa/browser_walkthrough_checklist_2026-03-11.md](./qa/browser_walkthrough_checklist_2026-03-11.md)
  页面级人工走查清单，覆盖任务、结果、训练、模型、流水线等关键控制台页。
- [qa/browser_walkthrough_report_2026-03-12.md](./qa/browser_walkthrough_report_2026-03-12.md)
  页面级走查结果与修复结论，记录本轮导航拆分、术语减负、回跳链路和布局稳定性收口情况。
- [qa/ocr_generalization_iteration_2026-03-12.md](./qa/ocr_generalization_iteration_2026-03-12.md)
  OCR 真实泛化迭代记录，覆盖库内 45° 侧拍车身标记识别场景、本轮场景配置外置和难样本 probe 结果。
- [references.md](./references.md)
  文档体系参考的公开方法论来源。

## Working Method

推荐按以下顺序使用文档：

1. 先读 [architecture.md](./architecture.md) 和 [business_data_flow.md](./business_data_flow.md)，搞清当前真实边界。
2. 再按角色进入对应轨道文档，明确需要产出的工件与评审标准。
3. 任何跨系统新能力都先写 ADR 或 PRD，再进入交互、UI、QA 落地。
4. 发布前统一走 ORR / QA Gate / GO-NO-GO，确保评审、验证和发布决策使用同一套证据。

## Templates

- [templates/adr_template.md](./templates/adr_template.md)
- [templates/prd_template.md](./templates/prd_template.md)
- [templates/interaction_spec_template.md](./templates/interaction_spec_template.md)
- [templates/test_plan_template.md](./templates/test_plan_template.md)
- [templates/orr_template.md](./templates/orr_template.md)
- [templates/qa_release_checklist.md](./templates/qa_release_checklist.md)
- [templates/phase_report_template.md](./templates/phase_report_template.md)

## QA Reports

- 门禁报告归档目录：[qa/reports/](./qa/reports/)
