from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Initializes standard Business Roles (Groups) for the AMS'

    def handle(self, *args, **options):
        self.stdout.write("Initializing AMS Business Roles...")

        # 1. Stock In-charge (Legacy - keeping for compatibility)
        stock_incharge_group, _ = Group.objects.get_or_create(name='Stock In-charge')
        stock_perms = [
            ('view_location', 'inventory'),
            ('view_category', 'inventory'),
            ('view_person', 'inventory'),
            ('add_stockentry', 'inventory'),
            ('change_stockentry', 'inventory'),
            ('view_stockentry', 'inventory'),
            ('delete_stockentry', 'inventory'),
            ('add_stockrecord', 'inventory'),
            ('change_stockrecord', 'inventory'),
            ('view_stockrecord', 'inventory'),
            ('delete_stockrecord', 'inventory'),
            ('add_stockallocation', 'inventory'),
            ('change_stockallocation', 'inventory'),
            ('view_stockallocation', 'inventory'),
            ('delete_stockallocation', 'inventory'),
            ('add_item', 'inventory'),
            ('change_item', 'inventory'),
            ('view_item', 'inventory'),
            ('delete_item', 'inventory'),
            # Inspection Stage 2: Departmental Store Entry
            ('fill_stock_details', 'inventory'),
            ('view_inspectioncertificate', 'inventory'),
            ('view_inspectionitem', 'inventory'),
            ('add_inspectionitem', 'inventory'),
            ('change_inspectionitem', 'inventory'),
            ('view_scoped_distribution', 'inventory'),
            ('manage_stock_register', 'inventory'),
            ('view_stockregister', 'inventory'),
        ]
        self._assign_perms(stock_incharge_group, stock_perms)
        
        # 2. System Admin
        system_admin_group, _ = Group.objects.get_or_create(name='System Admin')
        all_inventory_perms = Permission.objects.filter(content_type__app_label='inventory')
        all_user_perms = Permission.objects.filter(content_type__app_label__in=['auth', 'user_management'])
        system_admin_perms = list(all_inventory_perms) + list(all_user_perms)
        system_admin_group.permissions.set(system_admin_perms)

        # 3. Location Head (Department Manager)
        location_head_group, _ = Group.objects.get_or_create(name='Location Head')
        location_head_perms = [
            ('view_location', 'inventory'),
            ('view_category', 'inventory'),
            ('view_item', 'inventory'),
            ('view_person', 'inventory'),
            ('view_stockentry', 'inventory'),
            ('view_stockrecord', 'inventory'),
            ('view_stockallocation', 'inventory'),
            # Inspection Stage 1 (Initiate) & Final Approval
            ('initiate_inspection', 'inventory'),
            ('add_inspectioncertificate', 'inventory'),
            ('change_inspectioncertificate', 'inventory'),
            ('view_inspectioncertificate', 'inventory'),
            ('view_inspectionitem', 'inventory'),
            ('view_scoped_distribution', 'inventory'),
            ('add_user', 'auth'),
            ('change_user', 'auth'),
            ('view_user', 'auth'),
            ('view_user_accounts_assigned_location', 'user_management'),
            ('view_userprofile', 'user_management'),
            ('change_userprofile', 'user_management'),
            ('view_stockregister', 'inventory'),
        ]
        self._assign_perms(location_head_group, location_head_perms)

        # 4. Central Store Manager (Level 1 Store Stock In-charge)
        central_manager_group, _ = Group.objects.get_or_create(name='Central Store Manager')
        central_manager_perms = [
            ('add_stockentry', 'inventory'),
            ('change_stockentry', 'inventory'),
            ('view_stockentry', 'inventory'),
            ('delete_stockentry', 'inventory'),
            ('add_category', 'inventory'),
            ('change_category', 'inventory'),
            ('view_category', 'inventory'),
            ('add_item', 'inventory'),
            ('change_item', 'inventory'),
            ('view_item', 'inventory'),
            ('delete_item', 'inventory'),
            # Inspection Stage 3: Central Registry Entry & Final Approval
            ('fill_central_register', 'inventory'),
            ('change_inspectioncertificate', 'inventory'),
            ('view_inspectioncertificate', 'inventory'),
            ('view_inspectionitem', 'inventory'),
            ('add_inspectionitem', 'inventory'),
            ('change_inspectionitem', 'inventory'),
            ('view_location', 'inventory'),
            ('view_person', 'inventory'),
            ('view_stockrecord', 'inventory'),  # Crucial for distribution
            ('view_stockallocation', 'inventory'), # Crucial for distribution details
            ('view_global_distribution', 'inventory'),
            ('view_itembatch', 'inventory'),
            ('view_iteminstance', 'inventory'),
            ('manage_stock_register', 'inventory'),
            ('view_stockregister', 'inventory'),
        ]
        self._assign_perms(central_manager_group, central_manager_perms)

        # 5. AD Finance
        ad_finance_group, _ = Group.objects.get_or_create(name='AD Finance')
        ad_finance_perms = [
            ('view_location', 'inventory'),
            ('view_category', 'inventory'),
            ('add_item', 'inventory'),
            ('change_item', 'inventory'),
            ('view_item', 'inventory'),
            ('delete_item', 'inventory'),
            ('view_person', 'inventory'),
            ('view_stockentry', 'inventory'),
            ('view_stockrecord', 'inventory'),
            ('view_stockallocation', 'inventory'),
            # Inspection Stage 4: Finance Review & Final Approval
            ('review_finance', 'inventory'),
            ('change_inspectioncertificate', 'inventory'),
            ('view_inspectioncertificate', 'inventory'),
            ('view_inspectionitem', 'inventory'),
            ('change_inspectionitem', 'inventory'),
            ('view_global_distribution', 'inventory'), # AD Finance needs to see everything
            ('view_itembatch', 'inventory'),
            ('view_iteminstance', 'inventory'),
            ('view_stockregister', 'inventory'),
        ]
        self._assign_perms(ad_finance_group, ad_finance_perms)

        # 6. Auditor (Global View Access)
        auditor_group, _ = Group.objects.get_or_create(name='Auditor')
        
        # Dynamically fetch all "view" permissions from relevant apps
        all_view_perms = Permission.objects.filter(
            codename__startswith='view_',
            content_type__app_label__in=['inventory', 'user_management', 'auth']
        )
        
        # Also include any special view permissions that might not start with view_ (if any)
        # For now, codename__startswith='view_' covers everything requested including global distributions
        
        auditor_group.permissions.set(all_view_perms)

        # 7. Cleanup: Remove Inspector role if it exists
        Group.objects.filter(name='Inspector').delete()


        self.stdout.write(self.style.SUCCESS("AMS Business Roles initialized successfully."))
        self.stdout.write(" - Created/Updated: 'Stock In-charge'")
        self.stdout.write(" - Created/Updated: 'Location Head'")
        self.stdout.write(" - Created/Updated: 'Central Store Manager'")
        self.stdout.write(" - Created/Updated: 'AD Finance'")
        self.stdout.write(" - Created/Updated: 'Auditor' (Dynamic Global View)")
        self.stdout.write(" - Created/Updated: 'System Admin'")

    def _assign_perms(self, group, perms):
        for codename, app_label in perms:
            try:
                perm = Permission.objects.get(codename=codename, content_type__app_label=app_label)
                group.permissions.add(perm)
            except Permission.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Permission {codename} for {app_label} not found."))
