from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum

from inventory.models import (
    AssetAdjustmentType,
    CategoryType,
    DepreciationAssetClass,
    DepreciationEntry,
    DepreciationPolicy,
    DepreciationRateVersion,
    DepreciationRun,
    DepreciationRunStatus,
    FixedAssetRegisterEntry,
    FixedAssetStatus,
    FixedAssetTargetType,
    TrackingType,
)


MONEY_QUANT = Decimal("0.01")


def money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def fiscal_year_bounds(fiscal_year_start: int) -> tuple[date, date]:
    return date(fiscal_year_start, 7, 1), date(fiscal_year_start + 1, 6, 30)


def get_default_policy(user=None) -> DepreciationPolicy:
    policy = DepreciationPolicy.objects.filter(is_default=True, is_active=True).first()
    if policy:
        return policy
    return DepreciationPolicy.objects.create(
        name="FBR WDV",
        is_default=True,
        is_active=True,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def default_asset_class_code(category) -> str:
    raw_code = category.code or f"CAT-{category.id}"
    return f"DEP-{raw_code}"[:50]


def get_or_create_asset_class_for_item(item, user=None) -> DepreciationAssetClass:
    policy = get_default_policy(user)
    category = item.category
    asset_class, _ = DepreciationAssetClass.objects.get_or_create(
        category=category,
        defaults={
            "name": category.name,
            "code": default_asset_class_code(category),
            "policy": policy,
            "created_by": user if getattr(user, "is_authenticated", False) else None,
        },
    )
    if asset_class.policy_id is None:
        asset_class.policy = policy
        asset_class.save(update_fields=["policy", "updated_at"])

    if not asset_class.rate_versions.exists():
        inherited_rate = category.get_depreciation_rate()
        if inherited_rate and inherited_rate > 0:
            DepreciationRateVersion.objects.create(
                asset_class=asset_class,
                rate=inherited_rate,
                effective_from=date(2001, 7, 1),
                source_reference="Migrated category default depreciation rate",
                created_by=user if getattr(user, "is_authenticated", False) else None,
                approved_by=user if getattr(user, "is_authenticated", False) else None,
            )
    return asset_class


def is_fixed_asset_item(item) -> bool:
    return bool(item and item.category and item.category.get_category_type() == CategoryType.FIXED_ASSET)


def rate_version_for_asset(asset: FixedAssetRegisterEntry, fiscal_year_start_date: date) -> DepreciationRateVersion:
    rate = asset.asset_class.rate_versions.filter(
        effective_from__lte=fiscal_year_start_date,
    ).filter(
        effective_to__isnull=True
    ).order_by("-effective_from", "-created_at").first()
    if rate:
        return rate
    rate = asset.asset_class.rate_versions.filter(
        effective_from__lte=fiscal_year_start_date,
        effective_to__gte=fiscal_year_start_date,
    ).order_by("-effective_from", "-created_at").first()
    if rate:
        return rate
    raise ValueError(f"No depreciation rate is configured for asset class {asset.asset_class.code}.")


def accumulated_before(asset: FixedAssetRegisterEntry, fiscal_year_start: int) -> Decimal:
    latest = asset.depreciation_entries.filter(
        run__status=DepreciationRunStatus.POSTED,
        fiscal_year_start__lt=fiscal_year_start,
    ).order_by("-fiscal_year_start", "-created_at").first()
    return latest.accumulated_depreciation if latest else Decimal("0.00")


def adjustments_before(asset: FixedAssetRegisterEntry, fiscal_year_start_date: date) -> Decimal:
    total = asset.adjustments.filter(
        effective_date__lt=fiscal_year_start_date,
    ).aggregate(total=Sum("amount"))["total"]
    return money(total or Decimal("0.00"))


def opening_wdv(asset: FixedAssetRegisterEntry, fiscal_year_start: int) -> Decimal:
    start_date, _ = fiscal_year_bounds(fiscal_year_start)
    return max(
        Decimal("0.00"),
        money(asset.original_cost + adjustments_before(asset, start_date) - accumulated_before(asset, fiscal_year_start)),
    )


def eligible_assets_for_run(policy: DepreciationPolicy, fiscal_year_start: int):
    _, end_date = fiscal_year_bounds(fiscal_year_start)
    return FixedAssetRegisterEntry.objects.select_related(
        "item",
        "item__category",
        "instance",
        "batch",
        "asset_class",
        "policy",
    ).filter(
        status=FixedAssetStatus.ACTIVE,
        capitalization_date__lte=end_date,
    ).filter(
        policy=policy,
    ).order_by("asset_number", "id")


def build_depreciation_row(asset: FixedAssetRegisterEntry, fiscal_year_start: int) -> dict:
    start_date, _ = fiscal_year_bounds(fiscal_year_start)
    rate_version = rate_version_for_asset(asset, start_date)
    opening = opening_wdv(asset, fiscal_year_start)
    depreciation = money(opening * rate_version.rate / Decimal("100.00"))
    accumulated = money(accumulated_before(asset, fiscal_year_start) + depreciation)
    closing = max(Decimal("0.00"), money(opening - depreciation))
    return {
        "asset": asset,
        "fiscal_year_start": fiscal_year_start,
        "rate_version": rate_version,
        "rate": rate_version.rate,
        "opening_value": opening,
        "depreciation_amount": depreciation,
        "accumulated_depreciation": accumulated,
        "closing_value": closing,
    }


def preview_depreciation_run(fiscal_year_start: int, policy: DepreciationPolicy | None = None) -> list[dict]:
    policy = policy or get_default_policy()
    posted_asset_ids = DepreciationEntry.objects.filter(
        run__status=DepreciationRunStatus.POSTED,
        fiscal_year_start=fiscal_year_start,
    ).values_list("asset_id", flat=True)
    rows = []
    for asset in eligible_assets_for_run(policy, fiscal_year_start).exclude(id__in=posted_asset_ids):
        rows.append(build_depreciation_row(asset, fiscal_year_start))
    return rows


@transaction.atomic
def post_depreciation_run(fiscal_year_start: int, user, policy: DepreciationPolicy | None = None) -> DepreciationRun:
    policy = policy or get_default_policy(user)
    run, _ = DepreciationRun.objects.get_or_create(
        policy=policy,
        fiscal_year_start=fiscal_year_start,
        defaults={"created_by": user if getattr(user, "is_authenticated", False) else None},
    )
    if run.status == DepreciationRunStatus.POSTED:
        return run
    if run.status == DepreciationRunStatus.REVERSED:
        raise ValueError("Reversed depreciation runs cannot be posted again.")

    rows = preview_depreciation_run(fiscal_year_start, policy)
    for row in rows:
        DepreciationEntry.objects.create(run=run, **row)
    run.mark_posted(user)
    return run


@transaction.atomic
def reverse_depreciation_run(run: DepreciationRun, user) -> DepreciationRun:
    if run.status != DepreciationRunStatus.POSTED:
        raise ValueError("Only posted depreciation runs can be reversed.")
    run.mark_reversed(user)
    return run


def capitalization_date_for_inspection(inspection_item):
    if inspection_item.capitalization_date:
        return inspection_item.capitalization_date
    certificate = inspection_item.inspection_certificate
    return (
        certificate.finance_check_date
        or certificate.date_of_inspection
        or certificate.date
        or date.today()
    )


def total_capitalization_cost_for_inspection(inspection_item) -> Decimal:
    if inspection_item.capitalization_cost is not None:
        return money(inspection_item.capitalization_cost)
    return money(inspection_item.unit_price * Decimal(inspection_item.accepted_quantity or 0))


def individual_capitalization_costs(inspection_item, instance_count: int) -> list[Decimal]:
    if instance_count <= 0:
        return []
    if inspection_item.capitalization_cost is None:
        return [money(inspection_item.unit_price) for _ in range(instance_count)]

    total = total_capitalization_cost_for_inspection(inspection_item)
    base = money(total / Decimal(instance_count))
    costs = [base for _ in range(instance_count)]
    costs[-1] = money(total - (base * Decimal(instance_count - 1)))
    return costs


def capitalize_inspection_item(inspection_item, *, instances=None, batch=None, user=None) -> list[FixedAssetRegisterEntry]:
    item = inspection_item.item
    if not is_fixed_asset_item(item):
        return []

    asset_class = inspection_item.depreciation_asset_class or get_or_create_asset_class_for_item(item, user)
    policy = asset_class.policy or get_default_policy(user)
    cap_date = capitalization_date_for_inspection(inspection_item)
    tracking_type = item.category.get_tracking_type()
    created = []

    if tracking_type == TrackingType.INDIVIDUAL:
        instance_list = list(instances or [])
        instance_costs = individual_capitalization_costs(inspection_item, len(instance_list))
        for instance, original_cost in zip(instance_list, instance_costs):
            asset, was_created = FixedAssetRegisterEntry.objects.get_or_create(
                instance=instance,
                defaults={
                    "item": item,
                    "target_type": FixedAssetTargetType.INSTANCE,
                    "asset_class": asset_class,
                    "policy": policy,
                    "source_inspection": inspection_item.inspection_certificate,
                    "inspection_item": inspection_item,
                    "original_quantity": 1,
                    "remaining_quantity": 1,
                    "original_cost": original_cost,
                    "capitalization_date": cap_date,
                    "depreciation_start_date": cap_date,
                    "created_by": user if getattr(user, "is_authenticated", False) else None,
                },
            )
            if was_created:
                created.append(asset)
        return created

    if tracking_type == TrackingType.QUANTITY and batch:
        total_cost = total_capitalization_cost_for_inspection(inspection_item)
        asset, was_created = FixedAssetRegisterEntry.objects.get_or_create(
            batch=batch,
            defaults={
                "item": item,
                "target_type": FixedAssetTargetType.LOT,
                "asset_class": asset_class,
                "policy": policy,
                "source_inspection": inspection_item.inspection_certificate,
                "inspection_item": inspection_item,
                "original_quantity": inspection_item.accepted_quantity,
                "remaining_quantity": inspection_item.accepted_quantity,
                "original_cost": total_cost,
                "capitalization_date": cap_date,
                "depreciation_start_date": cap_date,
                "created_by": user if getattr(user, "is_authenticated", False) else None,
            },
        )
        if was_created:
            created.append(asset)
    return created


def depreciation_summary_for_asset(asset: FixedAssetRegisterEntry | None) -> dict | None:
    if asset is None:
        return None
    latest = asset.depreciation_entries.filter(run__status=DepreciationRunStatus.POSTED).order_by("-fiscal_year_start").first()
    accumulated = latest.accumulated_depreciation if latest else Decimal("0.00")
    current_value = latest.closing_value if latest else money(asset.original_cost + adjustments_before(asset, date.today()))
    return {
        "capitalized": True,
        "asset_id": asset.id,
        "asset_number": asset.asset_number,
        "target_type": asset.target_type,
        "original_cost": str(money(asset.original_cost)),
        "accumulated_depreciation": str(money(accumulated)),
        "current_wdv": str(money(current_value)),
        "latest_posted_fiscal_year": latest.fiscal_year_start if latest else None,
        "status": asset.status,
    }


def empty_depreciation_summary() -> dict:
    return {
        "capitalized": False,
        "asset_id": None,
        "asset_number": None,
        "target_type": None,
        "original_cost": "0.00",
        "accumulated_depreciation": "0.00",
        "current_wdv": "0.00",
        "latest_posted_fiscal_year": None,
        "status": None,
    }
