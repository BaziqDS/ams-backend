from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from itertools import cycle
import random
import time
from typing import Any

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.db import close_old_connections, connections
from django.test import override_settings
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.test import APIClient
from rest_framework.views import APIView

from inventory.models import (
    AssetValueAdjustment,
    Category,
    DepreciationAssetClass,
    DepreciationRun,
    FixedAssetRegisterEntry,
    InspectionCertificate,
    InspectionItem,
    Item,
    ItemBatch,
    ItemInstance,
    Location,
    Person,
    StockAllocation,
    StockEntry,
    StockRecord,
    StockRegister,
)
from inventory.models.category_model import CategoryType, TrackingType
from inventory.models.depreciation_model import AssetAdjustmentType
from inventory.models.location_model import LocationType
from notifications.models import NotificationEvent, UserNotification

DEFAULT_DEMO_PASSWORD = "DemoPass123!"

CATEGORY_BLUEPRINTS: list[dict[str, Any]] = [
    {
        "name": "Computing Equipment",
        "category_type": CategoryType.FIXED_ASSET,
        "default_depreciation_rate": "30.00",
        "children": [
            ("Serialized Assets", TrackingType.INDIVIDUAL),
            ("Bulk Assets", TrackingType.QUANTITY),
        ],
    },
    {
        "name": "Laboratory Equipment",
        "category_type": CategoryType.FIXED_ASSET,
        "default_depreciation_rate": "15.00",
        "children": [
            ("Serialized Assets", TrackingType.INDIVIDUAL),
            ("Bulk Assets", TrackingType.QUANTITY),
        ],
    },
    {
        "name": "Furniture & Fixtures",
        "category_type": CategoryType.FIXED_ASSET,
        "default_depreciation_rate": "10.00",
        "children": [
            ("Serialized Assets", TrackingType.INDIVIDUAL),
            ("Bulk Assets", TrackingType.QUANTITY),
        ],
    },
    {
        "name": "Audio Visual Systems",
        "category_type": CategoryType.FIXED_ASSET,
        "default_depreciation_rate": "20.00",
        "children": [
            ("Serialized Assets", TrackingType.INDIVIDUAL),
            ("Bulk Assets", TrackingType.QUANTITY),
        ],
    },
    {
        "name": "Office Consumables",
        "category_type": CategoryType.CONSUMABLE,
        "children": [
            ("General Stock", TrackingType.QUANTITY),
            ("Project Stock", TrackingType.QUANTITY),
        ],
    },
    {
        "name": "IT Consumables",
        "category_type": CategoryType.CONSUMABLE,
        "children": [
            ("General Stock", TrackingType.QUANTITY),
            ("Project Stock", TrackingType.QUANTITY),
        ],
    },
    {
        "name": "Electrical Supplies",
        "category_type": CategoryType.CONSUMABLE,
        "children": [
            ("General Stock", TrackingType.QUANTITY),
            ("Workshop Stock", TrackingType.QUANTITY),
        ],
    },
    {
        "name": "Chemical Stocks",
        "category_type": CategoryType.PERISHABLE,
        "children": [
            ("Lab Lots", TrackingType.QUANTITY),
            ("Secure Lots", TrackingType.QUANTITY),
        ],
    },
    {
        "name": "Sanitation Supplies",
        "category_type": CategoryType.PERISHABLE,
        "children": [
            ("Cleaning Lots", TrackingType.QUANTITY),
            ("Emergency Lots", TrackingType.QUANTITY),
        ],
    },
]

ROLE_BLUEPRINTS: list[dict[str, Any]] = [
    {
        "name": "Operations Admin",
        "requires_store": False,
        "module_selections": {
            "users": "full",
            "roles": "full",
            "locations": "full",
            "categories": "full",
            "items": "full",
            "stock-entries": "full",
            "stock-registers": "full",
            "reports": "view",
            "inspections": "full",
            "depreciation": "full",
        },
    },
    {
        "name": "Inventory Controller",
        "requires_store": True,
        "module_selections": {
            "locations": "manage",
            "categories": "manage",
            "items": "manage",
            "stock-entries": "full",
            "stock-registers": "full",
            "reports": "view",
            "inspections": "view",
            "depreciation": "view",
        },
    },
    {
        "name": "Inspection Coordinator",
        "requires_store": False,
        "module_selections": {
            "inspections": "full",
            "items": "view",
            "locations": "view",
            "stock-registers": "view",
            "reports": "view",
            "depreciation": "view",
        },
    },
    {
        "name": "Department Store Officer",
        "requires_store": True,
        "module_selections": {
            "items": "view",
            "locations": "view",
            "stock-entries": "manage",
            "stock-registers": "manage",
            "reports": "view",
        },
    },
    {
        "name": "Depreciation Analyst",
        "requires_store": False,
        "module_selections": {
            "depreciation": "full",
            "items": "view",
            "categories": "view",
            "inspections": "view",
            "reports": "view",
        },
    },
    {
        "name": "Audit Viewer",
        "requires_store": False,
        "module_selections": {
            "users": "view",
            "roles": "view",
            "locations": "view",
            "categories": "view",
            "items": "view",
            "stock-entries": "view",
            "stock-registers": "view",
            "reports": "view",
            "inspections": "view",
            "depreciation": "view",
        },
    },
    {
        "name": "User Administration Officer",
        "requires_store": False,
        "module_selections": {
            "users": "full",
            "roles": "manage",
            "locations": "view",
            "reports": "view",
        },
    },
    {
        "name": "Catalog Maintainer",
        "requires_store": False,
        "module_selections": {
            "categories": "full",
            "items": "full",
            "reports": "view",
            "depreciation": "view",
        },
    },
]

DEPARTMENT_NAMES = [
    "Computer Science",
    "Electrical Engineering",
    "Mechanical Engineering",
    "Civil Engineering",
    "Architecture",
    "Applied Physics",
    "Textile Engineering",
    "Chemistry",
]

CHILD_LOCATION_BLUEPRINTS = [
    ("Innovation Lab", LocationType.LAB),
    ("Faculty Office", LocationType.OFFICE),
    ("Teaching Room", LocationType.ROOM),
    ("AV Hall", LocationType.AV_HALL),
]

