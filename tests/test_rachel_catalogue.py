import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import yaml

import rachel_catalogue as rachel


def published(look_id, date, video_id=None):
    return {"date": date, "video_id": video_id or look_id, "rachel_look": {"id": look_id}}


class RachelCatalogue(unittest.TestCase):
    def setUp(self):
        self.catalogue = rachel.load_catalogue()
        self.history = patch.object(rachel, "records", return_value=[])
        self.history.start()
        self.addCleanup(self.history.stop)

    def test_six_real_images_are_validated_vertical_and_intact(self):
        self.assertEqual(len(self.catalogue["looks"]), 6)
        for look in self.catalogue["looks"]:
            self.assertTrue(look["approved"])
            self.assertTrue(look["enabled"])
            self.assertTrue(rachel.image_path(look).is_file())
            self.assertFalse(look["animation_tested"])
        changed = dict(self.catalogue["looks"][0], sha256="incorrect")
        with self.assertRaisesRegex(ValueError, "a changé"):
            rachel.image_path(changed)

    def test_theme_and_format_route_to_compatible_images(self):
        cases = [
            ({"titre": "Un nouvel outil IA"}, "avatar", "", "bureau"),
            ({"titre": "Une attaque bloque la messagerie"}, "avatar", "", "studio"),
            ({"titre": "Apprendre à vérifier un résultat"}, "avatar", "", "formation"),
            ({"titre": "La maintenance change dans les usines"}, "avatar", "", "industrie"),
            ({"titre": "Une nouvelle frontière"}, "prospective", "Économie", "prospective"),
            ({"titre": "Demain les compétences changent"}, "prospective", "Éducation et transmission", "formation"),
        ]
        for data, kind, context, expected in cases:
            with self.subTest(titre=data["titre"]):
                look, family = rachel.select_look(data, kind, context)
                self.assertEqual(look["id"], expected)
                self.assertIn(family, look["families"])
                self.assertIn(kind, look["formats"])
        look, _ = rachel.select_look({"_publication_plan": {"nom": "Cybersécurité et incidents"}}, "avatar")
        self.assertEqual(look["id"], "studio")
        with self.assertRaises(ValueError):
            rachel.select_look({}, "statique")

    def test_rotation_is_shared_and_uses_last_publication_not_upload_attempts(self):
        rows = [published("studio", "2026-11-18T12:00:00+00:00")]
        # Le studio utilisé par le flux avatar est exclu du prochain prospectif.
        look, _ = rachel.select_look({"titre": "Une attaque change la suite"}, "prospective", rows=rows)
        self.assertEqual(look["id"], "prospective")
        attempts = [{"date": "2026-11-19", "rachel_look": {"id": "bureau"}}]
        look, _ = rachel.select_look({"titre": "Un nouvel outil"}, "avatar", rows=attempts)
        self.assertEqual(look["id"], "bureau")

    def test_oldest_compatible_image_wins_despite_duplicates_and_priority(self):
        rows = [published("originale", "2026-11-10"), published("bureau", "2026-11-11"),
                published("prospective", "2026-11-12"), published("studio", "2026-11-13")]
        rows += copy.deepcopy(rows)
        look, _ = rachel.select_look({"titre": "Une autre frontière"}, "prospective", rows=rows)
        self.assertEqual(look["id"], "originale")

    def test_unapproved_disabled_or_modified_images_cannot_be_selected(self):
        for field in ("approved", "enabled", "sha256"):
            with self.subTest(field=field):
                catalogue = copy.deepcopy(self.catalogue)
                bureau = next(look for look in catalogue["looks"] if look["id"] == "bureau")
                bureau[field] = "changed" if field == "sha256" else False
                look, _ = rachel.select_look({"titre": "Un outil"}, "avatar", catalogue=catalogue)
                self.assertEqual(look["id"], "originale")

    def test_heygen_upload_is_cached_by_image_fingerprint(self):
        look = next(item for item in self.catalogue["looks"] if item["id"] == "bureau")
        reply = Mock()
        reply.json.return_value = {"data": {"asset_id": "asset-bureau-test"}}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"HEYGEN_API_KEY": "test-only"}), \
             patch.object(rachel, "ASSET_CACHE", Path(folder, "assets.json")), \
             patch.object(rachel.requests, "post", return_value=reply) as post:
            self.assertEqual(rachel.ensure_asset(look), "asset-bureau-test")
            self.assertEqual(rachel.ensure_asset(look), "asset-bureau-test")
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.args[0], "https://api.heygen.com/v3/assets")
            self.assertEqual(post.call_args.kwargs["files"]["file"][2], "image/png")
            cache = json.loads(rachel.ASSET_CACHE.read_text())
            self.assertEqual(cache["assets"]["bureau"]["sha256"], look["sha256"])
            cache["assets"]["bureau"]["sha256"] = "previous-image"
            rachel.ASSET_CACHE.write_text(json.dumps(cache))
            rachel.ensure_asset(look)
            self.assertEqual(post.call_count, 2)

    def test_selected_image_is_attached_to_the_script_for_journaling(self):
        data = {"titre": "Un nouvel outil"}
        with patch.object(rachel, "ensure_asset", return_value="asset-bureau-test"):
            self.assertEqual(rachel.prepare_rachel_image(data, "avatar"), "asset-bureau-test")
        self.assertEqual(data["_rachel_look"]["id"], "bureau")
        self.assertEqual(data["_rachel_look"]["image"], "assets/rachel/bureau.png")
        self.assertFalse(data["_rachel_look"]["fallback"])

    def test_upload_failure_and_missing_catalogue_fall_back_to_original(self):
        for failed, error in (("ensure_asset", requests.HTTPError("upload error")),
                              ("load_catalogue", FileNotFoundError("catalogue missing"))):
            with self.subTest(failed=failed), patch.dict(os.environ, {"RACHEL_PHOTO_ASSET_ID": "original-test"}), \
                 patch.object(rachel, failed, side_effect=error):
                data = {"titre": "Un nouvel outil"}
                self.assertEqual(rachel.prepare_rachel_image(data, "avatar"), "original-test")
                self.assertTrue(data["_rachel_look"]["fallback"])
                self.assertEqual(data["_rachel_look"]["id"], "originale-secours")
        with patch.dict(os.environ, {"RACHEL_PHOTO_ASSET_ID": ""}), \
             patch.object(rachel, "ensure_asset", side_effect=requests.HTTPError("upload error")):
            with self.assertRaisesRegex(RuntimeError, "secours absent"):
                rachel.prepare_rachel_image({"titre": "Un outil"}, "avatar")

    def test_two_rachel_workflows_preserve_cache_even_on_failure(self):
        for name in ("short_video_avatar.yml", "short_video_prospective.yml"):
            workflow = yaml.safe_load(Path(".github/workflows", name).read_text())
            self.assertEqual(workflow["concurrency"]["group"], "youtube-shorts-publication")
            steps = next(iter(workflow["jobs"].values()))["steps"]
            persist = next(step for step in steps if step["name"] == "Commit updated history")
            self.assertEqual(persist["if"], "always()")
            self.assertIn("rachel_assets.json", persist["run"])
            self.assertIn("git add rachel_assets.json", persist["run"])


if __name__ == "__main__":
    unittest.main()
