"""
One-shot import of 13 inspections extracted from inspection_data.md.

Run from the backend root with USE_POSTGRES=true so it hits the restored Postgres:

    set USE_POSTGRES=true && venv\\Scripts\\python.exe scripts\\import_inspections.py

The script is idempotent on contract_no — re-running skips inspections already created.
"""
import os
import sys
import django

# Bootstrap Django so this can run as a plain script
BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ams.settings")
django.setup()

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from inventory.models.category_model import Category, CategoryType, TrackingType
from inventory.models.item_model import Item
from inventory.models.location_model import Location
from inventory.models.stock_register_model import StockRegister
from inventory.models.inspection_model import (
    InspectionCertificate,
    InspectionItem,
    InspectionStage,
)


# =============================================================================
# REFERENCE DATA — users, locations
# =============================================================================
chairman = User.objects.get(username="chairman.csit")
it_csit = User.objects.get(username="it.csit")
mgr_central = User.objects.get(username="manager.centralstore")
finance = User.objects.get(username="assistantdirector.finance")

csit_dept = Location.objects.get(id=5)
csit_store = Location.objects.get(id=csit_dept.auto_created_store_id)  # CSIT office
central_store = Location.objects.get(id=2)
print(f"Dept: {csit_dept.name} -> store: {csit_store.name} (id={csit_store.id})")
print(f"Central store: {central_store.name} (id={central_store.id})")


# =============================================================================
# CATEGORIES — 3 parents + 7 subcategories
# =============================================================================
def get_or_create_parent(name, ctype, dep_rate=None):
    obj, created = Category.objects.get_or_create(
        name=name,
        parent_category=None,
        defaults={
            "category_type": ctype,
            "default_depreciation_rate": dep_rate,
        },
    )
    if created:
        print(f"  + parent category: {name}")
    return obj


def get_or_create_sub(name, parent, tracking):
    obj, created = Category.objects.get_or_create(
        name=name,
        parent_category=parent,
        defaults={
            "tracking_type": tracking,
            "category_type": parent.category_type,
        },
    )
    if created:
        print(f"  + subcategory: {parent.name} / {name} ({tracking})")
    return obj


print("\n== Categories ==")
cons_parent = get_or_create_parent("Consumable", CategoryType.CONSUMABLE)
peri_parent = get_or_create_parent("Perishable", CategoryType.PERISHABLE)
fixed_parent = get_or_create_parent(
    "Fixed Asset", CategoryType.FIXED_ASSET, dep_rate=Decimal("10.00")
)

stationery = get_or_create_sub("Stationery", cons_parent, TrackingType.QUANTITY)
printer_cons = get_or_create_sub("Printer Consumables", cons_parent, TrackingType.QUANTITY)
cables_acc = get_or_create_sub("Cables & Accessories", cons_parent, TrackingType.QUANTITY)
it_equip = get_or_create_sub("IT Equipment", fixed_parent, TrackingType.INDIVIDUAL)
lab_elec = get_or_create_sub("Lab & Research Electronics", fixed_parent, TrackingType.INDIVIDUAL)
plumbing = get_or_create_sub("Plumbing Fixtures", fixed_parent, TrackingType.QUANTITY)
awards = get_or_create_sub("Awards & Display", fixed_parent, TrackingType.QUANTITY)


# =============================================================================
# ITEMS — 25 unique items
# =============================================================================
def get_or_create_item(name, category, acct_unit="No.", specs=""):
    obj, created = Item.objects.get_or_create(
        name=name,
        defaults={
            "category": category,
            "acct_unit": acct_unit,
            "specifications": specs,
            "is_active": True,
        },
    )
    if created:
        print(f"  + item: {name}")
    return obj


