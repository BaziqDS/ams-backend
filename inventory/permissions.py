from ams.permissions import StrictDjangoModelPermissions

class StockEntryPermission(StrictDjangoModelPermissions):
    """
    Custom permission for StockEntry:
    - Normal model permissions apply for most operations.
    - Creators can update/finalize their own entries if they are still in DRAFT status,
      even without global 'change_stockentry' permissions, provided they have 'add_stockentry'.
    """
    def has_permission(self, request, view):
        # 1. Superusers always have permission
        if request.user.is_superuser:
            return True

        # 2. For PUT/PATCH/DELETE, allow if they have 'add' permission 
        # so that has_object_permission can check if they own the draft.
        if request.method in ['PUT', 'PATCH', 'DELETE']:
            if request.user.has_perm('inventory.add_stockentry'):
                return True
        
        # 3. Otherwise default to parent (DjangoModelPermissions)
        return super().has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        # 1. Superusers can do anything
        if request.user.is_superuser:
            return True

        # 2. If it's a safe method (GET, HEAD, OPTIONS), model permissions (view) apply
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            return super().has_object_permission(request, view, obj)

        # 3. Handle Updates (PUT, PATCH)
        if request.method in ['PUT', 'PATCH']:
            # Exception for DRAFT entries: Allow if user is the creator and has 'add' permission
            if obj.status == 'DRAFT' and obj.created_by == request.user:
                return request.user.has_perm('inventory.add_stockentry')
            
            # Otherwise, fall back to default model permission check (requires change_stockentry)
            return super().has_object_permission(request, view, obj)

        # 4. Handle Deletion
        if request.method == 'DELETE':
            # Model-level restriction already ensures only DRAFT can be deleted.
            # Here we just check if they have permission to delete or if they own the draft.
            if obj.status == 'DRAFT' and obj.created_by == request.user:
                return request.user.has_perm('inventory.add_stockentry')
            return super().has_object_permission(request, view, obj)

        return super().has_object_permission(request, view, obj)
