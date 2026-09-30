import unittest
from unittest.mock import patch
from backend import providers as p
from backend.core import Rejected

class QuoteTests(unittest.TestCase):
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
