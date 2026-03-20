#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_ollama_root(base_url: str) -> str:
    clean = str(base_url or "").strip().rstrip("/")
    if clean.endswith("/v1"):
        clean = clean[:-3].rstrip("/")
    return clean


def ollama_model_ready(base_url: str, runtime_model: str) -> bool:
    model_name = str(runtime_model or "").strip()
    if not model_name:
        return False
    req = urllib.request.Request(f"{normalize_ollama_root(base_url)}/api/tags", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    models = payload.get("models") if isinstance(payload, dict) else []
    names = {str(item.get("name") or "").strip() for item in models if isinstance(item, dict)}
    return model_name in names


def run_ollama_pull(*, status_path: Path, log_path: Path, base_payload: dict, base_url: str, runtime_model: str) -> int:
    request_body = json.dumps({"name": runtime_model, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        f"{normalize_ollama_root(base_url)}/api/pull",
        data=request_body,
        headers={"Content-Type": "application/json"},
    )
    latest_downloaded = 0
    latest_total = 0
    event_error = ""
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{now_iso()}] start ollama pull {runtime_model}\n")
        running_payload = dict(base_payload)
        running_payload["pid"] = 0
        write_status(status_path, running_payload)
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    log_file.write(f"{line}\n")
                    log_file.flush()
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    if str(event.get("error") or "").strip():
                        event_error = str(event.get("error") or "").strip()
                        failed_payload = dict(base_payload)
                        failed_payload.update(
                            {
                                "status": "failed",
                                "finished_at": now_iso(),
                                "error": event_error,
                                "downloaded_bytes": latest_downloaded,
                                "total_bytes": latest_total,
                                "runtime_ready": False,
                            }
                        )
                        write_status(status_path, failed_payload)
                        return 1
                    latest_downloaded = int(event.get("completed") or latest_downloaded or 0)
                    latest_total = int(event.get("total") or latest_total or 0)
                    progress_pct = 0
                    if latest_total > 0:
                        progress_pct = max(0, min(100, int((latest_downloaded / latest_total) * 100)))
                    status_text = str(event.get("status") or "running").strip() or "running"
                    payload = dict(running_payload)
                    payload.update(
                        {
                            "status": "running",
                            "progress_pct": progress_pct,
                            "progress_label": f"{progress_pct}%" if latest_total > 0 else status_text,
                            "downloaded_bytes": latest_downloaded,
                            "total_bytes": latest_total,
                            "runtime_ready": False,
                            "detail": status_text,
                        }
                    )
                    write_status(status_path, payload)
        except Exception as exc:
            failed_payload = dict(base_payload)
            failed_payload.update(
                {
                    "status": "failed",
                    "finished_at": now_iso(),
                    "error": str(exc),
                    "downloaded_bytes": latest_downloaded,
                    "total_bytes": latest_total,
                    "runtime_ready": False,
                }
            )
            write_status(status_path, failed_payload)
            return 1

    runtime_ready = ollama_model_ready(base_url, runtime_model)
    if not runtime_ready:
        failed_payload = dict(base_payload)
        failed_payload.update(
            {
                "status": "failed",
                "finished_at": now_iso(),
                "error": f"{runtime_model} 未出现在运行时模型列表中",
                "downloaded_bytes": latest_downloaded,
                "total_bytes": latest_total,
                "runtime_ready": False,
            }
        )
        write_status(status_path, failed_payload)
        return 1

    succeeded_payload = dict(base_payload)
    succeeded_payload.update(
        {
            "status": "succeeded",
            "finished_at": now_iso(),
            "downloaded_bytes": latest_downloaded,
            "total_bytes": latest_total,
            "progress_pct": 100,
            "progress_label": "已完成",
            "runtime_ready": runtime_ready,
        }
    )
    write_status(status_path, succeeded_payload)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Download curated LLM snapshot with huggingface-cli")
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--target-dir", required=True)
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--revision", default="")
    parser.add_argument("--strategy", default="huggingface")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--runtime-model", default="")
    args = parser.parse_args()

    repo_id = str(args.repo_id).strip()
    target_dir = Path(args.target_dir).resolve()
    status_path = Path(args.status_file).resolve()
    log_path = Path(args.log_file).resolve()
    revision = str(args.revision or "").strip()
    strategy = str(args.strategy or "huggingface").strip() or "huggingface"
    base_url = str(args.base_url or "").strip()
    runtime_model = str(args.runtime_model or "").strip()

    target_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    base_payload = {
        "repo_id": repo_id,
        "target_dir": str(target_dir),
        "status": "running",
        "started_at": now_iso(),
        "pid": 0,
        "log_file": str(log_path),
        "strategy": strategy,
        "runtime_model_name": runtime_model,
        "base_url": base_url,
    }
    write_status(status_path, base_payload)

    if strategy == "ollama":
        if not base_url or not runtime_model:
            failed_payload = dict(base_payload)
            failed_payload.update({"status": "failed", "finished_at": now_iso(), "error": "missing ollama runtime config"})
            write_status(status_path, failed_payload)
            return 1
        return run_ollama_pull(
            status_path=status_path,
            log_path=log_path,
            base_payload=base_payload,
            base_url=base_url,
            runtime_model=runtime_model,
        )

    cmd = ["huggingface-cli", "download", repo_id, "--local-dir", str(target_dir), "--resume-download"]
    if revision:
        cmd.extend(["--revision", revision])

    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{now_iso()}] start download {repo_id}\n")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
        running_payload = dict(base_payload)
        running_payload["pid"] = proc.pid
        write_status(status_path, running_payload)
        try:
            code = proc.wait()
        except KeyboardInterrupt:
            proc.send_signal(signal.SIGTERM)
            raise

    final_payload = dict(running_payload)
    final_payload["finished_at"] = now_iso()
    if code == 0:
        final_payload["status"] = "succeeded"
    else:
        final_payload["status"] = "failed"
        final_payload["exit_code"] = code
    write_status(status_path, final_payload)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
