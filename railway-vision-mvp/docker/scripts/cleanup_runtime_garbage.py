from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.db.models import DataAsset, InferenceResult, ModelRecord  # noqa: E402


def _resolve_runtime_path(raw: str | None) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    path = Path(text)
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([REPO_ROOT / path, Path("/app") / path])
    elif str(path).startswith("/app/"):
        relative = path.relative_to("/app")
        candidates.append(REPO_ROOT / relative)
        if relative.parts[:2] == ("app", "uploads"):
            candidates.append(REPO_ROOT / "backend" / relative)
        if relative.parts[:2] == ("app", "models_repo"):
            candidates.append(REPO_ROOT / "backend" / relative)
        if relative.parts and relative.parts[0] == "demo_data":
            candidates.append(REPO_ROOT / relative)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[-1].resolve()


def _git_tracked_paths() -> set[Path]:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        check=True,
        capture_output=True,
        text=False,
    )
    tracked: set[Path] = set()
    for entry in result.stdout.decode("utf-8", errors="ignore").split("\x00"):
        cleaned = entry.strip()
        if cleaned:
            tracked.add((REPO_ROOT / cleaned).resolve())
    return tracked


def _referenced_runtime_paths() -> set[Path]:
    session = SessionLocal()
    try:
        referenced: set[Path] = set()
        for storage_uri, in session.query(DataAsset.storage_uri).all():
            resolved = _resolve_runtime_path(storage_uri)
            if resolved:
                referenced.add(resolved)
        for screenshot_uri, in session.query(InferenceResult.screenshot_uri).all():
            resolved = _resolve_runtime_path(screenshot_uri)
            if resolved:
                referenced.add(resolved)
        for encrypted_uri, signature_uri, manifest_uri in session.query(
            ModelRecord.encrypted_uri,
            ModelRecord.signature_uri,
            ModelRecord.manifest_uri,
        ).all():
            for raw in (encrypted_uri, signature_uri, manifest_uri):
                resolved = _resolve_runtime_path(raw)
                if resolved:
                    referenced.add(resolved)
        return referenced
    finally:
        session.close()


def _prune_empty_dirs(paths: set[Path], *, stop: Path) -> int:
    removed = 0
    for path in sorted(paths, key=lambda item: len(item.parts), reverse=True):
        current = path
        while current != stop and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            removed += 1
            current = current.parent
    return removed


def _remove_path(path: Path, *, apply: bool) -> bool:
    if not path.exists():
        return False
    if not apply:
        return True
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def collect_cleanup_plan() -> dict[str, list[Path]]:
    settings = get_settings()
    tracked = _git_tracked_paths()
    referenced = _referenced_runtime_paths()
    asset_repo = Path(settings.asset_repo_path).resolve()
    model_repo = Path(settings.model_repo_path).resolve()

    plan: dict[str, list[Path]] = {
        "macos_metadata": sorted(REPO_ROOT.rglob(".DS_Store")),
        "python_caches": sorted(REPO_ROOT.rglob("__pycache__")),
        "tmp_runtime": [REPO_ROOT / "tmp"] if (REPO_ROOT / "tmp").exists() else [],
        "qa_reports": sorted((REPO_ROOT / "docs" / "qa" / "reports").glob("*.json")),
        "unreferenced_uploads": [],
        "unreferenced_models": [],
    }

    for root_key, root_path in (("unreferenced_uploads", asset_repo), ("unreferenced_models", model_repo)):
        if not root_path.exists():
            continue
        for file_path in sorted(path for path in root_path.rglob("*") if path.is_file()):
            resolved = file_path.resolve()
            if resolved in tracked or resolved in referenced:
                continue
            if file_path.name == ".gitkeep":
                continue
            plan[root_key].append(file_path)
    return plan


def execute_cleanup(plan: dict[str, list[Path]], *, apply: bool) -> dict[str, object]:
    settings = get_settings()
    asset_repo = Path(settings.asset_repo_path).resolve()
    model_repo = Path(settings.model_repo_path).resolve()
    removed_dirs: set[Path] = set()
    deleted: dict[str, int] = {}

    for category, paths in plan.items():
        count = 0
        for path in paths:
            if _remove_path(path, apply=apply):
                count += 1
                parent = path.parent if path.is_file() else path
                if parent.exists():
                    removed_dirs.add(parent)
        deleted[category] = count

    empty_dirs_removed = 0
    if apply:
        empty_dirs_removed += _prune_empty_dirs(removed_dirs, stop=asset_repo) if asset_repo.exists() else 0
        empty_dirs_removed += _prune_empty_dirs(removed_dirs, stop=model_repo) if model_repo.exists() else 0

    return {
        "apply": apply,
        "deleted": deleted,
        "empty_dirs_removed": empty_dirs_removed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean repo-local runtime garbage without touching tracked or DB-referenced files.")
    parser.add_argument("--apply", action="store_true", help="Actually delete files instead of printing a dry-run summary.")
    args = parser.parse_args()

    plan = collect_cleanup_plan()
    summary = execute_cleanup(plan, apply=args.apply)
    summary["candidates"] = {key: [str(path.relative_to(REPO_ROOT)) for path in value] for key, value in plan.items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
