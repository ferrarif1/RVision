#!/usr/bin/env python3
"""Cleanup safe runtime housekeeping artifacts.

Targets:
- old QA report json files under docs/qa/reports (keeps latest aliases)
- stale temporary upload files under backend/app/uploads matching .upload-*
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT / "docs" / "qa" / "reports"
UPLOADS_DIR = ROOT / "backend" / "app" / "uploads"
KEEP_REPORT_NAMES = {
    "latest_go_no_go.json",
    "training_control_plane_latest.json",
    "runtime_hardening_latest.json",
}


@dataclass
class CleanupCandidate:
    path: Path
    kind: str
    age_seconds: int


def _age_seconds(path: Path) -> int:
    return max(0, int(time.time() - path.stat().st_mtime))


def _find_report_candidates(retention_days: int) -> list[CleanupCandidate]:
    if not REPORTS_DIR.exists():
        return []
    max_age = retention_days * 24 * 3600
    candidates: list[CleanupCandidate] = []
    for path in REPORTS_DIR.glob("*.json"):
        if path.name in KEEP_REPORT_NAMES:
            continue
        age_seconds = _age_seconds(path)
        if age_seconds >= max_age:
            candidates.append(CleanupCandidate(path=path, kind="qa_report", age_seconds=age_seconds))
    return sorted(candidates, key=lambda item: item.path.name)


def _find_temp_upload_candidates(retention_hours: int) -> list[CleanupCandidate]:
    if not UPLOADS_DIR.exists():
        return []
    max_age = retention_hours * 3600
    candidates: list[CleanupCandidate] = []
    for path in UPLOADS_DIR.glob(".upload-*"):
        if not path.is_file():
            continue
        age_seconds = _age_seconds(path)
        if age_seconds >= max_age:
            candidates.append(CleanupCandidate(path=path, kind="temp_upload", age_seconds=age_seconds))
    return sorted(candidates, key=lambda item: item.path.name)


def _render_summary(candidates: list[CleanupCandidate], apply: bool) -> dict:
    summary = {
        "mode": "apply" if apply else "dry-run",
        "generated_at": int(time.time()),
        "count": len(candidates),
        "items": [
            {
                "kind": item.kind,
                "path": str(item.path),
                "age_seconds": item.age_seconds,
            }
            for item in candidates
        ],
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup safe runtime housekeeping artifacts.")
    parser.add_argument("--reports-retention-days", type=int, default=14, help="delete dated QA reports older than N days")
    parser.add_argument("--temp-upload-retention-hours", type=int, default=6, help="delete .upload-* temp files older than N hours")
    parser.add_argument("--apply", action="store_true", help="actually delete files instead of dry-run output")
    args = parser.parse_args()

    candidates = _find_report_candidates(args.reports_retention_days)
    candidates.extend(_find_temp_upload_candidates(args.temp_upload_retention_hours))
    candidates.sort(key=lambda item: (item.kind, item.path.name))

    if args.apply:
        for item in candidates:
            item.path.unlink(missing_ok=True)

    print(json.dumps(_render_summary(candidates, args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
