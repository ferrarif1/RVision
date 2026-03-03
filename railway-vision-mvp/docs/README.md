# Docs Index

## Unified Business Thread

以下文档统一使用同一套 4 条业务线口径：

- 客户用户上传图片或视频资产，资产可用于训练、微调、测试验收或推理。
- 供应商上传初始算法与可选预训练模型，在平台受控环境内结合客户数据反复微调，形成候选成果模型并提交审批。
- 平台管理员结合客户测试数据验证模型有效性，审批并发布模型。
- 授权客户设备通过模型 API 或授权密钥使用加密模型，本地运行时完成解密。

## Unified Technical Thread

以下文档统一使用同一套平台技术主线：

- `Model Registry`：统一管理 router / expert 模型元数据、插件协议、运行时、版本和哈希。
- `Pipeline Registry`：一条 Pipeline = 主路由 + 专家映射 + 阈值 + 融合规则 + 人工复核规则。
- `Orchestrator`：按 router 输出动态拉起专家推理，融合结果并写入运行记录。
- `Result Store / Audit`：保存 pipeline 版本、阈值版本、输入摘要、输出摘要、耗时、哈希和审计记录。

## Core Documents
- [architecture.md](./architecture.md): platform architecture and deployment view
- [business_data_flow.md](./business_data_flow.md): business and data flow
- [company_responsibilities.md](./company_responsibilities.md): company vs supplier responsibilities
- [model_package.md](./model_package.md): model package standard
- [demo.md](./demo.md): demo runbook
- [roadmap_ctxport_based.md](./roadmap_ctxport_based.md): engineering roadmap based on ctxport methodology
- [cto/adr-0002-edge-plugin-runtime.md](./cto/adr-0002-edge-plugin-runtime.md): edge plugin runtime decision
- [qa/release_gate_runbook.md](./qa/release_gate_runbook.md): GO/NO-GO execution runbook

## Working Tracks
- [ceo/](./ceo/README.md): pricing, settlement, policy
- [cto/](./cto/README.md): ADR and architecture governance
- [product/](./product/README.md): IA, role matrix, workflows
- [interaction/](./interaction/README.md): process and interaction specs
- [ui/](./ui/README.md): design tokens and visual standards
- [qa/](./qa/README.md): test strategy and release gate reports

## Templates
- [templates/adr_template.md](./templates/adr_template.md)
- [templates/qa_release_checklist.md](./templates/qa_release_checklist.md)
- [templates/phase_report_template.md](./templates/phase_report_template.md)

## QA Reports
- gate report archive directory: [qa/reports/](./qa/reports/)
