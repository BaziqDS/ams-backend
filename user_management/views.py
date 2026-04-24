from rest_framework import viewsets, permissions, filters
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth.models import User, Permission, Group

from .models import UserProfile
from .permissions import (
    AvailableRolePermissionsPermission,
    RolePermission,
    UserAccountPermission,
)
from .serializers import (
    GroupSerializer,
    UserManagementSerializer,
    UserProfileSerializer,
    UserSerializer,
)


def _visible_users_queryset(request_user):
    base_qs = (
        User.objects.all()
        .select_related("profile")
        .prefetch_related("user_permissions", "groups")
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


class GroupViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.all().prefetch_related("permissions")
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
        inventory_perms = Permission.objects.filter(content_type__app_label="inventory")
        user_mgmt_perms = Permission.objects.filter(content_type__app_label="user_management")
        perms = list(inventory_perms | user_mgmt_perms)
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
