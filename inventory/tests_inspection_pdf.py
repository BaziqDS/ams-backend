from datetime import date
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from .models import InspectionCertificate, InspectionItem, Location, LocationType
from .utils.pdf_generator import InspectionPDFGenerator


class InspectionPDFTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('pdf_admin', 'pdf@example.com', 'pw')
        cls.department = Location.objects.create(
            name='PDF Test Department', location_type=LocationType.DEPARTMENT, is_standalone=True,
        )
        cls.certificate = InspectionCertificate.objects.create(
            contract_no='PDF/2026/001', contract_date=date(2026, 10, 30),
            contractor_name='Test Supplier', contractor_address=None,
            indenter='Test Indenter', indent_no='IND-001', department=cls.department,
        )
        cls.row = InspectionItem.objects.create(
            inspection_certificate=cls.certificate,
            item_description='Cable <adapter> & accessories\nSecond line',
            tendered_quantity=2, accepted_quantity=1, rejected_quantity=1,
            remarks='Broken <connector> & damaged casing',
            stock_register_no='SR-01', stock_register_page_no='12',
            stock_entry_date=date(2026, 10, 30),
            central_register_no='CR-01', central_register_page_no='21',
        )

    def test_pdf_endpoint_returns_pdf_without_writing_contract_filename(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        # Even slash-containing contract numbers must render to a response buffer.
        with patch('inventory.utils.generator.InspectionCertificateGenerator.__init__', side_effect=AssertionError('Disk-writing constructor must not run')):
            response = client.get(f'/api/inventory/inspections/{self.certificate.pk}/view_pdf/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF-'))
        self.assertTrue(response.content.rstrip().endswith(b'%%EOF'))
        self.assertIn('inline;', response['Content-Disposition'])

    def test_adapter_maps_optional_values_quantities_registers_and_escapes_plain_text(self):
        generator = InspectionPDFGenerator(self.certificate)
        self.assertEqual(generator.data['date'], '30/10/2026')
        self.assertEqual(generator.data['contractor_address'], '')
        self.assertEqual(generator.data['stock_register_no'], 'SR-01')
        self.assertEqual(generator.data['dead_stock_page_nos'], '21')
        self.assertEqual(generator.item_data['descriptions'], ['Cable &lt;adapter&gt; &amp; accessories<br/>Second line'])
        self.assertEqual(generator.item_data['acct_unit'], [''])
        self.assertEqual(generator.item_data['a_quantity'], [1])
        self.assertEqual(generator.rejected_item_data['item_no'], [1])
        self.assertIn('&lt;connector&gt;', generator.rejected_item_data['reasons'][0])

    def test_empty_draft_renders_and_pdf_endpoint_requires_authentication(self):
        self.certificate.items.all().delete()
        output = BytesIO()
        InspectionPDFGenerator(self.certificate).generate(output)
        self.assertTrue(output.getvalue().startswith(b'%PDF-'))
        response = APIClient().get(f'/api/inventory/inspections/{self.certificate.pk}/view_pdf/')
        self.assertIn(response.status_code, [401, 403])
