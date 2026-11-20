import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ia_controlled as c


class ControlledDialogue(unittest.TestCase):
    def test_ambiguous_paid_post_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(c, 'OUT', Path(folder)):
            state, entry = {}, {}
            call = Mock(side_effect=TimeoutError())
            with self.assertRaises(TimeoutError):
                c.once(state, entry, 'render', call)
            with self.assertRaisesRegex(RuntimeError, 'incertaine'):
                c.once(state, entry, 'render', call)
            self.assertEqual(call.call_count, 1)

    def test_subtitles_follow_voice_timestamps(self):
        words = [{'text': 'Bonjour', 'start_time': .2, 'end_time': .7},
                 {'text': 'Mina', 'start_time': .8, 'end_time': 1.1}]
        self.assertEqual(c.subtitle_cues(words, 10, 2), [(10.2, 11.1, 'Bonjour Mina')])
        with self.assertRaises(ValueError):
            c.subtitle_cues([], 0, 2)

    def test_restart_is_encrypted_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(c, 'ROOT', Path(folder)), \
                patch.object(c, 'OUT', Path(folder) / 'out'), patch.dict(os.environ, {'HEYGEN_API_KEY': 'test-key'}):
            c.OUT.mkdir()
            p = c.OUT / 'checkpoint.json'
            p.write_text('{"render":"already-generated"}')
            c.archive_restart()
            self.assertNotIn(b'already-generated', (c.ROOT / 'controlled-restart.enc').read_bytes())
            p.unlink()
            c.restore_restart()
            self.assertEqual(json.loads(p.read_text())['render'], 'already-generated')

    def test_final_segment_excludes_generated_video_audio(self):
        # Le rendu source porte du silence, le WAV source un signal audible.
        # Le segment doit contenir uniquement le second flux, en mono, sans troncature.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw, voice, result = root/'raw.mp4', root/'voice.wav', root/'segment.mkv'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=black:s=108x192:d=1',
                            '-f','lavfi','-i','anullsrc=r=48000:cl=mono','-t','1','-c:v','libx264',
                            '-c:a','aac',str(raw)],check=True)
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=800:duration=1',
                            str(voice)],check=True)
            command = c.segment_command(raw, voice, result, 1.24)
            self.assertEqual([command[i+1] for i,x in enumerate(command) if x=='-map'], ['0:v:0','1:a:0'])
            subprocess.run(command,check=True)
            report = c.probe(result)
            audio = [s for s in report['streams'] if s['codec_type']=='audio']
            self.assertEqual(len(audio),1)
            self.assertEqual(audio[0]['channels'],1)
            self.assertGreaterEqual(c.duration(result),1.23)
