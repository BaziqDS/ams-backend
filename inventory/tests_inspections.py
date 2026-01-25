from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Location, Category, Item, InspectionCertificate, InspectionItem, InspectionStage

class InspectionWorkflowTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.dept = Location.objects.create(
            name='Test Department',
            code='DEPT01',
            location_type='OFFICE',
            is_standalone=True
        )
        self.cat = Category.objects.create(name='Electronics', code='ELEC')
        self.item = Item.objects.create(
            name='Test Item',
            code='ITEM01',
            category=self.cat,
            acct_unit='NOS'
        )

    def test_workflow_stages(self):
        # 1. Initiation
        ic = InspectionCertificate.objects.create(
            contract_no='CON-001',
            contractor_name='John Doe',
            indenter='NED UET',
            indent_no='IND-001',
            department=self.dept,
            initiated_by=self.user
        )
        self.assertEqual(ic.stage, InspectionStage.INITIATED)

        # Create items
        ii = InspectionItem.objects.create(
            inspection_certificate=ic,
            item_description='Test Processor',
            tendered_quantity=10,
            accepted_quantity=10,
            unit_price=500.00
        )

        # 2. To Stock Details
        ic.stage = InspectionStage.STOCK_DETAILS
        ic.save()
        self.assertEqual(ic.stage, InspectionStage.STOCK_DETAILS)

        # 3. To Central Register
        ic.stage = InspectionStage.CENTRAL_REGISTER
        ic.stock_filled_by = self.user
        ic.stock_filled_at = timezone.now()
        ic.save()

        # Link item
        ii.item = self.item
        ii.central_register_no = 'CR-001'
        ii.save()

        # 4. To Finance
        ic.stage = InspectionStage.FINANCE_REVIEW
        ic.central_store_filled_by = self.user
        ic.central_store_filled_at = timezone.now()
        ic.save()

        # 5. Complete
        ic.stage = InspectionStage.COMPLETED
        ic.status = 'COMPLETED'
        ic.finance_reviewed_by = self.user
        ic.finance_reviewed_at = timezone.now()
        ic.save()

        self.assertEqual(ic.status, 'COMPLETED')

    def test_rejection(self):
        ic = InspectionCertificate.objects.create(
            contract_no='CON-002',
            contractor_name='Jane Doe',
            indenter='NED UET',
            indent_no='IND-002',
            department=self.dept,
            initiated_by=self.user
        )
        
        ic.stage = InspectionStage.REJECTED
        ic.status = 'REJECTED'
        ic.rejection_reason = 'Faulty items'
        ic.rejected_by = self.user
        ic.save()

        self.assertEqual(ic.status, 'REJECTED')
        self.assertEqual(ic.rejection_reason, 'Faulty items')
