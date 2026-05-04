from django.db.models import Sum
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from ..models.allocation_model import AllocationStatus, StockAllocation
from ..models.person_model import Person
from ..models.stockentry_model import StockEntry, StockEntryItem
from ..models.correction_model import CorrectionStatus
from ..models.item_model import Item
from ..models.batch_model import ItemBatch
from ..models.instance_model import ItemInstance
from ..models.stock_record_model import StockRecord
from ..models.category_model import CategoryType, TrackingType

class PersonSerializer(serializers.ModelSerializer):
    standalone_locations_display = serializers.StringRelatedField(source='standalone_locations', many=True, read_only=True)

    class Meta:
        model = Person
        fields = [
            'id', 'name', 'designation', 'department', 
            'standalone_locations', 'standalone_locations_display',
            'is_active', 'created_at', 'updated_at'
        ]

class StockEntryItemSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True, allow_null=True)
    stock_register_name = serializers.CharField(source='stock_register.register_number', read_only=True)
    ack_stock_register_name = serializers.CharField(source='ack_stock_register.register_number', read_only=True, allow_null=True)
    
    class Meta:
        model = StockEntryItem
        fields = (
            'id', 'item', 'item_name', 'batch', 'batch_number', 'quantity', 'instances',
            'stock_register', 'stock_register_name', 'page_number',
            'ack_stock_register', 'ack_stock_register_name', 'ack_page_number',
            'accepted_quantity', 'accepted_instances'
        )

