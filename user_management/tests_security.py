from django.contrib.auth.models import Permission, User
from django.test import TestCase
from rest_framework.test import APIClient

from inventory.models import Location, LocationType


class AccountBoundaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='boundary-user', password='pw')
        self.other = User.objects.create_user(username='boundary-other', password='pw')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_current_user_can_edit_name_but_cannot_promote_themselves(self):
        response = self.client.patch('/auth/users/me/', {
            'first_name': 'Allowed', 'is_superuser': True, 'is_staff': True,
        }, format='json')
        self.assertEqual(response.status_code, 200)
        current = self.client.get('/auth/users/me/').data
        self.assertEqual(current['first_name'], 'Allowed')
        self.assertFalse(current['is_superuser'])
        self.assertFalse(current['is_staff'])

    def test_auth_api_cannot_read_or_edit_another_account(self):
        path = f'/auth/users/{self.other.pk}/'
        self.assertIn(self.client.get(path).status_code, (403, 404))
        self.assertIn(self.client.patch(path, {'first_name': 'Intruder'}, format='json').status_code, (403, 404))

    def test_own_profile_cannot_assign_locations_but_can_change_ai_preference(self):
        root = Location.objects.create(name='Boundary root', location_type=LocationType.DEPARTMENT)
        response = self.client.patch(f'/api/users/profiles/{self.user.profile.pk}/', {
            'assigned_locations': [root.pk], 'ai_enabled': True, 'is_active': False,
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['assigned_locations'], [])
        self.assertTrue(response.data['ai_enabled'])
        self.assertTrue(response.data['is_active'])

    def test_profile_manager_cannot_assign_locations_without_assignment_permission(self):
        root = Location.objects.create(name='Manager root', location_type=LocationType.DEPARTMENT)
        self.user.profile.assigned_locations.set([root])
        self.other.profile.assigned_locations.set([root])
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='user_management',
            codename__in=['view_user_accounts', 'edit_user_accounts'],
        ))
        response = self.client.patch(f'/api/users/profiles/{self.other.profile.pk}/', {
            'assigned_locations': [root.pk],
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_superuser_can_assign_another_profile_location(self):
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        root = Location.objects.create(name='Admin root', location_type=LocationType.DEPARTMENT)
        response = self.client.patch(f'/api/users/profiles/{self.other.profile.pk}/', {
            'assigned_locations': [root.pk],
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['assigned_locations'], [root.pk])

    def test_self_cannot_assign_direct_permissions_even_with_role_assignment_permission(self):
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='user_management',
            codename__in=['edit_user_accounts', 'assign_user_roles'],
        ))
        response = self.client.patch(f'/api/users/management/{self.user.pk}/', {
            'user_permissions_list': ['delete_user_accounts'],
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.user.user_permissions.filter(codename='delete_user_accounts').exists())

    def test_superuser_can_assign_direct_permissions_to_another_user(self):
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        response = self.client.patch(f'/api/users/management/{self.other.pk}/', {
            'user_permissions_list': ['view_user_accounts'],
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.other.user_permissions.filter(codename='view_user_accounts').exists())
