#!/usr/bin/env python
"""
Seed AMS data via HTTP API calls only (no ORM writes).

Creates:
- Locations (NED University + CSIT, including main stores via backend auto-create)
- Roles (Location Head, Central Stock In-Charge, Stock In-Charge, Finance)
- Users mapped to roles/locations
- Categories/Subcategories (IT Equipment, Furniture, Chemicals)
- Items (no stock entries, no inspection, no transfers)

Usage:
    cd backend
    python scripts/seed_api_data.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class SeedContext:
    base_url: str
    session: requests.Session
    headers: dict[str, str]


def urljoin(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def request_json(ctx: SeedContext, method: str, path: str, expected: tuple[int, ...], **kwargs: Any) -> Any:
    url = urljoin(ctx.base_url, path)
    hdrs = dict(ctx.headers)
    hdrs.update(kwargs.pop("headers", {}))
    resp = ctx.session.request(method=method, url=url, headers=hdrs, timeout=30, **kwargs)
    if resp.status_code not in expected:
        body = resp.text
        raise RuntimeError(f"{method} {path} failed: {resp.status_code}\n{body}")
    if not resp.text:
        return None
    try:
        return resp.json()
    except Exception:
        return resp.text


def list_all(ctx: SeedContext, path: str) -> list[dict[str, Any]]:
    data = request_json(ctx, "GET", path, (200,))
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    if isinstance(data, list):
        return data
    raise RuntimeError(f"Unexpected list response at {path}: {data}")


def login(base_url: str, username: str, password: str) -> SeedContext:
    session = requests.Session()
    token_resp = session.post(
        urljoin(base_url, "/auth/jwt/create/"),
        json={"username": username, "password": password},
        timeout=30,
    )
    if token_resp.status_code != 200:
        raise RuntimeError(f"Login failed: {token_resp.status_code}\n{token_resp.text}")
    data = token_resp.json()
    access = data.get("access")
    if not access:
        raise RuntimeError(f"Login response missing access token: {data}")
    return SeedContext(
        base_url=base_url,
        session=session,
        headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
    )


def ensure_role(ctx: SeedContext, payload: dict[str, Any]) -> dict[str, Any]:
    name = payload["name"]
    groups = list_all(ctx, "/api/users/groups/")
    existing = next((g for g in groups if g.get("name") == name), None)
    if existing:
        role_id = existing["id"]
        updated = request_json(ctx, "PATCH", f"/api/users/groups/{role_id}/", (200,), json=payload)
        print(f"[role] updated: {name}")
        return updated
    created = request_json(ctx, "POST", "/api/users/groups/", (201,), json=payload)
    print(f"[role] created: {name}")
    return created


def ensure_standalone_location(ctx: SeedContext, name: str, location_type: str, main_store_name: str | None = None) -> dict[str, Any]:
    locations = list_all(ctx, "/api/inventory/locations/")
    existing = next((l for l in locations if l.get("name") == name), None)
    if existing:
        print(f"[location] exists: {name}")
        return existing

    payload: dict[str, Any] = {
        "name": name,
        "location_type": location_type,
        "is_active": True,
        "description": f"Auto-seeded standalone location: {name}",
    }
    if main_store_name is not None:
        payload["main_store_name"] = main_store_name

    created = request_json(ctx, "POST", "/api/inventory/locations/standalone/", (201,), json=payload)
    print(f"[location] created standalone: {name}")
    return created


def refresh_locations_by_name(ctx: SeedContext) -> dict[str, dict[str, Any]]:
    locations = list_all(ctx, "/api/inventory/locations/")
    return {loc["name"]: loc for loc in locations}


def ensure_user(
    ctx: SeedContext,
    *,
    username: str,
    first_name: str,
    last_name: str,
    password: str,
    group_id: int,
    assigned_location_ids: list[int],
) -> dict[str, Any]:
    users = list_all(ctx, "/api/users/management/")
    existing = next((u for u in users if u.get("username") == username), None)
    payload = {
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "password": password,
        "is_staff": False,
        "is_superuser": False,
        "groups": [group_id],
        "assigned_locations": assigned_location_ids,
        "is_active": True,
    }

    if existing:
        user_id = existing["id"]
        payload.pop("password", None)
        updated = request_json(ctx, "PATCH", f"/api/users/management/{user_id}/", (200,), json=payload)
        print(f"[user] updated: {username}")
        return updated

    created = request_json(ctx, "POST", "/api/users/management/", (201,), json=payload)
    print(f"[user] created: {username}")
    return created


def ensure_category(
    ctx: SeedContext,
    *,
    name: str,
    parent_category: int | None,
    category_type: str | None,
    tracking_type: str | None,
    default_depreciation_rate: str | None,
) -> dict[str, Any]:
    categories = list_all(ctx, "/api/inventory/categories/")
    existing = next(
        (
            c
            for c in categories
            if c.get("name") == name and c.get("parent_category") == parent_category
        ),
        None,
    )

    payload: dict[str, Any] = {
        "name": name,
        "parent_category": parent_category,
        "is_active": True,
    }
    if category_type is not None:
        payload["category_type"] = category_type
    if tracking_type is not None:
        payload["tracking_type"] = tracking_type
    if default_depreciation_rate is not None:
        payload["default_depreciation_rate"] = default_depreciation_rate

    if existing:
        cat_id = existing["id"]
        updated = request_json(ctx, "PATCH", f"/api/inventory/categories/{cat_id}/", (200,), json=payload)
        print(f"[category] updated: {name}")
        return updated

    created = request_json(ctx, "POST", "/api/inventory/categories/", (201,), json=payload)
    print(f"[category] created: {name}")
    return created


def ensure_item(ctx: SeedContext, *, name: str, category_id: int, acct_unit: str, low_stock_threshold: int = 0) -> dict[str, Any]:
    items = list_all(ctx, "/api/inventory/items/")
    existing = next((i for i in items if i.get("name") == name), None)
    payload = {
        "name": name,
        "category": category_id,
        "acct_unit": acct_unit,
        "description": f"Auto-seeded item: {name}",
        "specifications": "",
        "low_stock_threshold": low_stock_threshold,
        "is_active": True,
    }

    if existing:
        item_id = existing["id"]
        updated = request_json(ctx, "PATCH", f"/api/inventory/items/{item_id}/", (200,), json=payload)
        print(f"[item] updated: {name}")
        return updated

    created = request_json(ctx, "POST", "/api/inventory/items/", (201,), json=payload)
    print(f"[item] created: {name}")
    return created


def build_role_payloads() -> list[dict[str, Any]]:
    return [
        {
            "name": "Location Head",
            "module_selections": {
                "users": "manage",
                "roles": "view",
                "locations": "view",
                "categories": "view",
                "items": "view",
                "stock-registers": "view",
                "stock-entries": "view",
                "inspections": "manage",
            },
            "inspection_stages": ["initiate_inspection"],
        },
        {
            "name": "Central Stock In-Charge",
            "module_selections": {
                "users": "manage",
                "roles": "view",
                "locations": "view",
                "categories": "manage",
                "items": "manage",
                "stock-registers": "manage",
                "stock-entries": "manage",
                "inspections": "manage",
            },
            "inspection_stages": ["fill_central_register"],
        },
        {
            "name": "Stock In-Charge",
            "module_selections": {
                "users": "manage",
                "roles": "view",
                "locations": "view",
                "categories": "manage",
                "items": "manage",
                "stock-registers": "manage",
                "stock-entries": "manage",
                "inspections": "manage",
            },
            "inspection_stages": ["fill_stock_details"],
        },
        {
            "name": "Finance",
            "module_selections": {
                "users": "view",
                "roles": "view",
                "locations": "view",
                "categories": "view",
                "items": "view",
                "stock-registers": "view",
                "stock-entries": "view",
                "inspections": "manage",
            },
            "inspection_stages": ["review_finance"],
        },
    ]


def run(args: argparse.Namespace) -> int:
    ctx = login(args.base_url, args.username, args.password)
    print("[auth] logged in")

    # 1) Locations
    ensure_standalone_location(ctx, "NED University", "DEPARTMENT", main_store_name="Central Store")
    ensure_standalone_location(ctx, "CSIT", "DEPARTMENT")

    locs = refresh_locations_by_name(ctx)
    required_locs = ["NED University", "CSIT", "Central Store", "CSIT - Main Store"]
    missing = [name for name in required_locs if name not in locs]
    if missing:
        raise RuntimeError(f"Missing required auto-created locations/stores: {missing}")

    # 2) Roles
    role_map: dict[str, dict[str, Any]] = {}
    for payload in build_role_payloads():
        role = ensure_role(ctx, payload)
        role_map[role["name"]] = role

    # 3) Users
    user_password = args.user_password
    ensure_user(
        ctx,
        username="ned_location_head",
        first_name="NED",
        last_name="LocationHead",
        password=user_password,
        group_id=role_map["Location Head"]["id"],
        assigned_location_ids=[locs["NED University"]["id"]],
    )
    ensure_user(
        ctx,
        username="csit_location_head",
        first_name="CSIT",
        last_name="LocationHead",
        password=user_password,
        group_id=role_map["Location Head"]["id"],
        assigned_location_ids=[locs["CSIT"]["id"]],
    )
    ensure_user(
        ctx,
        username="csit_stock_incharge",
        first_name="CSIT",
        last_name="StockIncharge",
        password=user_password,
        group_id=role_map["Stock In-Charge"]["id"],
        assigned_location_ids=[locs["CSIT"]["id"], locs["CSIT - Main Store"]["id"]],
    )
    ensure_user(
        ctx,
        username="central_stock_incharge",
        first_name="Central",
        last_name="StockIncharge",
        password=user_password,
        group_id=role_map["Central Stock In-Charge"]["id"],
        assigned_location_ids=[locs["NED University"]["id"], locs["Central Store"]["id"]],
    )
    ensure_user(
        ctx,
        username="finance_user",
        first_name="Finance",
        last_name="User",
        password=user_password,
        group_id=role_map["Finance"]["id"],
        assigned_location_ids=[locs["NED University"]["id"]],
    )

    # 4) Categories + subcategories
    it_equipment = ensure_category(
        ctx,
        name="IT Equipment",
        parent_category=None,
        category_type="FIXED_ASSET",
        tracking_type=None,
        default_depreciation_rate="10.00",
    )
    furniture = ensure_category(
        ctx,
        name="Furniture",
        parent_category=None,
        category_type="CONSUMABLE",
        tracking_type=None,
        default_depreciation_rate=None,
    )
    chemicals = ensure_category(
        ctx,
        name="Chemicals",
        parent_category=None,
        category_type="CONSUMABLE",
        tracking_type=None,
        default_depreciation_rate=None,
    )

    processors = ensure_category(
        ctx,
        name="Processors",
        parent_category=it_equipment["id"],
        category_type=None,
        tracking_type="INDIVIDUAL",
        default_depreciation_rate=None,
    )
    laptops = ensure_category(
        ctx,
        name="Laptops",
        parent_category=it_equipment["id"],
        category_type=None,
        tracking_type="INDIVIDUAL",
        default_depreciation_rate=None,
    )
    tables = ensure_category(
        ctx,
        name="Tables",
        parent_category=furniture["id"],
        category_type=None,
        tracking_type="QUANTITY",
        default_depreciation_rate=None,
    )
    chairs = ensure_category(
        ctx,
        name="Chairs",
        parent_category=furniture["id"],
        category_type=None,
        tracking_type="QUANTITY",
        default_depreciation_rate=None,
    )
    lab_chemicals = ensure_category(
        ctx,
        name="Lab Chemicals",
        parent_category=chemicals["id"],
        category_type=None,
        tracking_type="QUANTITY",
        default_depreciation_rate=None,
    )

    # 5) Items only (no stock)
    ensure_item(ctx, name="Laptops Auto", category_id=laptops["id"], acct_unit="Nos")
    ensure_item(ctx, name="Processors Auto", category_id=processors["id"], acct_unit="Nos")
    ensure_item(ctx, name="Tables Auto", category_id=tables["id"], acct_unit="Nos")
    ensure_item(ctx, name="Chairs Auto", category_id=chairs["id"], acct_unit="Nos")
    ensure_item(ctx, name="Hydrochloric Acid", category_id=lab_chemicals["id"], acct_unit="Litre")

    print("\nSeed complete. Created/updated locations, roles, users, categories, and items via API only.")
    print("No inspections, no stock entries, no allocations/transfers were created.")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed AMS via API calls")
    p.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL")
    p.add_argument("--username", default="admin", help="Admin username")
    p.add_argument("--password", default="admin", help="Admin password")
    p.add_argument("--user-password", default="admin123", help="Password for created non-admin users")
    return p.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
