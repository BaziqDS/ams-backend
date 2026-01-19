from django.db.models.signals import post_save
from django.dispatch import receiver
from .models.location_model import Location, LocationType
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
