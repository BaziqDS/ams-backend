from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from inventory.models import StockEntry
from notifications.services import notify_stock_entry_pending_ack


@receiver(post_save, sender=StockEntry)
def create_pending_ack_notification(sender, instance: StockEntry, created: bool, **kwargs):
    if not created:
        return
    if instance.status != "PENDING_ACK" or instance.entry_type not in {"RECEIPT", "RETURN"}:
        return

    transaction.on_commit(lambda: notify_stock_entry_pending_ack(instance, actor=instance.created_by))
