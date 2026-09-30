import json, os, tempfile, unittest
from unittest.mock import patch, Mock
from backend.core import Store
from backend import worker, preflight

class JourneyTests(unittest.TestCase):
    def test_journey_and_restart_without_duplicate_generation(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'ARTIFACT_PATH':directory+'/artifacts'}), patch.object(worker,'configuration',return_value=[]):
            store=Store(directory+'/db'); lead,token=store.signup('camille@entreprise.fr','Camille','Entreprise')
            store.queue_mail('verify-test',lead,'Accès','lien')
            with patch.object(worker.p,'mail') as mail:
                worker.flush_mail(store); worker.flush_mail(store); self.assertEqual(mail.call_count,1)
            request=store.reserve(store.verify(token),'entreprise.fr',True)
            source={'url':'https://entreprise.fr','text':'Une source officielle suffisamment longue'}
            with patch.object(worker.p,'collect',return_value=source), patch.object(worker.p,'script',return_value=({'title':'Portrait express','voice':'texte','format':'portrait'},{})), patch.object(worker.p,'verify_script',return_value={}), patch.object(worker.p,'voice') as voice, patch.object(worker.p,'duration',return_value=20), patch.object(worker.p,'avatar_start',return_value='avatar-id') as avatar, patch.object(worker.p,'avatar_get',side_effect=[{'status':'pending'},{'status':'completed','video_url':'https://video.example/video'}]), patch.object(worker.p,'req',return_value=Mock(content=b'video')), patch.object(worker.p,'youtube_start',return_value='session') as upload_start, patch.object(worker.p,'youtube_upload',return_value='youtube-id') as upload, patch.object(worker.p,'youtube_ready',return_value=True), patch.object(worker.p,'mail') as mail:
                worker.tick(store)
                self.assertEqual(store.get(request)['status'],'avatar')
                # Simulate a process restart with the same durable database.
                store=Store(directory+'/db'); worker.tick(store); worker.tick(store); worker.tick(store)
                self.assertEqual(store.get(request)['status'],'completed')
                for call in (voice,avatar,upload_start,upload,mail): self.assertEqual(call.call_count,1)
                self.assertEqual(json.loads(store.get(request)['data'])['url'],'https://www.youtube.com/watch?v=youtube-id')
    def test_uncertain_paid_call_blocks_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory+'/db'); _,token=store.signup('a@entreprise.fr','Camille','Entreprise')
            request=store.reserve(store.verify(token),'entreprise.fr',True)
            store.checkpoint(request,'voice',{'pending_paid':'voice'})
            with patch.object(worker.p,'voice') as voice: worker.tick(store); voice.assert_not_called()
            self.assertEqual(store.get(request)['status'],'blocked')
    def test_preflight_rejects_private_delivery(self):
        with patch.dict(os.environ,{'PUBLIC_BASE_URL':'https://rachel.example','YOUTUBE_PRIVACY':'private','ADMIN_TOKEN':'x'*32}):
            self.assertTrue(any('YOUTUBE_PRIVACY' in error for error in preflight.check()['errors']))
