from rest_framework import serializers
from django.contrib.auth.models import User, Permission, Group
from .models import UserProfile
from .services.capability_service import (
    apply_module_selections,
    compute_capabilities_for_user,
)
from ams.permissions_manifest import MODULES
from inventory.models.location_model import Location

class UserSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    assigned_locations = serializers.PrimaryKeyRelatedField(
        source='profile.assigned_locations',
        many=True,
        read_only=True
    )
    groups_display = serializers.StringRelatedField(
        source='groups',
        many=True,
        read_only=True
    )

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'is_superuser', 'is_staff', 'permissions', 'assigned_locations', 'groups_display')


    def get_permissions(self, obj):
        return list(obj.get_all_permissions())

class UserManagementSerializer(serializers.ModelSerializer):
    employee_id = serializers.CharField(source='profile.employee_id', required=False, allow_blank=True)
    assigned_locations = serializers.PrimaryKeyRelatedField(
        source='profile.assigned_locations',
        many=True,
        queryset=Location.objects.all(),
        required=False
    )
    assigned_locations_display = serializers.StringRelatedField(
        source='profile.assigned_locations',
        many=True,
        read_only=True
    )
    user_permissions_list = serializers.SlugRelatedField(
        source='user_permissions',
        many=True,
        queryset=Permission.objects.all(),
        slug_field='codename',
        required=False
    )
    groups = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Group.objects.all(),
        required=False
    )
    groups_display = serializers.StringRelatedField(
        source='groups',
        many=True,
        read_only=True
    )
    is_active = serializers.BooleanField(source='profile.is_active', required=False)
    power_level = serializers.IntegerField(source='profile.power_level', read_only=True)
    password = serializers.CharField(write_only=True, required=False)
    created_at = serializers.DateTimeField(source='profile.created_at', read_only=True)

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name', 'password',
            'is_superuser', 'is_staff', 'is_active', 'power_level',
            'employee_id', 'assigned_locations', 'assigned_locations_display',
            'user_permissions_list', 'groups', 'groups_display', 'last_login',
            'created_at',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and request.user and hasattr(request.user, 'profile'):
            # Scope the assignable-locations dropdown to the admin's own
            # locations plus their direct children (one-level delegation). The
            # broader subtree from get_user_management_locations() is used for
            # *viewing* users, not for *assigning* locations to them.
            self.fields['assigned_locations'].queryset = (
                request.user.profile.get_assignable_locations_for_user_management()
            )

    def create(self, validated_data):
        profile_data = validated_data.pop('profile', {})
        user_permissions = validated_data.pop('user_permissions', [])
        groups = validated_data.pop('groups', [])
        password = validated_data.pop('password', None)
        
        # Create user using create_user to hash password
        user = User.objects.create_user(
            username=validated_data.get('username'),
            email=validated_data.get('email', ''),
            password=password,
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            is_superuser=validated_data.get('is_superuser', False),
            is_staff=validated_data.get('is_staff', False)
        )

        if user_permissions:
            user.user_permissions.set(user_permissions)
        
        if groups:
            user.groups.set(groups)

        # Profile is created by signal, so we update it
        profile = user.profile
        if 'employee_id' in profile_data:
            profile.employee_id = profile_data['employee_id']
        if 'is_active' in profile_data:
            profile.is_active = profile_data['is_active']
        if 'assigned_locations' in profile_data:
            profile.assigned_locations.set(profile_data['assigned_locations'])
        
        profile.save()
        return user

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', {})

        # Self-edit guard: a user editing their own profile cannot remove any
        # location that was granted to them by an upstream admin. Additions are
        # still allowed (and further constrained to the delegation scope by the
        # assigned_locations queryset in __init__).
        if 'assigned_locations' in profile_data:
            request = self.context.get('request')
            editing_self = (
                request is not None
                and request.user is not None
                and request.user.is_authenticated
                and instance.pk == request.user.pk
                and not request.user.is_superuser
            )
            if editing_self:
                incoming_ids = {loc.pk for loc in profile_data['assigned_locations']}
                current_ids = set(
                    instance.profile.assigned_locations.values_list('pk', flat=True)
                )
                removed = current_ids - incoming_ids
                if removed:
                    raise serializers.ValidationError({
                        'assigned_locations': (
                            "You cannot remove locations from your own profile. "
                            "Ask an admin with broader scope to revoke them."
                        ),
                    })

        # Update User fields
        instance.username = validated_data.get('username', instance.username)
        instance.email = validated_data.get('email', instance.email)
        instance.first_name = validated_data.get('first_name', instance.first_name)
        instance.last_name = validated_data.get('last_name', instance.last_name)
        instance.is_superuser = validated_data.get('is_superuser', instance.is_superuser)
        instance.is_staff = validated_data.get('is_staff', instance.is_staff)

        if 'user_permissions_list' in validated_data:
            instance.user_permissions.set(validated_data['user_permissions_list'])

        if 'groups' in validated_data:
            instance.groups.set(validated_data['groups'])

        instance.save()

        # Update Profile fields
        profile = instance.profile
        if 'employee_id' in profile_data:
            profile.employee_id = profile_data['employee_id']
        if 'is_active' in profile_data:
            profile.is_active = profile_data['is_active']
        if 'assigned_locations' in profile_data:
            profile.assigned_locations.set(profile_data['assigned_locations'])

        profile.save()
        return instance

