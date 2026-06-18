# Legacy Inspection Dependency Summary

Source table: `C:\Users\Insha Khan\ams-production\ams-backend\docs\legacy_inspection_import_table.csv`

## Counts

- Inspection certificates: 31
- Item rows: 65
- Rows linked to existing catalog items: 31
- Unique planned/review item keys: 32
- Unique department stock-register keys: 6
- Unique central-register keys: 1

## Depreciation Plan

Per latest instruction, the import plan assumes depreciation setup does not already exist. For matched fixed assets, the table now plans one depreciation asset class per item, not one shared `Fixed Asset` class. The later ORM script should create/get the `FBR WDV` policy, create/get each item-based asset class, create/get a 25.00 percent rate version, assign that class to `InspectionItem.depreciation_asset_class`, then complete inspections so backend signals create fixed-asset register entries using the intended class.

`capitalization_total_cost_candidate` in the table is the backend default capitalization total (`unit_price * accepted_quantity`) if `InspectionItem.capitalization_cost` is left blank. `line_total_candidate` remains the source/invoice total candidate; use it for `capitalization_cost` only if finance wants tax/invoice-inclusive capitalization.

| metric | value |
| --- | --- |
| Assumption for depreciation setup | No existing depreciation setup; IDs intentionally blank |
| Depreciation policy to create/get | POLICY-FBR-WDV / FBR WDV |
| Matched fixed-asset rows | 17 |
| Item-based asset classes to create | 17 |
| Fixed asset individual-tracked rows | 13 |
| Fixed asset quantity-tracked rows | 4 |
| Consumable/perishable rows with no depreciation | 14 |
| Planned-new rows needing category decision | 34 |
| Desired fixed-asset depreciation rate | 25.00% |
| Rate effective-from candidate | 2001-07-01 |
| Fixed-asset backend-default capitalization total | 769790.00 |
| Fixed-asset source line-total candidate | 714334.00 |

## Depreciation Asset Classes To Create

| asset_class_key | asset_class_code | asset_class_name | item_code | item_name | category_id | policy_key | rate | effective_from | row_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEP-ITEM-ITM-0009 | DEP-ITM-0009 | NVIDIA GeForce RTX 5060 Ti 16GB Triple Fan | ITM-0009 | NVIDIA GeForce RTX 5060 Ti 16GB Triple Fan | 7 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0010 | DEP-ITM-0010 | LED Monitor HP 2225 22 inch | ITM-0010 | LED Monitor HP 2225 22 inch | 7 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0011 | DEP-ITM-0011 | A4TECH Wireless Keyboard + Mouse FG1200S 2.4GHz | ITM-0011 | A4TECH Wireless Keyboard + Mouse FG1200S 2.4GHz | 7 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0012 | DEP-ITM-0012 | A4TECH USB Hub HUB-30 | ITM-0012 | A4TECH USB Hub HUB-30 | 7 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0013 | DEP-ITM-0013 | A4TECH FULL HD WebCam PK-925H | ITM-0013 | A4TECH FULL HD WebCam PK-925H | 7 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0014 | DEP-ITM-0014 | TP-Link WiFi USB Dongle | ITM-0014 | TP-Link WiFi USB Dongle | 7 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0015 | DEP-ITM-0015 | UPS IDEAL-5320BLU 2000VA / 1200W | ITM-0015 | UPS IDEAL-5320BLU 2000VA / 1200W | 7 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0016 | DEP-ITM-0016 | NVIDIA Jetson Nano Developer Kit (4GB) | ITM-0016 | NVIDIA Jetson Nano Developer Kit (4GB) | 8 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0017 | DEP-ITM-0017 | MAX30102 Heart-rate & SpO2 Sensor | ITM-0017 | MAX30102 Heart-rate & SpO2 Sensor | 8 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0018 | DEP-ITM-0018 | MAX30205 Body Temperature Sensor | ITM-0018 | MAX30205 Body Temperature Sensor | 8 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0019 | DEP-ITM-0019 | Digital Stethoscope with Auxiliary Cable | ITM-0019 | Digital Stethoscope with Auxiliary Cable | 8 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0020 | DEP-ITM-0020 | RODE Wireless GO II Microphone | ITM-0020 | RODE Wireless GO II Microphone | 8 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0021 | DEP-ITM-0021 | LED Digital Clock Module JH3604 | ITM-0021 | LED Digital Clock Module JH3604 | 8 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0022 | DEP-ITM-0022 | Over Counter Washbasin | ITM-0022 | Over Counter Washbasin | 9 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0023 | DEP-ITM-0023 | Basin Mixer Tap | ITM-0023 | Basin Mixer Tap | 9 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0024 | DEP-ITM-0024 | Display Shield | ITM-0024 | Display Shield | 10 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |
| DEP-ITEM-ITM-0025 | DEP-ITM-0025 | Trophy | ITM-0025 | Trophy | 10 | POLICY-FBR-WDV | 25.00 | 2001-07-01 | 1 |

