import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import agent_short_video_avatar as avatar
import youtube_short_policy as policy


class AvatarNarration(unittest.TestCase):
    def test_main_retries_a_short_voice_before_using_heygen(self):
        topic = {"titre": "La CEDH et l’IA", "source": "ActuIA"}
        first = {
            "titre": "La CEDH sanctionne une avocate",
            "texte_voix": "Une avocate cite des arrêts inventés. La CEDH la sanctionne.",
            "resume": "La CEDH sanctionne une avocate après une citation erronée.",
            "mots_cles": ["CEDH", "IA", "avocate", "jurisprudence", "vérification"],
        }
        second = dict(first, texte_voix=first["texte_voix"] + " Vérifiez toujours vos sources.")
        rejected_audio = Path("too-short.mp3")
        accepted_audio = Path("accepted.mp3")
        stop_at_heygen = RuntimeError("fin du test avant l’envoi de l’audio")

        for selected_topic in (topic, None):
            with self.subTest(selected_topic=selected_topic):
                generate = Mock(side_effect=[first.copy(), second.copy()])
                voice = Mock(side_effect=[rejected_audio, accepted_audio])
                portrait = Mock(return_value="portrait")
                upload = Mock(side_effect=stop_at_heygen)
                duration = {rejected_audio: 27.678186, accepted_audio: 42.0}
                with patch.multiple(
                    avatar,
                    get_access_token=Mock(return_value="token"),
                    retry_playlists=Mock(),
                    publication_due=Mock(return_value=True),
                    load_history=Mock(return_value={}),
                    fetch_candidate_news=Mock(),
                    select_best_news=Mock(return_value=selected_topic),
                    generate_script_from_news=generate,
                    generate_script_evergreen=generate,
                    generate_voice=voice,
                    prepare_publication=Mock(),
                    prepare_rachel_image=portrait,
                    upload_audio_to_heygen=upload,
                ), patch.object(policy, "records", return_value=[]), patch.object(
                    policy, "media_duration", side_effect=duration.__getitem__
                ), self.assertRaisesRegex(RuntimeError, "fin du test"):
                    avatar.main()

                self.assertEqual(generate.call_count, 2)
                self.assertEqual(voice.call_count, 2)
                self.assertIn("27.68 secondes", generate.call_args.args[1])
                self.assertEqual(portrait.call_count, 1)
                self.assertEqual(portrait.call_args.args[0]["texte_voix"], second["texte_voix"])
                upload.assert_called_once_with(accepted_audio)
