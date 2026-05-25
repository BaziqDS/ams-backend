from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inventory.models import InspectionCertificate, Location, LocationType
from inventory.models.inspection_model import InspectionStage


class InspectionFinanceScopeContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = Location.objects.create(
            name="Inspection Contract Root",
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        cls.electrical = Location.objects.create(
            name="Inspection Contract Electrical",
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.csit = Location.objects.create(
            name="Inspection Contract CSIT",
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.electrical_certificate = cls._certificate("IC-CONTRACT-EE", cls.electrical)
        cls.csit_certificate = cls._certificate("IC-CONTRACT-CSIT", cls.csit)

    @classmethod
    def _certificate(cls, contract_no, department):
        today = timezone.now().date()
        return InspectionCertificate.objects.create(
            date=today,
            contract_no=contract_no,
            contract_date=today,
            contractor_name="Scope Supplier",
            contractor_address="Block A",
            indenter="Scope Indenter",
            indent_no=f"IND-{contract_no}",
            department=department,
            date_of_delivery=today,
            delivery_type="FULL",
            remarks="",
            inspected_by="Scope Inspector",
            date_of_inspection=today,
            consignee_name="Scope Consignee",
            consignee_designation="Manager",
        )

    def setUp(self):
        self.client = APIClient()

    def _perm(self, codename):
        return Permission.objects.get(content_type__app_label="inventory", codename=codename)

    def _make_user(self, username, assigned_location):
        user = User.objects.create_user(username=username, password="pw")
        user.user_permissions.add(self._perm("view_inspectioncertificate"))
        user.profile.assigned_locations.add(assigned_location)
        return user

    def _ids(self, response):
        data = response.data
        rows = data["results"] if isinstance(data, dict) and "results" in data else data
        return {row["id"] for row in rows}

    def test_review_finance_action_permission_does_not_bypass_location_scope(self):
        user = self._make_user("contract_finance_scoped", self.electrical)
        user.user_permissions.add(self._perm("review_finance"))

        self.client.force_authenticate(user=user)
        response = self.client.get("/api/inventory/inspections/")

        self.assertEqual(response.status_code, 200)
        returned_ids = self._ids(response)
        self.assertIn(self.electrical_certificate.id, returned_ids)
        self.assertNotIn(self.csit_certificate.id, returned_ids)

    def test_view_all_inspections_permission_bypasses_location_scope(self):
        user = self._make_user("contract_finance_global", self.electrical)
        user.user_permissions.add(self._perm("view_all_inspections"))

        self.client.force_authenticate(user=user)
        response = self.client.get("/api/inventory/inspections/")

        self.assertEqual(response.status_code, 200)
        returned_ids = self._ids(response)
        self.assertIn(self.electrical_certificate.id, returned_ids)
        self.assertIn(self.csit_certificate.id, returned_ids)

    def test_view_all_inspections_user_can_filter_by_location(self):
        user = self._make_user("contract_finance_global_filtered", self.electrical)
        user.user_permissions.add(self._perm("view_all_inspections"))

        self.client.force_authenticate(user=user)
        response = self.client.get(f"/api/inventory/inspections/?location={self.electrical.id}")

        self.assertEqual(response.status_code, 200)
        returned_ids = self._ids(response)
        self.assertIn(self.electrical_certificate.id, returned_ids)
        self.assertNotIn(self.csit_certificate.id, returned_ids)

    def test_superuser_can_filter_inspections_by_location(self):
        user = User.objects.create_superuser(
            username="inspection_superuser_filtered",
            email="inspection-super@example.com",
            password="pw",
        )

        self.client.force_authenticate(user=user)
        response = self.client.get(f"/api/inventory/inspections/?location={self.csit.id}")

        self.assertEqual(response.status_code, 200)
        returned_ids = self._ids(response)
        self.assertIn(self.csit_certificate.id, returned_ids)
        self.assertNotIn(self.electrical_certificate.id, returned_ids)

    def test_change_permission_without_review_finance_cannot_complete_inspection(self):
        certificate = self._certificate("IC-CONTRACT-FINANCE", self.electrical)
        certificate.stage = InspectionStage.FINANCE_REVIEW
        certificate.status = "IN_PROGRESS"
        certificate.save(update_fields=["stage", "status"])
        user = self._make_user("contract_change_without_finance", self.electrical)
        user.user_permissions.add(self._perm("change_inspectioncertificate"))

        self.client.force_authenticate(user=user)
        response = self.client.post(f"/api/inventory/inspections/{certificate.id}/complete/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["detail"], "You do not have permission to complete finance reviews.")
        certificate.refresh_from_db()
        self.assertEqual(certificate.stage, InspectionStage.FINANCE_REVIEW)
