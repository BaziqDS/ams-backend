"""GET /auth/capabilities/ — the frontend's single source of truth for what the
logged-in user can see and do.

Returns:
    {
      "modules": { "users": "manage", "roles": "view", ... },
      "is_superuser": true|false,
      "manifest": {
        "<module>": ["view", "manage", "full"],
        ...
      }
    }

The `manifest` field exposes the level names per module so the role-edit UI can
render the same radio groups the backend understands — without the frontend
hardcoding the shape.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ams.permissions_manifest import MODULES, INSPECTION_STAGE_PERMS, ALL_INSPECTION_STAGE_KEYS
from user_management.services.capability_service import (
    compute_capabilities_for_user,
    compute_inspection_stages_for_user,
)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def capabilities(request):
    modules = compute_capabilities_for_user(request.user)
    manifest = {module: list(levels.keys()) for module, levels in MODULES.items()}
    dependencies = {
        module: {
            level: [dep for dep in spec.get("reads", []) if dep in MODULES]
            for level, spec in levels.items()
            if any(dep in MODULES for dep in spec.get("reads", []))
        }
        for module, levels in MODULES.items()
    }
    return Response(
        {
            "modules": modules,
            "is_superuser": bool(request.user.is_superuser),
            "manifest": manifest,
            "dependencies": dependencies,
            "inspection_stages": {
                "available": ALL_INSPECTION_STAGE_KEYS,
                "held": compute_inspection_stages_for_user(request.user),
            },
        }
    )
