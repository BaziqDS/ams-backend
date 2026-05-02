from decimal import Decimal

from django.db.models import Q, Sum
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from inventory.models import (
    AssetValueAdjustment,
    CategoryType,
    DepreciationAssetClass,
    DepreciationEntry,
    DepreciationPolicy,
    DepreciationRateVersion,
    DepreciationRun,
    DepreciationRunStatus,
    FixedAssetRegisterEntry,
    FixedAssetTargetType,
    ItemBatch,
    ItemInstance,
    TrackingType,
)
from inventory.permissions import DepreciationPermission
from inventory.serializers.depreciation_serializer import (
    AssetValueAdjustmentSerializer,
    DepreciationAssetClassSerializer,
    DepreciationEntrySerializer,
    DepreciationPolicySerializer,
    DepreciationRateVersionSerializer,
    DepreciationRunSerializer,
    FixedAssetRegisterEntrySerializer,
)
from inventory.services.depreciation_service import (
    depreciation_category_for_item,
    get_default_policy,
    post_depreciation_run,
    preview_depreciation_run,
    reverse_depreciation_run,
)


class DepreciationPolicyViewSet(viewsets.ModelViewSet):
    serializer_class = DepreciationPolicySerializer
    permission_classes = [DepreciationPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "method"]

    def get_queryset(self):
        return DepreciationPolicy.objects.order_by("name")


class DepreciationAssetClassViewSet(viewsets.ModelViewSet):
    serializer_class = DepreciationAssetClassSerializer
    permission_classes = [DepreciationPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "code", "description"]

    def get_queryset(self):
        return DepreciationAssetClass.objects.select_related("category", "policy", "created_by").order_by("name")


