from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models.location_model import Location, LocationType
from .models.stockentry_model import StockEntry
from .models.stock_record_model import StockRecord
from .models.instance_model import ItemInstance
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Location)
def auto_create_store_for_standalone(sender, instance, created, **kwargs):
    """
    Automatically create a main store for standalone locations.
    """
    if created and instance.is_standalone and not instance.is_store:
        store_code = f"{instance.code}-MAIN-STORE"
        store_name = f"{instance.name} - Main Store"

        # Check if a store already exists with this code to be safe
        if Location.objects.filter(code=store_code).exists():
            logger.warning(f"Store with code {store_code} already exists for {instance.name}")
            return

        store = Location.objects.create(
            name=store_name,
            code=store_code,
            parent_location=instance,
            location_type=LocationType.STORE,
            is_store=True,
            is_auto_created=True,
            is_main_store=True,
            is_standalone=False,
            description=f"Auto-created main store for {instance.name}",
            address=instance.address,
            in_charge=instance.in_charge,
            contact_number=instance.contact_number,
            is_active=True,
            created_by=instance.created_by
        )

        instance.auto_created_store = store
        instance.save(update_fields=['auto_created_store'])
        
        logger.info(f"[SIGNAL] Auto-created main store {store_name} for standalone location {instance.name}")

from django.db.models.signals import post_save, m2m_changed
from django.dispatch import receiver
from django.db import transaction
from .models.location_model import Location, LocationType
from .models.stockentry_model import StockEntry, StockEntryItem
from .models.stock_record_model import StockRecord
from .models.instance_model import ItemInstance
import logging

logger = logging.getLogger(__name__)

# ... (auto_create_store_for_standalone remains same)

@receiver(post_save, sender=StockEntryItem)
def process_stock_entry_item(sender, instance, created, **kwargs):
    """
    Updates StockRecord and Item global quantity when a StockEntryItem is saved
    AND its parent StockEntry is COMPLETED.
    
    Unidirectional Processing:
    - ISSUE only decrements source
    - RECEIPT only increments destination
    - OTHER (RECEPT from None, ISSUE to None) handles global qty
    """
    stock_entry = instance.stock_entry
    item = instance.item
    qty = instance.quantity
    batch = instance.batch
    from_loc = stock_entry.from_location
    to_loc = stock_entry.to_location
    issued_to = stock_entry.issued_to

    # 3. Create linked receipt for inter-store ISSUE (even if PENDING_ACK)
    if stock_entry.entry_type == 'ISSUE' and to_loc and not stock_entry.reference_entry:
        # Check if a linked receipt already exists or create it
        # Status defaults to PENDING_ACK if the issue is PENDING_ACK
        target_status = stock_entry.status if stock_entry.status in ['PENDING_ACK', 'DRAFT'] else 'COMPLETED'
        
        linked_receipt, r_created = StockEntry.objects.get_or_create(
            reference_entry=stock_entry,
            entry_type='RECEIPT',
            defaults={
                'entry_date': stock_entry.entry_date,
                'from_location': from_loc,
                'to_location': to_loc,
                'status': target_status,
                'remarks': f"Auto-generated receipt for {stock_entry.entry_number}",
                'purpose': stock_entry.purpose,
                'created_by': stock_entry.created_by
            }
        )
        
        # Create linked item in the receipt
        receipt_item, i_created = StockEntryItem.objects.get_or_create(
            stock_entry=linked_receipt,
            item=item,
            batch=batch,
            defaults={'quantity': qty}
        )
        if not i_created:
            receipt_item.quantity = qty
            receipt_item.save()

        if instance.instances.exists():
            receipt_item.instances.set(instance.instances.all())
        
        logger.info(f"[SIGNAL] Linked RECEIPT item synced for ISSUE {stock_entry.entry_number}")

    # Now handle stock updates ONLY if COMPLETED
    if stock_entry.status != 'COMPLETED':
        return

    if not created:
        return

    with transaction.atomic():
        # 1. Processing for ISSUE (Sender)
        if stock_entry.entry_type == 'ISSUE':
            if from_loc:
                StockRecord.update_balance(
                    item=item,
                    location=from_loc,
                    quantity_change=-qty,
                    batch=batch
                )
                logger.info(f"[SIGNAL] ISSUE: Decremented {qty} {item.name} from {from_loc.name}")
            
            # Global adjustment: if it's leaving the system (to person or external)
            if to_loc is None or issued_to is not None:
                item.total_quantity -= qty
                item.save(update_fields=['total_quantity'])
                logger.info(f"[SIGNAL] ISSUE: Decreased global quantity of {item.name} by {qty}")

        # 2. Processing for RECEIPT (Receiver)
        elif stock_entry.entry_type == 'RECEIPT':
            if to_loc:
                StockRecord.update_balance(
                    item=item,
                    location=to_loc,
                    quantity_change=qty,
                    batch=batch
                )
                logger.info(f"[SIGNAL] RECEIPT: Incremented {qty} {item.name} in {to_loc.name}")
            
            # Global adjustment: if it's coming from external
            if from_loc is None:
                item.total_quantity += qty
                item.save(update_fields=['total_quantity'])
                logger.info(f"[SIGNAL] RECEIPT: Increased global quantity of {item.name} by {qty}")

