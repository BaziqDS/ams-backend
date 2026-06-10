from collections import defaultdict
import json

from django.db import transaction
from django.db.models import Q, Prefetch
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from ..models.category_model import TrackingType
from ..models.allocation_model import AllocationStatus, StockAllocation
from ..models.depreciation_model import AssetValueAdjustment, DepreciationEntry
from ..models.inspection_model import InspectionCertificate
from ..models.instance_model import ItemInstance
from ..models.item_model import Item
from ..models.stockentry_model import StockEntryItem
from ..serializers.instance_serializer import ItemInstanceSerializer
from ..services.serial_import import (
    SerialImportParseError,
    extract_candidates_from_upload,
    parse_serial_candidates,
)
from .utils import ScopedViewSetMixin, get_item_scope_locations, get_scope_tokens_from_request
from ..permissions import ItemInstancePermission


class ItemInstanceViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    """
    ViewSet for Item Instances.
    Supports read and update operations.
    """
    serializer_class = ItemInstanceSerializer
    permission_classes = [permissions.IsAuthenticated, ItemInstancePermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ['serial_number', 'qr_code']

    def get_queryset(self):
        # Base queryset with select_related for foreign keys (avoids N+1)
        queryset = ItemInstance.objects.select_related(
            'item',
            'item__category',
            'current_location',
            'current_location__parent_location',
            'authority_store',
            'created_by',
            'inspection_certificate',
            'fixed_asset_entry',
            'fixed_asset_entry__asset_class',
            'fixed_asset_entry__policy',
        ).order_by('-created_at')
        queryset = queryset.prefetch_related(
            Prefetch(
                'fixed_asset_entry__depreciation_entries',
                queryset=DepreciationEntry.objects.select_related('run', 'rate_version').order_by('-fiscal_year_start'),
                to_attr='prefetched_depreciation_entries',
            ),
            Prefetch(
                'fixed_asset_entry__adjustments',
                queryset=AssetValueAdjustment.objects.order_by('-effective_date', '-created_at'),
                to_attr='prefetched_adjustments',
            ),
        )
        
        item_id = self.request.query_params.get('item')
        if item_id:
            queryset = queryset.filter(item_id=item_id)
            
        location_id = self.request.query_params.get('location')
        if location_id:
            queryset = queryset.filter(current_location_id=location_id)
            
        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)

        stock_entry_ids = self.request.query_params.get('stock_entry_ids')
        if stock_entry_ids:
            id_list = [sid.strip() for sid in stock_entry_ids.split(',') if sid.strip()]
            queryset = queryset.filter(stock_entry_items__stock_entry_id__in=id_list).distinct()

        return queryset.filter(
            current_location__in=get_item_scope_locations(
                self.request.user,
                get_scope_tokens_from_request(self.request),
            )
        ).distinct()

    def _build_instance_serializer_maps(self, instances):
        instance_list = list(instances)
        instance_ids = [instance.id for instance in instance_list]
        allocated_instance_ids = [
            instance.id
            for instance in instance_list
            if instance.status == 'ALLOCATED'
        ]

        allocation_by_instance = {}
        if allocated_instance_ids:
            instance_entry_pairs = list(
                StockEntryItem.objects.filter(
                    instances__id__in=allocated_instance_ids,
                    stock_entry__allocations__status=AllocationStatus.ALLOCATED,
                )
                .values_list('instances__id', 'stock_entry_id')
                .distinct()
            )
            stock_entry_ids = {stock_entry_id for _, stock_entry_id in instance_entry_pairs}
            allocation_by_stock_entry = {}
            allocations = (
                StockAllocation.objects.filter(
                    stock_entry_id__in=stock_entry_ids,
                    status=AllocationStatus.ALLOCATED,
                )
                .filter(Q(allocated_to_person__isnull=False) | Q(allocated_to_location__isnull=False))
                .select_related('allocated_to_person', 'allocated_to_location', 'source_location')
                .order_by('-allocated_at')
            )
            for allocation in allocations:
                if allocation.stock_entry_id not in allocation_by_stock_entry:
                    allocation_by_stock_entry[allocation.stock_entry_id] = allocation
            for instance_id, stock_entry_id in instance_entry_pairs:
                allocation = allocation_by_stock_entry.get(stock_entry_id)
                if allocation and instance_id not in allocation_by_instance:
                    allocation_by_instance[instance_id] = allocation

        stock_entry_ids_by_instance = defaultdict(list)
        if instance_ids:
            pairs = (
                StockEntryItem.objects.filter(instances__id__in=instance_ids)
                .values_list('instances__id', 'stock_entry_id')
                .distinct()
                .order_by('stock_entry_id')
            )
            for instance_id, stock_entry_id in pairs:
                stock_entry_ids_by_instance[instance_id].append(stock_entry_id)

        return {
            'allocation_by_instance': allocation_by_instance,
            'stock_entry_ids_by_instance': dict(stock_entry_ids_by_instance),
        }

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(getattr(self, '_instance_serializer_maps', {}))
        return context

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            self._instance_serializer_maps = self._build_instance_serializer_maps(page)
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        instances = list(queryset)
        self._instance_serializer_maps = self._build_instance_serializer_maps(instances)
        serializer = self.get_serializer(instances, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        self._instance_serializer_maps = self._build_instance_serializer_maps([instance])
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def _get_individual_item(self):
        item_id = self.request.data.get('item')
        if not item_id:
            raise ValidationError({'item': 'Item is required.'})
        try:
            item = Item.objects.select_related('category').get(pk=item_id)
        except (TypeError, ValueError, Item.DoesNotExist):
            raise ValidationError({'item': 'Select a valid item.'})

        if item.category.get_tracking_type() != TrackingType.INDIVIDUAL:
            raise ValidationError({'item': 'Serial-number import is only available for individual-tracked items.'})
        return item

    def _get_optional_int(self, name):
        value = self.request.data.get(name)
        if value in (None, ''):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValidationError({name: 'Expected a numeric id.'})

    def _get_serial_import_store_ids(self):
        raw = None
        data = self.request.data
        if hasattr(data, 'getlist'):
            values = data.getlist('store_ids')
            if values:
                raw = values
        if raw is None:
            payload = data.get('store_ids')
            if payload not in (None, ''):
                raw = [payload] if not isinstance(payload, (list, tuple)) else list(payload)
        if raw is None:
            legacy = data.get('store')
            if legacy not in (None, ''):
                raw = [legacy]
        if not raw:
            raise ValidationError({'store_ids': 'Select at least one store under your custody.'})

        expanded = []
        for value in raw:
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.startswith('[') or stripped.startswith('{'):
                    try:
                        parsed = json.loads(stripped)
                    except json.JSONDecodeError:
                        parsed = stripped
                    if isinstance(parsed, list):
                        expanded.extend(parsed)
                        continue
                    value = parsed
                if isinstance(value, str) and ',' in value:
                    expanded.extend(part.strip() for part in value.split(',') if part.strip())
                    continue
            expanded.append(value)

        cleaned = []
        for value in expanded:
            try:
                cleaned.append(int(value))
            except (TypeError, ValueError):
                raise ValidationError({'store_ids': f"Invalid store id '{value}'."})
        cleaned = list(dict.fromkeys(cleaned))

        from ..models.location_model import Location
        scope_locations = get_item_scope_locations(
            self.request.user,
            get_scope_tokens_from_request(self.request),
        )
        scope_ids = set(scope_locations.values_list('id', flat=True))
        valid_store_ids = set(
            Location.objects.filter(id__in=cleaned, is_store=True, is_active=True)
            .values_list('id', flat=True)
        )
        invalid = [sid for sid in cleaned if sid not in valid_store_ids or sid not in scope_ids]
        if invalid:
            raise ValidationError({
                'store_ids': f'Stores not in your custody or not a store location: {invalid}.'
            })
        return cleaned

    def _get_serial_import_certificate(self, required=False):
        certificate_id = self._get_optional_int('inspection_certificate')
        contract_no = str(self.request.data.get('inspection_contract_no') or '').strip()
        if not certificate_id and not contract_no:
            if required:
                raise ValidationError({
                    'inspection_contract_no': 'Inspection certificate / contract number is required.'
                })
            return None

        queryset = InspectionCertificate.objects.all()
        try:
            if certificate_id:
                return queryset.get(pk=certificate_id)
            return queryset.get(contract_no__iexact=contract_no)
        except InspectionCertificate.DoesNotExist:
            raise ValidationError({
                'inspection_contract_no': 'No inspection certificate matches this contract number.'
            })

    def _serial_import_queryset(self, item, store_ids, blank_only=False, certificate=None):
        queryset = self.get_queryset().filter(item=item)

        queryset = queryset.filter(
            Q(authority_store_id__in=store_ids)
            | Q(authority_store__isnull=True, current_location_id__in=store_ids)
        )

        if certificate is not None:
            queryset = queryset.filter(inspection_certificate=certificate)

        if blank_only:
            queryset = queryset.filter(Q(serial_number__isnull=True) | Q(serial_number=''))

        return queryset.order_by('authority_store_id', 'created_at', 'id')

    def _get_serial_candidates(self):
        """
        Returns (candidates, source, extraction_mode).
        - Pasted text ? regex parse.
        - Uploaded text file ? regex parse on decoded contents.
        - Uploaded binary file ? LlamaExtract schema-driven extraction.
        """
        text = self.request.data.get('serial_numbers') or self.request.data.get('raw_text') or ''
        if text:
            return parse_serial_candidates(str(text)), 'text', 'line_split'

        uploaded_file = self.request.FILES.get('file')
        if not uploaded_file:
            raise ValidationError({'serial_numbers': 'Paste serial numbers or upload a file.'})
        try:
            candidates, mode = extract_candidates_from_upload(uploaded_file)
        except SerialImportParseError as exc:
            raise ValidationError({'file': str(exc)})
        return candidates, 'file', mode

    def _serial_conflict(self, serial_number, exclude_ids=None):
        exclude_ids = exclude_ids or []
        return (
            ItemInstance.objects.filter(serial_number__iexact=serial_number)
            .exclude(id__in=exclude_ids)
            .first()
        )

    @action(detail=False, methods=['get'], url_path='serial-import-stores')
    def serial_import_stores(self, request, *args, **kwargs):
        from ..models.location_model import Location

        item_id = request.query_params.get('item')
        if not item_id:
            raise ValidationError({'item': 'Item is required.'})
        try:
            item = Item.objects.get(pk=item_id)
        except (TypeError, ValueError, Item.DoesNotExist):
            raise ValidationError({'item': 'Select a valid item.'})

        scope_locations = get_item_scope_locations(
            request.user,
            get_scope_tokens_from_request(request),
        )
        scope_ids = set(scope_locations.values_list('id', flat=True))

        instances = self.get_queryset().filter(item=item)
        store_ids = set()
        for authority_id, current_id in instances.values_list('authority_store_id', 'current_location_id'):
            if authority_id and authority_id in scope_ids:
                store_ids.add(authority_id)
            elif not authority_id and current_id and current_id in scope_ids:
                store_ids.add(current_id)

        stores = (
            Location.objects.filter(id__in=store_ids, is_store=True, is_active=True)
            .order_by('name')
            .values('id', 'name')
        )
        blank_counts = {}
        for entry in (
            instances.filter(Q(serial_number__isnull=True) | Q(serial_number=''))
            .values('authority_store_id', 'current_location_id')
        ):
            key = entry['authority_store_id'] or entry['current_location_id']
            if key in store_ids:
                blank_counts[key] = blank_counts.get(key, 0) + 1

        return Response({
            'item': item.id,
            'stores': [
                {'id': s['id'], 'name': s['name'], 'blank_count': blank_counts.get(s['id'], 0)}
                for s in stores
            ],
        })

    @action(detail=False, methods=['post'], url_path='serial-import-preview')
    def serial_import_preview(self, request, *args, **kwargs):
        from ..models.instance_model import InstanceStatus

        item = self._get_individual_item()
        store_ids = self._get_serial_import_store_ids()
        certificate = self._get_serial_import_certificate(required=True)
        candidates, source, extraction_mode = self._get_serial_candidates()
        if not candidates:
            raise ValidationError({
                'serial_numbers': 'No serial numbers were found in the provided content.',
                'extraction_mode': extraction_mode,
            })

        available_instances = list(
            self._serial_import_queryset(item, store_ids, blank_only=True, certificate=certificate)
        )
        next_instance_index = 0
        seen = set()
        duplicate_count = 0
        in_transit_count = 0
        lines = []

        for candidate in candidates:
            serial_number = candidate['serial_number'].strip()
            serial_key = serial_number.casefold()
            status_value = 'MATCHED'
            error = None
            instance_id = None
            authority_store_id = None
            authority_store_name = None

            if serial_key in seen:
                status_value = 'DUPLICATE'
                error = 'Duplicate serial number in upload.'
                duplicate_count += 1
            else:
                seen.add(serial_key)
                conflict = self._serial_conflict(serial_number)
                if conflict:
                    status_value = 'DUPLICATE'
                    error = f"Serial number is already assigned to instance {conflict.id}."
                    duplicate_count += 1
                elif next_instance_index >= len(available_instances):
                    status_value = 'NO_INSTANCE'
                    error = 'No blank item instance is available for this serial number.'
                else:
                    target = available_instances[next_instance_index]
                    instance_id = target.id
                    if target.authority_store_id:
                        authority_store_id = target.authority_store_id
                        authority_store_name = target.authority_store.name
                    elif target.current_location_id:
                        authority_store_id = target.current_location_id
                        authority_store_name = target.current_location.name
                    if target.status == InstanceStatus.IN_TRANSIT:
                        in_transit_count += 1
                    next_instance_index += 1

            lines.append(
                {
                    'row_number': candidate['row_number'],
                    'serial_number': serial_number,
                    'raw_text': candidate['raw_text'],
                    'instance': instance_id,
                    'authority_store_id': authority_store_id,
                    'authority_store_name': authority_store_name,
                    'status': status_value,
                    'error': error,
                }
            )

        warnings = []
        if len(candidates) > len(available_instances):
            warnings.append('More serial numbers were found than blank instances available for the selected stores.')
        if in_transit_count:
            warnings.append(
                f'{in_transit_count} instance(s) are currently in transit; the serial will be locked in '
                'before the receiving store acknowledges.'
            )

        per_store_counts = defaultdict(int)
        for instance in available_instances:
            key = instance.authority_store_id or instance.current_location_id
            per_store_counts[key] += 1

        can_apply = bool(lines) and all(line['status'] == 'MATCHED' for line in lines)
        return Response(
            {
                'item': item.id,
                'inspection_certificate': certificate.id,
                'inspection_contract_no': certificate.contract_no,
                'source': source,
                'extraction_mode': extraction_mode,
                'store_ids': store_ids,
                'serial_count': len(candidates),
                'available_instance_count': len(available_instances),
                'available_by_store': [
                    {'store_id': sid, 'blank_count': count}
                    for sid, count in per_store_counts.items()
                ],
                'matched_count': sum(1 for line in lines if line['status'] == 'MATCHED'),
                'duplicate_count': duplicate_count,
                'in_transit_count': in_transit_count,
                'can_apply': can_apply,
                'warnings': warnings,
                'lines': lines,
            }
        )

    def _parse_assignments(self):
        assignments = self.request.data.get('assignments')
        if isinstance(assignments, str):
            try:
                assignments = json.loads(assignments)
            except json.JSONDecodeError:
                raise ValidationError({'assignments': 'Assignments must be valid JSON.'})
        if not isinstance(assignments, list) or not assignments:
            raise ValidationError({'assignments': 'At least one assignment is required.'})
        return assignments

    @action(detail=False, methods=['post'], url_path='serial-import-apply')
    def serial_import_apply(self, request, *args, **kwargs):
        item = self._get_individual_item()
        store_ids = self._get_serial_import_store_ids()
        certificate = self._get_serial_import_certificate(required=True)
        assignments = self._parse_assignments()
        normalized = []
        seen_serials = set()
        seen_instances = set()

        for index, assignment in enumerate(assignments, start=1):
            if not isinstance(assignment, dict):
                raise ValidationError({'assignments': f'Assignment {index} must be an object.'})
            instance_id = assignment.get('instance')
            serial_number = str(assignment.get('serial_number') or '').strip()
            if not instance_id:
                raise ValidationError({'assignments': f'Assignment {index} is missing an instance id.'})
            if not serial_number:
                raise ValidationError({'assignments': f'Assignment {index} is missing a serial number.'})
            try:
                instance_id = int(instance_id)
            except (TypeError, ValueError):
                raise ValidationError({'assignments': f'Assignment {index} has an invalid instance id.'})
            if len(serial_number) > 100:
                raise ValidationError({'assignments': f"Serial number '{serial_number}' exceeds 100 characters."})
            if instance_id in seen_instances:
                raise ValidationError({'assignments': f'Instance {instance_id} appears more than once.'})
            serial_key = serial_number.casefold()
            if serial_key in seen_serials:
                raise ValidationError({'assignments': f"Serial number '{serial_number}' appears more than once."})

            seen_instances.add(instance_id)
            seen_serials.add(serial_key)
            normalized.append({'instance': instance_id, 'serial_number': serial_number})

        instance_ids = [assignment['instance'] for assignment in normalized]
        with transaction.atomic():
            scoped_ids = list(
                self._serial_import_queryset(item, store_ids, certificate=certificate)
                .filter(id__in=instance_ids)
                .values_list('id', flat=True)
            )
            missing_ids = [instance_id for instance_id in instance_ids if instance_id not in scoped_ids]
            if missing_ids:
                raise ValidationError({'assignments': f'Instances are not available in your scope: {missing_ids}.'})

            scoped_instances = list(
                ItemInstance.objects.select_for_update()
                .filter(id__in=scoped_ids, item=item)
                .order_by('created_at', 'id')
            )
            instances_by_id = {instance.id: instance for instance in scoped_instances}

            for assignment in normalized:
                instance = instances_by_id[assignment['instance']]
                serial_number = assignment['serial_number']
                if instance.serial_number:
                    raise ValidationError(
                        {'assignments': f'Instance {instance.id} already has serial number {instance.serial_number}.'}
                    )
                conflict = self._serial_conflict(serial_number, exclude_ids=instance_ids)
                if conflict:
                    raise ValidationError(
                        {'assignments': f"Serial number '{serial_number}' is already assigned to instance {conflict.id}."}
                    )

            for assignment in normalized:
                instance = instances_by_id[assignment['instance']]
                instance.serial_number = assignment['serial_number']
                instance.save(update_fields=['serial_number', 'updated_at'])

        return Response(
            {
                'item': item.id,
                'applied_count': len(normalized),
                'assignments': normalized,
            },
            status=status.HTTP_200_OK,
        )
