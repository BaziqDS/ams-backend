from rest_framework import serializers
from ..models.stock_record_model import StockRecord

class StockRecordSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source='location.name', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True, allow_null=True)
    item_name = serializers.CharField(source='item.name', read_only=True)

    class Meta:
        model = StockRecord
        fields = [
            'id', 'item', 'item_name', 'batch', 'batch_number', 
            'location', 'location_name', 'quantity', 'last_updated'
        ]
