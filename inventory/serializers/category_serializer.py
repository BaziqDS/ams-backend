from rest_framework import serializers
from ..models.category_model import Category, CategoryRateHistory

class RateHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source='changed_by.username', read_only=True)
    
    class Meta:
        model = CategoryRateHistory
        fields = ['rate', 'changed_at', 'changed_by_name', 'notes']

class CategorySerializer(serializers.ModelSerializer):
    parent_category_display = serializers.StringRelatedField(source='parent_category', read_only=True)
    resolved_category_type = serializers.CharField(source='get_category_type', read_only=True)
    resolved_tracking_type = serializers.CharField(source='get_tracking_type', read_only=True)
    resolved_depreciation_rate = serializers.DecimalField(source='get_depreciation_rate', max_digits=5, decimal_places=2, read_only=True)
    rate_history = RateHistorySerializer(many=True, read_only=True)
    notes = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Category
        fields = [
            'id', 'name', 'code', 'parent_category', 'parent_category_display',
            'category_type', 'tracking_type', 'default_depreciation_rate',
            'resolved_category_type', 'resolved_tracking_type', 'resolved_depreciation_rate',
            'rate_history', 'is_active', 'created_at', 'updated_at', 'notes'
        ]
        read_only_fields = ('created_by',)

    def create(self, validated_data):
        request_user = validated_data.pop('request_user', None)
        audit_notes = validated_data.pop('audit_notes', None)
        validated_data.pop('notes', None)
        instance = Category(**validated_data)
        instance.save(request_user=request_user, audit_notes=audit_notes)
        return instance

    def update(self, instance, validated_data):
        request_user = validated_data.pop('request_user', None)
        audit_notes = validated_data.pop('audit_notes', None)
        validated_data.pop('notes', None)

        if (
            'tracking_type' in validated_data
            and instance.parent_category_id
            and validated_data['tracking_type'] != instance.tracking_type
        ):
            raise serializers.ValidationError({
                'tracking_type': "Tracking type cannot be changed after subcategory creation.",
            })

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save(request_user=request_user, audit_notes=audit_notes)
        return instance
