import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from app.db.database import engine

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "db" / "migrations" / "versions"


@dataclass(frozen=True)
class MigrationStatus:
    version: str
    filename: str
    checksum: str
    applied: bool


def _ensure_schema_migrations_table() -> None:
    statement = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version VARCHAR(128) PRIMARY KEY,
        filename VARCHAR(255) NOT NULL,
        checksum VARCHAR(64) NOT NULL,
        applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """
    with engine.begin() as conn:
        conn.execute(text(statement))


def _migration_files() -> list[Path]:
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted(path for path in MIGRATIONS_DIR.glob("*.sql") if path.is_file())


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _applied_versions() -> dict[str, tuple[str, str]]:
    _ensure_schema_migrations_table()
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT version, filename, checksum FROM schema_migrations ORDER BY version")).all()
    return {row.version: (row.filename, row.checksum) for row in rows}


def list_migration_status() -> list[MigrationStatus]:
    applied = _applied_versions()
    payload: list[MigrationStatus] = []
    for path in _migration_files():
        version = path.stem
        checksum = _checksum(path)
        applied_row = applied.get(version)
        if applied_row and applied_row[1] != checksum:
            raise RuntimeError(
                f"migration checksum mismatch for {version}: recorded={applied_row[1]} current={checksum}"
            )
        payload.append(
            MigrationStatus(
                version=version,
                filename=path.name,
                checksum=checksum,
                applied=version in applied,
            )
        )
    return payload


def _apply_single_migration(path: Path, checksum: str) -> None:
    sql_text = path.read_text(encoding="utf-8")
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cursor:
            cursor.execute(sql_text)
            cursor.execute(
                """
                INSERT INTO schema_migrations(version, filename, checksum)
                VALUES (%s, %s, %s)
                """,
                (path.stem, path.name, checksum),
            )
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def run_schema_migrations() -> list[MigrationStatus]:
    _ensure_schema_migrations_table()
    applied = _applied_versions()
    for path in _migration_files():
        version = path.stem
        checksum = _checksum(path)
        applied_row = applied.get(version)
        if applied_row:
            if applied_row[1] != checksum:
                raise RuntimeError(
                    f"migration checksum mismatch for {version}: recorded={applied_row[1]} current={checksum}"
                )
            continue
        _apply_single_migration(path, checksum)
        applied[version] = (path.name, checksum)
    return list_migration_status()
