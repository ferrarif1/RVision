import argparse
import json

from app.services.schema_migration_service import list_migration_status, run_schema_migrations


def _render_status() -> dict:
    rows = list_migration_status()
    return {
        "count": len(rows),
        "applied_count": sum(1 for row in rows if row.applied),
        "pending_count": sum(1 for row in rows if not row.applied),
        "items": [
            {
                "version": row.version,
                "filename": row.filename,
                "checksum": row.checksum,
                "applied": row.applied,
            }
            for row in rows
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or apply database schema migrations.")
    parser.add_argument("--apply", action="store_true", help="apply pending migrations before printing status")
    args = parser.parse_args()

    if args.apply:
        run_schema_migrations()
    print(json.dumps(_render_status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
