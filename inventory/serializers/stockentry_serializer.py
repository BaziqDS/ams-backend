from django.utils import timezone
from rest_framework import serializers
from ..models.person_model import Person
from ..models.stockentry_model import StockEntry, StockEntryItem
from ..models.item_model import Item
from ..models.batch_model import ItemBatch
from ..models.instance_model import ItemInstance

class PersonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = '__all__'

class StockEntryItemSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True, allow_null=True)
    
    class Meta:
        model = StockEntryItem
        fields = ('id', 'item', 'item_name', 'batch', 'batch_number', 'quantity', 'instances')

class StockEntrySerializer(serializers.ModelSerializer):
    items = StockEntryItemSerializer(many=True)
    from_location_name = serializers.CharField(source='from_location.name', read_only=True)
    to_location_name = serializers.CharField(source='to_location.name', read_only=True)
    issued_to_name = serializers.CharField(source='issued_to.name', read_only=True, allow_null=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = StockEntry
        fields = (
            'id', 'entry_type', 'entry_number', 'entry_date', 
            'from_location', 'from_location_name', 
            'to_location', 'to_location_name',
            'issued_to', 'issued_to_name',
            'status', 'remarks', 'purpose', 'items',
            'created_by', 'created_by_name', 'created_at'
        )
        read_only_fields = ('entry_number', 'created_by', 'created_at')

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        request = self.context.get('request')
        if request and request.user:
            validated_data['created_by'] = request.user
        
        from ..models.stock_record_model import StockRecord
        from_location = validated_data.get('from_location')
        entry_type = validated_data.get('entry_type')

        # Validate stock availability for all items before creating anything
        if entry_type in ['ISSUE', 'TRANSFER', 'RETURN'] and from_location:
            for item_data in items_data:
                item = item_data.get('item')
                batch = item_data.get('batch')
                quantity = item_data.get('quantity')
                
                try:
                    record = StockRecord.objects.get(
                        item=item,
                        location=from_location,
                        batch=batch
                    )
                    if record.quantity < quantity:
                        raise serializers.ValidationError({
                            "items": f"Insufficient stock for {item.name}. Available: {record.quantity}, Requested: {quantity}"
                        })
                except StockRecord.DoesNotExist:
                    raise serializers.ValidationError({
                        "items": f"No stock found for {item.name} at the source location."
                    })

        from django.db import transaction
        with transaction.atomic():
            stock_entry = StockEntry.objects.create(**validated_data)
            
            for item_data in items_data:
                instances = item_data.pop('instances', [])
                item_entry = StockEntryItem.objects.create(stock_entry=stock_entry, **item_data)
                if instances:
                    item_entry.instances.set(instances)
        
        return stock_entry

