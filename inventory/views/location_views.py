from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from ..models.location_model import Location
from ..serializers.location_serializer import LocationSerializer
from ams.permissions import StrictDjangoModelPermissions
from user_management.models import UserProfile

class LocationViewSet(viewsets.ModelViewSet):
    serializer_class = LocationSerializer
    permission_classes = [permissions.IsAuthenticated, StrictDjangoModelPermissions]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code']

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

    @action(detail=False, methods=['get'])
    def transferrable(self, request):
        """
        Returns locations where the user is allowed to transfer from a given source.
        Query Param: from_location_id
        """
        from_loc_id = request.query_params.get('from_location_id')
        if not from_loc_id:
            return Response({"detail": "from_location_id is required"}, status=400)
            
        try:
            from_loc = Location.objects.get(id=from_loc_id)
        except Location.DoesNotExist:
            return Response({"detail": "Source location not found"}, status=404)
            
        profile = request.user.profile
        queryset = profile.get_transferrable_locations(from_loc)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def allocatable_targets(self, request):
        """
        Returns locations (rooms) and persons allowed for allocation from a source store.
        Query Param: source_store_id
        """
        source_id = request.query_params.get('source_store_id')
        if not source_id:
            return Response({"detail": "source_store_id is required"}, status=400)
            
        try:
            source_store = Location.objects.get(id=source_id)
        except Location.DoesNotExist:
            return Response({"detail": "Source store not found"}, status=404)
            
        profile = request.user.profile
        targets = profile.get_allocatable_targets(source_store)
        
        loc_serializer = self.get_serializer(targets['locations'], many=True)
        from ..serializers.stockentry_serializer import PersonSerializer
        person_serializer = PersonSerializer(targets['persons'], many=True)
        
        return Response({
            'locations': loc_serializer.data,
            'persons': person_serializer.data
        })

    @action(detail=False, methods=['get'])
    def assignable(self, request):
        """
        Returns locations that the user is allowed to assign to other users.
        - Global managers see all.
        - Scoped managers see their descendant locations.
        """
        user = request.user
        if user.is_superuser or user.has_perm('user_management.view_all_user_accounts'):
            queryset = Location.objects.filter(is_active=True)
        elif user.has_perm('user_management.view_user_accounts_assigned_location'):
            try:
                queryset = user.profile.get_descendant_locations()
            except UserProfile.DoesNotExist:
                queryset = Location.objects.none()
        else:
            queryset = Location.objects.none()
            
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
