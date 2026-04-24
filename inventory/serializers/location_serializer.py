from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from ..models.location_model import Location

class LocationSerializer(serializers.ModelSerializer):
    parent_location_display = serializers.StringRelatedField(source='parent_location', read_only=True)
    main_store_name = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=True)
    main_store_id = serializers.SerializerMethodField()
    main_store_display = serializers.SerializerMethodField()
    main_store_code = serializers.SerializerMethodField()

    def get_main_store_id(self, obj):
        return obj.auto_created_store_id

    def get_main_store_display(self, obj):
        return obj.auto_created_store.name if obj.auto_created_store else None

    def get_main_store_code(self, obj):
        return obj.auto_created_store.code if obj.auto_created_store else None

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

    def create(self, validated_data):
        main_store_name = validated_data.pop('main_store_name', '')
        location = Location(**validated_data)
        location._main_store_name = main_store_name
        location.save()
        return location
    
    class Meta:
        model = Location
        fields = '__all__'
        read_only_fields = ('created_by', 'hierarchy_level', 'hierarchy_path', 'auto_created_store')
