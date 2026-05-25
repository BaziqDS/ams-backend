#!/usr/bin/env python
"""
Provision production roles and user accounts through the AMS backend API.

Run this on the deployed server from any folder that can reach the backend:

    python provision_production_roles.py --base-url http://127.0.0.1:8000

Required environment variables:
    AMS_ADMIN_USERNAME
    AMS_ADMIN_PASSWORD

Optional environment variables:
    AMS_DEFAULT_USER_PASSWORD  password assigned to newly created users
                               default: ChangeMe123!

The script intentionally uses HTTP POST/PATCH requests instead of writing to the
database directly, so the same serializers, permissions, and signals run as they
do from the application UI.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

try:
    import requests
except ImportError:
    print("Missing dependency: requests. Install it with: pip install requests", file=sys.stderr)
    raise


ROLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "Location Head": {
        "module_selections": {
            "users": "manage",
            "roles": "view",
            "locations": "manage",
            "categories": "view",
            "items": "view",
            "stock-entries": "view",
            "employees": "manage",
            "stock-registers": "view",
            "reports": None,
            "inspections": "manage",
            "depreciation": None,
            "maintenance": None,
        },
        "inspection_stages": ["initiate_inspection"],
    },
    "Stock In Charge": {
        "module_selections": {
            "users": "view",
            "roles": None,
            "locations": "view",
            "categories": "view",
            "items": "view",
            "stock-entries": "manage",
            "employees": "view",
            "stock-registers": "manage",
            "reports": None,
            "inspections": "manage",
            "depreciation": None,
            "maintenance": None,
        },
        "inspection_stages": ["fill_stock_details"],
    },
    "Central Store Manager": {
        "module_selections": {
            "users": "view",
            "roles": "view",
            "locations": "view",
            "categories": "manage",
            "items": "manage",
            "stock-entries": "manage",
            "employees": "manage",
            "stock-registers": "manage",
            "reports": None,
            "inspections": "manage",
            "depreciation": None,
            "maintenance": None,
        },
        "inspection_stages": ["fill_central_register"],
    },
    "Assistant Director of Finance": {
        "module_selections": {
            "users": "view",
            "roles": "view",
            "locations": "view",
            "categories": "view",
            "items": "view",
            "stock-entries": "manage",
            "employees": "view",
            "stock-registers": "view",
            "reports": None,
            "inspections": "manage",
            "depreciation": "full",
            "maintenance": "view",
        },
        "inspection_stages": ["review_finance"],
    },
}


USER_DEFINITIONS = [
    {
        "username": "assistant_director_finance",
        "email": "assistant_director_finance@example.com",
        "first_name": "Assistant Director",
        "last_name": "Finance",
        "role": "Assistant Director of Finance",
        "locations": ["NED University"],
    },
    {
        "username": "central_store_manager",
        "email": "central_store_manager@example.com",
        "first_name": "Central Store",
        "last_name": "Manager",
        "role": "Central Store Manager",
        "locations": ["NED University", "Central Store"],
    },
    {
        "username": "location_head_ned",
        "email": "location_head_ned@example.com",
        "first_name": "Location Head",
        "last_name": "NED",
        "role": "Location Head",
        "locations": ["NED University"],
    },
    {
        "username": "location_head_csit",
        "email": "location_head_csit@example.com",
        "first_name": "Location Head",
        "last_name": "CSIT",
        "role": "Location Head",
        "locations": ["CSIT"],
    },
    {
        "username": "stock_incharge_csit",
        "email": "stock_incharge_csit@example.com",
        "first_name": "Stock In Charge",
        "last_name": "CSIT",
        "role": "Stock In Charge",
        "locations": ["CSIT", "CSIT Main Store"],
    },
]


class ApiClient:
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def login(self, username: str, password: str) -> None:
        response = self.session.post(
            f"{self.base_url}/auth/jwt/create/",
            json={"username": username, "password": password},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Login failed ({response.status_code}): {response.text}")
        token = response.json().get("access")
        if not token:
            raise RuntimeError(f"Login response did not include an access token: {response.text}")
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            timeout=self.timeout,
            **kwargs,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"{method.upper()} {path} failed ({response.status_code}): {response.text}"
            )
        if response.status_code == 204:
            return None
        return response.json()

    def get_all(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        data = self.request("get", path, params=params)
        if isinstance(data, dict) and "results" in data:
            results = list(data["results"])
            next_url = data.get("next")
            while next_url:
                response = self.session.get(next_url, timeout=self.timeout)
                if response.status_code >= 400:
                    raise RuntimeError(f"GET {next_url} failed ({response.status_code}): {response.text}")
                data = response.json()
                results.extend(data["results"])
                next_url = data.get("next")
            return results
        if isinstance(data, list):
            return data
        raise RuntimeError(f"Expected list response from {path}, got: {data!r}")


def find_one_by_name(items: list[dict[str, Any]], name: str, label: str) -> dict[str, Any]:
    matches = [item for item in items if item.get("name", "").strip().lower() == name.lower()]
    if not matches:
        raise RuntimeError(f"Could not find {label} named {name!r}.")
    if len(matches) > 1:
        ids = ", ".join(str(item.get("id")) for item in matches)
        raise RuntimeError(f"Found multiple {label} records named {name!r}: IDs {ids}")
    return matches[0]


def upsert_role(client: ApiClient, existing_roles: list[dict[str, Any]], name: str, spec: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "name": name,
        "module_selections": spec["module_selections"],
        "inspection_stages": spec["inspection_stages"],
    }
    existing = next((role for role in existing_roles if role.get("name") == name), None)
    if existing:
        role = client.request("patch", f"/api/users/groups/{existing['id']}/", json=payload)
        print(f"Updated role: {name} (id={role['id']})")
        return role

    role = client.request("post", "/api/users/groups/", json=payload)
    print(f"Created role: {name} (id={role['id']})")
    existing_roles.append(role)
    return role


def upsert_user(
    client: ApiClient,
    existing_users: list[dict[str, Any]],
    user_spec: dict[str, Any],
    role_by_name: dict[str, dict[str, Any]],
    location_by_name: dict[str, dict[str, Any]],
    default_password: str,
) -> dict[str, Any]:
    role = role_by_name[user_spec["role"]]
    location_ids = [location_by_name[name]["id"] for name in user_spec["locations"]]
    payload = {
        "username": user_spec["username"],
        "email": user_spec["email"],
        "first_name": user_spec["first_name"],
        "last_name": user_spec["last_name"],
        "password": default_password,
        "is_superuser": False,
        "is_staff": False,
        "is_active": True,
        "groups": [role["id"]],
        "assigned_locations": location_ids,
    }

    existing = next((user for user in existing_users if user.get("username") == user_spec["username"]), None)
    if existing:
        payload.pop("password", None)
        user = client.request("patch", f"/api/users/management/{existing['id']}/", json=payload)
        print(f"Updated user: {user_spec['username']} (id={user['id']})")
        return user

    user = client.request("post", "/api/users/management/", json=payload)
    print(f"Created user: {user_spec['username']} (id={user['id']})")
    existing_users.append(user)
    return user


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision AMS production roles and users via API.")
    parser.add_argument("--base-url", default=os.getenv("AMS_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    admin_username = os.getenv("AMS_ADMIN_USERNAME")
    admin_password = os.getenv("AMS_ADMIN_PASSWORD")
    default_password = os.getenv("AMS_DEFAULT_USER_PASSWORD", "ChangeMe123!")

    if not admin_username or not admin_password:
        print("Set AMS_ADMIN_USERNAME and AMS_ADMIN_PASSWORD before running this script.", file=sys.stderr)
        return 2

    client = ApiClient(args.base_url, timeout=args.timeout)
    client.login(admin_username, admin_password)

    roles = client.get_all("/api/users/groups/")
    role_by_name = {
        name: upsert_role(client, roles, name, spec)
        for name, spec in ROLE_DEFINITIONS.items()
    }

    locations = client.get_all("/api/inventory/locations/")
    needed_location_names = sorted({name for user in USER_DEFINITIONS for name in user["locations"]})
    location_by_name = {
        name: find_one_by_name(locations, name, "location")
        for name in needed_location_names
    }

    users = client.get_all("/api/users/management/")
    for user_spec in USER_DEFINITIONS:
        upsert_user(client, users, user_spec, role_by_name, location_by_name, default_password)

    print("Provisioning complete.")
    print(f"Default password used for newly created users: {default_password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
