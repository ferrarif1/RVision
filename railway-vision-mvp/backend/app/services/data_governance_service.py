from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


FILE_ROOT = Path(__file__).resolve()
SCRIPT_ROOT_CANDIDATES = [
    FILE_ROOT.parents[3] / "docker" / "scripts",
    FILE_ROOT.parents[2] / "docker" / "scripts",
    Path("/app/docker/scripts"),
]


def _script_path(script_name: str) -> Path:
    path = next((root / script_name for root in SCRIPT_ROOT_CANDIDATES if (root / script_name).exists()), None)
    if path is None:
        raise RuntimeError(f"Unable to locate maintenance script: {script_name}")
    return path


def _run_script(script_name: str, *args: str) -> dict[str, Any]:
    path = _script_path(script_name)
    proc = subprocess.run(
        [sys.executable, str(path), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        stdout = proc.stdout.strip()
        raise RuntimeError(stderr or stdout or f"{script_name} exited with code {proc.returncode}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - safety
        raise RuntimeError(f"{script_name} returned invalid JSON output") from exc


def _slice_rows(rows: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    return [dict(row) for row in (rows or [])[:limit]]


def preview_keep_demo_chain() -> dict[str, Any]:
    plan = _run_script("cleanup_keep_current_demo_chain.py")
    summary = dict(plan.get("summary") or {})
    return {
        "action": "keep_demo_chain",
        "title": "只保留当前车号演示主链",
        "summary": summary,
        "keep_preview": {
            "models": _slice_rows((plan.get("keep") or {}).get("models") or []),
            "training_jobs": _slice_rows((plan.get("keep") or {}).get("training_jobs") or []),
            "assets": _slice_rows((plan.get("keep") or {}).get("assets") or []),
            "pipelines": _slice_rows((plan.get("keep") or {}).get("pipelines") or []),
        },
        "delete_preview": {
            "models": _slice_rows((plan.get("delete") or {}).get("models") or []),
            "training_jobs": _slice_rows((plan.get("delete") or {}).get("training_jobs") or []),
            "assets": _slice_rows((plan.get("delete") or {}).get("assets") or []),
            "dataset_versions": _slice_rows((plan.get("delete") or {}).get("dataset_versions") or []),
        },
    }


def execute_keep_demo_chain() -> dict[str, Any]:
    result = _run_script("cleanup_keep_current_demo_chain.py", "--apply")
    return {
        "action": "keep_demo_chain",
        "result": result,
    }


def preview_cleanup_synthetic_runtime() -> dict[str, Any]:
    summary = _run_script("cleanup_synthetic_runtime_records.py")
    return {
        "action": "cleanup_synthetic_runtime",
        "title": "清理 synthetic 运行残留",
        "summary": summary,
    }


def execute_cleanup_synthetic_runtime() -> dict[str, Any]:
    summary = _run_script("cleanup_synthetic_runtime_records.py", "--apply")
    return {
        "action": "cleanup_synthetic_runtime",
        "result": summary,
    }


def preview_prune_ocr_exports(*, keep_latest: int) -> dict[str, Any]:
    summary = _run_script("prune_old_car_number_export_assets.py", "--keep-latest", str(max(int(keep_latest), 1)))
    rows = summary.get("rows") or []
    return {
        "action": "prune_ocr_exports",
        "title": "裁剪旧 OCR 导出历史",
        "summary": {key: value for key, value in summary.items() if key != "rows"},
        "rows_preview": _slice_rows(rows, limit=8),
    }


def execute_prune_ocr_exports(*, keep_latest: int) -> dict[str, Any]:
    summary = _run_script("prune_old_car_number_export_assets.py", "--keep-latest", str(max(int(keep_latest), 1)), "--apply")
    return {
        "action": "prune_ocr_exports",
        "result": summary,
    }


def build_data_governance_preview(*, keep_latest: int = 3) -> dict[str, Any]:
    return {
        "keep_demo_chain": preview_keep_demo_chain(),
        "cleanup_synthetic_runtime": preview_cleanup_synthetic_runtime(),
        "prune_ocr_exports": preview_prune_ocr_exports(keep_latest=keep_latest),
    }
