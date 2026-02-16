from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Location, Category, Item, InspectionCertificate, InspectionItem, InspectionStage, InspectionDocument, StockRegister

class InspectionWorkflowTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        
        # 1. Setup Root Standalone Location (L1)
        # The signal auto_generate_stock_from_inspection looks for the first location as root
        self.root_dept = Location.objects.create(
            name='Central Administration',
            code='ROOT',
            location_type='OFFICE',
            is_standalone=True,
            created_by=self.user
        )
        
        # 2. Setup Sub-Department (L2)
        self.dept = Location.objects.create(
            name='Test Department',
            code='DEPT01',
            location_type='OFFICE',
            is_standalone=True,
            parent_location=self.root_dept,
            created_by=self.user
        )
        
        # Refresh from DB to get auto-created stores from signals
        self.root_dept.refresh_from_db()
        self.dept.refresh_from_db()
        
        # 3. Setup Stock Registers
        self.central_reg = StockRegister.objects.create(
            register_number='CR-001',
            register_type='CSR',
            store=self.root_dept.auto_created_store,
            created_by=self.user
        )
        
        self.dept_reg = StockRegister.objects.create(
            register_number='DR-001',
            register_type='CSR',
            store=self.dept.auto_created_store,
            created_by=self.user
        )

        self.cat = Category.objects.create(name='Electronics', code='ELEC')
        self.item = Item.objects.create(
            name='Test Item',
            code='ITEM01',
            category=self.cat,
            acct_unit='NOS'
        )

    def test_workflow_stages(self):
        # 1. Initiation (starts as DRAFT)
        ic = InspectionCertificate.objects.create(
            contract_no='CON-001',
            contractor_name='John Doe',
            indenter='NED UET',
            indent_no='IND-001',
            department=self.dept,
            initiated_by=self.user
        )
        self.assertEqual(ic.stage, InspectionStage.DRAFT)

        # Create items
        ii = InspectionItem.objects.create(
            inspection_certificate=ic,
            item=self.item,
            item_description='Test Processor',
            tendered_quantity=10,
            accepted_quantity=10,
            unit_price=500.00,
            central_register=self.central_reg,
            central_register_no='CR-001',
            central_register_page_no='1'
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

        # 4. To Finance
        ic.stage = InspectionStage.FINANCE_REVIEW
        ic.central_store_filled_by = self.user
        ic.central_store_filled_at = timezone.now()
        ic.save()

        # 5. Complete (This triggers the stock generation signal)
        ic.stage = InspectionStage.COMPLETED
        ic.status = 'COMPLETED'
        ic.finance_reviewed_by = self.user
        ic.finance_reviewed_at = timezone.now()
        ic.save()

        self.assertEqual(ic.status, 'COMPLETED')
        self.assertTrue(ic.stock_entries.exists())

    def test_inspection_documents(self):
        ic = InspectionCertificate.objects.create(
            contract_no='CON-DOC-001',
            contractor_name='Test Contractor',
            indenter='NED UET',
            indent_no='IND-DOC-001',
            department=self.dept
        )
        
        from django.core.files.uploadedfile import SimpleUploadedFile
        file_content = b"test file content"
        uploaded_file = SimpleUploadedFile("test_image.jpg", file_content, content_type="image/jpeg")
        
        doc = InspectionDocument.objects.create(
            inspection_certificate=ic,
            file=uploaded_file,
            label="Test Image"
        )
        
        self.assertEqual(ic.documents.count(), 1)
        self.assertEqual(ic.documents.first().label, "Test Image")
        self.assertTrue(ic.documents.first().file.name.startswith('inspection_docs/'))

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

    def test_serializer_form_data_handling(self):
        """
        Verify that the serializer handles JSON-encoded 'items' string (as sent by FormData).
        """
        import json
        from .serializers.inspection_serializer import InspectionCertificateSerializer
        
        data = {
            'contract_no': 'CON-FORM-001',
            'contractor_name': 'Form Contractor',
            'indenter': 'NED UET',
            'indent_no': 'IND-FORM-001',
            'department': self.dept.id,
            'items': json.dumps([{
                'item_description': 'Form Item',
                'tendered_quantity': 5,
                'accepted_quantity': 5,
                'unit_price': 100.00
            }])
        }
        
        serializer = InspectionCertificateSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        instance = serializer.save()
        self.assertEqual(instance.items.count(), 1)
        self.assertEqual(instance.items.first().item_description, 'Form Item')
