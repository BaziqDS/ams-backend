from rest_framework import serializers
from ..models.instance_model import ItemInstance

class ItemInstanceSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    item_code = serializers.CharField(source='item.code', read_only=True)
    location_name = serializers.CharField(source='current_location.name', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True, allow_null=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = ItemInstance
        fields = [
            'id', 'item', 'item_name', 'item_code', 'batch', 'batch_number',
            'serial_number', 'qr_code', 'current_location', 'location_name',
            'status', 'is_active', 'created_at', 'updated_at', 'created_by_name'
        ]
        read_only_fields = ('created_at', 'updated_at', 'created_by')