FIXED_INDIVIDUAL_TEMPLATES = [
    "Laptop",
    "Desktop Workstation",
    "Network Switch",
    "Microscope",
    "Oscilloscope",
    "Digital Multimeter",
    "Executive Chair",
    "Fireproof Cabinet",
    "Projector",
    "Smart Display",
    "PA Amplifier",
    "Document Camera",
]
FIXED_QUANTITY_TEMPLATES = [
    "Classroom Chair Set",
    "Training Table Set",
    "Storage Rack Bundle",
    "Laboratory Stool Set",
    "Display Speaker Cluster",
    "Lecture Podium Fixture",
    "Workshop Tool Cabinet Set",
    "Reception Counter Module",
]
CONSUMABLE_TEMPLATES = [
    "A4 Paper Reams",
    "Toner Cartridge Packs",
    "Ethernet Patch Cable Bundles",
    "LED Tube Boxes",
    "Electrical Socket Kits",
    "UPS Battery Packs",
    "Printer Ribbon Sets",
    "Stationery Supply Boxes",
    "Label Roll Packs",
    "Extension Cord Bundles",
]
PERISHABLE_TEMPLATES = [
    "Acetone Lab Lots",
    "Disinfectant Drums",
    "Glass Cleaner Lots",
    "Industrial Solvent Lots",
    "Bleach Canisters",
    "Lab Reagent Bundles",
]

FIRST_NAMES = [
    "Ayesha",
    "Bilal",
    "Danish",
    "Eman",
    "Fatima",
    "Hamza",
    "Iqra",
    "Junaid",
    "Kashif",
    "Laiba",
    "Maham",
    "Noman",
    "Omair",
    "Rabia",
    "Saad",
    "Tania",
    "Usman",
    "Wajeeha",
    "Yasir",
    "Zara",
]
LAST_NAMES = [
    "Ahmed",
    "Ali",
    "Butt",
    "Farooq",
    "Hassan",
    "Iqbal",
    "Javed",
    "Khan",
    "Malik",
    "Qureshi",
]
DESIGNATIONS = [
    "Inventory Officer",
    "Store Assistant",
    "Lab Engineer",
    "Department Coordinator",
    "Procurement Analyst",
    "Accounts Assistant",
    "IT Technician",
    "Facilities Officer",
]

FIXED_CAPITALIZATION_DATES = [
    date(2024, 3, 15),
    date(2024, 10, 12),
    date(2025, 9, 5),
    date(2025, 12, 18),
]


@dataclass(slots=True)
class PopulateConfig:
    tag: str = "DEMO"
    role_count: int = 20
    standalone_units: int = 20
    child_locations_per_unit: int = 2
    internal_stores_per_unit: int = 1
    fixed_asset_parent_count: int = 20
    consumable_parent_count: int = 6
    perishable_parent_count: int = 4
    item_count: int = 40
    person_count: int = 20
    user_count: int = 20
    completed_root_inspections: int = 20
    completed_department_inspections: int = 20
    finance_review_inspections: int = 6
    central_register_inspections: int = 6
    draft_inspections: int = 6
    manual_person_allocations: int = 10
    manual_location_allocations: int = 10
    manual_returns: int = 10
    depreciation_run_count: int = 20
    asset_adjustments: int = 20
    user_password: str = DEFAULT_DEMO_PASSWORD


class PopulationError(RuntimeError):
    pass


