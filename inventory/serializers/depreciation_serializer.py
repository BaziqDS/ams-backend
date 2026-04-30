from rest_framework import serializers

from inventory.models import (
    AssetValueAdjustment,
    CategoryType,
    DepreciationAssetClass,
    DepreciationEntry,
    DepreciationPolicy,
    DepreciationRateVersion,
    DepreciationRun,
    FixedAssetRegisterEntry,
    FixedAssetTargetType,
    Item,
    ItemBatch,
    ItemInstance,
)
from inventory.services.depreciation_service import (
    depreciation_summary_for_asset,
    empty_depreciation_summary,
    get_default_policy,
    get_or_create_asset_class_for_item,
)


class DepreciationPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = DepreciationPolicy
        fields = [
            "id", "name", "method", "fiscal_year_start_month", "fiscal_year_start_day",
            "is_default", "is_active", "created_at", "updated_at", "created_by",
        ]
        read_only_fields = ["created_at", "updated_at", "created_by"]


class DepreciationAssetClassSerializer(serializers.ModelSerializer):
    policy_name = serializers.CharField(source="policy.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, allow_null=True)
    current_rate = serializers.SerializerMethodField()

    class Meta:
        model = DepreciationAssetClass
        fields = [
            "id", "name", "code", "category", "category_name", "policy", "policy_name",
            "description", "is_active", "current_rate", "created_at", "updated_at", "created_by",
        ]
        read_only_fields = ["created_at", "updated_at", "created_by"]

    def get_current_rate(self, obj):
        rate = obj.rate_versions.order_by("-effective_from", "-created_at").first()
        return str(rate.rate) if rate else None

    def create(self, validated_data):
        request = self.context.get("request")
        if "policy" not in validated_data or validated_data.get("policy") is None:
            validated_data["policy"] = get_default_policy(request.user if request else None)
        if request and request.user:
            validated_data["created_by"] = request.user
        return super().create(validated_data)


class DepreciationRateVersionSerializer(serializers.ModelSerializer):
    asset_class_name = serializers.CharField(source="asset_class.name", read_only=True)

    class Meta:
        model = DepreciationRateVersion
        fields = [
            "id", "asset_class", "asset_class_name", "rate", "effective_from", "effective_to",
            "source_reference", "notes", "created_by", "approved_by", "created_at",
        ]
        read_only_fields = ["created_by", "created_at"]

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user:
            validated_data["created_by"] = request.user
            if not validated_data.get("approved_by"):
                validated_data["approved_by"] = request.user
        return super().create(validated_data)


class DepreciationEntrySerializer(serializers.ModelSerializer):
    asset_number = serializers.CharField(source="asset.asset_number", read_only=True)
    item_name = serializers.CharField(source="asset.item.name", read_only=True)
    rate_version_label = serializers.SerializerMethodField()

    class Meta:
        model = DepreciationEntry
        fields = [
            "id", "run", "asset", "asset_number", "item_name", "fiscal_year_start",
            "rate_version", "rate_version_label", "rate", "opening_value", "depreciation_amount",
            "accumulated_depreciation", "closing_value", "created_at",
        ]
        read_only_fields = fields

    def get_rate_version_label(self, obj):
        return f"{obj.rate_version.asset_class.code} {obj.rate}% from {obj.rate_version.effective_from}"


class FixedAssetRegisterEntrySerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_code = serializers.CharField(source="item.code", read_only=True)
    instance_serial = serializers.CharField(source="instance.serial_number", read_only=True, allow_null=True)
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True, allow_null=True)
    asset_class_name = serializers.CharField(source="asset_class.name", read_only=True)
    policy_name = serializers.CharField(source="policy.name", read_only=True, allow_null=True)
    source_contract_no = serializers.CharField(source="source_inspection.contract_no", read_only=True, allow_null=True)
    depreciation_summary = serializers.SerializerMethodField()

    class Meta:
        model = FixedAssetRegisterEntry
        fields = [
            "id", "asset_number", "item", "item_name", "item_code", "instance", "instance_serial",
            "batch", "batch_number", "target_type", "asset_class", "asset_class_name", "policy",
            "policy_name", "source_inspection", "source_contract_no", "inspection_item",
            "original_quantity", "remaining_quantity", "original_cost", "capitalization_date",
            "depreciation_start_date", "status", "notes", "depreciation_summary",
            "created_by", "created_at", "updated_at",
        ]
        read_only_fields = ["asset_number", "created_by", "created_at", "updated_at"]

    def get_depreciation_summary(self, obj):
        return depreciation_summary_for_asset(obj) or empty_depreciation_summary()

    def validate(self, attrs):
        item = attrs.get("item") or getattr(self.instance, "item", None)
        instance = attrs.get("instance") or getattr(self.instance, "instance", None)
        batch = attrs.get("batch") or getattr(self.instance, "batch", None)
        target_type = attrs.get("target_type") or getattr(self.instance, "target_type", None)

        if instance and batch:
            raise serializers.ValidationError("Choose either an item instance or an item batch/lot, not both.")
        if instance:
            target_type = FixedAssetTargetType.INSTANCE
            item = instance.item
        if batch:
            target_type = FixedAssetTargetType.LOT
            item = batch.item
        if not item:
            raise serializers.ValidationError({"item": "A fixed asset entry requires an item."})
        if item.category.get_category_type() != CategoryType.FIXED_ASSET:
            raise serializers.ValidationError({"item": "Only fixed asset items can be capitalized."})
        if target_type == FixedAssetTargetType.INSTANCE and not instance:
            raise serializers.ValidationError({"instance": "Individual fixed assets require an instance."})
        if target_type == FixedAssetTargetType.LOT and not batch:
            raise serializers.ValidationError({"batch": "Quantity fixed assets require a batch/lot."})

        attrs["item"] = item
        attrs["target_type"] = target_type
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user:
            validated_data["created_by"] = request.user
        if not validated_data.get("policy"):
            validated_data["policy"] = get_default_policy(request.user if request else None)
        if not validated_data.get("asset_class"):
            validated_data["asset_class"] = get_or_create_asset_class_for_item(
                validated_data["item"],
                request.user if request else None,
            )
        return super().create(validated_data)


