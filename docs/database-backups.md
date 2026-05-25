# Database Backups

AMS uses SQLite in development and PostgreSQL in production. The development
backup commands are real operational tooling for the local SQLite database, but
they are not a replacement for PostgreSQL WAL/PITR in production.

## Development SQLite Commands

Create a backup:

```powershell
python manage.py backup_database --label "before stock workflow test"
```

List backups:

```powershell
python manage.py list_database_backups
```

Verify a backup:

```powershell
python manage.py verify_database_backup ams-sqlite-YYYYMMDD-HHMMSS
```

Restore a backup:

```powershell
python manage.py restore_database_backup ams-sqlite-YYYYMMDD-HHMMSS --confirm
```

Stop the Django development server before restoring. Restore replaces
`db.sqlite3`, creates a `pre-restore-YYYYMMDD-HHMMSS.sqlite3` rollback file, and
runs Django system checks afterward.

Backups are stored in `backups/database/` under the backend directory. This path
is ignored by Git and should stay out of source control.

## What Each Backup Contains

Each backup creates:

- `ams-sqlite-YYYYMMDD-HHMMSS.sqlite3`
- `ams-sqlite-YYYYMMDD-HHMMSS.metadata.json`

The metadata records the source database path, database engine, Django
environment, file size, SHA-256 checksum, creation timestamp, and migration
state summary.

Verification checks:

- backup file exists,
- SHA-256 checksum matches metadata,
- SQLite `PRAGMA integrity_check` returns `ok`,
- whether the `django_migrations` table is present.

## Production PostgreSQL Target

For production on your own server or container, use PostgreSQL-specific tooling
instead of the SQLite commands:

- pgBackRest or Barman for base backups and retention,
- continuous WAL archiving for point-in-time recovery,
- encrypted offsite backup storage,
- immutable or offline backup copies,
- scheduled restore drills,
- alerts for failed backups, failed WAL archiving, and stale restore points.

The intended production pattern is full/base backups plus WAL archiving. That
allows restoring to a specific time before accidental deletion, corruption, or an
attack. SQLite development backups prove the operator workflow, but SQLite does
not provide PostgreSQL-style WAL/PITR recovery.
