from rest_framework import serializers
from ..models.batch_model import ItemBatch
from ..services.depreciation_service import depreciation_summary_for_asset, empty_depreciation_summary

class ItemBatchSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    item_code = serializers.CharField(source='item.code', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    quantity = serializers.IntegerField(read_only=True)
    in_transit_quantity = serializers.IntegerField(read_only=True)
    allocated_quantity = serializers.IntegerField(read_only=True)
    available_quantity = serializers.SerializerMethodField()
    depreciation_summary = serializers.SerializerMethodField()

    def get_available_quantity(self, obj):
        quantity = getattr(obj, 'quantity', 0) or 0
        in_transit = getattr(obj, 'in_transit_quantity', 0) or 0
        allocated = getattr(obj, 'allocated_quantity', 0) or 0
        return max(0, quantity - in_transit - allocated)

    def get_depreciation_summary(self, obj):
        asset = getattr(obj, "fixed_asset_entry", None)
        return depreciation_summary_for_asset(asset) or empty_depreciation_summary()

    class Meta:
        model = ItemBatch
        fields = [
            'id', 'item', 'item_name', 'item_code', 'batch_number',
            'manufactured_date', 'expiry_date',
            'quantity', 'available_quantity', 'in_transit_quantity', 'allocated_quantity',
            'depreciation_summary', 'is_active',
            'created_at', 'updated_at', 'created_by_name'
        ]
        read_only_fields = ('created_at', 'updated_at', 'created_by')