class StockEntrySerializer(serializers.ModelSerializer):
    items = StockEntryItemSerializer(many=True)
    inspection_certificate = serializers.PrimaryKeyRelatedField(read_only=True)
    inspection_certificate_number = serializers.CharField(source='inspection_certificate.contract_no', read_only=True, allow_null=True)
    from_location_name = serializers.CharField(source='from_location.name', read_only=True)
    to_location_name = serializers.CharField(source='to_location.name', read_only=True)
    issued_to_name = serializers.CharField(source='issued_to.name', read_only=True, allow_null=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    acknowledged_by_name = serializers.CharField(source='acknowledged_by.username', read_only=True, allow_null=True)
    cancelled_by_name = serializers.CharField(source='cancelled_by.username', read_only=True, allow_null=True)
    can_acknowledge = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_correct = serializers.SerializerMethodField()
    can_request_reversal = serializers.SerializerMethodField()
    active_correction = serializers.SerializerMethodField()
    correction_status = serializers.SerializerMethodField()
    generated_correction_entries = serializers.SerializerMethodField()
    replacement_entry = serializers.SerializerMethodField()


    class Meta:
        model = StockEntry
        fields = (
            'id', 'entry_type', 'entry_number', 'entry_date', 
            'inspection_certificate', 'inspection_certificate_number',
            'from_location', 'from_location_name', 
            'to_location', 'to_location_name',
            'issued_to', 'issued_to_name',
            'status', 'remarks', 'purpose', 'items', 'reference_entry',
            'reference_purpose',
            'acknowledged_by', 'acknowledged_by_name', 'acknowledged_at',
            'cancellation_reason', 'cancelled_by', 'cancelled_by_name', 'cancelled_at',
            'created_by', 'created_by_name', 'created_at',
            'can_acknowledge', 'can_cancel', 'can_correct', 'can_request_reversal',
            'active_correction', 'correction_status', 'generated_correction_entries',
            'replacement_entry',
        )
        read_only_fields = ('entry_number', 'created_by', 'created_at', 'acknowledged_by', 'acknowledged_at', 'cancelled_by', 'cancelled_at')

    def _should_auto_split_consumable_issue_item(self, entry_type, from_location, item_data):
        if entry_type != 'ISSUE' or not from_location:
            return False

        item = item_data.get('item')
        batch = item_data.get('batch')
        if not item or batch is not None:
            return False

        category = getattr(item, 'category', None)
        if not category:
            return False

        return (
            category.get_tracking_type() == TrackingType.QUANTITY and
            category.get_category_type() == CategoryType.CONSUMABLE
        )

    def _expand_consumable_issue_items(self, entry_type, from_location, items_data):
        if entry_type != 'ISSUE' or not from_location:
            return items_data

        expanded_items = []

        for item_data in items_data:
            if not self._should_auto_split_consumable_issue_item(entry_type, from_location, item_data):
                expanded_items.append(item_data)
                continue

            item = item_data['item']
            remaining_quantity = item_data.get('quantity') or 0
            matched_any_batch = False

            batched_records = list(
                StockRecord.objects.filter(item=item, location=from_location)
                .exclude(batch=None)
                .select_related('batch')
                .order_by('batch__created_at', 'batch_id', 'id')
            )
            null_batch_records = list(
                StockRecord.objects.filter(item=item, location=from_location, batch=None)
                .select_related('batch')
                .order_by('id')
            )

            for record in [*batched_records, *null_batch_records]:
                if remaining_quantity <= 0:
                    break

                available_quantity = record.available_quantity
                if available_quantity <= 0:
                    continue

                take_quantity = min(remaining_quantity, available_quantity)
                if take_quantity <= 0:
                    continue

                matched_any_batch = True
                expanded_items.append({
                    **item_data,
                    'batch': record.batch,
                    'quantity': take_quantity,
                })
                remaining_quantity -= take_quantity

            if remaining_quantity > 0:
                expanded_items.append({
                    **item_data,
                    'batch': None,
                    'quantity': remaining_quantity,
                })
            elif not matched_any_batch:
                expanded_items.append(item_data)

        return expanded_items

    def _validate_assigned_creation_store(self, errors, entry_type, from_location, to_location):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or user.is_superuser:
            return

        if not hasattr(user, 'profile'):
            errors['from_location' if entry_type == 'ISSUE' else 'to_location'] = (
                'A directly assigned store is required to create stock entries.'
            )
            return

        if entry_type == 'ISSUE':
            store = from_location
            field = 'from_location'
        elif entry_type == 'RECEIPT':
            store = to_location
            field = 'to_location'
        else:
            return

        if not store or not getattr(store, 'is_store', False):
            return

        assigned_store_ids = set(
            user.profile.assigned_locations.filter(
                is_active=True,
                is_store=True,
            ).values_list('id', flat=True)
        )
        if store.id not in assigned_store_ids:
            errors[field] = 'Select a store directly assigned to this user.'

    def validate(self, attrs):
        candidate = self.instance or StockEntry()
        for field, value in attrs.items():
            if field != 'items':
                setattr(candidate, field, value)

        entry_type = attrs.get('entry_type', getattr(candidate, 'entry_type', None))
        from_location = attrs.get('from_location', getattr(candidate, 'from_location', None))
        to_location = attrs.get('to_location', getattr(candidate, 'to_location', None))
        issued_to = attrs.get('issued_to', getattr(candidate, 'issued_to', None))

        errors = {}
        if entry_type == 'RETURN':
            errors['entry_type'] = 'Create a receipt entry when receiving returned stock.'

        if entry_type == 'ISSUE':
            if not from_location or not getattr(from_location, 'is_store', False):
                errors['from_location'] = 'Source store is required.'
            if issued_to and to_location:
                errors['issued_to'] = 'Choose either a receiving person or a destination location, not both.'
            if not issued_to and not to_location:
                errors['to_location'] = 'Destination store, non-store location, or receiving person is required.'
        elif entry_type == 'RECEIPT':
            if not to_location or not getattr(to_location, 'is_store', False):
                errors['to_location'] = 'Receiving store is required.'
            if issued_to and from_location:
                errors['issued_to'] = 'Choose either a returning person or a returning location, not both.'
            if not issued_to and not from_location:
                errors['from_location'] = 'Returning person or location is required.'

            is_allocation_return = issued_to or (from_location and not getattr(from_location, 'is_store', False))
            if to_location and is_allocation_return:
                requested_by_item = {}
                items_data = attrs.get('items')
                if items_data is None and self.instance:
                    items_data = [
                        {
                            'item': entry_item.item,
                            'batch': entry_item.batch,
                            'quantity': entry_item.quantity,
                        }
                        for entry_item in self.instance.items.all()
                    ]

                for item_data in items_data or []:
                    item = item_data.get('item')
                    if not item:
                        continue
                    batch = item_data.get('batch')
                    item_id = item.pk if hasattr(item, 'pk') else item
                    batch_id = batch.pk if hasattr(batch, 'pk') else batch
                    key = (item_id, batch_id)
                    requested_by_item[key] = requested_by_item.get(key, 0) + (item_data.get('quantity') or 0)

                for (item_id, batch_id), requested_quantity in requested_by_item.items():
                    allocation_filter = {
                        'item_id': item_id,
                        'batch_id': batch_id,
                        'source_location': to_location,
                        'status': AllocationStatus.ALLOCATED,
                    }
                    if issued_to:
                        allocation_filter['allocated_to_person'] = issued_to
                    else:
                        allocation_filter['allocated_to_location'] = from_location

                    allocated_quantity = StockAllocation.objects.filter(**allocation_filter).aggregate(total=Sum('quantity'))['total'] or 0
                    if allocated_quantity < requested_quantity:
                        errors['items'] = (
                            'Returned items must match an active allocation from this receiving store '
                            'to the selected person or non-store location.'
                        )
                        break

        if from_location and to_location and from_location.pk == to_location.pk:
            errors['to_location'] = 'Destination cannot be the same as the source store.'
        self._validate_assigned_creation_store(errors, entry_type, from_location, to_location)
        if errors:
            raise serializers.ValidationError(errors)

        try:
            candidate.clean()
        except DjangoValidationError as exc:
            if hasattr(exc, 'message_dict'):
                raise serializers.ValidationError(exc.message_dict)
            raise serializers.ValidationError({'non_field_errors': exc.messages})
        return attrs

    def _creation_status(self, validated_data):
        entry_type = validated_data.get('entry_type')
        to_location = validated_data.get('to_location')
        issued_to = validated_data.get('issued_to')
        if entry_type == 'ISSUE' and (issued_to or (to_location and not to_location.is_store)):
            return 'COMPLETED'
        return 'PENDING_ACK'

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        request = self.context.get('request')
        if request and request.user:
            validated_data['created_by'] = request.user
        validated_data['status'] = self._creation_status(validated_data)

        from_location = validated_data.get('from_location')
        entry_type = validated_data.get('entry_type')
        items_data = self._expand_consumable_issue_items(entry_type, from_location, items_data)

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

    def _user_can_edit_entries(self):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        return bool(user and user.is_authenticated and (user.is_superuser or user.has_perm('inventory.edit_stock_entries')))

    def get_can_cancel(self, obj):
        return bool(obj.status == 'PENDING_ACK' and self._user_can_edit_entries())

    def get_can_correct(self, obj):
        return bool(obj.status == 'COMPLETED' and obj.from_location_id and self._user_can_edit_entries())

    def get_can_request_reversal(self, obj):
        return bool(
            obj.status == 'COMPLETED'
            and obj.entry_type == 'ISSUE'
            and obj.from_location_id
            and obj.to_location_id
            and getattr(obj.to_location, 'is_store', False)
            and self._user_can_edit_entries()
        )

    def _correction_source_entry(self, obj):
        if (
            obj.entry_type == 'RECEIPT'
            and obj.reference_entry_id
            and obj.reference_purpose == 'AUTO_RECEIPT'
        ):
            return obj.reference_entry
        return obj

    def _latest_correction(self, obj):
        correction_source = self._correction_source_entry(obj)
        return correction_source.correction_requests.order_by('-requested_at').first()

    def _serialize_correction_summary(self, correction):
        if not correction:
            return None
        return {
            'id': correction.id,
            'original_entry': correction.original_entry_id,
            'status': correction.status,
            'resolution_type': correction.resolution_type,
            'reason': correction.reason,
            'message': correction.message,
            'requested_at': correction.requested_at,
            'applied_at': correction.applied_at,
        }

    def get_active_correction(self, obj):
        correction_source = self._correction_source_entry(obj)
        correction = correction_source.correction_requests.exclude(
            status__in=[CorrectionStatus.APPLIED, CorrectionStatus.REJECTED]
        ).order_by('-requested_at').first()
        return self._serialize_correction_summary(correction)

    def get_correction_status(self, obj):
        correction = self._latest_correction(obj)
        return correction.status if correction else None

    def get_generated_correction_entries(self, obj):
        correction_source = self._correction_source_entry(obj)
        entries = StockEntry.objects.filter(
            generated_by_correction_requests__original_entry=correction_source
        ).distinct().order_by('id')
        return [
            {
                'id': entry.id,
                'entry_number': entry.entry_number,
                'entry_type': entry.entry_type,
                'status': entry.status,
                'reference_purpose': entry.reference_purpose,
            }
            for entry in entries
        ]

    def get_replacement_entry(self, obj):
        replacement = StockEntry.objects.filter(
            reference_entry=obj,
            reference_purpose='REPLACEMENT',
        ).order_by('-created_at').first()
        if not replacement:
            return None
        return {
            'id': replacement.id,
            'entry_number': replacement.entry_number,
            'entry_type': replacement.entry_type,
            'status': replacement.status,
        }

