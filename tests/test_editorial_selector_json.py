"""Tests de robustesse du décodage JSON du sélecteur éditorial."""
import json
import unittest
from unittest.mock import patch

import editorial_selector


class JsonResponseTests(unittest.TestCase):
    @staticmethod
    def block(text):
        return [{"type": "text", "text": text}]

    @patch("editorial_selector._claude")
    def test_valid_json_first_attempt(self, claude):
        claude.return_value = self.block('[{"sujet":"Décision"}]')
        result = editorial_selector._json_response("key", "prompt", {}, 1200)
        self.assertEqual(result[0]["sujet"], "Décision")
        self.assertEqual(claude.call_count, 1)

    @patch("editorial_selector._claude")
    def test_truncated_json_recovers_with_retry(self, claude):
        claude.side_effect = [
            self.block('[{"sujet": "incomplet'),
            self.block('```json\n[{"sujet": "complet"}]\n```'),
        ]
        result = editorial_selector._json_response("key", "prompt", {}, 1200)
        self.assertEqual(result[0]["sujet"], "complet")
        self.assertEqual(claude.call_count, 2)
        self.assertEqual(claude.call_args.args[3], 3000)

    @patch("editorial_selector._claude")
    def test_invalid_json_fails_after_three_attempts(self, claude):
        claude.return_value = self.block('{"sujet": "incomplet')
        with self.assertRaisesRegex(ValueError, "après 3 tentatives"):
            editorial_selector._json_response("key", "prompt", {}, 1200)
        self.assertEqual(claude.call_count, 3)

    @patch("editorial_selector._claude")
    def test_valid_json_object_choice(self, claude):
        claude.return_value = self.block('{"numero": 2}')
        self.assertEqual(
            editorial_selector._json_response("key", "prompt", {}, 80),
            {"numero": 2},
        )


if __name__ == "__main__":
    unittest.main()
