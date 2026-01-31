from rest_framework import serializers
from django.contrib.auth.models import User, Permission, Group
from .models import UserProfile
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

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name', 'password',
            'is_superuser', 'is_staff', 'is_active', 'power_level',
            'employee_id', 'assigned_locations', 'assigned_locations_display',
            'user_permissions_list', 'groups', 'groups_display'
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and request.user and hasattr(request.user, 'profile'):
            # Filter assigned_locations to only those the requester has access to
            self.fields['assigned_locations'].queryset = request.user.profile.get_descendant_locations()

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
    permissions_details = serializers.SerializerMethodField()
    permissions = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Permission.objects.all(),
        required=False
    )

    class Meta:
        model = Group
        fields = ('id', 'name', 'permissions', 'permissions_details')

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
