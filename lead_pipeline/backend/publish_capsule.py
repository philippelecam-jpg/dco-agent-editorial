"""Publish an existing capsule, without Claude, voice or avatar generation."""
import json, os, re, time
from pathlib import Path
from . import providers as p
from .core import Rejected
from .first_capsule import log, failure_reason, public_report


def main():
    mode=os.getenv('TEST_MODE','youtube_unlisted')
    if mode not in ('youtube_private','youtube_unlisted','youtube_existing'):
        raise Rejected('Mode de publication inconnu.')
    out=Path('test-output')
    report_path=out/'report.json'
    video=out/'rachel.mp4'
    if not report_path.exists() or not video.exists(): raise Rejected('Vidéo ou rapport manquant : aucune génération automatique.')
    state=json.loads(report_path.read_text())
    if not state.get('video_ready') or not state.get('script'): raise Rejected('La capsule source n’est pas terminée.')
    checkpoint=out/'publication-checkpoint.json'
    if checkpoint.exists(): state.update(json.loads(checkpoint.read_text()))
    if state.get('pending'): raise Rejected('Téléversement interrompu. Vérifiez YouTube avant toute reprise.')
    existing_id=os.getenv('EXISTING_YOUTUBE_ID','')
    if existing_id:
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}',existing_id): raise Rejected('Identifiant YouTube existant invalide.')
        state['youtube_id']=existing_id
    privacy='private' if mode=='youtube_private' else 'unlisted'
    os.environ['YOUTUBE_PRIVACY']=privacy
    stage='youtube_start'
    def save(): checkpoint.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    def report(status,reason=None):
        result=public_report(state,state['company'],state['domain'],state['site_url'],status,stage,reason)
        report_path.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    try:
        state['youtube_privacy']=privacy
        if not state.get('youtube_id'):
            if not state.get('youtube_session'):
                log('stage_started',stage=stage)
                description=state['script']['voice']+'\n\nSources :\n'+'\n'.join(s['url'] for s in state.get('sources',[]))+'\n\nPrésentatrice et voix générées par IA. Créée avec La Fabrik, par Décisions & Co.'
                state['youtube_session']=p.youtube_start(state['script']['title'],description);save()
            stage='youtube_upload';log('stage_started',stage=stage)
            state['pending']='youtube_upload';save()
            video_id=p.youtube_upload(state['youtube_session'],video)
            if not isinstance(video_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}',video_id): raise Rejected('Identifiant vidéo YouTube invalide.')
            state['youtube_id']=video_id;state.pop('pending',None);save()
            log('stage_completed',stage=stage,youtube_id=video_id)
        stage='youtube_processing'
        if privacy=='private':
            report('completed');log('completed',youtube_id=state['youtube_id'],privacy=privacy)
            return
        deadline=time.monotonic()+600
        while time.monotonic()<deadline:
            if p.youtube_ready(state['youtube_id']):
                state['youtube_ready']=True;save();report('published')
                log('published',youtube_id=state['youtube_id'],youtube_url='https://www.youtube.com/watch?v='+state['youtube_id'],privacy=privacy)
                return
            log('youtube_processing',youtube_id=state['youtube_id'],message='Traitement en cours ou visibilité privée. Aucun nouvel upload.');time.sleep(15)
        raise Rejected('YouTube n’a pas confirmé une vidéo lisible après dix minutes. Vérifiez le traitement et la visibilité ; aucun nouvel upload automatique.')
    except Exception as exc:
        report('completed',failure_reason(exc)) # The MP4 exists: never regenerate it after a publication failure.
        log('publication_failed',stage=stage,reason=failure_reason(exc),youtube_id=state.get('youtube_id'))
        raise

if __name__=='__main__': main()
