import os
from dataclasses import dataclass


@dataclass
class EdgeSettings:
    backend_base_url: str = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
    edge_device_code: str = os.getenv("EDGE_DEVICE_CODE", "edge-01")
    edge_token: str = os.getenv("EDGE_TOKEN", "EDGE_TOKEN_CHANGE_ME")
    edge_poll_seconds: int = int(os.getenv("EDGE_POLL_SECONDS", "10"))
    edge_cache_dir: str = os.getenv("EDGE_CACHE_DIR", "/tmp/rv_edge_cache")
    edge_decrypt_key_path: str = os.getenv("EDGE_DECRYPT_KEY_PATH", "/app/keys/model_decrypt.key")
    edge_sign_public_key_path: str = os.getenv("EDGE_SIGN_PUBLIC_KEY_PATH", "/app/keys/model_sign_public.pem")
    edge_inference_mode: str = os.getenv("EDGE_INFERENCE_MODE", "mock")
    verify_tls: bool = os.getenv("VERIFY_TLS", "false").lower() == "true"


settings = EdgeSettings()
