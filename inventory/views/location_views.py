from rest_framework import viewsets, permissions
from ..models.location_model import Location
from ..serializers.location_serializer import LocationSerializer
from ams.permissions import StrictDjangoModelPermissions
from user_management.models import UserProfile

class LocationViewSet(viewsets.ModelViewSet):
    serializer_class = LocationSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Location.objects.all()
        
        try:
            profile = user.profile
            # Strict enforcement: You MUST have the view_location permission to see the list/detail
            return profile.get_accessible_locations('inventory.view_location')
        except (AttributeError, UserProfile.DoesNotExist):
            return Location.objects.none()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
