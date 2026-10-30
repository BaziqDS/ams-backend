from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient


class VoicePermitTests(TestCase):
    @override_settings(VOICE_MINUTE_LIMIT=2, VOICE_DAILY_LIMIT=3)
    def test_requires_enabled_authenticated_user_and_enforces_shared_quota(self):
        client = APIClient()
        self.assertEqual(client.post('/auth/voice-permit/').status_code, 401)
        user = User.objects.create_user(username='voice-user')
        client.force_authenticate(user)
        self.assertEqual(client.post('/auth/voice-permit/').status_code, 403)
        user.profile.ai_enabled = True
        user.profile.save(update_fields=['ai_enabled'])
        self.assertEqual(client.post('/auth/voice-permit/').status_code, 200)
        second_client = APIClient()
        second_client.force_authenticate(user)
        self.assertEqual(second_client.post('/auth/voice-permit/').status_code, 200)
        self.assertEqual(client.post('/auth/voice-permit/').status_code, 429)
