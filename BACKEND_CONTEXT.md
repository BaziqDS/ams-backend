# AMS Backend — Agent Context

> Self-contained brief for any agent picking up work in this project. Read this first.

## What this is

The **Asset Management System (AMS) Django backend**. A DRF-based JSON API serving the Next.js frontend (`../ams-frontend`) and providing the read-only SQL surface that the LangGraph copilot (`../langchain-agent-chat-openrouter`) queries.

- Django `5.2.8`, DRF `3.16`, SimpleJWT `5.5`, Djoser `2.3`
- Python project root: `ams/` (settings, root urls, custom auth)
- Dev DB: SQLite (`db.sqlite3`). Prod DB: PostgreSQL with `pgvector`.
- `ATOMIC_REQUESTS = True` in both DB modes.
- Default DRF permission: `IsAuthenticated` + cookie-JWT auth class.

## Apps

| Django app | Responsibility |
|---|---|
| `ams/` | Project config, settings, root urls, **cookie-JWT auth views** (`auth_views.py`, `cookie_auth.py`), capabilities endpoint, permissions manifest, database backup helpers |
| `inventory/` | **Largest domain.** Locations, categories, items + instances + batches, stock entries / registers / corrections / allocations, movement history, inspections (multi-stage), employees / persons, depreciation, maintenance. Has its own `AGENTS.md`. |
| `user_management/` | Users, groups, profiles, RBAC permission surface. Has `PERMISSIONS_RULES.md` describing the policy model. |
| `notifications/` | Notification models, signals → service → API for the frontend toast/inbox |
| `ai_assistant/` | Server-side AI helpers exposed under `/api/ai/` (prompts, service, views). Distinct from the external LangGraph copilot. |

## URL map

Mounted in `ams/urls.py`:

```
/admin/                       Django admin
/auth/cookie/login/           Cookie-JWT login   (sets httpOnly cookies)
/auth/cookie/refresh/         Cookie-JWT refresh
/auth/cookie/logout/          Cookie-JWT logout
/auth/capabilities/           What the current user is allowed to do (permission manifest)
/auth/                        Djoser user endpoints (incl. /auth/users/me/) + Djoser JWT
/api/users/                   user_management routers: profiles, management, groups, available-permissions
/api/inventory/               inventory routers (see below)
/api/notifications/           notifications router
/api/ai/                      ai_assistant views
/silk/                        django-silk profiler (only when ENABLE_SILK=True)
/media/                       served only when DEBUG (MEDIA_ROOT)
```

**`/api/inventory/` resources** (DRF DefaultRouter, all in `inventory/urls.py`):
`location-tags`, `locations`, `categories`, `items`, `distribution`, `stock-entries`, `stock-corrections`, `stock-allocations`, `inspections`, `employees`, `persons`, `item-instances`, `item-batches`, `movement-history`, `stock-registers`, `depreciation/{policies,assets,asset-classes,rates,runs,adjustments}`, `maintenance/{work-orders,plans,meter-readings}`.

## Inventory layout (the hotspot)

```
inventory/
├── models/        one file per aggregate: location, category, item, instance, batch,
│                  stockentry, stock_record, stock_register, correction, allocation,
│                  inspection, depreciation, maintenance, history, person
├── serializers/   matching one-file-per-aggregate set; this is the *frontend contract*
├── views/         matching one-file-per-aggregate ViewSets; scoped querysets + perms
├── services/      cross-aggregate business logic:
│                  deletion_policy.py, depreciation_service.py, embeddings.py,
│                  item_search.py, serial_import.py, stock_correction_service.py,
│                  stock_reconciliation_service.py
├── audit/         audit-log support
├── assets/        bundled static assets
├── permissions.py StrictDjangoModelPermissions + custom rules
├── signals.py     cross-model side effects
├── management/    custom manage.py commands
├── migrations/
└── tests_*.py     app-local pytest-discoverable tests (no central tree)
```

Multi-stage **inspection workflow**: DRAFT → STOCK_DETAILS → CENTRAL_REGISTER → FINANCE_REVIEW → FINAL_APPROVAL. Logic lives in `models/inspection_model.py`, `serializers/inspection_serializer.py`, `views/inspection_views.py`, plus a contract test `tests_inspection_scope_contract.py`.

## Auth model

- **Two auth surfaces:**
  - **Djoser** owns user lifecycle endpoints (`/auth/users/...`, `/auth/users/me/`).
  - **Custom cookie views** (`ams/auth_views.py` + `ams/cookie_auth.py`) own the session-like JWT flow: tokens issued as **httpOnly cookies** rather than bearer headers. This is the main web flow — don't refactor frontend calls toward `Authorization: Bearer ...`.
