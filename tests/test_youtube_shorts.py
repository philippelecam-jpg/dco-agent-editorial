import copy
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import yaml

import youtube_short_policy as policy


def script():
    return {
        "titre": "Outlook piraté : ce que ça change",
        "accroche": "Outlook expose votre messagerie.",
        "texte_voix": "Outlook expose votre messagerie. Voici une conséquence.",
        "resume": "Outlook expose une donnée sensible. Une vérification est nécessaire.",
        "mots_cles": ["Outlook", "messagerie", "cybersécurité", "comptes", "accès"],
        "hashtags": ["Outlook", "Cyber", "IA", "Autre"],
    }


def response(data=None, headers=None):
    result = Mock()
    result.json.return_value = data or {}
    result.headers = headers or {}
    return result


class YouTubeRules(unittest.TestCase):
    def test_metadata_and_description(self):
        result = policy.metadata(script(), avatar=True)
        self.assertEqual(result["snippet"]["categoryId"], "28")
        self.assertEqual(result["snippet"]["defaultLanguage"], "fr")
        self.assertEqual(result["snippet"]["defaultAudioLanguage"], "fr")
        self.assertTrue(result["status"]["containsSyntheticMedia"])
        self.assertFalse(result["status"]["selfDeclaredMadeForKids"])
        self.assertEqual(len(result["snippet"]["description"].splitlines()[-1].split()), 3)
        self.assertIn("https://decisionsandco.com", result["snippet"]["description"])
        self.assertIn("DecisionsAndCo", result["snippet"]["tags"])

    def test_duplicate_legacy_titles_and_nonduplicates(self):
        old = [{"titre": "Outlook piraté, ce que ça change !"}]
        with self.assertRaisesRegex(ValueError, "Titre proche"):
            policy.reject_duplicate(script()["titre"], old)
        policy.reject_duplicate("Maintenance : contrôler une pièce défectueuse", old)
        self.assertIsNone(policy.record_date({"date": "inconnue"}))
        self.assertEqual(policy.record_date({"date": "2026-11-17T12:00:00"}).hour, 13)

    def test_hooks_and_titles_are_checked(self):
        with patch.object(policy, "unique_recent", return_value=[]):
            policy.prepare_script(script())
            invalid = dict(script(), titre="Et si une panne arrivait ?")
            with self.assertRaises(ValueError):
                policy.prepare_script(invalid)
            invalid = dict(script(), accroche="Pourquoi ?", texte_voix="Pourquoi ? Voici.")
            with self.assertRaises(ValueError):
                policy.prepare_script(invalid)

    def test_weekly_cadence_and_force(self):
        with tempfile.TemporaryDirectory() as folder:
            fixed = datetime(2026, 11, 23, 12, tzinfo=policy.PARIS)
            with patch.object(policy, "datetime", wraps=datetime) as clock, patch.object(policy, "unique_recent", return_value=[]):
                clock.now.return_value = fixed
                self.assertTrue(policy.publication_due("statique"))
                self.assertFalse(policy.publication_due("avatar"))
                with patch.dict(os.environ, {"FORCE_PUBLICATION": "true"}):
                    self.assertTrue(policy.publication_due("avatar"))
            rows = [{"date": (fixed - timedelta(days=0)).isoformat(), "video_id": "old"}]
            with patch.object(policy, "datetime", wraps=datetime) as clock, patch.object(policy, "unique_recent", return_value=rows):
                clock.now.return_value = fixed
                self.assertFalse(policy.publication_due("statique"))

    def test_probe_rejects_landscape_rotation_and_long_files(self):
        probe = {"streams": [{"codec_type": "video", "width": 1080, "height": 1920,
                              "sample_aspect_ratio": "1:1"}], "format": {"duration": "59.99"}}
        with patch.object(policy.subprocess, "run", return_value=Mock(stdout=json.dumps(probe))):
            self.assertEqual(policy.inspect_video(Path("test.mp4")), 59.99)
        for mutate in (
            lambda data: data["streams"][0].update(width=1920, height=1080),
            lambda data: data["format"].update(duration="60.1"),
            lambda data: data["streams"][0].update(side_data_list=[{"rotation": 90}]),
        ):
            invalid = copy.deepcopy(probe)
            mutate(invalid)
            with patch.object(policy.subprocess, "run", return_value=Mock(stdout=json.dumps(invalid))):
                with self.assertRaises(ValueError):
                    policy.inspect_video(Path("test.mp4"))

    def test_uploaded_video_survives_playlist_failure(self):
        data = script()
        data["_publication_plan"] = {"nom": "Cybersécurité et incidents", "id": "PL-test"}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "test.mp4")
            path.write_bytes(b"test")
            journal = Path(folder, "journal.json")
            with patch.object(policy, "JOURNAL", journal), patch.object(policy, "inspect_video"), \
                 patch.object(policy, "reject_duplicate"), \
                 patch.object(policy.requests, "post", return_value=response(headers={"Location": "https://example.org/upload"})), \
                 patch.object(policy.requests, "put", return_value=response({"id": "video-published"})), \
                 patch.object(policy, "attach_playlist", side_effect=requests.HTTPError("playlist error")):
                with self.assertRaises(requests.HTTPError):
                    policy.upload_short(path, data, "token", "avatar")
                self.assertEqual(json.loads(journal.read_text())[0]["video_id"], "video-published")
                self.assertEqual(json.loads(journal.read_text())[0]["statut"], "playlist_en_attente")
            with patch.object(policy, "JOURNAL", journal), patch.object(policy, "attach_playlist") as attach:
                policy.retry_playlists("token")
                attach.assert_called_once_with("token", "video-published", "PL-test")
                self.assertEqual(json.loads(journal.read_text())[0]["statut"], "publié")

    def test_missing_playlist_permission_keeps_upload_and_queue(self):
        denied = response({"error": {"errors": [{"reason": "insufficientPermissions"}]}})
        denied.status_code = 403
        with patch.object(policy, "_get", return_value={"items": []}), \
             patch.object(policy.requests, "post", return_value=denied):
            with self.assertRaises(policy.PlaylistPermissionRequired):
                policy.attach_playlist("token", "video", "playlist")

        data = script()
        data["_publication_plan"] = {"nom": "Cybersécurité et incidents", "id": "PL-test"}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "test.mp4")
            path.write_bytes(b"test")
            journal = Path(folder, "journal.json")
            with patch.object(policy, "JOURNAL", journal), patch.object(policy, "inspect_video"), \
                 patch.object(policy, "reject_duplicate"), \
                 patch.object(policy.requests, "post", return_value=response(headers={"Location": "https://example.org/upload"})), \
                 patch.object(policy.requests, "put", return_value=response({"id": "published"})), \
                 patch.object(policy, "attach_playlist", side_effect=policy.PlaylistPermissionRequired("consentement")):
                self.assertEqual(policy.upload_short(path, data, "token", "avatar"), "published")
                policy.retry_playlists("token")
                self.assertEqual(json.loads(journal.read_text())[0]["statut"], "playlist_en_attente")

    def test_playlist_insert_is_idempotent(self):
        with patch.object(policy, "_get", return_value={"items": [{"id": "exists"}]}), \
             patch.object(policy.requests, "post") as post:
            policy.attach_playlist("token", "video", "playlist")
            post.assert_not_called()

    def test_workflows_share_lock_and_save_on_failure(self):
        for path in Path(".github/workflows").glob("short_video*.yml"):
            workflow = yaml.safe_load(path.read_text())
            self.assertFalse(workflow["concurrency"]["cancel-in-progress"])
            self.assertEqual(workflow["concurrency"]["group"], "youtube-shorts-publication")
            steps = next(iter(workflow["jobs"].values()))["steps"]
            persist = next(step for step in steps if step["name"] == "Commit updated history")
            self.assertEqual(persist["if"], "always()")
            self.assertIn("youtube_publications.json", persist["run"])

    def test_actual_vertical_render(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder, "source.mp4"), Path(folder, "render.mp4")
            subprocess.run([
                "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:r=5:d=1",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
            ], check=True)
            with patch.object(policy.subprocess, "run", wraps=subprocess.run) as run:
                policy.render_avatar_short(source, "Outlook expose votre messagerie.", output)
                self.assertGreater(policy.inspect_video(output), 0)
                overlay = next(call for call in run.call_args_list if "-filter_complex" in call.args[0])
                self.assertIn("lt(t,3)", " ".join(overlay.args[0]))


if __name__ == "__main__":
    unittest.main()
