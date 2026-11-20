import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ia_instagram_publish as publisher


class PublicationSafety(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.folder.name)
        self.item = {'id': 'test', 'video_id': 'a' * 32, 'approved': True, 'caption': 'Pilote IA'}
        self.client = Mock()
        self.client.find_published.return_value = None
        self.client.create_and_upload.return_value = '123'

    def tearDown(self):
        os.chdir(self.cwd)
        self.folder.cleanup()

    def test_journal_is_saved_before_publish_and_blocks_ambiguous_retry(self):
        def uncertain(*args):
            journal = json.loads(Path('historique/instagram/ia-bureau-test.json').read_text())
            self.assertEqual(journal['container_id'], '123')
            self.assertGreater(persist.call_count, 0)
            raise publisher.MetaError('Réponse ambiguë')
        with patch.object(publisher, 'persist') as persist, \
                patch.object(publisher, 'download_video', return_value=b'mp4'), \
                patch.object(publisher, 'publish', side_effect=uncertain) as publish:
            with self.assertRaises(publisher.MetaError):
                publisher.publish_item(self.client, 'account', self.item, '1:1')
            with self.assertRaises(publisher.MetaError):
                publisher.publish_item(self.client, 'account', self.item, '1:2')
            self.assertEqual(publish.call_count, 1)
            self.assertEqual(self.client.create_and_upload.call_count, 1)

    def test_existing_reel_does_not_upload_again(self):
        self.client.find_published.return_value = '456'
        with patch.object(publisher, 'persist'), patch.object(publisher, 'publish'):
            publisher.publish_item(self.client, 'account', self.item, '1:1')
        self.client.create_and_upload.assert_not_called()

    def test_unapproved_episode_is_rejected(self):
        self.item['approved'] = False
        with self.assertRaises(ValueError):
            publisher.validate_manifest({'account': 'decisionsandco', 'episodes': [self.item]})
