# pyright: reportAttributeAccessIssue=false, reportCallIssue=false, reportGeneralTypeIssues=false, reportArgumentType=false
"""Signals that enforce permission-implication semantics.

Two rules are applied whenever a permission is added to a User or a Group:

1. **Raw Django CRUD implication.** Granting add_X / change_X / delete_X on any
   model implies view_X on that same model (same content_type). This is what
   lets the admin UI work: a user with `add_user` can also open the user list.

2. **Explicit domain-perm implications.** A hand-maintained map of domain-level
   implications (e.g. `create_user_accounts` implies `view_user_accounts`).
   Extend this map when new modules join the manifest.

The signal listens on both User.user_permissions and Group.permissions m2m
relations, so the rules fire identically whether an admin edits a user directly
or — more commonly — edits a Group/role.
"""
from django.contrib.auth.models import Group, Permission, User
from django.db import transaction
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

from .models import UserProfile


# codename -> [implied codenames, ...] within the SAME content_type
EXPLICIT_PERMISSION_IMPLICATIONS: dict[str, list[str]] = {
    # User-accounts module
    "view_all_user_accounts": ["view_user_accounts"],
    "create_user_accounts": ["view_user_accounts"],
    "edit_user_accounts": ["view_user_accounts"],
    "delete_user_accounts": ["view_user_accounts"],
    "assign_user_locations": ["view_user_accounts"],
    "assign_user_roles": ["view_user_accounts"],
    # Roles module
    "create_roles": ["view_roles"],
    "edit_roles": ["view_roles"],
    "delete_roles": ["view_roles"],
    "assign_permissions_to_roles": ["view_roles"],
    # Locations module
    "create_locations": ["view_locations"],
    "edit_locations": ["view_locations"],
    "delete_locations": ["view_locations"],
    # Categories module
    "create_categories": ["view_categories"],
    "edit_categories": ["view_categories"],
    "delete_categories": ["view_categories"],
    # Items module
    "create_items": ["view_items"],
    "edit_items": ["view_items"],
    "delete_items": ["view_items"],
    # Stock entries module
    "create_stock_entries": ["view_stock_entries"],
    "edit_stock_entries": ["view_stock_entries"],
    "delete_stock_entries": ["view_stock_entries"],
    # Stock registers module
    "create_stock_registers": ["view_stock_registers"],
    "edit_stock_registers": ["view_stock_registers"],
    "delete_stock_registers": ["view_stock_registers"],
}


def _implied_codenames_for(permission: Permission) -> set[str]:
    implied: set[str] = set(EXPLICIT_PERMISSION_IMPLICATIONS.get(permission.codename, ()))
    if permission.codename.startswith(("add_", "change_", "delete_")):
        implied.add(f"view_{permission.codename.split('_', 1)[1]}")
    return implied


def _add_implied_permissions(target, relation_name: str, pk_set) -> None:
    """target is a User or Group; relation_name is 'user_permissions' or 'permissions'."""
    relation = getattr(target, relation_name)
    new_ids: list[int] = []

    for perm in Permission.objects.filter(pk__in=pk_set):
        for implied_codename in _implied_codenames_for(perm):
            if relation.filter(
                codename=implied_codename,
                content_type=perm.content_type,
            ).exists():
                continue
            try:
                implied = Permission.objects.get(
                    codename=implied_codename,
                    content_type=perm.content_type,
                )
            except Permission.DoesNotExist:
                continue
            new_ids.append(implied.id)

    if new_ids:
        relation.add(*new_ids)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, "profile"):
        instance.profile.save()


@receiver(m2m_changed, sender=User.user_permissions.through)
def enforce_user_permission_implications(sender, instance, action, reverse, pk_set, **kwargs):
    if action == "post_add" and not reverse and pk_set:
        with transaction.atomic():
            _add_implied_permissions(instance, "user_permissions", pk_set)


@receiver(m2m_changed, sender=Group.permissions.through)
def enforce_group_permission_implications(sender, instance, action, reverse, pk_set, **kwargs):
    if action == "post_add" and not reverse and pk_set:
        with transaction.atomic():
            _add_implied_permissions(instance, "permissions", pk_set)
