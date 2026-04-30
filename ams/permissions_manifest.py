"""Single source of truth for admin-facing module permissions.

Admins see a 4-level radio group per module (None / View / Manage / Full).
Each level maps to a concrete set of Django permissions, declared here.

When a module-level form adds dependent dropdowns (e.g. a user create form
needs the role list and location list), declare those as `reads` and the
capability service will auto-grant the corresponding view_* permissions
alongside the main grant.

One module per migration PR. Add new modules here; don't change existing
entries without updating every role that uses them.
"""
from __future__ import annotations

from typing import TypedDict


class ModuleLevel(TypedDict):
    perms: list[str]
    reads: list[str]


ModuleSpec = dict[str, ModuleLevel]


INSPECTION_STAGE_PERMS: dict[str, str] = {
    "initiate_inspection": "inventory.initiate_inspection",
    "fill_stock_details": "inventory.fill_stock_details",
    "fill_central_register": "inventory.fill_central_register",
    "review_finance": "inventory.review_finance",
}

ALL_INSPECTION_STAGE_KEYS = list(INSPECTION_STAGE_PERMS.keys())

MODULES: dict[str, ModuleSpec] = {
    "users": {
        "view": {
            "perms": ["user_management.view_user_accounts"],
            "reads": [],
        },
        "manage": {
            "perms": [
                "user_management.view_user_accounts",
                "user_management.create_user_accounts",
                "user_management.edit_user_accounts",
                "user_management.assign_user_locations",
                "user_management.assign_user_roles",
            ],
            "reads": ["roles", "locations"],
        },
        "full": {
            "perms": [
                "user_management.view_user_accounts",
                "user_management.view_all_user_accounts",
                "user_management.create_user_accounts",
                "user_management.edit_user_accounts",
                "user_management.delete_user_accounts",
                "user_management.assign_user_locations",
                "user_management.assign_user_roles",
            ],
            "reads": ["roles", "locations"],
        },
    },
    "roles": {
        "view": {
            "perms": ["user_management.view_roles"],
            "reads": [],
        },
        "manage": {
            "perms": [
                "user_management.view_roles",
                "user_management.create_roles",
                "user_management.edit_roles",
                "user_management.assign_permissions_to_roles",
            ],
            "reads": [],
        },
        "full": {
            "perms": [
                "user_management.view_roles",
                "user_management.create_roles",
                "user_management.edit_roles",
                "user_management.delete_roles",
                "user_management.assign_permissions_to_roles",
            ],
            "reads": [],
        },
    },
    "locations": {
        "view": {
            "perms": ["inventory.view_locations"],
            "reads": [],
        },
        "manage": {
            "perms": [
                "inventory.view_locations",
                "inventory.create_locations",
                "inventory.edit_locations",
            ],
            "reads": [],
        },
        "full": {
            "perms": [
                "inventory.view_locations",
                "inventory.create_locations",
                "inventory.edit_locations",
                "inventory.delete_locations",
            ],
            "reads": [],
        },
    },
    "categories": {
        "view": {
            "perms": ["inventory.view_categories"],
            "reads": [],
        },
        "manage": {
            "perms": [
                "inventory.view_categories",
                "inventory.create_categories",
                "inventory.edit_categories",
            ],
            "reads": [],
        },
        "full": {
            "perms": [
                "inventory.view_categories",
                "inventory.create_categories",
                "inventory.edit_categories",
                "inventory.delete_categories",
            ],
            "reads": [],
        },
    },
    "items": {
        "view": {
            "perms": ["inventory.view_items"],
            "reads": [],
        },
        "manage": {
            "perms": [
                "inventory.view_items",
                "inventory.create_items",
                "inventory.edit_items",
            ],
            "reads": ["categories"],
        },
        "full": {
            "perms": [
                "inventory.view_items",
                "inventory.create_items",
                "inventory.edit_items",
                "inventory.delete_items",
            ],
            "reads": ["categories"],
        },
    },
    "stock-entries": {
        "view": {
            "perms": ["inventory.view_stock_entries"],
            "reads": [],
        },
        "manage": {
            "perms": [
                "inventory.view_stock_entries",
                "inventory.create_stock_entries",
                "inventory.edit_stock_entries",
                "inventory.acknowledge_stockentry",
            ],
            "reads": ["items", "locations", "persons", "stock-registers", "stock-allocations"],
        },
        "full": {
            "perms": [
                "inventory.view_stock_entries",
                "inventory.create_stock_entries",
                "inventory.edit_stock_entries",
                "inventory.delete_stock_entries",
                "inventory.acknowledge_stockentry",
                "inventory.approve_stock_corrections",
            ],
            "reads": ["items", "locations", "persons", "stock-registers", "stock-allocations"],
        },
    },
    "stock-registers": {
        "view": {
            "perms": ["inventory.view_stock_registers"],
            "reads": [],
        },
        "manage": {
            "perms": [
                "inventory.view_stock_registers",
                "inventory.create_stock_registers",
                "inventory.edit_stock_registers",
            ],
            "reads": ["locations"],
        },
        "full": {
            "perms": [
                "inventory.view_stock_registers",
                "inventory.create_stock_registers",
                "inventory.edit_stock_registers",
                "inventory.delete_stock_registers",
            ],
            "reads": ["locations"],
        },
    },
    "inspections": {
        "view": {
            "perms": ["inventory.view_inspectioncertificate"],
            "reads": [],
        },
        "manage": {
            "perms": [
                "inventory.view_inspectioncertificate",
                "inventory.add_inspectioncertificate",
                "inventory.change_inspectioncertificate",
            ],
            "reads": ["items", "locations", "stock-registers"],
        },
        "full": {
            "perms": [
                "inventory.view_inspectioncertificate",
                "inventory.add_inspectioncertificate",
                "inventory.change_inspectioncertificate",
                "inventory.delete_inspectioncertificate",
                "inventory.initiate_inspection",
                "inventory.fill_stock_details",
                "inventory.fill_central_register",
                "inventory.review_finance",
            ],
            "reads": ["items", "locations", "stock-registers"],
        },
    },
}


# What "read access" to a module means for the capability resolver.
# When module X declares `reads: ["roles", "locations"]`, the resolver adds the
# codenames listed under READ_PERMS["roles"] and READ_PERMS["locations"].
READ_PERMS: dict[str, list[str]] = {
    "users": ["user_management.view_user_accounts"],
    "roles": ["user_management.view_roles"],
    # Keep the raw model read for legacy row-scope checks and include the
    # domain module read so dependency grants round-trip as Locations: View.
    "locations": ["inventory.view_locations", "inventory.view_location"],
    "categories": ["inventory.view_categories"],
    "items": ["inventory.view_items"],
    "stock-entries": ["inventory.view_stock_entries"],
    "persons": ["inventory.view_person"],
    "stock-registers": ["inventory.view_stock_registers", "inventory.view_stockregister"],
    "stock-allocations": ["inventory.view_stockallocation"],
    "inspections": ["inventory.view_inspectioncertificate"],
}


LEVEL_ORDER: tuple[str, ...] = ("view", "manage", "full")
