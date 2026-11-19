import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from cryptography.exceptions import InvalidTag
import yaml

import instagram_reels as reel


class RachelInstagramTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.archive = root / "archive"
        self.journal = root / "journal" / "abc123def45.json"
        self.video = root / "video.mp4"
        self.video.write_bytes(b"original montage")
        self.script = {"titre": "Les factures et l’IA", "resume": "Un exemple pour les PME."}
        self.client = Mock()
        self.client.token = "test-token"
        self.client.account_id.return_value = "123"
        self.client.find_published.return_value = None
        self.client.create_and_upload.return_value = "456"
        self.client.status.return_value = "FINISHED"
        self.client.publish.return_value = "789"
        self.client.verify.return_value = ("https://www.instagram.com/reel/example/", True)
        archive = patch.object(reel, "ARCHIVE", self.archive)
        archive.start()
        self.addCleanup(archive.stop)
        with patch.dict(reel.os.environ, {"INSTAGRAM_ACCESS_TOKEN": "test-token"}):
            reel.stage_reel(self.video, self.script, "abc123def45")
        self.manifest, self.metadata = reel.read_archive()

    def test_archive_preserves_the_exact_montage_and_binds_metadata(self):
        data = (self.archive / "reel.enc").read_bytes()
        self.assertNotIn(self.video.read_bytes(), data)
        with self.assertRaises(InvalidTag):
            reel.archive_cipher(self.client.token).decrypt(data[:12], data[12:], b"altered metadata")
        entry = {"youtube_id": "abc123def45"}
        reel.prepare(self.client, self.manifest, self.metadata, self.journal, entry, "1:1")
        self.client.create_and_upload.assert_called_once_with(
            "123", self.manifest["caption"], self.video.read_bytes())
        self.assertEqual(json.loads(self.journal.read_text())["statut"], "publication_demandee")
        self.client.publish.assert_not_called()

    def test_successfully_published_reel_is_not_sent_again(self):
        entry = {"youtube_id": "abc123def45"}
        reel.prepare(self.client, self.manifest, self.metadata, self.journal, entry, "1:1")
        reel.publish(self.client, self.manifest, self.journal, entry, "1:1")
        entry = json.loads(self.journal.read_text())
        self.assertTrue(entry["label_ia"])
        self.assertEqual(entry["permalink"], self.client.verify.return_value[0])
        reel.prepare(self.client, self.manifest, self.metadata, self.journal, entry, "2:1")
        reel.publish(self.client, self.manifest, self.journal, entry, "2:1")
        self.client.publish.assert_called_once_with("123", "456")

    def test_uncertain_publication_is_never_repeated(self):
        entry = {"youtube_id": "abc123def45"}
        reel.prepare(self.client, self.manifest, self.metadata, self.journal, entry, "1:1")
        self.client.publish.side_effect = reel.MetaError("Timeout")
        with self.assertRaisesRegex(reel.MetaError, "Publication non confirmée"):
            reel.publish(self.client, self.manifest, self.journal, entry, "1:1")
        with self.assertRaisesRegex(reel.MetaError, "déjà été demandée"):
            reel.prepare(self.client, self.manifest, self.metadata, self.journal, entry, "2:1")
        self.client.find_published.return_value = "789"
        reel.prepare(self.client, self.manifest, self.metadata, self.journal, entry, "2:1")
        reel.publish(self.client, self.manifest, self.journal, entry, "2:1")
        self.assertEqual(json.loads(self.journal.read_text())["media_id"], "789")
        self.client.publish.assert_called_once()

    def test_meta_upload_uses_returned_url_and_ai_label(self):
        client = reel.Instagram("test-token")
        uri = "https://rupload.facebook.com/ig-api-upload/456"
        with patch.object(client, "request", side_effect=[{"id": "456", "uri": uri}, {"success": True}]) as request:
            self.assertEqual(client.create_and_upload("123", "Légende", b"mp4"), "456")
            self.assertEqual(request.call_args_list[0].kwargs["data"]["is_ai_generated"], "true")
            self.assertEqual(request.call_args_list[1].args, ("POST", uri))
            self.assertEqual(request.call_args_list[1].kwargs["upload_headers"]["file_size"], "3")

    def test_only_rachel_workflows_call_instagram_and_checkpoint_precedes_publication(self):
        workflow_dir = Path(".github/workflows")
        for kind in ("avatar", "prospective"):
            workflow = yaml.safe_load((workflow_dir / f"short_video_{kind}.yml").read_text())
            self.assertEqual(workflow["jobs"]["instagram"]["needs"], f"short-video-{kind}")
            self.assertIn("instagram_artifact_id", workflow["jobs"]["instagram"]["if"])
        static = yaml.safe_load((workflow_dir / "short_video.yml").read_text())
        self.assertNotIn("instagram", static["jobs"])
        workflow = yaml.safe_load((workflow_dir / "instagram_reels.yml").read_text())
        steps = workflow["jobs"]["instagram-reel"]["steps"]
        index = next(i for i, step in enumerate(steps) if step.get("run") == "python instagram_reels.py publish")
        self.assertIn("persist_instagram_journal", steps[index - 1]["run"])
        self.assertEqual(steps[index + 1]["if"], "always()")