- `ams/capabilities_view.py` returns the user's allowed actions for the frontend to gate UI.
- `ams/permissions_manifest.py` is the authoritative list of permission codenames the frontend RBAC layer consumes.
- `user_management/permissions.py` + `inventory/permissions.py` enforce scoped queryset access (e.g., users only see their org's items). **Do not bypass `StrictDjangoModelPermissions` or the scoped queryset logic.**
- Production roles can be provisioned with `python provision_production_roles.py`.

## Configuration

Driven by `python-decouple` reading `.env`:

- `ENVIRONMENT` (`development` | `production`) — `IS_PRODUCTION` flips DEBUG, DB, CORS, cookie-secure
- `SECRET_KEY`, `ALLOWED_HOSTS`
- `ENABLE_SILK` — adds the django-silk profiler at `/silk/`
- DB env vars (sqlite path in dev, postgres + pgvector in prod)
- CORS allow-list via `django-cors-headers`

## Key dependencies

Beyond Django/DRF/Djoser/SimpleJWT:

| Package | Used for |
|---|---|
| `pgvector` + `pgvector` model fields | Embedding-based item search (`services/embeddings.py`, `services/item_search.py`) |
| `langchain`, `langchain-community`, `langchain-openrouter`, `langgraph`, `openai` | The Django-side `ai_assistant` app (not the external LangGraph monorepo) |
| `reportlab`, `qrcode`, `pillow` | PDF / QR generation (likely asset labels, inspection reports) |
| `social-auth-app-django`, `oauthlib` | Social login plumbing |
| `django-silk` | Optional profiling (gated by `ENABLE_SILK`) |
| `uvicorn`, `httpx` | ASGI + async outbound HTTP |

## Conventions and anti-patterns

- **DRF serializers are the frontend contract.** Update them before assuming a new client field exists.
- **Don't add bearer-header auth assumptions** — the web flow is httpOnly cookies.
- **Don't reintroduce DB seed/bootstrap scripts** without an explicit project decision (intentionally removed previously). Use `inventory/demo_population.py` / `tests_populate_demo_via_api.py` patterns instead.
- **Tests are app-local `tests*.py`**, not a central `tests/` tree. Discover with Django's test runner, not pytest collection rules.
- **Inventory has its own AGENTS.md** — read it before non-trivial inventory work. `user_management` has `PERMISSIONS_RULES.md`.
- `ATOMIC_REQUESTS=True` is on — handle DB exceptions deliberately; don't swallow `IntegrityError` mid-request.
- Don't ignore env-driven behavior in `ams/settings.py` (auth, CORS, DB, silk) when refactoring those areas.

## Commands

```bash
# Dev
python manage.py runserver           # http://localhost:8000
python manage.py migrate
python manage.py createsuperuser
python manage.py test                # discovers tests*.py in each app
python manage.py test inventory      # single app

# Operational
python provision_production_roles.py # seed production RBAC groups
```

## Deploy

Windows self-hosted via `.github/workflows/deploy.yml` — **NSSM + Waitress** on a Windows runner. Treat the workflow file as operationally important when touching anything that affects process startup, env loading, or static/media paths.

## Where to start, by task

| Task | Open this first |
|---|---|
| New / changed inventory field | `inventory/models/<aggregate>_model.py` → migration → `serializers/<aggregate>_serializer.py` → `views/<aggregate>_views.py` |
| Inspection workflow stage logic | `inventory/models/inspection_model.py`, `services/` files relevant to the stage, `views/inspection_views.py`, `tests_inspection_scope_contract.py` |
| Stock movement / correction | `inventory/services/stock_correction_service.py`, `stock_reconciliation_service.py`, `models/stockentry_model.py` |
| Depreciation run | `inventory/services/depreciation_service.py`, `models/depreciation_model.py` |
| Embedding / semantic item search | `inventory/services/embeddings.py`, `services/item_search.py`, `tests_item_hybrid_search.py` |
| Permission / RBAC change | `ams/permissions_manifest.py`, `ams/capabilities_view.py`, `user_management/permissions.py`, `inventory/permissions.py`, `user_management/PERMISSIONS_RULES.md` |
| Auth flow change | `ams/auth_views.py`, `ams/cookie_auth.py`, `ams/settings.py` (JWT + cookie + CORS sections) |
| Notification | `notifications/{models,signals,services,views,serializers}.py` |
| Server-side AI helper | `ai_assistant/{prompts,service,views}.py` |
