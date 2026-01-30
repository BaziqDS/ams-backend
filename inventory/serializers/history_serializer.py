from rest_framework import serializers
from ..models.history_model import MovementHistory

class MovementHistorySerializer(serializers.ModelSerializer):
    performed_by_name = serializers.CharField(source='performed_by.username', read_only=True)
    from_location_name = serializers.CharField(source='from_location.name', read_only=True)
    to_location_name = serializers.CharField(source='to_location.name', read_only=True)
    item_name = serializers.CharField(source='item.name', read_only=True)
    instance_serial = serializers.CharField(source='instance.serial_number', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)
    entry_number = serializers.CharField(source='stock_entry.entry_number', read_only=True)

    class Meta:
        model = MovementHistory
        fields = [
            'id', 'item', 'item_name', 'instance', 'instance_serial', 'batch', 'batch_number',
            'action', 'from_location', 'from_location_name', 'to_location', 'to_location_name',
            'stock_entry', 'entry_number', 'allocation', 'quantity', 
            'performed_by', 'performed_by_name', 'timestamp', 'remarks'
        ]
        read_only_fields = ('timestamp', 'performed_by')
