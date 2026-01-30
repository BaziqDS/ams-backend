from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth.models import User, Permission, Group
from .models import UserProfile
from .serializers import UserProfileSerializer, UserManagementSerializer, UserSerializer, GroupSerializer
from ams.permissions import StrictDjangoModelPermissions

class UserProfileViewSet(viewsets.ModelViewSet):
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().select_related('profile').prefetch_related('user_permissions', 'groups')
    serializer_class = UserManagementSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]

class GroupViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.all().prefetch_related('permissions')
    serializer_class = GroupSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]

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

