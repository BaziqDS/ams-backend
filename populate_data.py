#!/usr/bin/env python
"""
AMS Initial Data Population Script

This script populates the database with seed data using Django's ORM
so that signals fire correctly (auto-store creation, UserProfile creation, etc.).

Run from backend/ directory with: python populate_data.py
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ams.settings')
django.setup()

from django.contrib.auth.models import User, Group
from django.core.management import call_command

from inventory.models import Location, LocationType, Category, CategoryType, TrackingType, Item
from inventory.models import StockRegister, Person
from user_management.models import UserProfile


def main():
    print("=" * 60)
    print("AMS Data Population Script")
    print("=" * 60)
    
    # Step 1: Initialize Roles
    print("\n[1/8] Initializing roles...")
    call_command('initialize_roles')
    print("Roles initialized.")
    
    # Step 2: Create Locations
    print("\n[2/8] Creating locations...")
    
    # NED University (Root standalone - auto-creates "Central Store")
    ned_university = Location.objects.create(
        name="NED University",
        location_type=LocationType.BUILDING,
        is_standalone=True,
        description="NED University of Engineering & Technology"
    )
    ned_university.refresh_from_db()  # Get auto_created_store reference
    central_store = ned_university.auto_created_store
    print(f"  Created: {ned_university.name} (code: {ned_university.code})")
    print(f"  Auto-created store: {central_store.name} (code: {central_store.code})")
    
    # CSIT Department (Child standalone - auto-creates "CSIT - Main Store")
    csit = Location.objects.create(
        name="CSIT",
        location_type=LocationType.DEPARTMENT,
        parent_location=ned_university,
        is_standalone=True,
        description="Computer Science & Information Technology Department"
    )
    csit.refresh_from_db()  # Get auto_created_store reference
    csit_main_store = csit.auto_created_store
    print(f"  Created: {csit.name} (code: {csit.code})")
    print(f"  Auto-created store: {csit_main_store.name} (code: {csit_main_store.code})")
    
    # Rooms under CSIT
    rooms_data = ["Room 1", "Room 2", "Room 3"]
    for room_name in rooms_data:
        room = Location.objects.create(
            name=room_name,
            location_type=LocationType.ROOM,
            parent_location=csit,
            is_standalone=False
        )
        print(f"  Created: {room.name} (code: {room.code})")
    
    print(f"  Total locations created: {Location.objects.count()}")
    
    # Step 3: Create Users
    print("\n[3/8] Creating users...")
    
    # Get groups
    location_head_group = Group.objects.get(name="Location Head")
    central_store_manager_group = Group.objects.get(name="Central Store Manager")
    stock_incharge_group = Group.objects.get(name="Stock In-charge")
    ad_finance_group = Group.objects.get(name="AD Finance")
    
    # Dr. Tufail - Location Head for NED University
    user_tufail = User.objects.create_user(
        username="mainhead",
        first_name="Dr. Tufail",
        last_name="",
        password="head1234"
    )
    user_tufail.groups.add(location_head_group)
    user_tufail.profile.assigned_locations.set([ned_university])
    print(f"  Created: {user_tufail.username} (Location Head - NED University)")
    
    # Dr. Mubashir - Location Head for CSIT
    user_mubashir = User.objects.create_user(
        username="csithead",
        first_name="Dr. Mubashir",
        last_name="",
        password="head1234"
    )
    user_mubashir.groups.add(location_head_group)
    user_mubashir.profile.assigned_locations.set([csit])
    print(f"  Created: {user_mubashir.username} (Location Head - CSIT)")
    
    # Mr. Asad - Central Store Manager
    user_asad = User.objects.create_user(
        username="mainstock",
        first_name="Mr. Asad",
        last_name="",
        password="stock1234"
    )
    user_asad.groups.add(central_store_manager_group)
    user_asad.profile.assigned_locations.set([ned_university, central_store])
    print(f"  Created: {user_asad.username} (Central Store Manager - NED University + Central Store)")
    
    # Mr. Moin - Stock In-charge for CSIT
    user_moin = User.objects.create_user(
        username="csitstock",
        first_name="Mr. Moin",
        last_name="",
        password="stock1234"
    )
    user_moin.groups.add(stock_incharge_group)
    user_moin.profile.assigned_locations.set([csit, csit_main_store])
    print(f"  Created: {user_moin.username} (Stock In-charge - CSIT + CSIT Main Store)")
    
    # Finance user (AD Finance)
    user_finance = User.objects.create_user(
        username="finance",
        first_name="",
        last_name="",
        password="finance123"
    )
    user_finance.groups.add(ad_finance_group)
    print(f"  Created: {user_finance.username} (AD Finance - no location)")
    
    print(f"  Total users created: {User.objects.count()}")
    
    # Step 4: Create Categories
    print("\n[4/8] Creating categories...")
    
    # Parent: IT Equipments
    it_equipments = Category.objects.create(
        name="IT Equipments",
        category_type=CategoryType.FIXED_ASSET,
        default_depreciation_rate=25.00
    )
    print(f"  Created parent: {it_equipments.name} (type: {it_equipments.category_type}, depreciation: {it_equipments.default_depreciation_rate}%)")
    
    # Parent: Furniture
    furniture = Category.objects.create(
        name="Furniture",
        category_type=CategoryType.FIXED_ASSET,
        default_depreciation_rate=20.00
    )
    print(f"  Created parent: {furniture.name} (type: {furniture.category_type}, depreciation: {furniture.default_depreciation_rate}%)")
    
    # Subcategories for IT Equipments
    it_subcategories = [
        {"name": "Processor", "tracking_type": TrackingType.INDIVIDUAL},
        {"name": "Keyboard", "tracking_type": TrackingType.INDIVIDUAL},
        {"name": "Monitor", "tracking_type": TrackingType.INDIVIDUAL},
    ]
    for sub_data in it_subcategories:
        sub = Category.objects.create(
            name=sub_data["name"],
            parent_category=it_equipments,
            category_type=CategoryType.FIXED_ASSET,
            tracking_type=sub_data["tracking_type"]
        )
        print(f"    Created subcategory: {sub.name} (tracking: {sub.tracking_type})")
    
    # Subcategories for Furniture
    furniture_subcategories = [
        {"name": "Chair", "tracking_type": TrackingType.BATCH},
        {"name": "Table", "tracking_type": TrackingType.BATCH},
    ]
    for sub_data in furniture_subcategories:
        sub = Category.objects.create(
            name=sub_data["name"],
            parent_category=furniture,
            category_type=CategoryType.CONSUMABLE,  # Note: Furniture is CONSUMABLE in this subcategory
            tracking_type=sub_data["tracking_type"]
        )
        print(f"    Created subcategory: {sub.name} (tracking: {sub.tracking_type}, type: {sub.category_type})")
    
    print(f"  Total categories created: {Category.objects.count()}")
    
    # Step 5: Create Items
    print("\n[5/8] Creating items...")
    
    # Get subcategories
    processor_cat = Category.objects.get(name="Processor")
    keyboard_cat = Category.objects.get(name="Keyboard")
    
    # Create items
    item1 = Item.objects.create(
        name="Core i5 Processor",
        category=processor_cat,
        acct_unit="Unit"
    )
    print(f"  Created: {item1.name} (code: {item1.code}, category: {processor_cat.name})")
    
    item2 = Item.objects.create(
        name="Office Keyboard",
        category=keyboard_cat,
        acct_unit="Unit"
    )
    print(f"  Created: {item2.name} (code: {item2.code}, category: {keyboard_cat.name})")
    
    print(f"  Total items created: {Item.objects.count()}")
    
    # Step 6: Create Stock Registers
    print("\n[6/8] Creating stock registers...")
    
    # CSIT Main Store registers
    csit_csr = StockRegister.objects.create(
        register_number="CSR2025",
        register_type="CSR",
        store=csit_main_store
    )
    print(f"  Created: {csit_csr.register_number} (type: {csit_csr.register_type}, store: {csit_main_store.name})")
    
    csit_dsr = StockRegister.objects.create(
        register_number="DSR-2025",
        register_type="DSR",
        store=csit_main_store
    )
    print(f"  Created: {csit_dsr.register_number} (type: {csit_dsr.register_type}, store: {csit_main_store.name})")
    
    # Central Store registers
    central_csr = StockRegister.objects.create(
        register_number="bulk44CSR",
        register_type="CSR",
        store=central_store
    )
    print(f"  Created: {central_csr.register_number} (type: {central_csr.register_type}, store: {central_store.name})")
    
    central_dsr = StockRegister.objects.create(
        register_number="bulk40DSR",
        register_type="DSR",
        store=central_store
    )
    print(f"  Created: {central_dsr.register_number} (type: {central_dsr.register_type}, store: {central_store.name})")
    
    print(f"  Total stock registers created: {StockRegister.objects.count()}")
    
    # Step 7: Create Persons
    print("\n[7/8] Creating persons...")
    
    # CSIT Persons
    person1 = Person.objects.create(
        name="Dr. Umar Farooq",
        designation="Assistant Professor",
        department="CSIT"
    )
    person1.standalone_locations.add(csit)
    print(f"  Created: {person1.name} (designation: {person1.designation}, location: {csit.name})")
    
    person2 = Person.objects.create(
        name="Mr. Rohail Qamar",
        designation="Lecturer",
        department="CSIT"
    )
    person2.standalone_locations.add(csit)
    print(f"  Created: {person2.name} (designation: {person2.designation}, location: {csit.name})")
    
    person3 = Person.objects.create(
        name="Dr. Usman Amjad",
        designation="Assistant Professor",
        department="CSIT"
    )
    person3.standalone_locations.add(csit)
    print(f"  Created: {person3.name} (designation: {person3.designation}, location: {csit.name})")
    
    # NED University Persons
    person4 = Person.objects.create(
        name="Mr. Waqar",
        designation="Central Store Staff",
        department="NED University"
    )
    person4.standalone_locations.add(ned_university)
    print(f"  Created: {person4.name} (designation: {person4.designation}, location: {ned_university.name})")
    
    print(f"  Total persons created: {Person.objects.count()}")
    
    # Step 8: Summary
    print("\n[8/8] Verification Summary")
    print("-" * 40)
    print(f"  Locations:      {Location.objects.count()} (expected: 8)")
    print(f"  Users:          {User.objects.count()} (expected: 5)")
    print(f"  Groups:         {Group.objects.count()} (expected: 6)")
    print(f"  Categories:     {Category.objects.count()} (expected: 7)")
    print(f"  Items:          {Item.objects.count()} (expected: 2)")
    print(f"  Stock Registers: {StockRegister.objects.count()} (expected: 4)")
    print(f"  Persons:        {Person.objects.count()} (expected: 4)")
    print("-" * 40)
    print(f"  Central Store auto-created: {central_store.name}")
    print(f"  CSIT Main Store auto-created: {csit_main_store.name}")
    print("=" * 60)
    print("Data population completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