class DepreciationRunSerializer(serializers.ModelSerializer):
    policy = serializers.PrimaryKeyRelatedField(
        queryset=DepreciationPolicy.objects.all(),
        required=False,
        allow_null=True,
    )
    policy_name = serializers.CharField(source="policy.name", read_only=True)
    fiscal_year_label = serializers.CharField(read_only=True)
    entry_count = serializers.IntegerField(source="entries.count", read_only=True)

    class Meta:
        model = DepreciationRun
        fields = [
            "id", "policy", "policy_name", "fiscal_year_start", "fiscal_year_label",
            "status", "notes", "entry_count", "created_by", "posted_by", "posted_at",
            "reversed_by", "reversed_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "status", "created_by", "posted_by", "posted_at", "reversed_by",
            "reversed_at", "created_at", "updated_at",
        ]
        validators = []

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get("request")
        policy = attrs.get("policy") or getattr(self.instance, "policy", None)
        if policy is None:
            policy = get_default_policy(request.user if request else None)
            attrs["policy"] = policy

        fiscal_year_start = attrs.get("fiscal_year_start") or getattr(self.instance, "fiscal_year_start", None)
        if fiscal_year_start is not None:
            duplicate_runs = DepreciationRun.objects.filter(policy=policy, fiscal_year_start=fiscal_year_start)
            if self.instance is not None:
                duplicate_runs = duplicate_runs.exclude(pk=self.instance.pk)
            if duplicate_runs.exists():
                raise serializers.ValidationError({
                    "fiscal_year_start": "A depreciation run already exists for this policy and fiscal year."
                })
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if not validated_data.get("policy"):
            validated_data["policy"] = get_default_policy(request.user if request else None)
        if request and request.user:
            validated_data["created_by"] = request.user
        return super().create(validated_data)


class AssetValueAdjustmentSerializer(serializers.ModelSerializer):
    asset_number = serializers.CharField(source="asset.asset_number", read_only=True)
    item_name = serializers.CharField(source="asset.item.name", read_only=True)

    class Meta:
        model = AssetValueAdjustment
        fields = [
            "id", "asset", "asset_number", "item_name", "adjustment_type",
            "effective_date", "amount", "quantity_delta", "reason",
            "created_by", "created_at",
        ]
        read_only_fields = ["created_by", "created_at"]

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user:
            validated_data["created_by"] = request.user
        return super().create(validated_data)


class UncapitalizedAssetSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(choices=FixedAssetTargetType.choices)
    item = serializers.PrimaryKeyRelatedField(queryset=Item.objects.all())
    item_name = serializers.CharField()
    item_code = serializers.CharField()
    instance = serializers.PrimaryKeyRelatedField(queryset=ItemInstance.objects.all(), allow_null=True)
    batch = serializers.PrimaryKeyRelatedField(queryset=ItemBatch.objects.all(), allow_null=True)
    batch_number = serializers.CharField(allow_blank=True, allow_null=True)
    quantity = serializers.IntegerField()
