"""Translate admin-facing module selections into concrete Django permissions.

Admins edit roles through a small UI: one radio per module (None/View/Manage/Full).
This service is the boundary that converts that selection into the Django
Permission rows attached to a Group.

Call `apply_module_selections(group, {"users": "manage", "roles": "view"})`
whenever the admin saves a role. The signal in user_management/signals.py then
expands each assigned permission into its implied set.
"""
from __future__ import annotations

from django.contrib.auth.models import Group, Permission

from ams.permissions_manifest import MODULES, READ_PERMS, INSPECTION_STAGE_PERMS


def resolve_selections_to_codenames(
    selections: dict[str, str | None],
    inspection_stages: list[str] | None = None,
) -> set[str]:
    """Return the flat set of dotted codenames implied by a module-selection map.

    If inspection_stages is provided and inspections is at "manage" level,
    only the listed stage permissions are added (not all four).
    """
    wanted: set[str] = set()
    for module, level in selections.items():
        if not level or level == "none":
            continue
        if module not in MODULES and module in READ_PERMS:
            if level != "view":
                raise ValueError(f"Unknown module/level: {module!r} / {level!r}")
            wanted.update(READ_PERMS[module])
            continue
        if module not in MODULES or level not in MODULES[module]:
            raise ValueError(f"Unknown module/level: {module!r} / {level!r}")
        spec = MODULES[module][level]
        wanted.update(spec["perms"])
        for dep in spec["reads"]:
            if dep in READ_PERMS:
                wanted.update(READ_PERMS[dep])

    if inspection_stages and selections.get("inspections") == "manage":
        for stage_key in inspection_stages:
            if stage_key in INSPECTION_STAGE_PERMS:
                wanted.add(INSPECTION_STAGE_PERMS[stage_key])
            if stage_key == "fill_central_register":
                wanted.update(MODULES["items"]["manage"]["perms"])
                for dep in MODULES["items"]["manage"]["reads"]:
                    if dep in READ_PERMS:
                        wanted.update(READ_PERMS[dep])
            if stage_key == "review_finance":
                wanted.update(MODULES["depreciation"]["manage"]["perms"])
                for dep in MODULES["depreciation"]["manage"]["reads"]:
                    if dep in READ_PERMS:
                        wanted.update(READ_PERMS[dep])

    return wanted


def codenames_to_permissions(dotted_codenames: set[str]) -> list[Permission]:
    out: list[Permission] = []
    for dotted in dotted_codenames:
        app_label, codename = dotted.split(".", 1)
        try:
            out.append(
                Permission.objects.get(
                    content_type__app_label=app_label,
                    codename=codename,
                )
            )
        except Permission.DoesNotExist as exc:
            raise RuntimeError(
                f"Permissions manifest references missing permission: {dotted}"
            ) from exc
    return out


def apply_module_selections(
    group: Group,
    selections: dict[str, str | None],
    inspection_stages: list[str] | None = None,
) -> None:
    """Set the group's permissions to exactly what the selections resolve to.

    Implied permissions are then added by the m2m_changed signal, so the final
    row count on the group may be larger than len(codenames) — that is expected.
    """
    codenames = resolve_selections_to_codenames(selections, inspection_stages)
    perms = codenames_to_permissions(codenames)
    group.permissions.set(perms)


def compute_inspection_stages_for_user(user) -> list[str]:
    """Return the list of inspection stage keys the user holds."""
    if not user or not user.is_authenticated:
        return []
    held = set(user.get_all_permissions())
    return [key for key, perm in INSPECTION_STAGE_PERMS.items() if perm in held]


def compute_inspection_stages_for_group(group: Group) -> list[str]:
    """Return the list of inspection stage keys assigned to a group."""
    held = {
        f"{p.content_type.app_label}.{p.codename}"
        for p in group.permissions.select_related("content_type")
    }
    return [key for key, perm in INSPECTION_STAGE_PERMS.items() if perm in held]


def compute_capabilities_for_user(user) -> dict[str, str | None]:
    """For a given user, compute their effective level in each manifest module.

    The highest level whose perms are all satisfied wins. If none match, the
    module is reported as None (i.e. no access).
    """
    from ams.permissions_manifest import LEVEL_ORDER

    if not user or not user.is_authenticated:
        return {module: None for module in MODULES}

    held = set(user.get_all_permissions())
    result: dict[str, str | None] = {}
    for module, levels in MODULES.items():
        current: str | None = None
        for level_name in LEVEL_ORDER:
            if level_name not in levels:
                continue
            required = set(levels[level_name]["perms"])
            if required.issubset(held):
                current = level_name
        result[module] = current
    return result
