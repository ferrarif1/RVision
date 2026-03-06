# 边缘终端接入说明（Edge Terminal Access Guide）

- Owner: 平台后端 + 边缘运行时
- Status: Active
- Last Updated: 2026-03-06
- Scope: 边缘终端（Edge Agent）接入中心控制面，执行“拉任务 -> 拉模型 -> 本地推理 -> 回传结果”
- Non-goals: 不覆盖真实训练引擎部署，不覆盖 HSM/国密设备接入细节

## 1. 接入目标 / Goal

边缘终端接入后应具备以下能力：

1. 通过设备身份头访问中心端 `/edge/*` 接口。
2. 按授权范围拉取任务、模型和资产。
3. 本地完成验签、解密、推理，并回传结构化结果。
4. 断网时本地缓存结果，网络恢复后自动补传。

## 2. 架构路径 / End-to-End Path

```text
Edge Device
  └─ Edge Agent
      ├─ GET  /edge/ping
      ├─ POST /edge/pull_tasks
      ├─ POST /edge/pull_model
      ├─ GET  /edge/pull_asset
      └─ POST /edge/push_results
             ↓
      Control Plane (FastAPI + DB + Audit)
```

## 3. 前置条件 / Prerequisites

1. 中心端服务已启动（`backend` + `frontend`）。
2. 平台已完成模型提审与发布（至少一条 `RELEASED`）。
3. 已有可执行任务（`/tasks/create` 或 demo 脚本自动创建）。
4. 边缘端具备以下文件：
   - 解密密钥：`edge/keys/model_decrypt.key`
   - 验签公钥：`edge/keys/model_sign_public.pem`

## 4. 配置参数 / Edge Agent Configuration

配置定义见：`edge/agent/config.py`。

| 环境变量 | 默认值 | 中文说明 | English Description |
|---|---|---|---|
| `BACKEND_BASE_URL` | `http://localhost:8000` | 中心端基地址 | Control plane base URL |
| `EDGE_DEVICE_CODE` | `edge-01` | 设备编码（唯一） | Unique edge device code |
| `EDGE_TOKEN` | `EDGE_TOKEN_CHANGE_ME` | 设备鉴权令牌 | Device authentication token |
| `EDGE_POLL_SECONDS` | `10` | 轮询间隔（秒） | Poll interval in seconds |
| `EDGE_CACHE_DIR` | `/tmp/rv_edge_cache` | 本地缓存目录 | Local cache directory |
| `EDGE_DECRYPT_KEY_PATH` | `/app/keys/model_decrypt.key` | 模型解密密钥路径 | Decrypt key path |
| `EDGE_SIGN_PUBLIC_KEY_PATH` | `/app/keys/model_sign_public.pem` | 模型签名公钥路径 | Signature public key path |
| `EDGE_INFERENCE_MODE` | `mock` | 推理模式 | Inference mode |
| `VERIFY_TLS` | `false` | 是否校验证书 | Enable TLS verification |

## 5. 接入步骤 / Integration Steps

### 5.1 使用 Docker Compose Profile（推荐）

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp
docker compose --env-file docker/.env -f docker/docker-compose.yml up -d --build edge-agent
```

检查日志：

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml logs -f edge-agent
```

### 5.2 本地 Python 进程运行（调试）

```bash
cd /Users/zhangyuanyi/Downloads/RVision/railway-vision-mvp/edge
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export BACKEND_BASE_URL=http://localhost:8000
export EDGE_DEVICE_CODE=edge-01
export EDGE_TOKEN=EDGE_TOKEN_CHANGE_ME
export EDGE_DECRYPT_KEY_PATH=./keys/model_decrypt.key
export EDGE_SIGN_PUBLIC_KEY_PATH=./keys/model_sign_public.pem
python -m agent.main
```

## 6. 接口契约 / API Contract

> 所有 `/edge/*` 请求需要设备身份头：
>
> - `x-edge-device-code`
> - `x-edge-token`

### 6.1 `POST /edge/pull_tasks`

请求参数：

```json
{
  "limit": 3
}
```

字段说明：
- `limit`：本次拉取任务数量上限 / Maximum tasks in this pull.

### 6.2 `POST /edge/pull_model`

请求参数：

```json
{
  "model_id": "model-uuid"
}
```

返回关键字段：
- `manifest_b64` / `model_enc_b64` / `signature_b64`：用于本地验签与解密。

### 6.3 `GET /edge/pull_asset?asset_id=...`

返回关键字段：
- `file_b64`：资产二进制内容（Base64）。
- `sensitivity_level`：资产敏感等级。

### 6.4 `POST /edge/push_results`

返回关键字段：
- `task_id`：任务ID。
- `status`：任务最终状态（`SUCCEEDED`/`FAILED`）。

## 7. 关键安全点 / Security Notes

1. 模型包必须“先验签后解密”；任一步失败都应终止任务。
2. 设备 token 只用于边缘接口，不应复用于用户登录体系。
3. `upload_frames` 为关闭时，不应上传截图资产。
4. 保留 `model_hash` 与 `audit_hash`，确保结果可追溯。

## 8. 运行与排障 / Troubleshooting

1. `Model not released to this device`
   - 原因：模型未发布到该设备或买家范围。
   - 处理：检查 `/models/release` 的 `target_devices/target_buyers`。

2. `Model artifacts missing`
   - 原因：中心端模型仓库存储不完整。
   - 处理：检查 `manifest_uri/encrypted_uri/signature_uri` 对应文件。

3. 推送结果失败后任务丢失担忧
   - 机制：`edge/agent/main.py` 已支持本地补传队列。
   - 排查：检查 `EDGE_CACHE_DIR` 下 pending 文件与重试日志。

4. TLS 握手失败
   - 内网自签证书联调时可临时 `VERIFY_TLS=false`。
   - 生产建议启用证书校验并配发可信 CA。

## 9. 验收清单 / Acceptance Checklist

1. 能看到 `ping ok` 日志持续输出。
2. 能成功拉取至少一条任务并完成回传。
3. 结果中心可查到任务与截图（策略允许时）。
4. 审计中心可查到 `EDGE_PULL_TASKS`、`EDGE_PULL_MODEL`、`EDGE_PUSH_RESULTS`。