@receiver(post_save, sender=StockEntry)
def process_stock_on_status_change(sender, instance, created, **kwargs):
    """
    Trigger stock updates for all items when a StockEntry is marked as COMPLETED.
    """
    # Only process if status is COMPLETED
    if instance.status != 'COMPLETED':
        return

    # 1. Update stock for all items in this entry
    with transaction.atomic():
        for item_entry in instance.items.all():
            # We call the same logic that StockEntryItem signal uses, but manually
            item = item_entry.item
            qty = item_entry.quantity
            batch = item_entry.batch
            from_loc = instance.from_location
            to_loc = instance.to_location
            issued_to = instance.issued_to

            if instance.entry_type == 'ISSUE':
                if from_loc:
                    StockRecord.update_balance(item, from_loc, -qty, batch)
                if to_loc is None or issued_to is not None:
                    item.total_quantity -= qty
                    item.save(update_fields=['total_quantity'])
            
            elif instance.entry_type == 'RECEIPT':
                if to_loc:
                    StockRecord.update_balance(item, to_loc, qty, batch)
                if from_loc is None:
                    item.total_quantity += qty
                    item.save(update_fields=['total_quantity'])
        
        # 2. Sync status to linked entries
        # If this is a RECEIPT being acknowledged, ensure the parent ISSUE is also COMPLETED
        if instance.entry_type == 'RECEIPT' and instance.reference_entry:
            parent = instance.reference_entry
            if parent.status != 'COMPLETED':
                parent.status = 'COMPLETED'
                parent.save(update_fields=['status']) # Triggers this signal for the parent
                logger.info(f"[SIGNAL] Sync: Marked parent ISSUE {parent.entry_number} as COMPLETED")

        # If this is an ISSUE (e.g. manually corrected to COMPLETED), ensure children are COMPLETED
        elif instance.entry_type == 'ISSUE':
            children = StockEntry.objects.filter(reference_entry=instance, entry_type='RECEIPT')
            for child in children:
                if child.status != 'COMPLETED':
                    child.status = 'COMPLETED'
                    child.save(update_fields=['status'])
                    logger.info(f"[SIGNAL] Sync: Marked child RECEIPT {child.entry_number} as COMPLETED")

@receiver(m2m_changed, sender=StockEntryItem.instances.through)
def process_m2m_instances(sender, instance, action, pk_set, **kwargs):
    """
    Updates ItemInstance locations when they are added to a COMPLETED StockEntryItem.
    """
    if action == "post_add" and instance.stock_entry.status == 'COMPLETED':
        to_loc = instance.stock_entry.to_location
        if to_loc:
            ItemInstance.objects.filter(pk__in=pk_set).update(current_location=to_loc)
            logger.info(f"Updated {len(pk_set)} instances to location {to_loc.name}")


