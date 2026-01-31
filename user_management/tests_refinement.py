from django.test import TestCase
from django.contrib.auth.models import User, Permission
from django.urls import reverse
from rest_framework.test import APIClient
from user_management.models import UserProfile
from inventory.models.location_model import Location, LocationType

class UserManagementRefinementTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        
        # Create Root Location
        self.root_loc = Location.objects.create(
            name="University Root",
            code="ROOT-01",
            location_type=LocationType.OTHER,
            is_standalone=True
        )
        
        # Create CSIT Department (Standalone)
        self.csit_dept = Location.objects.create(
            name="CSIT Department",
            code="DEPT-CSIT",
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
            parent_location=self.root_loc
        )
        
        # Create CSIT Store (Descendant)
        self.csit_store = Location.objects.create(
            name="CSIT Store",
            code="STR-CSIT",
            location_type=LocationType.STORE,
            is_store=True,
            parent_location=self.csit_dept
        )
        
        # Create EE Department (Standalone)
        self.ee_dept = Location.objects.create(
            name="EE Department",
            code="DEPT-EE",
            location_type=LocationType.DEPARTMENT,
            is_standalone=True,
            parent_location=self.root_loc
        )
        
        # Create Users
        self.admin_user = User.objects.create_superuser(username='admin', password='password', email='admin@test.com')
        
        self.global_manager = User.objects.create_user(username='global_mgr', password='password')
        self.global_manager.user_permissions.add(
            Permission.objects.get(content_type__app_label='auth', codename='view_user'),
            Permission.objects.get(content_type__app_label='user_management', codename='view_all_user_accounts'),
            Permission.objects.get(content_type__app_label='inventory', codename='view_location')
        )
        
        self.csit_manager = User.objects.create_user(username='csit_mgr', password='password')
        self.csit_manager.user_permissions.add(
            Permission.objects.get(content_type__app_label='auth', codename='view_user'),
            Permission.objects.get(content_type__app_label='user_management', codename='view_user_accounts_assigned_location'),
            Permission.objects.get(content_type__app_label='inventory', codename='view_location'),
            Permission.objects.get(content_type__app_label='inventory', codename='view_scoped_distribution')
        )
        self.csit_manager.profile.assigned_locations.add(self.csit_dept)
        
        self.csit_staff = User.objects.create_user(username='csit_staff', password='password')
        self.csit_staff.profile.assigned_locations.add(self.csit_store)
        
        self.ee_staff = User.objects.create_user(username='ee_staff', password='password')
        self.ee_staff.profile.assigned_locations.add(self.ee_dept)

    def test_global_manager_sees_all_users(self):
        self.client.force_authenticate(user=self.global_manager)
        response = self.client.get('/api/users/management/')
        self.assertEqual(response.status_code, 200)
        usernames = [u['username'] for u in response.data]
        self.assertIn('csit_mgr', usernames)
        self.assertIn('csit_staff', usernames)
        self.assertIn('ee_staff', usernames)
        self.assertIn('global_mgr', usernames)

    def test_scoped_manager_sees_only_descendants(self):
        self.client.force_authenticate(user=self.csit_manager)
        response = self.client.get('/api/users/management/')
        self.assertEqual(response.status_code, 200)
        usernames = [u['username'] for u in response.data]
        
        # CSIT Manager is assigned to CSIT Dept.
        # CSIT Staff is assigned to CSIT Store (descendant of CSIT Dept).
        # Thus, CSIT Manager should see CSIT Staff and themselves.
        self.assertIn('csit_mgr', usernames)
        self.assertIn('csit_staff', usernames)
        
        # EE Staff is in EE Dept, which is NOT a descendant of CSIT Dept.
        self.assertNotIn('ee_staff', usernames)
        
        # Global Manager is NOT in CSIT.
        self.assertNotIn('global_mgr', usernames)

    def test_global_manager_sees_all_assignable_locations(self):
        self.client.force_authenticate(user=self.global_manager)
        response = self.client.get('/api/inventory/locations/assignable/')
        self.assertEqual(response.status_code, 200)
        location_codes = [l['code'] for l in response.data]
        self.assertIn('ROOT-01', location_codes)
        self.assertIn('DEPT-CSIT', location_codes)
        self.assertIn('DEPT-EE', location_codes)

    def test_scoped_manager_sees_only_scoped_assignable_locations(self):
        self.client.force_authenticate(user=self.csit_manager)
        response = self.client.get('/api/inventory/locations/assignable/')
        self.assertEqual(response.status_code, 200)
        location_codes = [l['code'] for l in response.data]
        
        self.assertIn('DEPT-CSIT', location_codes)
        self.assertIn('STR-CSIT', location_codes)
        
        self.assertNotIn('DEPT-EE', location_codes)
        self.assertNotIn('ROOT-01', location_codes)
