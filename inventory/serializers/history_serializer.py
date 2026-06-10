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
    stock_register = serializers.SerializerMethodField()
    stock_register_name = serializers.SerializerMethodField()
    ack_stock_register = serializers.SerializerMethodField()
    ack_stock_register_name = serializers.SerializerMethodField()

    def _stock_entry_item(self, obj):
        if not obj.stock_entry_id:
            return None
        cached = getattr(obj, '_stock_entry_item_cache', 'missing')
        if cached != 'missing':
            return cached

        from ..models.stockentry_model import StockEntryItem
        queryset = StockEntryItem.objects.select_related(
            'stock_register',
            'ack_stock_register',
        ).filter(
            stock_entry_id=obj.stock_entry_id,
            item_id=obj.item_id,
        )
        if obj.batch_id:
            queryset = queryset.filter(batch_id=obj.batch_id)
        entry_item = queryset.first()
        obj._stock_entry_item_cache = entry_item
        return entry_item

    def get_stock_register(self, obj):
        entry_item = self._stock_entry_item(obj)
        return entry_item.stock_register_id if entry_item else None

    def get_stock_register_name(self, obj):
        entry_item = self._stock_entry_item(obj)
        if entry_item and entry_item.stock_register_id:
            return entry_item.stock_register.register_number
        return None

    def get_ack_stock_register(self, obj):
        entry_item = self._stock_entry_item(obj)
        return entry_item.ack_stock_register_id if entry_item else None

    def get_ack_stock_register_name(self, obj):
        entry_item = self._stock_entry_item(obj)
        if entry_item and entry_item.ack_stock_register_id:
            return entry_item.ack_stock_register.register_number
        return None

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
            'stock_entry', 'entry_number',
            'stock_register', 'stock_register_name', 'ack_stock_register', 'ack_stock_register_name',
            'allocation', 'allocation_target_type', 'allocation_target_name', 'quantity',
            'performed_by', 'performed_by_name', 'timestamp', 'remarks'
        ]
        read_only_fields = ('timestamp', 'performed_by')
