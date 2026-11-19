import copy
from array import array
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
    def setUp(self):
        # Les tests de validation ne dépendent pas des futures publications réelles.
        self.history_patch = patch.object(policy, "records", return_value=[])
        self.history_patch.start()
        self.addCleanup(self.history_patch.stop)

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

    def test_forced_prospective_bypasses_weekly_limit_but_not_duplicates(self):
        existing = "Et si les bureaux disparaissaient ?"
        listing = {"items": [{"snippet": {
            "publishedAt": datetime.now(timezone.utc).isoformat(),
            "title": existing, "resourceId": {"videoId": "previous"},
        }}]}
        channels = {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "uploads"}}}]}
        def get(token, resource, **kwargs):
            return channels if resource == "channels" else listing
        with patch.object(policy, "resolve_playlists", return_value={"Prospective": "playlist"}), \
             patch.object(policy, "classify_playlist", return_value="Prospective"), \
             patch.object(policy, "_get", side_effect=get):
            with patch.dict(os.environ, {"FORCE_PUBLICATION": "false"}):
                with self.assertRaisesRegex(ValueError, "cette semaine"):
                    policy.prepare_publication(script(), "token", "prospective")
            with patch.dict(os.environ, {"FORCE_PUBLICATION": "true"}):
                self.assertEqual(policy.prepare_publication(script(), "token", "prospective")["id"], "playlist")
                with self.assertRaisesRegex(ValueError, "Titre proche"):
                    policy.prepare_publication(dict(script(), titre=existing), "token", "prospective")

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
        data["_rachel_look"] = {"id": "studio", "image": "assets/rachel/studio.png", "fallback": False}
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
                self.assertEqual(json.loads(journal.read_text())[0]["accroche"], data["accroche"])
                self.assertEqual(json.loads(journal.read_text())[0]["conclusion"], "Voici une conséquence.")
                self.assertEqual(json.loads(journal.read_text())[0]["rachel_look"], data["_rachel_look"])
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
                self.assertGreaterEqual(policy.inspect_video(output), policy.inspect_video(source) + .98)
                self.assertLess(policy.inspect_video(output), 2.2)
                overlay = next(call for call in run.call_args_list if "-filter_complex" in call.args[0])
                self.assertIn("lt(t,3)", " ".join(overlay.args[0]))
            self.assert_audio_end_preserved(output)

    def assert_audio_end_preserved(self, output):
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
            "-of", "json", str(output),
        ], capture_output=True, text=True, check=True)
        streams = {row["codec_type"]: float(row["duration"]) for row in json.loads(probe.stdout)["streams"]}
        self.assertGreaterEqual(streams["video"], 1.98)
        self.assertGreaterEqual(streams["audio"], 1.98)

        def samples(start, length):
            result = subprocess.run([
                "ffmpeg", "-v", "error", "-i", str(output), "-ss", str(start), "-t", str(length),
                "-vn", "-ar", "16000", "-ac", "1", "-f", "s16le", "pipe:1",
            ], capture_output=True, check=True)
            return array("h", result.stdout)
        voiced, silence = samples(.8, .15), samples(1.3, .5)
        self.assertGreater(len(voiced), 2000)
        self.assertGreater(max(abs(value) for value in voiced), 1000)
        self.assertGreater(len(silence), 7000)
        self.assertLess(max(abs(value) for value in silence), 20)

    def test_actual_static_render_has_silent_tail(self):
        with tempfile.TemporaryDirectory() as folder:
            image, audio, output = (Path(folder, name) for name in ("still.png", "tone.wav", "static.mp4"))
            policy.hook_image("Un fournisseur interrompt les commandes.", image, transparent=False)
            subprocess.run([
                "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                "sine=frequency=440:duration=1", str(audio),
            ], check=True)
            policy.render_static_short(image, audio, output)
            self.assertGreaterEqual(policy.inspect_video(output), 2.0)
            self.assertLess(policy.inspect_video(output), 2.2)
            self.assert_audio_end_preserved(output)

    def test_history_uses_recent_edges_once_and_skips_legacy(self):
        rows = [{"date": "2026-11-18", "titre": "Ancien titre", "video_id": "legacy"}]
        for index in range(14):
            row = {"date": f"2026-11-{index + 1:02}", "titre": f"Titre {index}",
                   "video_id": str(index), "accroche": f"Début {index}.", "conclusion": f"Fin {index}."}
            rows.extend([row, dict(row)])  # historique et journal d'upload
        with patch.object(policy, "records", return_value=rows):
            recent = policy.recent_script_edges()
            self.assertEqual(len(recent), 12)
            self.assertEqual(recent[0]["titre"], "Titre 13")
            self.assertEqual(recent[-1]["titre"], "Titre 2")
            self.assertIn("Fin 13.", policy.script_context())
            self.assertNotIn("Ancien titre", policy.script_context())

    def test_cliches_similar_edges_and_incomplete_endings_are_rejected(self):
        for text in (
            "Et si, un matin, votre fournisseur disparaissait ?",
            "Ce n’est pas de la science-fiction lointaine.",
            "Les briques existent déjà aujourd'hui.",
            "Voici une phrase inachevée...", "Voici une phrase inachevée…",
            "Voici une phrase inachevée",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                policy.check_script_variety(dict(script(), texte_voix=text))
        for row in ({"accroche": "Outlook expose votre messagerie !"},
                    {"conclusion": "Voici une conséquence !"}):
            with patch.object(policy, "recent_script_edges", return_value=[row]):
                with self.assertRaisesRegex(ValueError, "trop proche"):
                    policy.check_script_variety(script())
        policy.check_script_variety(script())

    def test_rewrite_receives_reason_and_stops_after_three_attempts(self):
        bad = dict(script(), texte_voix="Outlook expose votre messagerie. Les briques existent déjà.")
        generate = Mock(side_effect=[bad, script()])
        with patch.object(policy, "reject_duplicate"):
            self.assertEqual(policy.generate_validated_script(generate), script())
        self.assertEqual(generate.call_count, 2)
        self.assertIn("les briques existent deja", generate.call_args.args[0])
        generate = Mock(return_value=bad)
        with self.assertRaisesRegex(ValueError, "trois propositions"):
            policy.generate_validated_script(generate)
        self.assertEqual(generate.call_count, 3)

    def test_narration_rewrite_uses_measured_duration_and_rechecks_publication(self):
        generate, voice, preflight = Mock(return_value=script()), Mock(return_value=Path("voice.mp3")), Mock()
        with patch.object(policy, "check_audio_duration", side_effect=[ValueError("too short"), 42]), \
             patch.object(policy, "media_duration", return_value=25):
            data, path = policy.generate_validated_narration(generate, voice, Path("voice.mp3"), preflight)
        self.assertEqual(voice.call_count, 2)
        self.assertEqual(preflight.call_count, 2)
        self.assertIn("25.00 secondes", generate.call_args.args[0])
        self.assertIn("42 secondes", generate.call_args.args[0])
        with patch.object(policy, "check_audio_duration", side_effect=ValueError("still too short")), \
             patch.object(policy, "media_duration", return_value=25):
            voice.reset_mock()
            with self.assertRaisesRegex(ValueError, "still too short"):
                policy.generate_validated_narration(generate, voice, path, preflight)
            self.assertEqual(voice.call_count, 3)

    def test_duration_budget_never_truncates_narration(self):
        self.assertEqual(policy.finished_duration(58), 59)
        with self.assertRaisesRegex(ValueError, "jamais tronquer"):
            policy.finished_duration(59)
        with patch.object(policy, "media_duration", return_value=58):
            self.assertEqual(policy.check_audio_duration(Path("voice.mp3")), 58)
        with patch.object(policy, "media_duration", return_value=58.01):
            with self.assertRaisesRegex(ValueError, "sans couper"):
                policy.check_audio_duration(Path("voice.mp3"))
        with patch.object(policy, "inspect_video", return_value=59), \
             patch.object(policy, "media_duration", return_value=59), \
             patch.object(policy.subprocess, "run") as render:
            with self.assertRaisesRegex(ValueError, "jamais tronquer"):
                policy.render_avatar_short(Path("source.mp4"), "Une accroche.", Path("out.mp4"))
            render.assert_not_called()

    def test_truncated_heygen_audio_blocks_render(self):
        with patch.object(policy, "inspect_video", return_value=45), \
             patch.object(policy, "media_duration", side_effect=[44.5, 45]), \
             patch.object(policy.subprocess, "run") as render:
            with self.assertRaisesRegex(ValueError, "plus courte"):
                policy.render_avatar_short(Path("source.mp4"), "Une accroche.", Path("out.mp4"),
                                           reference_audio=Path("voice.mp3"))
            render.assert_not_called()


if __name__ == "__main__":
    unittest.main()
