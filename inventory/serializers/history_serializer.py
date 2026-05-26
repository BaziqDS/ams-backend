from rest_framework import serializers
from ..models.allocation_model import StockAllocation
from ..models.history_model import MovementHistory

class MovementHistorySerializer(serializers.ModelSerializer):
    performed_by_name = serializers.CharField(source='performed_by.username', read_only=True)
    from_location_name = serializers.CharField(source='from_location.name', read_only=True)
    to_location_name = serializers.CharField(source='to_location.name', read_only=True)
    item_name = serializers.CharField(source='item.name', read_only=True)
    instance_serial = serializers.CharField(source='instance.serial_number', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)
    entry_number = serializers.CharField(source='stock_entry.entry_number', read_only=True)
    allocation_target_type = serializers.SerializerMethodField()
    allocation_target_name = serializers.SerializerMethodField()

    def _resolved_allocation(self, obj):
        if obj.allocation_id:
            return obj.allocation
        if obj.action != 'ALLOCATE' or not obj.stock_entry_id:
            return None

        cached = getattr(obj, '_resolved_allocation_cache', None)
        if cached is not None:
            return cached

        queryset = StockAllocation.objects.select_related(
            'allocated_to_person',
            'allocated_to_location',
        ).filter(
            stock_entry_id=obj.stock_entry_id,
            item_id=obj.item_id,
        )
        if obj.batch_id:
            queryset = queryset.filter(batch_id=obj.batch_id)
        allocation = queryset.order_by('-allocated_at', '-id').first()
        obj._resolved_allocation_cache = allocation
        return allocation

    def get_allocation_target_type(self, obj):
        allocation = self._resolved_allocation(obj)
        if not allocation:
            return None
        if allocation.allocated_to_person_id:
            return 'PERSON'
        if allocation.allocated_to_location_id:
            return 'LOCATION'
        return None

    def get_allocation_target_name(self, obj):
        allocation = self._resolved_allocation(obj)
        if not allocation:
            return None
        if allocation.allocated_to_person_id:
            return allocation.allocated_to_person.name
        if allocation.allocated_to_location_id:
            return allocation.allocated_to_location.name
        return None

    class Meta:
        model = MovementHistory
        fields = [
            'id', 'item', 'item_name', 'instance', 'instance_serial', 'batch', 'batch_number',
            'action', 'from_location', 'from_location_name', 'to_location', 'to_location_name',
            'stock_entry', 'entry_number', 'allocation', 'allocation_target_type', 'allocation_target_name', 'quantity',
            'performed_by', 'performed_by_name', 'timestamp', 'remarks'
        ]
        read_only_fields = ('timestamp', 'performed_by')
