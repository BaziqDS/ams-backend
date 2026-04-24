"""DRF permission classes for inventory endpoints."""
from rest_framework import permissions


def _has_perm(user, codename: str) -> bool:
    dotted = codename if "." in codename else f"inventory.{codename}"
    return user.has_perm(dotted)


class LocationPermission(permissions.BasePermission):
    """Domain-permission gate for /api/inventory/locations/."""

    def has_permission(self, request, view):  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True

        if request.method in permissions.SAFE_METHODS:
            return _has_perm(user, "inventory.view_locations")
        if request.method == "POST":
            return _has_perm(user, "inventory.create_locations")
        if request.method in {"PUT", "PATCH"}:
            return _has_perm(user, "inventory.edit_locations")
        if request.method == "DELETE":
            return _has_perm(user, "inventory.delete_locations")
        return False


class StockEntryPermission(permissions.BasePermission):
    """Compatibility gate mirroring prior stock-entry method checks."""

    def has_permission(self, request, view):  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True

        if request.method in permissions.SAFE_METHODS:
            return (
                _has_perm(user, "inventory.view_stockentry")
                or _has_perm(user, "inventory.add_stockentry")
                or _has_perm(user, "inventory.change_stockentry")
                or _has_perm(user, "inventory.delete_stockentry")
            )

        if request.method == "POST":
            action = getattr(view, "action", None)
            detail_actions = {"acknowledge", "cancel"}
            if action in detail_actions:
                return (
                    _has_perm(user, "inventory.change_stockentry")
                    or _has_perm(user, "inventory.add_stockentry")
                )
            return _has_perm(user, "inventory.add_stockentry")

        if request.method in {"PUT", "PATCH"}:
            return _has_perm(user, "inventory.change_stockentry")
        if request.method == "DELETE":
            return _has_perm(user, "inventory.delete_stockentry")
        return False


class CategoryPermission(permissions.BasePermission):
    """Domain-permission gate for /api/inventory/categories/."""

    def has_permission(self, request, view):  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True

        if request.method in permissions.SAFE_METHODS:
            return _has_perm(user, "inventory.view_categories")
        if request.method == "POST":
            return _has_perm(user, "inventory.create_categories")
        if request.method in {"PUT", "PATCH"}:
            return _has_perm(user, "inventory.edit_categories")
        if request.method == "DELETE":
            return _has_perm(user, "inventory.delete_categories")
        return False


class ItemPermission(permissions.BasePermission):
    """Domain-permission gate for /api/inventory/items/."""

    def has_permission(self, request, view):  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True

        if request.method in permissions.SAFE_METHODS:
            return _has_perm(user, "inventory.view_items")
        if request.method == "POST":
            return _has_perm(user, "inventory.create_items")
        if request.method in {"PUT", "PATCH"}:
            return _has_perm(user, "inventory.edit_items")
        if request.method == "DELETE":
            return _has_perm(user, "inventory.delete_items")
        return False


class ItemReadPermission(permissions.BasePermission):
    """Read-only companion gate for item-owned support endpoints."""

    def has_permission(self, request, view):  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if request.method in permissions.SAFE_METHODS:
            return _has_perm(user, "inventory.view_items")
        return False


class ItemInstancePermission(permissions.BasePermission):
    """Item module gate for instance reads plus controlled instance edits."""

    def has_permission(self, request, view):  # type: ignore[override]
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True

        if request.method in permissions.SAFE_METHODS:
            return _has_perm(user, "inventory.view_items")
        if request.method == "POST":
            return _has_perm(user, "inventory.create_items")
        if request.method in {"PUT", "PATCH"}:
            return (
                _has_perm(user, "inventory.edit_items")
                or _has_perm(user, "inventory.change_item_instance")
            )
        if request.method == "DELETE":
            return _has_perm(user, "inventory.delete_items")
        return False
