#!/usr/bin/env python
"""
AMS sample data population script for the current backend schema.

Run from backend/ with:
    python populate_data.py

This script is safe to re-run on a mostly empty/dev database. It uses the
current ORM so signals still fire for hierarchy stores, QR images, and stock
entry receipt bridges.
"""

import os
from datetime import timedelta
from decimal import Decimal

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ams.settings")
django.setup()

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from inventory.models import (
    Category,
    CategoryType,
    InspectionCertificate,
    InspectionItem,
    Item,
    ItemBatch,
    ItemInstance,
    Location,
    LocationType,
    Person,
    StockEntry,
    StockEntryItem,
    StockRecord,
    StockRegister,
    TrackingType,
)


def ensure_user(username, password, first_name="", last_name=""):
    user, created = User.objects.get_or_create(
        username=username,
        defaults={"first_name": first_name, "last_name": last_name},
    )
    if created or not user.check_password(password):
        user.set_password(password)
    if first_name:
        user.first_name = first_name
    if last_name:
        user.last_name = last_name
    user.is_active = True
    user.save()
    return user


def ensure_group_membership(user, group_name):
    group = Group.objects.get(name=group_name)
    user.groups.add(group)
    return group


def assign_locations(user, *locations):
    profile = user.profile
    profile.assigned_locations.set([loc for loc in locations if loc])
    return profile


def ensure_location(name, location_type, *, parent=None, is_standalone=False, description="", in_charge="", contact=""):
    location, created = Location.objects.get_or_create(
        name=name,
        defaults={
            "location_type": location_type,
            "parent_location": parent,
            "is_standalone": is_standalone,
            "description": description,
            "in_charge": in_charge,
            "contact_number": contact,
            "is_active": True,
        },
    )
    if not created:
        changed = False
        if location.parent_location_id != (parent.id if parent else None):
            location.parent_location = parent
            changed = True
        if location.location_type != location_type:
            location.location_type = location_type
            changed = True
        if location.is_standalone != is_standalone:
            location.is_standalone = is_standalone
            changed = True
        if description and location.description != description:
            location.description = description
            changed = True
        if in_charge and location.in_charge != in_charge:
            location.in_charge = in_charge
            changed = True
        if contact and location.contact_number != contact:
            location.contact_number = contact
            changed = True
        if changed:
            location.save()
    location.refresh_from_db()
    return location


def ensure_category(name, *, parent=None, category_type=None, tracking_type=None, rate=None):
    category, created = Category.objects.get_or_create(
        name=name,
        parent_category=parent,
        defaults={
            "category_type": category_type,
            "tracking_type": tracking_type,
            "default_depreciation_rate": rate,
            "is_active": True,
        },
    )
    if not created:
        changed = False
        if category.category_type != category_type:
            category.category_type = category_type
            changed = True
        if category.tracking_type != tracking_type:
            category.tracking_type = tracking_type
            changed = True
        if category.default_depreciation_rate != rate:
            category.default_depreciation_rate = rate
            changed = True
        if changed:
            category.save()
    return category


def ensure_item(name, category, *, acct_unit="Unit", description="", specifications="", threshold=0, created_by=None):
    item, created = Item.objects.get_or_create(
        name=name,
        category=category,
        defaults={
            "acct_unit": acct_unit,
            "description": description,
            "specifications": specifications,
            "low_stock_threshold": threshold,
            "created_by": created_by,
            "is_active": True,
        },
    )
    if not created:
        changed = False
        updates = {
            "acct_unit": acct_unit,
            "description": description,
            "specifications": specifications,
            "low_stock_threshold": threshold,
        }
        for field, value in updates.items():
            if getattr(item, field) != value:
                setattr(item, field, value)
                changed = True
        if created_by and item.created_by_id != created_by.id:
            item.created_by = created_by
            changed = True
        if changed:
            item.save()
    return item


def ensure_register(number, register_type, store, created_by=None):
    register, created = StockRegister.objects.get_or_create(
        register_number=number,
        store=store,
        defaults={"register_type": register_type, "created_by": created_by, "is_active": True},
    )
    if not created and register.register_type != register_type:
        register.register_type = register_type
        register.save(update_fields=["register_type"])
    return register


def ensure_person(name, designation, department, *locations):
    person, _ = Person.objects.get_or_create(
        name=name,
        defaults={"designation": designation, "department": department, "is_active": True},
    )
    person.designation = designation
    person.department = department
    person.is_active = True
    person.save()
    if locations:
        person.standalone_locations.set(locations)
    return person


