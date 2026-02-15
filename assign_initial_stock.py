from inventory.models import Item, Location, StockEntry, StockEntryItem
from django.utils import timezone
from django.db import transaction

def assign_initial_stock():
    item_ids = [1, 2] # Core i5, Interwood Chair
    store_ids = [47, 50, 49] # Central Store, Lab 1, CSIT - Main Store
    quantity = 5

    with transaction.atomic():
        for store_id in store_ids:
            store = Location.objects.get(id=store_id)
            print(f"Assigning stock to {store.name}...")
            
            entry = StockEntry.objects.create(
                entry_type='RECEIPT',
                status='COMPLETED',
                to_location=store,
                entry_date=timezone.now(),
                remarks=f"Initial stock assignment for {store.name}",
                purpose="Initial Setup"
            )
            
            from inventory.models.stock_register_model import StockRegister
            register, _ = StockRegister.objects.get_or_create(
                location=store,
                register_number=f"SR-{store.code}-INIT",
                defaults={'register_type': 'CSR' if store.code == 'CENTRAL-STORE' else 'DSR', 'created_by': entry.created_by}
            )

            for item_id in item_ids:
                item = Item.objects.get(id=item_id)
                StockEntryItem.objects.create(
                    stock_entry=entry,
                    item=item,
                    quantity=quantity,
                    stock_register=register,
                    page_number=1
                )
                print(f"  Added 5 units of {item.name} to {register.register_number}")

assign_initial_stock()
