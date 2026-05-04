from rest_framework import viewsets
from django.db.models import Q


def _split_scope_tokens(raw_tokens):
    tokens = []
    for raw in raw_tokens or []:
        for token in str(raw).split(','):
            token = token.strip()
            if token:
                tokens.append(token)
    return tokens


def get_scope_tokens_from_request(request):
    if not request:
        return []
    return _split_scope_tokens(request.query_params.getlist('scope'))


def _same_standalone_locations(standalone):
    queryset = standalone.get_descendants(include_self=True)
    nested_units = standalone.get_descendants(include_self=False).filter(is_standalone=True)
    for child_unit in nested_units:
        queryset = queryset.exclude(hierarchy_path__startswith=child_unit.hierarchy_path)
    return queryset


def _assigned_standalones(user):
    if not hasattr(user, 'profile'):
        return []

    seen = set()
    standalones = []
    for loc in user.profile.assigned_locations.filter(is_active=True):
        standalone = loc if loc.is_standalone else loc.get_parent_standalone()
        if standalone and standalone.id not in seen:
            seen.add(standalone.id)
            standalones.append(standalone)
    return standalones


def _assigned_store_locations(user):
    if not hasattr(user, 'profile'):
        return []
    return list(
        user.profile.assigned_locations.filter(
            is_active=True,
            is_store=True,
        ).order_by('name')
    )


def user_has_root_item_scope(user):
    if user.is_superuser or user.groups.filter(name='System Admin').exists():
        return True
    if not hasattr(user, 'profile'):
        return False
    return user.profile.assigned_locations.filter(
        parent_location__isnull=True,
        is_standalone=True,
        is_active=True,
    ).exists()


def get_item_scope_options(user):
    """
    Filter options exposed to the item distribution UI.

    Root assignments get an all-system default plus a root-only option.
    Non-root assignments get one option per visible standalone. Assigned
    stores are exposed as explicit store filters in both cases.
    """
    if not hasattr(user, 'profile') and not user.is_superuser:
        return {"options": [], "default": [], "is_root_scope": False}

    from ..models.location_model import Location

    if user.is_superuser or user.groups.filter(name='System Admin').exists():
        root = Location.objects.filter(parent_location__isnull=True, is_active=True).first()
        options = [{"id": "all", "label": "All locations", "kind": "all", "location_id": None}]
        if root:
            options.append({
                "id": f"root:{root.id}",
                "label": f"{root.name} only",
                "kind": "root",
                "location_id": root.id,
            })
        return {"options": options, "default": ["all"], "is_root_scope": True}

    root_scope = user_has_root_item_scope(user)
    standalones = _assigned_standalones(user)
    stores = _assigned_store_locations(user)
    options = []
    default_tokens = []

    if root_scope:
        root = next((loc for loc in standalones if loc.parent_location_id is None), None)
        options.append({"id": "all", "label": "All locations", "kind": "all", "location_id": None})
        default_tokens = ["all"]
        if root:
            options.append({
                "id": f"root:{root.id}",
                "label": f"{root.name} only",
                "kind": "root",
                "location_id": root.id,
            })
    else:
        for standalone in sorted(standalones, key=lambda loc: loc.name):
            token = f"standalone:{standalone.id}"
            options.append({
                "id": token,
                "label": standalone.name,
                "kind": "standalone",
                "location_id": standalone.id,
            })
            default_tokens.append(token)

    for store in stores:
        options.append({
            "id": f"store:{store.id}",
            "label": store.name,
            "kind": "store",
            "location_id": store.id,
        })

    return {"options": options, "default": default_tokens, "is_root_scope": root_scope}


def get_item_scope_locations(user, scope_tokens=None):
    """
    Locations visible through the items module.

    Root-level standalone assignment defaults to the entire system. Non-root
    assignments default to the user's standalone unit(s). Explicit scope
    tokens narrow the result to selected root/standalone/store options.
    """
    from ..models.location_model import Location

    if not hasattr(user, 'profile') and not user.is_superuser:
        return Location.objects.none()

    if user.is_superuser or user.groups.filter(name='System Admin').exists():
        tokens = _split_scope_tokens(scope_tokens)
        if not tokens or "all" in tokens:
            return Location.objects.filter(is_active=True)
        location_ids = set()
        for token in tokens:
            kind, _, raw_id = token.partition(':')
            if kind not in {"root", "standalone", "store"}:
                continue
            try:
                location = Location.objects.get(id=int(raw_id), is_active=True)
            except (TypeError, ValueError, Location.DoesNotExist):
                continue
            if kind == "store" and location.is_store:
                location_ids.add(location.id)
            elif kind in {"root", "standalone"} and location.is_standalone:
                location_ids.update(_same_standalone_locations(location).values_list('id', flat=True))
        return Location.objects.filter(id__in=location_ids, is_active=True).distinct()

    options = get_item_scope_options(user)
    allowed = {option["id"]: option for option in options["options"]}
    requested_tokens = _split_scope_tokens(scope_tokens)
    tokens = requested_tokens or options["default"]

    if "all" in tokens and "all" in allowed:
        return Location.objects.filter(is_active=True)

    location_ids = set()
    for token in tokens:
        option = allowed.get(token)
        if not option:
            continue
        kind = option["kind"]
        location_id = option["location_id"]
        if kind == "store" and location_id:
            location_ids.add(location_id)
            continue
        if kind in {"root", "standalone"} and location_id:
            try:
                standalone = Location.objects.get(id=location_id, is_standalone=True, is_active=True)
            except Location.DoesNotExist:
                continue
            location_ids.update(_same_standalone_locations(standalone).values_list('id', flat=True))

    return Location.objects.filter(id__in=location_ids, is_active=True).distinct()

class ScopedViewSetMixin:
    """
    Standardized Row-Level Security Mixin for AMS.
    Filters the queryset based on the user's hierarchical scope.
    """
    
    def get_scoped_queryset(self, queryset, location_field='location'):
        user = self.request.user
        if not hasattr(user, 'profile'):
            return queryset.none()
            
        # Bypass scoping for central roles and workflow administrators
        if (user.is_superuser or 
            user.groups.filter(name='Central Store Manager').exists() or
            user.has_perm('inventory.fill_central_register') or
            user.has_perm('inventory.review_finance')):
            return queryset

        accessible_locations = user.profile.get_descendant_locations()
        
        # Handle multi-field filtering (e.g. StockEntry from/to)
        if isinstance(location_field, (list, tuple)):
            q_objects = Q()
            for field in location_field:
                q_objects |= Q(**{f"{field}__in": accessible_locations})
            return queryset.filter(q_objects).distinct()
            
        return queryset.filter(**{f"{location_field}__in": accessible_locations}).distinct()
