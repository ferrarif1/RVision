# Vistral Training Worker Bundle

这个目录已经是可直接下发到远端训练机的独立 worker bundle。

## 目录内容

- `training_worker_runner.py`：worker 真实执行脚本
- `run_worker.sh`：启动入口，会自动读取同目录 `worker.env`
- `worker.env.example`：环境变量模板
- `requirements.txt`：最小 Python 依赖
- `backend/app/...`：候选模型打包所需的最小 Python 模块
- `keys/README.md`：必须补充的密钥说明

## 部署步骤

```bash
cd /opt/vistral-training-worker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp worker.env.example worker.env
# 编辑 worker.env，填入 worker_code / worker_token / backend 地址
bash run_worker.sh
```

## 必需密钥

在启动前，请把以下文件放到 `keys/` 目录：

- `keys/model_decrypt.key`
- `keys/model_encrypt.key`
- `keys/model_sign_private.pem`

## 自检

```bash
bash run_worker.sh --help
```
