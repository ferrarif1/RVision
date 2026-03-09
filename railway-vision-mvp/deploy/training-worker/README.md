# Vistral Training Worker Deployment

`deploy/training-worker/` 是训练 worker 的独立部署目录。这个目录把远端训练机真正需要的文件入口集中起来，避免继续从仓库各处手工拼脚本、密钥路径和依赖。

## 目录说明

- `run_worker.sh`：worker 启动入口。优先读取同目录 `worker.env`，再自动补齐默认路径。
- `worker.env.example`：环境变量模板，包含中英文注释。
- `requirements.txt`：worker 最小 Python 依赖。
- `build_bundle.py`：生成可直接下发到远端训练机的独立 bundle。
- `keys/README.md`：需要放入 bundle 的密钥说明。

## 在仓库内直接运行

```bash
cd <repo-root>
cp deploy/training-worker/worker.env.example deploy/training-worker/worker.env
bash deploy/training-worker/run_worker.sh --help
```

如果当前仓库已经执行过 `docker/scripts/generate_local_materials.sh`，`run_worker.sh` 会自动优先使用仓库里的：

- `edge/keys/model_decrypt.key`
- `docker/keys/model_encrypt.key`
- `docker/keys/model_sign_private.pem`
- `backend/`

## 生成独立部署包

```bash
cd <repo-root>
python3 deploy/training-worker/build_bundle.py
```

输出目录默认是：

- `deploy/training-worker/dist/vistral-training-worker/`

bundle 会包含：

- `training_worker_runner.py`
- `run_worker.sh`
- `worker.env.example`
- `requirements.txt`
- `backend/app/...` 最小打包依赖
- `keys/README.md`

> 为了避免把敏感材料直接打进仓库产物，构建脚本不会自动复制密钥。下发到远端机器前，需要把加密/签名相关密钥按 `keys/README.md` 的要求单独放进去。

## 远端机器部署步骤

```bash
cd /opt/vistral-training-worker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp worker.env.example worker.env
# 编辑 worker.env，填入 worker_code / worker_token / backend 地址
bash run_worker.sh
```

## 外部训练命令契约

如需接入真实 trainer，使用 `TRAINING_TRAINER_CMD` 或 `--trainer-cmd`。

可用占位变量：

- `{job_dir}`
- `{train_manifest}`
- `{val_manifest}`
- `{base_model_path}`
- `{output_model_path}`
- `{job_json}`
- `{metrics_json}`

退出码约定：

- `10`：配置错误，不可重试
- `11`：输入契约错误，不可重试
- `12`：数据错误，不可重试
- `20`：运行时错误，可重试
- `21`：依赖不可用，可重试
- `22`：中断退出，可重试

`metrics_json` 需要输出稳定 JSON object，支持：

- 顶层指标：`epochs / learning_rate / train_loss / val_loss / train_accuracy / val_accuracy / final_loss / val_score`
- 历史曲线：`history`
- 最优 checkpoint：`best_checkpoint`

## 最低运行要求

- Python 3.11+
- 能访问中心端 `backend`
- 已在平台侧注册训练 worker，并拿到 bootstrap token
- 已放置以下密钥文件：
  - `keys/model_decrypt.key`
  - `keys/model_encrypt.key`
  - `keys/model_sign_private.pem`
