from django.core.management.base import BaseCommand

from ams.database_backups import list_backups


class Command(BaseCommand):
    help = "List available development database backups."

    def handle(self, *args, **options):
        backups = list_backups()
        if not backups:
            self.stdout.write("No database backups found.")
            return

        for backup in backups:
            backup_id = backup.get("backup_id", "<unknown>")
            created_at = backup.get("created_at", "<unknown>")
            size = backup.get("file_size_bytes", "<unknown>")
            environment = backup.get("django_environment", "<unknown>")
            label = backup.get("label") or ""
            label_suffix = f" [{label}]" if label else ""
            self.stdout.write(f"{backup_id}{label_suffix} | {created_at} | {size} bytes | {environment}")
