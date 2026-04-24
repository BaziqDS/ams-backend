"""DRF permission classes for the user_management module.

These enforce the domain-named permissions declared in UserProfile.Meta.permissions
(see also backend/ams/permissions_manifest.py for the admin-facing abstraction).

Keep enforcement here keyed to domain verbs (view / create / edit / delete),
NOT Django's auto-generated add/change/delete — those are for admin internals.
"""
from rest_framework import permissions


_UNSET = object()


def _has_perm(user, codename: str) -> bool:
    """Check either a direct user permission or a group permission."""
    dotted = codename if "." in codename else f"user_management.{codename}"
    return user.has_perm(dotted)


class UserAccountPermission(permissions.BasePermission):
    """Gates /api/users/management/ and /api/users/profiles/."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True

        if request.method in permissions.SAFE_METHODS:
            return (
                _has_perm(user, "user_management.view_user_accounts")
                or _has_perm(user, "user_management.view_all_user_accounts")
            )
        if request.method == "POST":
            return _has_perm(user, "user_management.create_user_accounts")
        if request.method in {"PUT", "PATCH"}:
            return _has_perm(user, "user_management.edit_user_accounts")
        if request.method == "DELETE":
            return _has_perm(user, "user_management.delete_user_accounts")
        return False


class RolePermission(permissions.BasePermission):
    """Gates /api/users/groups/.

    Assigning a permission set to a role requires the separate
    `assign_permissions_to_roles` capability on top of the create/edit perm.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True

        if request.method in permissions.SAFE_METHODS:
            return _has_perm(user, "user_management.view_roles")

        if request.method == "POST":
            if not _has_perm(user, "user_management.create_roles"):
                return False
            # If the caller is assigning permissions (either via raw
            # `permissions` or manifest `module_selections`), also require
            # the separate sub-capability.
            if request.data.get("permissions") or request.data.get("module_selections"):
                return _has_perm(user, "user_management.assign_permissions_to_roles")
            return True

        if request.method in {"PUT", "PATCH"}:
            if not _has_perm(user, "user_management.edit_roles"):
                return False
            perms_provided = request.data.get("permissions", _UNSET)
            modules_provided = request.data.get("module_selections", _UNSET)
            if perms_provided is _UNSET and modules_provided is _UNSET:
                return True
            return _has_perm(user, "user_management.assign_permissions_to_roles")

        if request.method == "DELETE":
            return _has_perm(user, "user_management.delete_roles")

        return False


class AvailableRolePermissionsPermission(permissions.BasePermission):
    """Gates /api/users/available-permissions/ — only role-permission assigners see the catalog."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return _has_perm(user, "user_management.assign_permissions_to_roles")
