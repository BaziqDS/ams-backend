from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient


class NotificationSummaryContractTests(TestCase):
    def test_summary_includes_same_alerts_as_panel_with_consistent_counts(self):
        client = APIClient()
        user = User.objects.create_user(username='summary-user')
        client.force_authenticate(user)
        summary = client.get('/api/notifications/summary/')
        alerts = client.get('/api/notifications/alerts/')
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.data['alerts'], alerts.data)
        self.assertEqual(summary.data['open_alerts'], len(summary.data['alerts']))