class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    assigned_locations_display = serializers.StringRelatedField(source='assigned_locations', many=True, read_only=True)

    class Meta:
        model = UserProfile
        fields = ('id', 'user', 'employee_id', 'assigned_locations', 'assigned_locations_display', 'is_active', 'created_at', 'updated_at')

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    employee_id = serializers.CharField(required=False, write_only=True)
    assigned_locations = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Location.objects.all(), required=False, write_only=True
    )

    class Meta:
        model = User
        fields = ('username', 'password', 'email', 'first_name', 'last_name', 'employee_id', 'assigned_locations')

    def create(self, validated_data):
        employee_id = validated_data.pop('employee_id', None)
        assigned_locations = validated_data.pop('assigned_locations', [])
        
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', '')
        )
        
        # Profile is created by signal, so we catch it and update
        profile, created = UserProfile.objects.get_or_create(user=user)
        if employee_id:
            profile.employee_id = employee_id
        if assigned_locations:
            profile.assigned_locations.set(assigned_locations)
        profile.save()
        
        return user

class GroupSerializer(serializers.ModelSerializer):
    """Role serializer backed by the capability manifest.

    Input (preferred): `module_selections` — a dict like
        {"users": "manage", "roles": "view"}
    which is resolved via apply_module_selections() into the underlying perms.

    Input (fallback, legacy / superuser escape hatch): `permissions` — a flat
    list of Permission IDs. Kept so raw assignment still works from the Django
    admin and tests.

    Output always includes both `module_selections` (derived) and
    `permissions_details` so the UI can choose its representation.
    """

    permissions_details = serializers.SerializerMethodField()
    module_selections = serializers.SerializerMethodField()
    permissions = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Permission.objects.all(),
        required=False,
    )

    class Meta:
        model = Group
        fields = (
            'id', 'name',
            'permissions', 'permissions_details',
            'module_selections',
        )

    def get_permissions_details(self, obj):
        perms = obj.permissions.select_related('content_type')
        return [
            {
                'id': p.id,
                'name': p.name,
                'codename': p.codename,
                'model': p.content_type.model
            }
            for p in perms
        ]

    def get_module_selections(self, obj):
        """Back-compute the highest matching level per module for this group."""
        from ams.permissions_manifest import LEVEL_ORDER
        held = {f"{p.content_type.app_label}.{p.codename}" for p in obj.permissions.select_related('content_type')}
        out: dict[str, str | None] = {}
        for module, levels in MODULES.items():
            current: str | None = None
            for level_name in LEVEL_ORDER:
                if level_name not in levels:
                    continue
                if set(levels[level_name]["perms"]).issubset(held):
                    current = level_name
            out[module] = current
        return out

    def _pop_module_selections(self):
        """Extract module_selections from raw request.data (not in validated_data)."""
        request = self.context.get('request')
        if request is None:
            return None
        raw = request.data.get('module_selections')
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise serializers.ValidationError({'module_selections': 'Must be an object mapping module -> level.'})
        # Validate keys/values against the manifest
        for module, level in raw.items():
            if module not in MODULES:
                raise serializers.ValidationError({'module_selections': f"Unknown module: {module!r}"})
            if level not in (None, 'none') and level not in MODULES[module]:
                raise serializers.ValidationError({'module_selections': f"Unknown level {level!r} for module {module!r}"})
        return raw

    def create(self, validated_data):
        module_selections = self._pop_module_selections()
        permissions = validated_data.pop('permissions', None)
        group = Group.objects.create(name=validated_data['name'])
        if module_selections is not None:
            apply_module_selections(group, module_selections)
        elif permissions:
            group.permissions.set(permissions)
        return group

    def update(self, instance, validated_data):
        module_selections = self._pop_module_selections()
        permissions = validated_data.pop('permissions', serializers.empty)
        if 'name' in validated_data:
            instance.name = validated_data['name']
            instance.save()
        if module_selections is not None:
            apply_module_selections(instance, module_selections)
        elif permissions is not serializers.empty:
            instance.permissions.set(permissions or [])
        return instance
