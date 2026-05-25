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
from ..models.inspection_model import InspectionItem
from ..models.instance_model import InstanceStatus, ItemInstance
from ..models.stock_record_model import StockRecord
from ..models.category_model import TrackingType
from ..services.deletion_policy import get_delete_blockers

class PersonSerializer(serializers.ModelSerializer):
    standalone_locations_display = serializers.StringRelatedField(source='standalone_locations', many=True, read_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        field = self.fields.get('standalone_locations')
        if not field or not user or not user.is_authenticated or user.is_superuser:
            return

        from ..models.location_model import Location

        if not hasattr(user, 'profile'):
            field.child_relation.queryset = Location.objects.none()
            return

        profile = user.profile
        if profile.power_level == 0:
            field.child_relation.queryset = Location.objects.filter(is_active=True, is_standalone=True)
            return

        accessible_locs = profile.get_location_view_locations()
        standalone_ids = set(
            accessible_locs.filter(is_standalone=True).values_list('id', flat=True)
        )
        standalone_ids.update(
            accessible_locs.exclude(parent_location__isnull=True)
            .filter(parent_location__is_standalone=True)
            .values_list('parent_location_id', flat=True)
        )
        field.child_relation.queryset = Location.objects.filter(
            id__in=standalone_ids,
            is_active=True,
            is_standalone=True,
        )

    class Meta:
        model = Person
        fields = [
            'id', 'perse_number', 'name', 'designation', 'department',
            'standalone_locations', 'standalone_locations_display',
            'is_active', 'created_at', 'updated_at'
        ]
        extra_kwargs = {
            'perse_number': {'required': True, 'allow_blank': False, 'allow_null': False},
        }

    def validate_perse_number(self, value):
        if value is None or not str(value).strip():
            raise serializers.ValidationError('PERSE number is required.')
        return str(value).strip()

class StockEntryItemSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True, allow_null=True)
    stock_register_name = serializers.CharField(source='stock_register.register_number', read_only=True)
    ack_stock_register_name = serializers.CharField(source='ack_stock_register.register_number', read_only=True, allow_null=True)
    source_inspection = serializers.SerializerMethodField()
    source_inspection_number = serializers.SerializerMethodField()
    source_inspection_item = serializers.SerializerMethodField()
    source_inspection_department = serializers.SerializerMethodField()

    def _source_inspection_item(self, obj):
        batch_number = getattr(obj.batch, 'batch_number', None)
        if not obj.batch_id or not batch_number:
            return None
        cached = getattr(obj, '_source_inspection_item_cache', None)
        if cached is not None:
            return cached

        source = (
            InspectionItem.objects
            .select_related('inspection_certificate', 'inspection_certificate__department')
            .filter(item_id=obj.item_id, batch_number=batch_number)
            .order_by('-inspection_certificate__date', '-id')
            .first()
        )
        obj._source_inspection_item_cache = source
        return source

    def get_source_inspection(self, obj):
        source = self._source_inspection_item(obj)
        return source.inspection_certificate_id if source else None

    def get_source_inspection_number(self, obj):
        source = self._source_inspection_item(obj)
        return source.inspection_certificate.contract_no if source else None

    def get_source_inspection_item(self, obj):
        source = self._source_inspection_item(obj)
        return source.id if source else None

    def get_source_inspection_department(self, obj):
        source = self._source_inspection_item(obj)
        if not source or not source.inspection_certificate.department:
            return None
        return source.inspection_certificate.department.name
    
    class Meta:
        model = StockEntryItem
        fields = (
            'id', 'item', 'item_name', 'batch', 'batch_number', 'quantity', 'instances',
            'source_inspection', 'source_inspection_number', 'source_inspection_item',
            'source_inspection_department',
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
    can_delete = serializers.SerializerMethodField()
    delete_blockers = serializers.SerializerMethodField()


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
            'replacement_entry', 'can_delete', 'delete_blockers',
        )
        read_only_fields = ('entry_number', 'created_by', 'created_at', 'acknowledged_by', 'acknowledged_at', 'cancelled_by', 'cancelled_at')

    def get_delete_blockers(self, obj):
        return get_delete_blockers(obj)

    def get_can_delete(self, obj):
        return not self.get_delete_blockers(obj)

    def _should_auto_split_quantity_issue_item(self, entry_type, from_location, item_data):
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
            category.get_tracking_type() == TrackingType.QUANTITY
        )

    def _expand_quantity_issue_items(self, entry_type, from_location, items_data):
        if entry_type != 'ISSUE' or not from_location:
            return items_data

        expanded_items = []

        for item_data in items_data:
            if not self._should_auto_split_quantity_issue_item(entry_type, from_location, item_data):
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

    def _allocation_return_filter(self, *, item, batch=None, source_location=None, issued_to=None, from_location=None):
        allocation_filter = {
            'item': item,
            'source_location': source_location,
            'status': AllocationStatus.ALLOCATED,
        }
        if batch is not None:
            allocation_filter['batch'] = batch
        if issued_to:
            allocation_filter['allocated_to_person'] = issued_to
        else:
            allocation_filter['allocated_to_location'] = from_location
        return allocation_filter

    def _should_auto_split_quantity_return_item(self, entry_type, to_location, issued_to, from_location, item_data):
        if entry_type != 'RECEIPT' or not to_location:
            return False

        if not (issued_to or (from_location and not getattr(from_location, 'is_store', False))):
            return False

        item = item_data.get('item')
        batch = item_data.get('batch')
        if not item or batch is not None:
            return False

        category = getattr(item, 'category', None)
        if not category:
            return False

        return category.get_tracking_type() == TrackingType.QUANTITY

    def _expand_quantity_return_items(self, entry_type, to_location, issued_to, from_location, items_data):
        if entry_type != 'RECEIPT' or not to_location:
            return items_data

        expanded_items = []

        for item_data in items_data:
            if not self._should_auto_split_quantity_return_item(entry_type, to_location, issued_to, from_location, item_data):
                expanded_items.append(item_data)
                continue

            item = item_data['item']
            remaining_quantity = item_data.get('quantity') or 0
            allocation_filter = self._allocation_return_filter(
                item=item,
                source_location=to_location,
                issued_to=issued_to,
                from_location=from_location,
            )
            active_allocations = (
                StockAllocation.objects
                .filter(**allocation_filter)
                .select_related('batch')
                .order_by('allocated_at', 'batch_id', 'id')
            )

            for allocation in active_allocations:
                if remaining_quantity <= 0:
                    break

                return_quantity = min(remaining_quantity, allocation.quantity)
                if return_quantity <= 0:
                    continue

                expanded_items.append({
                    **item_data,
                    'batch': allocation.batch,
                    'quantity': return_quantity,
                })
                remaining_quantity -= return_quantity

            if remaining_quantity > 0:
                expanded_items.append({
                    **item_data,
                    'batch': None,
                    'quantity': remaining_quantity,
                })

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

    def _validate_instances_for_entry(self, errors, entry_type, from_location, items_data):
        seen_instance_ids = set()

        for item_data in items_data or []:
            instances = item_data.get('instances') or []
            if not instances:
                continue

            if entry_type != 'ISSUE':
                errors['items'] = 'Instance selection is only allowed on issue entries.'
                return

            if not from_location:
                errors['items'] = 'Source store is required when selecting item instances.'
                return

            item = item_data.get('item')
            for instance in instances:
                if instance.id in seen_instance_ids:
                    errors['items'] = 'Each item instance can only be selected once.'
                    return
                seen_instance_ids.add(instance.id)

                if item and instance.item_id != item.id:
                    errors['items'] = 'Selected item instances must belong to the entry item.'
                    return

                if instance.current_location_id != from_location.id:
                    errors['items'] = 'Selected item instances must be available at the source store.'
                    return

                if instance.status != InstanceStatus.AVAILABLE:
                    errors['items'] = 'Selected item instances must be available before issue.'
                    return

    def _validate_no_duplicate_submitted_items(self, errors, items_data):
        seen_item_ids = set()

        for item_data in items_data or []:
            item = item_data.get('item')
            if not item:
                continue

            item_id = item.pk if hasattr(item, 'pk') else item
            if item_id in seen_item_ids:
                errors['items'] = 'Each item can only be added once in a stock entry.'
                return
            seen_item_ids.add(item_id)

    def _validate_issue_stock_available(self, entry_type, from_location, items_data):
        if entry_type != 'ISSUE' or not from_location:
            return

        requested_by_record = {}
        for item_data in items_data or []:
            item = item_data.get('item')
            if not item:
                continue

            batch = item_data.get('batch')
            item_id = item.pk if hasattr(item, 'pk') else item
            batch_id = batch.pk if hasattr(batch, 'pk') else batch
            key = (item_id, batch_id)
            requested_by_record[key] = requested_by_record.get(key, 0) + (item_data.get('quantity') or 0)

        for (item_id, batch_id), requested_quantity in requested_by_record.items():
            try:
                record = StockRecord.objects.get(
                    item_id=item_id,
                    location=from_location,
                    batch_id=batch_id,
                )
            except StockRecord.DoesNotExist:
                raise serializers.ValidationError({
                    'items': 'Cannot issue stock that is not available at the source store.'
                })

            if requested_quantity > record.available_quantity:
                raise serializers.ValidationError({
                    'items': (
                        f'Requested quantity ({requested_quantity}) exceeds available stock '
                        f'({record.available_quantity}) at the source store.'
                    )
                })

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

                items_data = self._expand_quantity_return_items(
                    entry_type,
                    to_location,
                    issued_to,
                    from_location,
                    items_data or [],
                )

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
        self._validate_no_duplicate_submitted_items(errors, attrs.get('items'))
        self._validate_instances_for_entry(errors, entry_type, from_location, attrs.get('items'))
        if errors:
            raise serializers.ValidationError(errors)

        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if (
            not getattr(candidate, 'created_by_id', None)
            and user
            and user.is_authenticated
        ):
            candidate.created_by = user

        try:
            candidate.clean()
        except DjangoValidationError as exc:
            if hasattr(exc, 'message_dict'):
                raise serializers.ValidationError(exc.message_dict)
            raise serializers.ValidationError({'non_field_errors': exc.messages})
        return attrs

    def _creation_status(self, validated_data):
        entry_type = validated_data.get('entry_type')
        from_location = validated_data.get('from_location')
        to_location = validated_data.get('to_location')
        issued_to = validated_data.get('issued_to')
        if entry_type == 'ISSUE' and (issued_to or (to_location and not to_location.is_store)):
            return 'COMPLETED'
        if entry_type == 'RECEIPT' and (issued_to or (from_location and not from_location.is_store)):
            return 'COMPLETED'
        return 'PENDING_ACK'

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        request = self.context.get('request')
        if request and request.user:
            validated_data['created_by'] = request.user
        validated_data['status'] = self._creation_status(validated_data)

        from_location = validated_data.get('from_location')
        to_location = validated_data.get('to_location')
        issued_to = validated_data.get('issued_to')
        entry_type = validated_data.get('entry_type')
        items_data = self._expand_quantity_issue_items(entry_type, from_location, items_data)
        items_data = self._expand_quantity_return_items(entry_type, to_location, issued_to, from_location, items_data)
        self._validate_issue_stock_available(entry_type, from_location, items_data)
        reference_entry = validated_data.get('reference_entry')
        if reference_entry and reference_entry.inspection_certificate_id:
            validated_data['inspection_certificate'] = reference_entry.inspection_certificate

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
                from_location = validated_data.get('from_location', instance.from_location)
                entry_type = validated_data.get('entry_type', instance.entry_type)
                items_data = self._expand_quantity_issue_items(entry_type, from_location, items_data)
                self._validate_issue_stock_available(entry_type, from_location, items_data)

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
        access_checker = self.context.get('stock_entry_location_access_checker')
        if access_checker and obj.to_location:
            return bool(access_checker(obj.to_location))
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
        if obj.inspection_certificate_id and obj.entry_type == 'RECEIPT' and obj.from_location_id is None:
            return False
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

    def _prefetched_attr(self, obj, *names):
        for name in names:
            if hasattr(obj, name):
                return getattr(obj, name)
        return None

    def _correction_requests(self, obj):
        correction_source = self._correction_source_entry(obj)
        requests = self._prefetched_attr(
            correction_source,
            'prefetched_correction_requests',
            '_prefetched_correction_requests',
        )
        if requests is not None:
            return list(requests)
        return None

    def _latest_correction(self, obj):
        requests = self._correction_requests(obj)
        if requests is not None:
            return requests[0] if requests else None
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
        requests = self._correction_requests(obj)
        if requests is not None:
            correction = next(
                (
                    request
                    for request in requests
                    if request.status not in [CorrectionStatus.APPLIED, CorrectionStatus.REJECTED]
                ),
                None,
            )
            return self._serialize_correction_summary(correction)

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
        prefetched_entries = self._prefetched_attr(
            correction_source,
            'prefetched_generated_correction_entries',
            '_prefetched_generated_correction_entries',
        )
        if prefetched_entries is None:
            requests = self._correction_requests(obj)
            if requests is not None:
                by_id = {}
                for correction in requests:
                    generated_entries = self._prefetched_attr(
                        correction,
                        'prefetched_generated_entries',
                        '_prefetched_generated_entries',
                    )
                    if generated_entries is None:
                        generated_entries = getattr(correction, '_prefetched_objects_cache', {}).get('generated_entries')
                    if generated_entries is None:
                        generated_entries = []
                    for entry in generated_entries:
                        by_id[entry.id] = entry
                prefetched_entries = [by_id[key] for key in sorted(by_id)]

        if prefetched_entries is not None:
            return [
                {
                    'id': entry.id,
                    'entry_number': entry.entry_number,
                    'entry_type': entry.entry_type,
                    'status': entry.status,
                    'reference_purpose': entry.reference_purpose,
                }
                for entry in prefetched_entries
            ]

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
        prefetched_replacements = self._prefetched_attr(
            obj,
            'prefetched_replacement_entries',
            '_prefetched_replacement_entries',
        )
        if prefetched_replacements is not None:
            replacement = prefetched_replacements[0] if prefetched_replacements else None
            if not replacement:
                return None
            return {
                'id': replacement.id,
                'entry_number': replacement.entry_number,
                'entry_type': replacement.entry_type,
                'status': replacement.status,
            }

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
