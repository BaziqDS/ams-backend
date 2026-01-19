from rest_framework import viewsets, permissions, status
from .models import UserProfile
from .serializers import UserProfileSerializer
from ams.permissions import StrictDjangoModelPermissions

class UserProfileViewSet(viewsets.ModelViewSet):
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]
