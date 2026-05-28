from rest_framework import serializers
from django.db import models
from ..models.instance_model import ItemInstance
from ..services.depreciation_service import depreciation_summary_for_asset, empty_depreciation_summary


class ItemInstanceSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    item_code = serializers.CharField(source='item.code', read_only=True)
    item_category_name = serializers.CharField(source='item.category.name', read_only=True)
    item_model_number = serializers.CharField(source='item.model_number', read_only=True)
    location_name = serializers.SerializerMethodField()
    location_code = serializers.SerializerMethodField()
    full_location_path = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    
    in_charge = serializers.SerializerMethodField()
    authority_store_name = serializers.SerializerMethodField()
    authority_store_code = serializers.SerializerMethodField()
    
    # New fields for inspection certificate and allocation
    inspection_certificate = serializers.CharField(source='inspection_certificate.contract_no', read_only=True, allow_null=True)
    inspection_certificate_id = serializers.PrimaryKeyRelatedField(source='inspection_certificate', read_only=True)
    allocated_to = serializers.SerializerMethodField()
    allocated_to_type = serializers.SerializerMethodField()
    stock_entry_ids = serializers.SerializerMethodField()
    depreciation_summary = serializers.SerializerMethodField()

    class Meta:
        model = ItemInstance
        fields = [
            'id', 'item', 'item_name', 'item_code', 'item_category_name', 'item_model_number',
            'serial_number', 'qr_code', 'qr_code_image',
            'current_location', 'location_name', 'location_code', 'full_location_path',
            'authority_store', 'status', 'in_charge', 'authority_store_name', 'authority_store_code',
            'inspection_certificate', 'inspection_certificate_id', 'allocated_to', 'allocated_to_type',
            'stock_entry_ids', 'depreciation_summary', 'is_active', 'created_at', 'updated_at', 'created_by_name'
        ]
        read_only_fields = ('authority_store', 'created_at', 'updated_at', 'created_by')

    def _get_latest_allocation(self, obj):
        """
        Get the latest active allocation using prefetched data (avoids N+1 queries).
        Falls back to DB query if not prefetched.
        """
        # Use prefetched allocations if available (from optimized viewset)
        if hasattr(obj, '_prefetched_allocations'):
            allocations = obj._prefetched_allocations
            if allocations:
                return allocations[0]  # Already ordered by -allocated_at in prefetch

        allocation_by_instance = self.context.get('allocation_by_instance')
        if allocation_by_instance is not None:
            return allocation_by_instance.get(obj.id)
        
        # Fallback: Use the same allocation across all three methods
        # Cache on the object to avoid repeated queries in same serialization
        if not hasattr(obj, '_cached_allocation'):
            from ..models.allocation_model import StockAllocation, AllocationStatus
            obj._cached_allocation = StockAllocation.objects.filter(
                item=obj.item,
                batch=None,
                status=AllocationStatus.ALLOCATED
            ).filter(
                stock_entry__items__instances=obj,
            ).filter(
                models.Q(allocated_to_person__isnull=False) | models.Q(allocated_to_location__isnull=False)
            ).select_related(
                'allocated_to_person',
                'allocated_to_location',
                'source_location'
            ).order_by('-allocated_at').first()
        
        return obj._cached_allocation

    def get_location_name(self, obj):
        latest_alloc = self._get_latest_allocation(obj) if obj.status == 'ALLOCATED' else None
        if latest_alloc and latest_alloc.allocated_to_person:
            return f"Allocated to {latest_alloc.allocated_to_person.name}"
        if latest_alloc and latest_alloc.allocated_to_location:
            return latest_alloc.allocated_to_location.name
        return obj.current_location.name if obj.current_location else None

    def get_location_code(self, obj):
        latest_alloc = self._get_latest_allocation(obj) if obj.status == 'ALLOCATED' else None
        if latest_alloc and latest_alloc.allocated_to_person:
            return 'PERSON'
        if latest_alloc and latest_alloc.allocated_to_location:
            return latest_alloc.allocated_to_location.code
        return obj.current_location.code if obj.current_location else None

    def get_full_location_path(self, obj):
        latest_alloc = self._get_latest_allocation(obj) if obj.status == 'ALLOCATED' else None
        if latest_alloc and latest_alloc.allocated_to_person:
            source_name = latest_alloc.source_location.name if latest_alloc.source_location else None
            return f"{source_name} / {latest_alloc.allocated_to_person.name}" if source_name else latest_alloc.allocated_to_person.name
        if latest_alloc and latest_alloc.allocated_to_location:
            return latest_alloc.allocated_to_location.hierarchy_path
        return obj.current_location.hierarchy_path if obj.current_location else None

    def get_in_charge(self, obj):
        if obj.status == 'ALLOCATED':
            latest_alloc = self._get_latest_allocation(obj)
            
            if latest_alloc:
                if latest_alloc.allocated_to_person:
                    return latest_alloc.allocated_to_person.name
                if latest_alloc.allocated_to_location:
                    return latest_alloc.allocated_to_location.in_charge or latest_alloc.allocated_to_location.name
        
        return obj.current_location.in_charge or "N/A"

    def get_allocated_to(self, obj):
        """Get the person or location this instance is allocated to."""
        if obj.status == 'ALLOCATED':
            latest_alloc = self._get_latest_allocation(obj)
            
            if latest_alloc:
                if latest_alloc.allocated_to_person:
                    return latest_alloc.allocated_to_person.name
                if latest_alloc.allocated_to_location:
                    return latest_alloc.allocated_to_location.name
        return None

    def get_allocated_to_type(self, obj):
        """Get the type of allocation: PERSON or LOCATION."""
        if obj.status == 'ALLOCATED':
            latest_alloc = self._get_latest_allocation(obj)
            
            if latest_alloc:
                if latest_alloc.allocated_to_person:
                    return 'PERSON'
                if latest_alloc.allocated_to_location:
                    return 'LOCATION'
        return None

    def get_stock_entry_ids(self, obj):
        stock_entry_ids_by_instance = self.context.get('stock_entry_ids_by_instance')
        if stock_entry_ids_by_instance is not None:
            return stock_entry_ids_by_instance.get(obj.id, [])
        return list(obj.stock_entry_items.values_list('stock_entry_id', flat=True).distinct())

    def get_depreciation_summary(self, obj):
        asset = getattr(obj, "fixed_asset_entry", None)
        return depreciation_summary_for_asset(asset) or empty_depreciation_summary()

    def get_authority_store_name(self, obj):
        if obj.authority_store:
            return obj.authority_store.name
        return "N/A"

    def get_authority_store_code(self, obj):
        if obj.authority_store:
            return obj.authority_store.code
        return "N/A"
