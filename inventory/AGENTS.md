# INVENTORY DOMAIN KNOWLEDGE BASE

## OVERVIEW
Largest backend subsystem. Heavy model graph, many view modules, shared queryset scoping, and a large signal hub.

## STRUCTURE
```text
inventory/
├── models/       # split model files, imported via __init__
├── serializers/  # split serializer files per subdomain
├── views/        # split DRF view modules + shared utils
├── signals.py    # cross-cutting side effects / auto-creation / movement history
├── urls.py       # mounts inventory endpoints
└── management/commands/ # custom management commands, if any
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Row-level visibility | `views/utils.py` | `ScopedViewSetMixin` |
| Root endpoint wiring | `urls.py` | API surface summary |
| Auto side effects | `signals.py` | high-risk, high-coupling file |
| Location hierarchy | `models/location_model.py` | hierarchy logic |
| Movement / stock history | `signals.py`, `models/history_model.py`, `views/history_views.py` | side effects span files |

## CONVENTIONS
- Models, serializers, and views are split by file, then reassembled by package imports.
- Shared view security/scoping lives in `views/utils.py`, not duplicated per viewset.
- Location hierarchy and store rules are core to many operations; check location helpers before changing filters.

## ANTI-PATTERNS
- Do not edit `signals.py` casually; it coordinates auto-created stores, movement history, and dedupe logic.
- Do not bypass `ScopedViewSetMixin` when adding inventory endpoints that expose location-bound data.
- Do not create return loops or duplicate movement-history side effects.
- Do not assume stores/standalones are interchangeable; hierarchy rules are explicit and nontrivial.

## UNIQUE STYLES
- Business rules live partly in model helpers, partly in signals, partly in view scoping.
- Central-role bypasses exist in scoped query logic (`Central Store Manager`, specific perms).
- Avoid reintroducing database seed/bootstrap commands without an explicit project decision.

## COMMANDS
```bash
python manage.py test inventory
```

## NOTES
- Complexity hotspot: `signals.py` is >600 lines and should be read before any inventory side-effect change.
- Frontend currently depends on user/role/admin flows more than inventory, but inventory still dominates backend complexity.
