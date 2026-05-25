from django.core.management.base import BaseCommand, CommandError

from ams.database_backups import restore_backup


class Command(BaseCommand):
    help = "Restore a verified development database backup."

    def add_arguments(self, parser):
        parser.add_argument("backup_id", help="Backup id to restore.")
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required. Confirms replacement of the active development database.",
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.WARNING(
                "Restore replaces the active SQLite database. Stop the Django dev server before running this."
            )
        )
        try:
            result = restore_backup(options["backup_id"], confirm=options["confirm"])
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"Database restore failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Restored backup {result['backup_id']}."))
        self.stdout.write(f"Restored database: {result['restored_to']}")
        self.stdout.write(f"Rollback backup: {result['rollback_backup']}")