def ensure_batch(item, batch_number, *, manufactured_date=None, expiry_date=None, created_by=None):
    batch, created = ItemBatch.objects.get_or_create(
        item=item,
        batch_number=batch_number,
        defaults={
            "manufactured_date": manufactured_date,
            "expiry_date": expiry_date,
            "created_by": created_by,
            "is_active": True,
        },
    )
    if not created:
        changed = False
        if batch.manufactured_date != manufactured_date:
            batch.manufactured_date = manufactured_date
            changed = True
        if batch.expiry_date != expiry_date:
            batch.expiry_date = expiry_date
            changed = True
        if created_by and batch.created_by_id != created_by.id:
            batch.created_by = created_by
            changed = True
        if changed:
            batch.save()
    return batch


def ensure_instance(item, serial_number, *, location, batch=None, status="AVAILABLE", created_by=None, inspection=None):
    instance, created = ItemInstance.objects.get_or_create(
        serial_number=serial_number,
        defaults={
            "item": item,
            "batch": batch,
            "current_location": location,
            "status": status,
            "created_by": created_by,
            "inspection_certificate": inspection,
            "is_active": True,
        },
    )
    if not created:
        changed = False
        updates = {
            "item": item,
            "batch": batch,
            "current_location": location,
            "status": status,
            "inspection_certificate": inspection,
            "is_active": True,
        }
        for field, value in updates.items():
            current = getattr(instance, field)
            current_id = getattr(current, "id", current)
            value_id = getattr(value, "id", value)
            if current_id != value_id:
                setattr(instance, field, value)
                changed = True
        if created_by and instance.created_by_id != created_by.id:
            instance.created_by = created_by
            changed = True
        if changed:
            instance.save()
    return instance


def ensure_stock(item, location, quantity, *, batch=None, in_transit=0, allocated=0):
    record, _ = StockRecord.objects.get_or_create(
        item=item,
        location=location,
        batch=batch,
        defaults={"quantity": quantity, "in_transit_quantity": in_transit, "allocated_quantity": allocated},
    )
    updates = {
        "quantity": quantity,
        "in_transit_quantity": in_transit,
        "allocated_quantity": allocated,
    }
    changed = False
    for field, value in updates.items():
        if getattr(record, field) != value:
            setattr(record, field, value)
            changed = True
    if changed:
        record.save()
    return record


def ensure_inspection(
    contract_no,
    department,
    initiated_by,
    stock_filled_by,
    central_store_filled_by,
    finance_reviewed_by,
    items,
):
    today = timezone.now().date()
    inspection, created = InspectionCertificate.objects.get_or_create(
        contract_no=contract_no,
        defaults={
            "date": today - timedelta(days=15),
            "contract_date": today - timedelta(days=20),
            "contractor_name": "TechSource Pakistan",
            "contractor_address": "Main Shahrah-e-Faisal, Karachi",
            "indenter": "Procurement Cell",
            "indent_no": "IND-AMS-2026-001",
            "department": department,
            "date_of_delivery": today - timedelta(days=12),
            "delivery_type": "FULL",
            "remarks": "Sample seeded certificate for stock intake and dashboard workflows.",
            "inspected_by": "Inspection Committee A",
            "date_of_inspection": today - timedelta(days=10),
            "consignee_name": "Mr. Moin",
            "consignee_designation": "Stock In-charge",
            "stage": "COMPLETED",
            "status": "COMPLETED",
            "initiated_by": initiated_by,
            "stock_filled_by": stock_filled_by,
            "stock_filled_at": timezone.now() - timedelta(days=11),
            "central_store_filled_by": central_store_filled_by,
            "central_store_filled_at": timezone.now() - timedelta(days=9),
            "finance_reviewed_by": finance_reviewed_by,
            "finance_reviewed_at": timezone.now() - timedelta(days=8),
            "finance_check_date": today - timedelta(days=8),
        },
    )
    if created:
        for payload in items:
            InspectionItem.objects.create(inspection_certificate=inspection, **payload)
    return inspection


