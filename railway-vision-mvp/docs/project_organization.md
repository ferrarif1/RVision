# Project Organization Map

## 1. Purpose

这份文档把“这个仓库该怎么继续长大”说清楚，避免后续开发把产品、推理、训练、交付、文档和测试继续缠在一起。

## 2. Current Repository Topology

| Directory | Responsibility | Current Status |
|---|---|---|
| `backend/` | 平台控制面 API、权限、模型/流水线/任务/审计 | 已是当前主控制面 |
| `edge/` | 边缘 Agent、推理运行时、插件执行、结果回传 | 已是真实运行平面 |
| `frontend/` | 控制台 UI 与角色化操作入口 | 已完成多轮 IA 与 UI 收敛 |
| `docker/` | 本地部署、demo、质量门禁脚本 | 已是当前交付入口 |
| `deploy/` | 独立部署物料与远端 worker 下发目录 | 新增 worker 部署收口入口 |
| `docs/` | 组织控制面、架构与发布标准 | 本轮已升级为统一文档体系 |
| `demo_data/` | 演示数据与样本 | 辅助目录 |

## 3. Architecture Boundaries To Keep Clean

后续开发必须守住这几个边界：

### A. Control Plane vs Runtime Plane

- `backend/` 是控制面：注册、审批、授权、编排配置、审计、任务下发。
- `edge/` 是运行平面：拉任务、拉模型、推理、缓存、回传。
- 不能把边缘运行逻辑继续塞回后端接口层。

### B. Inference Plane vs Training Plane

- 当前仓库只有推理平面真实落地。
- 训练平面属于下一阶段能力，必须单独建设，不应混在 `tasks` 或 `edge inference` 里凑合实现。
- 真正做训练时，应新增独立的 training control plane 和 worker agent，而不是复用现有 edge 推理 agent。

### C. Product Surface vs Internal Complexity

- 用户默认入口只暴露“上传、执行、查看结果”及审批发布等主路径。
- JSON、兼容模式、专家配置、调试开关要继续收在高级层，不再回流到默认界面。

## 4. Recommended Next Refactor Order

按影响面和收益排序，建议这样推进：

### Priority 1: Training Control Plane

目标：

- 补齐训练数据分发、真实训练执行、产物回收与模型晋级链路。

原因：

- 这是当前业务口径与真实实现之间最大的缺口。
- 不补这一层，平台只能算“交付与推理平台”，还不是完整的托管训练平台。

### Priority 2: Shared Contracts

目标：

- 把模型协议、流水线 schema、审计字段、结果结构整理成共享 contract。

原因：

- 当前这些契约分散在前端、后端、边缘与文档里。
- 不先收敛 contract，后续训练控制面和更多模型类型会继续放大耦合。

### Priority 3: Frontend Componentization

目标：

- 当前前端已拆分为模块化 SPA：`frontend/src/core + src/layout + src/pages + src/main.js`，壳层入口为 `frontend/index.html`。

原因：

- 当前前端已经可用，但维护成本会随着页面继续增长而迅速上升。

### Priority 4: QA Automation Expansion

目标：

- 把 release gate 从“基础 compile + parity + demo smoke”扩展到更稳定的回归矩阵。

原因：

- 训练控制面、更多角色路径和更多交付方式上线后，现有门禁覆盖会不足。

## 5. Suggested Ownership Model

| Track | Primary Owner | Secondary Owner |
|---|---|---|
| Product | 产品负责人 | 设计 / 前端 |
| UI / Interaction | 设计负责人 | 前端 / 产品 |
| Backend Control Plane | 平台后端 | CTO |
| Edge Runtime | 平台算法 / 边缘工程 | CTO / QA |
| QA Gate | QA | Backend / Frontend / Edge |
| Business / Pricing | CEO / 商务 | Product / CTO |

## 6. Repo Change Rules

后续较大改动遵循以下规则：

1. 新能力先更新文档，再改代码。
2. 新子系统先写 ADR 或 PRD，再进入实现。
3. 涉及发布路径、权限、审计、模型协议的改动必须同步更新 QA 与 runbook。
4. 所有新能力必须说明当前是否真的可运行，禁止把 roadmap 写成已实现。

## 7. What “Project Optimization” Means Next

下一轮如果继续做“整个项目优化”，建议按这个顺序执行：

1. 先把训练控制面的执行面补齐。
2. 再收敛共享协议和 schema。
3. 再拆前端组件与页面层。
4. 最后扩 QA、ORR、发布门禁。

这个顺序可以保证项目先补真实能力缺口，再优化可维护性，而不是反过来。
