# QA Track

## Mission

QA 轨道负责把“看起来能跑”变成“有证据地可发布”。质量不是最后一环兜底，而是对需求、实现、数据、权限、审计、发布与回滚的系统性约束。

## Current Truth

- 当前推理链路已经可以通过 demo、golden checks、parity regression 和 GO/NO-GO 脚本验证。
- 当前训练 / 微调控制面已具备最小闭环，并已纳入正式 QA 门禁。
- 当前训练相关 QA 结论覆盖：作业对象、worker 接入、资产/模型受控拉取、候选模型回收入库、审计痕迹。
- 当前训练相关 QA 结论仍不能冒充“真实训练引擎验证”，因为实际训练执行器还没落地。

## Test Strategy

推荐使用分层策略而不是单一人工回归：

| Layer | Goal | Typical Evidence |
|---|---|---|
| Compile / Static | 保证代码和基础资源可解析 | `py_compile`、`node --check`、lint |
| Unit / Module | 保证关键函数与数据转换稳定 | 单元测试、golden fixtures |
| API / Contract | 保证前后端、角色、审计契约稳定 | parity regression、schema checks |
| Runtime Smoke | 保证关键闭环真实可跑 | bootstrap demo、docker logs、API smoke |
| Manual Risk Review | 覆盖高风险 UI/权限/流程体验 | checklist、截图、录屏、复盘 |

## Quality Officer Protocol

每次功能完成后，质量官至少要做两件事：

1. 跑通通用门禁：`bash docker/scripts/quality_gate.sh`
2. 如改动涉及训练控制面，归档 `docs/qa/reports/training_control_plane_latest.json`

没有脚本报告或运行证据，默认视为“未检查完成”。

## Release Gate

发布前必须至少回答：

- 这次发布改了哪些关键路径。
- 哪些风险通过自动化覆盖，哪些仍靠人工验证。
- 哪些已知问题被接受上线，谁签字承担。
- 失败后如何回滚，数据如何恢复。

核心文档：

- [release_gate_runbook.md](./release_gate_runbook.md)
- [../templates/qa_release_checklist.md](../templates/qa_release_checklist.md)
- [../templates/test_plan_template.md](../templates/test_plan_template.md)
- [../templates/phase_report_template.md](../templates/phase_report_template.md)

## Evidence Standard

没有证据就不算完成。可接受证据包括：

- 脚本输出与报告文件
- 截图、录屏、容器日志
- 审计记录与数据库落点
- 质量门禁 JSON 报告
- 风险接受人与时间戳

## QA Review Questions

- 是否验证了当前版本真实支持的能力，而不是验证目标态描述。
- 空状态、无权限、接口失败时是否都有明确反馈。
- 角色权限是否在前端和后端同时正确收敛。
- 结果、导出、发布、审计等关键动作是否都能回查。
