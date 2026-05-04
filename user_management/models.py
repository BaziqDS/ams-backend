from django.db import models
from django.contrib.auth.models import Group, User, Permission
from django.core.exceptions import ValidationError
from django.db.models import Q

class RoleMetadata(models.Model):
    group = models.OneToOneField(Group, on_delete=models.CASCADE, related_name='role_metadata')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_role_metadata')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Role Metadata'
        verbose_name_plural = 'Role Metadata'

    def __str__(self):
        return f"{self.group.name} metadata"


class UserProfile(models.Model):
    """
    Robust UserProfile using Django's standard Permission system 
    combined with Location Hierarchy.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    employee_id = models.CharField(max_length=50, unique=True, null=True, blank=True)
    
    # Fundamental Access Control: WHERE is the user allowed to operate?
    assigned_locations = models.ManyToManyField(
        'inventory.Location',
        blank=True,
        related_name='assigned_users',
        help_text="The security boundaries for this user."
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} ({self.employee_id or 'No ID'})"

    def has_location_access(self, location):
        """
        Pure hierarchy check: Is the target location within my assigned nodes?
        """
        if self.user.is_superuser or self.user.groups.filter(name='System Admin').exists():
            return True
            
        # Check direct or descendant access
        for assigned_loc in self.assigned_locations.all():
            if location == assigned_loc or location.hierarchy_path.startswith(f"{assigned_loc.hierarchy_path}/"):
                return True
        return False

    def has_capability(self, perm_codename, location=None):
        """
        The Core Security Engine.
        Checks: 
        1. Does the user have the Django Permission (Capability)?
        2. If location is provided, are they allowed to use it there?
        
        Usage: request.user.profile.has_capability('inventory.add_stockentry', target_loc)
        """
        # 1. Check Global Django Permission (assigned via Groups or directly)
        if not self.user.has_perm(perm_codename):
            return False

        # 2. Check Spatial Constraint (Location)
        if location:
            return self.has_location_access(location)
            
        return True

    def get_accessible_locations(self, required_perm=None):
        """
        Returns a queryset of locations the user can access.
        Includes:
        1. Descendants (area of management)
        2. Ancestors (for upward movement/visibility)
        3. Peer/Related Stores (for specific hierarchy rules like L1 -> L2)
        """
        from inventory.models import Location
        
        if required_perm and not self.user.has_perm(required_perm):
            return Location.objects.none()

        if self.user.is_superuser:
            return Location.objects.filter(is_active=True)

        location_ids = set()
        for loc in self.assigned_locations.all():
            # 1. Include descendants (Managed area)
            descendants = loc.get_descendants(include_self=True)
            location_ids.update(descendants.values_list('id', flat=True))
            
            # 2. Include ancestors and their stores (Visibility for upward movement)
            curr = loc.parent_location
            while curr:
                location_ids.add(curr.id)
                if curr.auto_created_store_id:
                    location_ids.add(curr.auto_created_store_id)
                curr = curr.parent_location

            # 3. Special Rule: Level 1 Stores can see all Level 2 Stores 
            # (e.g. Central Store issuing to any Department Main Store)
            if loc.is_store and loc.hierarchy_level == 1:
                location_ids.update(
                    Location.objects.filter(is_store=True, hierarchy_level=2).values_list('id', flat=True)
                )
            
            # 4. If assigned to a store, include all non-store locations in the same standalone unit (department)
            if loc.is_store:
                standalone = loc.get_parent_standalone()
                if standalone:
                    location_ids.update(
                        Location.objects.filter(
                            hierarchy_path__startswith=standalone.hierarchy_path,
                            is_store=False
                        ).values_list('id', flat=True)
                    )
            
        return Location.objects.filter(id__in=location_ids, is_active=True).distinct()

    def get_descendant_locations(self):
        """
        Returns a queryset of locations strictly at or below the user's assigned locations.
        Used for inventory visibility (can't see above me).
        Exception: Level 1 Stores can see EVERYTHING (University wide).
        """
        from inventory.models import Location
        
        # 1. Global Visibility (System Admin or users with global distribution perm)
        if (self.user.is_superuser or 
            self.user.groups.filter(name='System Admin').exists() or 
            self.user.has_perm('inventory.view_global_distribution') or
            self.user.has_perm('inventory.manage_all_locations')):
            return Location.objects.filter(is_active=True)

        location_ids = set()
        assigned_locs = self.assigned_locations.all()

        # 2. Scoped Visibility (users with scoped distribution perm)
        if self.user.has_perm('inventory.view_scoped_distribution'):
            for loc in assigned_locs:
                # Include descendants (Managed area)
                descendants = loc.get_descendants(include_self=True)
                location_ids.update(descendants.values_list('id', flat=True))
                
                # Departmental Context: If in a store, allow seeing everything in that department
                if loc.is_store:
                    standalone = loc.get_parent_standalone()
                    if standalone:
                        department_locs = Location.objects.filter(
                            hierarchy_path__startswith=standalone.hierarchy_path
                        )
                        location_ids.update(department_locs.values_list('id', flat=True))

        return Location.objects.filter(id__in=location_ids, is_active=True).distinct()

    def get_location_view_locations(self):
        """
        Locations visible in the Locations module.

        Visibility is based on the user's assigned standalone boundary:
        the assigned standalone itself and every sub-location below it. Store
        assignments inherit the parent standalone as the boundary.
        """
        from inventory.models import Location

        if self.user.is_superuser:
            return Location.objects.filter(is_active=True)

        location_ids = set()
        for loc in self.assigned_locations.filter(is_active=True):
            standalone = loc if loc.is_standalone else loc.get_parent_standalone()
            if not standalone:
                continue
            location_ids.update(
                standalone.get_descendants(include_self=True).values_list('id', flat=True)
            )

        return Location.objects.filter(id__in=location_ids, is_active=True).distinct()

    def get_inspection_department_locations(self):
        """
        Standalone departments visible in the inspections module.

        A root-level standalone assignment exposes every standalone in the
        university. Non-root assignments expose only the user's assigned
        standalone units; store assignments resolve to their parent standalone.
        """
        from inventory.models import Location

        if self.user.is_superuser:
            return Location.objects.filter(is_standalone=True, is_store=False, is_active=True)

        assigned = self.assigned_locations.filter(is_active=True)
        if assigned.filter(parent_location__isnull=True, is_standalone=True).exists():
            return Location.objects.filter(is_standalone=True, is_store=False, is_active=True)

        standalone_ids = set()
        for loc in assigned:
            standalone = loc if loc.is_standalone else loc.get_parent_standalone()
            if standalone:
                standalone_ids.add(standalone.id)

        return Location.objects.filter(
            id__in=standalone_ids,
            is_standalone=True,
            is_store=False,
            is_active=True,
        ).distinct()

    def get_creatable_inspection_department_locations(self):
        """
        Standalone departments the user may choose when creating an inspection.

        Creation is limited to directly assigned standalone units. Store or
        child-location assignments resolve upward to their owning standalone.
        A root-level standalone assignment counts only as that standalone and
        does not unlock every university department.
        """
        from inventory.models import Location

        if self.user.is_superuser:
            return Location.objects.filter(is_standalone=True, is_store=False, is_active=True)

        standalone_ids = set()
        for loc in self.assigned_locations.filter(is_active=True):
            standalone = loc if loc.is_standalone else loc.get_parent_standalone()
            if standalone and not standalone.is_store and standalone.is_active:
                standalone_ids.add(standalone.id)

        return Location.objects.filter(
            id__in=standalone_ids,
            is_standalone=True,
            is_store=False,
            is_active=True,
        ).distinct()

    def has_root_inspection_scope(self):
        if self.user.is_superuser:
            return True
        return self.assigned_locations.filter(
            parent_location__isnull=True,
            is_standalone=True,
            is_active=True,
        ).exists()

    def get_stock_entry_scope_locations(self):
        """
        Returns the location boundary used for stock-entry visibility.

        Main-store assignments see the whole standalone unit. Non-main store
        assignments see only that store. Standalone assignments behave like
        the standalone's main-store scope.
        """
        from inventory.models import Location

        if self.user.is_superuser or self.user.groups.filter(name='System Admin').exists():
            return Location.objects.filter(is_active=True)

        location_ids = set()
        for loc in self.assigned_locations.filter(is_active=True):
            if loc.is_store:
                if loc.is_main_store:
                    standalone = loc.get_parent_standalone()
                    if standalone:
                        location_ids.update(self._get_same_standalone_location_ids(standalone))
                    else:
                        location_ids.add(loc.id)
                else:
                    location_ids.add(loc.id)
                continue

            standalone = loc if loc.is_standalone else loc.get_parent_standalone()
            if standalone and standalone.parent_location_id is None and loc.is_standalone:
                location_ids.update(
                    standalone.get_descendants(include_self=True).values_list('id', flat=True)
                )
            elif standalone:
                location_ids.update(self._get_same_standalone_location_ids(standalone))

        return Location.objects.filter(id__in=location_ids, is_active=True).distinct()

    def get_stock_register_scope_locations(self):
        """
        Returns the location boundary used for stock-register visibility.

        Standalone assignments see stores within that standalone unit only.
        Main-store assignments inherit the same standalone-unit visibility.
        Non-main store assignments see only their own store.
        """
        from inventory.models import Location

        if (
            self.user.is_superuser
            or self.user.groups.filter(name='System Admin').exists()
        ):
            return Location.objects.filter(is_store=True, is_active=True)

        location_ids = set()
        for loc in self.assigned_locations.filter(is_active=True):
            if loc.is_store and not loc.is_main_store:
                location_ids.add(loc.id)
                continue

            standalone = loc if loc.is_standalone else loc.get_parent_standalone()
            if not standalone:
                if loc.is_store:
                    location_ids.add(loc.id)
                continue

            location_ids.update(
                Location.objects.filter(
                    id__in=self._get_same_standalone_store_ids(standalone),
                    is_store=True,
                    is_active=True,
                ).values_list('id', flat=True)
            )

        return Location.objects.filter(id__in=location_ids, is_store=True, is_active=True).distinct()

    def get_creatable_stock_register_stores(self):
        """
        Stores available when creating or reassigning stock registers.

        Root-standalone assignments are creation-sensitive: they do not unlock
        every descendant store. Those users may only create registers for
        directly assigned stores. Non-root scopes retain the existing
        standalone-boundary behavior.
        """
        from inventory.models import Location

        if (
            self.user.is_superuser
            or self.user.groups.filter(name='System Admin').exists()
        ):
            return Location.objects.filter(is_store=True, is_active=True)

        assigned = self.assigned_locations.filter(is_active=True)
        has_root_standalone = assigned.filter(
            parent_location__isnull=True,
            is_standalone=True,
        ).exists()
        if not has_root_standalone:
            return self.get_stock_register_scope_locations()

        return assigned.filter(is_store=True, is_active=True).distinct()

    def _get_same_standalone_location_ids(self, standalone):
        """
        Location ids that belong to the standalone unit itself, excluding any
        nested child standalone units and their descendants.
        """
        from inventory.models import Location

        scoped_locations = Location.objects.filter(
            hierarchy_path__startswith=standalone.hierarchy_path,
            is_active=True,
        )

        nested_units = standalone.get_descendants(include_self=False).filter(is_standalone=True)
        for child_unit in nested_units:
            scoped_locations = scoped_locations.exclude(
                hierarchy_path__startswith=child_unit.hierarchy_path,
            )

        return scoped_locations.values_list('id', flat=True)

    def _get_same_standalone_store_ids(self, standalone):
        """
        Store ids that belong to the standalone unit itself, excluding any
        nested child standalone units and their store trees.
        """
        from inventory.models import Location

        scoped_stores = Location.objects.filter(
            hierarchy_path__startswith=standalone.hierarchy_path,
            is_store=True,
            is_active=True,
        )

        nested_units = standalone.get_descendants(include_self=False).filter(is_standalone=True)
        for child_unit in nested_units:
            scoped_stores = scoped_stores.exclude(
                hierarchy_path__startswith=child_unit.hierarchy_path,
            )

        return scoped_stores.values_list('id', flat=True)

    def get_user_management_locations(self):
        """
        Locations that define which user accounts this user can manage/view.
        Does NOT include the L1->L2 global-visibility shortcut used by
        get_descendant_locations() — user management is scoped by the user's own
        assigned locations and their descendants, plus (if the user is assigned
        to a store) the departmental context of that store.
        """
        from inventory.models import Location

        if self.user.is_superuser:
            return Location.objects.filter(is_active=True)

        if not self.assigned_locations.exists():
            return Location.objects.none()

        location_ids = set()
        for loc in self.assigned_locations.all():
            descendants = loc.get_descendants(include_self=True)
            location_ids.update(descendants.values_list('id', flat=True))

            if loc.is_store:
                standalone = loc.get_parent_standalone()
                if standalone:
                    department_locs = Location.objects.filter(
                        hierarchy_path__startswith=standalone.hierarchy_path,
                        is_active=True,
                    )
                    location_ids.update(department_locs.values_list('id', flat=True))

        return Location.objects.filter(id__in=location_ids, is_active=True).distinct()

    def has_root_user_management_scope(self):
        """Whether this profile's assigned location scope covers the whole system."""
        if self.user.is_superuser:
            return True
        return self.assigned_locations.filter(
            parent_location__isnull=True,
            is_active=True,
        ).exists()

    def get_assignable_locations_for_user_management(self):
        """Locations this user may assign to other users they manage.

        Uses the same spatial boundary as user-management visibility:
        assigned locations and their descendants. If the user is assigned to
        the level-0 root, this naturally expands to every active location.
        """
        from inventory.models import Location

        if self.user.is_superuser:
            return Location.objects.filter(is_active=True)

        return self.get_user_management_locations()

    def get_assigned_permissions(self):
        """Helper to list all dynamic permissions for UI displays."""
        return self.user.get_all_permissions()

    @property
    def power_level(self):
        """
        Deprecated in favor of explicit Roles (Groups).
        Kept for backward-compatibility with UI list displays.
        0: System Admin
        1: Operational / Assigned
        3: Personal / No Assignment
        """
        if self.user.is_superuser or self.user.groups.filter(name='System Admin').exists():
            return 0
        
        assigned_locs = self.assigned_locations.all()
        if not assigned_locs.exists():
            return 3
            
        return 1

    def get_transferrable_locations(self, from_location):
        """
        Enforces strict directional flow based on Store Hierarchy.
        Central store -> root-level regular stores or standalone main stores.
        Standalone main store -> central store or regular stores in the same standalone.
        Regular store -> own standalone main store.
        """
        from inventory.models import Location
        
        if not from_location.is_store:
            return Location.objects.none()

        if from_location.hierarchy_level == 1 and from_location.is_main_store:
            return Location.objects.filter(
                is_active=True,
                is_store=True,
            ).filter(
                Q(hierarchy_level=2, is_main_store=True) |
                Q(hierarchy_level=1, is_main_store=False)
            ).exclude(id=from_location.id)

        standalone = from_location.get_parent_standalone()
        if not standalone:
            return Location.objects.none()

        same_scope_stores = Location.objects.filter(
            id__in=self._get_same_standalone_store_ids(standalone),
            is_store=True,
            is_active=True,
        ).exclude(id=from_location.id)
        main_store = from_location.get_containing_main_store()
        is_source_main_store = bool(from_location.is_main_store)

        if is_source_main_store:
            central_stores = Location.objects.filter(is_store=True, hierarchy_level=1, is_main_store=True, is_active=True)
            peer_regular_stores = same_scope_stores.filter(is_main_store=False)
            return (central_stores | peer_regular_stores).distinct()

        peer_regular_stores = same_scope_stores.filter(is_main_store=False)
        own_main_store = same_scope_stores.filter(id=getattr(main_store, 'id', None))
        return (own_main_store | peer_regular_stores).distinct()

        return Location.objects.none()

    def get_allocatable_targets(self, source_store):
        """
        Defines the scope for issuing items to persons or rooms.
        L1: Global allocation
        L2/L3: Departmental allocation
        """
        from inventory.models import Location, Person
        
        # Determine the management unit (standalone parent)
        standalone = source_store.get_parent_standalone()
        
        # If the store belongs to a unit (Department/Section), always restrict to that unit
        if standalone:
            dept_locations = Location.objects.filter(
                hierarchy_path__startswith=standalone.hierarchy_path,
                is_store=False,
                is_standalone=False,
                is_active=True
            )
            
            # EXCLUSION LOGIC: Exclude any locations that are managed by a child standalone unit.
            child_standalones = Location.objects.filter(
                is_standalone=True,
                hierarchy_path__startswith=f"{standalone.hierarchy_path}/"
            ).values_list('hierarchy_path', flat=True)
            
            if child_standalones:
                q_exclude = Q()
                for child_path in child_standalones:
                    q_exclude |= Q(hierarchy_path__startswith=child_path)
                dept_locations = dept_locations.exclude(q_exclude)
                
            # Filter persons linked to the same standalone unit
            # STRICT FILTERING: Persons must belong to the source store's standalone unit.
            # No bypass for superusers - physical items must flow properly.
            dept_persons = Person.objects.filter(standalone_locations=standalone, is_active=True).distinct()
                
            return {
                'locations': dept_locations,
                'persons': dept_persons
            }
            
        # If no standalone parent (Global Store) and user is Admin, allow global
        if self.user.is_superuser or self.user.groups.filter(name='System Admin').exists():
            return {
                'locations': Location.objects.filter(is_store=False, is_active=True),
                'persons': Person.objects.filter(is_active=True)
            }
            
        return {'locations': Location.objects.none(), 'persons': Person.objects.none()}

    class Meta:
        verbose_name = "User Profile"
        permissions = [
            # User accounts module
            ("view_user_accounts", "Can view user accounts in assigned locations"),
            ("view_all_user_accounts", "Can view all user accounts university-wide"),
            ("create_user_accounts", "Can create user accounts"),
            ("edit_user_accounts", "Can edit user accounts"),
            ("delete_user_accounts", "Can delete user accounts"),
            ("assign_user_locations", "Can assign locations to user accounts"),
            ("assign_user_roles", "Can assign roles to user accounts"),
            # Roles module
            ("view_roles", "Can view roles"),
            ("create_roles", "Can create roles"),
            ("edit_roles", "Can edit roles"),
            ("delete_roles", "Can delete roles"),
            ("assign_permissions_to_roles", "Can assign permissions to roles"),
        ]
