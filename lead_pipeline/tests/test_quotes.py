import unittest
from unittest.mock import patch
from backend import providers as p
from backend.core import Rejected

class QuoteTests(unittest.TestCase):
    def test_evidence_selection_materializes_exact_source(self):
        result={'blocked':False,'reason':'','title':'Portrait express','format':'portrait','voice':' '.join(['mot']*20),'sensitive':False,'claims':[{'text':'Activité','evidence_id':'s0-e0'}]}
        sources=[{'url':'https://example.com','text':'Une société développe des outils fiables.'}]
        with patch.object(p,'claude',return_value=(result,{})):
            draft,_=p.sourced_draft('test','Entreprise',sources)
        self.assertEqual(draft['claims'][0]['quote'],sources[0]['text'])
        self.assertEqual(draft['claims'][0]['source_index'],0)
        with patch.object(p,'claude',return_value=({'approved':False,'reason':'Le fait ne découle pas de cet extrait'},{})),self.assertRaises(Rejected):
            p.verify_script(draft,sources)
    def test_unknown_evidence_identifier_rejected(self):
        result={'blocked':False,'reason':'','title':'Portrait express','format':'portrait','voice':' '.join(['mot']*20),'sensitive':False,'claims':[{'text':'Activité','evidence_id':'invented'}]}
        with patch.object(p,'claude',return_value=(result,{})),self.assertRaises(Rejected):
            p.sourced_draft('test','Entreprise',[{'url':'https://example.com','text':'Une société développe des outils fiables.'}])
    def test_company_discovery_reads_linked_pages_and_excludes_external(self):
        home={'url':'https://example.com/','text':'Accueil '*30,'links':['/fr/presentation','https://other.com/news'],'collected_at':'2026-09-30'}
        def collect(url):
            if url=='https://example.com/': return home
            if url=='https://example.com/fr/presentation': return {'url':url,'text':'Présentation entreprise '*20,'collected_at':'2026-09-30','links':[]}
            raise Rejected('Page absente')
        with patch.object(p,'collect',side_effect=collect) as fetch:
            sources=p.collect_company('example.com')
        self.assertEqual(len(sources),2)
        self.assertNotIn('links',sources[0])
        self.assertTrue(all('other.com' not in call.args[0] for call in fetch.call_args_list))
    def script(self,quote,index=0):
        return {'voice':' '.join(['mot']*20),'claims':[{'quote':quote,'source_index':index}]}
    def test_whitespace_and_unicode_only_then_editorial_check(self):
        with patch.object(p,'claude',return_value=({'approved':True,'reason':''},{})) as check:
            p.verify_script(self.script('Une société développe des outils'),[{'text':'Une socie\u0301te\u0301\u00a0développe\n des  outils fiables.'}])
            check.assert_called_once()
    def test_fabricated_quote_and_wrong_index_still_rejected(self):
        for quote,index in [('Une société invente des outils',0),('Une société développe des outils',1),('Une société développe des outils',True),('court',0)]:
            with self.subTest(quote=quote,index=index),patch.object(p,'claude') as check,self.assertRaises(Rejected):
                p.verify_script(self.script(quote,index),[{'text':'Une société développe des outils fiables.'}])
            check.assert_not_called()
    def test_no_punctuation_or_case_fuzzy_matching(self):
        for quote in ('Une société, développe des outils','une société développe des outils'):
            with self.assertRaises(Rejected):
                p.verify_script(self.script(quote),[{'text':'Une société développe des outils fiables.'}])
    def test_one_rewrite_then_independent_verification(self):
        sources=[{'text':'Une société développe des outils fiables.'}]
        bad=self.script('Une société invente des outils')
        good=self.script('Une société développe des outils')
        usage=[]
        with patch.object(p,'script',side_effect=[(bad,{'tokens':1}),(good,{'tokens':2})]),patch.object(p,'claude',return_value=({'approved':True,'reason':''},{'tokens':3})) as claude:
            self.assertEqual(p.verified_script('Entreprise',sources,lambda op,u:usage.append((op,u))),good)
        self.assertEqual(claude.call_count,1)
        self.assertEqual([op for op,u in usage],['script','rewrite','verification'])
    def test_second_bad_quote_stops_without_editorial_call(self):
        bad=self.script('Une société invente des outils')
        with patch.object(p,'script',return_value=(bad,{})),patch.object(p,'claude',return_value=(bad,{})) as claude,self.assertRaises(p.EvidenceRejected):
            p.verified_script('Entreprise',[{'text':'Une société développe des outils fiables.'}],lambda op,u:None)
        self.assertEqual(claude.call_count,0)
    def test_editorial_refusal_is_not_rewritten(self):
        good=self.script('Une société développe des outils')
        with patch.object(p,'script',return_value=(good,{})),patch.object(p,'claude',return_value=({'approved':False,'reason':'Identité incertaine'},{})) as claude,self.assertRaises(Rejected):
            p.verified_script('Entreprise',[{'text':'Une société développe des outils fiables.'}],lambda op,u:None)
        self.assertEqual(claude.call_count,1)
    def test_sensitive_content_is_not_rewritten(self):
        bad=self.script('Une société développe des outils');bad['sensitive']=True
        with patch.object(p,'script',return_value=(bad,{})),patch.object(p,'claude') as claude,self.assertRaises(Rejected):
            p.verified_script('Entreprise',[{'text':'Une société développe des outils fiables.'}],lambda op,u:None)
        claude.assert_not_called()
