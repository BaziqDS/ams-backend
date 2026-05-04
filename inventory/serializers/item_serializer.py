from rest_framework import serializers
from decimal import Decimal

from ..models.item_model import Item
from ..models.inspection_model import InspectionCertificate, InspectionStage
from .category_serializer import CategorySerializer
from ..models.category_model import CategoryType
from ..services.depreciation_service import (
    depreciation_summary_for_asset,
    empty_depreciation_summary,
    money,
)

class ItemSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='category.name', read_only=True)
    category_type = serializers.CharField(source='category.get_category_type', read_only=True)
    tracking_type = serializers.CharField(source='category.get_tracking_type', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    provisional_inspection = serializers.PrimaryKeyRelatedField(
        queryset=InspectionCertificate.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )
    is_provisional = serializers.BooleanField(required=False, write_only=True)
    total_quantity = serializers.SerializerMethodField()
    in_transit_quantity = serializers.SerializerMethodField()
    available_quantity = serializers.SerializerMethodField()
    is_low_stock = serializers.SerializerMethodField()
    standalone_location_count = serializers.SerializerMethodField()
    depreciation_summary = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = (
            'id', 'name', 'code', 'category', 'category_display', 
            'category_type', 'tracking_type', 'description', 
            'acct_unit', 'specifications', 'low_stock_threshold',
            'total_quantity', 
            'in_transit_quantity', 'available_quantity',
            'is_low_stock', 'standalone_location_count', 'is_active',
            'is_provisional', 'provisional_inspection',
            'created_at', 'updated_at',
            'created_by_name', 'depreciation_summary'
        )
        read_only_fields = ('created_at', 'updated_at', 'created_by')


    def validate(self, attrs):
        attrs = super().validate(attrs)
        provisional_inspection = attrs.get('provisional_inspection')
        wants_provisional = bool(provisional_inspection or attrs.get('is_provisional'))
        if not wants_provisional:
            attrs['is_provisional'] = False
            return attrs

        if self.instance is not None:
            raise serializers.ValidationError({
                'provisional_inspection': 'Provisional inspection ownership can only be set when creating an item.'
            })

        if provisional_inspection is None:
            raise serializers.ValidationError({
                'provisional_inspection': 'Select the inspection certificate that owns this provisional item.'
            })

        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            raise serializers.ValidationError({
                'provisional_inspection': 'Authentication is required to create provisional inspection items.'
            })

        if not user.is_superuser and not user.has_perm('inventory.fill_central_register'):
            raise serializers.ValidationError({
                'provisional_inspection': 'Only central-register users can create provisional inspection items.'
            })

        if provisional_inspection.stage != InspectionStage.CENTRAL_REGISTER:
            raise serializers.ValidationError({
                'provisional_inspection': 'Provisional items can only be created while the inspection is at the Central Register stage.'
            })

        if not user.is_superuser:
            if not hasattr(user, 'profile') or not user.profile.get_inspection_department_locations().filter(id=provisional_inspection.department_id).exists():
                raise serializers.ValidationError({
                    'provisional_inspection': 'You do not have access to this inspection certificate.'
                })

        attrs['is_provisional'] = True
        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        if request and request.user:
            validated_data['created_by'] = request.user
        return super().create(validated_data)

    def get_total_quantity(self, obj):
        return getattr(obj, 'restricted_total', 0)

    def get_in_transit_quantity(self, obj):
        return getattr(obj, 'restricted_in_transit', 0)

    def get_available_quantity(self, obj):
        return max(0, getattr(obj, 'restricted_available', 0))

    def get_is_low_stock(self, obj):
        total = getattr(obj, 'restricted_total', 0)
        threshold = obj.low_stock_threshold or 0
        return threshold > 0 and total > 0 and total <= threshold

    def get_standalone_location_count(self, obj):
        counts = self.context.get('standalone_location_counts') or {}
        return counts.get(obj.id, 0)

    def get_depreciation_summary(self, obj):
        if not obj.category or obj.category.get_category_type() != CategoryType.FIXED_ASSET:
            return empty_depreciation_summary()

        asset_count = 0
        original_cost = Decimal("0.00")
        accumulated = Decimal("0.00")
        current_wdv = Decimal("0.00")
        latest_year = None
        linked_entry_id = None

        assets = obj.fixed_asset_entries.select_related("asset_class", "policy").prefetch_related("depreciation_entries")
        for asset in assets:
            summary = depreciation_summary_for_asset(asset)
            if not summary:
                continue
            asset_count += 1
            linked_entry_id = linked_entry_id or summary["asset_id"]
            original_cost += Decimal(summary["original_cost"])
            accumulated += Decimal(summary["accumulated_depreciation"])
            current_wdv += Decimal(summary["current_wdv"])
            if summary["latest_posted_fiscal_year"] is not None:
                latest_year = max(latest_year or summary["latest_posted_fiscal_year"], summary["latest_posted_fiscal_year"])

        return {
            "capitalized": asset_count > 0,
            "asset_id": linked_entry_id if asset_count == 1 else None,
            "asset_count": asset_count,
            "asset_number": None,
            "target_type": None,
            "original_cost": str(money(original_cost)),
            "accumulated_depreciation": str(money(accumulated)),
            "current_wdv": str(money(current_wdv)),
            "latest_posted_fiscal_year": latest_year,
            "status": None,
        }


