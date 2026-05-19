from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import Location, LocationType


class UserCreationSetupContractTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            username="user_creation_admin",
            email="admin@example.com",
            password="pw",
        )
        self.client.force_authenticate(user=self.admin)

    def test_create_user_without_roles_or_locations_is_rejected_when_setup_is_empty(self):
        resp = self.client.post(
            "/api/users/management/",
            {
                "username": "pending.user",
                "email": "pending@example.com",
                "first_name": "Pending",
                "last_name": "User",
                "password": "pw",
                "groups": [],
                "assigned_locations": [],
                "is_active": True,
            },
            format="json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("groups", resp.data)
        self.assertIn("assigned_locations", resp.data)
        self.assertFalse(User.objects.filter(username="pending.user").exists())

    def test_create_user_without_locations_is_rejected_when_locations_exist(self):
        Location.objects.create(
            name="NED Root",
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )

        resp = self.client.post(
            "/api/users/management/",
            {
                "username": "unscoped.user",
                "email": "unscoped@example.com",
                "first_name": "Unscoped",
                "last_name": "User",
                "password": "pw",
                "groups": [],
                "assigned_locations": [],
                "is_active": True,
            },
            format="json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("assigned_locations", resp.data)

    def test_create_user_without_roles_is_rejected_when_location_is_assigned(self):
        location = Location.objects.create(
            name="NED Root For User",
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )

        resp = self.client.post(
            "/api/users/management/",
            {
                "username": "norole.user",
                "email": "norole@example.com",
                "first_name": "No",
                "last_name": "Role",
                "password": "pw",
                "groups": [],
                "assigned_locations": [location.id],
                "is_active": True,
            },
            format="json",
            HTTP_HOST="localhost",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("groups", resp.data)
