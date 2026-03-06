#!/usr/bin/env python3
import argparse
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT_DIR / "backend" / "app" / "db" / "migrations" / "versions"
SCHEMA_PATH = ROOT_DIR / "backend" / "app" / "db" / "schema.sql"


def _migration_files() -> list[Path]:
    return sorted(path for path in MIGRATIONS_DIR.glob("*.sql") if path.is_file())


def _latest_snapshot_migration() -> Path:
    files = _migration_files()
    if not files:
        raise RuntimeError(f"no migration files found under {MIGRATIONS_DIR}")

    snapshot_files = [path for path in files if "schema" in path.stem or "snapshot" in path.stem]
    if not snapshot_files:
        raise RuntimeError(
            "no snapshot migration found; add a *_schema.sql or *_snapshot.sql migration before syncing schema.sql"
        )

    latest_snapshot = snapshot_files[-1]
    latest_migration = files[-1]
    if latest_snapshot != latest_migration:
        raise RuntimeError(
            "latest migration is not a snapshot migration; refresh the schema snapshot migration before release"
        )
    return latest_snapshot


def _normalized_bytes(path: Path) -> bytes:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    if not data.endswith(b"\n"):
        data += b"\n"
    return data


def check_snapshot() -> Path:
    source = _latest_snapshot_migration()
    if _normalized_bytes(source) != _normalized_bytes(SCHEMA_PATH):
        raise RuntimeError(
            f"schema snapshot drift detected: {SCHEMA_PATH.relative_to(ROOT_DIR)} "
            f"does not match {source.relative_to(ROOT_DIR)}"
        )
    print(
        "[ok] schema snapshot is in sync:",
        f"{SCHEMA_PATH.relative_to(ROOT_DIR)} == {source.relative_to(ROOT_DIR)}",
    )
    return source


def write_snapshot() -> None:
    source = _latest_snapshot_migration()
    SCHEMA_PATH.write_bytes(_normalized_bytes(source))
    print(
        "[ok] schema snapshot updated:",
        f"{SCHEMA_PATH.relative_to(ROOT_DIR)} <- {source.relative_to(ROOT_DIR)}",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Check or sync backend/app/db/schema.sql from snapshot migrations.")
    parser.add_argument(
        "--write",
        action="store_true",
        help="overwrite backend/app/db/schema.sql with the latest snapshot migration",
    )
    args = parser.parse_args()

    if args.write:
        write_snapshot()
        return

    check_snapshot()


if __name__ == "__main__":
    main()
