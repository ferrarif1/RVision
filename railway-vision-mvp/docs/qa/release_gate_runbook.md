# Release Gate Runbook

## 1. Purpose

这个 runbook 定义发布前的最小质量门槛，用来回答两个问题：

- 这次改动是否已经有足够证据可以发布。
- 如果现在发布失败，团队是否知道如何定位、止损和回滚。

它不是单一脚本说明，而是一套统一的 GO / NO-GO 决策流程。

## 2. Release Gate Scope

当前门禁覆盖以下真实已落地能力：

1. 编译与基础解析检查
2. 边缘推理 golden regression
3. 训练控制面 smoke
4. 角色权限与接口契约校验
5. 审计关键链路校验
6. demo 闭环的可运行性验证

不在当前门禁范围内的能力要明确写出来：

- 真实训练执行引擎
- 完整远程训练 worker 调度、重试与容量治理

这些属于目标态能力，不能在发布决策时假设已经被验证。

## 3. Preconditions

- `docker compose` 相关服务已启动：`backend`、`frontend`、`postgres`、`redis`
- 如需验证任务终态，`edge-agent` profile 已运行
- demo 用户、基线模型、演示资产已准备完成
- 本次变更对应的风险说明、已知问题和回滚方案已可追溯

## 4. Commands

### 4.1 Quality Gate

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
bash docker/scripts/quality_gate.sh
```

该命令当前会执行：

- 编译检查
- 边缘推理 golden checks
- 后端健康检查
- `training_control_plane_smoke.py`

### 4.2 API Parity Regression

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
python3 docker/scripts/parity_regression.py --wait-seconds 120
```

### 4.3 Full GO / NO-GO

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
bash docker/scripts/go_no_go.sh
```

可指定报告目录与等待时间：

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
bash docker/scripts/go_no_go.sh --wait-seconds 180 --report-dir docs/qa/reports
```

## 5. What Must Pass

### Functional / Contract

1. 角色权限契约一致：
   - `/auth/login`
   - `/users/me`
2. 审计边界正确：
   - 平台管理员可读
   - 买家只读边界不越权
3. 任务 / 结果接口关键字段稳定：
   - 任务创建
   - 结果查询
   - 导出链路
4. `RESULT_EXPORT` 等关键动作有对应审计痕迹

### Runtime / Evidence

1. golden checks 通过
2. training control plane smoke 通过
3. demo 闭环能到达终态
4. 边缘回传后的运行记录、结果与审计能查询

## 6. Decision Rules

- `go_no_go.sh` 退出码为 `0`：可进入 `GO`
- 任意步骤失败：默认 `NO-GO`
- 如带已知风险发布，必须显式记录：
  - 风险项
  - 风险接受人
  - 临时缓解措施
  - 最晚修复时间

## 7. Artifacts Produced

- `docs/qa/reports/go_no_go_YYYYMMDD_HHMMSS.json`
- `docs/qa/reports/latest_go_no_go.json`
- 如有 parity 结果，也应同步归档到 `docs/qa/reports/`

## 8. Common Failure Handling

### Task not terminal in time

- 确认 `edge-agent` 是否已运行
- 检查 `docker logs rv_edge_agent`
- 检查 `/edge/pull_tasks` 与 `/edge/push_results` 审计痕迹

### Permission mismatch

- 检查后端角色映射和 capability 下发
- 检查前端页面与控件是否按 capability 收敛

### Audit trace missing

- 检查对应 API handler 是否写审计
- 检查 `resource_type / action / resource_id` 是否符合约定

## 9. Final Gate Question

在做最终 GO / NO-GO 前，负责人必须回答一句话：

“这次发布验证的是当前真实支持的能力，还是把未来能力误当成已实现能力？”

如果回答不清楚，默认 `NO-GO`。
