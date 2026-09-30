import json, unittest
from unittest.mock import Mock, patch
from backend import providers as p
from backend.core import Rejected

class ClaudeTests(unittest.TestCase):
    def call(self, text, stop='end_turn', schema=p.VERIFY_SCHEMA):
        body={'content':[{'type':'text','text':text}],'stop_reason':stop,'usage':{'input_tokens':5}}
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY':'test'}), patch.object(p,'req',return_value=Mock(json=Mock(return_value=body))) as req:
            result=p.claude('test',{},schema)
            self.assertEqual(req.call_args.kwargs['json']['output_config']['format']['schema'],schema)
            return result
    def test_valid_and_usage(self):
        result,usage=self.call('{"approved":false,"reason":"Sources insuffisantes"}')
        self.assertFalse(result['approved']); self.assertEqual(usage['input_tokens'],5)
    def test_invalid_outputs_stop(self):
        for text in ('','```json\n{}\n```','Pas assez de sources','[]','{}','{"approved":"true","reason":"x"}','{"approved":true,"reason":"x","extra":1}'):
            with self.subTest(text=text),self.assertRaises(Rejected): self.call(text)
    def test_refusal_and_truncation(self):
        for stop in ('refusal','max_tokens','tool_use',None):
            with self.subTest(stop=stop),self.assertRaises(Rejected): self.call('{}',stop)
    def test_blocked_script(self):
        script={'blocked':True,'reason':'Sources insuffisantes','title':'','voice':'','format':'portrait','claims':[],'sensitive':False}
        value,_=self.call(json.dumps(script),schema=p.SCRIPT_SCHEMA)
        with self.assertRaises(Rejected): p.verify_script(value,[])
    def test_claim_index_boolean_rejected(self):
        script={'blocked':False,'reason':'','title':'Portrait express','voice':'x','format':'portrait','claims':[{'text':'x','quote':'x','source_index':True}],'sensitive':False}
        with self.assertRaises(Rejected): self.call(json.dumps(script),schema=p.SCRIPT_SCHEMA)
    def test_script_uses_schema(self):
        with patch.object(p,'sourced_draft',return_value=({},{})) as draft:
            p.script('Entreprise',[])
            self.assertEqual(draft.call_args.args[1:],('Entreprise',[]))
    def test_verification_uses_schema(self):
        script={'voice':' '.join(['mot']*20),'claims':[{'source_index':0,'quote':'Une source suffisamment longue'}]}
        with patch.object(p,'claude',return_value=({'approved':True,'reason':''},{})) as claude:
            p.verify_script(script,[{'text':'Une source suffisamment longue'}])
            self.assertEqual(claude.call_args.args[2],p.VERIFY_SCHEMA)

