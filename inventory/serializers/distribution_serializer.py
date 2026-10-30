from rest_framework import serializers
from ..models.stock_record_model import StockRecord
from ..models.inspection_model import InspectionItem
from ..models.stockentry_model import StockEntryItem
from ..models.location_model import Location


class StockRecordListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        rows = list(data.all() if hasattr(data, 'all') else data)
        if not rows:
            return []
        # Location paths use stable codes. Load ancestors once for this page,
        # including their tags, regardless of hierarchy depth.
        codes = {code for row in rows for code in row.location.hierarchy_path.split('/') if code}
        locations = {loc.code: loc for loc in Location.objects.filter(code__in=codes).prefetch_related('tags')}
        item_ids = {row.item_id for row in rows}
        batch_numbers = {row.batch.batch_number for row in rows if row.batch_id}
        inspections = {}
        if batch_numbers:
            for item in InspectionItem.objects.filter(item_id__in=item_ids, batch_number__in=batch_numbers).select_related('inspection_certificate').order_by('-inspection_certificate__date', '-id'):
                inspections.setdefault((item.item_id, item.batch_number), []).append(item.inspection_certificate.contract_no)
        entries = {}
        for item in StockEntryItem.objects.filter(
            item_id__in=item_ids, stock_entry__status='COMPLETED',
            stock_entry__inspection_certificate__isnull=False,
        ).select_related('stock_entry__inspection_certificate').order_by('-stock_entry__entry_date', '-id'):
            entries.setdefault((item.item_id, item.batch_id), []).append(item.stock_entry.inspection_certificate.contract_no)
        for row in rows:
            tags = {tag.id: tag for tag in row.location.tags.all()}
            for code in reversed(row.location.hierarchy_path.split('/')):
                ancestor = locations.get(code)
                if ancestor and ancestor.is_standalone:
                    tags.update({tag.id: tag for tag in ancestor.tags.all()})
                    break
            row._reporting_tags = sorted(tags.values(), key=lambda tag: tag.name)
            contracts = inspections.get((row.item_id, row.batch.batch_number), []) if row.batch_id else []
            row._source_contracts = list(dict.fromkeys(contracts + entries.get((row.item_id, row.batch_id), [])))
        return super().to_representation(rows)

class StockRecordSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source='location.name', read_only=True)
    location_tags = serializers.SerializerMethodField()
    location_tags_display = serializers.SerializerMethodField()
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True, allow_null=True)
    item_name = serializers.CharField(source='item.name', read_only=True)
    item_code = serializers.CharField(source='item.code', read_only=True)
    subcategory_name = serializers.CharField(source='item.category.name', read_only=True)
    category_type = serializers.CharField(source='item.category.get_category_type', read_only=True)
    low_stock_threshold = serializers.IntegerField(source='item.low_stock_threshold', read_only=True)
    source_inspection_contracts = serializers.SerializerMethodField()

    def _reporting_tags(self, obj):
        if hasattr(obj, '_reporting_tags'):
            return obj._reporting_tags
        tags_by_id = {tag.id: tag for tag in obj.location.tags.all()}
        standalone = obj.location.get_parent_standalone()
        if standalone and standalone.id != obj.location_id:
            for tag in standalone.tags.all():
                tags_by_id.setdefault(tag.id, tag)
        return sorted(tags_by_id.values(), key=lambda tag: tag.name)

    def get_location_tags(self, obj):
        return [tag.id for tag in self._reporting_tags(obj)]

    def get_location_tags_display(self, obj):
        return [
            {
                'id': tag.id,
                'name': tag.name,
                'code': tag.code,
                'category': tag.category,
                'category_display': tag.get_category_display(),
                'label': f"{tag.get_category_display()}: {tag.name}",
                'color': tag.color,
                'is_active': tag.is_active,
            }
            for tag in self._reporting_tags(obj)
        ]

    def get_source_inspection_contracts(self, obj):
        if hasattr(obj, '_source_contracts'):
            return obj._source_contracts
        contracts = []
        seen = set()

        if obj.batch_id and obj.batch and obj.batch.batch_number:
            inspection_items = (
                InspectionItem.objects
                .select_related('inspection_certificate')
                .filter(item_id=obj.item_id, batch_number=obj.batch.batch_number)
                .order_by('-inspection_certificate__date', '-id')
            )
            for inspection_item in inspection_items:
                contract = inspection_item.inspection_certificate.contract_no
                if contract not in seen:
                    seen.add(contract)
                    contracts.append(contract)

        entry_items = (
            StockEntryItem.objects
            .select_related('stock_entry__inspection_certificate')
            .filter(
                item_id=obj.item_id,
                batch_id=obj.batch_id,
                stock_entry__inspection_certificate__isnull=False,
                stock_entry__status='COMPLETED',
            )
            .order_by('-stock_entry__entry_date', '-id')
        )
        for entry_item in entry_items:
            contract = entry_item.stock_entry.inspection_certificate.contract_no
            if contract not in seen:
                seen.add(contract)
                contracts.append(contract)

        return contracts

    class Meta:
        model = StockRecord
        list_serializer_class = StockRecordListSerializer
        fields = [
            'id', 'item', 'item_name', 'batch', 'batch_number', 
            'item_code', 'subcategory_name', 'category_type', 'low_stock_threshold', 'source_inspection_contracts',
            'location', 'location_name', 'location_tags', 'location_tags_display',
            'quantity', 'in_transit_quantity',
            'available_quantity', 'last_updated'
        ]

