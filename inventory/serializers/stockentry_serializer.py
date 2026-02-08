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
    cancelled_by_name = serializers.CharField(source='cancelled_by.username', read_only=True, allow_null=True)
    can_acknowledge = serializers.SerializerMethodField()


    class Meta:
        model = StockEntry
        fields = (
            'id', 'entry_type', 'entry_number', 'entry_date', 
            'from_location', 'from_location_name', 
            'to_location', 'to_location_name',
            'issued_to', 'issued_to_name',
            'status', 'remarks', 'purpose', 'items',
            'cancellation_reason', 'cancelled_by', 'cancelled_by_name', 'cancelled_at',
            'created_by', 'created_by_name', 'created_at',
            'can_acknowledge'
        )
        read_only_fields = ('entry_number', 'created_by', 'created_at', 'cancelled_by', 'cancelled_at')


    def create(self, validated_data):
        items_data = validated_data.pop('items')
        request = self.context.get('request')
        if request and request.user:
            validated_data['created_by'] = request.user
        
        from ..models.stock_record_model import StockRecord
        from_location = validated_data.get('from_location')
        entry_type = validated_data.get('entry_type')

        # Validate stock availability for all items before creating anything
        if entry_type == 'ISSUE' and from_location:
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
                except StockRecord.DoesNotExist:
                    # If record doesn't exist, we'll let the model signals handle it (StockRecord creation)
                    pass

        from django.db import transaction
        with transaction.atomic():
            stock_entry = StockEntry.objects.create(**validated_data)
            
            for item_data in items_data:
                instances = item_data.pop('instances', [])
                item_entry = StockEntryItem.objects.create(stock_entry=stock_entry, **item_data)
                if instances:
                    item_entry.instances.set(instances)
        
        return stock_entry

    def update(self, instance, validated_data):
        if instance.status != 'DRAFT':
            raise serializers.ValidationError({"detail": "Only DRAFT entries can be edited."})
            
        items_data = validated_data.pop('items', None)
        
        from django.db import transaction
        with transaction.atomic():
            # Update main entry fields
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()
            
            # Update nested items if provided
            if items_data is not None:
                # Simple approach: clear and recreate
                # (Appropriate since Draft entries don't have side effects yet)
                instance.items.all().delete()
                for item_data in items_data:
                    instances = item_data.pop('instances', [])
                    item_entry = StockEntryItem.objects.create(stock_entry=instance, **item_data)
                    if instances:
                        item_entry.instances.set(instances)
                        
        return instance

    def get_can_acknowledge(self, obj):
        request = self.context.get('request')
        if not request or not request.user:
            return False
        
        user = request.user
        if user.is_superuser:
            return True if obj.status == 'PENDING_ACK' and obj.entry_type in ['RECEIPT', 'RETURN'] else False

        # Must be PENDING_ACK (RECEIPT or RETURN)
        if obj.status != 'PENDING_ACK' or obj.entry_type not in ['RECEIPT', 'RETURN']:
            return False

        # Must have permission
        if not user.has_perm('inventory.acknowledge_stockentry'):
            return False

        # Must have location access to the destination
        if hasattr(user, 'profile') and obj.to_location:
            return user.profile.has_location_access(obj.to_location)

        return False

