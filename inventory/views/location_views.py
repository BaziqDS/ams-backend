# pyright: reportAttributeAccessIssue=false
from django.db import transaction
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from ..models.location_model import Location, LocationTag, LocationType
from ..serializers.location_serializer import LocationListSerializer, LocationSerializer, LocationTagSerializer
from ..permissions import LocationPermission
from ..services.deletion_policy import DeletionBlocked, delete_with_policy
from user_management.models import UserProfile


def _is_truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple)):
        value = value[0] if value else False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _with_location_serializer_relations(queryset):
    return queryset.select_related(
        'parent_location',
        'created_by',
        'auto_created_store',
    ).prefetch_related('tags')


class LocationTagViewSet(viewsets.ModelViewSet):
    serializer_class = LocationTagSerializer
    permission_classes = [permissions.IsAuthenticated, LocationPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code', 'category']

    def get_queryset(self):
        return LocationTag.objects.all()


class LocationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Locations.
    Optimized with select_related for parent relationships.
    """
    serializer_class = LocationSerializer
    permission_classes = [permissions.IsAuthenticated, LocationPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code']

    def get_serializer_class(self):
        if self.action in {'list', 'assignable', 'transferrable', 'allocatable_targets'}:
            return LocationListSerializer
        return super().get_serializer_class()

    def get_queryset(self):
        # Add select_related to avoid N+1 on parent_location
        queryset = _with_location_serializer_relations(Location.objects.all())
        
        user = self.request.user
        if user.is_superuser:
            return queryset
        
        try:
            profile = user.profile
            scoped_locations = profile.get_location_view_locations()
            return queryset.filter(id__in=scoped_locations.values_list('id', flat=True))
        except (AttributeError, UserProfile.DoesNotExist):
            return Location.objects.none()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        roots = Location.objects.filter(parent_location__isnull=True).select_related('auto_created_store')
        context['root_locations_by_code'] = {root.code: root for root in roots}
        return context

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            delete_with_policy(instance)
        except DeletionBlocked as exc:
            return Response(
                {'detail': 'Delete is blocked by existing dependencies.', 'delete_blockers': exc.blockers},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

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
        create_main_store = _is_truthy(data.get('create_main_store', False))

        if create_main_store:
            if parent.auto_created_store_id or parent.get_main_store():
                return Response(
                    {'detail': 'This location already has a main store.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            data['location_type'] = LocationType.STORE
            data['is_store'] = True
            data['is_main_store'] = True
            data['is_auto_created'] = True
            if not data.get('code'):
                data['code'] = 'CENTRAL-STORE' if parent.parent_location_id is None else f'{parent.code}-MAIN-STORE'

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        if create_main_store:
            with transaction.atomic():
                self.perform_create(serializer)
                parent.auto_created_store = serializer.instance
                parent.save(update_fields=['auto_created_store'])
        else:
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
            queryset = self.get_queryset().filter(is_active=True)
        else:
            try:
                queryset = _with_location_serializer_relations(
                    user.profile.get_assignable_locations_for_user_management()
                )
            except UserProfile.DoesNotExist:
                queryset = Location.objects.none()

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