## Category And Tracking Split

| classification | row_count |
| --- | --- |
| CONSUMABLE + QUANTITY | 14 |
| FIXED_ASSET + INDIVIDUAL | 13 |
| FIXED_ASSET + QUANTITY | 4 |
| UNMATCHED + UNMATCHED | 34 |

## Planned Stock Registers

| register_key | number | type | store_id | store_name | existing_id | row_count |
| --- | --- | --- | --- | --- | --- | --- |
| SR-31-DSR-SOFTWARE-ENGINEERING | DSR (CSE) | DSR | 31 | Software Engineering  Office |  | 1 |
| SR-6-MAIN-CSR | Main CSR | CSR | 6 | CSIT office | 1 | 39 |
| SR-6-MAIN-DSR | Main DSR | DSR | 6 | CSIT office | 2 | 2 |
| SR-6-MAIN-FFFR | Main FFFR | DSR | 6 | CSIT office |  | 1 |
| SR-6-MAIN-FFR | Main FFR | DSR | 6 | CSIT office |  | 1 |
| SR-6-PHD-DSR | PHD DSR | DSR | 6 | CSIT office |  | 2 |

## Planned Central Registers

| register_key | number | type | store_id | store_name | existing_id | row_count |
| --- | --- | --- | --- | --- | --- | --- |
| SR-2-11 | 11 | DSR | 2 | Central Store |  | 14 |

## Item Plan

