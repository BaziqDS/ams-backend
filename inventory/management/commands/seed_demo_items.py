from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from inventory.models import (
    AllocationStatus,
    Category,
    Item,
    ItemBatch,
    ItemInstance,
    Location,
    Person,
    StockAllocation,
    StockRecord,
)


class Command(BaseCommand):
    help = "Seed coherent demo item data for the redesigned items module."

    def handle(self, *args, **options):
        created_by = User.objects.filter(is_superuser=True).order_by("id").first() or User.objects.order_by("id").first()

        root = self.location(
            name="NED University",
            code="NED",
            location_type="BUILDING",
            parent_location=None,
            is_standalone=True,
            created_by=created_by,
        )

        central_store = self.location(
            name="Central Store",
            code="CENTRAL-STORE",
            location_type="STORE",
            parent_location=root,
            is_store=True,
            is_main_store=True,
            created_by=created_by,
        )

        csit = self.location(
            name="CSIT",
            code="CSS",
            location_type="DEPARTMENT",
            parent_location=root,
            is_standalone=True,
            in_charge="Chairperson CSIT",
            created_by=created_by,
        )
        csit_store = self.location(
            name="CSIT - Main Store",
            code="CSS-MAIN-STORE",
            location_type="STORE",
            parent_location=csit,
            is_store=True,
            is_main_store=True,
            in_charge="CSIT Store Officer",
            created_by=created_by,
        )
        csit_lab_a = self.location(
            name="CSIT Programming Lab A",
            code="CSIT-LAB-A",
            location_type="LAB",
            parent_location=csit,
            in_charge="Lab Engineer CSIT",
            created_by=created_by,
        )
        csit_lab_b = self.location(
            name="CSIT Hardware Lab B",
            code="CSIT-LAB-B",
            location_type="LAB",
            parent_location=csit,
            in_charge="Hardware Lab Incharge",
            created_by=created_by,
        )
        csit_office = self.location(
            name="CSIT Faculty Office",
            code="CSIT-OFFICE",
            location_type="OFFICE",
            parent_location=csit,
            in_charge="Department Coordinator",
            created_by=created_by,
        )

        mechanical = self.location(
            name="Mechanical Engineering",
            code="MECH",
            location_type="DEPARTMENT",
            parent_location=root,
            is_standalone=True,
            in_charge="Chairperson Mechanical",
            created_by=created_by,
        )
        mech_store = self.location(
            name="Mechanical - Main Store",
            code="MECH-MAIN-STORE",
            location_type="STORE",
            parent_location=mechanical,
            is_store=True,
            is_main_store=True,
            in_charge="Mechanical Store Officer",
            created_by=created_by,
        )
        mech_lab = self.location(
            name="Mechanical CAD Lab",
            code="MECH-CAD-LAB",
            location_type="LAB",
            parent_location=mechanical,
            in_charge="CAD Lab Incharge",
            created_by=created_by,
        )
        mech_office = self.location(
            name="Mechanical Faculty Office",
            code="MECH-OFFICE",
            location_type="OFFICE",
            parent_location=mechanical,
            in_charge="Mechanical Coordinator",
            created_by=created_by,
        )

        electrical = self.location(
            name="Electrical Engineering",
            code="ELEC",
            location_type="DEPARTMENT",
            parent_location=root,
            is_standalone=True,
            in_charge="Chairperson Electrical",
            created_by=created_by,
        )
        elec_store = self.location(
            name="Electrical - Main Store",
            code="ELEC-MAIN-STORE",
            location_type="STORE",
            parent_location=electrical,
            is_store=True,
            is_main_store=True,
            in_charge="Electrical Store Officer",
            created_by=created_by,
        )
        elec_lab = self.location(
            name="Electrical Circuits Lab",
            code="ELEC-CIRCUITS-LAB",
            location_type="LAB",
            parent_location=electrical,
            in_charge="Circuits Lab Incharge",
            created_by=created_by,
        )

        fixed_assets = self.category("IT Equipments", "IT-EQUIP", None, "FIXED_ASSET", None)
        consumables = self.category("Office & Lab Consumables", "OFF-LAB-CONS", None, "CONSUMABLE", None)

        processor_cat = self.category("Processor", "SUB-0002", fixed_assets, "FIXED_ASSET", "INDIVIDUAL")
        desktop_cat = self.category("Desktop Computer", "SUB-DESKTOP", fixed_assets, "FIXED_ASSET", "INDIVIDUAL")
        network_cat = self.category("Network Equipment", "SUB-NETWORK", fixed_assets, "FIXED_ASSET", "INDIVIDUAL")
        keyboard_cat = self.category("Keyboard", "SUB-0003", fixed_assets, "FIXED_ASSET", "BATCH")
        toner_cat = self.category("Printer Toner", "SUB-TONER", consumables, "CONSUMABLE", "BATCH")
        paper_cat = self.category("Printer Paper", "SUB-PAPER", consumables, "CONSUMABLE", "BATCH")

        processor = self.item(
            "Intel Core i5 Processor",
            "ITM-DEMO-I5",
            processor_cat,
            "pcs",
            "Desktop processor used in teaching labs and staff systems.",
            "Intel Core i5, 12th generation class, LGA desktop CPU",
            created_by,
        )
        desktop = self.item(
            "Dell OptiPlex Teaching Desktop",
            "ITM-DEMO-DESKTOP",
            desktop_cat,
            "pcs",
            "Standard lab desktop issued to teaching and CAD labs.",
            "Core i5, 16GB RAM, 512GB SSD, 22 inch display bundle",
            created_by,
        )
        switch = self.item(
            "Cisco Catalyst Access Switch",
            "ITM-DEMO-SWITCH",
            network_cat,
            "pcs",
            "Managed access switch for departmental labs.",
            "24-port managed Gigabit switch with uplink ports",
            created_by,
        )
        keyboard = self.item(
            "Logitech USB Keyboard",
            "ITM-DEMO-KEYBOARD",
            keyboard_cat,
            "pcs",
            "Replacement USB keyboards for labs and offices.",
            "Full-size wired USB keyboard",
            created_by,
        )
        toner = self.item(
            "HP LaserJet 85A Toner Cartridge",
            "ITM-DEMO-TONER",
            toner_cat,
            "cartridges",
            "Printer toner for departmental offices.",
            "Compatible black toner cartridge for HP LaserJet printers",
            created_by,
        )
        paper = self.item(
            "A4 Printer Paper Ream",
            "ITM-DEMO-PAPER",
            paper_cat,
            "reams",
            "A4 paper used by offices and labs.",
            "80 GSM white A4 paper, 500 sheets per ream",
            created_by,
        )

        toner_q2 = self.batch(toner, "TONER-2026-Q2", date.today() - timedelta(days=35), date.today() + timedelta(days=330), created_by)
        toner_q3 = self.batch(toner, "TONER-2026-Q3", date.today() - timedelta(days=5), date.today() + timedelta(days=420), created_by)
        paper_apr = self.batch(paper, "PAPER-APR-2026", date.today() - timedelta(days=20), None, created_by)
        keyboard_lot = self.batch(keyboard, "KEYBOARD-LOT-0426", date.today() - timedelta(days=28), None, created_by)

        self.stock(processor, csit_store, 6, allocated_quantity=4)
        self.stock(processor, mech_store, 3, allocated_quantity=2)
        self.stock(processor, elec_store, 2, in_transit_quantity=1)
        self.stock(desktop, csit_store, 10, allocated_quantity=6)
        self.stock(desktop, mech_store, 5, allocated_quantity=3)
        self.stock(switch, central_store, 4, in_transit_quantity=1)
        self.stock(switch, csit_store, 2, allocated_quantity=1)
        self.stock(keyboard, csit_store, 40, batch=keyboard_lot, allocated_quantity=14)
        self.stock(keyboard, mech_store, 20, batch=keyboard_lot, allocated_quantity=6)
        self.stock(toner, csit_store, 12, batch=toner_q2, allocated_quantity=3)
        self.stock(toner, mech_store, 8, batch=toner_q2, allocated_quantity=2)
        self.stock(toner, elec_store, 10, batch=toner_q3, allocated_quantity=4)
        self.stock(paper, csit_store, 60, batch=paper_apr, allocated_quantity=18)
        self.stock(paper, mech_store, 35, batch=paper_apr, allocated_quantity=10)
        self.stock(paper, elec_store, 45, batch=paper_apr, allocated_quantity=12)

        dr_ayesha = self.person("Dr. Ayesha Khan", "Assistant Professor", "CSIT", [csit])
        prof_hamid = self.person("Prof. Hamid Raza", "Professor", "Mechanical Engineering", [mechanical])
        engr_sana = self.person("Engr. Sana Ahmed", "Lab Engineer", "Electrical Engineering", [electrical])

        self.allocate(processor, csit_store, 2, person=dr_ayesha)
        self.allocate(processor, csit_store, 2, location=csit_lab_b)
        self.allocate(processor, mech_store, 1, person=prof_hamid)
        self.allocate(processor, mech_store, 1, location=mech_lab)
        self.allocate(desktop, csit_store, 4, location=csit_lab_a)
        self.allocate(desktop, csit_store, 2, person=dr_ayesha)
        self.allocate(desktop, mech_store, 3, location=mech_lab)
        self.allocate(switch, csit_store, 1, location=csit_lab_a)
        self.allocate(keyboard, csit_store, 10, batch=keyboard_lot, location=csit_lab_a)
        self.allocate(keyboard, csit_store, 4, batch=keyboard_lot, location=csit_office)
        self.allocate(keyboard, mech_store, 6, batch=keyboard_lot, location=mech_lab)
        self.allocate(toner, csit_store, 3, batch=toner_q2, location=csit_office)
        self.allocate(toner, mech_store, 2, batch=toner_q2, location=mech_office)
        self.allocate(toner, elec_store, 4, batch=toner_q3, person=engr_sana)
        self.allocate(paper, csit_store, 18, batch=paper_apr, location=csit_office)
        self.allocate(paper, mech_store, 10, batch=paper_apr, location=mech_office)
        self.allocate(paper, elec_store, 12, batch=paper_apr, location=elec_lab)

        self.instances(processor, "I5", [
            (csit_store, "AVAILABLE", 2),
            (csit_lab_b, "ALLOCATED", 2),
            (csit_store, "ALLOCATED", 2),
            (mech_lab, "ALLOCATED", 1),
            (mech_store, "AVAILABLE", 2),
            (elec_store, "IN_TRANSIT", 2),
        ], created_by)
        self.instances(desktop, "DESK", [
            (csit_lab_a, "ALLOCATED", 4),
            (csit_store, "ALLOCATED", 2),
            (csit_store, "AVAILABLE", 4),
            (mech_lab, "ALLOCATED", 3),
            (mech_store, "AVAILABLE", 2),
        ], created_by)
        self.instances(switch, "SW", [
            (central_store, "AVAILABLE", 3),
            (central_store, "IN_TRANSIT", 1),
            (csit_lab_a, "ALLOCATED", 1),
            (csit_store, "AVAILABLE", 1),
        ], created_by)

        self.stdout.write(self.style.SUCCESS("Seeded coherent demo item data."))
        self.stdout.write(
            "Items: {items}, stock records: {stock}, allocations: {allocations}, batches: {batches}, instances: {instances}".format(
                items=Item.objects.filter(code__startswith="ITM-DEMO-").count(),
                stock=StockRecord.objects.filter(item__code__startswith="ITM-DEMO-").count(),
                allocations=StockAllocation.objects.filter(item__code__startswith="ITM-DEMO-").count(),
                batches=ItemBatch.objects.filter(item__code__startswith="ITM-DEMO-").count(),
                instances=ItemInstance.objects.filter(item__code__startswith="ITM-DEMO-").count(),
            )
        )

    def location(self, **kwargs):
        code = kwargs["code"]
        defaults = kwargs.copy()
        defaults.pop("code")
        location, _ = Location.objects.update_or_create(code=code, defaults=defaults)
        return location

    def category(self, name, code, parent, category_type, tracking_type):
        category, _ = Category.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "parent_category": parent,
                "category_type": category_type,
                "tracking_type": tracking_type,
                "is_active": True,
            },
        )
        return category

    def item(self, name, code, category, unit, description, specifications, created_by):
        item, _ = Item.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "category": category,
                "acct_unit": unit,
                "description": description,
                "specifications": specifications,
                "is_active": True,
                "created_by": created_by,
            },
        )
        return item

    def batch(self, item, batch_number, manufactured_date, expiry_date, created_by):
        batch, _ = ItemBatch.objects.update_or_create(
            item=item,
            batch_number=batch_number,
            defaults={
                "manufactured_date": manufactured_date,
                "expiry_date": expiry_date,
                "is_active": True,
                "created_by": created_by,
            },
        )
        return batch

    def stock(self, item, location, quantity, batch=None, in_transit_quantity=0, allocated_quantity=0):
        StockRecord.objects.update_or_create(
            item=item,
            batch=batch,
            location=location,
            defaults={
                "quantity": quantity,
                "in_transit_quantity": in_transit_quantity,
                "allocated_quantity": allocated_quantity,
            },
        )

    def person(self, name, designation, department, standalone_locations):
        person, _ = Person.objects.update_or_create(
            name=name,
            defaults={
                "designation": designation,
                "department": department,
                "is_active": True,
            },
        )
        person.standalone_locations.set(standalone_locations)
        return person

    def allocate(self, item, source_location, quantity, batch=None, person=None, location=None):
        lookup = {
            "item": item,
            "batch": batch,
            "source_location": source_location,
            "allocated_to_person": person,
            "allocated_to_location": location,
            "status": AllocationStatus.ALLOCATED,
        }
        StockAllocation.objects.update_or_create(
            **lookup,
            defaults={
                "quantity": quantity,
                "allocated_at": timezone.now(),
                "remarks": "Demo allocation for item distribution testing",
            },
        )

    def instances(self, item, prefix, location_status_counts, created_by):
        serial = 1
        for location, status, count in location_status_counts:
            for _ in range(count):
                serial_number = f"DEMO-{prefix}-{serial:03d}"
                ItemInstance.objects.update_or_create(
                    serial_number=serial_number,
                    defaults={
                        "item": item,
                        "current_location": location,
                        "status": status,
                        "is_active": True,
                        "created_by": created_by,
                    },
                )
                serial += 1
