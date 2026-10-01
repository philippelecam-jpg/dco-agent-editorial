import json, unittest
from unittest.mock import Mock, patch
from backend import providers as p
from backend.core import Rejected

class NetworkCollectionTests(unittest.TestCase):
    def test_next_address_after_failure(self):
        raw=Mock(); tls=Mock()
        with patch.object(p.socket,'create_connection',side_effect=[OSError(101,'unreachable'),raw]) as connect:
            connection=p.PinnedHTTPS('baresto.fr',['2001:4860:4860::8888','8.8.8.8'])
            connection._context=Mock(wrap_socket=Mock(return_value=tls))
            connection.connect()
            self.assertEqual(connect.call_count,2)
            self.assertEqual(connect.call_args.args[0],('8.8.8.8',443))
            connection._context.wrap_socket.assert_called_once_with(raw,server_hostname='baresto.fr')
            self.assertIs(connection.sock,tls)
            connection.close()
    def test_tls_failure_closes_socket(self):
        first=Mock(); second=Mock()
        with patch.object(p.socket,'create_connection',side_effect=[first,second]):
            connection=p.PinnedHTTPS('baresto.fr',['8.8.8.8','1.1.1.1'])
            connection._context=Mock(wrap_socket=Mock(side_effect=[p.ssl.SSLError('handshake'),Mock()]))
            connection.connect()
            first.close.assert_called_once()
            self.assertEqual(connection._context.wrap_socket.call_count,2)
            connection.close()
    def test_all_failures_explained(self):
        with patch.object(p.socket,'create_connection',side_effect=ConnectionRefusedError(111,'refused')):
            with self.assertRaisesRegex(Rejected,'Connexion refusée'):
                p.PinnedHTTPS('baresto.fr',['8.8.8.8','1.1.1.1']).connect()
    def test_total_time_budget(self):
        with patch.object(p.time,'monotonic',side_effect=[0,1,21]), patch.object(p.socket,'create_connection',side_effect=TimeoutError) as connect:
            with self.assertRaisesRegex(Rejected,'Délai de connexion dépassé'):
                p.PinnedHTTPS('baresto.fr',['8.8.8.8','1.1.1.1']).connect()
            self.assertEqual(connect.call_count,1)
    def test_dns_error_diagnostic(self):
        with patch.object(p,'collect',side_effect=p.socket.gaierror(-2,'private diagnostic')):
            with self.assertRaisesRegex(Rejected,'Résolution DNS impossible') as error:
                p.collect_company('https://baresto.fr/')
            self.assertNotIn('private diagnostic',str(error.exception))
    def test_nonpublic_address_never_connects(self):
        with patch('backend.core.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]), patch.object(p.socket,'create_connection') as connect:
            with self.assertRaisesRegex(Rejected,'non publique'):
                p.collect('https://baresto.fr/')
            connect.assert_not_called()

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
