# Training Control Plane

## 1. Current Scope

当前仓库已经落地训练控制面的最小骨架，但还不是完整训练平台。

已实现：

- `training_jobs`
  - 创建训练作业
  - 查询训练作业
  - 记录作业状态、输入资产、目标模型、worker 选择器、输出摘要
- `training_workers`
  - 注册 worker
  - worker 心跳
  - worker 拉取待执行作业
  - worker 受控拉取训练资产
  - worker 受控拉取基线模型包
  - worker 上传候选模型包
  - worker 回传作业状态
- 候选模型回收
  - 训练 worker 上传合法模型包后，平台自动验签、入库并生成 `SUBMITTED` 候选模型
  - 训练作业自动关联 `candidate_model_id`
- 审计事件
  - `TRAINING_JOB_CREATE`
  - `TRAINING_JOB_ASSIGN`
  - `TRAINING_JOB_UPDATE`
  - `TRAINING_WORKER_REGISTER`
  - `TRAINING_WORKER_HEARTBEAT`
  - `TRAINING_ASSET_PULL`
  - `TRAINING_MODEL_PULL`
  - `TRAINING_CANDIDATE_UPLOAD`

未实现：

- 真正的训练执行引擎
- 训练日志流式上传与长期留存
- 候选模型自动审批、自动晋级
- 调度队列、重试、超时回收、容量治理

## 2. API Surface

平台侧：

- `POST /training/jobs`
- `GET /training/jobs`
- `GET /training/jobs/{job_id}`
- `POST /training/workers/register`
- `GET /training/workers`

worker 侧：

- `POST /training/workers/heartbeat`
- `POST /training/workers/pull-jobs`
- `GET /training/workers/pull-asset`
- `POST /training/workers/pull-base-model`
- `POST /training/workers/upload-candidate`
- `POST /training/workers/push-update`

## 3. State Model

### Training Job

- `PENDING`
- `DISPATCHED`
- `RUNNING`
- `SUCCEEDED`
- `FAILED`
- `CANCELLED`

### Training Worker

- `ACTIVE`
- `INACTIVE`
- `UNHEALTHY`

## 4. Intended Deployment Model

- `server1`
  - 训练控制面
  - API / 审计 / 状态机 / 调度策略
- remote hosts
  - 训练 worker
  - 按凭证拉取训练作业
  - 执行训练或微调
  - 回传状态与产物摘要

当前实现只完成了这个模型中的“控制面骨架 + worker 接入骨架”。

进一步说，当前已经具备：

- 控制面：作业、worker、状态机、审计
- 受控分发：训练资产和基线模型按作业授权下发
- 产物回收：候选模型包回传后自动入库并等待审批

但还没有真正完成：

- 分布式训练执行器
- 失败重试与超时回收
- 数据预热、缓存复用、容量调度

## 5. Next Step

下一阶段应优先补齐：

1. worker 真实执行协议、训练日志与指标流
2. 训练完成后的自动验证、审批编排与发布串联
3. 训练重试、超时回收、容量治理与告警
4. 数据缓存复用和更细粒度的数据访问控制
