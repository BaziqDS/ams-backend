import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core import checks, management
from django.core.management.base import CommandError
from django.db import connections
from django.utils import timezone


BACKUP_DIR = "backups/database"
BACKUP_PREFIX = "ams-sqlite"
METADATA_SUFFIX = ".metadata.json"


@dataclass(frozen=True)
class BackupVerification:
    backup_id: str
    database_path: Path
    metadata_path: Path
    checksum_matches: bool
    integrity_check: str
    has_migration_table: bool
    metadata: dict


def get_backup_root() -> Path:
    return Path(settings.BASE_DIR) / BACKUP_DIR


def get_default_database() -> dict:
    return settings.DATABASES["default"]


def get_database_engine() -> str:
    return get_default_database()["ENGINE"]


def is_sqlite_database() -> bool:
    return get_database_engine() == "django.db.backends.sqlite3"


def require_sqlite_database() -> Path:
    if not is_sqlite_database():
        raise CommandError(
            "Only SQLite development backups are currently supported. "
            "Production PostgreSQL should use pgBackRest/Barman with WAL archiving."
        )
    name = get_default_database()["NAME"]
    db_path = Path(name)
    if not db_path.exists():
        raise CommandError(f"SQLite database does not exist: {db_path}")
    return db_path


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_migration_state() -> dict:
    default_connection = connections["default"]
    try:
        with default_connection.cursor() as cursor:
            cursor.execute("SELECT app, name FROM django_migrations ORDER BY app, name")
            migrations = [f"{app}.{name}" for app, name in cursor.fetchall()]
    except Exception as exc:
        return {"available": False, "error": str(exc), "count": 0, "migrations": []}

    return {
        "available": True,
        "count": len(migrations),
        "migrations": migrations,
    }


def create_sqlite_backup(label: str = "") -> dict:
    source_path = require_sqlite_database()
    backup_root = get_backup_root()
    backup_root.mkdir(parents=True, exist_ok=True)

    created_at = timezone.now()
    backup_id = f"{BACKUP_PREFIX}-{created_at.strftime('%Y%m%d-%H%M%S')}"
    backup_path = backup_root / f"{backup_id}.sqlite3"
    metadata_path = backup_root / f"{backup_id}{METADATA_SUFFIX}"

    source = sqlite3.connect(source_path)
    try:
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()

    checksum = calculate_sha256(backup_path)
    metadata = {
        "backup_id": backup_id,
        "label": label,
        "created_at": created_at.isoformat(),
        "database_engine": get_database_engine(),
        "source_database_path": str(source_path),
        "backup_file": str(backup_path),
        "metadata_file": str(metadata_path),
        "sha256": checksum,
        "file_size_bytes": backup_path.stat().st_size,
        "django_environment": getattr(settings, "ENVIRONMENT", "unknown"),
        "migration_state": get_migration_state(),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return metadata


def list_backups() -> list[dict]:
    backup_root = get_backup_root()
    if not backup_root.exists():
        return []

    backups = []
    for metadata_path in sorted(backup_root.glob(f"*{METADATA_SUFFIX}"), reverse=True):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metadata = {
                "backup_id": metadata_path.name.removesuffix(METADATA_SUFFIX),
                "metadata_file": str(metadata_path),
                "metadata_error": "Invalid JSON metadata.",
            }
        backups.append(metadata)
    return backups


def resolve_backup_metadata(backup_id: str) -> tuple[Path, dict]:
    backup_root = get_backup_root()
    metadata_path = backup_root / f"{backup_id}{METADATA_SUFFIX}"
    if not metadata_path.exists():
        raise CommandError(f"Backup metadata not found for '{backup_id}'.")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CommandError(f"Backup metadata is not valid JSON: {metadata_path}") from exc

    return metadata_path, metadata


def verify_backup(backup_id: str) -> BackupVerification:
    metadata_path, metadata = resolve_backup_metadata(backup_id)
    backup_path = Path(metadata.get("backup_file", ""))
    if not backup_path.exists():
        raise CommandError(f"Backup database file not found: {backup_path}")

    actual_checksum = calculate_sha256(backup_path)
    expected_checksum = metadata.get("sha256")
    if actual_checksum != expected_checksum:
        raise CommandError(
            f"Backup checksum mismatch for '{backup_id}'. "
            f"Expected {expected_checksum}, got {actual_checksum}."
        )

    connection = sqlite3.connect(backup_path)
    try:
        integrity_check = connection.execute("PRAGMA integrity_check").fetchone()[0]
        has_migration_table = (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'django_migrations'"
            ).fetchone()
            is not None
        )
    finally:
        connection.close()

    if integrity_check != "ok":
        raise CommandError(f"SQLite integrity check failed for '{backup_id}': {integrity_check}")

    return BackupVerification(
        backup_id=backup_id,
        database_path=backup_path,
        metadata_path=metadata_path,
        checksum_matches=True,
        integrity_check=integrity_check,
        has_migration_table=has_migration_table,
        metadata=metadata,
    )


def restore_backup(backup_id: str, confirm: bool = False) -> dict:
    if getattr(settings, "ENVIRONMENT", "development") == "production" or getattr(settings, "IS_PRODUCTION", False):
        raise CommandError("Refusing to restore a database while ENVIRONMENT=production.")
    if not confirm:
        raise CommandError("Restore requires --confirm because it replaces the active development database.")

    target_path = require_sqlite_database()
    verification = verify_backup(backup_id)

    created_at = timezone.now()
    rollback_path = get_backup_root() / f"pre-restore-{created_at.strftime('%Y%m%d-%H%M%S')}.sqlite3"
    rollback_path.parent.mkdir(parents=True, exist_ok=True)
    connections.close_all()
    shutil.copy2(target_path, rollback_path)
    shutil.copy2(verification.database_path, target_path)
    connections.close_all()

    check_errors = checks.run_checks()
    if check_errors:
        messages = "; ".join(str(error) for error in check_errors)
        raise CommandError(f"Django system checks failed after restore: {messages}")
    management.call_command("check", verbosity=0)

    return {
        "backup_id": backup_id,
        "restored_to": str(target_path),
        "rollback_backup": str(rollback_path),
    }
