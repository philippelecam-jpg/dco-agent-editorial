"""Signed delivery of a capsule result to the lead Worker. No prospect address here."""
import hashlib, hmac, json, os, time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def refusal_reason(exc):
    # Only fixed known diagnostics are shown, never arbitrary server content.
    reason='Réponse non reconnue : consultez les événements Cloudflare.'
    try:
        raw=exc.read(4096)
        data=json.loads(raw)
        known={
            'Signature invalide.':'Signature rejetée par La Fabrik : vérifier le secret partagé et les en-têtes de signature.',
            'Retour non configuré.':'LEAD_CALLBACK_SECRET absent du Worker.',
            'Tentative obsolète.':'Cette tentative a été remplacée par une autre demande.',
        }
        if isinstance(data,dict): reason=known.get(data.get('error'),reason)
    except (ValueError,TypeError,OSError):
        pass
    return 'Retour Worker refusé (HTTP %s). %s' % (exc.code,reason)


def main():
    url=os.getenv('LEAD_CALLBACK_URL','')
    if not url: return
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path!='/api/capsule-result': raise ValueError('URL de retour invalide.')
    secret=os.environ.get('LEAD_CALLBACK_SECRET','')
    if not secret: raise ValueError('LEAD_CALLBACK_SECRET absent.')
    path=Path('test-output/report.json')
    report=json.loads(path.read_text()) if path.exists() else {}
    status='published' if report.get('youtube_ready') else ('completed' if report.get('video_ready') else 'failed')
    payload={'request_id':os.environ['LEAD_REQUEST_ID'],'request_key':os.environ['LEAD_REQUEST_KEY'],'github_run_id':os.environ['GITHUB_RUN_ID'],'status':status,'youtube_id':report.get('youtube_id'), 'publication_pending':report.get('provider_call_pending')=='youtube_upload','error':str(report.get('reason') or ('Le workflow a échoué avant le rapport.' if not report else ''))[:500]}
    body=json.dumps(payload,separators=(',',':'),ensure_ascii=False).encode()
    for attempt in range(3):
        timestamp=str(int(time.time()))
        signature=hmac.new(secret.encode(),timestamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
        try:
            request=Request(url,data=body,headers={'Content-Type':'application/json','X-Lead-Timestamp':timestamp,'X-Lead-Signature':signature},method='POST')
            with urlopen(request,timeout=20) as response: http_status=response.status
            if http_status==200:
                print(json.dumps({'event':'lead_result_delivered','status':status}),flush=True);return
            if http_status in (400,401,403,404,409): raise ValueError('Retour Worker refusé (HTTP %s).' % http_status)
        except HTTPError as exc:
            if exc.code in (400,401,403,404,409): raise ValueError(refusal_reason(exc)) from None
        except (URLError, OSError):
            pass
        if attempt<2: time.sleep(3)
    raise RuntimeError('Retour Worker indisponible : la vidéo et le rapport restent dans les artifacts.')

if __name__=='__main__': main()
