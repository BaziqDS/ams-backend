from rest_framework import serializers
from ..models.location_model import Location

class LocationSerializer(serializers.ModelSerializer):
    parent_location_display = serializers.StringRelatedField(source='parent_location', read_only=True)
    
    class Meta:
        model = Location
        fields = '__all__'
        read_only_fields = ('created_by', 'hierarchy_level', 'hierarchy_path', 'auto_created_store')
