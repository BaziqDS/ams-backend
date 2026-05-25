from django.core.management.base import BaseCommand, CommandError

from ams.database_backups import verify_backup


class Command(BaseCommand):
    help = "Verify a development database backup checksum and SQLite integrity."

    def add_arguments(self, parser):
        parser.add_argument("backup_id", help="Backup id, for example ams-sqlite-20260525-120000.")

    def handle(self, *args, **options):
        try:
            verification = verify_backup(options["backup_id"])
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"Backup verification failed: {exc}") from exc

        migration_status = "present" if verification.has_migration_table else "missing"
        self.stdout.write(self.style.SUCCESS(f"Backup {verification.backup_id} verified."))
        self.stdout.write("Checksum: ok")
        self.stdout.write(f"SQLite integrity_check: {verification.integrity_check}")
        self.stdout.write(f"django_migrations table: {migration_status}")
