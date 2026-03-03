#!/usr/bin/env python3
"""Run release gate and archive structured reports."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
QUALITY_GATE = ROOT / "docker" / "scripts" / "quality_gate.sh"
PARITY = ROOT / "docker" / "scripts" / "parity_regression.py"
REPORT_DIR_DEFAULT = ROOT / "docs" / "qa" / "reports"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_report_stem(ts: datetime) -> str:
    return ts.strftime("go_no_go_%Y%m%d_%H%M%S")


def _try_git_info() -> dict[str, str]:
    info: dict[str, str] = {}
    try:
        commit = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True, stderr=subprocess.DEVNULL)
            .strip()
        )
        info["commit"] = commit
        short = (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True, stderr=subprocess.DEVNULL)
            .strip()
        )
        info["short_commit"] = short
    except Exception:
        pass
    return info


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)


def _parse_json_stdout(stdout: str) -> dict[str, Any]:
    content = stdout.strip()
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Try parse from the last JSON object.
        start = content.rfind("\n{")
        if start >= 0:
            return json.loads(content[start + 1 :])
        if content.startswith("{"):
            return json.loads(content)
        raise


def run_gate(wait_seconds: int) -> tuple[int, dict[str, Any]]:
    started_at = _utc_now()
    report: dict[str, Any] = {
        "status": "failed",
        "meta": {
            "started_at": started_at.isoformat(),
            "wait_seconds": wait_seconds,
            "api_base": os.getenv("PARITY_API_BASE", "http://localhost:8000"),
        },
        "steps": {},
    }
    report["meta"].update(_try_git_info())

    # Step 1: quality gate.
    quality = _run(["bash", str(QUALITY_GATE)], cwd=ROOT)
    report["steps"]["quality_gate"] = {
        "exit_code": quality.returncode,
        "stdout_tail": quality.stdout.splitlines()[-120:],
        "stderr_tail": quality.stderr.splitlines()[-120:],
    }
    if quality.returncode != 0:
        report["status"] = "no-go"
        report["error"] = "quality_gate_failed"
        report["meta"]["finished_at"] = _utc_now().isoformat()
        return 2, report

    # Step 2: parity regression.
    parity = _run(["python3", str(PARITY), "--wait-seconds", str(wait_seconds)], cwd=ROOT)
    parity_json: dict[str, Any] = {}
    parse_error = ""
    try:
        parity_json = _parse_json_stdout(parity.stdout)
    except Exception as exc:
        parse_error = str(exc)

    report["steps"]["parity_regression"] = {
        "exit_code": parity.returncode,
        "stdout_tail": parity.stdout.splitlines()[-120:],
        "stderr_tail": parity.stderr.splitlines()[-120:],
        "parsed_json": parity_json if parity_json else None,
        "parse_error": parse_error or None,
    }
    if parity.returncode != 0:
        report["status"] = "no-go"
        report["error"] = "parity_regression_failed"
        report["meta"]["finished_at"] = _utc_now().isoformat()
        return 2, report

    report["status"] = "go"
    report["meta"]["finished_at"] = _utc_now().isoformat()
    return 0, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run GO/NO-GO release gate and archive report")
    parser.add_argument("--wait-seconds", type=int, default=120, help="parity polling timeout")
    parser.add_argument("--report-dir", type=str, default=str(REPORT_DIR_DEFAULT), help="report output directory")
    args = parser.parse_args()

    code, report = run_gate(wait_seconds=args.wait_seconds)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_report_stem(_utc_now())
    report_path = report_dir / f"{stem}.json"
    latest_path = report_dir / "latest_go_no_go.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(report_path, latest_path)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[report] {report_path}")
    print(f"[report-latest] {latest_path}")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
