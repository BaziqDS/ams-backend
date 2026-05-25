import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from ams.database_backups import (
    calculate_sha256,
    create_sqlite_backup,
    list_backups,
    restore_backup,
    verify_backup,
)


def create_sqlite_database(path: Path, marker: str = "initial"):
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE django_migrations (id integer primary key, app text, name text, applied text)")
        connection.execute("CREATE TABLE sample_data (id integer primary key, marker text)")
        connection.execute("INSERT INTO django_migrations (app, name, applied) VALUES ('ams', '0001_initial', '')")
        connection.execute("INSERT INTO sample_data (marker) VALUES (?)", (marker,))
        connection.commit()
    finally:
        connection.close()


def read_marker(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT marker FROM sample_data ORDER BY id LIMIT 1").fetchone()[0]
    finally:
        connection.close()


class DatabaseBackupServiceTests(SimpleTestCase):
    def test_create_sqlite_backup_writes_database_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            db_path = base_dir / "db.sqlite3"
            create_sqlite_database(db_path)

            with override_settings(
                BASE_DIR=base_dir,
                ENVIRONMENT="development",
                IS_PRODUCTION=False,
                DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": db_path}},
            ):
                with patch("ams.database_backups.get_migration_state", return_value={"available": True, "count": 1}):
                    metadata = create_sqlite_backup(label="test backup")

            backup_path = Path(metadata["backup_file"])
            metadata_path = Path(metadata["metadata_file"])

            self.assertTrue(backup_path.exists())
            self.assertTrue(metadata_path.exists())
            self.assertEqual(metadata["label"], "test backup")
            self.assertEqual(metadata["sha256"], calculate_sha256(backup_path))
            self.assertEqual(read_marker(backup_path), "initial")

            persisted_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted_metadata["backup_id"], metadata["backup_id"])

    def test_verify_backup_rejects_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            db_path = base_dir / "db.sqlite3"
            create_sqlite_database(db_path)

            with override_settings(
                BASE_DIR=base_dir,
                ENVIRONMENT="development",
                IS_PRODUCTION=False,
                DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": db_path}},
            ):
                with patch("ams.database_backups.get_migration_state", return_value={"available": True, "count": 1}):
                    metadata = create_sqlite_backup()
                Path(metadata["backup_file"]).write_bytes(b"tampered")

                with self.assertRaisesMessage(CommandError, "checksum mismatch"):
                    verify_backup(metadata["backup_id"])

    def test_verify_backup_runs_integrity_check_and_reports_migrations_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            db_path = base_dir / "db.sqlite3"
            create_sqlite_database(db_path)

            with override_settings(
                BASE_DIR=base_dir,
                ENVIRONMENT="development",
                IS_PRODUCTION=False,
                DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": db_path}},
            ):
                with patch("ams.database_backups.get_migration_state", return_value={"available": True, "count": 1}):
                    metadata = create_sqlite_backup()
                verification = verify_backup(metadata["backup_id"])

            self.assertEqual(verification.integrity_check, "ok")
            self.assertTrue(verification.has_migration_table)

    def test_restore_backup_requires_confirm_and_creates_rollback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            db_path = base_dir / "db.sqlite3"
            create_sqlite_database(db_path, marker="before")

            with override_settings(
                BASE_DIR=base_dir,
                ENVIRONMENT="development",
                IS_PRODUCTION=False,
                DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": db_path}},
            ):
                with patch("ams.database_backups.get_migration_state", return_value={"available": True, "count": 1}):
                    metadata = create_sqlite_backup()

                connection = sqlite3.connect(db_path)
                try:
                    connection.execute("UPDATE sample_data SET marker = 'after'")
                    connection.commit()
                finally:
                    connection.close()
                self.assertEqual(read_marker(db_path), "after")

                with self.assertRaisesMessage(CommandError, "requires --confirm"):
                    restore_backup(metadata["backup_id"], confirm=False)

                with patch("ams.database_backups.management.call_command"):
                    result = restore_backup(metadata["backup_id"], confirm=True)

            rollback_path = Path(result["rollback_backup"])
            self.assertTrue(rollback_path.exists())
            self.assertEqual(read_marker(db_path), "before")
            self.assertEqual(read_marker(rollback_path), "after")

    def test_restore_backup_refuses_production_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            db_path = base_dir / "db.sqlite3"
            create_sqlite_database(db_path)

            with override_settings(
                BASE_DIR=base_dir,
                ENVIRONMENT="production",
                IS_PRODUCTION=True,
                DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": db_path}},
            ):
                with self.assertRaisesMessage(CommandError, "ENVIRONMENT=production"):
                    restore_backup("ams-sqlite-20990101-000000", confirm=True)

    def test_list_backups_reads_metadata_newest_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            db_path = base_dir / "db.sqlite3"
            create_sqlite_database(db_path)

            with override_settings(
                BASE_DIR=base_dir,
                ENVIRONMENT="development",
                IS_PRODUCTION=False,
                DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": db_path}},
            ):
                with patch("ams.database_backups.get_migration_state", return_value={"available": True, "count": 1}):
                    metadata = create_sqlite_backup()

                backups = list_backups()

            self.assertEqual(backups[0]["backup_id"], metadata["backup_id"])
