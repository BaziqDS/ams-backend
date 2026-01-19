from rest_framework import serializers
from django.contrib.auth.models import User
from .models import UserProfile
from inventory.models.location_model import Location

class UserSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'is_superuser', 'permissions')

    def get_permissions(self, obj):
        # Return all permissions (from groups and individual)
        return list(obj.get_all_permissions())

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
