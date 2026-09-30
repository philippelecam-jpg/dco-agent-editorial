"""Controlled first capsule using existing GitHub secrets, without emailing prospects."""
import json,os,time
from pathlib import Path
from .core import domain,Rejected
from . import providers as p

VIDEO_KEYS=('ANTHROPIC_API_KEY','ELEVENLABS_API_KEY','ELEVENLABS_VOICE_ID','HEYGEN_API_KEY')
YOUTUBE_KEYS=('YOUTUBE_CLIENT_ID','YOUTUBE_CLIENT_SECRET','YOUTUBE_REFRESH_TOKEN')

def main():
    mode=os.getenv('TEST_MODE','check')
    if mode not in ('check','video','youtube_private'): raise Rejected('Mode inconnu.')
    missing=[key for key in VIDEO_KEYS+YOUTUBE_KEYS if not os.getenv(key)]
    print(json.dumps({'mode':mode,'missing_configuration':missing},ensure_ascii=False))
    if missing: raise Rejected('Secrets requis absents : '+', '.join(missing))
    if mode=='check':
        print('Configuration présente. Aucun appel payant et aucune vidéo créée.'); return
    host=domain(os.environ['COMPANY_SITE']); company=os.environ['COMPANY_NAME'].strip()
    if not company or len(company)>150: raise Rejected('Nom de société invalide.')
    out=Path('test-output');out.mkdir(exist_ok=True)
    state_path=out/'checkpoint.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {}
    if state.get('domain',host)!=host or state.get('company',company)!=company: raise Rejected('Le checkpoint appartient à une autre société.')
    if state.get('pending'): raise Rejected('Appel fournisseur interrompu. Vérifier son résultat avant de relancer.')
    state.update({'domain':host,'company':company})
    def save(): state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    def paid(operation, action):
        state['pending']=operation;save()
        result=action();state.pop('pending',None);return result
    if 'script' not in state:
        sources=[p.collect('https://'+host)]
        for path in ('/actualites','/news'):
            try: sources.append(p.collect('https://'+host+path))
            except Exception: pass
        usage=[]
        try:
            script=p.verified_script(company,sources,lambda operation,value:usage.append({'operation':operation,'usage':value}))
        except Rejected as exc:
            (out/'report.json').write_text(json.dumps({'company':company,'domain':host,'status':'blocked','reason':str(exc),'anthropic_usage':usage},ensure_ascii=False,indent=2))
            raise
        state.update({'script':script,'sources':sources,'anthropic_usage':usage});save()
    audio=out/'voice.mp3'
    if not state.get('voice_ready'):
        paid('voice',lambda:p.voice(state['script']['voice'],audio))
        state['voice_seconds']=p.duration(audio);state['voice_ready']=True;save()
    if 'heygen_id' not in state:
        state['heygen_id']=paid('heygen',lambda:p.avatar_start(audio,state['script']['title']));save()
    video=out/'rachel.mp4'
    if not state.get('video_ready'):
        deadline=time.monotonic()+1200
        while time.monotonic()<deadline:
            data=p.avatar_get(state['heygen_id'])
            if data['status']=='failed': raise Rejected('HeyGen a refusé la génération.')
            if data['status']=='completed':
                video.write_bytes(p.req('GET',data['video_url'],timeout=180).content)
                state['video_seconds']=p.duration(video);state['video_ready']=True;save();break
            time.sleep(15)
        else: raise Rejected('HeyGen toujours en cours. Le checkpoint conserve son identifiant.')
    if mode=='youtube_private' and not state.get('youtube_id'):
        # This test never makes a video public, regardless of repository settings.
        os.environ['YOUTUBE_PRIVACY']='private'
        if 'youtube_session' not in state:
            description=state['script']['voice']+'\n\nSources :\n'+'\n'.join(s['url'] for s in state['sources'])+'\n\nRachel est une présentatrice IA. Test Décisions & Co.'
            state['youtube_session']=p.youtube_start(state['script']['title'],description);save()
        state['youtube_id']=paid('youtube_upload',lambda:p.youtube_upload(state['youtube_session'],video));save()
    # Do not upload session URLs or other operational capability data as artifacts.
    report={key:value for key,value in state.items() if key not in ('youtube_session','sources')}
    report['sources']=[{'url':s['url'],'collected_at':s['collected_at']} for s in state['sources']]
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'video_seconds':state['video_seconds'],'youtube_id':state.get('youtube_id'),'video_artifact':'rachel.mp4'},ensure_ascii=False))

if __name__=='__main__': main()
