# Training Control Plane

## 1. Current Scope

当前仓库已经落地训练控制面的最小骨架，但还不是完整训练平台。

已实现：

- `training_jobs`
  - 创建训练作业
  - 查询训练作业
  - 取消 / 重试 / 改派训练作业
  - 记录作业状态、输入资产、目标模型、worker 选择器、输出摘要
- `training_workers`
  - 注册 worker
  - worker 心跳
  - worker 拉取待执行作业
  - worker 查询作业控制信号（继续 / 停止）
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
  - `TRAINING_JOB_CANCEL`
  - `TRAINING_JOB_RETRY`
  - `TRAINING_JOB_REASSIGN`
  - `TRAINING_WORKER_REGISTER`
  - `TRAINING_WORKER_HEARTBEAT`
  - `TRAINING_ASSET_PULL`
  - `TRAINING_MODEL_PULL`
  - `TRAINING_CANDIDATE_UPLOAD`

已补齐（MVP 执行层）：

- 源脚本 `docker/scripts/training_worker_runner.py` 实现 worker 端完整执行循环：
  - 心跳、拉取作业
  - 查询作业控制信号，支持运行中取消后的 worker 侧中止
  - 受控拉取训练/验证资产
  - 受控拉取并解密基线模型
  - 执行训练命令钩子（`--trainer-cmd`）或内置 mock 微调
  - 候选模型打包（复用 `model_package_tool`）并上传
  - 回传 `RUNNING/SUCCEEDED/FAILED` 状态与指标摘要
  - 内置 / mock trainer 会按 epoch 回写 `history` 和 `best_checkpoint`，训练页可直接展示收敛曲线
  - 控制面可自动识别 stale worker、DISPATCHED 超时、RUNNING 超时，并将作业回收到 `FAILED` 且写入告警摘要

仍未实现（平台级增强）：

- 分布式训练执行器（多 worker 协同调度）
- 训练日志流式上传与长期留存（当前只回传摘要）
- 候选模型自动审批、自动晋级
- 容量治理与更精细的资源调度

## 2. API Surface

平台侧：

- `POST /training/jobs`
- `GET /training/jobs`
- `GET /training/jobs/{job_id}`
- `POST /training/jobs/{job_id}/cancel`
- `POST /training/jobs/{job_id}/retry`
- `POST /training/jobs/{job_id}/reassign`
- `POST /training/workers/register`
- `GET /training/workers`
- `POST /training/runtime/reconcile`

worker 侧：

- `POST /training/workers/heartbeat`
- `POST /training/workers/pull-jobs`
- `GET /training/workers/job-control`
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
- 运行健康：worker 心跳过期、派发超时、执行超时可自动转成结构化告警与失败原因

但还没有真正完成：

- 分布式训练执行器
- 数据预热、缓存复用、容量调度

## 5. Next Step

下一阶段应优先补齐：

1. worker 真实执行协议、训练日志与指标流
2. 训练完成后的自动验证、审批编排与发布串联
3. 容量治理、资源排序与更细粒度的调度策略
4. 数据缓存复用和更细粒度的数据访问控制


## 6. Worker Runner（新增）

独立部署目录：`deploy/training-worker/`。

其中：

- `run_worker.sh`：worker 启动入口
- `worker.env.example`：环境变量模板
- `requirements.txt`：最小依赖
- `build_bundle.py`：构建独立部署包
- `training_worker_runner.py`：bundle 内的真实执行脚本（由构建脚本从 `docker/scripts/training_worker_runner.py` 复制）

### 6.1 作用

该脚本把训练控制面 API 串成可执行链路：

1. `POST /training/workers/heartbeat`
2. `POST /training/workers/pull-jobs`
3. `GET /training/workers/job-control`
4. `GET /training/workers/pull-asset`
5. `POST /training/workers/pull-base-model`
6. 本地训练（外部命令或内置 mock）
7. `POST /training/workers/upload-candidate`
8. `POST /training/workers/push-update`

### 6.2 快速运行

```bash
cd <repo-root>
cp deploy/training-worker/worker.env.example deploy/training-worker/worker.env
bash deploy/training-worker/run_worker.sh --once
```

如果需要下发到远端训练机：

```bash
cd <repo-root>
python3 deploy/training-worker/build_bundle.py
```

输出目录：

- `deploy/training-worker/dist/vistral-training-worker/`

### 6.3 接入真实训练

可通过 `--trainer-cmd` 注入真实训练逻辑。命令支持占位变量：

- `{job_dir}`
- `{train_manifest}`
- `{val_manifest}`
- `{base_model_path}`
- `{output_model_path}`
- `{job_json}`
- `{metrics_json}`

外部训练命令契约版本：`vistral.external_trainer.v1`

退出码约定：

- `10`：配置错误（不可重试）
- `11`：输入契约错误（不可重试）
- `12`：训练数据错误（不可重试）
- `20`：训练运行时错误（可重试）
- `21`：依赖不可用（可重试）
- `22`：中断退出（可重试）

真实训练命令需至少产出：

- 模型文件：`{output_model_path}`
- 指标文件：`{metrics_json}`（JSON object）

`metrics_json` 固定字段：

- 顶层：`epochs / learning_rate / train_loss / val_loss / train_accuracy / val_accuracy / final_loss / val_score`
- 历史：`history: [{epoch, train_loss, val_loss, train_accuracy, val_accuracy, learning_rate, duration_sec, note}]`
- 最优 checkpoint：`best_checkpoint: {epoch, metric, value, path}`

如果外部 trainer 返回非零退出码，worker 会把失败分类、是否可重试、退出码以及 stdout/stderr 末尾摘要写入 `output_summary`，便于控制台直接展示与后续重试决策。