print("\n== Items ==")
I = {
    "paper_ream": get_or_create_item("Paper Ream A4 80GSM", stationery, "Ream"),
    "board_marker": get_or_create_item("Whiteboard Marker (Erasable)", stationery),
    "marker_ink": get_or_create_item("Marker Ink Refill", stationery),
    "duster": get_or_create_item("Whiteboard Duster", stationery),
    "box_file": get_or_create_item("Box File", stationery),
    "ppc_toner": get_or_create_item("PPC Machine Toner", printer_cons),
    "jumper_wires": get_or_create_item(
        "Jumper Wires (50 pcs/set, M-M / M-F / F-F)", cables_acc, "Set"
    ),
    "hdmi_vga": get_or_create_item("HDMI to VGA Cable", cables_acc),
    "nvidia_rtx": get_or_create_item(
        "NVIDIA GeForce RTX 5060 Ti 16GB Triple Fan",
        it_equip,
        "No.",
        "16GB GDDR6, triple-fan",
    ),
    "led_monitor": get_or_create_item("LED Monitor HP 2225 22 inch", it_equip),
    "kb_mouse_set": get_or_create_item(
        "A4TECH Wireless Keyboard + Mouse FG1200S 2.4GHz", it_equip, "Set"
    ),
    "usb_hub": get_or_create_item("A4TECH USB Hub HUB-30", it_equip),
    "webcam": get_or_create_item("A4TECH FULL HD WebCam PK-925H", it_equip),
    "wifi_dongle": get_or_create_item("TP-Link WiFi USB Dongle", it_equip),
    "ups": get_or_create_item(
        "UPS IDEAL-5320BLU 2000VA / 1200W",
        it_equip,
        "No.",
        "Input 220Vac@50Hz, Output 220Vac@50Hz",
    ),
    "jetson_nano": get_or_create_item(
        "NVIDIA Jetson Nano Developer Kit (4GB)",
        lab_elec,
        "Set",
        "128-core Maxwell GPU, Arm Cortex A57, 4GB LPDDR4",
    ),
    "max30102": get_or_create_item(
        "MAX30102 Heart-rate & SpO2 Sensor", lab_elec, "Set"
    ),
    "max30205": get_or_create_item(
        "MAX30205 Body Temperature Sensor", lab_elec, "Set"
    ),
    "stethoscope": get_or_create_item(
        "Digital Stethoscope with Auxiliary Cable", lab_elec, "Set"
    ),
    "rode_mic": get_or_create_item("RODE Wireless GO II Microphone", lab_elec),
    "led_clock_module": get_or_create_item("LED Digital Clock Module JH3604", lab_elec),
    "washbasin": get_or_create_item("Over Counter Washbasin", plumbing),
    "basin_tap": get_or_create_item("Basin Mixer Tap", plumbing),
    "shield": get_or_create_item("Display Shield", awards),
    "trophy": get_or_create_item("Trophy", awards),
}


# =============================================================================
# STOCK REGISTERS — 3 at CSIT office, 2 at Central Store
# =============================================================================
def get_or_create_register(register_number, store, register_type):
    obj, created = StockRegister.objects.get_or_create(
        register_number=register_number,
        store=store,
        defaults={"register_type": register_type, "is_active": True, "created_by": chairman},
    )
    if created:
        print(f"  + register: {register_number} @ {store.name} ({register_type})")
    return obj


print("\n== Stock Registers ==")
csit_main_csr = get_or_create_register("Main CSR", csit_store, "CSR")
csit_main_dsr = get_or_create_register("Main DSR", csit_store, "DSR")
csit_pad_dsr = get_or_create_register("PAD DSR", csit_store, "DSR")
central_main_csr = get_or_create_register("Main CSR", central_store, "CSR")
central_main_dsr = get_or_create_register("Main DSR", central_store, "DSR")


# =============================================================================
# INSPECTIONS — 13 entries from inspection_data.md
# =============================================================================
def D(s):
    """Parse dd-mm-yyyy or dd-mm-yy."""
    parts = s.replace("/", "-").split("-")
    d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
    if y < 100:
        y += 2000
    return date(y, m, d)


