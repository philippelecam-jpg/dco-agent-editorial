"""Controlled first capsule using existing GitHub secrets, without emailing prospects."""
import json,os,time
from pathlib import Path
from .core import domain,site_url,Rejected
from . import providers as p

VIDEO_KEYS=('ANTHROPIC_API_KEY','ELEVENLABS_API_KEY','ELEVENLABS_VOICE_ID','HEYGEN_API_KEY')
YOUTUBE_KEYS=('YOUTUBE_CLIENT_ID','YOUTUBE_CLIENT_SECRET','YOUTUBE_REFRESH_TOKEN')


def manual_source(source_url):
    text=' '.join(os.getenv('SOURCE_TEXT','').split())
    if not text: return None
    if len(text)<120: raise Rejected('Source texte trop courte : fournir au moins 120 caractères factuels.')
    if len(text)>12000: raise Rejected('Source texte trop longue : limiter à 12 000 caractères.')
    return {'url':source_url+'#source-text','text':text,'collected_at':time.strftime('%Y-%m-%d'),'manual':True}


def log(event,**fields):
    payload={'event':event,**fields}
    print(json.dumps(payload,ensure_ascii=False),flush=True)


def failure_reason(exc):
    if isinstance(exc,Rejected): return str(exc)
    return 'Erreur inattendue : '+type(exc).__name__


def public_report(state,company,host,source_url,status,stage,reason=None,include_excerpts=False):
    report={key:value for key,value in state.items() if key not in ('youtube_session','sources','heygen_id')}
    report.update({'company':company,'domain':host,'site_url':source_url,'status':status,'stage':stage})
    if reason: report['reason']=reason
    if state.get('pending'): report['provider_call_pending']=state['pending']
    sources=state.get('sources') or []
    if sources:
        report['sources']=[{
            'url':source.get('url'),
            'collected_at':source.get('collected_at'),
            'characters':len(source.get('text','')),
            **({'excerpt':source.get('text','')[:1200]} if include_excerpts else {})
        } for source in sources]
    return report


def write_report(out,state,company,host,source_url,status,stage,reason=None,include_excerpts=False):
    out.mkdir(exist_ok=True)
    report=public_report(state,company,host,source_url,status,stage,reason,include_excerpts)
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))


