from rest_framework import serializers
from django.contrib.auth.models import User, Permission, Group
from .models import UserProfile
from .services.capability_service import (
    apply_module_selections,
    compute_capabilities_for_user,
    compute_inspection_stages_for_group,
)
from ams.permissions_manifest import MODULES, INSPECTION_STAGE_PERMS
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
        if request and request.user:
            # Scope assignable locations to the admin's own spatial boundary.
            # DRF uses this queryset for both dropdown data and payload
            # validation, so out-of-scope location IDs are rejected server-side.
            self.fields['assigned_locations'].queryset = self._assignable_locations_for_request_user()

    def _assignable_locations_for_request_user(self):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return Location.objects.none()
        if request.user.is_superuser:
            return Location.objects.filter(is_active=True)

        try:
            return request.user.profile.get_assignable_locations_for_user_management()
        except UserProfile.DoesNotExist:
            return Location.objects.none()

    def _request_user_has_global_location_scope(self):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        try:
            return request.user.profile.has_root_user_management_scope()
        except UserProfile.DoesNotExist:
            return False

    def _request_user_has_permission(self, codename):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        permission_name = codename if "." in codename else f"user_management.{codename}"
        return request.user.has_perm(permission_name)

    def validate_assigned_locations(self, locations):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return locations
        if request.user.is_superuser:
            return locations

        allowed_ids = set(
            self._assignable_locations_for_request_user().values_list('id', flat=True)
        )

        invalid = [location for location in locations if location.id not in allowed_ids]
        if invalid:
            raise serializers.ValidationError(
                "You can only assign users to your assigned locations and their sub-locations."
            )
        return locations

    def create(self, validated_data):
        profile_data = validated_data.pop('profile', {})
        user_permissions = validated_data.pop('user_permissions', [])
        groups = validated_data.pop('groups', [])
        password = validated_data.pop('password', None)

        if 'assigned_locations' in profile_data and not self._request_user_has_permission('assign_user_locations'):
            raise serializers.ValidationError({
                'assigned_locations': "You do not have permission to assign locations to users.",
            })

        if groups and not self._request_user_has_permission('assign_user_roles'):
            raise serializers.ValidationError({
                'groups': "You do not have permission to assign roles to users.",
            })

        if user_permissions and not self._request_user_has_permission('assign_user_roles'):
            raise serializers.ValidationError({
                'user_permissions_list': "You do not have permission to assign direct permissions to users.",
            })

        if (
            not self._request_user_has_global_location_scope()
            and not profile_data.get('assigned_locations')
        ):
            raise serializers.ValidationError({
                'assigned_locations': (
                    "Select at least one location within your assigned scope."
                ),
            })
        
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
        request = self.context.get('request')
        editing_self = (
            request is not None
            and request.user is not None
            and request.user.is_authenticated
            and instance.pk == request.user.pk
            and not request.user.is_superuser
        )

        if editing_self and 'assigned_locations' in profile_data:
            incoming_ids = {loc.pk for loc in profile_data['assigned_locations']}
            current_ids = set(
                instance.profile.assigned_locations.values_list('pk', flat=True)
            )
            if incoming_ids != current_ids:
                raise serializers.ValidationError({
                    'assigned_locations': (
                        "You cannot change locations on your own profile. "
                        "Ask an admin with broader scope to update them."
                    ),
                })

        if editing_self and 'groups' in validated_data:
            incoming_ids = {group.pk for group in validated_data['groups']}
            current_ids = set(instance.groups.values_list('pk', flat=True))
            if incoming_ids != current_ids:
                raise serializers.ValidationError({
                    'groups': (
                        "You cannot change roles on your own profile. "
                        "Ask an admin with broader scope to update them."
                    ),
                })

        if editing_self and 'user_permissions_list' in validated_data:
            incoming_ids = {perm.pk for perm in validated_data['user_permissions_list']}
            current_ids = set(instance.user_permissions.values_list('pk', flat=True))
            if incoming_ids != current_ids:
                raise serializers.ValidationError({
                    'user_permissions_list': (
                        "You cannot change permissions on your own profile. "
                        "Ask an admin with broader scope to update them."
                    ),
                })

        if (
            not editing_self
            and not self._request_user_has_global_location_scope()
            and 'assigned_locations' in profile_data
            and not profile_data['assigned_locations']
        ):
            raise serializers.ValidationError({
                'assigned_locations': (
                    "Select at least one location within your assigned scope."
                ),
            })

        if 'assigned_locations' in profile_data and not self._request_user_has_permission('assign_user_locations'):
            raise serializers.ValidationError({
                'assigned_locations': "You do not have permission to assign locations to users.",
            })

        if 'groups' in validated_data and not self._request_user_has_permission('assign_user_roles'):
            raise serializers.ValidationError({
                'groups': "You do not have permission to assign roles to users.",
            })

        if 'user_permissions_list' in validated_data and not self._request_user_has_permission('assign_user_roles'):
            raise serializers.ValidationError({
                'user_permissions_list': "You do not have permission to assign direct permissions to users.",
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
            'module_selections', 'inspection_stages',
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

    inspection_stages = serializers.SerializerMethodField()

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

    def get_inspection_stages(self, obj):
        """Return stage keys this group holds for the inspections module."""
        return compute_inspection_stages_for_group(obj)

    def _pop_module_selections(self):
        """Extract module_selections and inspection_stages from raw request.data."""
        request = self.context.get('request')
        if request is None:
            return None, None
        raw = request.data.get('module_selections')
        if raw is None:
            return None, None
        if not isinstance(raw, dict):
            raise serializers.ValidationError({'module_selections': 'Must be an object mapping module -> level.'})
        from ams.permissions_manifest import READ_PERMS
        for module, level in raw.items():
            if module not in MODULES and module in READ_PERMS:
                if level not in (None, 'none', 'view'):
                    raise serializers.ValidationError({'module_selections': f"Unknown level {level!r} for module {module!r}"})
                continue
            if module not in MODULES:
                raise serializers.ValidationError({'module_selections': f"Unknown module: {module!r}"})
            if level not in (None, 'none') and level not in MODULES[module]:
                raise serializers.ValidationError({'module_selections': f"Unknown level {level!r} for module {module!r}"})

        inspection_stages = request.data.get('inspection_stages')
        if inspection_stages is not None:
            if not isinstance(inspection_stages, list):
                raise serializers.ValidationError({'inspection_stages': 'Must be a list of stage keys.'})
            valid_keys = set(INSPECTION_STAGE_PERMS.keys())
            for key in inspection_stages:
                if key not in valid_keys:
                    raise serializers.ValidationError({'inspection_stages': f"Unknown stage: {key!r}"})

        return raw, inspection_stages

    def create(self, validated_data):
        module_selections, inspection_stages = self._pop_module_selections()
        permissions = validated_data.pop('permissions', None)
        group = Group.objects.create(name=validated_data['name'])
        if module_selections is not None:
            apply_module_selections(group, module_selections, inspection_stages)
        elif permissions:
            group.permissions.set(permissions)
        return group

    def update(self, instance, validated_data):
        module_selections, inspection_stages = self._pop_module_selections()
        permissions = validated_data.pop('permissions', serializers.empty)
        if 'name' in validated_data:
            instance.name = validated_data['name']
            instance.save()
        if module_selections is not None:
            apply_module_selections(instance, module_selections, inspection_stages)
        elif permissions is not serializers.empty:
            instance.permissions.set(permissions or [])
        return instance
