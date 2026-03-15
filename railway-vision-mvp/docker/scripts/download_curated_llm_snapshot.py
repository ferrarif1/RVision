#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def write_status(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download curated LLM snapshot with huggingface-cli")
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--target-dir", required=True)
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--revision", default="")
    args = parser.parse_args()

    repo_id = str(args.repo_id).strip()
    target_dir = Path(args.target_dir).resolve()
    status_path = Path(args.status_file).resolve()
    log_path = Path(args.log_file).resolve()
    revision = str(args.revision or "").strip()

    target_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    base_payload = {
        "repo_id": repo_id,
        "target_dir": str(target_dir),
        "status": "running",
        "started_at": now_iso(),
        "pid": 0,
        "log_file": str(log_path),
    }
    write_status(status_path, base_payload)

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