| planned_item_key | action | matched_item | sample_source_description | category_type | tracking_type | depreciation_required | rate | asset_class_key | row_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ITM-0001 | link_existing_item | ITM-0001 Paper Ream A4 80GSM | Paper Ream A4 size | CONSUMABLE | QUANTITY | NO |  |  | 7 |
| ITM-0002 | link_existing_item | ITM-0002 Whiteboard Marker (Erasable) | Board marker erasable | CONSUMABLE | QUANTITY | NO |  |  | 1 |
| ITM-0003 | link_existing_item | ITM-0003 Marker Ink Refill | Marker Ink | CONSUMABLE | QUANTITY | NO |  |  | 1 |
| ITM-0004 | link_existing_item | ITM-0004 Whiteboard Duster | Dusters | CONSUMABLE | QUANTITY | NO |  |  | 1 |
| ITM-0005 | link_existing_item | ITM-0005 Box File | Box files | CONSUMABLE | QUANTITY | NO |  |  | 1 |
| ITM-0006 | link_existing_item | ITM-0006 PPC Machine Toner | PPC Machine Toner, or Equivalent | CONSUMABLE | QUANTITY | NO |  |  | 1 |
| ITM-0007 | link_existing_item | ITM-0007 Jumper Wires (50 pcs/set, M-M / M-F / F-F) | Jumpers wire, Male to Male, Male to Female & Female to Female, set of 50 pcs each | CONSUMABLE | QUANTITY | NO |  |  | 1 |
| ITM-0008 | link_existing_item | ITM-0008 HDMI to VGA Cable | HDMI to VGA Cable | CONSUMABLE | QUANTITY | NO |  |  | 1 |
| ITM-0009 | link_existing_item | ITM-0009 NVIDIA GeForce RTX 5060 Ti 16GB Triple Fan | NVIDIA GeForce RTX-5060 Ti 16 GB Tripple Fan | FIXED_ASSET | INDIVIDUAL | YES | 25.00 | DEP-ITEM-ITM-0009 | 1 |
| ITM-0010 | link_existing_item | ITM-0010 LED Monitor HP 2225 22 inch | LED HP Model 2225 22inch | FIXED_ASSET | INDIVIDUAL | YES | 25.00 | DEP-ITEM-ITM-0010 | 1 |
| ITM-0011 | link_existing_item | ITM-0011 A4TECH Wireless Keyboard + Mouse FG1200S 2.4GHz | Wireless Keyboard and Mouse A4TECH 2.4GHz FG1200S | FIXED_ASSET | INDIVIDUAL | YES | 25.00 | DEP-ITEM-ITM-0011 | 1 |
| ITM-0012 | link_existing_item | ITM-0012 A4TECH USB Hub HUB-30 | USB Hub: A4TECH HUB-30 | FIXED_ASSET | INDIVIDUAL | YES | 25.00 | DEP-ITEM-ITM-0012 | 1 |
| ITM-0013 | link_existing_item | ITM-0013 A4TECH FULL HD WebCam PK-925H | WebCam FULL HD A4TECH PK-925H | FIXED_ASSET | INDIVIDUAL | YES | 25.00 | DEP-ITEM-ITM-0013 | 1 |
| ITM-0014 | link_existing_item | ITM-0014 TP-Link WiFi USB Dongle | WIFI USB DONGLE TP Link | FIXED_ASSET | INDIVIDUAL | YES | 25.00 | DEP-ITEM-ITM-0014 | 1 |
| ITM-0015 | link_existing_item | ITM-0015 UPS IDEAL-5320BLU 2000VA / 1200W | UPS, Input # 220Vac@50Hz, Output # 220Vac@50Hz, Capacity # 2000VA/1200W, Model # IDEAL-5320BLU, Brand # IDEAL, Or Equivalent | FIXED_ASSET | INDIVIDUAL | YES | 25.00 | DEP-ITEM-ITM-0015 | 1 |
| ITM-0016 | link_existing_item | ITM-0016 NVIDIA Jetson Nano Developer Kit (4GB) | Jetson Nanao NVIDIA Jeston Nano GPU: 128-core NVIDIA Maxwell CPU: Arm Cortex A57 MPCore RAM: 4GB LPDDR4 5V & 4A Charger and USB Developer Kit | FIXED_ASSET | INDIVIDUAL | YES | 25.00 | DEP-ITEM-ITM-0016 | 1 |
| ITM-0017 | link_existing_item | ITM-0017 MAX30102 Heart-rate & SpO2 Sensor | Max 30102 for heart rate and oxygen sensor | FIXED_ASSET | INDIVIDUAL | YES | 25.00 | DEP-ITEM-ITM-0017 | 1 |
| ITM-0018 | link_existing_item | ITM-0018 MAX30205 Body Temperature Sensor | Max30205 for body temperature sensing | FIXED_ASSET | INDIVIDUAL | YES | 25.00 | DEP-ITEM-ITM-0018 | 1 |
| ITM-0019 | link_existing_item | ITM-0019 Digital Stethoscope with Auxiliary Cable | Digital Stethoscope with Auxiliary Cable | FIXED_ASSET | INDIVIDUAL | YES | 25.00 | DEP-ITEM-ITM-0019 | 1 |
| ITM-0020 | link_existing_item | ITM-0020 RODE Wireless GO II Microphone | Wireless Mic (RODE Wireless GO II) | FIXED_ASSET | INDIVIDUAL | YES | 25.00 | DEP-ITEM-ITM-0020 | 1 |
| ITM-0021 | link_existing_item | ITM-0021 LED Digital Clock Module JH3604 | LED Digital Clock Module JH3604 | FIXED_ASSET | INDIVIDUAL | YES | 25.00 | DEP-ITEM-ITM-0021 | 1 |
| ITM-0022 | link_existing_item | ITM-0022 Over Counter Washbasin | Over Counter Washbasin | FIXED_ASSET | QUANTITY | YES | 25.00 | DEP-ITEM-ITM-0022 | 1 |
| ITM-0023 | link_existing_item | ITM-0023 Basin Mixer Tap | Basin Mixer (Tap) | FIXED_ASSET | QUANTITY | YES | 25.00 | DEP-ITEM-ITM-0023 | 1 |
| ITM-0024 | link_existing_item | ITM-0024 Display Shield | Shields | FIXED_ASSET | QUANTITY | YES | 25.00 | DEP-ITEM-ITM-0024 | 1 |
| ITM-0025 | link_existing_item | ITM-0025 Trophy | Trophies | FIXED_ASSET | QUANTITY | YES | 25.00 | DEP-ITEM-ITM-0025 | 1 |
| NEW-ITEM-12V-5V-ADAPTER-RECEIVER-SOUND | create_or_review_new_item |  | 12V - 5V ADAPTER FOR RECEIVER SOUND |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-ABSTRACT-BOOK-26-PAGES | create_or_review_new_item |  | Abstract Book (26 Pages) or Equivalent |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-BANNERS-4-X-6 | create_or_review_new_item |  | Banners (4 x 6) |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-BOARD-FITTING-ACCESSORIES | create_or_review_new_item |  | Board Fitting Accessories |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-CARDS-IDENTIFICATION-RIBBON-PACKET | create_or_review_new_item |  | Cards for Identification with Ribbon & Packet. ~~or Equivalent.~~ |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-CHANNEL-DUCT | create_or_review_new_item |  | CHANNEL DUCT SIZE |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-COMPLETE-INSTALLATION-TRANSPORTATION-CHARGES-ALL-RESPECT-LAY | create_or_review_new_item |  | COMPLETE INSTALLATION AND TRANSPORTATION CHARGERS WITH ALL RESPECT LAYING, PULLING, DRILLING, FITTING, CONNECTING |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-DAWN-VISITOR-CHAIR | create_or_review_new_item |  | Dawn Visitor Chair |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-DOOR-LOCK | create_or_review_new_item |  | Door Lock |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-DT-HEADSET-MICROPHONE-DM-793 | create_or_review_new_item |  | DT Brand Headset Microphone Model No.DM-793 |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-EPSON-EB-E01-PROJECTOR | create_or_review_new_item |  | Epson Multimedia Projector Model No. EB-EDI 3 LCD UNIT TECHNOLOGY 3,300 KYNEB\XGA.1024X768,4.3 CONTRAST RATIO 15,000:1 |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 2 |
| NEW-ITEM-EXECUTIVE-CHAIR-REVOLVING-GENESIS-HIGH-BACK-BLACK-COLOR | create_or_review_new_item |  | Executive Chair Revolving Genesis high Back Black color Master make or Equivalent |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-HDMI-4K-SUPPORT-CABLE | create_or_review_new_item |  | HDMI 4K SUPPORT CABLE |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-HDMI-CABLE-5-METER | create_or_review_new_item |  | HDMI CABLE 5 METER |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-HEADSET-REDRAGON-WIRELESS-GAMING-HEADPHONE-H848-REDRAGON | create_or_review_new_item |  | HEADSET, Regdragon Wireless Gaming Headphone. Model # H848, Brand # Redragon, Or Equivalent |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-INVITATION-CARDS-ENVELOPES | create_or_review_new_item |  | Invitation Cards with Envelopes or Equivalent |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-MARBLE-SLAB-COUNTERTOP | create_or_review_new_item |  | Marble Slab Countertop |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-MOUSE-VAMPIRE-ELITE-WIRELESS-GAMING-MOUSE-M686-REDRAGON | create_or_review_new_item |  | Mouse, VAMPIRE ELITE Wireless Gaming Mouse. Model # M686, Brand # Redragon, Or Equivalent |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-PBS-POLARIZING-BEAM-SPLITTER-TRANSPARENT-LENS-630NM-660NM | create_or_review_new_item |  | PBS Polarizing Beam Splitter Transparent Lens 630nm-660nm Polarizing Beam Splitter Cubes Lens 10X10X10mm, Reflection Angle : 45 Broadband transparent 630nm-660nm Principal Transmittance: Tp > 95% and Ts 99% and Rp <5% |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-PEN-BRANDING | create_or_review_new_item |  | Pen with Branding or Equivalent |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-POWER-CABLE-PROJECTOR-15-METER | create_or_review_new_item |  | POWER CABLE FOR PROJECTOR 15 METER |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-PROJECTOR-CEILING-STAND | create_or_review_new_item |  | PROJECTOR CELLING STAND |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-PVC-CABLE-4-CORE-16-SQ-MM | create_or_review_new_item |  | PVC Cable 4 Core (16 Sq.MM) |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-ROSTRUM-CLASSROOM | create_or_review_new_item |  | Rostrum for Classroom |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-SAFETY-SECURITY-BOX-PROJECTOR | create_or_review_new_item |  | SAFETY SECURITY BOX FOR PROJECTOR |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-SOFT-BOARD-NOTICE-BOARD-FABRIC-CUSHION | create_or_review_new_item |  | Soft Board Notice Board with Fabric Cushion |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-VISITOR-CHAIRS-MESH-FABRIC-UPHOLSTERY-SEAT-BACK-FIXED | create_or_review_new_item |  | Visitor Chairs (Mesh Fabric upholstery seat and back fixed arms |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-WHITE-BOARD-LAMINATION-SHEET | create_or_review_new_item |  | White Board Lamination Sheet |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-WHITE-BOARD-SHEETS | create_or_review_new_item |  | White Board Sheets with Fitting |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 2 |
| NEW-ITEM-WINDOW-SHUTTER | create_or_review_new_item |  | Window Shutter |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-WRITING-PADS-8-X-5 | create_or_review_new_item |  | Writing Pads (8 x 5) or Equivalent |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
| NEW-ITEM-X-STANDEES | create_or_review_new_item |  | X-Standees or Equivalent |  |  | CATEGORY_NEEDED | 25.00_IF_FIXED_ASSET | CREATE_AFTER_ITEM_IS_FIXED_ASSET | 1 |
