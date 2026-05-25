from django.core.management.base import BaseCommand, CommandError

from ams.database_backups import create_sqlite_backup


class Command(BaseCommand):
    help = "Create a verified metadata-backed SQLite development database backup."

    def add_arguments(self, parser):
        parser.add_argument("--label", default="", help="Optional human-readable backup label.")

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.WARNING(
                "Creating a development SQLite backup. Stop the Django dev server before restore operations."
            )
        )
        try:
            metadata = create_sqlite_backup(label=options["label"])
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"Database backup failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Created backup {metadata['backup_id']}"))
        self.stdout.write(f"Database file: {metadata['backup_file']}")
        self.stdout.write(f"Metadata file: {metadata['metadata_file']}")
        self.stdout.write(f"SHA-256: {metadata['sha256']}")
