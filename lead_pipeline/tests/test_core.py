import concurrent.futures,json,tempfile,unittest
from unittest.mock import patch
from backend.core import Store,Rejected,domain,public_ips
from backend import providers

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.store=Store(self.tmp.name+'/leads.db')
    def tearDown(self): self.tmp.cleanup()
    def session(self,address='camille@entreprise.fr'):
        lead,token=self.store.signup(address,'Camille Martin','Entreprise'); return self.store.verify(token)
    def test_domain_normalization(self):
        self.assertEqual(domain('https://www.ENTREPRISE.fr/news?x=1'),'entreprise.fr')
    def test_local_and_credential_urls_rejected(self):
        for value in ('127.0.0.1','http://localhost','https://user@entreprise.fr','ftp://entreprise.fr','https://entreprise.fr:8080','https://internal.local'):
            with self.assertRaises(Rejected): domain(value)
    def test_token_single_use_and_hashed(self):
        lead,token=self.store.signup('a@entreprise.fr','Camille','Entreprise')
        with self.store.connect() as db: self.assertNotEqual(db.execute('SELECT hash FROM tokens').fetchone()[0],token)
        self.store.verify(token)
        with self.assertRaises(Rejected): self.store.verify(token)
    def test_expired_token(self):
        lead,token=self.store.signup('a@entreprise.fr','Camille','Entreprise')
        with self.store.connect() as db: db.execute('UPDATE tokens SET expires=0')
        with self.assertRaises(Rejected): self.store.verify(token)
    def test_unverified_session(self):
        with self.assertRaises(Rejected): self.store.reserve('fake','entreprise.fr',True)
    def test_different_email_domain_is_allowed(self):
        request_id = self.store.reserve(self.session('dirigeant@gmail.com'),'autre.fr',True)
        self.assertEqual(self.store.get(request_id)['domain'], 'autre.fr')
    def test_acknowledgement(self):
        with self.assertRaises(Rejected): self.store.reserve(self.session(),'entreprise.fr',False)
    def test_atomic_company_reservation(self):
        sessions=[self.session('a@entreprise.fr'),self.session('b@entreprise.fr')]
        def reserve(s):
            try: return self.store.reserve(s,'entreprise.fr',True)
            except Rejected: return None
        with concurrent.futures.ThreadPoolExecutor(2) as pool: results=list(pool.map(reserve,sessions))
        self.assertEqual(sum(r is not None for r in results),1)
    def test_one_email(self):
        session=self.session(); self.store.reserve(session,'www.entreprise.fr',True)
        with self.assertRaises(Rejected): self.store.reserve(session,'entreprise.fr',True)
    def test_siren_duplicate(self):
        self.store.reserve(self.session(),'entreprise.fr',True,'123456789')
        with self.assertRaises(Rejected): self.store.reserve(self.session('a@autre.fr'),'autre.fr',True,'123456789')
    def test_private_dns(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(Rejected): public_ips('entreprise.fr')
    def test_video_max_duration(self):
        with patch('subprocess.check_output',return_value='30.01'):
            with self.assertRaises(Rejected): providers.duration('test.mp4')
        with patch('subprocess.check_output',return_value='29.9'): self.assertEqual(providers.duration('test.mp4'),29.9)
    def test_hallucinated_source_rejected(self):
        script={'voice':' '.join(['mot']*30),'claims':[{'source_index':0,'quote':'Une affirmation totalement inventée'}]}
        with self.assertRaises(Rejected): providers.verify_script(script,[{'text':'Les faits publiés sont différents.'}])
    def test_checkpoint_and_single_claim(self):
        request=self.store.reserve(self.session(),'entreprise.fr',True)
        self.assertEqual(self.store.claim(),request); self.assertIsNone(self.store.claim())
        self.store.checkpoint(request,'blocked',{'heygen_id':'known'},'À contrôler')
        self.assertEqual(json.loads(self.store.get(request)['data'])['heygen_id'],'known')

if __name__=='__main__': unittest.main()
