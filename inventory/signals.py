from django.db.models.signals import post_save, pre_save, post_delete, m2m_changed
from django.dispatch import receiver
from django.db import transaction
import logging

from .models.location_model import Location, LocationType
from .models.stockentry_model import StockEntry, StockEntryItem
from .models.stock_record_model import StockRecord
from .models.instance_model import ItemInstance
from .models.inspection_model import InspectionCertificate, InspectionItem
from .models.batch_model import ItemBatch
from .models.history_model import MovementHistory, MovementAction

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Location)
def auto_create_store_for_standalone(sender, instance, created, **kwargs):
    """
    Automatically create a main store for standalone locations.
    - Root standalone (ID 1) gets "Central Store" (ID 2).
    - Child standalones (Departments) get stores parented by themselves to ensure UI visibility.
    """
    if created and instance.is_standalone and not instance.is_store:
        is_root = instance.parent_location is None
        
        if is_root:
            store_code = "CENTRAL-STORE"
            store_name = "Central Store"
            # Root store's physical parent is the root location (ID 1)
            store_parent = instance
        else:
            store_code = f"{instance.code}-MAIN-STORE"
            store_name = f"{instance.name} - Main Store"
            # Every departmental store must have its standalone location as parent for visibility
            store_parent = instance

        # Check if a store already exists with this code to be safe
        if Location.objects.filter(code=store_code).exists():
            logger.warning(f"Store with code {store_code} already exists for {instance.name}")
            # Try to link existing store if it's the root case
            if is_root:
                existing_store = Location.objects.get(code=store_code)
                instance.auto_created_store = existing_store
                instance.save(update_fields=['auto_created_store'])
            return

        store = Location.objects.create(
            name=store_name,
            code=store_code,
            parent_location=store_parent,
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
        
        logger.info(f"[SIGNAL] Auto-created hierarchical store {store_name} (parent: {store_parent.name}) for standalone {instance.name}")

def _record_movement_history(instance, entry):
    """
    Records a MovementHistory entry for a StockEntryItem.
    """
    if entry.status != 'COMPLETED':
        return

    from .models.history_model import MovementHistory, MovementAction
    
    action = MovementAction.RECEIVE if entry.entry_type == 'RECEIPT' else MovementAction.ISSUE
    
    # Check if this movement was already recorded for this entry/item to avoid duplicates
    if MovementHistory.objects.filter(stock_entry=entry, item=instance.item, batch=instance.batch).exists():
        # If instances exist, check if each instance has a movement for this entry
        if instance.instances.exists():
            for inst in instance.instances.all():
                if not MovementHistory.objects.filter(stock_entry=entry, instance=inst).exists():
                    MovementHistory.objects.create(
                        item=instance.item,
                        instance=inst,
                        batch=instance.batch,
                        action=action,
                        from_location=entry.from_location,
                        to_location=entry.to_location,
                        stock_entry=entry,
                        performed_by=entry.created_by,
                        remarks=entry.remarks
                    )
    else:
        # Initial recording for this item/batch in this entry
        if instance.instances.exists():
            for inst in instance.instances.all():
                MovementHistory.objects.create(
                    item=instance.item,
                    instance=inst,
                    batch=instance.batch,
                    action=action,
                    from_location=entry.from_location,
                    to_location=entry.to_location,
                    stock_entry=entry,
                    performed_by=entry.created_by,
                    remarks=entry.remarks
                )
        else:
            MovementHistory.objects.create(
                item=instance.item,
                batch=instance.batch,
                action=action,
                from_location=entry.from_location,
                to_location=entry.to_location,
                quantity=instance.quantity,
                stock_entry=entry,
                performed_by=entry.created_by,
                remarks=entry.remarks
            )

@receiver(post_save, sender=StockEntryItem)
def process_stock_entry_item(sender, instance, created, **kwargs):
    """
    Handles item-level stock records (in-transit or physical) when an item is saved.
    Also handles linked receipt creation for inter-store movements.
    """
    stock_entry = instance.stock_entry
    
    # 1. Linked RECEIPT creation (ISSUE -> RECEIPT bridge)
    # CRITICAL: Do NOT create receipts for DRAFT entries. Wait until finalized.
    if stock_entry.entry_type == 'ISSUE' and stock_entry.to_location and not stock_entry.reference_entry and stock_entry.status != 'DRAFT':
        # INTER-STORE: Force PENDING_ACK regardless of Issue status
        # This ensures the Handshake is mandatory.
        
        linked_receipt, r_created = StockEntry.objects.get_or_create(
            reference_entry=stock_entry,
            entry_type='RECEIPT',
            defaults={
                'entry_number': f"R-{stock_entry.entry_number}",
                'entry_date': stock_entry.entry_date,
                'from_location': stock_entry.from_location,
                'to_location': stock_entry.to_location,
                'status': 'PENDING_ACK',
                'remarks': f"Auto-generated receipt for {stock_entry.entry_number}. {stock_entry.remarks or ''}",
                'purpose': stock_entry.purpose,
                'inspection_certificate': stock_entry.inspection_certificate,
                'created_by': stock_entry.created_by
            }
        )
        
        receipt_item, i_created = StockEntryItem.objects.get_or_create(
            stock_entry=linked_receipt,
            item=instance.item,
            batch=instance.batch,
            defaults={
                'quantity': instance.quantity,
                'stock_register': instance.stock_register,
                'page_number': instance.page_number
            }
        )
        if not i_created:
            receipt_item.quantity = instance.quantity
            receipt_item.save()

        # Sync instances if they were already added (e.g. bulk create or retrospective save)
        if instance.instances.exists():
            receipt_item.instances.set(instance.instances.all())
        
        logger.info(f"[SIGNAL] Linked RECEIPT item synced for {stock_entry.entry_number}")

    # 2. Trigger individual item processing (In-Transit / Stock Completion)
    process_single_stock_item(instance)

def process_single_stock_item(instance):
    """
    Helper to process a single StockEntryItem's effect on StockRecord.
    Handles PENDING_ACK (In-Transit) and COMPLETED (Balance Update).
    """
    entry = instance.stock_entry
    item = instance.item
    qty = instance.quantity
    batch = instance.batch
    from_loc = entry.from_location
    to_loc = entry.to_location

    with transaction.atomic():
        # A. Handle "In Transit" (Source side)
        if entry.entry_type == 'ISSUE' and from_loc:
            # If entry is PENDING_ACK: We need it in-transit
            if entry.status == 'PENDING_ACK' and not instance.is_in_transit_recorded:
                StockRecord.update_balance(item, from_loc, batch=batch, in_transit_change=qty)
                # Mark instances as IN_TRANSIT
                if instance.instances.exists():
                    instance.instances.all().update(status='IN_TRANSIT')
                instance.is_in_transit_recorded = True
                instance.save(update_fields=['is_in_transit_recorded'])
                logger.info(f"[SIGNAL] Recorded In-Transit: {item.name} at {from_loc.name} (Instances marked IN_TRANSIT)")
            
            # If entry is CANCELLED/REJECTED: We reverse in-transit if it was recorded
            elif entry.status in ['CANCELLED', 'REJECTED'] and instance.is_in_transit_recorded:
                StockRecord.update_balance(item, from_loc, batch=batch, in_transit_change=-qty)
                # Revert instances to AVAILABLE
                if instance.instances.exists():
                    instance.instances.all().update(status='AVAILABLE')
                instance.is_in_transit_recorded = False
                instance.save(update_fields=['is_in_transit_recorded'])
                logger.info(f"[SIGNAL] Reversed In-Transit: {item.name} at {from_loc.name} (Instances reverted to AVAILABLE)")

        # B. Handle "Physical Completion" (Store or Allocation)
        if entry.status == 'COMPLETED' and not instance.is_stock_recorded:
            if entry.entry_type == 'ISSUE' and from_loc:
                # Is this an allocation (to person or non-store)?
                is_allocation = entry.issued_to or (entry.to_location and not entry.to_location.is_store)
                
                if is_allocation:
                    # ALLOCATION logic: Decreases availability, increases allocated count, stays in total
                    StockRecord.update_balance(item, from_loc, batch=batch, allocated_change=qty)
                    
                    # Create Allocation record
                    from .models.allocation_model import StockAllocation
                    StockAllocation.objects.create(
                        item=item,
                        batch=batch,
                        source_location=from_loc,
                        quantity=qty,
                        allocated_to_person=entry.issued_to,
                        allocated_to_location=entry.to_location if (entry.to_location and not entry.to_location.is_store) else None,
                        stock_entry=entry,
                        allocated_by=entry.created_by
                    )

                    # Update instances
                    if instance.instances.exists():
                        instance.instances.all().update(status='ALLOCATED')
                    
                    # Record Movement History for Allocation
                    from .models.history_model import MovementHistory, MovementAction
                    if instance.instances.exists():
                        for inst in instance.instances.all():
                            MovementHistory.objects.create(
                                item=item,
                                instance=inst,
                                batch=batch,
                                action=MovementAction.ALLOCATE,
                                from_location=from_loc,
                                stock_entry=entry,
                                performed_by=entry.created_by,
                                remarks=f"Allocated via {entry.entry_number}"
                            )
                    else:
                        MovementHistory.objects.create(
                            item=item,
                            batch=batch,
                            action=MovementAction.ALLOCATE,
                            from_location=from_loc,
                            quantity=qty,
                            stock_entry=entry,
                            performed_by=entry.created_by,
                            remarks=f"Allocated via {entry.entry_number}"
                        )

                    logger.info(f"[SIGNAL] ALLOCATED: {qty} {item.name} from {from_loc.name}")
                else:
                    # NORMAL ISSUE (to another store): Decreases total quantity
                    StockRecord.update_balance(item, from_loc, quantity_change=-qty, batch=batch)
                    logger.info(f"[SIGNAL] COMPLETED ISSUE (TRANSFER): Decremented {qty} {item.name} from {from_loc.name}")

                # Deduct in-transit if it was previously recorded
                if instance.is_in_transit_recorded:
                    StockRecord.update_balance(item, from_loc, batch=batch, in_transit_change=-qty)
                    instance.is_in_transit_recorded = False
            
            elif entry.entry_type == 'RECEIPT' and to_loc:
                # Is this a return from an allocation (Person or Non-Store)?
                is_return = entry.issued_to or (entry.from_location and not entry.from_location.is_store)
                
                if is_return:
                    # RETURN logic: Decrements allocated_quantity, moves back to 'Available' but stays in 'Total'
                    StockRecord.update_balance(item, to_loc, batch=batch, allocated_change=-qty)
                    
                    # Update StockAllocation records (Status -> RETURNED)
                    from .models.allocation_model import StockAllocation, AllocationStatus
                    from django.utils import timezone
                    
                    alloc_filter = {
                        'item': item,
                        'batch': batch,
                        'source_location': to_loc,
                        'status': AllocationStatus.ALLOCATED
                    }
                    if entry.issued_to:
                        alloc_filter['allocated_to_person'] = entry.issued_to
                    else:
                        alloc_filter['allocated_to_location'] = entry.from_location
                    
                    # Find active allocations for this target and reduce them
                    active_allocs = StockAllocation.objects.filter(**alloc_filter).order_by('allocated_at')
                    remaining_to_return = qty
                    for alloc in active_allocs:
                        if remaining_to_return <= 0: break
                        
                        return_qty = min(alloc.quantity, remaining_to_return)
                        if return_qty == alloc.quantity:
                            alloc.status = AllocationStatus.RETURNED
                            alloc.return_date = timezone.now()
                        else:
                            # Split or decrement allocation (for simplicity, we decrement in this MVP)
                            alloc.quantity -= return_qty
                        
                        remaining_to_return -= return_qty
                        alloc.save()

                    # Update instances
                    if instance.instances.exists():
                        instance.instances.all().update(current_location=to_loc, status='AVAILABLE')
                    
                    # Record Movement History for Return
                    from .models.history_model import MovementHistory, MovementAction
                    if instance.instances.exists():
                        for inst in instance.instances.all():
                            MovementHistory.objects.create(
                                item=item,
                                instance=inst,
                                batch=batch,
                                action=MovementAction.RETURN,
                                to_location=to_loc,
                                stock_entry=entry,
                                performed_by=entry.created_by,
                                remarks=f"Returned via {entry.entry_number}"
                            )
                    else:
                        MovementHistory.objects.create(
                            item=item,
                            batch=batch,
                            action=MovementAction.RETURN,
                            to_location=to_loc,
                            quantity=qty,
                            stock_entry=entry,
                            performed_by=entry.created_by,
                            remarks=f"Returned via {entry.entry_number}"
                        )

                    logger.info(f"[SIGNAL] RETURNED: {qty} {item.name} back to {to_loc.name} from {'person' if entry.issued_to else 'non-store'}")
                else:
                    # NORMAL RECEIPT (from another store): Increments total quantity
                    StockRecord.update_balance(item, to_loc, quantity_change=qty, batch=batch)
                    
                    # Update instances location and set to AVAILABLE
                    if instance.instances.exists():
                        instance.instances.all().update(current_location=to_loc, status='AVAILABLE')
                    
                    logger.info(f"[SIGNAL] COMPLETED RECEIPT (TRANSFER): Incremented {qty} {item.name} in {to_loc.name}")
            
            instance.is_stock_recorded = True
            instance.save(update_fields=['is_stock_recorded', 'is_in_transit_recorded'])

        # C. Handle "Cancellation" (Reversals)
        elif entry.status == 'CANCELLED' and instance.is_stock_recorded:
             if entry.entry_type == 'ISSUE' and from_loc:
                is_allocation = entry.issued_to or (entry.to_location and not entry.to_location.is_store)
                if is_allocation:
                    # Reverse allocation
                    StockRecord.update_balance(item, from_loc, batch=batch, allocated_change=-qty)
                    # Mark allocation records collectively as returned or just delete if it's a hard cancel?
                    # Let's mark as returned/cancelled
                    from .models.allocation_model import StockAllocation, AllocationStatus
                    StockAllocation.objects.filter(stock_entry=entry, item=item, batch=batch).update(status=AllocationStatus.RETURNED)
                    
                    if instance.instances.exists():
                        instance.instances.all().update(status='AVAILABLE')
                else:
                    # Reverse physical decrement
                    StockRecord.update_balance(item, from_loc, quantity_change=qty, batch=batch)
                
                instance.is_stock_recorded = False
                instance.save(update_fields=['is_stock_recorded'])
                logger.info(f"[SIGNAL] CANCELLED ISSUE: Reversed stock/allocation for {item.name}")

    # Helper function to record history (Called OUTSIDE atomic block for persistence or after)
    _record_movement_history(instance, entry)

@receiver(post_save, sender=StockEntry)
def process_stock_on_status_change(sender, instance, created, **kwargs):
    """
    Trigger stock updates for all items when a StockEntry status changes.
    """
    with transaction.atomic():
        # Ensure we have the latest items and process their stock effects
        for entry_item in instance.items.all():
            process_single_stock_item(entry_item)
            
            # CRITICAL: If an ISSUE is moving out of DRAFT, we need to create the linked RECEIPT item
            # which was suppressed in process_stock_entry_item
            if instance.status != 'DRAFT' and instance.entry_type == 'ISSUE' and instance.to_location and not instance.reference_entry:
                # We reuse the logic from process_stock_entry_item implicitly by re-triggering the signal logic
                # or we can explicitly call a helper. Let's just re-save the item to trigger the signal
                # but wait, process_stock_entry_item is a post_save on StockEntryItem.
                # If we just change the StockEntry status, the items aren't saved again.
                # So we manually handle it here for reliability.
                target_status = instance.status if instance.status == 'PENDING_ACK' else 'COMPLETED'
                
                linked_receipt, r_created = StockEntry.objects.get_or_create(
                    reference_entry=instance,
                    entry_type='RECEIPT',
                    defaults={
                        'entry_number': f"R-{instance.entry_number}",
                        'entry_date': instance.entry_date,
                        'from_location': instance.from_location,
                        'to_location': instance.to_location,
                        'status': 'PENDING_ACK',
                        'remarks': f"Auto-generated receipt for {instance.entry_number}. {instance.remarks or ''}",
                        'purpose': instance.purpose,
                        'inspection_certificate': instance.inspection_certificate,
                        'created_by': instance.created_by
                    }
                )
                
                # Create/Update linked item in the receipt
                receipt_item, i_created = StockEntryItem.objects.get_or_create(
                    stock_entry=linked_receipt,
                    item=entry_item.item,
                    batch=entry_item.batch,
                    defaults={'quantity': entry_item.quantity}
                )
                if not i_created:
                    receipt_item.quantity = entry_item.quantity
                    receipt_item.save()

                if entry_item.instances.exists():
                    receipt_item.instances.set(entry_item.instances.all())
        
        # Sync bridge status (RECEIPT or RETURN completion marks Parent ISSUE completion)
        if instance.status == 'COMPLETED' and instance.entry_type in ['RECEIPT', 'RETURN'] and instance.reference_entry:
            parent = instance.reference_entry
            if parent.status != 'COMPLETED':
                parent.status = 'COMPLETED'
                parent.save(update_fields=['status'])
                logger.info(f"[SIGNAL] Status Sync: Completed parent ISSUE {parent.entry_number}")

        # Propagation: parent ISSUE cancellation cancels linked RECEIPT
        if instance.status == 'CANCELLED' and instance.entry_type == 'ISSUE':
            children = StockEntry.objects.filter(reference_entry=instance)
            for child in children:
                if child.status != 'CANCELLED':
                    child.status = 'CANCELLED'
                    child.cancellation_reason = f"Parent {instance.entry_number} was cancelled. {instance.cancellation_reason or ''}"
                    child.cancelled_by = instance.cancelled_by
                    child.cancelled_at = instance.cancelled_at
                    child.save(update_fields=['status', 'cancellation_reason', 'cancelled_by', 'cancelled_at'])
                    logger.info(f"[SIGNAL] Propagation: Cancelled linked RECEIPT {child.entry_number}")

@receiver(post_delete, sender=StockEntry)
def auto_delete_linked_entries(sender, instance, **kwargs):
    """
    Automatically delete linked RECEIPT entries when the parent ISSUE is deleted.
    Prevents orphaned pending receipts in the receiver's list.
    """
    # Only delete linked receipts if they are not yet completed
    # (though COMPLETED entries shouldn't ideally be deleted)
    linked_entries = StockEntry.objects.filter(reference_entry=instance)
    for entry in linked_entries:
        if entry.status in ['PENDING_ACK', 'DRAFT']: # Safety check
            entry.delete()
            logger.info(f"[SIGNAL] Auto-deleted orphaned linked RECEIPT {entry.entry_number}")

@receiver(post_delete, sender=StockEntryItem)

def reverse_stock_on_item_delete(sender, instance, **kwargs):
    """
    Reverses the effect of a StockEntryItem on StockRecord if it's deleted.
    Crucial for correcting "In Transit" and physical balances upon deletion.
    """
    entry = instance.stock_entry
    item = instance.item
    qty = instance.quantity
    batch = instance.batch
    from_loc = entry.from_location
    to_loc = entry.to_location

    with transaction.atomic():
        # 1. Reverse "In Transit" if it was recorded
        if instance.is_in_transit_recorded and from_loc:
            StockRecord.update_balance(item, from_loc, batch=batch, in_transit_change=-qty)
            logger.info(f"[SIGNAL] Reversed In-Transit for deleted item: {item.name}")

        # 2. Reverse "Physical Stock" if it was recorded
        if instance.is_stock_recorded:
            if entry.entry_type == 'ISSUE' and from_loc:
                StockRecord.update_balance(item, from_loc, quantity_change=qty, batch=batch)
            elif entry.entry_type == 'RECEIPT' and to_loc:
                StockRecord.update_balance(item, to_loc, quantity_change=-qty, batch=batch)
            elif entry.entry_type in ['TRANSFER', 'CORRECTION']:
                if from_loc: StockRecord.update_balance(item, from_loc, qty, batch)
                if to_loc: StockRecord.update_balance(item, to_loc, -qty, batch)
            logger.info(f"[SIGNAL] Reversed COMPLETED stock for deleted item: {item.name}")

@receiver(m2m_changed, sender=StockEntryItem.instances.through)
def process_m2m_instances(sender, instance, action, pk_set, **kwargs):
    """
    Updates ItemInstance locations when they are added to a COMPLETED or PARTIALLY_ACCEPTED StockEntryItem.
    """
    if action == "post_add" and instance.stock_entry.status == 'COMPLETED':
        to_loc = instance.stock_entry.to_location
        if to_loc:
            ItemInstance.objects.filter(pk__in=pk_set).update(current_location=to_loc)
            logger.info(f"Updated {len(pk_set)} instances to location {to_loc.name}")

@receiver(post_save, sender=InspectionCertificate)
def auto_generate_stock_from_inspection(sender, instance, created, **kwargs):
    """
    Automatically create stock entries when an Inspection Certificate is COMPLETED.
    """
    if instance.status != 'COMPLETED':
        return

    # Guard against double creation
    if StockEntry.objects.filter(inspection_certificate=instance, entry_type='RECEIPT').exists():
        return

    with transaction.atomic():
        # 1. Setup Stores
        root_location = Location.objects.order_by('id').first()
        if not root_location or not root_location.auto_created_store:
            logger.error(f"[SIGNAL] Failed to generate stock entry: Root store not found.")
            raise ValueError("Root store not found. Cannot complete inspection.")
            
        central_store = root_location.auto_created_store
        target_store = instance.department.auto_created_store
        
        if not target_store:
            logger.error(f"[SIGNAL] Failed to generate stock entry: Target store for {instance.department.name} not found.")
            raise ValueError(f"Target store for {instance.department.name} not found. Cannot complete inspection.")

        # 2. Create Initial RECEIPT entry in Central Store
        receipt = StockEntry.objects.create(
            entry_type='RECEIPT',
            to_location=central_store,
            status='COMPLETED',
            remarks=f"Generated from Inspection Certificate: {instance.contract_no}",
            purpose=f"Initial stock receipt for Contract/Invoice: {instance.contract_no}",
            inspection_certificate=instance,
            created_by=instance.finance_reviewed_by or instance.initiated_by
        )

        items_to_move = []
        for i_item in instance.items.filter(accepted_quantity__gt=0):
            # Find or Create Batch
            batch = None
            if i_item.batch_number:
                batch, _ = ItemBatch.objects.get_or_create(
                    item=i_item.item,
                    batch_number=i_item.batch_number,
                    defaults={
                        'expiry_date': i_item.expiry_date,
                        'created_by': receipt.created_by
                    }
                )
            
            # Prepare page number
            try:
                page_no = int(i_item.central_register_page_no) if i_item.central_register_page_no and i_item.central_register_page_no.isdigit() else 0
            except (ValueError, TypeError):
                page_no = 0

            # Create StockEntryItem for Receipt
            sei = StockEntryItem.objects.create(
                stock_entry=receipt,
                item=i_item.item,
                batch=batch,
                quantity=i_item.accepted_quantity,
                stock_register=i_item.central_register,
                page_number=page_no
            )

            # 2.1 Handle Individual Tracking (Instance Generation)
            tracking_type = i_item.item.category.get_tracking_type()
            if tracking_type == 'INDIVIDUAL':
                instances = []
                for idx in range(i_item.accepted_quantity):
                    # Auto-generate serial if empty
                    serial = f"SN-{i_item.item.code}-{receipt.id}-{idx+1}"
                    instance_obj = ItemInstance.objects.create(
                        item=i_item.item,
                        batch=batch,
                        serial_number=serial,
                        current_location=central_store,
                        status='AVAILABLE',
                        created_by=receipt.created_by
                    )
                    instances.append(instance_obj)
                
                # Link instances to the entry item
                sei.instances.set(instances)

            items_to_move.append((
                i_item.item, 
                batch, 
                i_item.accepted_quantity, 
                (instances if tracking_type == 'INDIVIDUAL' else []),
                i_item.central_register,
                page_no
            ))

        logger.info(f"[SIGNAL] Logic: Auto-created RECEIPT {receipt.entry_number} for Inspection {instance.contract_no}")

        # 3. Create ISSUE entry if it's for a Specific Department (Hierarchy Level != 0)
        if instance.department.hierarchy_level != 0:
            # Check if target is same as central (redundant check but safe)
            if target_store.id == central_store.id:
                return

            issue = StockEntry.objects.create(
                entry_type='ISSUE',
                from_location=central_store,
                to_location=target_store,
                status='COMPLETED',
                remarks=f"Inter-store transfer from Central to {instance.department.name} for Contract: {instance.contract_no}",
                purpose=f"Departmental distribution for Contract: {instance.contract_no}",
                inspection_certificate=instance,
                created_by=receipt.created_by
            )

            for item, batch, qty, instances, item_central_reg, item_page_no in items_to_move:
                issue_item = StockEntryItem.objects.create(
                    stock_entry=issue,
                    item=item,
                    batch=batch,
                    quantity=qty,
                    stock_register=item_central_reg,
                    page_number=item_page_no
                )
                if instances:
                    issue_item.instances.set(instances)
            
            logger.info(f"[SIGNAL] Logic: Auto-created ISSUE {issue.entry_number} for distribution to {instance.department.name}")
            # Note: The linked RECEIPT for the target store will be automatically created
            # by the post_save signal on StockEntryItem (process_stock_entry_item) 
            # when the COMPLETED ISSUE items are saved.