def main():
    mode=os.getenv('TEST_MODE','check')
    if mode not in ('check','video','youtube_private'): raise Rejected('Mode inconnu.')
    missing=[key for key in VIDEO_KEYS+YOUTUBE_KEYS if not os.getenv(key)]
    log('configuration',mode=mode,missing_configuration=missing)
    if missing: raise Rejected('Secrets requis absents : '+', '.join(missing))
    if mode=='check':
        log('configuration_ok',message='Aucun appel payant et aucune vidéo créée.')
        return
    source_url=site_url(os.environ['COMPANY_SITE'])
    host=domain(source_url); company=os.environ['COMPANY_NAME'].strip()
    if not company or len(company)>150: raise Rejected('Nom de société invalide.')
    out=Path('test-output');out.mkdir(exist_ok=True)
    state_path=out/'checkpoint.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {}
    stage='initialisation'
    def save(): state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    def paid(operation, action):
        log('provider_call_started',operation=operation)
        state['pending']=operation;save()
        result=action();state.pop('pending',None)
        log('provider_call_completed',operation=operation)
        return result
    try:
        if state.get('domain',host)!=host or state.get('company',company)!=company: raise Rejected('Le checkpoint appartient à une autre société.')
        if state.get('pending'): raise Rejected('Reprise suspendue : appel fournisseur %s dont le résultat est incertain. Vérifier le fournisseur avant toute nouvelle tentative.' % state['pending'])
        if state.get('voice_ready') and not (out/'voice.mp3').is_file():
            raise Rejected('Reprise impossible : voix marquée terminée mais voice.mp3 absent de l’artefact.')
        if state.get('video_ready') and not (out/'rachel.mp4').is_file():
            raise Rejected('Reprise impossible : vidéo marquée terminée mais rachel.mp4 absent de l’artefact.')
        supplied_source=manual_source(source_url)
        state.update({'domain':host,'company':company,'site_url':source_url,'source_mode':'text' if supplied_source else 'site'});save()
        if 'script' not in state:
            stage='collection'
            log('stage_started',stage=stage,site_url=source_url,source_mode=state['source_mode'])
            sources=[supplied_source] if supplied_source else p.collect_company(source_url)
            state['sources']=sources;save()
            log('stage_completed',stage=stage,sources=len(sources),source_mode=state['source_mode'])
            usage=[]
            stage='script'
            log('stage_started',stage=stage)
            script=p.verified_script(company,sources,lambda operation,value:usage.append({'operation':operation,'usage':value}))
            state.update({'script':script,'anthropic_usage':usage});save()
            log('stage_completed',stage=stage,title=script.get('title'),format=script.get('format'))
        audio=out/'voice.mp3'
        if not state.get('voice_ready'):
            stage='voice'
            log('stage_started',stage=stage)
            paid('voice',lambda:p.voice(state['script']['voice'],audio))
            stage='voice_duration'
            state['voice_seconds']=p.duration(audio);state['voice_ready']=True;save()
            log('stage_completed',stage='voice',seconds=state['voice_seconds'])
        if 'heygen_id' not in state:
            stage='heygen_start'
            log('stage_started',stage=stage)
            state['heygen_id']=paid('heygen',lambda:p.avatar_start(audio,state['script']['title']));save()
            log('stage_completed',stage=stage)
        video=out/'rachel.mp4'
        if not state.get('video_ready'):
            stage='heygen_poll'
            deadline=time.monotonic()+1200
            started=time.monotonic()
            while time.monotonic()<deadline:
                data=p.avatar_get(state['heygen_id'])
                log('heygen_status',status=data.get('status'),elapsed_seconds=round(time.monotonic()-started))
                if data['status']=='failed': raise Rejected('HeyGen a refusé la génération.')
                if data['status']=='completed':
                    stage='video_download'
                    log('stage_started',stage=stage)
                    video.write_bytes(p.req('GET',data['video_url'],timeout=180).content)
                    stage='video_duration'
                    state['video_seconds']=p.duration(video);state['video_ready']=True;save()
                    log('stage_completed',stage='video',seconds=state['video_seconds'])
                    break
                time.sleep(15)
            else: raise Rejected('HeyGen toujours en cours. Le checkpoint conserve son identifiant.')
        if mode=='youtube_private' and not state.get('youtube_id'):
            # This test never makes a video public, regardless of repository settings.
            os.environ['YOUTUBE_PRIVACY']='private'
            if 'youtube_session' not in state:
                stage='youtube_start'
                log('stage_started',stage=stage)
                description=state['script']['voice']+'\n\nSources :\n'+'\n'.join(s['url'] for s in state['sources'])+'\n\nRachel est une présentatrice IA. Test Décisions & Co.'
                state['youtube_session']=p.youtube_start(state['script']['title'],description);save()
                log('stage_completed',stage=stage)
            stage='youtube_upload'
            log('stage_started',stage=stage)
            state['youtube_id']=paid('youtube_upload',lambda:p.youtube_upload(state['youtube_session'],video));save()
            log('stage_completed',stage=stage,youtube_id=state['youtube_id'])
        write_report(out,state,company,host,source_url,'completed','complete')
        log('completed',video_seconds=state['video_seconds'],youtube_id=state.get('youtube_id'),video_artifact='rachel.mp4',report_artifact='report.json')
    except Exception as exc:
        # A documented HTTP 401 is an explicit rejection: no synthesis was authorized.
        # Other network/provider failures remain pending, since they may have been charged.
        if stage=='voice' and state.get('pending')=='voice' and isinstance(exc, RuntimeError) and 'Appel fournisseur refusé (HTTP 401)' in str(exc):
            state.pop('pending',None)
            save()
            log('provider_call_rejected',operation='voice',http_status=401,retry_safe=True)
        reason=failure_reason(exc)
        status='blocked' if isinstance(exc,Rejected) else 'failed'
        write_report(out,state,company,host,source_url,status,stage,reason,include_excerpts=stage in ('script','collection'))
        log('failed',status=status,stage=stage,reason=reason)
        raise

if __name__=='__main__': main()
