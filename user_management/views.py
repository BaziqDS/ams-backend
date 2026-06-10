from rest_framework import viewsets, permissions, filters
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth.models import User, Permission, Group
from django.db.models import Count, Prefetch
from django.http import QueryDict

from .models import UserProfile
from .permissions import (
    AvailableRolePermissionsPermission,
    RolePermission,
    UserAccountPermission,
    _has_perm,
)
from .serializers import (
    GroupSerializer,
    UserManagementSerializer,
    UserProfileSerializer,
    UserSerializer,
)

# Fields a non-admin is allowed to change on their OWN record via the
# /api/users/management/ self-edit path. Keep this set tight — adding a
# field here means a regular user can self-assign it without admin perms.
SELF_EDIT_ALLOWED_FIELDS = frozenset({
    "first_name",
    "last_name",
    "email",
    "avatar",
})


def _visible_users_queryset(request_user):
    base_qs = (
        User.objects.all()
        .select_related("profile")
        .prefetch_related(
            "profile__assigned_locations",
            Prefetch(
                "user_permissions",
                queryset=Permission.objects.select_related("content_type"),
            ),
            Prefetch(
                "groups",
                queryset=Group.objects.prefetch_related(
                    Prefetch(
                        "permissions",
                        queryset=Permission.objects.select_related("content_type"),
                    )
                ),
            ),
        )
        .order_by("id")
    )
    if request_user.is_superuser:
        return base_qs
    has_user_view = (
        request_user.has_perm("user_management.view_user_accounts")
        or request_user.has_perm("user_management.view_all_user_accounts")
    )
    if not has_user_view:
        return base_qs.filter(id=request_user.id)
    try:
        profile = request_user.profile
    except UserProfile.DoesNotExist:
        return base_qs.filter(id=request_user.id)
    if profile.has_root_user_management_scope():
        return base_qs
    managed_locations = profile.get_user_management_locations()
    if managed_locations.exists():
        return base_qs.filter(
            profile__assigned_locations__in=managed_locations
        ).distinct()
    return base_qs.filter(id=request_user.id)


class UserProfileViewSet(viewsets.ModelViewSet):
    queryset = UserProfile.objects.all().select_related("user").prefetch_related("assigned_locations")
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated, UserAccountPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ["user__username", "employee_id"]

    def get_queryset(self):
        request_user = self.request.user
        base_qs = (
            UserProfile.objects.all()
            .select_related("user")
            .prefetch_related("assigned_locations")
            .order_by("id")
        )
        if request_user.is_superuser:
            return base_qs
        has_user_view = (
            request_user.has_perm("user_management.view_user_accounts")
            or request_user.has_perm("user_management.view_all_user_accounts")
        )
        if not has_user_view:
            return base_qs.filter(user=request_user)
        try:
            profile = request_user.profile
        except UserProfile.DoesNotExist:
            return base_qs.filter(user=request_user)
        if profile.has_root_user_management_scope():
            return base_qs
        managed_locations = profile.get_user_management_locations()
        if managed_locations.exists():
            return base_qs.filter(
                assigned_locations__in=managed_locations
            ).distinct()
        return base_qs.filter(user=request_user)


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserManagementSerializer
    permission_classes = [permissions.IsAuthenticated, UserAccountPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ["username", "email", "first_name", "last_name"]

    def get_queryset(self):
        return _visible_users_queryset(self.request.user)

    def partial_update(self, request, *args, **kwargs):
        """Override to sanitize input for non-admin self-edits.

        Background: the profile-settings modal in the topbar lets any user
        update their own name and avatar via PATCH. The permission class
        allows this (see UserAccountPermission), but we still need to
        prevent a regular user from escalating privileges by including
        fields like ``is_superuser`` or ``groups`` in the same request.
        Here we strip every field that isn't in ``SELF_EDIT_ALLOWED_FIELDS``
        when the requester is editing their own record without admin perms.
        Admins and superusers are unaffected.
        """
        instance = self.get_object()
        user = request.user
        is_admin = (
            user.is_superuser
            or _has_perm(user, "user_management.edit_user_accounts")
        )
        if instance.pk == user.pk and not is_admin:
            sanitized = self._restrict_to_self_edit_fields(request.data)
            serializer = self.get_serializer(
                instance, data=sanitized, partial=True,
            )
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
            return Response(serializer.data)
        return super().partial_update(request, *args, **kwargs)

    @staticmethod
    def _restrict_to_self_edit_fields(data):
        """Return a copy of `data` containing only the safe self-edit fields.

        Handles both QueryDict (multipart upload — what the avatar form
        sends) and plain dict (JSON). Preserves the original type so the
        downstream serializer parses files correctly.
        """
        if isinstance(data, QueryDict):
            clean = QueryDict("", mutable=True)
            for key in data.keys():
                if key in SELF_EDIT_ALLOWED_FIELDS:
                    clean.setlist(key, data.getlist(key))
            return clean
        # Plain dict / Mapping
        return {k: v for k, v in data.items() if k in SELF_EDIT_ALLOWED_FIELDS}


class GroupViewSet(viewsets.ModelViewSet):
    queryset = (
        Group.objects.all()
        .select_related("role_metadata", "role_metadata__created_by")
        .prefetch_related(
            Prefetch(
                "permissions",
                queryset=Permission.objects.select_related("content_type"),
                to_attr="prefetched_permissions",
            )
        )
        .annotate(
            permission_count=Count("permissions", distinct=True),
            user_count=Count("user", distinct=True),
        )
        .order_by("name", "id")
    )
    serializer_class = GroupSerializer
    permission_classes = [permissions.IsAuthenticated, RolePermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]


class AvailablePermissionsView(APIView):
    """Legacy endpoint — returns the raw Django permission catalog.

    Kept for the advanced/escape-hatch flow. New admin UI should render from
    /auth/capabilities/ manifest instead of listing individual permissions.
    """

    permission_classes = [permissions.IsAuthenticated, AvailableRolePermissionsPermission]

    def get(self, request):
        perms = list(
            Permission.objects.filter(
                content_type__app_label__in=["inventory", "user_management"]
            ).select_related("content_type")
        )
        data = [
            {
                "id": p.id,
                "name": p.name,
                "codename": p.codename,
                "app_label": p.content_type.app_label,
                "model": p.content_type.model,
            }
            for p in perms
        ]
        return Response(data)
