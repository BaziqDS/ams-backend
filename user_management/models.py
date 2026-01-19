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
        if self.user.is_superuser:
            return True
            
        # Check direct or descendant access
        # Uses hierarchy_path from the Location model we designed
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
        If required_perm is provided, it checks for that specific capability.
        """
        from inventory.models import Location
        
        # If a specific perm is required and they don't have it globally, return none
        if required_perm and not self.user.has_perm(required_perm):
            return Location.objects.none()

        if self.user.is_superuser:
            return Location.objects.filter(is_active=True)

        # Retrieve all descendants of assigned locations
        location_ids = []
        for loc in self.assigned_locations.all():
            # Using the get_descendants method from our Location template
            descendants = loc.get_descendants(include_self=True)
            location_ids.extend(descendants.values_list('id', flat=True))
            
        return Location.objects.filter(id__in=location_ids, is_active=True).distinct()

    def get_assigned_permissions(self):
        """Helper to list all dynamic permissions for UI displays."""
        return self.user.get_all_permissions()

    class Meta:
        verbose_name = "User Profile"
        # No hardcoded roles here! We use standard Django permissions in ViewSets.
