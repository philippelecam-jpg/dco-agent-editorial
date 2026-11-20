import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('ia_pilots', Path(__file__).parents[1] / 'scripts/ia_pilots.py')
pilots = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilots)


def storyboard():
    return {'title': 'Test', 'scenes': [
        {'visual': 'Le personnage déplace une carte.', 'overlay': '', 'lines': [
            {'speaker': 'Mina' if i % 2 else 'Nino', 'text': ' '.join(['mot'] * 20)}
        ]} for i in range(4)
    ]}


class PilotSafety(unittest.TestCase):
    def test_two_speakers_and_word_budget(self):
        self.assertEqual(pilots.validate_story(storyboard())['title'], 'Test')
        one_voice = storyboard()
        for scene in one_voice['scenes']:
            scene['lines'][0]['speaker'] = 'Mina'
        with self.assertRaises(ValueError):
            pilots.validate_story(one_voice)
        long = storyboard()
        long['scenes'][0]['lines'][0]['text'] = ' '.join(['mot'] * 100)
        with self.assertRaises(ValueError):
            pilots.validate_story(long)

    def test_ambiguous_submission_is_recorded_and_never_repeated(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            api = Mock(side_effect=[{}, TimeoutError('ambiguous response')])
            evidence = {'actions': [
                {'action': 'Envoyer le devis', 'responsable': 'Nino', 'echeance': 'vendredi'},
                {'action': 'Appeler le fournisseur', 'responsable': 'Mina', 'echeance': 'non précisée'}]}
            # save's default path is captured at definition time; redirect every write.
            original_save = pilots.save
            def save(value, path=None):
                original_save(value, path or out / 'checkpoint.json')
            with patch.object(pilots, 'OUT', out), patch.object(pilots, 'CHECKPOINT', out / 'checkpoint.json'), \
                 patch.object(pilots, 'save', side_effect=save), patch.object(pilots, 'heygen', api), \
                 patch.object(pilots, 'claude', return_value=evidence), \
                 patch.object(pilots, 'generate_story', return_value=storyboard()), \
                 patch.dict(pilots.os.environ, {'GITHUB_RUN_ATTEMPT': '1'}):
                with self.assertRaises(TimeoutError):
                    pilots.submit()
                state = json.loads((out / 'checkpoint.json').read_text())
                self.assertEqual(len(state['episodes']), 1)
                self.assertEqual(state['episodes'][0]['status'], 'submitting')
                with self.assertRaisesRegex(RuntimeError, 'déjà tentée'):
                    pilots.submit()
                self.assertEqual(api.call_count, 2)  # one GET, one POST, no retry


if __name__ == '__main__':
    unittest.main()
