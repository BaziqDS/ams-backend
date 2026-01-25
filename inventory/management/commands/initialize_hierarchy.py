from django.core.management.base import BaseCommand
from inventory.models.location_model import Location, LocationType
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Initializes the institutional location hierarchy with Main University and Central Store'

    def handle(self, *args, **options):
        self.stdout.write("Initializing institutional hierarchy (Strict ID Enforcement)...")
        
        from django.db import transaction
        
        with transaction.atomic():
            if Location.objects.exists():
                self.stdout.write(self.style.WARNING("Existing locations detected. This command is intended for fresh databases to guarantee IDs 1 and 2."))
                root = Location.objects.order_by('id').first()
                self.stdout.write(f"Existing Root: {root.name} (ID: {root.pk})")
            else:
                # 1. Create Main University (Should get ID 1)
                root = Location.objects.create(
                    name='Main University',
                    code='MAIN-UNI',
                    location_type=LocationType.ROOM,
                    is_standalone=True,
                    description='Root institutional location for the university',
                    is_active=True
                )
                self.stdout.write(self.style.SUCCESS(f"Created root location: {root.name} (ID: {root.pk})"))

            # The signal 'auto_create_store_for_standalone' handles Central Store
            # In a fresh DB, root is ID 1, store is ID 2.
            
            # Verify Central Store
            central_store = root.auto_created_store
            if not central_store:
                # If signal didn't run or existing root had no store
                central_store = Location.objects.filter(code='CENTRAL-STORE').first()
                if not central_store:
                    self.stdout.write(self.style.WARNING("Central Store missing. Creating manually..."))
                    central_store = Location.objects.create(
                        name='Central Store',
                        code='CENTRAL-STORE',
                        parent_location=root,
                        location_type=LocationType.STORE,
                        is_store=True,
                        is_auto_created=True,
                        is_main_store=True,
                        is_active=True
                    )
                root.auto_created_store = central_store
                root.save(update_fields=['auto_created_store'])

            self.stdout.write(self.style.SUCCESS(f"Hierarchy complete: {root.name} (ID: {root.pk}) -> {central_store.name} (ID: {central_store.pk})"))

        self.stdout.write(self.style.SUCCESS("Institutional hierarchy initialization finished."))