class DepreciationRateVersionViewSet(viewsets.ModelViewSet):
    serializer_class = DepreciationRateVersionSerializer
    permission_classes = [DepreciationPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ["asset_class__name", "asset_class__code", "source_reference", "notes"]

    def get_queryset(self):
        queryset = DepreciationRateVersion.objects.select_related("asset_class", "created_by", "approved_by")
        asset_class = self.request.query_params.get("asset_class")
        if asset_class:
            queryset = queryset.filter(asset_class_id=asset_class)
        return queryset.order_by("asset_class__name", "-effective_from", "-created_at")


class FixedAssetRegisterEntryViewSet(viewsets.ModelViewSet):
    serializer_class = FixedAssetRegisterEntrySerializer
    permission_classes = [DepreciationPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ["asset_number", "item__name", "item__code", "batch__batch_number", "instance__serial_number"]

    def get_queryset(self):
        queryset = FixedAssetRegisterEntry.objects.select_related(
            "item",
            "item__category",
            "instance",
            "batch",
            "asset_class",
            "policy",
            "source_inspection",
            "inspection_item",
            "created_by",
        ).order_by("asset_number", "id")
        item_id = self.request.query_params.get("item")
        target_type = self.request.query_params.get("target_type")
        status_value = self.request.query_params.get("status")
        if item_id:
            queryset = queryset.filter(item_id=item_id)
        if target_type:
            queryset = queryset.filter(target_type=target_type)
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    @action(detail=True, methods=["get"])
    def schedule(self, request, pk=None):
        asset = self.get_object()
        entries = asset.depreciation_entries.select_related("run", "rate_version", "rate_version__asset_class").order_by("fiscal_year_start")
        return Response(DepreciationEntrySerializer(entries, many=True).data)

    def _uncapitalized_depreciation_context(self, item):
        category = depreciation_category_for_item(item)
        setup = DepreciationAssetClass.objects.filter(category=category).prefetch_related("rate_versions").order_by("id").first()
        rate = setup.rate_versions.order_by("-effective_from", "-created_at").first() if setup else None
        return {
            "depreciation_category": category.id if category else None,
            "depreciation_category_name": category.name if category else None,
            "depreciation_category_code": category.code if category else None,
            "depreciation_setup": setup.id if setup else None,
            "depreciation_setup_name": setup.name if setup else None,
            "depreciation_setup_code": setup.code if setup else None,
            "depreciation_rate": str(rate.rate) if rate else None,
        }

    @action(detail=False, methods=["get"], url_path="uncapitalized")
    def uncapitalized(self, request):
        rows = []
        fixed_asset_category_filter = Q(item__category__category_type=CategoryType.FIXED_ASSET) | Q(
            item__category__parent_category__category_type=CategoryType.FIXED_ASSET
        )
        instances = ItemInstance.objects.select_related("item", "item__category", "item__category__parent_category").filter(
            fixed_asset_category_filter,
            fixed_asset_entry__isnull=True,
        )[:200]
        for instance in instances:
            rows.append({
                "target_type": FixedAssetTargetType.INSTANCE,
                "item": instance.item_id,
                "item_name": instance.item.name,
                "item_code": instance.item.code,
                "instance": instance.id,
                "batch": None,
                "batch_number": None,
                "quantity": 1,
                **self._uncapitalized_depreciation_context(instance.item),
            })

        batch_quantities = ItemBatch.objects.select_related("item", "item__category", "item__category__parent_category").filter(
            fixed_asset_category_filter,
            item__category__tracking_type=TrackingType.QUANTITY,
            fixed_asset_entry__isnull=True,
        ).annotate(quantity=Sum("stock_records__quantity"))[:200]
        for batch in batch_quantities:
            quantity = int(batch.quantity or 0)
            if quantity <= 0:
                continue
            rows.append({
                "target_type": FixedAssetTargetType.LOT,
                "item": batch.item_id,
                "item_name": batch.item.name,
                "item_code": batch.item.code,
                "instance": None,
                "batch": batch.id,
                "batch_number": batch.batch_number,
                "quantity": quantity,
                **self._uncapitalized_depreciation_context(batch.item),
            })
        return Response(rows)


class DepreciationRunViewSet(viewsets.ModelViewSet):
    serializer_class = DepreciationRunSerializer
    permission_classes = [DepreciationPermission]

    def get_queryset(self):
        return DepreciationRun.objects.select_related("policy", "created_by", "posted_by", "reversed_by").prefetch_related("entries")

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        run = self.get_object()
        try:
            rows = preview_depreciation_run(run.fiscal_year_start, run.policy)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        payload = [
            {
                "asset": row["asset"].id,
                "asset_number": row["asset"].asset_number,
                "item_name": row["asset"].item.name,
                "fiscal_year_start": row["fiscal_year_start"],
                "rate_version": row["rate_version"].id,
                "rate": str(row["rate"]),
                "opening_value": str(row["opening_value"]),
                "depreciation_amount": str(row["depreciation_amount"]),
                "accumulated_depreciation": str(row["accumulated_depreciation"]),
                "closing_value": str(row["closing_value"]),
            }
            for row in rows
        ]
        return Response(payload)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        run = self.get_object()
        try:
            posted = post_depreciation_run(run.fiscal_year_start, request.user, run.policy)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(posted).data)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        run = self.get_object()
        try:
            reversed_run = reverse_depreciation_run(run, request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(reversed_run).data)

    def perform_create(self, serializer):
        policy = serializer.validated_data.get("policy") or get_default_policy(self.request.user)
        serializer.save(policy=policy, created_by=self.request.user)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.status != DepreciationRunStatus.DRAFT:
            return Response({"detail": "Only draft depreciation runs can be edited."}, status=status.HTTP_400_BAD_REQUEST)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.status != DepreciationRunStatus.DRAFT:
            return Response({"detail": "Only draft depreciation runs can be deleted."}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)


class AssetValueAdjustmentViewSet(viewsets.ModelViewSet):
    serializer_class = AssetValueAdjustmentSerializer
    permission_classes = [DepreciationPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ["asset__asset_number", "asset__item__name", "reason"]

    def get_queryset(self):
        queryset = AssetValueAdjustment.objects.select_related("asset", "asset__item", "created_by").order_by("-effective_date", "-created_at")
        asset_id = self.request.query_params.get("asset")
        if asset_id:
            queryset = queryset.filter(asset_id=asset_id)
        return queryset
