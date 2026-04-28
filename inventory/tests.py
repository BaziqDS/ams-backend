# pyright: reportAttributeAccessIssue=false
import json
from datetime import timedelta

from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import TemporaryUploadedFile
from django.http import QueryDict
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inventory.models import (
    Category,
    CategoryType,
    InspectionCertificate,
    InspectionItem,
    InspectionStage,
    Item,
    ItemBatch,
    ItemInstance,
    Location,
    LocationType,
    Person,
    AllocationStatus,
    StockAllocation,
    StockRecord,
    StockEntry,
    StockEntryItem,
    StockRegister,
    TrackingType,
)
from inventory.serializers.inspection_serializer import InspectionCertificateSerializer

from ams.permissions_manifest import MODULES, READ_PERMS
from user_management.services.capability_service import resolve_selections_to_codenames
from user_management.signals import EXPLICIT_PERMISSION_IMPLICATIONS


class CategoryDomainPermissionBootstrapTests(TestCase):
    def test_category_domain_permissions_exist(self):
        perms = set(
            Permission.objects.filter(content_type__app_label='inventory').values_list('codename', flat=True)
        )

        self.assertTrue(
            {
                'view_categories',
                'create_categories',
                'edit_categories',
                'delete_categories',
            }.issubset(perms)
        )


class ItemDomainPermissionBootstrapTests(TestCase):
    def test_item_domain_permissions_exist(self):
        perms = set(
            Permission.objects.filter(content_type__app_label='inventory').values_list('codename', flat=True)
        )

        self.assertTrue(
            {
                'view_items',
                'create_items',
                'edit_items',
                'delete_items',
            }.issubset(perms)
        )


class StockEntryDomainPermissionBootstrapTests(TestCase):
    def test_stock_entry_domain_permissions_exist(self):
        perms = set(
            Permission.objects.filter(content_type__app_label='inventory').values_list('codename', flat=True)
        )

        self.assertTrue(
            {
                'view_stock_entries',
                'create_stock_entries',
                'edit_stock_entries',
                'delete_stock_entries',
            }.issubset(perms)
        )

    def test_stock_entries_manifest_declares_dependencies(self):
        resolved = resolve_selections_to_codenames({'stock-entries': 'manage'})

        self.assertIn('inventory.view_stock_entries', resolved)
        self.assertIn('inventory.create_stock_entries', resolved)
        self.assertIn('inventory.edit_stock_entries', resolved)
        self.assertIn('inventory.acknowledge_stockentry', resolved)
        self.assertIn('inventory.view_items', resolved)
        self.assertIn('inventory.view_locations', resolved)
        self.assertIn('inventory.view_person', resolved)
        self.assertIn('inventory.view_stockregister', resolved)
        self.assertIn('inventory.view_stockallocation', resolved)
        self.assertNotIn('inventory.delete_stock_entries', resolved)

    def test_stock_entries_read_perm_declared(self):
        self.assertIn('stock-entries', MODULES)
        self.assertEqual(READ_PERMS.get('stock-entries'), ['inventory.view_stock_entries'])

    def test_stock_entry_permission_implications_declared(self):
        self.assertEqual(EXPLICIT_PERMISSION_IMPLICATIONS.get('create_stock_entries'), ['view_stock_entries'])
        self.assertEqual(EXPLICIT_PERMISSION_IMPLICATIONS.get('edit_stock_entries'), ['view_stock_entries'])
        self.assertEqual(EXPLICIT_PERMISSION_IMPLICATIONS.get('delete_stock_entries'), ['view_stock_entries'])


