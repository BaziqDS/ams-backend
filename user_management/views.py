from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth.models import User, Permission, Group
from django.db.models import Q
from .models import UserProfile
from .serializers import UserProfileSerializer, UserManagementSerializer, UserSerializer, GroupSerializer
from ams.permissions import StrictDjangoModelPermissions

class UserProfileViewSet(viewsets.ModelViewSet):
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]
    filter_backends = [filters.SearchFilter]
    search_fields = ['user__username', 'employee_id']

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.has_perm('user_management.view_all_user_accounts'):
            return UserProfile.objects.all()
        
        if user.has_perm('user_management.view_user_accounts_assigned_location'):
            try:
                managed_locations = user.profile.get_descendant_locations()
                return UserProfile.objects.filter(
                    assigned_locations__in=managed_locations
                ).distinct()
            except UserProfile.DoesNotExist:
                return UserProfile.objects.none()
        
        return UserProfile.objects.filter(user=user)

class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserManagementSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]
    filter_backends = [filters.SearchFilter]
    search_fields = ['username', 'email', 'first_name', 'last_name']

    def get_queryset(self):
        user = self.request.user
        base_qs = User.objects.all().select_related('profile').prefetch_related('user_permissions', 'groups')
        
        if user.is_superuser or user.has_perm('user_management.view_all_user_accounts'):
            return base_qs
            
        if user.has_perm('user_management.view_user_accounts_assigned_location'):
            try:
                managed_locations = user.profile.get_descendant_locations()
                return base_qs.filter(
                    profile__assigned_locations__in=managed_locations
                ).distinct()
            except UserProfile.DoesNotExist:
                return base_qs.none()
                
        return base_qs.filter(id=user.id)

class GroupViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.all().prefetch_related('permissions')
    serializer_class = GroupSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']

class AvailablePermissionsView(APIView):
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]

    def get(self, request):
        # We only care about inventory model permissions for now
        inventory_perms = Permission.objects.filter(content_type__app_label='inventory')
        user_mgmt_perms = Permission.objects.filter(content_type__app_label='user_management')
        
        # Include custom permissions if needed, or just all from these apps
        perms = list(inventory_perms | user_mgmt_perms)
        
        data = [
            {
                'id': p.id,
                'name': p.name,
                'codename': p.codename,
                'app_label': p.content_type.app_label,
                'model': p.content_type.model
            }
            for p in perms
        ]
        return Response(data)

