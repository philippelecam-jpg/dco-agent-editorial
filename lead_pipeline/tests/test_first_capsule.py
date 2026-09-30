import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from backend import first_capsule
from backend.core import Rejected

class FirstCapsuleDiagnosticsTests(unittest.TestCase):
    def run_in_tmp(self,callback):
        previous=os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try: callback(Path(directory))
            finally: os.chdir(previous)
    def env(self):
        return patch.dict(os.environ,{
            'TEST_MODE':'video',
            'COMPANY_NAME':'Entreprise',
            'COMPANY_SITE':'https://www.entreprise.fr',
            'ANTHROPIC_API_KEY':'anthropic',
            'ELEVENLABS_API_KEY':'eleven',
            'ELEVENLABS_VOICE_ID':'voice',
            'HEYGEN_API_KEY':'heygen',
            'YOUTUBE_CLIENT_ID':'client',
            'YOUTUBE_CLIENT_SECRET':'secret',
            'YOUTUBE_REFRESH_TOKEN':'refresh',
        },clear=False)
    def test_voice_failure_writes_safe_report(self):
        def scenario(directory):
            sources=[{'url':'https://www.entreprise.fr/','text':'Présentation publique '*20,'collected_at':'2026-09-30'}]
            script={'title':'Portrait express','format':'portrait','voice':' '.join(['mot']*20),'claims':[]}
            with self.env(), \
                 patch.object(first_capsule.p,'collect_company',return_value=sources), \
                 patch.object(first_capsule.p,'verified_script',return_value=script), \
                 patch.object(first_capsule.p,'voice',side_effect=Rejected('Voix refusée')):
                with self.assertRaises(Rejected): first_capsule.main()
            report=json.loads((directory/'test-output'/'report.json').read_text())
            self.assertEqual(report['status'],'blocked')
            self.assertEqual(report['stage'],'voice')
            self.assertEqual(report['provider_call_pending'],'voice')
            self.assertEqual(report['reason'],'Voix refusée')
            self.assertNotIn('youtube_session',report)
            self.assertNotIn('heygen_id',report)
            self.assertEqual(report['sources'][0]['url'],'https://www.entreprise.fr/')
            self.assertNotIn('excerpt',report['sources'][0])
        self.run_in_tmp(scenario)
    def test_script_rejection_report_keeps_evidence_excerpt(self):
        def scenario(directory):
            sources=[{'url':'https://www.entreprise.fr/','text':'Présentation publique '*20,'collected_at':'2026-09-30'}]
            with self.env(), \
                 patch.object(first_capsule.p,'collect_company',return_value=sources), \
                 patch.object(first_capsule.p,'verified_script',side_effect=Rejected('Sources insuffisantes')):
                with self.assertRaises(Rejected): first_capsule.main()
            report=json.loads((directory/'test-output'/'report.json').read_text())
            self.assertEqual(report['status'],'blocked')
            self.assertEqual(report['stage'],'script')
            self.assertEqual(report['reason'],'Sources insuffisantes')
            self.assertIn('excerpt',report['sources'][0])
        self.run_in_tmp(scenario)

if __name__=='__main__': unittest.main()
