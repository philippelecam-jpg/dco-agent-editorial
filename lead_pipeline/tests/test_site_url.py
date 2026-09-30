import json,tempfile,unittest
from unittest.mock import patch
from backend.core import site_url,domain,Store,Rejected
from backend import providers as p

class SiteURLTests(unittest.TestCase):
    def test_pasted_url_preserves_www_path_and_query(self):
        self.assertEqual(site_url('  HTTP://WWW.ENTREPRISE.FR/fr/?lang=fr#top  '),'https://www.entreprise.fr/fr/?lang=fr')
        self.assertEqual(site_url('www.entreprise.fr'),'https://www.entreprise.fr/')
        self.assertEqual(domain(site_url('www.entreprise.fr')),'entreprise.fr')
    def test_unsafe_input_rejected_before_collection(self):
        for value in ('https://a@entreprise.fr','https://127.0.0.1','ftp://entreprise.fr','https://entreprise.fr:8080','https://entre prise.fr',None):
            with self.subTest(value=value),self.assertRaises((Rejected,ValueError)): site_url(value)
    def test_submitted_address_tried_before_alternate(self):
        page={'url':'https://www.entreprise.fr/fr/','text':'Source publique '*20,'links':[]}
        def collect(url):
            if url==page['url']: return page
            raise Rejected('Page absente')
        with patch.object(p,'collect',side_effect=collect) as fetch:
            sources=p.collect_company(' www.entreprise.fr/fr/ ')
        self.assertEqual(fetch.call_args_list[0].args[0],page['url'])
        self.assertEqual(sources[0]['url'],page['url'])
    def test_fallback_preserves_path_and_uses_actual_origin(self):
        page={'url':'https://www.entreprise.fr/fr/','text':'Source publique '*20,'links':[]}
        def collect(url):
            if url==page['url']: return page
            raise Rejected('HTTP 202')
        with patch.object(p,'collect',side_effect=collect) as fetch:
            p.collect_company('entreprise.fr/fr/')
        self.assertEqual([c.args[0] for c in fetch.call_args_list[:2]],['https://entreprise.fr/fr/','https://www.entreprise.fr/fr/'])
        self.assertTrue(all(c.args[0].startswith('https://www.entreprise.fr/') for c in fetch.call_args_list[2:]))
    def test_both_fail_explicitly(self):
        with patch.object(p,'collect',side_effect=Rejected('HTTP 202')) as fetch:
            with self.assertRaisesRegex(Rejected,'Collecte du site impossible'): p.collect_company('www.entreprise.fr')
        self.assertEqual(fetch.call_count,2)
    def test_reservation_keeps_address_and_domain_uniqueness(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory+'/db')
            _,token=store.signup('a@entreprise.fr','Camille','Entreprise')
            request=store.reserve(store.verify(token),' https://www.entreprise.fr/fr/ ',True)
            row=store.get(request)
            self.assertEqual(row['domain'],'entreprise.fr')
            self.assertEqual(json.loads(row['data'])['site_url'],'https://www.entreprise.fr/fr/')
            _,token=store.signup('b@entreprise.fr','Camille','Entreprise')
            with self.assertRaises(Rejected): store.reserve(store.verify(token),'entreprise.fr',True)
