from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Initializes standard Business Roles (Groups) for the AMS'

    def handle(self, *args, **options):
        self.stdout.write("Initializing AMS Business Roles...")

        # 1. Stock In-charge
        stock_incharge_group, created = Group.objects.get_or_create(name='Stock In-charge')
        
        # Permissions for Stock In-charge
        stock_perms = [
            # Inventory View-only
            ('view_location', 'inventory'),
            ('view_category', 'inventory'),
            ('view_person', 'inventory'),
            
            # Stock Entry (CRUD)
            ('add_stockentry', 'inventory'),
            ('change_stockentry', 'inventory'),
            ('view_stockentry', 'inventory'),
            ('delete_stockentry', 'inventory'),
            
            # Stock Record (CRUD)
            ('add_stockrecord', 'inventory'),
            ('change_stockrecord', 'inventory'),
            ('view_stockrecord', 'inventory'),
            ('delete_stockrecord', 'inventory'),
            
            # Stock Allocation (CRUD)
            ('add_stockallocation', 'inventory'),
            ('change_stockallocation', 'inventory'),
            ('view_stockallocation', 'inventory'),
            ('delete_stockallocation', 'inventory'),
            
            # Item Management (CRUD)
            ('add_item', 'inventory'),
            ('change_item', 'inventory'),
            ('view_item', 'inventory'),
            ('delete_item', 'inventory'),
        ]

        # 2. System Admin
        system_admin_group, created = Group.objects.get_or_create(name='System Admin')
        
        # System Admin gets EVERYTHING in inventory
        all_inventory_perms = Permission.objects.filter(content_type__app_label='inventory')
        # And user management
        all_user_perms = Permission.objects.filter(content_type__app_label__in=['auth', 'user_management'])
        
        system_admin_perms = list(all_inventory_perms) + list(all_user_perms)

        # Assign perms to Stock In-charge
        for codename, app_label in stock_perms:
            try:
                perm = Permission.objects.get(codename=codename, content_type__app_label=app_label)
                stock_incharge_group.permissions.add(perm)
            except Permission.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Permission {codename} for {app_label} not found."))

        # Assign perms to System Admin
        system_admin_group.permissions.set(system_admin_perms)

        self.stdout.write(self.style.SUCCESS("AMS Business Roles initialized successfully."))
        self.stdout.write(f" - Created/Updated: 'Stock In-charge'")
        self.stdout.write(f" - Created/Updated: 'System Admin'")
