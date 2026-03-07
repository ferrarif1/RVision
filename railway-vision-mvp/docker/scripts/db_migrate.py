#!/usr/bin/env python3
"""Inspect or apply versioned schema migrations.

Default behavior prefers running inside the `vistral_backend` container so the
database URL and Python dependencies match the live backend runtime.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
CONTAINER_NAME = "vistral_backend"


def _can_use_container() -> bool:
    if not shutil.which("docker"):
        return False
    probe = subprocess.run(
        ["docker", "exec", "-w", "/app", CONTAINER_NAME, "true"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return probe.returncode == 0


def _run_in_container(args: list[str]) -> int:
    result = subprocess.run(
        ["docker", "exec", "-w", "/app", CONTAINER_NAME, "python", "-m", "app.db.migration_cli", *args],
        check=False,
    )
    return result.returncode


def _run_local(args: list[str]) -> int:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from app.db.migration_cli import main as local_main  # noqa: E402

    sys.argv = [sys.argv[0], *args]
    local_main()
    return 0


if __name__ == "__main__":
    forwarded_args = sys.argv[1:]
    if _can_use_container():
        raise SystemExit(_run_in_container(forwarded_args))
    raise SystemExit(_run_local(forwarded_args))