class DemoDataPopulator:
    def __init__(self, user: User, config: PopulateConfig):
        if not user or not user.is_authenticated:
            raise PopulationError("An authenticated superuser is required.")
        if not user.is_superuser:
            raise PopulationError("Demo data population is restricted to superusers.")

        self.user = user
        self.config = config
        self.client = APIClient()
        self.client.defaults["HTTP_HOST"] = "localhost"
        self.client.force_authenticate(user=user)
        self.tag_slug = slugify(config.tag) or "demo"
        self.tag_key = self.tag_slug.replace("-", "")
        tag_prefix = self.tag_key[:4] or "demo"
        tag_suffix = self.tag_key[-2:] if len(self.tag_key) > 4 else ""
        self.short_tag = f"{tag_prefix}{tag_suffix}".upper().ljust(4, "D")[:6]
        self.title_tag = self.tag_slug.replace("-", " ").title()
        self.username_prefix = self.tag_key.lower()
        self.rng = random.Random(self.tag_key)
        self.before_counts = self._snapshot_counts()

        self.root: Location | None = None
        self.created_standalones: list[Location] = []
        self.created_department_children: defaultdict[int, list[Location]] = defaultdict(list)
        self.created_internal_stores: defaultdict[int, list[Location]] = defaultdict(list)
        self.registers_by_store: defaultdict[int, list[StockRegister]] = defaultdict(list)
        self.created_roles: list[dict[str, Any]] = []
        self.created_users: list[User] = []
        self.created_people: list[Person] = []
        self.fixed_parent_categories: list[Category] = []
        self.subcategories_by_kind: defaultdict[str, list[Category]] = defaultdict(list)
        self.items_by_kind: defaultdict[str, list[Item]] = defaultdict(list)
        self.asset_class_by_parent: dict[int, DepreciationAssetClass] = {}
        self.created_inspections: list[InspectionCertificate] = []
        self.created_allocation_entries: list[StockEntry] = []
        self.created_asset_ids: set[int] = set()

    def populate(self) -> dict[str, Any]:
        self.root = self.ensure_root_location()
        self.create_locations()
        self.create_categories()
        self.create_items()
        self.create_stock_registers()
        self.create_roles()
        self.create_users()
        self.create_people()
        self.create_depreciation_setup()
        self.create_inspections()
        self.create_manual_allocations_and_returns()
        self.close_and_reopen_registers()
        self.create_depreciation_runs()
        self.create_asset_adjustments()
        return self.build_summary()

    def _snapshot_counts(self) -> dict[str, int]:
        return {
            "locations": Location.objects.count(),
            "categories": Category.objects.count(),
            "items": Item.objects.count(),
            "persons": Person.objects.count(),
            "stock_registers": StockRegister.objects.count(),
            "roles": Group.objects.count(),
            "users": User.objects.count(),
            "inspections": InspectionCertificate.objects.count(),
            "stock_entries": StockEntry.objects.count(),
            "allocations": StockAllocation.objects.count(),
            "item_batches": ItemBatch.objects.count(),
            "item_instances": ItemInstance.objects.count(),
            "fixed_assets": FixedAssetRegisterEntry.objects.count(),
            "asset_classes": DepreciationAssetClass.objects.count(),
            "depreciation_runs": DepreciationRun.objects.count(),
            "asset_adjustments": AssetValueAdjustment.objects.count(),
            "notification_events": NotificationEvent.objects.count(),
            "user_notifications": UserNotification.objects.count(),
        }

    def _body(self, response) -> Any:
        if hasattr(response, "data"):
            return response.data
        content = getattr(response, "content", b"") or b""
        try:
            return content.decode("utf-8")
        except Exception:  # pragma: no cover - defensive
            return str(content)

    def _expect(self, response, expected: tuple[int, ...], *, method: str, path: str) -> Any:
        if response.status_code not in expected:
            raise PopulationError(f"{method} {path} failed with {response.status_code}: {self._body(response)}")
        return self._body(response)

    def _release_db_locks(self, pause_seconds: float = 0.05) -> None:
        try:
            connections.close_all()
        finally:
            close_old_connections()
        time.sleep(pause_seconds)

    @staticmethod
    def _is_database_lock_error(exc: Exception) -> bool:
        return "database is locked" in str(exc).lower()

    def _request_with_retry(self, method: str, path: str, payload: dict[str, Any], expected: tuple[int, ...]) -> Any:
        last_exc: Exception | None = None
        for attempt in range(1, 13):
            close_old_connections()
            response = None
            try:
                request_fn = getattr(self.client, method)
                response = request_fn(path, payload, format="json")
                return self._expect(response, expected, method=method.upper(), path=path)
            except PopulationError as exc:
                if not self._is_database_lock_error(exc):
                    raise
                last_exc = exc
            except Exception as exc:  # pragma: no cover - exercised against real sqlite file locks
                if not self._is_database_lock_error(exc):
                    raise
                last_exc = exc
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
                self._release_db_locks(0.05 * attempt)

            time.sleep(0.1 * attempt)

        raise PopulationError(
            f"{method.upper()} {path} could not complete because the sqlite database remained locked. "
            f"Last error: {last_exc}"
        )

    def _post(self, path: str, payload: dict[str, Any] | None = None, *, expected: tuple[int, ...] = (201, 200)) -> Any:
        return self._request_with_retry("post", path, payload or {}, expected)

    def _patch(self, path: str, payload: dict[str, Any], *, expected: tuple[int, ...] = (200,)) -> Any:
        return self._request_with_retry("patch", path, payload, expected)

    def _get_register(self, store_id: int, register_type: str) -> StockRegister | None:
        registers = [register for register in self.registers_by_store.get(store_id, []) if register.is_active]
        for register in registers:
            if register.register_type == register_type:
                return register
        return registers[0] if registers else None

    def _preferred_register(self, store_id: int, item: Item | None = None) -> StockRegister:
        register_type = "DSR" if item and item.category.get_category_type() == CategoryType.FIXED_ASSET else "CSR"
        register = self._get_register(store_id, register_type)
        if register is None:
            register = StockRegister.objects.filter(store_id=store_id, is_active=True, register_type=register_type).order_by("id").first()
        if register is None:
            register = StockRegister.objects.filter(store_id=store_id, is_active=True).order_by("id").first()
        if register is None:
            raise PopulationError(f"No active stock register is available for store {store_id}.")
        return register

    def _category_kind(self, category: Category) -> str:
        category_type = category.get_category_type()
        tracking_type = category.get_tracking_type()
        if category_type == CategoryType.FIXED_ASSET and tracking_type == TrackingType.INDIVIDUAL:
            return "fixed_individual"
        if category_type == CategoryType.FIXED_ASSET and tracking_type == TrackingType.QUANTITY:
            return "fixed_quantity"
        if category_type == CategoryType.CONSUMABLE:
            return "consumable_quantity"
        return "perishable_quantity"

    def _register_created_inspection_assets(self, inspection: InspectionCertificate) -> None:
        self.created_asset_ids.update(
            FixedAssetRegisterEntry.objects.filter(source_inspection=inspection).values_list("id", flat=True)
        )

    def ensure_root_location(self) -> Location:
        root = Location.objects.filter(parent_location__isnull=True).order_by("id").first()
        if root:
            root.refresh_from_db()
            return root

        payload = {
            "name": f"{self.title_tag} University",
            "location_type": LocationType.DEPARTMENT,
            "description": f"Root location created for {self.title_tag} showcase data.",
        }
        data = self._post("/api/inventory/locations/standalone/", payload)
        return Location.objects.get(pk=data["id"])

    def create_locations(self) -> None:
        root = self.root or self.ensure_root_location()

        for index in range(self.config.standalone_units):
            sequence = index + 1
            base_name = DEPARTMENT_NAMES[index % len(DEPARTMENT_NAMES)]
            payload = {
                "name": f"{base_name} {self.title_tag} {sequence:02d}",
                "location_type": LocationType.DEPARTMENT,
                "description": f"Standalone department seeded for {self.title_tag}.",
                "main_store_name": f"{base_name} {self.title_tag} Main Store {sequence:02d}",
            }
            data = self._post("/api/inventory/locations/standalone/", payload)
            department = Location.objects.get(pk=data["id"])
            department.refresh_from_db()
            self.created_standalones.append(department)

            child_specs = [
                CHILD_LOCATION_BLUEPRINTS[child_index % len(CHILD_LOCATION_BLUEPRINTS)]
                for child_index in range(self.config.child_locations_per_unit)
            ]
            for child_index, (suffix, location_type) in enumerate(child_specs, start=1):
                child_data = self._post(
                    f"/api/inventory/locations/{department.id}/children/",
                    {
                        "name": f"{base_name} {suffix} {self.title_tag} {sequence:02d}-{child_index:02d}",
                        "location_type": location_type,
                        "description": f"Operational child location for {base_name}.",
                    },
                )
                child = Location.objects.get(pk=child_data["id"])
                self.created_department_children[department.id].append(child)

            for store_index in range(1, self.config.internal_stores_per_unit + 1):
                child_data = self._post(
                    f"/api/inventory/locations/{department.id}/children/",
                    {
                        "name": f"{base_name} Section Store {self.title_tag} {sequence:02d}-{store_index:02d}",
                        "location_type": LocationType.STORE,
                        "description": f"Operational section store for {base_name}.",
                    },
                )
                child_store = Location.objects.get(pk=child_data["id"])
                self.created_internal_stores[department.id].append(child_store)

        root.refresh_from_db()

    def create_categories(self) -> None:
        plan = [
            (CategoryType.FIXED_ASSET, self.config.fixed_asset_parent_count),
            (CategoryType.CONSUMABLE, self.config.consumable_parent_count),
            (CategoryType.PERISHABLE, self.config.perishable_parent_count),
        ]
        blueprints_by_type: dict[str, list[dict[str, Any]]] = {
            category_type: [blueprint for blueprint in CATEGORY_BLUEPRINTS if blueprint["category_type"] == category_type]
            for category_type, _count in plan
        }

        for category_type, count in plan:
            blueprints = blueprints_by_type.get(category_type, [])
            if not blueprints:
                continue

            for index in range(count):
                blueprint = blueprints[index % len(blueprints)]
                sequence = index + 1
                parent_payload: dict[str, Any] = {
                    "name": f"{blueprint['name']} {self.title_tag} {category_type[:3]} {sequence:02d}",
                    "category_type": blueprint["category_type"],
                    "notes": f"Seeded for {self.title_tag} showcase.",
                }
                if blueprint.get("default_depreciation_rate"):
                    parent_payload["default_depreciation_rate"] = blueprint["default_depreciation_rate"]

                parent_data = self._post("/api/inventory/categories/", parent_payload)
                parent = Category.objects.get(pk=parent_data["id"])
                if parent.get_category_type() == CategoryType.FIXED_ASSET:
                    self.fixed_parent_categories.append(parent)

                child_templates = blueprint["children"]
                for child_index, (child_name, tracking_type) in enumerate(child_templates, start=1):
                    child_data = self._post(
                        "/api/inventory/categories/",
                        {
                            "name": f"{child_name} {self.title_tag} {sequence:02d}-{child_index:02d}",
                            "parent_category": parent.id,
                            "tracking_type": tracking_type,
                            "notes": f"Child category for {parent.name}.",
                        },
                    )
                    child = Category.objects.get(pk=child_data["id"])
                    self.subcategories_by_kind[self._category_kind(child)].append(child)

    def create_items(self) -> None:
        template_map: dict[str, list[str]] = {
            "fixed_individual": FIXED_INDIVIDUAL_TEMPLATES,
            "fixed_quantity": FIXED_QUANTITY_TEMPLATES,
            "consumable_quantity": CONSUMABLE_TEMPLATES,
            "perishable_quantity": PERISHABLE_TEMPLATES,
        }
        kind_order = [
            "fixed_individual",
            "fixed_quantity",
            "consumable_quantity",
            "perishable_quantity",
        ]
        counters: defaultdict[str, int] = defaultdict(int)
        template_indices: defaultdict[str, int] = defaultdict(int)

        for index in range(self.config.item_count):
            primary_kind = kind_order[index % len(kind_order)]
            ordered_kinds = kind_order[kind_order.index(primary_kind):] + kind_order[:kind_order.index(primary_kind)]
            kind = next((candidate for candidate in ordered_kinds if self.subcategories_by_kind.get(candidate)), None)
            if kind is None:
                continue

            subcategories = self.subcategories_by_kind[kind]
            templates = template_map[kind]
            template = templates[template_indices[kind] % len(templates)]
            template_indices[kind] += 1

            category = subcategories[counters[kind] % len(subcategories)]
            counters[kind] += 1
            name = f"{template} {self.short_tag}-{counters[kind]:02d}"
            item_data = self._post(
                "/api/inventory/items/",
                {
                    "name": name,
                    "category": category.id,
                    "acct_unit": "Nos" if category.get_tracking_type() == TrackingType.INDIVIDUAL else "Units",
                    "description": f"{template} stocked for the {self.title_tag} showcase.",
                    "specifications": f"Seeded {kind.replace('_', ' ')} item for dashboards.",
                    "low_stock_threshold": 2 if category.get_tracking_type() == TrackingType.INDIVIDUAL else 8,
                    "is_active": True,
                },
            )
            item = Item.objects.get(pk=item_data["id"])
            self.items_by_kind[kind].append(item)

    def create_stock_registers(self) -> None:
        stores: list[Location] = []
        root = self.root or self.ensure_root_location()
        root.refresh_from_db()
        if root.auto_created_store_id:
            stores.append(root.auto_created_store)

        for department in self.created_standalones:
            department.refresh_from_db()
            if department.auto_created_store_id:
                stores.append(department.auto_created_store)
            stores.extend(self.created_internal_stores.get(department.id, []))

        seen_store_ids: set[int] = set()
        for store in stores:
            if not store or store.id in seen_store_ids:
                continue
            seen_store_ids.add(store.id)
            for register_type in ("CSR", "DSR"):
                register_data = self._post(
                    "/api/inventory/stock-registers/",
                    {
                        "register_number": f"{register_type}-{self.short_tag}-{store.id:03d}-{len(self.registers_by_store[store.id]) + 1}",
                        "register_type": register_type,
                        "store": store.id,
                        "is_active": True,
                    },
                )
                register = StockRegister.objects.get(pk=register_data["id"])
                self.registers_by_store[store.id].append(register)

    def create_roles(self) -> None:
        for index in range(self.config.role_count):
            blueprint = ROLE_BLUEPRINTS[index % len(ROLE_BLUEPRINTS)]
            role_data = self._post(
                "/api/users/groups/",
                {
                    "name": f"{self.title_tag} {blueprint['name']} {index + 1:02d}",
                    "module_selections": blueprint["module_selections"],
                },
            )
            role = Group.objects.get(pk=role_data["id"])
            self.created_roles.append({
                "group": role,
                "requires_store": blueprint["requires_store"],
            })

    def create_users(self) -> None:
        if not self.created_roles:
            return

        location_cycle = [self.root] + self.created_standalones if self.root else self.created_standalones[:]
        if not location_cycle:
            return

        for index in range(self.config.user_count):
            first_name = FIRST_NAMES[index % len(FIRST_NAMES)]
            last_name = LAST_NAMES[index % len(LAST_NAMES)]
            role_info = self.created_roles[index % len(self.created_roles)]
            assigned_location = location_cycle[index % len(location_cycle)]
            assigned_ids = [assigned_location.id]

            role_requires_store = role_info["group"].permissions.filter(
                content_type__app_label="inventory",
                codename="create_stock_entries",
            ).exists() or role_info["requires_store"]

            if role_requires_store:
                if assigned_location == self.root and self.root and self.root.auto_created_store_id:
                    assigned_ids.append(self.root.auto_created_store_id)
                elif assigned_location and assigned_location.auto_created_store_id:
                    assigned_ids.append(assigned_location.auto_created_store_id)

            payload = {
                "username": f"{self.username_prefix}.user{index + 1:02d}",
                "email": f"{self.username_prefix}.user{index + 1:02d}@example.com",
                "first_name": first_name,
                "last_name": last_name,
                "password": self.config.user_password,
                "employee_id": f"EMP-{self.short_tag}-{index + 1:04d}",
                "assigned_locations": assigned_ids,
                "groups": [role_info["group"].id],
                "is_staff": index % 4 == 0,
                "is_active": index % 9 != 0,
            }
            user_data = self._post("/api/users/management/", payload)
            self.created_users.append(User.objects.get(pk=user_data["id"]))

    def create_people(self) -> None:
        departments = self.created_standalones[:]
        if not departments and self.root:
            departments = [self.root]
        if not departments:
            return

        for index in range(self.config.person_count):
            department = departments[index % len(departments)]
            full_name = f"{FIRST_NAMES[(index + 3) % len(FIRST_NAMES)]} {LAST_NAMES[(index + 5) % len(LAST_NAMES)]}"
            person_data = self._post(
                "/api/inventory/persons/",
                {
                    "name": full_name,
                    "designation": DESIGNATIONS[index % len(DESIGNATIONS)],
                    "department": department.name,
                    "standalone_locations": [department.id],
                    "is_active": True,
                },
            )
            self.created_people.append(Person.objects.get(pk=person_data["id"]))

    def create_depreciation_setup(self) -> None:
        for index, category in enumerate(self.fixed_parent_categories, start=1):
            asset_class_data = self._post(
                "/api/inventory/depreciation/asset-classes/",
                {
                    "name": f"{category.name} Profile",
                    "code": f"DEP-{self.short_tag}-{index:02d}",
                    "category": category.id,
                    "description": f"Depreciation profile for {category.name}.",
                    "is_active": True,
                },
            )
            asset_class = DepreciationAssetClass.objects.get(pk=asset_class_data["id"])
            self.asset_class_by_parent[category.id] = asset_class
            self._post(
                "/api/inventory/depreciation/rates/",
                {
                    "asset_class": asset_class.id,
                    "rate": str(category.get_depreciation_rate() or Decimal("10.00")),
                    "effective_from": "2023-07-01",
                    "source_reference": f"{self.title_tag} baseline rate",
                    "notes": "Seeded baseline depreciation rate.",
                },
            )
            if index % 2 == 0:
                self._post(
                    "/api/inventory/depreciation/rates/",
                    {
                        "asset_class": asset_class.id,
                        "rate": str((category.get_depreciation_rate() or Decimal("10.00")) + Decimal("2.50")),
                        "effective_from": "2025-07-01",
                        "source_reference": f"{self.title_tag} revised rate",
                        "notes": "Seeded revised depreciation rate.",
                    },
                )

    def _build_inspection_item_payload(self, item: Item, *, accepted_quantity: int, unit_price: Decimal) -> dict[str, Any]:
        return {
            "item": item.id,
            "item_description": item.name,
            "item_specifications": item.specifications or "",
            "tendered_quantity": accepted_quantity,
            "accepted_quantity": accepted_quantity,
            "rejected_quantity": 0,
            "unit_price": str(unit_price),
            "remarks": f"Seeded for {self.title_tag}.",
        }

    def _pick_item_for_phase(self, phase_index: int) -> Item:
        phase_order = [
            "fixed_individual",
            "fixed_quantity",
            "consumable_quantity",
            "perishable_quantity",
        ]
        for attempt in range(len(phase_order)):
            kind = phase_order[(phase_index + attempt) % len(phase_order)]
            bucket = self.items_by_kind.get(kind)
            if bucket:
                return bucket[phase_index % len(bucket)]
        raise PopulationError("No seeded items are available for inspection population.")

    def _pick_item_from_kinds(self, preferred_kinds: list[str], cycle_index: int) -> Item:
        if not preferred_kinds:
            return self._pick_item_for_phase(cycle_index)

        start = cycle_index % len(preferred_kinds)
        bucket_index = cycle_index // len(preferred_kinds)
        for offset in range(len(preferred_kinds)):
            kind = preferred_kinds[(start + offset) % len(preferred_kinds)]
            bucket = self.items_by_kind.get(kind)
            if bucket:
                return bucket[bucket_index % len(bucket)]
        return self._pick_item_for_phase(cycle_index)

    def _unit_price_for_item(self, item: Item) -> Decimal:
        category_type = item.category.get_category_type()
        tracking_type = item.category.get_tracking_type()
        if category_type == CategoryType.FIXED_ASSET and tracking_type == TrackingType.INDIVIDUAL:
            return Decimal("125000.00")
        if category_type == CategoryType.FIXED_ASSET:
            return Decimal("32000.00")
        if category_type == CategoryType.PERISHABLE:
            return Decimal("6500.00")
        return Decimal("1800.00")

    def _accepted_quantity_for_item(self, item: Item, phase_index: int) -> int:
        tracking_type = item.category.get_tracking_type()
        if tracking_type == TrackingType.INDIVIDUAL:
            return 1 if phase_index % 2 == 0 else 2
        if item.category.get_category_type() == CategoryType.FIXED_ASSET:
            return 3
        if item.category.get_category_type() == CategoryType.PERISHABLE:
            return 6
        return 10

    def _cap_date_for_index(self, index: int) -> date:
        return FIXED_CAPITALIZATION_DATES[index % len(FIXED_CAPITALIZATION_DATES)]

    def _create_inspection(self, *, phase: str, department: Location, item: Item, sequence: int) -> InspectionCertificate:
        accepted_quantity = self._accepted_quantity_for_item(item, sequence)
        unit_price = self._unit_price_for_item(item)
        base_date = self._cap_date_for_index(sequence) if item.category.get_category_type() == CategoryType.FIXED_ASSET else timezone.localdate() - timedelta(days=(sequence + 1) * 5)
        contract_no = f"{self.config.tag}-{sequence + 1:03d}"

        create_data = {
            "date": base_date.isoformat(),
            "contract_no": contract_no,
            "contract_date": base_date.isoformat(),
            "contractor_name": f"{self.title_tag} Supplier {sequence + 1:02d}",
            "contractor_address": f"Warehouse Block {sequence + 1:02d}",
            "indenter": f"{department.name} Procurement",
            "indent_no": f"IND-{self.short_tag}-{sequence + 1:03d}",
            "department": department.id,
            "date_of_delivery": base_date.isoformat(),
            "delivery_type": "FULL",
            "remarks": f"{self.title_tag} seeded inspection.",
            "inspected_by": f"Inspector {sequence + 1:02d}",
            "date_of_inspection": base_date.isoformat(),
            "consignee_name": f"Consignee {sequence + 1:02d}",
            "consignee_designation": "Store Manager",
            "items": [self._build_inspection_item_payload(item, accepted_quantity=accepted_quantity, unit_price=unit_price)],
            "is_initiated": phase != "draft",
        }
        created = self._post("/api/inventory/inspections/", create_data)
        inspection = InspectionCertificate.objects.get(pk=created["id"])
        self.created_inspections.append(inspection)

        if phase == "draft":
            return inspection

        inspection_item = inspection.items.get()
        item_updates: dict[str, Any] = {"id": inspection_item.id, "item": item.id}
        if department.id != (self.root.id if self.root else None):
            dept_register = self._preferred_register(department.auto_created_store_id, item)
            item_updates.update(
                {
                    "stock_register": dept_register.id,
                    "stock_register_no": dept_register.register_number,
                    "stock_register_page_no": str(sequence + 11),
                    "stock_entry_date": base_date.isoformat(),
                }
            )
            self._patch(f"/api/inventory/inspections/{inspection.id}/", {"items": [item_updates]})
            if phase in {"central", "finance", "completed"}:
                self._post(f"/api/inventory/inspections/{inspection.id}/submit_to_central_register/", {}, expected=(200,))
        elif phase in {"central", "finance", "completed"}:
            inspection.refresh_from_db()

        if phase in {"central", "finance", "completed"}:
            central_register = self._preferred_register(self.root.auto_created_store_id, item)
            central_updates: dict[str, Any] = {
                "id": inspection_item.id,
                "item": item.id,
                "central_register": central_register.id,
                "central_register_no": central_register.register_number,
                "central_register_page_no": str(sequence + 101),
            }
            if item.category.get_tracking_type() == TrackingType.QUANTITY:
                central_updates["batch_number"] = f"{self.short_tag}-LOT-{inspection.id}"
                if item.category.get_category_type() == CategoryType.PERISHABLE:
                    central_updates["manufactured_date"] = base_date.isoformat()
                    central_updates["expiry_date"] = (base_date + timedelta(days=365)).isoformat()
            if item.category.get_category_type() == CategoryType.FIXED_ASSET:
                parent_category = item.category.parent_category or item.category
                asset_class = self.asset_class_by_parent.get(parent_category.id)
                if asset_class:
                    central_updates["depreciation_asset_class"] = asset_class.id
                central_updates["capitalization_cost"] = str(unit_price * accepted_quantity)
                central_updates["capitalization_date"] = self._cap_date_for_index(sequence).isoformat()
            self._patch(f"/api/inventory/inspections/{inspection.id}/", {"items": [central_updates]})

        if phase in {"finance", "completed"}:
            self._post(f"/api/inventory/inspections/{inspection.id}/submit_to_finance_review/", {}, expected=(200,))

        if phase == "completed":
            self._post(f"/api/inventory/inspections/{inspection.id}/complete/", {}, expected=(200,))
            inspection.refresh_from_db()
            self._register_created_inspection_assets(inspection)
            if department.id != (self.root.id if self.root else None):
                self._acknowledge_inspection_receipt(inspection)
        return inspection

    def _acknowledge_inspection_receipt(self, inspection: InspectionCertificate) -> None:
        issue = StockEntry.objects.filter(
            inspection_certificate=inspection,
            entry_type="ISSUE",
        ).order_by("-id").first()
        if not issue:
            return
        receipt = StockEntry.objects.filter(reference_entry=issue, entry_type="RECEIPT").order_by("-id").first()
        if not receipt or receipt.status != "PENDING_ACK":
            return

        items_payload = []
        for line_index, entry_item in enumerate(receipt.items.all().select_related("item", "batch"), start=1):
            ack_register = self._preferred_register(receipt.to_location_id, entry_item.item)
            items_payload.append(
                {
                    "id": entry_item.id,
                    "quantity": entry_item.quantity,
                    "instances": list(entry_item.instances.values_list("id", flat=True)),
                    "ack_stock_register": ack_register.id,
                    "ack_page_number": line_index,
                }
            )
        self._post(
            f"/api/inventory/stock-entries/{receipt.id}/acknowledge/",
            {"items": items_payload},
            expected=(200,),
        )

    def create_inspections(self) -> None:
        if not self.root:
            raise PopulationError("Root location must exist before creating inspections.")

        sequence = 0
        departments = self.created_standalones or [self.root]
        central_departments = [self.root] + departments

        root_completed_kinds = ["fixed_individual", "fixed_quantity"]
        department_completed_kinds = ["consumable_quantity", "perishable_quantity", "fixed_quantity"]
        review_kinds = ["fixed_individual", "consumable_quantity", "fixed_quantity", "perishable_quantity"]

        for index in range(self.config.completed_root_inspections):
            item = self._pick_item_from_kinds(root_completed_kinds, index)
            self._create_inspection(phase="completed", department=self.root, item=item, sequence=sequence)
            sequence += 1

        for index in range(self.config.completed_department_inspections):
            department = departments[index % len(departments)]
            item = self._pick_item_from_kinds(department_completed_kinds, index)
            self._create_inspection(phase="completed", department=department, item=item, sequence=sequence)
            sequence += 1

        for index in range(self.config.finance_review_inspections):
            department = departments[index % len(departments)]
            item = self._pick_item_from_kinds(review_kinds, index)
            self._create_inspection(phase="finance", department=department, item=item, sequence=sequence)
            sequence += 1

        for index in range(self.config.central_register_inspections):
            department = central_departments[index % len(central_departments)]
            item = self._pick_item_from_kinds(review_kinds, index)
            self._create_inspection(phase="central", department=department, item=item, sequence=sequence)
            sequence += 1

        for index in range(self.config.draft_inspections):
            department = central_departments[index % len(central_departments)]
            item = self._pick_item_from_kinds(review_kinds, index)
            self._create_inspection(phase="draft", department=department, item=item, sequence=sequence)
            sequence += 1

    def _eligible_allocation_records(self) -> list[StockRecord]:
        records: list[StockRecord] = []
        for department in self.created_standalones:
            if not department.auto_created_store_id:
                continue
            queryset = StockRecord.objects.select_related("item", "item__category", "batch", "location").filter(
                location_id=department.auto_created_store_id,
                quantity__gt=0,
            )
            for record in queryset:
                if record.available_quantity <= 0:
                    continue
                if record.item.category.get_tracking_type() != TrackingType.QUANTITY:
                    continue
                records.append(record)
        return records

    def _fresh_allocation_record(self, record_id: int) -> StockRecord | None:
        return StockRecord.objects.select_related("item", "item__category", "batch", "location", "location__parent_location").filter(
            id=record_id,
            quantity__gt=0,
        ).first()

    def _next_available_allocation_record(self, record_ids: list[int], start_index: int) -> StockRecord | None:
        if not record_ids:
            return None
        for offset in range(len(record_ids)):
            record = self._fresh_allocation_record(record_ids[(start_index + offset) % len(record_ids)])
            if record and record.available_quantity > 0 and record.item.category.get_tracking_type() == TrackingType.QUANTITY:
                return record
        return None

    def _make_allocation_issue(self, *, record: StockRecord, person: Person | None = None, target_location: Location | None = None, page_number: int) -> StockEntry:
        source_register = self._preferred_register(record.location_id, record.item)
        payload: dict[str, Any] = {
            "entry_type": "ISSUE",
            "from_location": record.location_id,
            "to_location": target_location.id if target_location else None,
            "issued_to": person.id if person else None,
            "purpose": f"{self.title_tag} operational allocation",
            "remarks": f"Seeded allocation from {record.location.name}.",
            "items": [
                {
                    "item": record.item_id,
                    "batch": record.batch_id,
                    "quantity": 1 if record.available_quantity > 0 else 0,
                    "instances": [],
                    "stock_register": source_register.id,
                    "page_number": page_number,
                    "ack_stock_register": None,
                    "ack_page_number": None,
                }
            ],
        }
        data = self._post("/api/inventory/stock-entries/", payload)
        entry = StockEntry.objects.get(pk=data["id"])
        self.created_allocation_entries.append(entry)
        return entry

    def _make_return_entry(self, entry: StockEntry, *, page_number: int) -> StockEntry | None:
        entry_item = entry.items.select_related("item", "batch").first()
        if not entry_item:
            return None

        ack_register = self._preferred_register(entry.from_location_id, entry_item.item)
        payload: dict[str, Any] = {
            "entry_type": "RECEIPT",
            "from_location": entry.to_location_id if entry.to_location_id and not getattr(entry.to_location, "is_store", False) else None,
            "to_location": entry.from_location_id,
            "issued_to": entry.issued_to_id,
            "purpose": f"{self.title_tag} allocation return",
            "remarks": f"Seeded return for {entry.entry_number}.",
            "items": [
                {
                    "item": entry_item.item_id,
                    "batch": entry_item.batch_id,
                    "quantity": 1,
                    "instances": [],
                    "stock_register": None,
                    "page_number": None,
                    "ack_stock_register": None,
                    "ack_page_number": None,
                }
            ],
        }
        created = self._post("/api/inventory/stock-entries/", payload)
        return_entry = StockEntry.objects.get(pk=created["id"])
        return_line = return_entry.items.get()
        self._post(
            f"/api/inventory/stock-entries/{return_entry.id}/acknowledge/",
            {
                "items": [
                    {
                        "id": return_line.id,
                        "quantity": return_line.quantity,
                        "instances": [],
                        "ack_stock_register": ack_register.id,
                        "ack_page_number": page_number,
                    }
                ]
            },
            expected=(200,),
        )
        return return_entry

    def create_manual_allocations_and_returns(self) -> None:
        record_ids = [record.id for record in self._eligible_allocation_records()]
        if not record_ids:
            return

        person_targets = [
            person
            for person in self.created_people
            if person.standalone_locations.exists()
        ]
        page_number = 200

        for index in range(self.config.manual_person_allocations):
            record = self._next_available_allocation_record(record_ids, index)
            if record is None:
                break
            standalone = record.location.parent_location
            person = next(
                (
                    target
                    for target in person_targets
                    if target.standalone_locations.filter(id=standalone.id).exists()
                ),
                None,
            )
            if person is None:
                continue
            self._make_allocation_issue(record=record, person=person, target_location=None, page_number=page_number)
            page_number += 1

        for index in range(self.config.manual_location_allocations):
            record = self._next_available_allocation_record(record_ids, index + self.config.manual_person_allocations)
            if record is None:
                break
            standalone = record.location.parent_location
            locations = [loc for loc in self.created_department_children.get(standalone.id, []) if not loc.is_store]
            if not locations:
                continue
            target_location = locations[index % len(locations)]
            self._make_allocation_issue(record=record, person=None, target_location=target_location, page_number=page_number)
            page_number += 1

        for index, entry in enumerate(self.created_allocation_entries[: self.config.manual_returns], start=1):
            self._make_return_entry(entry, page_number=page_number + index)

    def close_and_reopen_registers(self) -> None:
        active_registers = [register for registers in self.registers_by_store.values() for register in registers if register.is_active]
        if not active_registers:
            return

        close_target = active_registers[0]
        self._post(
            f"/api/inventory/stock-registers/{close_target.id}/close/",
            {"reason": f"{self.title_tag} showcase ledger close-out."},
            expected=(200,),
        )
        close_target.refresh_from_db()

        reopen_target = active_registers[1] if len(active_registers) > 1 else close_target
        self._post(
            f"/api/inventory/stock-registers/{reopen_target.id}/close/",
            {"reason": f"{self.title_tag} temporary review closure."},
            expected=(200,),
        )
        self._post(
            f"/api/inventory/stock-registers/{reopen_target.id}/reopen/",
            {"reason": f"{self.title_tag} review completed."},
            expected=(200,),
        )

    def create_depreciation_runs(self) -> None:
        count = max(0, self.config.depreciation_run_count)
        if count == 0:
            return

        existing_max = DepreciationRun.objects.order_by("-fiscal_year_start").values_list("fiscal_year_start", flat=True).first()
        if existing_max is not None:
            start_year = existing_max + 1
        else:
            start_year = max(2001, timezone.localdate().year - count + 1)

        for index in range(count):
            fiscal_year_start = start_year + index
            run_data = self._post(
                "/api/inventory/depreciation/runs/",
                {
                    "fiscal_year_start": fiscal_year_start,
                    "notes": f"{self.title_tag} seeded depreciation run.",
                },
            )
            run_id = run_data["id"]
            if index % 5 == 0:
                self._post(f"/api/inventory/depreciation/runs/{run_id}/post/", {}, expected=(200,))
                self._post(f"/api/inventory/depreciation/runs/{run_id}/reverse/", {}, expected=(200,))
            elif index % 2 == 0:
                self._post(f"/api/inventory/depreciation/runs/{run_id}/post/", {}, expected=(200,))

    def create_asset_adjustments(self) -> None:
        if not self.created_asset_ids:
            return

        adjustment_types = [
            AssetAdjustmentType.ADDITION,
            AssetAdjustmentType.COST_CORRECTION,
            AssetAdjustmentType.ADDITION,
            AssetAdjustmentType.COST_CORRECTION,
            AssetAdjustmentType.ADDITION,
        ]
        asset_ids = list(self.created_asset_ids)
        for index in range(self.config.asset_adjustments):
            asset_id = asset_ids[index % len(asset_ids)]
            self._post(
                "/api/inventory/depreciation/adjustments/",
                {
                    "asset": asset_id,
                    "adjustment_type": adjustment_types[index % len(adjustment_types)],
                    "effective_date": timezone.localdate().isoformat(),
                    "amount": str(Decimal("2500.00") + Decimal(index * 750)),
                    "quantity_delta": 0,
                    "reason": f"{self.title_tag} seeded asset adjustment {index + 1}.",
                },
            )

    def build_summary(self) -> dict[str, Any]:
        after_counts = self._snapshot_counts()
        summary = {
            "tag": self.config.tag,
            "seeded_user_password": self.config.user_password,
            "standalone_units_created": len(self.created_standalones),
            "locations_created": after_counts["locations"] - self.before_counts["locations"],
            "categories_created": after_counts["categories"] - self.before_counts["categories"],
            "items_created": after_counts["items"] - self.before_counts["items"],
            "persons_created": after_counts["persons"] - self.before_counts["persons"],
            "stock_registers_created": after_counts["stock_registers"] - self.before_counts["stock_registers"],
            "roles_created": after_counts["roles"] - self.before_counts["roles"],
            "users_created": after_counts["users"] - self.before_counts["users"],
            "inspections_created": after_counts["inspections"] - self.before_counts["inspections"],
            "stock_entries_created": after_counts["stock_entries"] - self.before_counts["stock_entries"],
            "stock_allocations_created": after_counts["allocations"] - self.before_counts["allocations"],
            "item_batches_created": after_counts["item_batches"] - self.before_counts["item_batches"],
            "item_instances_created": after_counts["item_instances"] - self.before_counts["item_instances"],
            "fixed_assets_created": after_counts["fixed_assets"] - self.before_counts["fixed_assets"],
            "asset_classes_created": after_counts["asset_classes"] - self.before_counts["asset_classes"],
            "depreciation_runs_created": after_counts["depreciation_runs"] - self.before_counts["depreciation_runs"],
            "asset_adjustments_created": after_counts["asset_adjustments"] - self.before_counts["asset_adjustments"],
            "notification_events_created": after_counts["notification_events"] - self.before_counts["notification_events"],
            "user_notifications_created": after_counts["user_notifications"] - self.before_counts["user_notifications"],
        }
        return summary


def populate_demo_data(user: User, config: PopulateConfig | None = None) -> dict[str, Any]:
    rest_framework_settings = dict(settings.REST_FRAMEWORK)
    rest_framework_settings["DEFAULT_THROTTLE_CLASSES"] = []
    rest_framework_settings["DEFAULT_THROTTLE_RATES"] = {}
    middleware = [
        entry
        for entry in settings.MIDDLEWARE
        if entry != "silk.middleware.SilkyMiddleware"
    ]
    original_throttle_classes = APIView.throttle_classes

    with override_settings(REST_FRAMEWORK=rest_framework_settings, MIDDLEWARE=middleware):
        APIView.throttle_classes = []
        try:
            return DemoDataPopulator(user, config or PopulateConfig()).populate()
        finally:
            APIView.throttle_classes = original_throttle_classes