def create_completed_transfer(
    *,
    item,
    batch,
    instances,
    quantity,
    from_location,
    to_location,
    created_by,
    source_register,
    source_page,
    ack_register,
    ack_page,
    purpose,
    remarks,
    inspection_certificate=None,
):
    existing = StockEntry.objects.filter(
        entry_type="ISSUE",
        from_location=from_location,
        to_location=to_location,
        purpose=purpose,
    ).order_by("id").first()
    if existing:
        return existing

    issue = StockEntry.objects.create(
        entry_type="ISSUE",
        from_location=from_location,
        to_location=to_location,
        status="PENDING_ACK",
        created_by=created_by,
        purpose=purpose,
        remarks=remarks,
        inspection_certificate=inspection_certificate,
        entry_date=timezone.now() - timedelta(days=7),
    )
    issue_item = StockEntryItem.objects.create(
        stock_entry=issue,
        item=item,
        batch=batch,
        quantity=quantity,
        stock_register=source_register,
        page_number=source_page,
    )
    if instances:
        issue_item.instances.set(instances)

    receipt = StockEntry.objects.get(reference_entry=issue, entry_type="RECEIPT")
    receipt_item = receipt.items.get(item=item, batch=batch)
    receipt_item.ack_stock_register = ack_register
    receipt_item.ack_page_number = ack_page
    receipt_item.accepted_quantity = quantity
    receipt_item.save()
    if instances:
        receipt_item.accepted_instances.set(instances)
    receipt.acknowledged_by = created_by
    receipt.acknowledged_at = timezone.now() - timedelta(days=6)
    receipt.status = "COMPLETED"
    receipt.save()
    return issue


def create_pending_allocation(
    *,
    item,
    instances,
    quantity,
    from_location,
    issued_to,
    created_by,
    source_register,
    source_page,
    purpose,
    remarks,
):
    existing = StockEntry.objects.filter(
        entry_type="ISSUE",
        from_location=from_location,
        issued_to=issued_to,
        status="PENDING_ACK",
        purpose=purpose,
    ).order_by("id").first()
    if existing:
        return existing

    entry = StockEntry.objects.create(
        entry_type="ISSUE",
        from_location=from_location,
        issued_to=issued_to,
        status="PENDING_ACK",
        created_by=created_by,
        purpose=purpose,
        remarks=remarks,
        entry_date=timezone.now() - timedelta(days=2),
    )
    entry_item = StockEntryItem.objects.create(
        stock_entry=entry,
        item=item,
        quantity=quantity,
        stock_register=source_register,
        page_number=source_page,
    )
    if instances:
        entry_item.instances.set(instances)
    return entry