# Each entry: contract_no, contractor, indenter, indent_no, consignee, consignee_desig,
# dates (deliv, insp, entry), dept_reg + page, central_reg + page, items
INSPECTIONS = [
    # 1 — Paper Ream June 2026
    {
        "contract_no": "CCS/2026/4/390",
        "contractor": "METRO Pakistan (Pvt) Ltd",
        "indenter": "NIL",
        "indent_no": "NIL",
        "consignee": "Imdadullah",
        "consignee_desig": "PA, CSIT",
        "deliv": D("02-06-2026"),
        "insp": D("02-06-2026"),
        "entry": D("03-04-2026"),
        "dept_reg": csit_main_csr,
        "dept_page": "424",
        "central_reg": central_main_csr,
        "central_page": "424",
        "remarks": "Memo Ref CCS/2026/4/390 — Reimbursement of Paper Ream purchase, Rs. 5,496/-",
        "items": [("paper_ream", 5, 5, 0, Decimal("1099.20"), None)],
    },
    # 2 — LED Digital Clock Modules
    {
        "contract_no": "CCS/2026/40062",
        "contractor": "ALPHA ENGINEERING",
        "indenter": "NIL",
        "indent_no": "NIL",
        "consignee": "IMDADULLAH",
        "consignee_desig": "PA, CSIT",
        "deliv": D("25-05-2026"),
        "insp": D("25-05-2026"),
        "entry": D("25-05-2026"),
        "dept_reg": csit_main_csr,
        "dept_page": "461",
        "central_reg": central_main_dsr,
        "central_page": "461",
        "remarks": "Memo Ref CCS/2026/40062 — LED Digital Clock Modules, Rs. 99,120/-",
        "items": [
            (
                "led_clock_module",
                12,
                12,
                0,
                Decimal("8260.00"),
                {"cap": Decimal("8260.00"), "cap_date": D("25-05-2026")},
            )
        ],
    },
    # 3 — Paper Ream May 2026
    {
        "contract_no": "CCS/2026/38147",
        "contractor": "METRO Pakistan (Pvt) Ltd",
        "indenter": "NIL",
        "indent_no": "NIL",
        "consignee": "IMDADULLAH",
        "consignee_desig": "PA, CSIT",
        "deliv": D("14-05-2026"),
        "insp": D("14-05-2026"),
        "entry": D("18-05-2026"),
        "dept_reg": csit_main_csr,
        "dept_page": "386",
        "central_reg": central_main_csr,
        "central_page": "386",
        "remarks": "Memo Ref CCS/2026/38147 — Paper Ream from CSIT Sustainability, Rs. 5,396/-",
        "items": [("paper_ream", 5, 5, 0, Decimal("1079.20"), None)],
    },
    # 4 — NVIDIA RTX 5060 Ti
    {
        "contract_no": "CCS/2026/33322",
        "contractor": "IAFE Solutions",
        "contractor_addr": (
            "Flat B-5, 2nd Floor, Farhan Apartment, St-8, Gulshan-E-Faisal, "
            "Bath Island, Clifton, Karachi"
        ),
        "indenter": "Dr. Usman Amjad, CS&IT",
        "indent_no": "---",
        "consignee": "Dr. Usman Amjad",
        "consignee_desig": "Associate Professor",
        "deliv": D("16-04-2026"),
        "insp": D("27-04-2026"),
        "entry": D("27-04-2026"),
        "dept_reg": csit_main_csr,
        "dept_page": "825",
        "central_reg": central_main_dsr,
        "central_page": "825",
        "remarks": "Memo Ref CCS/2026/33322 — SRSP HEC Project #426 (Real Time Post-Flood Diseases Detection)",
        "items": [
            (
                "nvidia_rtx",
                1,
                1,
                0,
                Decimal("211000.00"),
                {"cap": Decimal("248980.00"), "cap_date": D("27-04-2026")},
            )
        ],
    },
    # 5 — Continental Traders multi-item (SRSP #426)
    {
        "contract_no": "SRSP-426/CT-2026-04-A",
        "contractor": "Continental Traders",
        "indenter": "Dr. Usman Amjad, CS&IT",
        "indent_no": "---",
        "consignee": "Dr. Usman Amjad",
        "consignee_desig": "Associate Professor",
        "deliv": D("20-04-2026"),
        "insp": D("27-04-2026"),
        "entry": D("28-04-2026"),
        "dept_reg": csit_main_csr,
        "dept_page": "169,270,278,229,300,130,168,115",
        "central_reg": central_main_csr,
        "central_page": "169,270,278,229,300,130,168,115",
        "remarks": "SRSP HEC Project #426 — sensors, cables, peripherals",
        "items": [
            ("max30102", 3, 3, 0, Decimal("0.00"), {"cap": Decimal("0.00"), "cap_date": D("27-04-2026")}),
            ("max30205", 3, 3, 0, Decimal("0.00"), {"cap": Decimal("0.00"), "cap_date": D("27-04-2026")}),
            ("jumper_wires", 3, 3, 0, Decimal("0.00"), None),
            ("stethoscope", 1, 1, 0, Decimal("0.00"), {"cap": Decimal("0.00"), "cap_date": D("27-04-2026")}),
            ("usb_hub", 1, 1, 0, Decimal("0.00"), {"cap": Decimal("0.00"), "cap_date": D("27-04-2026")}),
            ("kb_mouse_set", 1, 1, 0, Decimal("0.00"), {"cap": Decimal("0.00"), "cap_date": D("27-04-2026")}),
            ("webcam", 1, 1, 0, Decimal("0.00"), {"cap": Decimal("0.00"), "cap_date": D("27-04-2026")}),
            ("hdmi_vga", 1, 1, 0, Decimal("0.00"), None),
            ("wifi_dongle", 1, 1, 0, Decimal("0.00"), {"cap": Decimal("0.00"), "cap_date": D("27-04-2026")}),
        ],
    },
    # 6 — IAFE LED Monitor
    {
        "contract_no": "SRSP-426/IAFE-LED-2026",
        "contractor": "IAFE Solutions",
        "indenter": "Dr. Usman Amjad, CS&IT",
        "indent_no": "---",
        "consignee": "Dr. Usman Amjad",
        "consignee_desig": "Associate Professor",
        "deliv": D("22-04-2026"),
        "insp": D("23-04-2026"),
        "entry": D("27-04-2026"),
        "dept_reg": csit_main_csr,
        "dept_page": "307",
        "central_reg": central_main_dsr,
        "central_page": "307",
        "remarks": "SRSP HEC Project #426 — LED HP Monitor 22 inch",
        "items": [
            (
                "led_monitor",
                1,
                1,
                0,
                Decimal("0.00"),
                {"cap": Decimal("0.00"), "cap_date": D("23-04-2026")},
            )
        ],
    },
    # 7 — RODE Wireless Mic
    {
        "contract_no": "CCS-ALPHA-MIC-2026",
        "contractor": "ALPHA ENGINEERING",
        "indenter": "NIL",
        "indent_no": "NIL",
        "consignee": "Imdadullah",
        "consignee_desig": "PA, CSIT",
        "deliv": D("03-01-2026"),
        "insp": D("13-04-2026"),
        "entry": D("13-04-2026"),
        "dept_reg": csit_main_csr,
        "dept_page": "303",
        "central_reg": central_main_dsr,
        "central_page": "303",
        "remarks": "RODE Wireless GO II microphone",
        "items": [
            (
                "rode_mic",
                1,
                1,
                0,
                Decimal("0.00"),
                {"cap": Decimal("0.00"), "cap_date": D("13-04-2026")},
            )
        ],
    },
    # 8 — Stationery bundle
    {
        "contract_no": "CCS-ALPHA-STAT-2026",
        "contractor": "ALPHA ENGINEERING",
        "indenter": "NIL",
        "indent_no": "NIL",
        "consignee": "Imdadullah",
        "consignee_desig": "PA, CSIT",
        "deliv": D("02-01-2026"),
        "insp": D("02-04-2026"),
        "entry": D("06-04-2026"),
        "dept_reg": csit_main_csr,
        "dept_page": "422,284,51,265,388",
        "central_reg": central_main_csr,
        "central_page": "422,284,51,265,388",
        "remarks": "Stationery bundle — markers, ink, dusters, box files, paper",
        "items": [
            ("board_marker", 120, 120, 0, Decimal("0.00"), None),
            ("marker_ink", 8, 8, 0, Decimal("0.00"), None),
            ("duster", 24, 24, 0, Decimal("0.00"), None),
            ("box_file", 5, 5, 0, Decimal("0.00"), None),
            ("paper_ream", 5, 5, 0, Decimal("0.00"), None),
        ],
    },
    # 9 — Plumbing fixtures
    {
        "contract_no": "CCS-ALPHA-PLUMB-2025",
        "contractor": "ALPHA ENGINEERING",
        "indenter": "NIL",
        "indent_no": "NIL",
        "consignee": "Imdadullah",
        "consignee_desig": "PA, CSIT",
        "deliv": D("29-12-2025"),
        "insp": D("02-04-2026"),
        "entry": D("06-04-2026"),
        "dept_reg": csit_main_csr,
        "dept_page": "416",
        "central_reg": central_main_dsr,
        "central_page": "416",
        "remarks": "Over-counter washbasins + basin mixer taps",
        "items": [
            (
                "washbasin",
                6,
                6,
                0,
                Decimal("0.00"),
                {"cap": Decimal("0.00"), "cap_date": D("02-04-2026")},
            ),
            (
                "basin_tap",
                6,
                6,
                0,
                Decimal("0.00"),
                {"cap": Decimal("0.00"), "cap_date": D("02-04-2026")},
            ),
        ],
    },
    # 10 — Jetson Nano (Main DSR)
    {
        "contract_no": "SRSP-426/JETSON-2026",
        "contractor": "Continental Traders",
        "indenter": "Dr. Usman Amjad, CS&IT",
        "indent_no": "---",
        "consignee": "Dr. Usman Amjad",
        "consignee_desig": "Associate Professor",
        "deliv": D("25-02-2026"),
        "insp": D("05-03-2026"),
        "entry": D("06-03-2026"),
        "dept_reg": csit_main_dsr,
        "dept_page": "279",
        "central_reg": central_main_dsr,
        "central_page": "364/65",
        "remarks": "SRSP HEC Project #426 — Jetson Nano Developer Kit",
        "items": [
            (
                "jetson_nano",
                1,
                1,
                0,
                Decimal("96760.00"),
                {"cap": Decimal("96760.00"), "cap_date": D("05-03-2026")},
            )
        ],
    },
    # 11 — UPS (PAD DSR, Huma Tabassum PhD project)
    {
        "contract_no": "PHD-FBPLA/UPS-2024",
        "contractor": "Continental Traders",
        "indenter": "Chairman, CS&IT",
        "indent_no": "---",
        "consignee": "Ms. Huma Tabassum",
        "consignee_desig": "PhD Researcher",
        "deliv": D("11-07-2024"),
        "insp": D("18-07-2024"),
        "entry": D("18-07-2024"),
        "dept_reg": csit_pad_dsr,
        "dept_page": "21",
        "central_reg": central_main_dsr,
        "central_page": "42/17",
        "remarks": "PhD Research Project — Formulating Feedback-based Perspective Learning Analytics Model",
        "items": [
            (
                "ups",
                1,
                1,
                0,
                Decimal("0.00"),
                {"cap": Decimal("0.00"), "cap_date": D("18-07-2024")},
            )
        ],
    },
    # 12 — Shields & Trophies
    {
        "contract_no": "CCS-ALPHA-AWARDS-2025",
        "contractor": "Alpha Engineering",
        "indenter": "Chairman, CS&IT",
        "indent_no": "NIL",
        "consignee": "Imdadullah",
        "consignee_desig": "PA, CSIT",
        "deliv": D("25-04-2025"),
        "insp": D("25-04-2025"),
        "entry": D("28-04-2025"),
        "dept_reg": csit_main_csr,
        "dept_page": "222,244",
        "central_reg": central_main_dsr,
        "central_page": "44/46",
        "remarks": "Awards bundle for Software Engineering Complex Engineering Activity",
        "items": [
            (
                "shield",
                6,
                6,
                0,
                Decimal("0.00"),
                {"cap": Decimal("0.00"), "cap_date": D("25-04-2025")},
            ),
            (
                "trophy",
                3,
                3,
                0,
                Decimal("0.00"),
                {"cap": Decimal("0.00"), "cap_date": D("25-04-2025")},
            ),
        ],
    },
    # 13 — Printing supplies Metro
    {
        "contract_no": "CCS-PRINT-METRO-2024",
        "contractor": "Metro Pakistan (Pvt) Ltd",
        "indenter": "Chairman, CS&IT",
        "indent_no": "---",
        "consignee": "Imdadullah",
        "consignee_desig": "PA, CSIT",
        "deliv": D("21-10-2024"),
        "insp": D("25-10-2024"),
        "entry": D("25-10-2024"),
        "dept_reg": csit_main_csr,
        "dept_page": "385",
        "central_reg": central_main_dsr,
        "central_page": "42/24",
        "remarks": "Printing Expenses — Paper A4 + PPC Toner",
        "items": [
            ("paper_ream", 5, 5, 0, Decimal("0.00"), None),
            ("ppc_toner", 1, 1, 0, Decimal("0.00"), None),
        ],
    },
]


