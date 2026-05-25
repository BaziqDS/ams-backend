from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from ..models.location_model import Location, LocationTag, LocationType
from ..services.deletion_policy import get_delete_blockers


class LocationTagSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    label = serializers.SerializerMethodField()

    def get_label(self, obj):
        return f"{obj.get_category_display()}: {obj.name}"

    def validate_name(self, value):
        normalized = ' '.join(value.split())
        queryset = LocationTag.objects.filter(name__iexact=normalized)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A tag with this name already exists.")
        return normalized
 
    class Meta:
        model = LocationTag
        fields = '__all__'


class LocationSerializer(serializers.ModelSerializer):
    parent_location_display = serializers.StringRelatedField(source='parent_location', read_only=True)
    tags_display = LocationTagSerializer(source='tags', many=True, read_only=True)
    main_store_name = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=True)
    main_store_id = serializers.SerializerMethodField()
    main_store_display = serializers.SerializerMethodField()
    main_store_code = serializers.SerializerMethodField()
    root_main_store_id = serializers.SerializerMethodField()
    root_main_store_display = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    delete_blockers = serializers.SerializerMethodField()

    def get_delete_blockers(self, obj):
        return get_delete_blockers(obj)

    def get_can_delete(self, obj):
        return not self.get_delete_blockers(obj)

    def get_main_store_id(self, obj):
        return obj.auto_created_store_id

    def get_main_store_display(self, obj):
        return obj.auto_created_store.name if obj.auto_created_store else None

    def get_main_store_code(self, obj):
        return obj.auto_created_store.code if obj.auto_created_store else None

    def _get_root_location(self, obj):
        roots_by_code = self.context.get('root_locations_by_code') or {}
        root_code = (obj.hierarchy_path or obj.code or '').split('/')[0]
        if root_code in roots_by_code:
            return roots_by_code[root_code]

        current = obj
        while getattr(current, 'parent_location', None) is not None:
            current = current.parent_location
        return current

    def get_root_main_store_id(self, obj):
        root = self._get_root_location(obj)
        return root.auto_created_store_id if root and root.auto_created_store_id else None

    def get_root_main_store_display(self, obj):
        root = self._get_root_location(obj)
        return root.auto_created_store.name if root and root.auto_created_store else None

    def validate(self, attrs):
        if attrs.get('location_type') == LocationType.STORE and 'is_store' not in attrs:
            attrs['is_store'] = True

        candidate = self.instance or Location()
        for field, value in attrs.items():
            if field == 'tags':
                continue
            setattr(candidate, field, value)
        try:
            candidate.clean()
        except DjangoValidationError as exc:
            if hasattr(exc, 'message_dict'):
                raise serializers.ValidationError(exc.message_dict)
            raise serializers.ValidationError({'non_field_errors': exc.messages})
        return attrs

    def create(self, validated_data):
        tags = validated_data.pop('tags', [])
        main_store_name = validated_data.pop('main_store_name', '')
        location = Location(**validated_data)
        location._main_store_name = main_store_name
        location.save()
        if tags:
            location.tags.set(tags)
        return location

    def update(self, instance, validated_data):
        tags = validated_data.pop('tags', None)
        instance = super().update(instance, validated_data)
        if tags is not None:
            instance.tags.set(tags)
        return instance
    
    class Meta:
        model = Location
        fields = '__all__'
        read_only_fields = ('created_by', 'hierarchy_level', 'hierarchy_path', 'auto_created_store')
