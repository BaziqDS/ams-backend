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

Install Python dependencies from `requirements.lock.txt`, then run:

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

## Security and provider changes (30 October 2026)

Use Python 3.13 and install `requirements.lock.txt` for the audited dependency
set. `requirements.txt` records the direct requirements; regenerate the lock
with `uv pip compile requirements.txt -o requirements.lock.txt` when updating.
For regression tests install `requirements-dev.txt`, then run
`python manage.py test --keepdb --noinput` against a dedicated local database.

Run migrations for `user_management.0010_voiceusage`. Voice quotas are enforced
in PostgreSQL across Next.js/Django workers; `VOICE_MINUTE_LIMIT` and
`VOICE_DAILY_LIMIT` default to 20 and 200 per user. Chat and voice require the
user's chatbot preference to be enabled. The internal assistant reads allowed
inventory API resources with that user's existing permissions and location
scope; it has no SQL tools or direct database connection.

Cookie-authenticated writes, login and refresh now require CSRF validation.
The browser gets a masked token from `/auth/cookie/csrf/` and sends
`X-CSRFToken`. Explicit bearer clients retain their existing contract. Access
tokens last 15 minutes, the frontend refreshes expired sessions, and logout
blacklists the presented refresh token. Already issued access tokens remain
valid until expiry (including older tokens issued before this rollout).

For separate trusted UI/API subdomains, configure `COOKIE_DOMAIN` to their
shared parent, e.g. `.example.com`; use an empty value when they share one host.
Set exact CORS and CSRF trusted origins. Enable `SECURE_SSL_REDIRECT` and HSTS
for HTTPS. Enable `TRUST_PROXY_HTTPS_HEADER` only when a trusted reverse proxy
overwrites `X-Forwarded-Proto` and direct untrusted access is blocked. Review
subdomain ownership before sharing authentication cookies. Keep the requested
local `admin/admin` account out of deployment.

If reusing the Windows workflow, set the new COOKIE_DOMAIN and HTTPS settings
as repository secrets. Its loopback health probe must match the server's
HTTPS/allowed-host configuration when redirects are enabled. This workflow
has not been executed during local remediation.

### Optional semantic index worker

Item saves update keyword search immediately and no longer wait for an
embedding provider. When `ITEM_SEARCH_HYBRID_ENABLED=True`, schedule this
command every minute using the server's scheduler (Task Scheduler, cron or a
service timer), from the backend directory with its environment loaded:

```text
python manage.py backfill_item_embeddings --batch-size 50
```

It skips unchanged indexed items, retries failed/missing vectors and takes a
PostgreSQL advisory lock so overlapping scheduled runs do not duplicate work.
Provider calls happen outside row locks; results are discarded if the item
changed meanwhile. Semantic results catch up on the next run. Keyword search
continues working when the worker or provider is unavailable. Run `--force`
after changing embedding models, retaining the configured vector dimension.

### Document serial extraction API

Text/pasted serial previews still return their normal response immediately.
PDF/image/DOCX previews now submit extraction without holding a web worker in
a polling loop. A processing response is HTTP 202 with `extraction_ticket`
and `Retry-After: 2`. Repost to the same preview endpoint after that delay,
using the same item/store/certificate context and the ticket instead of the
file. Repeat while 202; stop when the existing HTTP 200 preview is returned
or an error occurs. Tickets are signed, bound to the user, and expire after
10 minutes. Polls recheck current permissions and custody. Client requests
must carry CSRF headers. Preview never writes serial assignments; the separate
apply endpoint retains its validation and transaction rules. Submission calls
have individual 10-second network timeouts; provider completion runs remotely.
Any external client of the binary preview API must adopt this 202 contract.

Stock-entry lists now use `/api/inventory/stock-entries/movements/`, paginating
12 movements while keeping linked issue/receipt rows together. The original
stock-entry API remains available. Source inventory loads by store, and batches
and instances load by selected item. Notification summaries include `alerts`
so each background polling cycle requires one request; the alerts endpoint
remains available for existing consumers.
