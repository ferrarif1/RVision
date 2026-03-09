#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

BUNDLE_NAME = "vistral-training-worker"
DEPLOY_ROOT = Path(__file__).resolve().parent
REPO_ROOT = DEPLOY_ROOT.parents[1]
DEFAULT_OUTPUT_DIR = DEPLOY_ROOT / "dist" / BUNDLE_NAME

STATIC_FILES = (
    (DEPLOY_ROOT / "BUNDLE_README.md", Path("README.md")),
    (DEPLOY_ROOT / "requirements.txt", Path("requirements.txt")),
    (DEPLOY_ROOT / "worker.env.example", Path("worker.env.example")),
    (DEPLOY_ROOT / "run_worker.sh", Path("run_worker.sh")),
    (DEPLOY_ROOT / "keys" / "README.md", Path("keys/README.md")),
)

BUNDLE_FILES = (
    (REPO_ROOT / "docker" / "scripts" / "training_worker_runner.py", Path("training_worker_runner.py")),
    (REPO_ROOT / "backend" / "app" / "__init__.py", Path("backend/app/__init__.py")),
    (REPO_ROOT / "backend" / "app" / "core" / "__init__.py", Path("backend/app/core/__init__.py")),
    (REPO_ROOT / "backend" / "app" / "core" / "brand.py", Path("backend/app/core/brand.py")),
    (REPO_ROOT / "backend" / "app" / "services" / "__init__.py", Path("backend/app/services/__init__.py")),
    (REPO_ROOT / "backend" / "app" / "services" / "model_package_tool.py", Path("backend/app/services/model_package_tool.py")),
)


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)



def build_bundle(output_dir: Path) -> Path:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for src, relative_dst in STATIC_FILES + BUNDLE_FILES:
        if not src.exists():
            raise FileNotFoundError(f"required file not found: {src}")
        _copy_file(src, output_dir / relative_dst)

    run_script = output_dir / "run_worker.sh"
    run_script.chmod(0o755)

    return output_dir



def main() -> None:
    parser = argparse.ArgumentParser(description="Build standalone Vistral training worker bundle")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    output_dir = build_bundle(Path(args.output_dir).expanduser().resolve())
    print(f"bundle ready: {output_dir}")
    print("included files:")
    for path in sorted(output_dir.rglob("*")):
        if path.is_file():
            print(f"- {path.relative_to(output_dir)}")


if __name__ == "__main__":
    main()
