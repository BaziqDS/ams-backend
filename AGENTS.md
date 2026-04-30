# BACKEND KNOWLEDGE BASE

## OVERVIEW
Django 5.2 + DRF backend. Cookie-JWT auth, Djoser user endpoints, inventory + user-management apps.

## STRUCTURE
```text
backend/
├── ams/              # project config, auth, root urls, cookie auth
├── inventory/        # largest domain: models, serializers, views, signals
├── user_management/  # users, groups/roles, profiles, permission surfaces
├── manage.py         # local entry point
└── .github/workflows/ # Windows self-hosted deploy flow
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Root routing | `ams/urls.py` | auth + app mounts |
| Auth flow | `ams/auth_views.py`, `ams/cookie_auth.py` | cookie login/refresh/logout |
| Global config | `ams/settings.py` | env, DB, DRF, JWT, CORS |
| Inventory rules | `inventory/` | see local AGENTS for hotspot details |
| User/group API | `user_management/views.py`, `serializers.py`, `urls.py` | frontend contract source |

## CONVENTIONS
- Auth default is `IsAuthenticated` plus cookie JWT auth class in settings.
- Frontend-facing schema lives in DRF serializers; update them before assuming client fields.
- Development DB is sqlite; production DB is postgres.
- `ATOMIC_REQUESTS=True` is enabled in both DB modes.
- User/role APIs live under `/api/users/`; inventory under `/api/inventory/`.

## ANTI-PATTERNS
- Do not bypass `StrictDjangoModelPermissions` or scoped queryset logic casually.
- Do not assume bearer-header auth is the main web flow; the app uses httpOnly cookie endpoints.
- Do not add frontend-only fields without serializer support.
- Do not ignore environment-driven behavior in `ams/settings.py` when changing auth/CORS/DB code.

## UNIQUE STYLES
- Custom auth is split: Djoser for user endpoints, custom cookie views for session-like JWT flow.
- Avoid reintroducing database seed/bootstrap scripts without an explicit project decision.
- Tests are app-local `tests.py` modules, not a centralized pytest tree.

## COMMANDS
```bash
python manage.py runserver
python manage.py test
python manage.py migrate
```

## NOTES
- `user_management` is the main frontend contract surface for admin pages.
- `inventory` has the highest complexity/churn and gets its own child AGENTS file.
- `backend/.github/workflows/deploy.yml` is operationally important: Windows + NSSM + Waitress.