class InspectionCertificateSerializerContractTests(TestCase):
    def test_multipart_create_data_with_file_does_not_deepcopy_upload(self):
        department = Location.objects.create(
            name='Inspection Multipart Department',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        upload = TemporaryUploadedFile('delivery.pdf', 'application/pdf', 0, 'utf-8')

        data = QueryDict('', mutable=True)
        data.update({
            'date': timezone.now().date().isoformat(),
            'contract_no': 'IC-MULTIPART-001',
            'contract_date': timezone.now().date().isoformat(),
            'contractor_name': 'Multipart Supplier',
            'contractor_address': 'Block B',
            'indenter': 'Multipart Indenter',
            'indent_no': 'IND-MULTI-1',
            'department': str(department.id),
            'date_of_delivery': timezone.now().date().isoformat(),
            'delivery_type': 'FULL',
            'remarks': 'Multipart contract',
            'inspected_by': 'Multipart Inspector',
            'date_of_inspection': timezone.now().date().isoformat(),
            'consignee_name': 'Multipart Consignee',
            'consignee_designation': 'Manager',
            'items': json.dumps([
                {
                    'item': None,
                    'item_description': 'Multipart line item',
                    'item_specifications': 'Specs',
                    'tendered_quantity': 1,
                    'accepted_quantity': 0,
                    'rejected_quantity': 0,
                    'unit_price': '0.00',
                    'remarks': '',
                }
            ]),
        })
        data.setlist('documents[0]', [upload])

        try:
            serializer = InspectionCertificateSerializer(data=data)

            self.assertTrue(serializer.is_valid(), serializer.errors)
        finally:
            upload.close()

    def test_serializer_exposes_named_workflow_actors_and_related_stock_entries(self):
        department = Location.objects.create(
            name='Inspection Serializer Department',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        stock_user = User.objects.create_user(username='stock.actor', password='pw')
        central_user = User.objects.create_user(username='central.actor', password='pw')
        finance_user = User.objects.create_user(username='finance.actor', password='pw')
        initiated_user = User.objects.create_user(username='initiated.actor', password='pw')

        certificate = InspectionCertificate.objects.create(
            date=timezone.now().date(),
            contract_no='IC-SERIALIZER-001',
            contract_date=timezone.now().date(),
            contractor_name='Serializer Supplier',
            contractor_address='Block A',
            indenter='Serializer Indenter',
            indent_no='IND-SER-1',
            department=department,
            date_of_delivery=timezone.now().date(),
            delivery_type='FULL',
            remarks='Serializer contract',
            inspected_by='QA Inspector',
            date_of_inspection=timezone.now().date(),
            consignee_name='Serializer Consignee',
            consignee_designation='Manager',
            stage=InspectionStage.FINANCE_REVIEW,
            status='IN_PROGRESS',
            initiated_by=initiated_user,
            stock_filled_by=stock_user,
            central_store_filled_by=central_user,
            finance_reviewed_by=finance_user,
        )

        StockEntry.objects.create(
            entry_type='RECEIPT',
            status='COMPLETED',
            inspection_certificate=certificate,
            created_by=finance_user,
        )

        data = InspectionCertificateSerializer(certificate).data

        self.assertEqual(data['initiated_by_name'], 'initiated.actor')
        self.assertEqual(data['stock_filled_by_name'], 'stock.actor')
        self.assertEqual(data['central_store_filled_by_name'], 'central.actor')
        self.assertEqual(data['finance_reviewed_by_name'], 'finance.actor')
        self.assertIsNone(data['rejected_by_name'])
        self.assertEqual(len(data['stock_entries']), 1)
        self.assertEqual(data['stock_entries'][0]['entry_type'], 'RECEIPT')
        self.assertIn('entry_number', data['stock_entries'][0])

    def test_initiated_create_starts_at_stock_details_for_non_root_departments(self):
        root = Location.objects.create(
            name='Inspection Initiated Root',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        department = Location.objects.create(
            name='Inspection Initiated Department',
            location_type=LocationType.DEPARTMENT,
            parent_location=root,
            is_standalone=True,
        )

        serializer = InspectionCertificateSerializer(data={
            'date': timezone.now().date().isoformat(),
            'contract_no': 'IC-INIT-001',
            'contract_date': timezone.now().date().isoformat(),
            'contractor_name': 'Initiated Supplier',
            'contractor_address': 'Block C',
            'indenter': 'Initiated Indenter',
            'indent_no': 'IND-INIT-1',
            'department': department.id,
            'date_of_delivery': timezone.now().date().isoformat(),
            'delivery_type': 'FULL',
            'remarks': '',
            'inspected_by': 'Initiated Inspector',
            'date_of_inspection': timezone.now().date().isoformat(),
            'consignee_name': 'Initiated Consignee',
            'consignee_designation': 'Manager',
            'is_initiated': True,
            'items': [
                {
                    'item': None,
                    'item_description': 'Initiated line item',
                    'item_specifications': '',
                    'tendered_quantity': 1,
                    'accepted_quantity': 1,
                    'rejected_quantity': 0,
                    'unit_price': '10.00',
                    'remarks': '',
                }
            ],
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        certificate = serializer.save()

        self.assertEqual(certificate.stage, InspectionStage.STOCK_DETAILS)
        self.assertEqual(certificate.status, 'IN_PROGRESS')

    def test_initiated_create_skips_stock_details_for_root_departments(self):
        department = Location.objects.create(
            name='Inspection Root Department',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )

        serializer = InspectionCertificateSerializer(data={
            'date': timezone.now().date().isoformat(),
            'contract_no': 'IC-INIT-ROOT-001',
            'contract_date': timezone.now().date().isoformat(),
            'contractor_name': 'Root Supplier',
            'contractor_address': 'Block R',
            'indenter': 'Root Indenter',
            'indent_no': 'IND-INIT-ROOT-1',
            'department': department.id,
            'date_of_delivery': timezone.now().date().isoformat(),
            'delivery_type': 'FULL',
            'remarks': '',
            'inspected_by': 'Root Inspector',
            'date_of_inspection': timezone.now().date().isoformat(),
            'consignee_name': 'Root Consignee',
            'consignee_designation': 'Manager',
            'is_initiated': True,
            'items': [
                {
                    'item': None,
                    'item_description': 'Root line item',
                    'item_specifications': '',
                    'tendered_quantity': 1,
                    'accepted_quantity': 1,
                    'rejected_quantity': 0,
                    'unit_price': '10.00',
                    'remarks': '',
                }
            ],
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        certificate = serializer.save()

        self.assertEqual(certificate.stage, InspectionStage.CENTRAL_REGISTER)
        self.assertEqual(certificate.status, 'IN_PROGRESS')

    def test_non_initiated_create_stays_draft(self):
        department = Location.objects.create(
            name='Inspection Draft Department',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )

        serializer = InspectionCertificateSerializer(data={
            'date': timezone.now().date().isoformat(),
            'contract_no': 'IC-DRAFT-001',
            'contract_date': timezone.now().date().isoformat(),
            'contractor_name': 'Draft Supplier',
            'contractor_address': 'Block D',
            'indenter': 'Draft Indenter',
            'indent_no': 'IND-DRAFT-1',
            'department': department.id,
            'date_of_delivery': timezone.now().date().isoformat(),
            'delivery_type': 'FULL',
            'remarks': '',
            'inspected_by': 'Draft Inspector',
            'date_of_inspection': timezone.now().date().isoformat(),
            'consignee_name': 'Draft Consignee',
            'consignee_designation': 'Manager',
            'items': [
                {
                    'item': None,
                    'item_description': 'Draft line item',
                    'item_specifications': '',
                    'tendered_quantity': 1,
                    'accepted_quantity': 1,
                    'rejected_quantity': 0,
                    'unit_price': '10.00',
                    'remarks': '',
                }
            ],
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        certificate = serializer.save()

        self.assertEqual(certificate.stage, InspectionStage.DRAFT)
        self.assertEqual(certificate.status, 'DRAFT')


class InspectionCertificateApiScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = Location.objects.create(
            name='Inspection Scope Root',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        cls.electrical = Location.objects.create(
            name='Inspection Scope Electrical',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.csit = Location.objects.create(
            name='Inspection Scope CSIT',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.electrical_certificate = cls._certificate('IC-SCOPE-EE', cls.electrical)
        cls.csit_certificate = cls._certificate('IC-SCOPE-CSIT', cls.csit)

    @classmethod
    def _certificate(cls, contract_no, department):
        return InspectionCertificate.objects.create(
            date=timezone.now().date(),
            contract_no=contract_no,
            contract_date=timezone.now().date(),
            contractor_name='Scope Supplier',
            contractor_address='Block A',
            indenter='Scope Indenter',
            indent_no=f'IND-{contract_no}',
            department=department,
            date_of_delivery=timezone.now().date(),
            delivery_type='FULL',
            remarks='',
            inspected_by='Scope Inspector',
            date_of_inspection=timezone.now().date(),
            consignee_name='Scope Consignee',
            consignee_designation='Manager',
        )

    def setUp(self):
        self.client = APIClient()

    def _perm(self, codename):
        return Permission.objects.get(content_type__app_label='inventory', codename=codename)

    def _make_user(self, username, assigned_location):
        user = User.objects.create_user(username=username, password='pw')
        user.user_permissions.add(self._perm('view_inspectioncertificate'))
        user.profile.assigned_locations.add(assigned_location)
        return user

    def _rows(self, response):
        data = response.data
        if isinstance(data, dict) and 'results' in data:
            return data['results']
        return data

    def test_root_assigned_user_sees_all_inspections_without_distribution_permissions(self):
        user = self._make_user('inspection_root_scope', self.root)

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/inspections/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.electrical_certificate.id, returned_ids)
        self.assertIn(self.csit_certificate.id, returned_ids)

    def test_standalone_assigned_user_sees_only_own_location_inspections(self):
        user = self._make_user('inspection_standalone_scope', self.electrical)

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/inspections/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.electrical_certificate.id, returned_ids)
        self.assertNotIn(self.csit_certificate.id, returned_ids)


class InspectionRootWorkflowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.root = Location.objects.create(
            name='Root Campus',
            code='ROOT-CAMPUS',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        self.central_register = StockRegister.objects.create(
            register_number='ROOT-CENTRAL-1',
            store=self.root.auto_created_store,
            register_type='CSR',
        )

        asset_parent = Category.objects.create(
            name='Root Workflow Assets',
            code='ROOT-WF-ASSET',
            category_type=CategoryType.FIXED_ASSET,
        )
        asset_child = Category.objects.create(
            name='Root Workflow Individual Assets',
            code='ROOT-WF-IND',
            parent_category=asset_parent,
            tracking_type=TrackingType.INDIVIDUAL,
        )
        self.item = Item.objects.create(
            name='Root Workflow Laptop',
            category=asset_child,
            acct_unit='Nos',
        )

    def _perm(self, codename):
        return Permission.objects.get(content_type__app_label='inventory', codename=codename)

    def _make_user(self, username, *perm_codenames):
        user = User.objects.create_user(username=username, password='pw')
        user.profile.assigned_locations.add(self.root)
        for codename in perm_codenames:
            user.user_permissions.add(self._perm(codename))
        return user

    def _make_certificate(self, stage):
        certificate = InspectionCertificate.objects.create(
            date=timezone.now().date(),
            contract_no=f'IC-ROOT-WF-{stage}',
            contract_date=timezone.now().date(),
            contractor_name='Root Workflow Supplier',
            contractor_address='Block A',
            indenter='Root Workflow Indenter',
            indent_no=f'IND-ROOT-WF-{stage}',
            department=self.root,
            date_of_delivery=timezone.now().date(),
            delivery_type='FULL',
            remarks='',
            inspected_by='Root Workflow Inspector',
            date_of_inspection=timezone.now().date(),
            consignee_name='Root Workflow Consignee',
            consignee_designation='Manager',
            stage=stage,
            status='IN_PROGRESS',
        )
        InspectionItem.objects.create(
            inspection_certificate=certificate,
            item=self.item,
            item_description='Root workflow line item',
            tendered_quantity=1,
            accepted_quantity=1,
            rejected_quantity=0,
            unit_price='10.00',
            central_register=self.central_register,
            central_register_no=self.central_register.register_number,
            central_register_page_no='11',
        )
        return certificate

    def test_root_departments_can_submit_to_finance_without_stock_details_register(self):
        certificate = self._make_certificate(InspectionStage.CENTRAL_REGISTER)
        user = self._make_user(
            'root.workflow.central',
            'view_inspectioncertificate',
            'change_inspectioncertificate',
            'fill_central_register',
        )

        self.client.force_authenticate(user=user)
        response = self.client.post(
            f'/api/inventory/inspections/{certificate.id}/submit_to_finance_review/'
        )

        self.assertEqual(response.status_code, 200, response.data)
        certificate.refresh_from_db()
        self.assertEqual(certificate.stage, InspectionStage.FINANCE_REVIEW)

    def test_root_departments_can_complete_without_stock_details_register(self):
        certificate = self._make_certificate(InspectionStage.FINANCE_REVIEW)
        user = self._make_user(
            'root.workflow.finance',
            'view_inspectioncertificate',
            'change_inspectioncertificate',
            'review_finance',
        )

        self.client.force_authenticate(user=user)
        response = self.client.post(f'/api/inventory/inspections/{certificate.id}/complete/')

        self.assertEqual(response.status_code, 200, response.data)
        certificate.refresh_from_db()
        self.assertEqual(certificate.stage, InspectionStage.COMPLETED)
        self.assertEqual(certificate.status, 'COMPLETED')


class InspectionTrackingIntakeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = Location.objects.create(
            name='Tracking Intake University',
            code='TRACK-ROOT',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        cls.department = Location.objects.create(
            name='Tracking Intake Department',
            code='TRACK-DEPT',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.user = User.objects.create_superuser(username='tracking.intake', password='pw')
        cls.user.user_permissions.add(
            Permission.objects.get(content_type__app_label='inventory', codename='view_inspectioncertificate'),
            Permission.objects.get(content_type__app_label='inventory', codename='review_finance'),
        )
        cls.user.profile.assigned_locations.add(cls.root)
        cls.register = StockRegister.objects.create(
            register_number='TRACK-REG-1',
            store=cls.root.auto_created_store,
            register_type='CENTRAL',
            created_by=cls.user,
        )

        cls.asset_parent = Category.objects.create(
            name='Tracking Intake Assets',
            code='TRACK-ASSET',
            category_type=CategoryType.FIXED_ASSET,
        )
        cls.asset_child = Category.objects.create(
            name='Tracking Intake Individual Assets',
            code='TRACK-IND',
            parent_category=cls.asset_parent,
            category_type=CategoryType.FIXED_ASSET,
            tracking_type=TrackingType.INDIVIDUAL,
        )
        cls.asset_item = Item.objects.create(
            name='Tracked Processor',
            code='TRACK-CPU',
            category=cls.asset_child,
            acct_unit='unit',
        )

        cls.perishable_parent = Category.objects.create(
            name='Tracking Intake Perishables',
            code='TRACK-PER',
            category_type=CategoryType.PERISHABLE,
        )
        cls.perishable_child = Category.objects.create(
            name='Tracking Intake Chemicals',
            code='TRACK-CHEM',
            parent_category=cls.perishable_parent,
            category_type=CategoryType.PERISHABLE,
            tracking_type=TrackingType.QUANTITY,
        )
        cls.perishable_item = Item.objects.create(
            name='Tracked Chemical',
            code='TRACK-CHEM-ITM',
            category=cls.perishable_child,
            acct_unit='bottle',
        )

        cls.consumable_parent = Category.objects.create(
            name='Tracking Intake Consumables',
            code='TRACK-CON',
            category_type=CategoryType.CONSUMABLE,
        )
        cls.consumable_child = Category.objects.create(
            name='Tracking Intake Stationery',
            code='TRACK-STAPLE',
            parent_category=cls.consumable_parent,
            category_type=CategoryType.CONSUMABLE,
            tracking_type=TrackingType.QUANTITY,
        )
        cls.consumable_item = Item.objects.create(
            name='Tracked Stapler Box',
            code='TRACK-STAPLER',
            category=cls.consumable_child,
            acct_unit='box',
        )

    def _certificate(self, contract_no):
        return InspectionCertificate.objects.create(
            date=timezone.now().date(),
            contract_no=contract_no,
            contract_date=timezone.now().date(),
            contractor_name='Tracking Supplier',
            contractor_address='Block T',
            indenter='Tracking Indenter',
            indent_no=f'IND-{contract_no}',
            department=self.department,
            date_of_delivery=timezone.now().date(),
            delivery_type='FULL',
            remarks='Tracking intake',
            inspected_by='Tracking Inspector',
            date_of_inspection=timezone.now().date(),
            consignee_name='Tracking Consignee',
            consignee_designation='Manager',
            stage=InspectionStage.FINANCE_REVIEW,
            status='IN_PROGRESS',
            initiated_by=self.user,
            stock_filled_by=self.user,
            central_store_filled_by=self.user,
        )

    def test_individual_inspection_intake_creates_batchless_instances(self):
        certificate = self._certificate('TRACK-IC-IND-001')
        InspectionItem.objects.create(
            inspection_certificate=certificate,
            item=self.asset_item,
            item_description='Processors',
            tendered_quantity=2,
            accepted_quantity=2,
            rejected_quantity=0,
            unit_price=100,
            central_register=self.register,
            central_register_page_no='1',
            stock_register=self.register,
            stock_register_page_no='2',
            batch_number='IGNORED-FOR-INDIVIDUAL',
            expiry_date=timezone.now().date(),
        )

        certificate.status = 'COMPLETED'
        certificate.stage = InspectionStage.COMPLETED
        certificate.finance_reviewed_by = self.user
        certificate.finance_reviewed_at = timezone.now()
        certificate.save()

        instances = ItemInstance.objects.filter(item=self.asset_item)
        self.assertEqual(instances.count(), 2)
        self.assertNotIn('batch', {field.name for field in ItemInstance._meta.get_fields()})
        self.assertFalse(ItemBatch.objects.filter(item=self.asset_item).exists())
        receipt_item = StockEntryItem.objects.get(
            stock_entry__inspection_certificate=certificate,
            stock_entry__entry_type='RECEIPT',
            stock_entry__from_location__isnull=True,
            item=self.asset_item,
        )
        self.assertEqual(receipt_item.accepted_quantity, 2)
        self.assertEqual(receipt_item.stock_register, self.register)
        self.assertEqual(receipt_item.page_number, 1)
        self.assertEqual(receipt_item.accepted_instances.count(), 2)

    def test_perishable_quantity_inspection_persists_manufactured_and_expiry_dates_to_batch(self):
        certificate = self._certificate('TRACK-IC-PER-002')
        manufactured_date = timezone.now().date() - timedelta(days=30)
        expiry_date = timezone.now().date() + timedelta(days=180)
        InspectionItem.objects.create(
            inspection_certificate=certificate,
            item=self.perishable_item,
            item_description='Chemicals',
            tendered_quantity=3,
            accepted_quantity=3,
            rejected_quantity=0,
            unit_price=10,
            central_register=self.register,
            central_register_page_no='1',
            stock_register=self.register,
            stock_register_page_no='2',
            batch_number='TRACK-BATCH-001',
            manufactured_date=manufactured_date,
            expiry_date=expiry_date,
        )

        certificate.status = 'COMPLETED'
        certificate.stage = InspectionStage.COMPLETED
        certificate.finance_reviewed_by = self.user
        certificate.finance_reviewed_at = timezone.now()
        certificate.save()

        batch = ItemBatch.objects.get(item=self.perishable_item, batch_number='TRACK-BATCH-001')
        self.assertEqual(batch.manufactured_date, manufactured_date)
        self.assertEqual(batch.expiry_date, expiry_date)

    def test_batch_listing_exposes_quantity_for_item_and_location_scopes(self):
        batch = ItemBatch.objects.create(
            item=self.perishable_item,
            batch_number='TRACK-BATCH-003',
            created_by=self.user,
        )
        StockRecord.objects.create(
            item=self.perishable_item,
            batch=batch,
            location=self.root.auto_created_store,
            quantity=2,
        )
        StockRecord.objects.create(
            item=self.perishable_item,
            batch=batch,
            location=self.department.auto_created_store,
            quantity=3,
        )

        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.get('/api/inventory/item-batches/', {
            'item': self.perishable_item.id,
        })

        self.assertEqual(response.status_code, 200)
        payload = response.data['results'] if isinstance(response.data, dict) and 'results' in response.data else response.data
        batch_row = next(row for row in payload if row['batch_number'] == 'TRACK-BATCH-003')
        self.assertEqual(batch_row['quantity'], 5)
        self.assertEqual(batch_row['available_quantity'], 5)
        self.assertEqual(batch_row['allocated_quantity'], 0)
        self.assertEqual(batch_row['in_transit_quantity'], 0)

        scoped_response = client.get('/api/inventory/item-batches/', {
            'item': self.perishable_item.id,
            'location': self.department.auto_created_store.id,
        })

        self.assertEqual(scoped_response.status_code, 200)
        scoped_payload = scoped_response.data['results'] if isinstance(scoped_response.data, dict) and 'results' in scoped_response.data else scoped_response.data
        scoped_batch_row = next(row for row in scoped_payload if row['batch_number'] == 'TRACK-BATCH-003')
        self.assertEqual(scoped_batch_row['quantity'], 3)
        self.assertEqual(scoped_batch_row['available_quantity'], 3)

    def test_perishable_quantity_inspection_requires_batch_number_before_completion(self):
        certificate = self._certificate('TRACK-IC-PER-001')
        InspectionItem.objects.create(
            inspection_certificate=certificate,
            item=self.perishable_item,
            item_description='Chemicals',
            tendered_quantity=3,
            accepted_quantity=3,
            rejected_quantity=0,
            unit_price=10,
            central_register=self.register,
            central_register_page_no='1',
            stock_register=self.register,
            stock_register_page_no='2',
        )

        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.post(f'/api/inventory/inspections/{certificate.id}/complete/')

        self.assertEqual(response.status_code, 400)
        self.assertIn('batch number', response.data['detail'].lower())

    def test_consumable_quantity_inspection_auto_generates_tracking_lot(self):
        certificate = self._certificate('TRACK-IC-CON-001')
        inspection_item = InspectionItem.objects.create(
            inspection_certificate=certificate,
            item=self.consumable_item,
            item_description='Staplers',
            tendered_quantity=10,
            accepted_quantity=10,
            rejected_quantity=0,
            unit_price=10,
            central_register=self.register,
            central_register_page_no='1',
            stock_register=self.register,
            stock_register_page_no='2',
        )

        certificate.status = 'COMPLETED'
        certificate.stage = InspectionStage.COMPLETED
        certificate.finance_reviewed_by = self.user
        certificate.finance_reviewed_at = timezone.now()
        certificate.save()

        inspection_item.refresh_from_db()
        self.assertEqual(inspection_item.batch_number, f'{certificate.contract_no}-L{inspection_item.id}')

        batch = ItemBatch.objects.get(item=self.consumable_item, batch_number=inspection_item.batch_number)
        self.assertTrue(
            StockEntryItem.objects.filter(
                stock_entry__inspection_certificate=certificate,
                item=self.consumable_item,
                batch=batch,
            ).exists()
        )
        receipt_item = StockEntryItem.objects.get(
            stock_entry__inspection_certificate=certificate,
            stock_entry__entry_type='RECEIPT',
            stock_entry__from_location__isnull=True,
            item=self.consumable_item,
            batch=batch,
        )
        self.assertEqual(receipt_item.accepted_quantity, 10)
        self.assertEqual(receipt_item.stock_register, self.register)
        self.assertEqual(receipt_item.page_number, 1)

    def test_inspection_item_distribution_endpoint_returns_quantity_lot_breakdown(self):
        certificate = self._certificate('TRACK-IC-CON-002')
        inspection_item = InspectionItem.objects.create(
            inspection_certificate=certificate,
            item=self.consumable_item,
            item_description='Staplers',
            tendered_quantity=10,
            accepted_quantity=10,
            rejected_quantity=0,
            unit_price=10,
            central_register=self.register,
            central_register_page_no='1',
            stock_register=self.register,
            stock_register_page_no='2',
        )

        certificate.status = 'COMPLETED'
        certificate.stage = InspectionStage.COMPLETED
        certificate.finance_reviewed_by = self.user
        certificate.finance_reviewed_at = timezone.now()
        certificate.save()

        inspection_item.refresh_from_db()
        batch = ItemBatch.objects.get(item=self.consumable_item, batch_number=inspection_item.batch_number)

        StockRecord.objects.filter(item=self.consumable_item, batch=batch).delete()
        StockAllocation.objects.filter(item=self.consumable_item, batch=batch).delete()

        StockRecord.objects.create(
            item=self.consumable_item,
            batch=batch,
            location=self.root.auto_created_store,
            quantity=4,
            allocated_quantity=0,
            in_transit_quantity=1,
        )
        StockRecord.objects.create(
            item=self.consumable_item,
            batch=batch,
            location=self.department.auto_created_store,
            quantity=6,
            allocated_quantity=2,
            in_transit_quantity=0,
        )
        person = Person.objects.create(name='Lab Attendant', designation='Attendant')
        person.standalone_locations.add(self.department)
        allocation = StockAllocation.objects.create(
            item=self.consumable_item,
            batch=batch,
            source_location=self.department.auto_created_store,
            quantity=2,
            allocated_to_person=person,
            status=AllocationStatus.ALLOCATED,
            allocated_by=self.user,
        )

        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.get(
            f'/api/inventory/inspections/{certificate.id}/items/{inspection_item.id}/distribution/'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['inspection']['id'], certificate.id)
        self.assertEqual(response.data['inspection_item']['id'], inspection_item.id)
        self.assertEqual(response.data['inspection_item']['tracking_lot'], inspection_item.batch_number)
        self.assertEqual(response.data['batch']['id'], batch.id)
        self.assertEqual(response.data['batch']['batch_number'], inspection_item.batch_number)

        root_unit = next(unit for unit in response.data['units'] if unit['id'] == self.root.id)
        self.assertEqual(root_unit['totalQuantity'], 4)
        self.assertEqual(root_unit['inTransitQuantity'], 1)
        self.assertEqual(root_unit['stores'][0]['batchId'], batch.id)
        self.assertEqual(root_unit['stores'][0]['batchNumber'], inspection_item.batch_number)

        department_unit = next(unit for unit in response.data['units'] if unit['id'] == self.department.id)
        self.assertEqual(department_unit['totalQuantity'], 6)
        self.assertEqual(department_unit['allocatedQuantity'], 2)
        self.assertEqual(department_unit['allocations'][0]['id'], allocation.id)
        self.assertEqual(department_unit['allocations'][0]['targetName'], 'Lab Attendant')
        self.assertEqual(department_unit['allocations'][0]['batchId'], batch.id)


class StockRegisterDomainPermissionBootstrapTests(TestCase):
    def test_stock_register_domain_permissions_exist(self):
        perms = set(
            Permission.objects.filter(content_type__app_label='inventory').values_list('codename', flat=True)
        )

        self.assertTrue(
            {
                'view_stock_registers',
                'create_stock_registers',
                'edit_stock_registers',
                'delete_stock_registers',
            }.issubset(perms)
        )


class StockEntryStoreHierarchyRulesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = Location.objects.create(
            name='Hierarchy Root',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        cls.root.refresh_from_db()
        cls.central_store = cls.root.auto_created_store

        cls.csit = Location.objects.create(
            name='Hierarchy CSIT',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.csit.refresh_from_db()
        cls.csit_main_store = cls.csit.auto_created_store

        cls.electrical = Location.objects.create(
            name='Hierarchy Electrical',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.electrical.refresh_from_db()
        cls.electrical_main_store = cls.electrical.auto_created_store

        cls.csit_lab = Location.objects.create(
            name='Hierarchy CSIT Lab',
            location_type=LocationType.LAB,
            parent_location=cls.csit,
            is_standalone=False,
        )
        cls.csit_lab_store = Location.objects.create(
            name='Hierarchy CSIT Lab Store',
            location_type=LocationType.STORE,
            parent_location=cls.csit_lab,
            is_store=True,
        )
        cls.csit_lab_two_store = Location.objects.create(
            name='Hierarchy CSIT Lab Two Store',
            location_type=LocationType.STORE,
            parent_location=cls.csit_main_store,
            is_store=True,
        )
        cls.electrical_lab_store = Location.objects.create(
            name='Hierarchy Electrical Lab Store',
            location_type=LocationType.STORE,
            parent_location=cls.electrical_main_store,
            is_store=True,
        )

        cls.user = User.objects.create_user(username='hierarchy_rules', password='pw')

    def transferrable_ids(self, source):
        return set(self.user.profile.get_transferrable_locations(source).values_list('id', flat=True))

    def test_central_store_transfers_only_to_standalone_main_stores(self):
        ids = self.transferrable_ids(self.central_store)

        self.assertIn(self.csit_main_store.id, ids)
        self.assertIn(self.electrical_main_store.id, ids)
        self.assertNotIn(self.csit_lab_store.id, ids)

    def test_standalone_main_store_transfers_to_central_and_same_scope_regular_stores(self):
        ids = self.transferrable_ids(self.csit_main_store)

        self.assertIn(self.central_store.id, ids)
        self.assertIn(self.csit_lab_store.id, ids)
        self.assertIn(self.csit_lab_two_store.id, ids)
        self.assertNotIn(self.electrical_main_store.id, ids)
        self.assertNotIn(self.electrical_lab_store.id, ids)

    def test_regular_store_transfers_to_own_main_store_and_peer_regular_stores(self):
        ids = self.transferrable_ids(self.csit_lab_store)

        self.assertIn(self.csit_main_store.id, ids)
        self.assertIn(self.csit_lab_two_store.id, ids)
        self.assertNotIn(self.central_store.id, ids)
        self.assertNotIn(self.electrical_lab_store.id, ids)

    def test_model_validation_allows_main_store_to_same_scope_regular_store(self):
        entry = StockEntry(
            entry_type='ISSUE',
            from_location=self.csit_main_store,
            to_location=self.csit_lab_store,
            status='DRAFT',
            created_by=self.user,
        )

        entry.clean()

    def test_model_validation_blocks_regular_store_to_central_store(self):
        entry = StockEntry(
            entry_type='ISSUE',
            from_location=self.csit_lab_store,
            to_location=self.central_store,
            status='DRAFT',
            created_by=self.user,
        )

        with self.assertRaises(ValidationError):
            entry.clean()


class LocationApiPermissionAndScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = Location.objects.create(
            name='University Root',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        cls.dept_a = Location.objects.create(
            name='Dept A',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.dept_a_room = Location.objects.create(
            name='Dept A Room',
            location_type=LocationType.ROOM,
            parent_location=cls.dept_a,
            is_standalone=False,
        )
        cls.dept_a_lab = Location.objects.create(
            name='Dept A Lab',
            location_type=LocationType.LAB,
            parent_location=cls.dept_a_room,
            is_standalone=False,
        )
        cls.dept_b = Location.objects.create(
            name='Dept B',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )

    def setUp(self):
        self.client = APIClient()

    def _perm(self, codename):
        return Permission.objects.get(content_type__app_label='inventory', codename=codename)

    def _user_mgmt_perm(self, codename):
        return Permission.objects.get(content_type__app_label='user_management', codename=codename)

    def _make_user(self, username):
        return User.objects.create_user(username=username, password='pw')

    def _rows(self, response):
        data = response.data
        if isinstance(data, dict) and 'results' in data:
            return data['results']
        return data

    def test_list_requires_domain_view_locations_perm(self):
        user = self._make_user('no_domain_view')
        user.user_permissions.add(self._perm('view_location'))
        user.profile.assigned_locations.add(self.root)

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/locations/')

        self.assertEqual(resp.status_code, 403)

    def test_scoped_list_keeps_get_accessible_locations_semantics(self):
        user = self._make_user('scoped_viewer')
        user.user_permissions.add(self._perm('view_locations'))
        user.user_permissions.add(self._perm('view_location'))
        user.profile.assigned_locations.add(self.dept_a)

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/locations/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.dept_a.id, returned_ids)
        self.assertIn(self.dept_a_room.id, returned_ids)
        self.assertNotIn(self.dept_b.id, returned_ids)

    def test_create_requires_domain_create_locations_perm(self):
        user = self._make_user('loc_view_only')
        user.user_permissions.add(self._perm('view_locations'))
        user.user_permissions.add(self._perm('view_location'))
        user.profile.assigned_locations.add(self.root)

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/locations/',
            {
                'name': 'Dept C',
                'location_type': LocationType.DEPARTMENT,
                'parent_location': self.root.id,
                'is_standalone': True,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 403)

    def test_assignable_returns_assigned_location_descendants_only_for_scoped_user(self):
        user = self._make_user('assignable_scoped')
        user.user_permissions.add(self._perm('view_locations'))
        user.user_permissions.add(self._perm('view_location'))
        user.profile.assigned_locations.add(self.dept_a)

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/locations/assignable/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.dept_a.id, returned_ids)
        self.assertIn(self.dept_a_room.id, returned_ids)
        self.assertIn(self.dept_a_lab.id, returned_ids)
        self.assertNotIn(self.dept_b.id, returned_ids)

    def test_assignable_ignores_view_all_user_accounts_for_non_root_assigned_user(self):
        user = self._make_user('assignable_view_all_scoped')
        user.user_permissions.add(self._perm('view_locations'))
        user.user_permissions.add(self._perm('view_location'))
        user.user_permissions.add(self._user_mgmt_perm('view_all_user_accounts'))
        user.profile.assigned_locations.add(self.dept_a)

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/locations/assignable/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.dept_a.id, returned_ids)
        self.assertIn(self.dept_a_room.id, returned_ids)
        self.assertIn(self.dept_a_lab.id, returned_ids)
        self.assertNotIn(self.dept_b.id, returned_ids)

    def test_assignable_ignores_system_admin_role_for_non_root_assigned_user(self):
        user = self._make_user('assignable_system_admin_scoped')
        group = Group.objects.create(name='System Admin')
        user.groups.add(group)
        user.user_permissions.add(self._perm('view_locations'))
        user.user_permissions.add(self._perm('view_location'))
        user.profile.assigned_locations.add(self.dept_a)

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/locations/assignable/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.dept_a.id, returned_ids)
        self.assertIn(self.dept_a_room.id, returned_ids)
        self.assertIn(self.dept_a_lab.id, returned_ids)
        self.assertNotIn(self.dept_b.id, returned_ids)

    def test_assignable_root_assigned_user_can_assign_all_active_locations(self):
        user = self._make_user('assignable_root')
        user.user_permissions.add(self._perm('view_locations'))
        user.user_permissions.add(self._perm('view_location'))
        user.profile.assigned_locations.add(self.root)

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/locations/assignable/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.root.id, returned_ids)
        self.assertIn(self.dept_a.id, returned_ids)
        self.assertIn(self.dept_a_room.id, returned_ids)
        self.assertIn(self.dept_a_lab.id, returned_ids)
        self.assertIn(self.dept_b.id, returned_ids)

    def test_serializer_enforces_model_clean_invariant_for_root_creation(self):
        user = self._make_user('loc_creator')
        user.user_permissions.add(self._perm('view_locations'))
        user.user_permissions.add(self._perm('create_locations'))
        user.user_permissions.add(self._perm('view_location'))
        user.profile.assigned_locations.add(self.root)

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/locations/',
            {
                'name': 'Invalid Extra Root',
                'location_type': LocationType.DEPARTMENT,
                'parent_location': None,
                'is_standalone': True,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('parent_location', resp.data)


class LocationStandaloneWorkflowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_superuser(
            username='location_admin',
            email='location_admin@example.com',
            password='pw',
        )
        self.client.force_authenticate(user=self.user)

    def _rows(self, response):
        data = response.data
        if isinstance(data, dict) and 'results' in data:
            return data['results']
        return data

    def test_standalone_create_endpoint_creates_first_root_and_central_store(self):
        resp = self.client.post(
            '/api/inventory/locations/standalone/',
            {
                'name': 'NED University',
                'location_type': LocationType.DEPARTMENT,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)
        root = Location.objects.get(pk=resp.data['id'])
        self.assertIsNone(root.parent_location)
        self.assertTrue(root.is_standalone)
        self.assertEqual(root.hierarchy_level, 0)
        self.assertIsNotNone(root.auto_created_store)
        self.assertEqual(root.auto_created_store.name, 'Central Store')
        self.assertTrue(root.auto_created_store.is_main_store)
        self.assertEqual(root.auto_created_store.parent_location, root)

    def test_standalone_create_endpoint_locks_child_to_root_and_uses_main_store_name(self):
        root = Location.objects.create(
            name='NED University',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )

        resp = self.client.post(
            '/api/inventory/locations/standalone/',
            {
                'name': 'CSIT',
                'location_type': LocationType.DEPARTMENT,
                'parent_location': None,
                'is_standalone': False,
                'main_store_name': 'CSIT Main Inventory',
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)
        csit = Location.objects.get(pk=resp.data['id'])
        self.assertEqual(csit.parent_location, root)
        self.assertTrue(csit.is_standalone)
        self.assertEqual(csit.auto_created_store.name, 'CSIT Main Inventory')
        self.assertEqual(csit.auto_created_store.parent_location, csit)

    def test_standalone_list_endpoint_returns_only_standalone_locations(self):
        root = Location.objects.create(
            name='NED University',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        csit = Location.objects.create(
            name='CSIT',
            location_type=LocationType.DEPARTMENT,
            parent_location=root,
            is_standalone=True,
        )
        room = Location.objects.create(
            name='CSIT Room 101',
            location_type=LocationType.ROOM,
            parent_location=csit,
            is_standalone=False,
        )

        resp = self.client.get('/api/inventory/locations/standalone/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(root.id, returned_ids)
        self.assertIn(csit.id, returned_ids)
        self.assertNotIn(root.auto_created_store.id, returned_ids)
        self.assertNotIn(csit.auto_created_store.id, returned_ids)
        self.assertNotIn(room.id, returned_ids)

    def test_children_endpoint_returns_immediate_children_and_root_excludes_standalones(self):
        root = Location.objects.create(
            name='NED University',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        csit = Location.objects.create(
            name='CSIT',
            location_type=LocationType.DEPARTMENT,
            parent_location=root,
            is_standalone=True,
        )
        root_lab = Location.objects.create(
            name='Root Lab',
            location_type=LocationType.LAB,
            parent_location=root,
            is_standalone=False,
        )
        csit_room = Location.objects.create(
            name='CSIT Room 101',
            location_type=LocationType.ROOM,
            parent_location=csit,
            is_standalone=False,
        )
        nested_room = Location.objects.create(
            name='Nested Room',
            location_type=LocationType.ROOM,
            parent_location=csit_room,
            is_standalone=False,
        )

        root_resp = self.client.get(f'/api/inventory/locations/{root.id}/children/')
        csit_resp = self.client.get(f'/api/inventory/locations/{csit.id}/children/')

        self.assertEqual(root_resp.status_code, 200)
        root_ids = {row['id'] for row in self._rows(root_resp)}
        self.assertIn(root_lab.id, root_ids)
        self.assertIn(root.auto_created_store.id, root_ids)
        self.assertNotIn(csit.id, root_ids)

        self.assertEqual(csit_resp.status_code, 200)
        csit_ids = {row['id'] for row in self._rows(csit_resp)}
        self.assertIn(csit_room.id, csit_ids)
        self.assertIn(csit.auto_created_store.id, csit_ids)
        self.assertNotIn(nested_room.id, csit_ids)

    def test_children_create_endpoint_locks_parent_and_marks_child_non_standalone(self):
        root = Location.objects.create(
            name='NED University',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        csit = Location.objects.create(
            name='CSIT',
            location_type=LocationType.DEPARTMENT,
            parent_location=root,
            is_standalone=True,
        )

        resp = self.client.post(
            f'/api/inventory/locations/{csit.id}/children/',
            {
                'name': 'CSIT Lab 1',
                'location_type': LocationType.LAB,
                'parent_location': root.id,
                'is_standalone': True,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)
        child = Location.objects.get(pk=resp.data['id'])
        self.assertEqual(child.parent_location, csit)
        self.assertFalse(child.is_standalone)

    def test_children_create_endpoint_marks_store_type_as_store(self):
        root = Location.objects.create(
            name='Store Type Root',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        csit = Location.objects.create(
            name='Store Type CSIT',
            location_type=LocationType.DEPARTMENT,
            parent_location=root,
            is_standalone=True,
        )

        resp = self.client.post(
            f'/api/inventory/locations/{csit.id}/children/',
            {
                'name': 'CSIT Lab Store',
                'location_type': LocationType.STORE,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)
        child = Location.objects.get(pk=resp.data['id'])
        self.assertTrue(child.is_store)
        self.assertFalse(child.is_standalone)


class CategoryApiDomainPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(
            name='Existing Category',
            category_type=CategoryType.FIXED_ASSET,
        )

    def setUp(self):
        self.client = APIClient()

    def _perm(self, codename):
        return Permission.objects.get(content_type__app_label='inventory', codename=codename)

    def _make_user(self, username):
        return User.objects.create_user(username=username, password='pw')

    def test_list_requires_domain_view_categories_perm(self):
        user = self._make_user('category_legacy_view')
        user.user_permissions.add(self._perm('view_category'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/categories/')

        self.assertEqual(resp.status_code, 403)

    def test_list_allows_domain_view_categories_perm(self):
        user = self._make_user('category_domain_view')
        user.user_permissions.add(self._perm('view_categories'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/categories/')

        self.assertEqual(resp.status_code, 200)

    def test_create_requires_domain_create_categories_perm(self):
        user = self._make_user('category_legacy_add')
        user.user_permissions.add(self._perm('add_category'))

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/categories/',
            {
                'name': 'Posted Category',
                'category_type': CategoryType.CONSUMABLE,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 403)

    def test_create_allows_domain_create_categories_perm(self):
        user = self._make_user('category_domain_create')
        user.user_permissions.add(self._perm('create_categories'))

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/categories/',
            {
                'name': 'Domain Created Category',
                'category_type': CategoryType.CONSUMABLE,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)

    def test_patch_requires_domain_edit_categories_perm(self):
        user = self._make_user('category_legacy_change')
        user.user_permissions.add(self._perm('change_category'))

        self.client.force_authenticate(user=user)
        resp = self.client.patch(
            f'/api/inventory/categories/{self.category.id}/',
            {'name': 'Renamed Category'},
            format='json',
        )

        self.assertEqual(resp.status_code, 403)

    def test_patch_allows_domain_edit_categories_perm(self):
        user = self._make_user('category_domain_edit')
        user.user_permissions.add(self._perm('edit_categories'))

        self.client.force_authenticate(user=user)
        resp = self.client.patch(
            f'/api/inventory/categories/{self.category.id}/',
            {'name': 'Domain Edited Category'},
            format='json',
        )

        self.assertEqual(resp.status_code, 200)

    def test_delete_requires_domain_delete_categories_perm(self):
        user = self._make_user('category_legacy_delete')
        user.user_permissions.add(self._perm('delete_category'))

        self.client.force_authenticate(user=user)
        resp = self.client.delete(f'/api/inventory/categories/{self.category.id}/')

        self.assertEqual(resp.status_code, 403)

    def test_delete_allows_domain_delete_categories_perm(self):
        user = self._make_user('category_domain_delete')
        user.user_permissions.add(self._perm('delete_categories'))

        category = Category.objects.create(
            name='Domain Deletable Category',
            category_type=CategoryType.CONSUMABLE,
        )

        self.client.force_authenticate(user=user)
        resp = self.client.delete(f'/api/inventory/categories/{category.id}/')

        self.assertEqual(resp.status_code, 204)

    def test_create_with_notes_succeeds_without_invalid_model_kwargs(self):
        user = self._make_user('category_notes_create')
        user.user_permissions.add(self._perm('create_categories'))

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/categories/',
            {
                'name': 'Category With Notes',
                'category_type': CategoryType.CONSUMABLE,
                'notes': 'created from category form',
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)
        created = Category.objects.get(id=resp.data['id'])
        self.assertEqual(created.name, 'Category With Notes')
        self.assertEqual(created.category_type, CategoryType.CONSUMABLE)

    def test_patch_with_notes_succeeds_without_invalid_model_kwargs(self):
        user = self._make_user('category_notes_patch')
        user.user_permissions.add(self._perm('edit_categories'))

        self.client.force_authenticate(user=user)
        resp = self.client.patch(
            f'/api/inventory/categories/{self.category.id}/',
            {
                'name': 'Existing Category (Updated With Notes)',
                'notes': 'edited from category form',
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 200)
        self.category.refresh_from_db()
        self.assertEqual(self.category.name, 'Existing Category (Updated With Notes)')

    def test_patch_rejects_subcategory_tracking_type_change(self):
        user = self._make_user('category_tracking_patch')
        user.user_permissions.add(self._perm('edit_categories'))
        parent = Category.objects.create(
            name='Fixed Asset Parent',
            category_type=CategoryType.FIXED_ASSET,
            default_depreciation_rate=12,
        )
        child = Category.objects.create(
            name='Fixed Asset Child',
            parent_category=parent,
            category_type=CategoryType.FIXED_ASSET,
            tracking_type=TrackingType.INDIVIDUAL,
            default_depreciation_rate=12,
        )

        self.client.force_authenticate(user=user)
        resp = self.client.patch(
            f'/api/inventory/categories/{child.id}/',
            {'tracking_type': TrackingType.QUANTITY},
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('tracking_type', resp.data)
        child.refresh_from_db()
        self.assertEqual(child.tracking_type, TrackingType.INDIVIDUAL)


class ItemApiDomainPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = Location.objects.create(
            name='University Root',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        cls.csit = Location.objects.create(
            name='CSIT',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.store = Location.objects.create(
            name='CSIT Store',
            location_type=LocationType.STORE,
            parent_location=cls.csit,
            is_store=True,
        )
        cls.parent_category = Category.objects.create(
            name='Computing Hardware',
            category_type=CategoryType.FIXED_ASSET,
        )
        cls.subcategory = Category.objects.create(
            name='Processors',
            parent_category=cls.parent_category,
            category_type=CategoryType.FIXED_ASSET,
            tracking_type=TrackingType.INDIVIDUAL,
        )
        cls.item = Item.objects.create(
            name='Core i5 Processor',
            category=cls.subcategory,
            acct_unit='unit',
            specifications='Intel Core i5',
        )
        cls.batch = ItemBatch.objects.create(
            item=cls.item,
            batch_number='B-001',
        )
        cls.instance = ItemInstance.objects.create(
            item=cls.item,
            current_location=cls.store,
            serial_number='CPU-001',
        )
        StockRecord.objects.create(
            item=cls.item,
            batch=cls.batch,
            location=cls.store,
            quantity=5,
            allocated_quantity=2,
        )

    def setUp(self):
        self.client = APIClient()

    def _perm(self, codename):
        return Permission.objects.get(content_type__app_label='inventory', codename=codename)

    def _make_user(self, username):
        user = User.objects.create_user(username=username, password='pw')
        user.profile.assigned_locations.add(self.root)
        user.user_permissions.add(self._perm('view_scoped_distribution'))
        return user

    def test_list_requires_domain_view_items_perm(self):
        user = self._make_user('item_legacy_view')
        user.user_permissions.add(self._perm('view_item'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/items/')

        self.assertEqual(resp.status_code, 403)

    def test_list_allows_domain_view_items_perm(self):
        user = self._make_user('item_domain_view')
        user.user_permissions.add(self._perm('view_items'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/items/')

        self.assertEqual(resp.status_code, 200)

    def test_create_requires_domain_create_items_perm(self):
        user = self._make_user('item_legacy_add')
        user.user_permissions.add(self._perm('add_item'))

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/items/',
            {
                'name': 'Blocked Item',
                'category': self.subcategory.id,
                'acct_unit': 'unit',
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 403)

    def test_create_allows_domain_create_items_perm(self):
        user = self._make_user('item_domain_create')
        user.user_permissions.add(self._perm('create_items'))

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/items/',
            {
                'name': 'Domain Created Item',
                'category': self.subcategory.id,
                'acct_unit': 'unit',
                'low_stock_threshold': 4,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['low_stock_threshold'], 4)

    def test_list_exposes_low_stock_threshold_and_flag(self):
        self.item.low_stock_threshold = 5
        self.item.save(update_fields=['low_stock_threshold'])
        user = self._make_user('item_low_stock_view')
        user.user_permissions.add(self._perm('view_items'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/items/')

        self.assertEqual(resp.status_code, 200)
        row = next(record for record in resp.data['results'] if record['id'] == self.item.id)
        self.assertEqual(row['low_stock_threshold'], 5)
        self.assertTrue(row['is_low_stock'])

    def test_update_allows_domain_edit_items_perm(self):
        user = self._make_user('item_domain_edit')
        user.user_permissions.add(self._perm('edit_items'))

        self.client.force_authenticate(user=user)
        resp = self.client.patch(
            f'/api/inventory/items/{self.item.id}/',
            {
                'low_stock_threshold': 2,
            },
            format='json',
        )

        self.assertEqual(resp.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.low_stock_threshold, 2)

    def test_distribution_hierarchical_allows_domain_view_items_perm(self):
        user = self._make_user('item_distribution_view')
        user.user_permissions.add(self._perm('view_items'))

        self.client.force_authenticate(user=user)
        resp = self.client.get(f'/api/inventory/distribution/hierarchical/?item={self.item.id}')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in resp.data}
        self.assertIn(self.csit.id, returned_ids)

    def test_distribution_hierarchical_aggregates_store_rows_across_batches_for_same_location(self):
        user = self._make_user('item_distribution_aggregate')
        user.user_permissions.add(self._perm('view_items'))
        StockRecord.objects.create(
            item=self.item,
            batch=None,
            location=self.store,
            quantity=4,
            allocated_quantity=1,
            in_transit_quantity=1,
        )

        self.client.force_authenticate(user=user)
        resp = self.client.get(f'/api/inventory/distribution/hierarchical/?item={self.item.id}')

        self.assertEqual(resp.status_code, 200)
        unit = next(row for row in resp.data if row['id'] == self.csit.id)

        self.assertEqual(unit['totalQuantity'], 9)
        self.assertEqual(unit['availableQuantity'], 5)
        self.assertEqual(unit['allocatedQuantity'], 3)
        self.assertEqual(unit['inTransitQuantity'], 1)
        self.assertEqual(len(unit['stores']), 1)
        self.assertEqual(unit['stores'][0]['locationId'], self.store.id)
        self.assertEqual(unit['stores'][0]['quantity'], 9)
        self.assertEqual(unit['stores'][0]['availableQuantity'], 5)
        self.assertEqual(unit['stores'][0]['allocatedTotal'], 3)
        self.assertEqual(unit['stores'][0]['inTransitQuantity'], 1)
        self.assertIsNone(unit['stores'][0]['batchId'])
        self.assertIsNone(unit['stores'][0]['batchNumber'])

    def test_batches_allow_domain_view_items_perm(self):
        user = self._make_user('item_batch_view')
        user.user_permissions.add(self._perm('view_items'))

        self.client.force_authenticate(user=user)
        resp = self.client.get(f'/api/inventory/item-batches/?item={self.item.id}')

        self.assertEqual(resp.status_code, 200)

    def test_instances_require_domain_view_items_perm(self):
        user = self._make_user('item_instance_no_view')

        self.client.force_authenticate(user=user)
        resp = self.client.get(f'/api/inventory/item-instances/?item={self.item.id}')

        self.assertEqual(resp.status_code, 403)

    def test_instances_allow_domain_view_items_perm(self):
        user = self._make_user('item_instance_view')
        user.user_permissions.add(self._perm('view_items'))

        self.client.force_authenticate(user=user)
        resp = self.client.get(f'/api/inventory/item-instances/?item={self.item.id}')

        self.assertEqual(resp.status_code, 200)


class StockEntryApiDomainPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = Location.objects.create(
            name='Stock Root',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        cls.csit = Location.objects.create(
            name='Stock CSIT',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.store = Location.objects.create(
            name='Stock CSIT Store',
            location_type=LocationType.STORE,
            parent_location=cls.csit,
            is_store=True,
            is_main_store=True,
        )
        cls.child_store = Location.objects.create(
            name='Stock CSIT Lab Store',
            location_type=LocationType.STORE,
            parent_location=cls.store,
            is_store=True,
        )
        cls.non_store_location = Location.objects.create(
            name='Stock CSIT Lab',
            location_type=LocationType.LAB,
            parent_location=cls.csit,
            is_standalone=False,
        )
        cls.person = Person.objects.create(
            name='Stock Entry Person',
            department='Stock CSIT',
        )
        cls.person.standalone_locations.add(cls.csit)
        cls.parent_category = Category.objects.create(
            name='Stock Entry Hardware',
            category_type=CategoryType.FIXED_ASSET,
        )
        cls.subcategory = Category.objects.create(
            name='Stock Entry Mouse',
            parent_category=cls.parent_category,
            category_type=CategoryType.FIXED_ASSET,
            tracking_type=TrackingType.QUANTITY,
        )
        cls.item = Item.objects.create(
            name='USB Mouse',
            category=cls.subcategory,
            acct_unit='unit',
        )
        cls.consumable_parent_category = Category.objects.create(
            name='Stock Entry Office Supplies',
            category_type=CategoryType.CONSUMABLE,
        )
        cls.consumable_subcategory = Category.objects.create(
            name='Stock Entry Staplers',
            parent_category=cls.consumable_parent_category,
            category_type=CategoryType.CONSUMABLE,
            tracking_type=TrackingType.QUANTITY,
        )
        cls.consumable_item = Item.objects.create(
            name='Stapler Box',
            category=cls.consumable_subcategory,
            acct_unit='box',
        )
        cls.batch = ItemBatch.objects.create(
            item=cls.item,
            batch_number='MOUSE-B1',
        )
        cls.consumable_batch_a = ItemBatch.objects.create(
            item=cls.consumable_item,
            batch_number='STAPLER-B1',
        )
        cls.consumable_batch_b = ItemBatch.objects.create(
            item=cls.consumable_item,
            batch_number='STAPLER-B2',
        )
        cls.source_stock = StockRecord.objects.create(
            item=cls.item,
            batch=cls.batch,
            location=cls.store,
            quantity=10,
        )
        cls.consumable_stock_a = StockRecord.objects.create(
            item=cls.consumable_item,
            batch=cls.consumable_batch_a,
            location=cls.store,
            quantity=4,
        )
        cls.consumable_stock_b = StockRecord.objects.create(
            item=cls.consumable_item,
            batch=cls.consumable_batch_b,
            location=cls.store,
            quantity=6,
        )
        cls.entry = StockEntry.objects.create(
            entry_type='ISSUE',
            from_location=cls.store,
            to_location=cls.child_store,
            status='DRAFT',
        )
        StockEntryItem.objects.create(
            stock_entry=cls.entry,
            item=cls.item,
            batch=cls.batch,
            quantity=3,
        )

    def setUp(self):
        self.client = APIClient()

    def _perm(self, codename):
        return Permission.objects.get(content_type__app_label='inventory', codename=codename)

    def _make_user(self, username):
        user = User.objects.create_user(username=username, password='pw')
        user.profile.assigned_locations.add(self.root)
        user.user_permissions.add(self._perm('view_scoped_distribution'))
        return user

    def _payload(self, purpose='Created from domain permission test'):
        return {
            'entry_type': 'ISSUE',
            'from_location': self.store.id,
            'to_location': self.child_store.id,
            'status': 'DRAFT',
            'purpose': purpose,
            'remarks': '',
            'items': [
                {
                    'item': self.item.id,
                    'batch': self.batch.id,
                    'quantity': 1,
                    'instances': [],
                    'stock_register': None,
                    'page_number': None,
                    'ack_stock_register': None,
                    'ack_page_number': None,
                }
            ],
        }

    def _consumable_payload(self, *, quantity=1, to_location=None, issued_to=None, purpose='Consumable movement'):
        return {
            'entry_type': 'ISSUE',
            'from_location': self.store.id,
            'to_location': to_location,
            'issued_to': issued_to,
            'status': 'DRAFT',
            'purpose': purpose,
            'remarks': '',
            'items': [
                {
                    'item': self.consumable_item.id,
                    'batch': None,
                    'quantity': quantity,
                    'instances': [],
                    'stock_register': None,
                    'page_number': None,
                    'ack_stock_register': None,
                    'ack_page_number': None,
                }
            ],
        }

    def _register(self, store, number):
        return StockRegister.objects.create(register_number=number, store=store)

    def _allocation(self, *, person=None, location=None, quantity=1, status=AllocationStatus.ALLOCATED):
        return StockAllocation.objects.create(
            item=self.item,
            batch=self.batch,
            source_location=self.store,
            quantity=quantity,
            allocated_to_person=person,
            allocated_to_location=location,
            status=status,
        )

    def test_list_requires_domain_view_stock_entries_perm(self):
        user = self._make_user('stock_entry_legacy_view')
        user.user_permissions.add(self._perm('view_stockentry'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/stock-entries/')

        self.assertEqual(resp.status_code, 403)

    def test_list_allows_domain_view_stock_entries_perm(self):
        user = self._make_user('stock_entry_domain_view')
        user.user_permissions.add(self._perm('view_stock_entries'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/stock-entries/')

        self.assertEqual(resp.status_code, 200)

    def test_list_scopes_entries_by_stock_entry_workflow_without_distribution_permission(self):
        issue_to_child = StockEntry.objects.create(
            entry_type='ISSUE',
            from_location=self.store,
            to_location=self.child_store,
            status='COMPLETED',
        )
        receipt_to_child = StockEntry.objects.create(
            entry_type='RECEIPT',
            from_location=self.store,
            to_location=self.child_store,
            status='PENDING_ACK',
            reference_entry=issue_to_child,
        )
        issue_to_store = StockEntry.objects.create(
            entry_type='ISSUE',
            from_location=self.child_store,
            to_location=self.store,
            status='COMPLETED',
        )
        receipt_to_store = StockEntry.objects.create(
            entry_type='RECEIPT',
            from_location=self.child_store,
            to_location=self.store,
            status='PENDING_ACK',
            reference_entry=issue_to_store,
        )
        return_to_store = StockEntry.objects.create(
            entry_type='RETURN',
            from_location=self.child_store,
            to_location=self.store,
            status='PENDING_ACK',
            reference_entry=receipt_to_child,
        )

        store_user = User.objects.create_user(username='stock_entry_store_scope', password='pw')
        store_user.profile.assigned_locations.add(self.store)
        store_user.user_permissions.add(self._perm('view_stock_entries'))

        child_store_user = User.objects.create_user(username='stock_entry_child_scope', password='pw')
        child_store_user.profile.assigned_locations.add(self.child_store)
        child_store_user.user_permissions.add(self._perm('view_stock_entries'))

        self.client.force_authenticate(user=store_user)
        store_resp = self.client.get('/api/inventory/stock-entries/')
        self.assertEqual(store_resp.status_code, 200)
        store_numbers = {row['entry_number'] for row in store_resp.data['results']}
        self.assertIn(issue_to_child.entry_number, store_numbers)
        self.assertIn(receipt_to_store.entry_number, store_numbers)
        self.assertIn(return_to_store.entry_number, store_numbers)
        self.assertNotIn(receipt_to_child.entry_number, store_numbers)
        self.assertNotIn(issue_to_store.entry_number, store_numbers)

        self.client.force_authenticate(user=child_store_user)
        child_resp = self.client.get('/api/inventory/stock-entries/')
        self.assertEqual(child_resp.status_code, 200)
        child_numbers = {row['entry_number'] for row in child_resp.data['results']}
        self.assertIn(receipt_to_child.entry_number, child_numbers)
        self.assertIn(issue_to_store.entry_number, child_numbers)
        self.assertNotIn(issue_to_child.entry_number, child_numbers)
        self.assertNotIn(receipt_to_store.entry_number, child_numbers)
        self.assertNotIn(return_to_store.entry_number, child_numbers)

    def test_create_requires_domain_create_stock_entries_perm(self):
        user = self._make_user('stock_entry_legacy_add')
        user.user_permissions.add(self._perm('add_stockentry'))

        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/inventory/stock-entries/', self._payload(), format='json')

        self.assertEqual(resp.status_code, 403)

    def test_create_allows_domain_create_stock_entries_perm(self):
        user = self._make_user('stock_entry_domain_create')
        user.user_permissions.add(self._perm('create_stock_entries'))

        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/inventory/stock-entries/', self._payload(), format='json')

        self.assertEqual(resp.status_code, 201)

    def test_create_issue_auto_splits_consumable_quantity_across_internal_batches(self):
        user = self._make_user('stock_entry_consumable_batchless_transfer')
        user.user_permissions.add(self._perm('create_stock_entries'))
        payload = self._consumable_payload(
            quantity=7,
            to_location=self.child_store.id,
            purpose='Consumable transfer without explicit batch',
        )

        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/inventory/stock-entries/', payload, format='json')

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['status'], 'PENDING_ACK')

        issue = StockEntry.objects.get(id=resp.data['id'])
        issue_items = list(issue.items.order_by('batch_id'))
        self.assertEqual(
            [(item.batch.batch_number if item.batch else None, item.quantity) for item in issue_items],
            [('STAPLER-B1', 4), ('STAPLER-B2', 3)],
        )

        linked_receipt = StockEntry.objects.get(reference_entry=issue, entry_type='RECEIPT')
        linked_items = list(linked_receipt.items.order_by('batch_id'))
        self.assertEqual(
            [(item.batch.batch_number if item.batch else None, item.quantity) for item in linked_items],
            [('STAPLER-B1', 4), ('STAPLER-B2', 3)],
        )

        self.consumable_stock_a.refresh_from_db()
        self.consumable_stock_b.refresh_from_db()
        self.assertEqual(self.consumable_stock_a.in_transit_quantity, 4)
        self.assertEqual(self.consumable_stock_b.in_transit_quantity, 3)

    def test_create_allocation_auto_splits_consumable_quantity_across_internal_batches(self):
        user = self._make_user('stock_entry_consumable_batchless_allocation')
        user.user_permissions.add(self._perm('create_stock_entries'))
        payload = self._consumable_payload(
            quantity=8,
            issued_to=self.person.id,
            purpose='Consumable allocation without explicit batch',
        )

        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/inventory/stock-entries/', payload, format='json')

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['status'], 'COMPLETED')

        entry = StockEntry.objects.get(id=resp.data['id'])
        entry_items = list(entry.items.order_by('batch_id'))
        self.assertEqual(
            [(item.batch.batch_number if item.batch else None, item.quantity) for item in entry_items],
            [('STAPLER-B1', 4), ('STAPLER-B2', 4)],
        )

        allocations = list(StockAllocation.objects.filter(stock_entry=entry).order_by('batch_id'))
        self.assertEqual(
            [(allocation.batch.batch_number if allocation.batch else None, allocation.quantity) for allocation in allocations],
            [('STAPLER-B1', 4), ('STAPLER-B2', 4)],
        )

        self.consumable_stock_a.refresh_from_db()
        self.consumable_stock_b.refresh_from_db()
        self.assertEqual(self.consumable_stock_a.allocated_quantity, 4)
        self.assertEqual(self.consumable_stock_b.allocated_quantity, 4)

    def test_create_forces_store_transfer_issue_to_pending_ack_and_creates_pending_receipt(self):
        user = self._make_user('stock_entry_force_pending_ack')
        user.user_permissions.add(self._perm('create_stock_entries'))
        payload = self._payload('Force status to pending ack')
        payload['status'] = 'COMPLETED'

        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/inventory/stock-entries/', payload, format='json')

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['status'], 'PENDING_ACK')
        linked_receipt = StockEntry.objects.get(reference_entry_id=resp.data['id'], entry_type='RECEIPT')
        self.assertEqual(linked_receipt.status, 'PENDING_ACK')

    def test_acknowledge_receipt_completes_receipt_and_parent_issue(self):
        user = self._make_user('stock_entry_acknowledger')
        user.user_permissions.add(self._perm('create_stock_entries'))
        user.user_permissions.add(self._perm('acknowledge_stockentry'))
        ack_register = self._register(self.child_store, 'ACK-FULL-1')

        self.client.force_authenticate(user=user)
        create_resp = self.client.post('/api/inventory/stock-entries/', self._payload('Acknowledge transfer'), format='json')
        self.assertEqual(create_resp.status_code, 201)
        linked_receipt = StockEntry.objects.get(reference_entry_id=create_resp.data['id'], entry_type='RECEIPT')
        receipt_item = linked_receipt.items.get()

        ack_resp = self.client.post(
            f'/api/inventory/stock-entries/{linked_receipt.id}/acknowledge/',
            {
                'items': [
                    {
                        'id': receipt_item.id,
                        'quantity': receipt_item.quantity,
                        'instances': [],
                        'ack_stock_register': ack_register.id,
                        'ack_page_number': 1,
                    }
                ]
            },
            format='json',
        )

        self.assertEqual(ack_resp.status_code, 200)
        linked_receipt.refresh_from_db()
        parent_issue = StockEntry.objects.get(id=create_resp.data['id'])
        self.assertEqual(linked_receipt.status, 'COMPLETED')
        self.assertEqual(parent_issue.status, 'COMPLETED')

    def test_issue_create_syncs_individual_instances_to_linked_receipt_and_acknowledge_self_heals_missing_receipt_instances(self):
        user = self._make_user('stock_entry_individual_sync')
        user.user_permissions.add(self._perm('create_stock_entries'))
        user.user_permissions.add(self._perm('acknowledge_stockentry'))
        ack_register = self._register(self.child_store, 'ACK-IND-1')

        individual_parent = Category.objects.create(
            name='Stock Entry Individual Hardware',
            category_type=CategoryType.FIXED_ASSET,
        )
        individual_category = Category.objects.create(
            name='Stock Entry Individual Device',
            parent_category=individual_parent,
            category_type=CategoryType.FIXED_ASSET,
            tracking_type=TrackingType.INDIVIDUAL,
        )
        individual_item = Item.objects.create(
            name='Portable Device',
            category=individual_category,
            acct_unit='unit',
        )
        instance = ItemInstance.objects.create(
            item=individual_item,
            current_location=self.store,
            status='AVAILABLE',
            created_by=user,
        )

        payload = {
            'entry_type': 'ISSUE',
            'from_location': self.store.id,
            'to_location': self.child_store.id,
            'status': 'DRAFT',
            'purpose': 'Individual transfer sync',
            'remarks': '',
            'items': [
                {
                    'item': individual_item.id,
                    'batch': None,
                    'quantity': 1,
                    'instances': [instance.id],
                    'stock_register': None,
                    'page_number': None,
                    'ack_stock_register': None,
                    'ack_page_number': None,
                }
            ],
        }

        self.client.force_authenticate(user=user)
        create_resp = self.client.post('/api/inventory/stock-entries/', payload, format='json')

        self.assertEqual(create_resp.status_code, 201)
        linked_receipt = StockEntry.objects.get(reference_entry_id=create_resp.data['id'], entry_type='RECEIPT')
        receipt_item = linked_receipt.items.get(item=individual_item)
        self.assertEqual(list(receipt_item.instances.values_list('id', flat=True)), [instance.id])

        receipt_item.instances.clear()
        ack_resp = self.client.post(
            f'/api/inventory/stock-entries/{linked_receipt.id}/acknowledge/',
            {
                'items': [
                    {
                        'id': receipt_item.id,
                        'quantity': 1,
                        'instances': [instance.id],
                        'ack_stock_register': ack_register.id,
                        'ack_page_number': 1,
                    }
                ]
            },
            format='json',
        )

        self.assertEqual(ack_resp.status_code, 200)
        receipt_item.refresh_from_db()
        self.assertEqual(list(receipt_item.instances.values_list('id', flat=True)), [instance.id])
        self.assertEqual(list(receipt_item.accepted_instances.values_list('id', flat=True)), [instance.id])

    def test_detail_includes_acknowledgement_audit_fields(self):
        user = self._make_user('stock_entry_detail_audit')
        user.user_permissions.add(self._perm('view_stock_entries'))
        user.user_permissions.add(self._perm('acknowledge_stockentry'))
        certificate = InspectionCertificate.objects.create(
            date=timezone.now().date(),
            contract_no='IC-STOCK-DETAIL-001',
            contract_date=timezone.now().date(),
            contractor_name='Detail Supplier',
            contractor_address='Block D',
            indenter='Detail Indenter',
            indent_no='IND-DETAIL-1',
            department=self.csit,
            date_of_delivery=timezone.now().date(),
            delivery_type='FULL',
            remarks='Detail link check',
            inspected_by='Inspector',
            date_of_inspection=timezone.now().date(),
            consignee_name='Consignee',
            consignee_designation='Manager',
            stage=InspectionStage.FINANCE_REVIEW,
            status='IN_PROGRESS',
            initiated_by=user,
            stock_filled_by=user,
            central_store_filled_by=user,
        )
        receipt = StockEntry.objects.create(
            entry_type='RECEIPT',
            from_location=self.store,
            to_location=self.child_store,
            status='COMPLETED',
            reference_entry=self.entry,
            inspection_certificate=certificate,
            acknowledged_by=user,
        )

        self.client.force_authenticate(user=user)
        resp = self.client.get(f'/api/inventory/stock-entries/{receipt.id}/')

        self.assertEqual(resp.status_code, 200)
        self.assertIn('reference_entry', resp.data)
        self.assertIn('acknowledged_at', resp.data)
        self.assertIn('acknowledged_by_name', resp.data)
        self.assertEqual(resp.data['inspection_certificate'], certificate.id)
        self.assertEqual(resp.data['inspection_certificate_number'], 'IC-STOCK-DETAIL-001')

    def test_partial_receipt_acknowledgement_records_accepted_quantity_and_creates_pending_return(self):
        user = self._make_user('stock_entry_partial_acknowledger')
        user.user_permissions.add(self._perm('create_stock_entries'))
        user.user_permissions.add(self._perm('acknowledge_stockentry'))
        ack_register = self._register(self.child_store, 'ACK-PARTIAL-1')
        payload = self._payload('Partial acknowledgement transfer')
        payload['items'][0]['quantity'] = 5

        self.client.force_authenticate(user=user)
        create_resp = self.client.post('/api/inventory/stock-entries/', payload, format='json')
        self.assertEqual(create_resp.status_code, 201)
        source_record = StockRecord.objects.get(item=self.item, batch=self.batch, location=self.store)
        self.assertEqual(source_record.quantity, 10)
        self.assertEqual(source_record.in_transit_quantity, 5)
        self.assertEqual(source_record.available_quantity, 5)
        linked_receipt = StockEntry.objects.get(reference_entry_id=create_resp.data['id'], entry_type='RECEIPT')
        receipt_item = linked_receipt.items.get()

        ack_resp = self.client.post(
            f'/api/inventory/stock-entries/{linked_receipt.id}/acknowledge/',
            {
                'items': [
                    {
                        'id': receipt_item.id,
                        'quantity': 2,
                        'instances': [],
                        'ack_stock_register': ack_register.id,
                        'ack_page_number': 9,
                    }
                ]
            },
            format='json',
        )

        self.assertEqual(ack_resp.status_code, 200)
        receipt_item.refresh_from_db()
        self.assertEqual(receipt_item.quantity, 5)
        self.assertEqual(receipt_item.accepted_quantity, 2)
        self.assertEqual(receipt_item.ack_stock_register, ack_register)
        self.assertEqual(receipt_item.ack_page_number, 9)
        return_entry = StockEntry.objects.get(reference_entry=linked_receipt, entry_type='RETURN')
        self.assertEqual(return_entry.from_location, self.child_store)
        self.assertEqual(return_entry.to_location, self.store)
        self.assertEqual(return_entry.status, 'PENDING_ACK')
        self.assertEqual(return_entry.items.get().quantity, 3)
        source_record.refresh_from_db()
        child_record = StockRecord.objects.get(item=self.item, batch=self.batch, location=self.child_store)
        self.assertEqual(source_record.quantity, 8)
        self.assertEqual(source_record.in_transit_quantity, 3)
        self.assertEqual(source_record.available_quantity, 5)
        self.assertEqual(child_record.quantity, 2)
        self.assertEqual(child_record.in_transit_quantity, 0)
        self.assertEqual(child_record.available_quantity, 2)

    def test_partial_transfer_return_acknowledgement_restores_source_available_from_in_transit(self):
        user = self._make_user('stock_entry_partial_return_recovery')
        user.user_permissions.add(self._perm('create_stock_entries'))
        user.user_permissions.add(self._perm('acknowledge_stockentry'))
        dest_ack_register = self._register(self.child_store, 'ACK-PARTIAL-RETURN-DEST')
        source_ack_register = self._register(self.store, 'ACK-PARTIAL-RETURN-SOURCE')
        payload = self._payload('Partial acknowledgement with return completion')
        payload['items'][0]['quantity'] = 5

        self.client.force_authenticate(user=user)
        create_resp = self.client.post('/api/inventory/stock-entries/', payload, format='json')
        self.assertEqual(create_resp.status_code, 201)

        linked_receipt = StockEntry.objects.get(reference_entry_id=create_resp.data['id'], entry_type='RECEIPT')
        receipt_item = linked_receipt.items.get()
        ack_resp = self.client.post(
            f'/api/inventory/stock-entries/{linked_receipt.id}/acknowledge/',
            {
                'items': [
                    {
                        'id': receipt_item.id,
                        'quantity': 2,
                        'instances': [],
                        'ack_stock_register': dest_ack_register.id,
                        'ack_page_number': 4,
                    }
                ]
            },
            format='json',
        )
        self.assertEqual(ack_resp.status_code, 200)

        return_entry = StockEntry.objects.get(reference_entry=linked_receipt, entry_type='RETURN')
        return_item = return_entry.items.get()
        return_ack_resp = self.client.post(
            f'/api/inventory/stock-entries/{return_entry.id}/acknowledge/',
            {
                'items': [
                    {
                        'id': return_item.id,
                        'quantity': return_item.quantity,
                        'instances': [],
                        'ack_stock_register': source_ack_register.id,
                        'ack_page_number': 12,
                    }
                ]
            },
            format='json',
        )

        self.assertEqual(return_ack_resp.status_code, 200)
        source_record = StockRecord.objects.get(item=self.item, batch=self.batch, location=self.store)
        child_record = StockRecord.objects.get(item=self.item, batch=self.batch, location=self.child_store)
        self.assertEqual(source_record.quantity, 8)
        self.assertEqual(source_record.in_transit_quantity, 0)
        self.assertEqual(source_record.available_quantity, 8)
        self.assertEqual(child_record.quantity, 2)
        self.assertEqual(child_record.available_quantity, 2)

    def test_return_acknowledgement_accepts_all_and_does_not_create_recursive_return(self):
        user = self._make_user('stock_entry_return_acknowledger')
        user.user_permissions.add(self._perm('acknowledge_stockentry'))
        ack_register = self._register(self.store, 'ACK-RETURN-1')
        receipt = StockEntry.objects.create(
            entry_type='RECEIPT',
            from_location=self.store,
            to_location=self.child_store,
            status='COMPLETED',
        )
        return_entry = StockEntry.objects.create(
            entry_type='RETURN',
            from_location=self.child_store,
            to_location=self.store,
            status='PENDING_ACK',
            reference_entry=receipt,
        )
        return_item = StockEntryItem.objects.create(
            stock_entry=return_entry,
            item=self.item,
            batch=self.batch,
            quantity=3,
        )

        self.client.force_authenticate(user=user)
        ack_resp = self.client.post(
            f'/api/inventory/stock-entries/{return_entry.id}/acknowledge/',
            {
                'items': [
                    {
                        'id': return_item.id,
                        'quantity': 1,
                        'instances': [],
                        'ack_stock_register': ack_register.id,
                        'ack_page_number': 12,
                    }
                ]
            },
            format='json',
        )

        self.assertEqual(ack_resp.status_code, 200)
        return_item.refresh_from_db()
        return_entry.refresh_from_db()
        self.assertEqual(return_entry.status, 'COMPLETED')
        self.assertEqual(return_item.accepted_quantity, 3)
        self.assertFalse(StockEntry.objects.filter(reference_entry=return_entry, entry_type='RETURN').exists())

    def test_patch_requires_domain_edit_stock_entries_perm(self):
        user = self._make_user('stock_entry_legacy_change')
        user.user_permissions.add(self._perm('change_stockentry'))

        self.client.force_authenticate(user=user)
        resp = self.client.patch(
            f'/api/inventory/stock-entries/{self.entry.id}/',
            self._payload('Legacy edit should be blocked'),
            format='json',
        )

        self.assertEqual(resp.status_code, 403)

    def test_patch_allows_domain_edit_stock_entries_perm(self):
        user = self._make_user('stock_entry_domain_edit')
        user.user_permissions.add(self._perm('edit_stock_entries'))

        self.client.force_authenticate(user=user)
        resp = self.client.patch(
            f'/api/inventory/stock-entries/{self.entry.id}/',
            self._payload('Domain edit should pass'),
            format='json',
        )

        self.assertEqual(resp.status_code, 200)

    def test_delete_requires_domain_delete_stock_entries_perm(self):
        user = self._make_user('stock_entry_legacy_delete')
        user.user_permissions.add(self._perm('delete_stockentry'))

        self.client.force_authenticate(user=user)
        resp = self.client.delete(f'/api/inventory/stock-entries/{self.entry.id}/')

        self.assertEqual(resp.status_code, 403)

    def test_create_rejects_return_entry_type_for_user_created_entries(self):
        user = self._make_user('stock_entry_return_blocked')
        user.user_permissions.add(self._perm('create_stock_entries'))
        payload = self._payload()
        payload['entry_type'] = 'RETURN'

        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/inventory/stock-entries/', payload, format='json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('entry_type', resp.data)

    def test_create_requires_source_store(self):
        user = self._make_user('stock_entry_source_required')
        user.user_permissions.add(self._perm('create_stock_entries'))
        payload = self._payload()
        payload['from_location'] = None

        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/inventory/stock-entries/', payload, format='json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('from_location', resp.data)

    def test_create_rejects_same_source_and_destination_store(self):
        user = self._make_user('stock_entry_same_store_blocked')
        user.user_permissions.add(self._perm('create_stock_entries'))
        payload = self._payload()
        payload['from_location'] = self.store.id
        payload['to_location'] = self.store.id

        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/inventory/stock-entries/', payload, format='json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('to_location', resp.data)

    def test_create_allows_receipt_return_from_person_to_store(self):
        user = self._make_user('stock_entry_receipt_person')
        user.user_permissions.add(self._perm('create_stock_entries'))
        self._allocation(person=self.person)
        payload = self._payload('Person return receipt')
        payload['entry_type'] = 'RECEIPT'
        payload['from_location'] = None
        payload['to_location'] = self.store.id
        payload['issued_to'] = self.person.id

        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/inventory/stock-entries/', payload, format='json')

        self.assertEqual(resp.status_code, 201)

    def test_create_allows_receipt_return_from_non_store_to_store(self):
        user = self._make_user('stock_entry_receipt_non_store')
        user.user_permissions.add(self._perm('create_stock_entries'))
        self._allocation(location=self.non_store_location)
        payload = self._payload('Non-store return receipt')
        payload['entry_type'] = 'RECEIPT'
        payload['from_location'] = self.non_store_location.id
        payload['to_location'] = self.store.id
        payload['issued_to'] = None

        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/inventory/stock-entries/', payload, format='json')

        self.assertEqual(resp.status_code, 201)

    def test_create_rejects_receipt_return_from_person_without_active_allocation(self):
        user = self._make_user('stock_entry_receipt_person_unallocated')
        user.user_permissions.add(self._perm('create_stock_entries'))
        payload = self._payload('Unallocated person return receipt')
        payload['entry_type'] = 'RECEIPT'
        payload['from_location'] = None
        payload['to_location'] = self.store.id
        payload['issued_to'] = self.person.id

        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/inventory/stock-entries/', payload, format='json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('items', resp.data)

    def test_create_rejects_receipt_return_from_non_store_without_active_allocation(self):
        user = self._make_user('stock_entry_receipt_location_unallocated')
        user.user_permissions.add(self._perm('create_stock_entries'))
        payload = self._payload('Unallocated non-store return receipt')
        payload['entry_type'] = 'RECEIPT'
        payload['from_location'] = self.non_store_location.id
        payload['to_location'] = self.store.id
        payload['issued_to'] = None

        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/inventory/stock-entries/', payload, format='json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('items', resp.data)


class StockRegisterApiPermissionAndScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = Location.objects.create(
            name='Stock Register Root',
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        cls.csit = Location.objects.create(
            name='Stock Register CSIT',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.ee = Location.objects.create(
            name='Stock Register EE',
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.central_store = cls.root.auto_created_store
        cls.csit_store = cls.csit.auto_created_store
        cls.ee_store = cls.ee.auto_created_store
        cls.root_lab = Location.objects.create(
            name='Stock Register Root Lab',
            location_type=LocationType.LAB,
            parent_location=cls.root,
            is_standalone=False,
        )
        cls.root_lab_store = Location.objects.create(
            name='Stock Register Root Lab Store',
            location_type=LocationType.STORE,
            parent_location=cls.root_lab,
            is_store=True,
        )
        cls.csit_lab_store = Location.objects.create(
            name='Stock Register CSIT Lab Store',
            location_type=LocationType.STORE,
            parent_location=cls.csit_store,
            is_store=True,
        )
        cls.central_register = StockRegister.objects.create(register_number='CSR-CENTRAL-1', register_type='CSR', store=cls.central_store)
        cls.root_lab_register = StockRegister.objects.create(register_number='CSR-ROOT-LAB-1', register_type='CSR', store=cls.root_lab_store)
        cls.csit_register = StockRegister.objects.create(register_number='CSR-CSIT-1', register_type='CSR', store=cls.csit_store)
        cls.csit_lab_register = StockRegister.objects.create(register_number='CSR-CSIT-LAB-1', register_type='CSR', store=cls.csit_lab_store)
        cls.ee_register = StockRegister.objects.create(register_number='DSR-EE-1', register_type='DSR', store=cls.ee_store)

    def setUp(self):
        self.client = APIClient()

    def _perm(self, codename):
        return Permission.objects.get(content_type__app_label='inventory', codename=codename)

    def _make_user(self, username, assigned_location):
        user = User.objects.create_user(username=username, password='pw')
        user.profile.assigned_locations.add(assigned_location)
        return user

    def _rows(self, response):
        data = response.data
        if isinstance(data, dict) and 'results' in data:
            return data['results']
        return data

    def _payload(self, *, register_number='CSR-NEW-1', register_type='CSR', store=None, is_active=True):
        return {
            'register_number': register_number,
            'register_type': register_type,
            'store': store or self.csit_store.id,
            'is_active': is_active,
        }

    def test_list_requires_domain_view_stock_registers_perm(self):
        user = self._make_user('stock_register_legacy_view', self.csit)
        user.user_permissions.add(self._perm('view_stockregister'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/stock-registers/')

        self.assertEqual(resp.status_code, 403)

    def test_scoped_list_only_returns_registers_within_accessible_locations(self):
        user = self._make_user('stock_register_scoped_view', self.csit)
        user.user_permissions.add(self._perm('view_stock_registers'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/stock-registers/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.csit_register.id, returned_ids)
        self.assertIn(self.csit_lab_register.id, returned_ids)
        self.assertNotIn(self.central_register.id, returned_ids)
        self.assertNotIn(self.root_lab_register.id, returned_ids)
        self.assertNotIn(self.ee_register.id, returned_ids)

    def test_main_store_assigned_user_sees_registers_within_same_standalone_unit(self):
        user = self._make_user('stock_register_central_store_view', self.central_store)
        user.user_permissions.add(self._perm('view_stock_registers'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/stock-registers/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.central_register.id, returned_ids)
        self.assertIn(self.root_lab_register.id, returned_ids)
        self.assertNotIn(self.csit_register.id, returned_ids)
        self.assertNotIn(self.csit_lab_register.id, returned_ids)
        self.assertNotIn(self.ee_register.id, returned_ids)

    def test_main_store_assigned_user_stays_same_standalone_scoped_even_with_global_distribution_permissions(self):
        user = self._make_user('stock_register_central_perm_scope', self.central_store)
        user.user_permissions.add(self._perm('view_stock_registers'))
        user.user_permissions.add(self._perm('view_global_distribution'))
        user.user_permissions.add(self._perm('manage_all_locations'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/stock-registers/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.central_register.id, returned_ids)
        self.assertIn(self.root_lab_register.id, returned_ids)
        self.assertNotIn(self.csit_register.id, returned_ids)
        self.assertNotIn(self.csit_lab_register.id, returned_ids)
        self.assertNotIn(self.ee_register.id, returned_ids)

    def test_department_main_store_sees_its_unit_registers_only(self):
        user = self._make_user('stock_register_csit_main_store_view', self.csit_store)
        user.user_permissions.add(self._perm('view_stock_registers'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/stock-registers/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.csit_register.id, returned_ids)
        self.assertIn(self.csit_lab_register.id, returned_ids)
        self.assertNotIn(self.central_register.id, returned_ids)
        self.assertNotIn(self.root_lab_register.id, returned_ids)
        self.assertNotIn(self.ee_register.id, returned_ids)

    def test_non_main_store_user_only_sees_own_registers(self):
        user = self._make_user('stock_register_csit_lab_store_view', self.csit_lab_store)
        user.user_permissions.add(self._perm('view_stock_registers'))

        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/inventory/stock-registers/')

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row['id'] for row in self._rows(resp)}
        self.assertIn(self.csit_lab_register.id, returned_ids)
        self.assertNotIn(self.csit_register.id, returned_ids)
        self.assertNotIn(self.central_register.id, returned_ids)
        self.assertNotIn(self.root_lab_register.id, returned_ids)
        self.assertNotIn(self.ee_register.id, returned_ids)

    def test_create_requires_domain_create_stock_registers_perm(self):
        user = self._make_user('stock_register_view_only', self.csit)
        user.user_permissions.add(self._perm('view_stock_registers'))

        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/inventory/stock-registers/', self._payload(register_number='CSR-CREATE-FAIL'), format='json')

        self.assertEqual(resp.status_code, 403)

    def test_create_allows_domain_create_stock_registers_perm_for_in_scope_store(self):
        user = self._make_user('stock_register_creator', self.csit)
        user.user_permissions.add(self._perm('create_stock_registers'))

        self.client.force_authenticate(user=user)
        resp = self.client.post('/api/inventory/stock-registers/', self._payload(register_number='CSR-CREATE-OK'), format='json')

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['store'], self.csit_store.id)

    def test_create_rejects_out_of_scope_store_even_with_create_perm(self):
        user = self._make_user('stock_register_creator_scoped', self.csit)
        user.user_permissions.add(self._perm('create_stock_registers'))

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            '/api/inventory/stock-registers/',
            self._payload(register_number='CSR-CREATE-OOS', store=self.ee_store.id),
            format='json',
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn('store', resp.data)

    def test_update_requires_domain_edit_stock_registers_perm(self):
        user = self._make_user('stock_register_view_patch', self.csit)
        user.user_permissions.add(self._perm('view_stock_registers'))

        self.client.force_authenticate(user=user)
        resp = self.client.patch(
            f'/api/inventory/stock-registers/{self.csit_register.id}/',
            {'register_number': 'CSR-PATCH-NOPE'},
            format='json',
        )

        self.assertEqual(resp.status_code, 403)

    def test_update_allows_domain_edit_stock_registers_perm(self):
        user = self._make_user('stock_register_editor', self.csit)
        user.user_permissions.add(self._perm('edit_stock_registers'))

        self.client.force_authenticate(user=user)
        resp = self.client.patch(
            f'/api/inventory/stock-registers/{self.csit_register.id}/',
            {'register_number': 'CSR-PATCH-OK'},
            format='json',
        )

        self.assertEqual(resp.status_code, 200)
        self.csit_register.refresh_from_db()
        self.assertEqual(self.csit_register.register_number, 'CSR-PATCH-OK')

    def test_close_requires_domain_edit_stock_registers_perm(self):
        user = self._make_user('stock_register_close_view_only', self.csit_store)
        user.user_permissions.add(self._perm('view_stock_registers'))

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            f'/api/inventory/stock-registers/{self.csit_register.id}/close/',
            {'reason': 'Closing for audit'},
            format='json',
        )

        self.assertEqual(resp.status_code, 403)

    def test_close_sets_closed_metadata_and_deactivates_register(self):
        user = self._make_user('stock_register_closer', self.csit_store)
        user.user_permissions.add(self._perm('edit_stock_registers'))

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            f'/api/inventory/stock-registers/{self.csit_register.id}/close/',
            {'reason': 'Ledger complete'},
            format='json',
        )

        self.assertEqual(resp.status_code, 200)
        self.csit_register.refresh_from_db()
        self.assertFalse(self.csit_register.is_active)
        self.assertEqual(self.csit_register.closed_reason, 'Ledger complete')
        self.assertEqual(self.csit_register.closed_by, user)
        self.assertIsNotNone(self.csit_register.closed_at)

    def test_close_allows_blank_reason(self):
        user = self._make_user('stock_register_close_blank_reason', self.csit_store)
        user.user_permissions.add(self._perm('edit_stock_registers'))

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            f'/api/inventory/stock-registers/{self.csit_register.id}/close/',
            {'reason': ''},
            format='json',
        )

        self.assertEqual(resp.status_code, 200)
        self.csit_register.refresh_from_db()
        self.assertEqual(self.csit_register.closed_reason, '')

    def test_reopen_reactivates_register_and_clears_close_metadata(self):
        user = self._make_user('stock_register_reopener', self.csit_store)
        user.user_permissions.add(self._perm('edit_stock_registers'))
        self.csit_register.is_active = False
        self.csit_register.closed_reason = 'End of year close'
        self.csit_register.closed_by = user
        self.csit_register.closed_at = timezone.now()
        self.csit_register.save(update_fields=['is_active', 'closed_reason', 'closed_by', 'closed_at'])

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            f'/api/inventory/stock-registers/{self.csit_register.id}/reopen/',
            {'reason': 'Audit resumed'},
            format='json',
        )

        self.assertEqual(resp.status_code, 200)
        self.csit_register.refresh_from_db()
        self.assertTrue(self.csit_register.is_active)
        self.assertEqual(self.csit_register.closed_reason, 'End of year close')
        self.assertEqual(self.csit_register.closed_by, user)
        self.assertIsNotNone(self.csit_register.closed_at)
        self.assertEqual(self.csit_register.reopened_reason, 'Audit resumed')
        self.assertEqual(self.csit_register.reopened_by, user)
        self.assertIsNotNone(self.csit_register.reopened_at)

    def test_delete_requires_domain_delete_stock_registers_perm(self):
        user = self._make_user('stock_register_editor_no_delete', self.csit)
        user.user_permissions.add(self._perm('edit_stock_registers'))

        self.client.force_authenticate(user=user)
        resp = self.client.delete(f'/api/inventory/stock-registers/{self.csit_register.id}/')

        self.assertEqual(resp.status_code, 403)

    def test_delete_allows_domain_delete_stock_registers_perm(self):
        register = StockRegister.objects.create(register_number='CSR-DELETE-ME', register_type='CSR', store=self.csit_store)
        user = self._make_user('stock_register_deleter', self.csit)
        user.user_permissions.add(self._perm('delete_stock_registers'))

        self.client.force_authenticate(user=user)
        resp = self.client.delete(f'/api/inventory/stock-registers/{register.id}/')

        self.assertEqual(resp.status_code, 204)
        self.assertFalse(StockRegister.objects.filter(id=register.id).exists())