# =============================================================================
# EXECUTE
# =============================================================================
print("\n== Inspections ==")
created_count = 0
skipped_count = 0
for spec in INSPECTIONS:
    cno = spec["contract_no"]
    if InspectionCertificate.objects.filter(contract_no=cno).exists():
        print(f"  - SKIP {cno} (already exists)")
        skipped_count += 1
        continue

    with transaction.atomic():
        ic = InspectionCertificate.objects.create(
            date=spec["insp"],
            contract_no=cno,
            contract_date=spec["insp"],
            contractor_name=spec["contractor"],
            contractor_address=spec.get("contractor_addr", ""),
            indenter=spec["indenter"],
            indent_no=spec["indent_no"],
            department=csit_dept,
            date_of_delivery=spec["deliv"],
            delivery_type="FULL",
            date_of_inspection=spec["insp"],
            consignee_name=spec["consignee"],
            consignee_designation=spec["consignee_desig"],
            remarks=spec.get("remarks", ""),
            stage=InspectionStage.DRAFT,
            status="DRAFT",
            initiated_by=chairman,
        )

        for tup in spec["items"]:
            key, tend, acc, rej, price, extra = tup
            item = I[key]
            extra = extra or {}
            InspectionItem.objects.create(
                inspection_certificate=ic,
                item=item,
                item_description=item.name,
                tendered_quantity=tend,
                accepted_quantity=acc,
                rejected_quantity=rej,
                unit_price=price,
                stock_register=spec["dept_reg"],
                stock_register_no=spec["dept_reg"].register_number,
                stock_register_page_no=spec["dept_page"],
                stock_entry_date=spec["entry"],
                central_register=spec["central_reg"],
                central_register_no=spec["central_reg"].register_number,
                central_register_page_no=spec["central_page"],
                capitalization_cost=extra.get("cap"),
                capitalization_date=extra.get("cap_date"),
            )

        # Walk through workflow: DRAFT → STOCK_DETAILS → CENTRAL_REGISTER → FINANCE_REVIEW → COMPLETED
        ic.stage = InspectionStage.STOCK_DETAILS
        ic.status = "IN_PROGRESS"
        ic.save()

        ic.stage = InspectionStage.CENTRAL_REGISTER
        ic.stock_filled_by = it_csit
        ic.stock_filled_at = timezone.now()
        ic.save()

        ic.stage = InspectionStage.FINANCE_REVIEW
        ic.central_store_filled_by = mgr_central
        ic.central_store_filled_at = timezone.now()
        ic.save()

        # Final transition — fires auto_generate_stock_from_inspection signal
        ic.stage = InspectionStage.COMPLETED
        ic.status = "COMPLETED"
        ic.finance_reviewed_by = finance
        ic.finance_reviewed_at = timezone.now()
        ic.finance_check_date = timezone.localdate()
        ic.save()

        print(f"  + {cno}  ->  COMPLETED  ({len(spec['items'])} items)")
        created_count += 1

print(
    f"\nSummary: {created_count} created, {skipped_count} skipped, "
    f"{InspectionCertificate.objects.count()} total inspections in DB."
)
