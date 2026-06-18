r"""
CSV-driven legacy inspection import.

This script is intentionally separate from scripts/import_inspections.py. It
uses docs/legacy_inspection_import_table.csv as the source of truth, preserves
auth/admin and locations, recreates only the prerequisites needed by the legacy
inspection rows, then completes inspections through the ORM so stock and fixed
asset signals run.

Dry run:
    venv\Scripts\python.exe scripts\import_legacy_inspections_from_table.py --clean --dry-run

Real run:
    venv\Scripts\python.exe scripts\import_legacy_inspections_from_table.py --clean --yes-clean
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ams.settings")

import django  # noqa: E402

django.setup()

from django.apps import apps  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.db import connection, transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from inventory.models import (  # noqa: E402
    Category,
    CategoryType,
    DepreciationAssetClass,
    DepreciationMethod,
    DepreciationPolicy,
    DepreciationRateVersion,
    InspectionCertificate,
    InspectionItem,
    InspectionStage,
    Item,
    Location,
    LocationTag,
    StockRegister,
    TrackingType,
)


CSV_PATH = BACKEND_ROOT / "docs" / "legacy_inspection_import_table.csv"
LEGACY_RATE = Decimal("25.00")
RATE_EFFECTIVE_FROM = date(2001, 7, 1)

# The item post-save signal can call the configured embedding provider. This
# import is bulk administrative data loading, so keep it deterministic/offline.
settings.ITEM_SEARCH_HYBRID_ENABLED = False


@dataclass(frozen=True)
class PlannedItemDefinition:
    name: str
    parent_type: str
    category_name: str
    tracking_type: str
    acct_unit: str = "No."
    specifications: str = ""


PLANNED_NEW_ITEMS: dict[str, PlannedItemDefinition] = {
    "NEW-ITEM-12V-5V-ADAPTER-RECEIVER-SOUND": PlannedItemDefinition(
        "12V - 5V Adapter for Receiver Sound",
        CategoryType.CONSUMABLE,
        "Cables & Accessories",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-ABSTRACT-BOOK-26-PAGES": PlannedItemDefinition(
        "Abstract Book (26 Pages)",
        CategoryType.CONSUMABLE,
        "Event & Printing Material",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-BANNERS-4-X-6": PlannedItemDefinition(
        "Banner 4 x 6",
        CategoryType.CONSUMABLE,
        "Event & Printing Material",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-BOARD-FITTING-ACCESSORIES": PlannedItemDefinition(
        "Board Fitting Accessories",
        CategoryType.CONSUMABLE,
        "Building Consumables",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-CARDS-IDENTIFICATION-RIBBON-PACKET": PlannedItemDefinition(
        "Identification Cards with Ribbon and Packet",
        CategoryType.CONSUMABLE,
        "Event & Printing Material",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-CHANNEL-DUCT": PlannedItemDefinition(
        "Channel Duct",
        CategoryType.CONSUMABLE,
        "Electrical Consumables",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-COMPLETE-INSTALLATION-TRANSPORTATION-CHARGES-ALL-RESPECT-LAY": PlannedItemDefinition(
        "Installation and Transportation Charges",
        CategoryType.CONSUMABLE,
        "Services & Charges",
        TrackingType.QUANTITY,
        acct_unit="Job",
    ),
    "NEW-ITEM-DAWN-VISITOR-CHAIR": PlannedItemDefinition(
        "Dawn Visitor Chair",
        CategoryType.FIXED_ASSET,
        "Furniture & Fixtures",
        TrackingType.INDIVIDUAL,
    ),
    "NEW-ITEM-DOOR-LOCK": PlannedItemDefinition(
        "Door Lock",
        CategoryType.FIXED_ASSET,
        "Building Fixtures",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-DT-HEADSET-MICROPHONE-DM-793": PlannedItemDefinition(
        "DT Headset Microphone DM-793",
        CategoryType.FIXED_ASSET,
        "IT Equipment",
        TrackingType.INDIVIDUAL,
    ),
    "NEW-ITEM-EPSON-EB-E01-PROJECTOR": PlannedItemDefinition(
        "Epson EB-E01 Multimedia Projector",
        CategoryType.FIXED_ASSET,
        "AV Equipment",
        TrackingType.INDIVIDUAL,
        specifications="3LCD, 3300 lumens, XGA 1024x768, contrast ratio 15,000:1",
    ),
    "NEW-ITEM-EXECUTIVE-CHAIR-REVOLVING-GENESIS-HIGH-BACK-BLACK-COLOR": PlannedItemDefinition(
        "Executive Revolving Chair Genesis High Back",
        CategoryType.FIXED_ASSET,
        "Furniture & Fixtures",
        TrackingType.INDIVIDUAL,
    ),
    "NEW-ITEM-HDMI-4K-SUPPORT-CABLE": PlannedItemDefinition(
        "HDMI 4K Support Cable",
        CategoryType.CONSUMABLE,
        "Cables & Accessories",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-HDMI-CABLE-5-METER": PlannedItemDefinition(
        "HDMI Cable 5 Meter",
        CategoryType.CONSUMABLE,
        "Cables & Accessories",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-HEADSET-REDRAGON-WIRELESS-GAMING-HEADPHONE-H848-REDRAGON": PlannedItemDefinition(
        "Redragon H848 Wireless Gaming Headphone",
        CategoryType.FIXED_ASSET,
        "IT Equipment",
        TrackingType.INDIVIDUAL,
    ),
    "NEW-ITEM-INVITATION-CARDS-ENVELOPES": PlannedItemDefinition(
        "Invitation Cards with Envelopes",
        CategoryType.CONSUMABLE,
        "Event & Printing Material",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-MARBLE-SLAB-COUNTERTOP": PlannedItemDefinition(
        "Marble Slab Countertop",
        CategoryType.FIXED_ASSET,
        "Building Fixtures",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-MOUSE-VAMPIRE-ELITE-WIRELESS-GAMING-MOUSE-M686-REDRAGON": PlannedItemDefinition(
        "Redragon M686 Vampire Elite Wireless Gaming Mouse",
        CategoryType.FIXED_ASSET,
        "IT Equipment",
        TrackingType.INDIVIDUAL,
    ),
    "NEW-ITEM-PBS-POLARIZING-BEAM-SPLITTER-TRANSPARENT-LENS-630NM-660NM": PlannedItemDefinition(
        "PBS Polarizing Beam Splitter 10x10x10mm",
        CategoryType.FIXED_ASSET,
        "Lab & Research Electronics",
        TrackingType.INDIVIDUAL,
    ),
    "NEW-ITEM-PEN-BRANDING": PlannedItemDefinition(
        "Pen with Branding",
        CategoryType.CONSUMABLE,
        "Event & Printing Material",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-POWER-CABLE-PROJECTOR-15-METER": PlannedItemDefinition(
        "Projector Power Cable 15 Meter",
        CategoryType.CONSUMABLE,
        "Cables & Accessories",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-PROJECTOR-CEILING-STAND": PlannedItemDefinition(
        "Projector Ceiling Stand",
        CategoryType.FIXED_ASSET,
        "AV Fixtures",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-PVC-CABLE-4-CORE-16-SQ-MM": PlannedItemDefinition(
        "PVC Cable 4 Core 16 Sq.MM",
        CategoryType.CONSUMABLE,
        "Electrical Consumables",
        TrackingType.QUANTITY,
        acct_unit="Meter",
    ),
    "NEW-ITEM-ROSTRUM-CLASSROOM": PlannedItemDefinition(
        "Classroom Rostrum",
        CategoryType.FIXED_ASSET,
        "Furniture & Fixtures",
        TrackingType.INDIVIDUAL,
    ),
    "NEW-ITEM-SAFETY-SECURITY-BOX-PROJECTOR": PlannedItemDefinition(
        "Projector Safety Security Box",
        CategoryType.FIXED_ASSET,
        "AV Fixtures",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-SOFT-BOARD-NOTICE-BOARD-FABRIC-CUSHION": PlannedItemDefinition(
        "Soft Board Notice Board with Fabric Cushion",
        CategoryType.FIXED_ASSET,
        "Building Fixtures",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-VISITOR-CHAIRS-MESH-FABRIC-UPHOLSTERY-SEAT-BACK-FIXED": PlannedItemDefinition(
        "Visitor Chair Mesh Fabric Upholstery",
        CategoryType.FIXED_ASSET,
        "Furniture & Fixtures",
        TrackingType.INDIVIDUAL,
    ),
    "NEW-ITEM-WHITE-BOARD-LAMINATION-SHEET": PlannedItemDefinition(
        "White Board Lamination Sheet",
        CategoryType.FIXED_ASSET,
        "Building Fixtures",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-WHITE-BOARD-SHEETS": PlannedItemDefinition(
        "White Board Sheets with Fitting",
        CategoryType.FIXED_ASSET,
        "Building Fixtures",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-WINDOW-SHUTTER": PlannedItemDefinition(
        "Window Shutter",
        CategoryType.FIXED_ASSET,
        "Building Fixtures",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-WRITING-PADS-8-X-5": PlannedItemDefinition(
        "Writing Pad 8 x 5",
        CategoryType.CONSUMABLE,
        "Event & Printing Material",
        TrackingType.QUANTITY,
    ),
    "NEW-ITEM-X-STANDEES": PlannedItemDefinition(
        "X-Standee",
        CategoryType.CONSUMABLE,
        "Event & Printing Material",
        TrackingType.QUANTITY,
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=str(CSV_PATH), help="Inspection import CSV path.")
    parser.add_argument("--clean", action="store_true", help="Clean inventory data first.")
    parser.add_argument(
        "--yes-clean",
        action="store_true",
        help="Required with --clean for a real destructive run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run inside a transaction and roll back at the end.",
    )
    parser.add_argument(
        "--admin-username",
        default="admin",
        help="Only this user is kept during cleanup and used as importer.",
    )
    parser.add_argument(
        "--keep-all-users",
        action="store_true",
        help="With --clean, keep all users instead of only --admin-username.",
    )
    parser.add_argument(
        "--leave-draft",
        action="store_true",
        help="Create inspections but do not complete them.",
    )
    return parser.parse_args()


def money(value: str | None) -> Decimal:
    text = (value or "").strip().replace(",", "")
    if not text:
        return Decimal("0.00")
    try:
        return Decimal(text)
    except InvalidOperation:
        return Decimal("0.00")


def integer(value: str | None, default: int = 0) -> int:
    value = (value or "").strip()
    if not value:
        return default
    try:
        return max(default, int(Decimal(value)))
    except InvalidOperation:
        return default


def parse_date(value: str | None) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def first_text(*values: str | None, default: str = "") -> str:
    for value in values:
        value = (value or "").strip()
        if value:
            return value
    return default


def normalize_page(value: str | None, fallback: int) -> str:
    value = (value or "").strip()
    if value.isdigit():
        return value
    match = re.search(r"\d+", value)
    if match:
        return match.group(0)
    return str(fallback)


def stable_code(prefix: str, index: int) -> str:
    return f"{prefix}-{index:04d}"


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise RuntimeError(f"No rows found in {path}")
    missing_defs = sorted(
        {
            row["planned_item_key"]
            for row in rows
            if row.get("item_import_action") == "create_or_review_new_item"
            and row.get("planned_item_key") not in PLANNED_NEW_ITEMS
        }
    )
    if missing_defs:
        raise RuntimeError(f"Missing planned item definitions: {missing_defs}")
    return rows


def importer_user(username: str) -> User:
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist as exc:
        raise RuntimeError(f"Admin user '{username}' does not exist.") from exc
    if not user.is_superuser:
        raise RuntimeError(f"Admin user '{username}' must be a superuser.")
    return user


def clean_database(admin: User, keep_all_users: bool) -> None:
    excluded = {
        (Location._meta.app_label, Location.__name__),
        (LocationTag._meta.app_label, LocationTag.__name__),
    }
    tables: list[str] = []
    for app_label in ("notifications", "inventory"):
        try:
            app_config = apps.get_app_config(app_label)
        except LookupError:
            continue
        for model in app_config.get_models(include_auto_created=False):
            if not model._meta.managed:
                continue
            if (model._meta.app_label, model.__name__) in excluded:
                continue
            tables.append(model._meta.db_table)

    if tables:
        quoted = ", ".join(connection.ops.quote_name(table) for table in tables)
        with connection.cursor() as cursor:
            cursor.execute(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")

    if not keep_all_users:
        User.objects.exclude(pk=admin.pk).delete()


def get_parent_category(name: str, category_type: str, depreciation_rate: Decimal | None = None) -> Category:
    category, _ = Category.objects.update_or_create(
        name=name,
        parent_category=None,
        defaults={
            "category_type": category_type,
            "tracking_type": None,
            "default_depreciation_rate": depreciation_rate,
            "is_active": True,
        },
    )
    return category


def get_subcategory(name: str, parent: Category, tracking_type: str) -> Category:
    category, _ = Category.objects.update_or_create(
        name=name,
        parent_category=parent,
        defaults={
            "category_type": parent.category_type,
            "tracking_type": tracking_type,
            "is_active": True,
        },
    )
    return category


def category_for(
    parents: dict[str, Category],
    cache: dict[tuple[str, str, str], Category],
    parent_type: str,
    category_name: str,
    tracking_type: str,
) -> Category:
    key = (parent_type, category_name, tracking_type)
    if key not in cache:
        parent = parents[parent_type]
        cache[key] = get_subcategory(category_name, parent, tracking_type)
    return cache[key]


def create_categories() -> tuple[dict[str, Category], dict[tuple[str, str, str], Category]]:
    parents = {
        CategoryType.CONSUMABLE: get_parent_category("Consumable", CategoryType.CONSUMABLE),
        CategoryType.PERISHABLE: get_parent_category("Perishable", CategoryType.PERISHABLE),
        CategoryType.FIXED_ASSET: get_parent_category(
            "Fixed Asset",
            CategoryType.FIXED_ASSET,
            LEGACY_RATE,
        ),
    }
    cache: dict[tuple[str, str, str], Category] = {}
    return parents, cache


def item_definition_from_existing_row(row: dict[str, str]) -> PlannedItemDefinition:
    category_type = first_text(row.get("matched_item_category_type"), default=CategoryType.CONSUMABLE)
    category_name = first_text(row.get("matched_item_category"), default="Legacy Imported Items")
    tracking_type = first_text(row.get("matched_item_tracking_type"), default=TrackingType.QUANTITY)
    return PlannedItemDefinition(
        name=first_text(row.get("matched_item_name"), row.get("item_description")),
        parent_type=category_type,
        category_name=category_name,
        tracking_type=tracking_type,
        acct_unit="Ream" if row.get("matched_item_code") == "ITM-0001" else "No.",
        specifications=first_text(row.get("item_specifications")),
    )


def create_items(
    rows: list[dict[str, str]],
    parents: dict[str, Category],
    category_cache: dict[tuple[str, str, str], Category],
    admin: User,
) -> tuple[dict[str, Item], dict[str, Item]]:
    by_existing_code: dict[str, PlannedItemDefinition] = {}
    by_planned_key: dict[str, PlannedItemDefinition] = {}
    sample_rows_by_existing_code: dict[str, dict[str, str]] = {}

    for row in rows:
        if row.get("item_import_action") == "link_existing_item":
            code = row["matched_item_code"]
            by_existing_code.setdefault(code, item_definition_from_existing_row(row))
            sample_rows_by_existing_code.setdefault(code, row)
        else:
            key = row["planned_item_key"]
            by_planned_key.setdefault(key, PLANNED_NEW_ITEMS[key])

    existing_items: dict[str, Item] = {}
    planned_items: dict[str, Item] = {}

    for code, definition in sorted(by_existing_code.items()):
        category = category_for(
            parents,
            category_cache,
            definition.parent_type,
            definition.category_name,
            definition.tracking_type,
        )
        sample = sample_rows_by_existing_code[code]
        item, _ = Item.objects.update_or_create(
            code=code,
            defaults={
                "name": definition.name,
                "category": category,
                "description": first_text(sample.get("item_description")),
                "acct_unit": definition.acct_unit,
                "specifications": definition.specifications,
                "is_active": True,
                "is_provisional": False,
                "created_by": admin,
            },
        )
        existing_items[code] = item

    for index, (key, definition) in enumerate(sorted(by_planned_key.items()), start=1):
        category = category_for(
            parents,
            category_cache,
            definition.parent_type,
            definition.category_name,
            definition.tracking_type,
        )
        item, _ = Item.objects.update_or_create(
            code=stable_code("LEG", index),
            defaults={
                "name": definition.name,
                "category": category,
                "description": key,
                "acct_unit": definition.acct_unit,
                "specifications": definition.specifications,
                "is_active": True,
                "is_provisional": False,
                "created_by": admin,
            },
        )
        planned_items[key] = item

    return existing_items, planned_items


def get_policy(admin: User) -> DepreciationPolicy:
    policy, _ = DepreciationPolicy.objects.update_or_create(
        name="FBR WDV",
        defaults={
            "method": DepreciationMethod.WDV,
            "fiscal_year_start_month": 7,
            "fiscal_year_start_day": 1,
            "is_default": True,
            "is_active": True,
            "created_by": admin,
        },
    )
    return policy


def depreciation_class_code(item: Item) -> str:
    return f"DEP-{item.code}"[:50]


def get_asset_class(item: Item, policy: DepreciationPolicy, admin: User) -> DepreciationAssetClass:
    asset_class, _ = DepreciationAssetClass.objects.update_or_create(
        code=depreciation_class_code(item),
        defaults={
            "name": item.name,
            "category": item.category,
            "policy": policy,
            "description": f"Legacy import item-based depreciation class for {item.code}.",
            "is_active": True,
            "created_by": admin,
        },
    )
    DepreciationRateVersion.objects.update_or_create(
        asset_class=asset_class,
        effective_from=RATE_EFFECTIVE_FROM,
        defaults={
            "rate": LEGACY_RATE,
            "effective_to": None,
            "source_reference": "Legacy inspection import default fixed asset rate",
            "notes": "Default rate requested for imported fixed assets.",
            "created_by": admin,
            "approved_by": admin,
        },
    )
    return asset_class


def create_depreciation_setup(items: list[Item], admin: User) -> dict[int, DepreciationAssetClass]:
    policy = get_policy(admin)
    asset_classes: dict[int, DepreciationAssetClass] = {}
    for item in sorted(items, key=lambda obj: obj.code):
        if item.category.get_category_type() == CategoryType.FIXED_ASSET:
            asset_classes[item.id] = get_asset_class(item, policy, admin)
    return asset_classes


def location_by_id(raw_id: str) -> Location:
    if not raw_id:
        raise RuntimeError("Missing location id in import row.")
    return Location.objects.get(pk=int(raw_id))


def central_store_location() -> Location:
    root = Location.objects.filter(parent_location__isnull=True).order_by("id").first()
    if not root or not root.auto_created_store_id:
        raise RuntimeError("Root location or root auto-created central store is missing.")
    return root.auto_created_store


def stock_register_for(
    row: dict[str, str],
    item: Item,
    department: Location,
    central_store: Location,
    admin: User,
    *,
    central: bool,
) -> tuple[StockRegister, str, str]:
    category_type = item.category.get_category_type()
    default_type = "CSR" if category_type == CategoryType.CONSUMABLE else "DSR"
    if central:
        store = central_store
        number = first_text(
            row.get("planned_central_register_number"),
            default=f"Legacy Central {default_type}",
        )
        register_type = first_text(row.get("planned_central_register_type"), default=default_type)
        page = normalize_page(row.get("central_register_page_no"), 910000 + integer(row.get("source_line")))
    else:
        store_id = row.get("stock_register_store_id")
        store = Location.objects.filter(pk=int(store_id)).first() if store_id else department.auto_created_store
        if not store:
            raise RuntimeError(f"Department '{department.name}' has no auto-created store.")
        number = first_text(
            row.get("planned_stock_register_number"),
            default=f"Legacy Department {default_type}",
        )
        register_type = first_text(row.get("planned_stock_register_type"), default=default_type)
        page = normalize_page(row.get("stock_register_page_no"), 810000 + integer(row.get("source_line")))

    register, _ = StockRegister.objects.update_or_create(
        register_number=number,
        store=store,
        defaults={
            "register_type": register_type if register_type in {"CSR", "DSR"} else default_type,
            "is_active": True,
            "created_by": admin,
        },
    )
    return register, number, page


def row_item(row: dict[str, str], existing_items: dict[str, Item], planned_items: dict[str, Item]) -> Item:
    if row.get("item_import_action") == "link_existing_item":
        return existing_items[row["matched_item_code"]]
    return planned_items[row["planned_item_key"]]


def create_inspections(
    rows: list[dict[str, str]],
    existing_items: dict[str, Item],
    planned_items: dict[str, Item],
    asset_classes: dict[int, DepreciationAssetClass],
    admin: User,
    *,
    complete: bool,
) -> None:
    central_store = central_store_location()
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["inspection_key"]].append(row)

    for inspection_key, item_rows in grouped.items():
        first = item_rows[0]
        department = location_by_id(first["resolved_department_id"])
        inspection_date = (
            parse_date(first.get("date_of_inspection"))
            or parse_date(first.get("certificate_date"))
            or timezone.localdate()
        )
        certificate_date = parse_date(first.get("certificate_date")) or inspection_date

        inspection, _ = InspectionCertificate.objects.update_or_create(
            contract_no=first["proposed_contract_no"],
            defaults={
                "date": certificate_date,
                "contract_date": parse_date(first.get("contract_date")),
                "contractor_name": first_text(first.get("contractor_name"), default="Unknown"),
                "contractor_address": first_text(first.get("contractor_address")),
                "indenter": first_text(first.get("indenter"), default="NIL"),
                "indent_no": first_text(first.get("indent_no"), default="NIL"),
                "department": department,
                "date_of_delivery": parse_date(first.get("date_of_delivery")),
                "delivery_type": first_text(first.get("delivery_type"), default="FULL"),
                "remarks": first_text(first.get("remarks"), default=f"Imported from {inspection_key}."),
                "inspected_by": "Legacy inspection committee",
                "date_of_inspection": inspection_date,
                "consignee_name": first_text(first.get("consignee_name")),
                "consignee_designation": first_text(first.get("consignee_designation")),
                "stage": InspectionStage.DRAFT,
                "status": "DRAFT",
                "initiated_by": admin,
            },
        )
        inspection.items.all().delete()

        for idx, row in enumerate(item_rows, start=1):
            item = row_item(row, existing_items, planned_items)
            stock_register, stock_no, stock_page = stock_register_for(
                row,
                item,
                department,
                central_store,
                admin,
                central=False,
            )
            central_register, central_no, central_page = stock_register_for(
                row,
                item,
                department,
                central_store,
                admin,
                central=True,
            )
            accepted_quantity = integer(row.get("accepted_quantity"), default=1)
            tendered_quantity = max(integer(row.get("tendered_quantity"), default=accepted_quantity), accepted_quantity)
            rejected_quantity = integer(row.get("rejected_quantity"), default=0)
            if accepted_quantity + rejected_quantity > tendered_quantity:
                tendered_quantity = accepted_quantity + rejected_quantity
            item_date = (
                parse_date(row.get("date_of_inspection"))
                or inspection.date_of_inspection
                or inspection.date
            )
            is_fixed = item.category.get_category_type() == CategoryType.FIXED_ASSET

            InspectionItem.objects.create(
                inspection_certificate=inspection,
                item=item,
                item_description=first_text(row.get("item_description"), row.get("matched_item_name"), default=item.name),
                item_specifications=first_text(row.get("item_specifications"), item.specifications),
                tendered_quantity=tendered_quantity,
                accepted_quantity=accepted_quantity,
                rejected_quantity=rejected_quantity,
                unit_price=money(row.get("unit_price_candidate")),
                remarks=(
                    f"Legacy row {row.get('item_row_key')}; source line {row.get('source_line')}. "
                    f"Source gaps: {row.get('source_gaps') or 'none'}."
                ),
                stock_register=stock_register,
                stock_register_no=stock_no,
                stock_register_page_no=stock_page,
                stock_entry_date=parse_date(row.get("stock_entry_date")) or item_date,
                central_register=central_register,
                central_register_no=central_no,
                central_register_page_no=central_page,
                depreciation_asset_class=asset_classes.get(item.id) if is_fixed else None,
                capitalization_date=item_date if is_fixed else None,
            )

        if complete:
            now = timezone.now()
            inspection.stage = InspectionStage.COMPLETED
            inspection.status = "COMPLETED"
            inspection.stock_filled_by = admin
            inspection.stock_filled_at = now
            inspection.central_store_filled_by = admin
            inspection.central_store_filled_at = now
            inspection.finance_reviewed_by = admin
            inspection.finance_reviewed_at = now
            inspection.finance_check_date = inspection.date_of_inspection or inspection.date
            inspection.save()


def print_summary(label: str) -> None:
    counts = {
        "users": User.objects.count(),
        "locations": Location.objects.count(),
        "categories": Category.objects.count(),
        "items": Item.objects.count(),
        "stock_registers": StockRegister.objects.count(),
        "inspections": InspectionCertificate.objects.count(),
        "inspection_items": InspectionItem.objects.count(),
        "stock_entries": apps.get_model("inventory", "StockEntry").objects.count(),
        "stock_records": apps.get_model("inventory", "StockRecord").objects.count(),
        "item_instances": apps.get_model("inventory", "ItemInstance").objects.count(),
        "item_batches": apps.get_model("inventory", "ItemBatch").objects.count(),
        "fixed_asset_entries": apps.get_model("inventory", "FixedAssetRegisterEntry").objects.count(),
        "depreciation_asset_classes": DepreciationAssetClass.objects.count(),
        "depreciation_rate_versions": DepreciationRateVersion.objects.count(),
    }
    print(label)
    for key, value in counts.items():
        print(f"  {key}: {value}")


def main() -> int:
    args = parse_args()
    csv_path = Path(args.csv)
    if args.clean and not (args.yes_clean or args.dry_run):
        raise RuntimeError("--clean requires --yes-clean for a real run, or --dry-run.")

    rows = load_rows(csv_path)
    admin = importer_user(args.admin_username)
    complete = not args.leave_draft

    print_summary("Before import")
    with transaction.atomic():
        if args.clean:
            clean_database(admin, keep_all_users=args.keep_all_users)
        parents, category_cache = create_categories()
        existing_items, planned_items = create_items(rows, parents, category_cache, admin)
        all_items = list(existing_items.values()) + list(planned_items.values())
        asset_classes = create_depreciation_setup(all_items, admin)
        create_inspections(
            rows,
            existing_items,
            planned_items,
            asset_classes,
            admin,
            complete=complete,
        )
        print_summary("After import inside transaction")
        if args.dry_run:
            transaction.set_rollback(True)
            print("DRY RUN: transaction marked for rollback.")

    print_summary("Final database state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
