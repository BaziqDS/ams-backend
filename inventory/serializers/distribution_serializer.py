from rest_framework import serializers
from ..models.stock_record_model import StockRecord

class StockRecordSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source='location.name', read_only=True)
    location_tags = serializers.SerializerMethodField()
    location_tags_display = serializers.SerializerMethodField()
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True, allow_null=True)
    item_name = serializers.CharField(source='item.name', read_only=True)

    def get_location_tags(self, obj):
        return [tag.id for tag in obj.location.tags.all()]

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
            for tag in obj.location.tags.all()
        ]

    class Meta:
        model = StockRecord
        fields = [
            'id', 'item', 'item_name', 'batch', 'batch_number', 
            'location', 'location_name', 'location_tags', 'location_tags_display',
            'quantity', 'in_transit_quantity',
            'available_quantity', 'last_updated'
        ]

