from rest_framework import serializers
from ..models.batch_model import ItemBatch

class ItemBatchSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    item_code = serializers.CharField(source='item.code', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = ItemBatch
        fields = [
            'id', 'item', 'item_name', 'item_code', 'batch_number',
            'manufactured_date', 'expiry_date', 'is_active',
            'created_at', 'updated_at', 'created_by_name'
        ]
        read_only_fields = ('created_at', 'updated_at', 'created_by')
