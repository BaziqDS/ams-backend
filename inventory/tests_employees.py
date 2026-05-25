from django.contrib.auth.models import Permission, User
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import Location, LocationType, Person


class EmployeeApiPermissionAndScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = Location.objects.create(
            name="Employee Scope Root",
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
        )
        cls.dept_a = Location.objects.create(
            name="Employee Dept A",
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.dept_b = Location.objects.create(
            name="Employee Dept B",
            location_type=LocationType.DEPARTMENT,
            parent_location=cls.root,
            is_standalone=True,
        )
        cls.employee_a = Person.objects.create(
            perse_number="PERSE-A-001",
            name="Dept A Employee",
            designation="Professor",
            department="Dept A",
        )
        cls.employee_a.standalone_locations.add(cls.dept_a)
        cls.employee_b = Person.objects.create(
            perse_number="PERSE-B-001",
            name="Dept B Employee",
            designation="Lab Engineer",
            department="Dept B",
        )
        cls.employee_b.standalone_locations.add(cls.dept_b)

    def setUp(self):
        self.client = APIClient()

    def _perm(self, codename):
        return Permission.objects.get(content_type__app_label="inventory", codename=codename)

    def _make_user(self, username):
        return User.objects.create_user(username=username, password="pw")

    def _rows(self, response):
        data = response.data
        if isinstance(data, dict) and "results" in data:
            return data["results"]
        return data

    def test_list_accepts_legacy_person_view_permission_but_requires_some_employee_read(self):
        user = self._make_user("employee_legacy_viewer")
        user.user_permissions.add(self._perm("view_person"))
        user.profile.assigned_locations.add(self.dept_a)

        self.client.force_authenticate(user=user)
        resp = self.client.get("/api/inventory/employees/")
        self.assertEqual(resp.status_code, 200)

        user.user_permissions.remove(self._perm("view_person"))
        resp = self.client.get("/api/inventory/employees/")
        self.assertEqual(resp.status_code, 403)

    def test_scoped_list_returns_employees_for_assigned_standalone_only(self):
        user = self._make_user("employee_scoped_viewer")
        user.user_permissions.add(self._perm("view_employees"))
        user.profile.assigned_locations.add(self.dept_a)

        self.client.force_authenticate(user=user)
        resp = self.client.get("/api/inventory/employees/")

        self.assertEqual(resp.status_code, 200)
        returned_ids = {row["id"] for row in self._rows(resp)}
        self.assertIn(self.employee_a.id, returned_ids)
        self.assertNotIn(self.employee_b.id, returned_ids)

    def test_create_requires_employee_create_permission(self):
        user = self._make_user("employee_view_only")
        user.user_permissions.add(self._perm("view_employees"))
        user.profile.assigned_locations.add(self.dept_a)

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            "/api/inventory/employees/",
            {
                "name": "Blocked Employee",
                "perse_number": "PERSE-BLOCKED-001",
                "designation": "Lecturer",
                "department": "Dept A",
                "standalone_locations": [self.dept_a.id],
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 403)

    def test_create_allows_employee_create_in_assigned_standalone_scope(self):
        user = self._make_user("employee_creator")
        user.user_permissions.add(self._perm("view_employees"))
        user.user_permissions.add(self._perm("create_employees"))
        user.profile.assigned_locations.add(self.dept_a)

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            "/api/inventory/employees/",
            {
                "name": "Created Employee",
                "perse_number": "PERSE-CREATED-001",
                "designation": "Lecturer",
                "department": "Dept A",
                "standalone_locations": [self.dept_a.id],
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(
            Person.objects.filter(
                name="Created Employee",
                perse_number="PERSE-CREATED-001",
                standalone_locations=self.dept_a,
            ).exists()
        )

    def test_create_requires_perse_number(self):
        user = self._make_user("employee_creator_no_perse")
        user.user_permissions.add(self._perm("view_employees"))
        user.user_permissions.add(self._perm("create_employees"))
        user.profile.assigned_locations.add(self.dept_a)

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            "/api/inventory/employees/",
            {
                "name": "No PERSE Employee",
                "designation": "Lecturer",
                "standalone_locations": [self.dept_a.id],
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("perse_number", resp.data)

    def test_create_rejects_employee_outside_assigned_standalone_scope(self):
        user = self._make_user("employee_out_of_scope_creator")
        user.user_permissions.add(self._perm("view_employees"))
        user.user_permissions.add(self._perm("create_employees"))
        user.profile.assigned_locations.add(self.dept_a)

        self.client.force_authenticate(user=user)
        resp = self.client.post(
            "/api/inventory/employees/",
            {
                "name": "Out Of Scope Employee",
                "perse_number": "PERSE-OOS-001",
                "designation": "Lecturer",
                "department": "Dept B",
                "standalone_locations": [self.dept_b.id],
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Person.objects.filter(name="Out Of Scope Employee").exists())
