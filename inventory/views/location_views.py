# pyright: reportAttributeAccessIssue=false
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from ..models.location_model import Location
from ..serializers.location_serializer import LocationSerializer
from ..permissions import LocationPermission
from user_management.models import UserProfile

class LocationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Locations.
    Optimized with select_related for parent relationships.
    """
    serializer_class = LocationSerializer
    permission_classes = [permissions.IsAuthenticated, LocationPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code']

    def get_queryset(self):
        # Add select_related to avoid N+1 on parent_location
        queryset = Location.objects.select_related(
            'parent_location',
            'created_by',
            'auto_created_store'
        ).all()
        
        user = self.request.user
        if user.is_superuser:
            return queryset
        
        try:
            profile = user.profile
            return profile.get_location_view_locations()
        except (AttributeError, UserProfile.DoesNotExist):
            return Location.objects.none()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get', 'post'])
    def standalone(self, request):
        """
        GET: list standalone, non-store locations for the main Locations page.
        POST: create a root location if none exists, otherwise create a standalone
        child under the root. Client-supplied parent/is_standalone flags are ignored.
        """
        if request.method == 'GET':
            queryset = self.filter_queryset(
                self.get_queryset().filter(is_standalone=True, is_store=False)
            )
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data)

        root = Location.objects.filter(parent_location__isnull=True).order_by('id').first()
        data = request.data.copy()
        data['parent_location'] = root.id if root else None
        data['is_standalone'] = True
        data['is_store'] = False
        data['is_main_store'] = False

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=True, methods=['get', 'post'])
    def children(self, request, pk=None):
        """
        GET: list immediate children for a standalone/root location. The root view
        excludes standalone children because those are managed as their own units.
        POST: create a non-standalone immediate child under this location.
        """
        parent = self.get_object()

        if request.method == 'GET':
            queryset = self.get_queryset().filter(parent_location=parent)
            if parent.hierarchy_level == 0:
                queryset = queryset.filter(is_standalone=False)
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data)

        if not parent.is_standalone:
            return Response(
                {'detail': 'Sub-locations can only be created under standalone locations.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = request.data.copy()
        data['parent_location'] = parent.id
        data['is_standalone'] = False

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

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
            from_loc = Location.objects.select_related('parent_location').get(id=from_loc_id)
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
            source_store = Location.objects.select_related('parent_location').get(id=source_id)
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
        Returns locations that this user may assign to other users they manage.

        - Superusers see all active locations.
        - Scoped user-managers see their own assigned locations and descendants.
          A level-0 root assignment therefore allows assigning any active
          location, while a department assignment stays inside that department.
        """
        user = request.user
        if user.is_superuser:
            queryset = Location.objects.filter(is_active=True)
        else:
            try:
                queryset = user.profile.get_assignable_locations_for_user_management()
            except UserProfile.DoesNotExist:
                queryset = Location.objects.none()

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
