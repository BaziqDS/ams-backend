from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from ..models.location_model import Location

class LocationSerializer(serializers.ModelSerializer):
    parent_location_display = serializers.StringRelatedField(source='parent_location', read_only=True)

    def validate(self, attrs):
        candidate = self.instance or Location()
        for field, value in attrs.items():
            setattr(candidate, field, value)
        try:
            candidate.clean()
        except DjangoValidationError as exc:
            if hasattr(exc, 'message_dict'):
                raise serializers.ValidationError(exc.message_dict)
            raise serializers.ValidationError({'non_field_errors': exc.messages})
        return attrs
    
    class Meta:
        model = Location
        fields = '__all__'
        read_only_fields = ('created_by', 'hierarchy_level', 'hierarchy_path', 'auto_created_store')
