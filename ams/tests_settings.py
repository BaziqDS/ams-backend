import os
import runpy
from pathlib import Path
from unittest.mock import patch

from decouple import Config, RepositoryEmpty
from django.test import SimpleTestCase


class ExplicitSettingsTests(SimpleTestCase):
    def load_settings(self, **overrides):
        values = {
            'SECRET_KEY': 'settings-test-secret',
            'DB_NAME': 'ams',
            'DB_USER': 'ams',
            'DB_PASSWORD': 'settings-test-password',
            'FRONTEND_URL': 'https://ams.example.com',
            'CORS_ALLOWED_ORIGINS': 'https://ams.example.com',
            **overrides,
        }
        # Isolate settings from both the developer's .env and process settings.
        with patch.dict(os.environ, values, clear=True):
            with patch('decouple.config', Config(RepositoryEmpty())):
                return runpy.run_path(str(Path(__file__).with_name('settings.py')))

    def test_defaults_use_postgresql_and_secure_cookies_without_debug(self):
        configured = self.load_settings()
        self.assertEqual(configured['DATABASES']['default']['ENGINE'], 'django.db.backends.postgresql')
        self.assertFalse(configured['DEBUG'])
        for name in ['COOKIE_SECURE', 'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE']:
            self.assertTrue(configured[name])
        self.assertEqual(configured['CSRF_TRUSTED_ORIGINS'], ['https://ams.example.com'])

    def test_debug_does_not_change_cookie_security_or_database(self):
        configured = self.load_settings(DEBUG='True')
        self.assertTrue(configured['DEBUG'])
        self.assertTrue(configured['COOKIE_SECURE'])
        self.assertEqual(configured['DATABASES']['default']['ENGINE'], 'django.db.backends.postgresql')

    def test_http_cookies_and_multiple_origins_can_be_configured_explicitly(self):
        configured = self.load_settings(
            COOKIE_SECURE='False',
            CORS_ALLOWED_ORIGINS='http://localhost:3000,http://127.0.0.1:3000',
            CSRF_TRUSTED_ORIGINS='http://localhost:3000,http://127.0.0.1:3000',
        )
        self.assertFalse(configured['DEBUG'])
        for name in ['COOKIE_SECURE', 'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE']:
            self.assertFalse(configured[name])
        expected = ['http://localhost:3000', 'http://127.0.0.1:3000']
        self.assertEqual(configured['CORS_ALLOWED_ORIGINS'], expected)
        self.assertEqual(configured['CSRF_TRUSTED_ORIGINS'], expected)
