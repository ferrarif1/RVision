#!/usr/bin/env python3
"""Bootstrap and manage a local Vistral training worker.

Usage examples:
  python3 deploy/training-worker/bootstrap_local_worker.py bootstrap --start --restart
  python3 deploy/training-worker/bootstrap_local_worker.py status
  python3 deploy/training-worker/bootstrap_local_worker.py stop
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
WORKER_ENV_PATH = SCRIPT_DIR / "worker.env"
RUNNER_PATH = SCRIPT_DIR / "run_worker.sh"
RUNTIME_DIR = REPO_ROOT / ".runtime" / "training-worker"
PID_FILE = RUNTIME_DIR / "local_worker.pid"
LOG_FILE = RUNTIME_DIR / "worker.log"

DEFAULT_LABELS = {"kind": "gpu", "managed_by": "bootstrap_local_worker"}
DEFAULT_RESOURCES = {"gpu_mem_mb": 4096, "cpu": 4}


def _candidate_api_bases() -> list[str]:
    env_value = str(os.getenv("VISTRAL_API_BASE") or "").strip()
    candidates = [env_value] if env_value else []
    candidates.extend(
        [
            "https://localhost:8443/api",
            "http://localhost:8000",
        ]
    )
    seen: set[str] = set()
    unique: list[str] = []
    for value in candidates:
        clean = value.rstrip("/")
        if clean and clean not in seen:
            unique.append(clean)
            seen.add(clean)
    return unique


def _build_ssl_context(url: str) -> ssl.SSLContext | None:
    if not url.startswith("https://"):
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _shell_assign(value: Any) -> str:
    text = str(value)
    return "'" + text.replace("'", "'\"'\"'") + "'"


def _json_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: int = 20,
) -> tuple[int, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_build_ssl_context(url)) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else raw
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload


def _detect_api_base() -> str:
    for base in _candidate_api_bases():
        status, _ = _json_request("GET", f"{base}/health", timeout=5)
        if status == 200:
            return base
    raise SystemExit("No reachable Vistral API base found. Tried: " + ", ".join(_candidate_api_bases()))


def _login(api_base: str, username: str, password: str) -> str:
    status, payload = _json_request(
        "POST",
        f"{api_base}/auth/login",
        payload={"username": username, "password": password},
        timeout=10,
    )
    if status != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
        raise SystemExit(f"Login failed for {username}: HTTP {status} {payload}")
    return str(payload["access_token"])


def _register_worker(
    api_base: str,
    token: str,
    *,
    worker_code: str,
    worker_name: str,
    worker_host: str,
    labels: dict[str, Any],
    resources: dict[str, Any],
) -> dict[str, Any]:
    status, payload = _json_request(
        "POST",
        f"{api_base}/training/workers/register",
        token=token,
        payload={
            "worker_code": worker_code,
            "name": worker_name,
            "host": worker_host,
            "status": "ACTIVE",
            "labels": labels,
            "resources": resources,
        },
        timeout=20,
    )
    if status != 200 or not isinstance(payload, dict):
        raise SystemExit(f"Worker register failed: HTTP {status} {payload}")
    return payload


def _list_workers(api_base: str, token: str) -> list[dict[str, Any]]:
    status, payload = _json_request("GET", f"{api_base}/training/workers", token=token, timeout=15)
    if status != 200 or not isinstance(payload, list):
        raise SystemExit(f"List workers failed: HTTP {status} {payload}")
    return payload


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _stop_worker() -> bool:
    pid = _read_pid()
    if not pid:
        return False
    if not _pid_alive(pid):
        PID_FILE.unlink(missing_ok=True)
        return False
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 10
    while time.time() < deadline:
        if not _pid_alive(pid):
            PID_FILE.unlink(missing_ok=True)
            return True
        time.sleep(0.2)
    os.kill(pid, signal.SIGKILL)
    PID_FILE.unlink(missing_ok=True)
    return True


def _write_worker_env(
    *,
    api_base: str,
    worker_code: str,
    worker_token: str,
    worker_host: str,
    labels: dict[str, Any],
    resources: dict[str, Any],
) -> None:
    lines = [
        "# Auto-generated by bootstrap_local_worker.py",
        f"TRAINING_BACKEND_BASE_URL={_shell_assign(api_base)}",
        f"TRAINING_WORKER_CODE={_shell_assign(worker_code)}",
        f"TRAINING_WORKER_TOKEN={_shell_assign(worker_token)}",
        f"TRAINING_WORKER_HOST={_shell_assign(worker_host)}",
        f"TRAINING_BACKEND_ROOT={_shell_assign(str(REPO_ROOT / 'backend'))}",
        f"TRAINING_WORK_DIR={_shell_assign(str(RUNTIME_DIR))}",
        f"MODEL_DECRYPT_KEY={_shell_assign(str(REPO_ROOT / 'edge/keys/model_decrypt.key'))}",
        f"MODEL_ENCRYPT_KEY={_shell_assign(str(REPO_ROOT / 'docker/keys/model_encrypt.key'))}",
        f"MODEL_SIGN_PRIVATE_KEY={_shell_assign(str(REPO_ROOT / 'docker/keys/model_sign_private.pem'))}",
        f"TRAINING_OUTPUT_MODEL={_shell_assign('candidate_model.bin')}",
        f"TRAINING_RUNTIME={_shell_assign('python')}",
        f"TRAINING_MODEL_TYPE={_shell_assign('expert')}",
        f"TRAINING_PLUGIN_NAME={_shell_assign('car_number_ocr')}",
        f"TRAINING_ROUND={_shell_assign('local-bootstrap')}",
        f"TRAINING_DATASET_LABEL={_shell_assign('local-worker-dataset')}",
        f"TRAINING_SUMMARY={_shell_assign('Candidate generated by local bootstrap worker')}",
        f"TRAINING_POLL_SECONDS={_shell_assign('3')}",
        f"TRAINING_PULL_LIMIT={_shell_assign('1')}",
        f"TRAINING_CONTROL_POLL_SECONDS={_shell_assign('2')}",
        f"TRAINING_TRAINER_MODE={_shell_assign('builtin')}",
        f"TRAINING_WORKER_LABELS={_shell_assign(json.dumps(labels, ensure_ascii=False))}",
        f"TRAINING_WORKER_RESOURCES={_shell_assign(json.dumps(resources, ensure_ascii=False))}",
        "",
    ]
    WORKER_ENV_PATH.write_text("\n".join(lines), encoding="utf-8")


def _start_worker(*, once: bool, foreground: bool, restart: bool) -> int:
    if restart:
        _stop_worker()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    cmd = ["bash", str(RUNNER_PATH)]
    if once:
        cmd.append("--once")
    if foreground:
        return subprocess.call(cmd, cwd=str(REPO_ROOT))
    with LOG_FILE.open("ab") as log_handle:
        process = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    return process.pid


def _resolve_worker_row(api_base: str, token: str, worker_code: str) -> dict[str, Any] | None:
    for row in _list_workers(api_base, token):
        if str(row.get("worker_code") or "").strip() == worker_code:
            return row
    return None


def _print_status(api_base: str | None, token: str | None, worker_code: str) -> int:
    pid = _read_pid()
    running = bool(pid and _pid_alive(pid))
    print(json.dumps(
        {
            "pid": pid,
            "process_running": running,
            "log_file": str(LOG_FILE),
            "worker_env": str(WORKER_ENV_PATH),
        },
        ensure_ascii=False,
        indent=2,
    ))
    if api_base and token:
        row = _resolve_worker_row(api_base, token, worker_code)
        if row:
            print(json.dumps({"api_worker": row}, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap and manage a local Vistral training worker.")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap = sub.add_parser("bootstrap", help="register worker, write worker.env, optionally start it")
    bootstrap.add_argument("--api-base", default="", help="Control plane API base, e.g. https://localhost:8443/api")
    bootstrap.add_argument("--username", default="platform_admin")
    bootstrap.add_argument("--password", default="platform123")
    bootstrap.add_argument("--worker-code", default="local-train-worker")
    bootstrap.add_argument("--worker-name", default="Local Train Worker")
    bootstrap.add_argument("--worker-host", default=socket.gethostname())
    bootstrap.add_argument("--labels", default=json.dumps(DEFAULT_LABELS, ensure_ascii=False))
    bootstrap.add_argument("--resources", default=json.dumps(DEFAULT_RESOURCES, ensure_ascii=False))
    bootstrap.add_argument("--start", action="store_true")
    bootstrap.add_argument("--restart", action="store_true")
    bootstrap.add_argument("--foreground", action="store_true")
    bootstrap.add_argument("--once", action="store_true")

    start = sub.add_parser("start", help="start local worker from existing worker.env")
    start.add_argument("--restart", action="store_true")
    start.add_argument("--foreground", action="store_true")
    start.add_argument("--once", action="store_true")

    sub.add_parser("stop", help="stop local worker process recorded in pid file")

    status = sub.add_parser("status", help="show local process and API worker state")
    status.add_argument("--api-base", default="")
    status.add_argument("--username", default="platform_admin")
    status.add_argument("--password", default="platform123")
    status.add_argument("--worker-code", default="local-train-worker")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "bootstrap":
        api_base = args.api_base.strip() or _detect_api_base()
        token = _login(api_base, args.username, args.password)
        labels = json.loads(args.labels)
        resources = json.loads(args.resources)
        worker = _register_worker(
            api_base,
            token,
            worker_code=args.worker_code.strip(),
            worker_name=args.worker_name.strip(),
            worker_host=args.worker_host.strip(),
            labels=labels,
            resources=resources,
        )
        bootstrap_token = str(worker.get("bootstrap_token") or "").strip()
        if not bootstrap_token:
            raise SystemExit("Worker register succeeded but bootstrap_token is missing")
        _write_worker_env(
            api_base=api_base,
            worker_code=args.worker_code.strip(),
            worker_token=bootstrap_token,
            worker_host=args.worker_host.strip(),
            labels=labels,
            resources=resources,
        )
        print(f"worker.env written to {WORKER_ENV_PATH}")
        print(f"worker_code={args.worker_code.strip()}")
        print(f"api_base={api_base}")
        if args.start:
            pid = _start_worker(once=args.once, foreground=args.foreground, restart=args.restart)
            if args.foreground:
                raise SystemExit(pid)
            print(f"worker started in background, pid={pid}")
            print(f"log={LOG_FILE}")
        else:
            print(f"next: bash {RUNNER_PATH} --once")
        return

    if args.command == "start":
        if not WORKER_ENV_PATH.exists():
            raise SystemExit(f"Missing {WORKER_ENV_PATH}. Run bootstrap first.")
        pid = _start_worker(once=args.once, foreground=args.foreground, restart=args.restart)
        if args.foreground:
            raise SystemExit(pid)
        print(f"worker started in background, pid={pid}")
        print(f"log={LOG_FILE}")
        return

    if args.command == "stop":
        stopped = _stop_worker()
        print("stopped" if stopped else "not_running")
        return

    if args.command == "status":
        api_base = args.api_base.strip() or _detect_api_base()
        token = _login(api_base, args.username, args.password)
        raise SystemExit(_print_status(api_base, token, args.worker_code.strip()))


if __name__ == "__main__":
    main()
