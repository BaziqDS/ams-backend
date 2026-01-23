from rest_framework import serializers
from ..models.allocation_model import StockAllocation, AllocationStatus

class StockAllocationSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True, allow_null=True)
    source_location_name = serializers.CharField(source='source_location.name', read_only=True)
    allocated_to_person_name = serializers.CharField(source='allocated_to_person.name', read_only=True, allow_null=True)
    allocated_to_location_name = serializers.CharField(source='allocated_to_location.name', read_only=True, allow_null=True)
    allocated_by_name = serializers.CharField(source='allocated_by.username', read_only=True)
    entry_number = serializers.CharField(source='stock_entry.entry_number', read_only=True, allow_null=True)

    class Meta:
        model = StockAllocation
        fields = (
            'id', 'item', 'item_name', 'batch', 'batch_number',
            'source_location', 'source_location_name',
            'allocated_to_person', 'allocated_to_person_name',
            'allocated_to_location', 'allocated_to_location_name',
            'quantity', 'status', 'stock_entry', 'entry_number',
            'allocated_by', 'allocated_by_name', 'allocated_at',
            'return_date', 'remarks'
        )
        read_only_fields = ('allocated_by', 'allocated_at', 'return_date')
