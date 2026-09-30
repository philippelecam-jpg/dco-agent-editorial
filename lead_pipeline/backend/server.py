"""Same-origin portal/API behind a TLS reverse proxy. Never expose this HTTP port directly."""
import html,json,os,secrets,time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .core import Store,Rejected,digest
from .worker import configuration

ROOT=Path(__file__).resolve().parent.parent/'dist'
STORE=None

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass  # Avoid email tokens and query strings in logs.
    def send(self,status,payload,cookie=None):
        body=json.dumps(payload,ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Referrer-Policy','no-referrer'); self.send_header('X-Content-Type-Options','nosniff')
        if cookie: self.send_header('Set-Cookie',cookie)
        self.end_headers(); self.wfile.write(body)
    def session(self):
        cookies=SimpleCookie(self.headers.get('Cookie',''))
        return cookies['rachel_session'].value if 'rachel_session' in cookies else ''
    def admin(self):
        secret=os.getenv('ADMIN_TOKEN','')
        if not secret or not secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+secret): raise Rejected('Accès administrateur refusé.')
    def do_GET(self):
        path=urlsplit(self.path).path
        try:
            if path=='/api/health': return self.send(200,{'ready':not configuration(),'mode':'live' if not configuration() else 'unconfigured'})
            if path=='/api/me':
                lead=STORE.lead(self.session()); row=STORE.request_for(lead['id'])
                result=None
                if row:
                    data=json.loads(row['data'])
                    result={k:row[k] for k in ('id','domain','status','error','created')}
                    result.update({'url':data.get('url'),'seconds':data.get('seconds'),'format':data.get('script',{}).get('format')})
                return self.send(200,{'name':lead['name'],'company':lead['company'],'request':result})
            if path=='/api/admin':
                self.admin()
                with STORE.connect() as db:
                    rows=[dict(r) for r in db.execute('SELECT r.id,r.domain,r.status,r.error,r.created,l.company,l.email FROM requests r JOIN leads l ON l.id=r.lead_id ORDER BY r.created DESC LIMIT 100')]
                    usage=[dict(r) for r in db.execute('SELECT * FROM usage ORDER BY created DESC LIMIT 200')]
                return self.send(200,{'requests':rows,'usage':usage,'missing_configuration':configuration()})
            if path=='/config.js':
                content=('window.RACHEL_CONFIG='+json.dumps({'mode':'live','apiBase':'','turnstileSiteKey':os.getenv('TURNSTILE_SITE_KEY','')})+';').encode()
                return self.asset(content,'text/javascript')
            files={'/':'index.html','/app.js':'app.js','/styles.css':'styles.css','/favicon.svg':'favicon.svg'}
            if path in files:
                target=ROOT/files[path]
                mime={'html':'text/html; charset=utf-8','js':'text/javascript','css':'text/css','svg':'image/svg+xml'}[target.suffix[1:]]
                return self.asset(target.read_bytes(),mime)
            return self.send(404,{'error':'Page introuvable.'})
        except Rejected as exc: self.send(401,{'error':str(exc)})
        except Exception: self.send(503,{'error':'Service momentanément indisponible.'})
    def asset(self,content,mime):
        self.send_response(200); self.send_header('Content-Type',mime); self.send_header('Cache-Control','no-store'); self.send_header('Referrer-Policy','no-referrer'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(content)
    def do_POST(self):
        try:
            base=os.getenv('PUBLIC_BASE_URL','').rstrip('/')
            if not base or self.headers.get('Origin')!=base: raise Rejected('Origine de la demande refusée.')
            if not self.headers.get('Content-Type','').startswith('application/json'): raise Rejected('Format JSON requis.')
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=8192: raise Rejected('Demande trop volumineuse.')
            data=json.loads(self.rfile.read(length)); path=urlsplit(self.path).path
            if path=='/api/signup':
                if configuration(): return self.send(503,{'error':'Le service est en préparation. Les demandes réelles ne sont pas encore ouvertes.'})
                STORE.limit('signup-ip:'+digest(self.client_address[0]),maximum=15)
                STORE.limit('signup-email:'+digest(str(data.get('email','')).lower()),maximum=3)
                # Public launch requires Turnstile to prevent paid abuse.
                from .providers import req,required
                check=req('POST','https://challenges.cloudflare.com/turnstile/v0/siteverify',data={'secret':required('TURNSTILE_SECRET_KEY'),'response':data.get('captcha','')}).json()
                if check.get('success') is not True or check.get('hostname')!=urlsplit(base).hostname: raise Rejected('Vérification anti-abus requise.')
                lead_id,token=STORE.signup(data.get('email',''),data.get('name',''),data.get('company',''))
                link=base+'/?verify='+token
                STORE.queue_mail('verify-'+digest(token),lead_id,'Votre accès à Rachel Entreprises','<p>Votre lien personnel est valable 15 minutes.</p><p><a href="'+html.escape(link,quote=True)+'">Accéder à mon espace</a></p>')
                return self.send(200,{'message':'Si cette adresse est valide, vous recevrez un lien d’accès.'})
            if path=='/api/verify':
                STORE.limit('verify:'+digest(self.client_address[0]),maximum=30)
                session=STORE.verify(data.get('token',''))
                secure='; Secure' if base.startswith('https://') else ''
                return self.send(200,{'verified':True},'rachel_session='+session+'; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800'+secure)
            if path=='/api/request':
                if configuration(): return self.send(503,{'error':'Production non configurée.'})
                STORE.limit('request-global:'+time.strftime('%Y-%m-%d'),maximum=int(os.getenv('MAX_DAILY_REQUESTS','10')),seconds=86400)
                request_id=STORE.reserve(self.session(),data.get('site',''),data.get('acknowledged'),data.get('siren') or None)
                return self.send(201,{'id':request_id})
            if path=='/api/admin/retry':
                self.admin(); row=STORE.get(data.get('id',''))
                if not row or row['status']!='blocked': raise Rejected('Demande non reprenable.')
                state=json.loads(row['data'])
                if state.get('pending_paid'): raise Rejected('Résultat fournisseur incertain. Réconciliez l’identifiant fournisseur avant reprise.')
                STORE.checkpoint(row['id'],'queued',state)
                return self.send(200,{'queued':True})
            return self.send(404,{'error':'Action inconnue.'})
        except (Rejected,ValueError,TypeError) as exc: self.send(400,{'error':str(exc)})
        except Exception: self.send(503,{'error':'Service momentanément indisponible.'})

if __name__=='__main__':
    STORE=Store()
    ThreadingHTTPServer((os.getenv('BIND_HOST','127.0.0.1'),int(os.getenv('PORT','8000'))),Handler).serve_forever()
