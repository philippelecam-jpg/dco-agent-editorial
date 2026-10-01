import hashlib,hmac,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,MagicMock,patch
from backend import publish_capsule as pub, lead_callback as cb
from backend.core import Rejected

class PublicationTests(unittest.TestCase):
    def scenario(self, action):
        previous=os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                out=Path('test-output');out.mkdir();(out/'rachel.mp4').write_bytes(b'video')
                report={'company':'Baresto','domain':'baresto.fr','site_url':'https://baresto.fr/','video_ready':True,'script':{'title':'Baresto','voice':'Portrait factuel'},'sources':[{'url':'https://baresto.fr/'}]}
                (out/'report.json').write_text(json.dumps(report))
                action(out)
            finally: os.chdir(previous)
    def test_existing_mp4_upload_and_link_ready(self):
        def run(out):
            with patch.dict(os.environ,{'TEST_MODE':'youtube_existing','EXISTING_YOUTUBE_ID':''}),patch.object(pub.p,'youtube_start',return_value='https://secret-upload.example/session') as start,patch.object(pub.p,'youtube_upload',return_value='aBcD1234_-Z') as upload,patch.object(pub.p,'youtube_ready',return_value=True):
                pub.main();self.assertEqual(os.environ['YOUTUBE_PRIVACY'],'unlisted');start.assert_called_once();upload.assert_called_once()
            report=json.loads((out/'report.json').read_text());self.assertEqual(report['status'],'published');self.assertTrue(report['youtube_ready']);self.assertNotIn('secret-upload',json.dumps(report))
        self.scenario(run)
    def test_known_youtube_id_never_reuploads(self):
        def run(out):
            with patch.dict(os.environ,{'TEST_MODE':'youtube_existing','EXISTING_YOUTUBE_ID':'aBcD1234_-Z'}),patch.object(pub.p,'youtube_start') as start,patch.object(pub.p,'youtube_upload') as upload,patch.object(pub.p,'youtube_ready',return_value=True):
                pub.main();start.assert_not_called();upload.assert_not_called()
        self.scenario(run)
    def test_upload_error_preserves_video_and_marks_pending(self):
        def run(out):
            with patch.dict(os.environ,{'TEST_MODE':'youtube_unlisted','EXISTING_YOUTUBE_ID':''}),patch.object(pub.p,'youtube_start',return_value='https://secret-session'),patch.object(pub.p,'youtube_upload',side_effect=RuntimeError('secret detail')):
                with self.assertRaises(RuntimeError):pub.main()
            report=json.loads((out/'report.json').read_text());self.assertEqual(report['status'],'completed');self.assertTrue(report['video_ready']);self.assertEqual(report['provider_call_pending'],'youtube_upload');self.assertNotIn('secret',report['reason'])
        self.scenario(run)
    def test_missing_video_never_generates(self):
        def run(out):
            (out/'rachel.mp4').unlink()
            with patch.object(pub.p,'youtube_start') as start,self.assertRaises(Rejected):pub.main()
            start.assert_not_called()
        self.scenario(run)
    def test_signed_callback_has_no_recipient_or_provider_secret(self):
        def run(out):
            report=json.loads((out/'report.json').read_text());report.update(youtube_ready=True,youtube_id='aBcD1234_-Z');(out/'report.json').write_text(json.dumps(report))
            env={'LEAD_CALLBACK_URL':'https://fabrik.test/api/capsule-result','LEAD_CALLBACK_SECRET':'shared-secret','LEAD_REQUEST_ID':'req','LEAD_REQUEST_KEY':'attempt','GITHUB_RUN_ID':'99'}
            response=MagicMock();response.__enter__.return_value.status=200
            with patch.dict(os.environ,env),patch.object(cb,'urlopen',return_value=response) as post:
                cb.main()
                request=post.call_args.args[0];timestamp=request.get_header('X-lead-timestamp');expected=hmac.new(b'shared-secret',timestamp.encode()+b'.'+request.data,hashlib.sha256).hexdigest()
                self.assertEqual(request.get_header('X-lead-signature'),expected);self.assertNotIn('shared-secret',request.data.decode());self.assertNotIn('email',json.loads(request.data))
        self.scenario(run)

if __name__=='__main__': unittest.main()
