# Local backend setup (Windows, PostgreSQL)

Run commands from the `backend` directory. Use Python 3.13 and the locally
installed PostgreSQL server; Docker is not required.

## This machine

The native PostgreSQL 17.11 binaries and pgvector 0.8.7 are installed under
`%LOCALAPPDATA%\AMS\pgsql`. The database cluster is under
`%LOCALAPPDATA%\AMS\data`, outside the OneDrive project directory.

- Host: `127.0.0.1`, port: `5432`
- Database and application role: `ams`
- Application password: in the backend's ignored `.env`
- Local administrator credentials: `%LOCALAPPDATA%\AMS\local-credentials.json`
- PostgreSQL log: `%LOCALAPPDATA%\AMS\postgresql.log`
- pgAdmin connection: `AMS Local PostgreSQL`, using the dedicated `ams` role

If pgAdmin asks for the `ams` password, use `DB_PASSWORD` from the backend's
`.env`. This is the database login; create a separate Django application login
with `createsuperuser` below.

PostgreSQL runs as your Windows user, rather than as an automatically starting
Windows service. After reboot, start it from the backend directory:

```powershell
.\scripts\local-postgres.ps1 start
.\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Use `.\scripts\local-postgres.ps1 status` to check the database or
`.\scripts\local-postgres.ps1 stop` to shut it down. Starting it again while
it is already running is safe.

The database is newly created; the existing SQLite backup has not been
imported. To create your application login, run
`.\venv\Scripts\python.exe manage.py createsuperuser`.

Installation sources: [PostgreSQL Windows binaries from EDB](https://www.enterprisedb.com/download-postgresql-binaries)
and [pgvector's Windows build instructions](https://github.com/pgvector/pgvector#windows).
pgvector is installed in both `ams` and `template1` so Django can also create
working test databases without granting the application role superuser access.

## Python environment

```powershell
py -3.13 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.lock.txt
```

Alternatively, with uv installed:

```powershell
uv venv --python 3.13 venv
uv pip install --python venv\Scripts\python.exe -r requirements.lock.txt
```

Copy `.env.example` to `.env` if `.env` does not already exist. Generate a
unique `SECRET_KEY` and fill in the PostgreSQL connection details. `.env` is
ignored by Git. PostgreSQL is always used. For local HTTP access, set
`DEBUG=True`, `COOKIE_SECURE=False`, `ALLOWED_HOSTS=localhost,127.0.0.1`, and
set `FRONTEND_URL`, CORS and CSRF origins to the local frontend URLs.
When starting from the HTTPS example, also set `SECURE_SSL_REDIRECT=False`,
`SECURE_HSTS_SECONDS=0`, `TRUST_PROXY_HTTPS_HEADER=False`, and clear
`COOKIE_DOMAIN` for localhost. The current local `.env` already uses local values.

## PostgreSQL database

Start the existing PostgreSQL server. Using pgAdmin or `psql` as a database
administrator, create a dedicated role and empty database if needed (replace
the example password before running):

```sql
CREATE ROLE ams LOGIN PASSWORD 'choose-a-local-password' CREATEDB;
CREATE DATABASE ams OWNER ams;
```

`CREATEDB` lets Django create and remove its separate `test_ams` database
during tests. Use the matching role/password in `.env`. Do not point local
development at a production database.

The existing `inventory.0057_item_hybrid_search` migration requires the
**pgvector server extension**, even when `ITEM_SEARCH_HYBRID_ENABLED=False`.
The Python `pgvector` package alone does not install this extension. Install
pgvector for your PostgreSQL server version, then connect to the `ams`
database as a database administrator and run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

For Django's PostgreSQL tests, pgvector must also be available in new test
databases (for example, provision the extension in `template1` as an
administrator). The migration creates it automatically only when the
connecting role has sufficient permissions.

## Verify and run

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py createsuperuser
.\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

The frontend runs at `http://localhost:3000`. Optional AI and document
extraction features need their own API keys; leave those entries blank until
configured. For application tests on the local PostgreSQL server:

```powershell
.\venv\Scripts\python.exe manage.py test
```

PostgreSQL is the only configured backend. See [deployment.md](deployment.md)
for the server handoff and the deployment-oriented `.env.example`.

Install `requirements-dev.txt` to run the complete test suite (includes the PDF test dependency).
