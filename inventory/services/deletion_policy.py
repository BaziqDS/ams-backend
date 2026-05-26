import time

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import OperationalError, transaction
from django.db.models import ProtectedError

from inventory.models import (
    Category,
    Item,
    Location,
    StockEntry,
    StockEntryItem,
    StockRegister,
)


class DeletionBlocked(Exception):
    def __init__(self, blockers):
        self.blockers = list(blockers)
        super().__init__("Delete is blocked by existing dependencies.")


SQLITE_LOCK_RETRY_DELAYS = (0.15, 0.35, 0.75)


def _is_database_locked_error(exc):
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


def _has(queryset_or_manager):
    return queryset_or_manager.exists()


def _has_related(instance, related_name, to_attr=None):
    if to_attr and hasattr(instance, to_attr):
        return bool(getattr(instance, to_attr))
    prefetched = getattr(instance, '_prefetched_objects_cache', {})
    if related_name in prefetched:
        return bool(prefetched[related_name])
    return _has(getattr(instance, related_name).all())


def category_delete_blockers(category):
    blockers = []
    if _has(category.subcategories.all()):
        blockers.append("This category has subcategories.")
    if _has(category.items.all()):
        blockers.append("This category is linked to inventory items.")
    if _has(category.depreciation_asset_classes.all()):
        blockers.append("This category is linked to depreciation asset classes.")
    return blockers


def item_delete_blockers(item):
    blockers = []
    if _has(item.stock_records.all()):
        blockers.append("This item has inventory balance or distribution history.")
    if StockEntryItem.objects.filter(item=item).exists():
        blockers.append("This item is used in stock entries.")
    if _has(item.instances.all()):
        blockers.append("This item has item instances.")
    if _has(item.batches.all()):
        blockers.append("This item has item batches.")
    if _has(item.allocations.all()):
        blockers.append("This item is used in stock allocations.")
    if _has(item.inspection_items.all()):
        blockers.append("This item is linked to inspection certificates.")
    if _has(item.movements.all()):
        blockers.append("This item has movement history.")
    if _has(item.fixed_asset_entries.all()):
        blockers.append("This item is capitalized in the fixed asset register.")
    if _has(item.maintenance_plans.all()) or _has(item.maintenance_work_orders.all()) or _has(item.maintenance_meter_readings.all()):
        blockers.append("This item is linked to maintenance records.")
    return blockers


def _direct_location_blockers(location, label="This location"):
    blockers = []
    if _has(location.assigned_users.all()):
        blockers.append(f"{label} is assigned to users.")
    if _has(location.persons.all()):
        blockers.append(f"{label} is linked to people records.")
    if _has(location.inspections.all()):
        blockers.append(f"{label} is linked to inspections.")
    if _has(location.stock_records.all()):
        blockers.append(f"{label} has inventory balance or distribution history.")
    if _has(location.stock_registers.all()):
        blockers.append(f"{label} has stock registers.")
    if _has(location.outgoing_entries.all()) or _has(location.incoming_entries.all()):
        blockers.append(f"{label} is used in stock entries.")
    if _has(location.outgoing_allocations.all()) or _has(location.incoming_allocations.all()):
        blockers.append(f"{label} is used in stock allocations.")
    if _has(location.instances.all()):
        blockers.append(f"{label} has item instances.")
    if _has(location.outgoing_movements.all()) or _has(location.incoming_movements.all()):
        blockers.append(f"{label} has movement history.")
    if _has(location.maintenance_work_orders.all()) or _has(location.maintenance_meter_readings.all()):
        blockers.append(f"{label} is linked to maintenance records.")
    return blockers


def location_delete_blockers(location):
    blockers = []
    auto_store_id = location.auto_created_store_id
    child_locations = location.child_locations.all()
    non_auto_children = child_locations.exclude(pk=auto_store_id) if auto_store_id else child_locations

    if _has(non_auto_children):
        blockers.append("This location has sub-locations.")

    blockers.extend(_direct_location_blockers(location))

    if auto_store_id:
        auto_store = location.auto_created_store
        store_blockers = _direct_location_blockers(auto_store, label="The auto-created main store")
        if _has(auto_store.child_locations.all()):
            store_blockers.append("The auto-created main store has child locations.")
        blockers.extend(store_blockers)

    return blockers


def stock_register_delete_blockers(register):
    blockers = []
    if _has(register.source_items.all()) or _has(register.dest_items.all()):
        blockers.append("This stock register is used in stock entry lines.")
    if _has(register.inspection_items_source.all()) or _has(register.inspection_items_central.all()):
        blockers.append("This stock register is used in inspection records.")
    return blockers


def stock_entry_delete_blockers(entry):
    blockers = []
    if entry.status != "DRAFT":
        blockers.append("This stock entry is an audit record; cancel it instead of deleting it.")
    if _has_related(entry, "correction_entries", "prefetched_correction_entries"):
        blockers.append("This stock entry has linked generated entries.")
    if _has_related(entry, "correction_requests", "prefetched_correction_requests") or _has_related(entry, "generated_by_correction_requests"):
        blockers.append("This stock entry is linked to correction requests.")
    if _has_related(entry, "movements") or _has_related(entry, "allocations"):
        blockers.append("This stock entry has movement or allocation history.")
    return blockers


def get_delete_blockers(instance):
    if isinstance(instance, Category):
        return category_delete_blockers(instance)
    if isinstance(instance, Item):
        return item_delete_blockers(instance)
    if isinstance(instance, Location):
        return location_delete_blockers(instance)
    if isinstance(instance, StockRegister):
        return stock_register_delete_blockers(instance)
    if isinstance(instance, StockEntry):
        return stock_entry_delete_blockers(instance)
    return []


def can_delete(instance):
    return not get_delete_blockers(instance)


def delete_with_policy(instance):
    blockers = get_delete_blockers(instance)
    if blockers:
        raise DeletionBlocked(blockers)

    for delay in (*SQLITE_LOCK_RETRY_DELAYS, None):
        try:
            with transaction.atomic():
                instance.delete()
            return
        except OperationalError as exc:
            if _is_database_locked_error(exc) and delay is not None:
                time.sleep(delay)
                continue
            if _is_database_locked_error(exc):
                raise DeletionBlocked(["The database is temporarily locked. Please retry in a moment."])
            raise
        except ProtectedError:
            raise DeletionBlocked(["This record is linked to existing records and cannot be deleted."])
        except DjangoValidationError as exc:
            if hasattr(exc, "messages"):
                raise DeletionBlocked(exc.messages)
            raise DeletionBlocked([str(exc)])
