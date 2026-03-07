import os
from dataclasses import dataclass


@dataclass
class EdgeSettings:
    # 边缘 Agent 回连中心端的 HTTPS 基地址 / Backend base URL used by edge agent.
    backend_base_url: str = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
    # 设备唯一编码（用于任务定向与审计）/ Unique device code for routing and audit trace.
    edge_device_code: str = os.getenv("EDGE_DEVICE_CODE", "edge-01")
    # 设备鉴权 Token（对应中心端登记）/ Edge authentication token issued by control plane.
    edge_token: str = os.getenv("EDGE_TOKEN", "EDGE_TOKEN_CHANGE_ME")
    # Agent 版本号（用于中心端设备可观测）/ Edge agent version reported to control plane.
    edge_agent_version: str = os.getenv("EDGE_AGENT_VERSION", "edge-agent/2026.03")
    # 轮询间隔秒数 / Poll interval in seconds.
    edge_poll_seconds: int = int(os.getenv("EDGE_POLL_SECONDS", "10"))
    # 本地缓存目录（资产、补传队列、临时文件）/ Local cache directory for assets and retry queue.
    edge_cache_dir: str = os.getenv("EDGE_CACHE_DIR", "/tmp/vistral_edge_cache")
    # 本地模型解密密钥路径 / Local decrypt key path for encrypted model artifacts.
    edge_decrypt_key_path: str = os.getenv("EDGE_DECRYPT_KEY_PATH", "/app/keys/model_decrypt.key")
    # 平台签名公钥路径（用于验签）/ Platform public key path for signature verification.
    edge_sign_public_key_path: str = os.getenv("EDGE_SIGN_PUBLIC_KEY_PATH", "/app/keys/model_sign_public.pem")
    # 推理模式（mock/真实插件）/ Inference mode, e.g. mock or plugin-based runtime.
    edge_inference_mode: str = os.getenv("EDGE_INFERENCE_MODE", "mock")
    # 是否校验证书 / Whether to verify TLS certificates.
    verify_tls: bool = os.getenv("VERIFY_TLS", "false").lower() == "true"


settings = EdgeSettings()
