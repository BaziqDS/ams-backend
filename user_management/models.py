from django.db import models
from django.contrib.auth.models import User, Permission
from django.core.exceptions import ValidationError
from django.db.models import Q

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
        L1 -> L2 only
        L2 -> L1 (Return) or L3 (Children)
        L3 -> L2 (Return) only
        """
        from inventory.models import Location
        
        if not from_location.is_store:
            return Location.objects.none()

        level = from_location.hierarchy_level
        
        if level == 1: # Central Store
            # Can issue to any L2 Main Store
            return Location.objects.filter(is_store=True, hierarchy_level=2, is_main_store=True, is_active=True)
            
        if level == 2: # Dept Main Store
            # 1. Return to L1
            l1_stores = Location.objects.filter(is_store=True, hierarchy_level=1, is_active=True)
            # 2. Issue to L3 children in same unit
            l3_stores = Location.objects.filter(
                parent_location=from_location, 
                is_store=True, 
                hierarchy_level=3, 
                is_active=True
            )
            return (l1_stores | l3_stores).distinct()
            
        if level == 3: # Section Store
            # Can only return to Parent L2
            if from_location.parent_location:
                return Location.objects.filter(id=from_location.parent_location_id, is_active=True)
                
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
