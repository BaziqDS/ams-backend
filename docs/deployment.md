# Server configuration

AMS uses PostgreSQL everywhere. Configure each setting directly; the application
does not select settings based on a development/production mode.

## Backend

Copy `.env.example` to `.env` in the backend root, or supply the same values as
process environment variables (process values take precedence). Replace the
placeholder secret, database credentials and domains. Keep `DEBUG=False` for
the deployed application. `COOKIE_SECURE=True` requires browser access over
HTTPS and applies to JWT, session and CSRF cookies.

`ALLOWED_HOSTS` contains hostnames, without schemes. `FRONTEND_URL`,
`CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` use full origins with schemes
and any nonstandard ports. Multiple hosts/origins are comma-separated.

Provision PostgreSQL and install the pgvector server extension for its major
version. Create the AMS database and role, then enable `vector` in that
database as an administrator before migrations. pgvector is required by an
existing migration even when semantic search is disabled. The application
role needs schema/migration rights; it does not need to be a superuser.

For the server move, restore the existing PostgreSQL data with the operator's
normal backup/restore tooling and copy the existing `media/` directory. Retain
the current `SECRET_KEY` if existing signed tokens should stay valid. The
local database created during setup is empty and is not a production backup.

Install Python dependencies from `requirements.txt`, then run:

```text
python manage.py check --database default
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py check --deploy
```

Serve `ams.wsgi:application` with the server's WSGI host. The existing Windows
workflow uses Waitress and NSSM; `waitress` is installed separately by that
workflow. Configure the web server/reverse proxy for HTTPS, collected static
files (`staticfiles/`, URL `/static/`) and user uploads (`media/`, URL `/media/`).
Django's local file-serving helpers do not serve those paths with `DEBUG=False`.
Back up PostgreSQL and uploaded files using the server's operational tooling.

Optional assistant, serial extraction and semantic search settings are included
in `.env.example`; leave keys blank for features that are not being configured.
Do not change `EMBEDDING_DIM` without migrating the vector column to match.

The included GitHub workflow writes `.env` from repository secrets. If reusing
it, set its domains, database and secret values for the new server. HTTPS-only
cookies and the frontend URL as the default trusted CSRF origin apply even
when those optional settings are omitted. Optional integration values must
also be supplied if those features are needed.

## Frontend

Use `frontend/.env.example` as the reference for `frontend/.env.local`. Set the
public backend URL and, when used, the external copilot URL before running
`npm ci` and `npm run build`. Run the built application with `npm run start`.
The backend must also be reachable from the Next.js server for auth checks.

`NEXT_PUBLIC_*` values are included in the browser bundle during the build;
rebuild when changing them. Groq and Google Translate keys are server-only
runtime values and must not use the `NEXT_PUBLIC_` prefix. The external copilot
is a separate service, not included in these two project folders.

Next.js still uses its standard internal `NODE_ENV` for `next dev`, `next build`
and `next start`; there are no custom application branches based on that value.
The existing frontend workflow writes the backend URL from repository secrets;
include the copilot and optional voice values when configuring that workflow.
