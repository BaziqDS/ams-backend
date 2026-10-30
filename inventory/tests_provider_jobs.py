from unittest.mock import Mock, patch
from io import StringIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from inventory.models import Category, Item, ItemInstance, InspectionCertificate, Location
from inventory.services.serial_import import SerialExtractionPending, extract_serials_with_llamaextract
from inventory.services.embeddings import EmbedResult, build_item_embedding_text, hash_text
from inventory.services import embeddings


class ProviderJobTests(TestCase):
    @override_settings(EMBEDDING_API_KEY='client-construction-test', EMBEDDING_TIMEOUT_SECONDS=15)
    def test_embedding_sdk_client_constructs_without_network_calls(self):
        with patch.object(embeddings, '_client', None):
            client = embeddings._get_client()
            try:
                self.assertIsNotNone(client)
                self.assertEqual(client.timeout, 15)
            finally:
                if client is not None:
                    client.close()

    def setUp(self):
        self.user = User.objects.create_superuser(username='provider-admin')
        self.root = Location.objects.create(name='Provider root', location_type='DEPARTMENT', is_standalone=True)
        self.store = self.root.auto_created_store
        parent = Category.objects.create(name='Provider parent', code='PP', tracking_type='INDIVIDUAL')
        self.category = Category.objects.create(name='Provider leaf', code='PL', parent_category=parent, tracking_type='INDIVIDUAL')
        self.item = Item.objects.create(name='Provider item', code='PITEM', category=self.category, acct_unit='Each')
        self.certificate = InspectionCertificate.objects.create(contract_no='PROVIDER-1', department=self.root)
        self.instance = ItemInstance.objects.create(item=self.item, current_location=self.store, inspection_certificate=self.certificate)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @override_settings(ITEM_SEARCH_HYBRID_ENABLED=True)
    @patch('inventory.signals.embed_item')
    def test_saving_item_keeps_lexical_search_current_without_provider_work(self, embed):
        self.item.name = 'Updated searchable name'
        self.item.save()
        embed.assert_not_called()
        self.item.refresh_from_db()
        self.assertIn('updat', str(self.item.search_text))

    @patch('inventory.views.instance_views.extract_candidates_from_upload', side_effect=SerialExtractionPending('job-1'))
    @patch('inventory.views.instance_views.poll_serial_extraction')
    def test_document_preview_polls_without_reupload_and_preserves_matching(self, poll, extract):
        path = '/api/inventory/item-instances/serial-import-preview/'
        data = {'item': self.item.pk, 'store_ids': [self.store.pk], 'inspection_contract_no': self.certificate.contract_no}
        response = self.client.post(path, {**data, 'file': SimpleUploadedFile('serial.pdf', b'pdf')}, format='multipart')
        self.assertEqual(response.status_code, 202)
        poll.assert_not_called()
        ticket = response.data['extraction_ticket']
        poll.side_effect = SerialExtractionPending('job-1')
        self.assertEqual(self.client.post(path, {**data, 'extraction_ticket': ticket}, format='json').status_code, 202)
        poll.side_effect = None
        poll.return_value = [{'row_number': 1, 'serial_number': 'SERIAL-123', 'raw_text': 'SERIAL-123'}]
        response = self.client.post(path, {**data, 'extraction_ticket': ticket}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['can_apply'])
        self.assertEqual(response.data['lines'][0]['instance'], self.instance.pk)
        self.assertEqual(extract.call_count, 1)
        self.instance.refresh_from_db()
        self.assertFalse(self.instance.serial_number)  # Preview never applies assignments.
        self.assertEqual(self.client.post(path, {**data, 'extraction_ticket': ticket + 'tampered'}, format='json').status_code, 400)
        other = User.objects.create_superuser(username='other-provider-admin')
        self.client.force_authenticate(other)
        self.assertEqual(self.client.post(path, {**data, 'extraction_ticket': ticket}, format='json').status_code, 400)

    @patch('inventory.services.serial_import.config')
    @patch('requests.post')
    @patch('requests.get')
    def test_provider_submission_returns_job_without_waiting_for_completion(self, get, post, config):
        config.side_effect = lambda key, default='': {'LLAMA_CLOUD_API_KEY': 'key', 'LLAMA_CLOUD_PROJECT_ID': 'project'}.get(key, default)
        post.side_effect = [Mock(json=lambda: {'id': 'file-1'}), Mock(json=lambda: {'id': 'job-1'})]
        with self.assertRaises(SerialExtractionPending) as pending:
            extract_serials_with_llamaextract(SimpleUploadedFile('serial.pdf', b'pdf'), '.pdf')
        self.assertEqual(pending.exception.job_id, 'job-1')
        get.assert_not_called()

    @patch('inventory.management.commands.backfill_item_embeddings._write_embedding', return_value=True)
    @patch('inventory.management.commands.backfill_item_embeddings.embed_item')
    def test_background_indexing_publishes_current_vector_and_skips_unchanged_items(self, embed, write):
        text = build_item_embedding_text(self.item)
        embed.return_value = EmbedResult(text, hash_text(text), [0.0])
        call_command('backfill_item_embeddings', stdout=StringIO())
        self.item.refresh_from_db()
        self.assertEqual(self.item.embedded_text_hash, hash_text(text))
        write.assert_called_once()
        with patch('inventory.management.commands.backfill_item_embeddings._has_embedding', return_value=True):
            call_command('backfill_item_embeddings', stdout=StringIO())
        self.assertEqual(embed.call_count, 1)

    @patch('inventory.management.commands.backfill_item_embeddings._write_embedding')
    @patch('inventory.management.commands.backfill_item_embeddings.embed_item')
    def test_background_indexing_does_not_publish_stale_results_after_concurrent_edit(self, embed, write):
        text = build_item_embedding_text(self.item)
        def provider_result(item):
            Item.objects.filter(pk=item.pk).update(name='Edited during provider call')
            return EmbedResult(text, hash_text(text), [0.0])
        embed.side_effect = provider_result
        call_command('backfill_item_embeddings', stdout=StringIO())
        write.assert_not_called()
        self.item.refresh_from_db()
        self.assertFalse(self.item.embedded_text_hash)
