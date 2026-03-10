#!/usr/bin/env python3
"""Inspect or apply versioned schema migrations.

Default behavior prefers running inside the `vistral_backend` container so the
database URL and Python dependencies match the live backend runtime.

When `--apply` succeeds, the host-side `backend/app/db/schema.sql` snapshot is
synced automatically unless `--no-sync-schema` is set. This removes the extra
manual `schema_snapshot_guard.py --write` step from the common migration flow.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
CONTAINER_NAME = "vistral_backend"
SCHEMA_GUARD = ROOT / "docker" / "scripts" / "schema_snapshot_guard.py"


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


def _sync_schema_snapshot() -> int:
    result = subprocess.run([sys.executable, str(SCHEMA_GUARD), "--write"], check=False)
    return result.returncode


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect or apply database schema migrations and optionally sync schema.sql."
    )
    parser.add_argument("--apply", action="store_true", help="apply pending migrations before printing status")
    parser.add_argument(
        "--no-sync-schema",
        action="store_true",
        help="skip host-side backend/app/db/schema.sql sync after a successful --apply",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    forwarded_args = ["--apply"] if args.apply else []
    if _can_use_container():
        exit_code = _run_in_container(forwarded_args)
    else:
        exit_code = _run_local(forwarded_args)
    if exit_code == 0 and args.apply and not args.no_sync_schema:
        exit_code = _sync_schema_snapshot()
    raise SystemExit(exit_code)
