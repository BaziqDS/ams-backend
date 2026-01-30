from rest_framework import permissions

class StrictDjangoModelPermissions(permissions.DjangoModelPermissions):
    """
    Extends DjangoModelPermissions to also check for 'view' permissions on GET requests.
    Allows GET if user has ANY of the model permissions (view, add, change, delete).
    """
    def __init__(self):
        self.perms_map = {
            'GET': ['%(app_label)s.view_%(model_name)s'],
            'OPTIONS': [],
            'HEAD': [],
            'POST': ['%(app_label)s.add_%(model_name)s'],
            'PUT': ['%(app_label)s.change_%(model_name)s'],
            'PATCH': ['%(app_label)s.change_%(model_name)s'],
            'DELETE': ['%(app_label)s.delete_%(model_name)s'],
        }

    def has_permission(self, request, view):
        # Workaround for custom actions: DRF DjangoModelPermissions checks 'add' for all POSTs.
        # For detail actions (e.g., transitions), we should allow it if they have 'change' permission.
        
        # Determine if this is a detail request
        # 1. Standard check
        is_detail = getattr(view, 'detail', False)
        # 2. Action check (for custom actions, DRF sets .action but might not set .detail on the instance early enough)
        if not is_detail:
            action = getattr(view, 'action', None)
            if action:
                method = getattr(view, action, None)
                is_detail = getattr(method, 'detail', False)

        queryset = self._queryset(view)
        model_cls = queryset.model
        user = request.user
        app_label = model_cls._meta.app_label
        model_name = model_cls._meta.model_name

        if request.method == 'POST' and is_detail:
            # Allow POST on detail routes if user has 'change' OR 'add' permission
            change_perm = f"{app_label}.change_{model_name}"
            add_perm = f"{app_label}.add_{model_name}"
            if user.has_perm(change_perm) or user.has_perm(add_perm):
                return True
                
        if request.method == 'GET':
            # Allow GET if user has ANY of the model permissions (view, add, change, delete)
            # This ensures someone with 'change' can still 'view' the object to edit it.
            perms = [
                f"{app_label}.view_{model_name}",
                f"{app_label}.add_{model_name}",
                f"{app_label}.change_{model_name}",
                f"{app_label}.delete_{model_name}"
            ]
            if any(user.has_perm(p) for p in perms):
                return True

        return super().has_permission(request, view)
