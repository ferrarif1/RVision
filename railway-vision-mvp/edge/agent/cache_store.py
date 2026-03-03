import base64
import json
import os
from datetime import datetime

from agent.config import settings

CACHE_ROOT = settings.edge_cache_dir
PENDING_FILE = os.path.join(CACHE_ROOT, "pending_results.jsonl")
ASSET_DIR = os.path.join(CACHE_ROOT, "assets")
MODEL_DIR = os.path.join(CACHE_ROOT, "models")
SCREENSHOT_DIR = os.path.join(CACHE_ROOT, "screenshots")


def ensure_cache_dirs() -> None:
    os.makedirs(CACHE_ROOT, exist_ok=True)
    os.makedirs(ASSET_DIR, exist_ok=True)
    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def save_asset_from_b64(asset_id: str, file_name: str, file_b64: str) -> str:
    ensure_cache_dirs()
    ext = os.path.splitext(file_name)[1] or ".bin"
    local_path = os.path.join(ASSET_DIR, f"{asset_id}{ext}")
    with open(local_path, "wb") as f:
        f.write(base64.b64decode(file_b64))
    return local_path


def enqueue_pending_result(payload: dict) -> None:
    ensure_cache_dirs()
    payload = dict(payload)
    payload["queued_at"] = datetime.utcnow().isoformat()
    with open(PENDING_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def dequeue_all_pending_results() -> list[dict]:
    if not os.path.exists(PENDING_FILE):
        return []
    with open(PENDING_FILE, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    pending = []
    for line in lines:
        try:
            pending.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    os.remove(PENDING_FILE)
    return pending


def get_model_dir() -> str:
    ensure_cache_dirs()
    return MODEL_DIR


def get_screenshot_dir() -> str:
    ensure_cache_dirs()
    return SCREENSHOT_DIR