def main():
    print("=" * 72)
    print("AMS Sample Data Population")
    print("=" * 72)

    with transaction.atomic():
        print("\n[1/9] Initializing roles and root hierarchy...")
        call_command("initialize_roles")
        call_command("initialize_hierarchy")

        root = Location.objects.order_by("id").first()
        if not root:
            raise RuntimeError("Root location was not created.")
        root.refresh_from_db()
        central_store = root.auto_created_store
        if not central_store:
            raise RuntimeError("Central Store is missing after hierarchy initialization.")
        print(f"  Root: {root.name} ({root.code})")
        print(f"  Central Store: {central_store.name} ({central_store.code})")

        print("\n[2/9] Creating organizational locations...")
        csit = ensure_location(
            "CSIT",
            LocationType.DEPARTMENT,
            parent=root,
            is_standalone=True,
            description="Computer Science and Information Technology Department",
            in_charge="Dr. Mubashir",
            contact="021-111-111",
        )
        ee = ensure_location(
            "Electrical Engineering",
            LocationType.DEPARTMENT,
            parent=root,
            is_standalone=True,
            description="Electrical Engineering Department",
            in_charge="Dr. Noman",
            contact="021-222-222",
        )
        csit_store = csit.auto_created_store
        ee_store = ee.auto_created_store
        ai_lab = ensure_location("AI Lab", LocationType.LAB, parent=csit, description="AI research lab")
        room_101 = ensure_location("CSIT Room 101", LocationType.ROOM, parent=csit, description="Teaching room")
        store_annex = ensure_location("CSIT Store Annex", LocationType.STORE, parent=csit_store, description="Internal CSIT store", in_charge="Mr. Moin")
        ee_lab = ensure_location("Power Lab", LocationType.LAB, parent=ee, description="Power systems lab")
        print(f"  Locations in system: {Location.objects.count()}")

        print("\n[3/9] Creating users and assigning scopes...")
        admin = User.objects.get(username="admin")
        ensure_group_membership(admin, "System Admin")
        assign_locations(admin, root, central_store)

        csit_head = ensure_user("csithead", "head1234", first_name="Dr. Mubashir")
        ensure_group_membership(csit_head, "Location Head")
        assign_locations(csit_head, csit)

        central_mgr = ensure_user("mainstock", "stock1234", first_name="Mr. Asad")
        ensure_group_membership(central_mgr, "Central Store Manager")
        assign_locations(central_mgr, root, central_store)

        csit_stock = ensure_user("csitstock", "stock1234", first_name="Mr. Moin")
        ensure_group_membership(csit_stock, "Stock In-charge")
        assign_locations(csit_stock, csit, csit_store, store_annex)

        finance = ensure_user("finance", "finance123", first_name="AD", last_name="Finance")
        ensure_group_membership(finance, "AD Finance")

        auditor = ensure_user("auditor", "audit1234", first_name="Internal", last_name="Audit")
        ensure_group_membership(auditor, "Auditor")
        print(f"  Users in system: {User.objects.count()}")

        print("\n[4/9] Creating reference people...")
        dr_umar = ensure_person("Dr. Umar Farooq", "Assistant Professor", "CSIT", csit)
        ensure_person("Mr. Rohail Qamar", "Lecturer", "CSIT", csit)
        ensure_person("Engr. Hina Ahmed", "Lab Engineer", "Electrical Engineering", ee)
        ensure_person("Mr. Waqar", "Central Store Staff", "Main University", root)
        print(f"  Persons in system: {Person.objects.count()}")

        print("\n[5/9] Creating categories and items...")
        it_parent = ensure_category("IT Equipment", category_type=CategoryType.FIXED_ASSET, rate=Decimal("25.00"))
        furniture_parent = ensure_category("Furniture", category_type=CategoryType.FIXED_ASSET, rate=Decimal("15.00"))
        consumables_parent = ensure_category("Consumables", category_type=CategoryType.CONSUMABLE)

        processor_cat = ensure_category("Processor", parent=it_parent, category_type=CategoryType.FIXED_ASSET, tracking_type=TrackingType.INDIVIDUAL)
        laptop_cat = ensure_category("Laptop", parent=it_parent, category_type=CategoryType.FIXED_ASSET, tracking_type=TrackingType.INDIVIDUAL)
        chair_cat = ensure_category("Chair", parent=furniture_parent, category_type=CategoryType.FIXED_ASSET, tracking_type=TrackingType.QUANTITY)
        cable_cat = ensure_category("Network Cable", parent=consumables_parent, category_type=CategoryType.CONSUMABLE, tracking_type=TrackingType.QUANTITY)

        cpu_item = ensure_item("Core i5 Workstation", processor_cat, description="Standard desktop CPU", specifications="12th Gen / 16GB / 512GB SSD", threshold=2, created_by=admin)
        laptop_item = ensure_item("Dell Latitude 5440", laptop_cat, description="Faculty laptop", specifications="Core i7 / 16GB / 512GB SSD", threshold=1, created_by=admin)
        chair_item = ensure_item("Ergonomic Office Chair", chair_cat, acct_unit="Piece", description="Mesh ergonomic chair", threshold=10, created_by=admin)
        cable_item = ensure_item("Cat6 Cable Box", cable_cat, acct_unit="Box", description="305m CAT6 network cable box", threshold=4, created_by=admin)
        print(f"  Items in system: {Item.objects.count()}")

        print("\n[6/9] Creating stock registers, batches and base stock...")
        central_dsr = ensure_register("CENTRAL-DSR-2026", "DSR", central_store, created_by=central_mgr)
        central_csr = ensure_register("CENTRAL-CSR-2026", "CSR", central_store, created_by=central_mgr)
        csit_dsr = ensure_register("CSIT-DSR-2026", "DSR", csit_store, created_by=csit_stock)
        csit_csr = ensure_register("CSIT-CSR-2026", "CSR", csit_store, created_by=csit_stock)
        annex_csr = ensure_register("CSIT-ANNEX-CSR-2026", "CSR", store_annex, created_by=csit_stock)

        chair_batch = ensure_batch(chair_item, "CH-2026-01", manufactured_date=timezone.now().date() - timedelta(days=40), created_by=central_mgr)
        cable_batch = ensure_batch(cable_item, "CB-2026-01", manufactured_date=timezone.now().date() - timedelta(days=30), expiry_date=timezone.now().date() + timedelta(days=365), created_by=central_mgr)

        ensure_stock(cpu_item, central_store, 3)
        ensure_stock(laptop_item, central_store, 2)
        ensure_stock(chair_item, central_store, 24, batch=chair_batch)
        ensure_stock(cable_item, central_store, 12, batch=cable_batch)
        ensure_stock(chair_item, csit_store, 6, batch=chair_batch)
        ensure_stock(cable_item, csit_store, 4, batch=cable_batch)

        print(f"  Stock registers in system: {StockRegister.objects.count()}")
        print(f"  Stock records in system: {StockRecord.objects.count()}")

        print("\n[7/9] Creating inspection data and tracked instances...")
        inspection = ensure_inspection(
            "C-AMS-2026-001",
            csit,
            initiated_by=csit_head,
            stock_filled_by=csit_stock,
            central_store_filled_by=central_mgr,
            finance_reviewed_by=finance,
            items=[
                {
                    "item": cpu_item,
                    "item_description": "Core i5 Workstation",
                    "item_specifications": "12th Gen / 16GB / 512GB SSD",
                    "tendered_quantity": 2,
                    "accepted_quantity": 2,
                    "rejected_quantity": 0,
                    "unit_price": Decimal("185000.00"),
                    "remarks": "Accepted for CSIT lab use.",
                    "stock_register": csit_dsr,
                    "stock_register_no": csit_dsr.register_number,
                    "stock_register_page_no": "15",
                    "stock_entry_date": timezone.now().date() - timedelta(days=11),
                    "central_register": central_dsr,
                    "central_register_no": central_dsr.register_number,
                    "central_register_page_no": "44",
                },
                {
                    "item": cable_item,
                    "item_description": "Cat6 Cable Box",
                    "item_specifications": "305m sealed box",
                    "tendered_quantity": 4,
                    "accepted_quantity": 4,
                    "rejected_quantity": 0,
                    "unit_price": Decimal("22000.00"),
                    "remarks": "For networking lab expansion.",
                    "stock_register": csit_csr,
                    "stock_register_no": csit_csr.register_number,
                    "stock_register_page_no": "8",
                    "stock_entry_date": timezone.now().date() - timedelta(days=11),
                    "central_register": central_csr,
                    "central_register_no": central_csr.register_number,
                    "central_register_page_no": "19",
                    "batch_number": cable_batch.batch_number,
                    "expiry_date": cable_batch.expiry_date,
                },
            ],
        )

        cpu_1 = ensure_instance(cpu_item, "CPU-CSIT-001", location=csit_store, created_by=central_mgr, inspection=inspection)
        cpu_2 = ensure_instance(cpu_item, "CPU-CSIT-002", location=ai_lab, created_by=central_mgr, inspection=inspection)
        laptop_1 = ensure_instance(laptop_item, "LAP-CSIT-001", location=central_store, created_by=central_mgr)
        laptop_2 = ensure_instance(laptop_item, "LAP-CSIT-002", location=central_store, created_by=central_mgr)
        print(f"  Item instances in system: {ItemInstance.objects.count()}")

        print("\n[8/9] Creating live stock movements...")
        create_completed_transfer(
            item=laptop_item,
            batch=None,
            instances=[laptop_1],
            quantity=1,
            from_location=central_store,
            to_location=csit_store,
            created_by=central_mgr,
            source_register=central_dsr,
            source_page=21,
            ack_register=csit_dsr,
            ack_page=12,
            purpose="Faculty deployment",
            remarks="Completed transfer from Central Store to CSIT main store.",
            inspection_certificate=inspection,
        )
        create_pending_allocation(
            item=cpu_item,
            instances=[cpu_2],
            quantity=1,
            from_location=csit_store,
            issued_to=dr_umar,
            created_by=csit_stock,
            source_register=csit_dsr,
            source_page=18,
            purpose="Faculty assignment",
            remarks="Pending handover to faculty member.",
        )

        print("\n[9/9] Summary")
        print("-" * 48)
        print(f"  Locations:        {Location.objects.count()}")
        print(f"  Users:            {User.objects.count()}")
        print(f"  Groups:           {Group.objects.count()}")
        print(f"  Categories:       {Category.objects.count()}")
        print(f"  Items:            {Item.objects.count()}")
        print(f"  Registers:        {StockRegister.objects.count()}")
        print(f"  Persons:          {Person.objects.count()}")
        print(f"  Batches:          {ItemBatch.objects.count()}")
        print(f"  Instances:        {ItemInstance.objects.count()}")
        print(f"  Stock Records:    {StockRecord.objects.count()}")
        print(f"  Inspections:      {InspectionCertificate.objects.count()}")
        print(f"  Stock Entries:    {StockEntry.objects.count()}")
        print("-" * 48)
        print("  Demo users:")
        print("    admin / admin")
        print("    mainstock / stock1234")
        print("    csitstock / stock1234")
        print("    csithead / head1234")
        print("    finance / finance123")
        print("    auditor / audit1234")

    print("\nSample data population completed.")


if __name__ == "__main__":
    main()
