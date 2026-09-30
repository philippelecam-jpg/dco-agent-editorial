"""Single durable worker. Restart safely; ambiguous paid calls block, never repeat."""
import html,json,os,time
from pathlib import Path
from .core import Store,Rejected
from . import providers as p

REQUIRED=('ANTHROPIC_API_KEY','ELEVENLABS_API_KEY','ELEVENLABS_VOICE_ID','HEYGEN_API_KEY','RACHEL_PHOTO_ASSET_ID','YOUTUBE_CLIENT_ID','YOUTUBE_CLIENT_SECRET','YOUTUBE_REFRESH_TOKEN','YOUTUBE_PRIVACY','RESEND_API_KEY','EMAIL_FROM','PUBLIC_BASE_URL','TURNSTILE_SITE_KEY','TURNSTILE_SECRET_KEY','ADMIN_TOKEN')

def configuration():
    return [name for name in REQUIRED if not os.getenv(name)]

def run(store,request_id):
    row=store.get(request_id); data=json.loads(row['data']); work=Path(os.getenv('ARTIFACT_PATH','data/artifacts'))/request_id; work.mkdir(parents=True,exist_ok=True)
    def save(stage): store.checkpoint(request_id,stage,data)
    try:
        if configuration(): raise Rejected('Fournisseurs non raccordés : '+', '.join(configuration()))
        if 'sources' not in data:
            sources=[p.collect('https://'+row['domain'])]
            # V1: official site + bounded common news pages; no invented external search.
            for path in ('/actualites','/news'):
                try: sources.append(p.collect('https://'+row['domain']+path))
                except Exception: pass
            data['sources']=sources; save('writing')
        if 'script' not in data:
            result=p.verified_script(row['company'],data['sources'],lambda operation,usage:store.usage(request_id,'anthropic',operation,usage))
            data['script']=result; save('voice')
        audio=work/'voice.mp3'
        if not data.get('audio_ready'):
            data['pending_paid']='voice'; save('voice')
            p.voice(data['script']['voice'],audio); data['audio_seconds']=p.duration(audio)
            data['audio_ready']=True; data.pop('pending_paid',None); store.usage(request_id,'elevenlabs','voice',{'characters':len(data['script']['voice']),'seconds':data['audio_seconds']}); save('avatar')
        if 'heygen_id' not in data:
            data['pending_paid']='heygen'; save('avatar')
            data['heygen_id']=p.avatar_start(audio,data['script']['title']); data.pop('pending_paid',None); store.usage(request_id,'heygen','video',{'seconds':data['audio_seconds']}); save('avatar')
        video=work/'rachel.mp4'
        if not data.get('video_ready'):
            status=p.avatar_get(data['heygen_id'])
            if status['status']=='failed': raise Rejected('Génération Rachel échouée.')
            if status['status']!='completed': save('avatar'); return
            video.write_bytes(p.req('GET',status['video_url'],timeout=180).content)
            data['seconds']=p.duration(video); data['video_ready']=True; save('upload')
        if 'youtube_session' not in data:
            sources='\n'.join(s['url'] for s in data['sources'])
            description=data['script']['voice']+'\n\nSources consultées :\n'+sources+'\n\nRachel est une présentatrice IA. Capsule produite par Décisions & Co.'
            data['youtube_session']=p.youtube_start(data['script']['title'],description); save('upload')
        if 'youtube_id' not in data:
            data['pending_paid']='youtube_upload'; save('upload')
            data['youtube_id']=p.youtube_upload(data['youtube_session'],video); data.pop('pending_paid',None); save('processing')
        if not p.youtube_ready(data['youtube_id']): save('processing'); return
        data['url']='https://www.youtube.com/watch?v='+data['youtube_id']
        store.queue_mail('delivery-'+request_id,row['lead_id'],'Votre capsule Rachel est disponible','<p>Votre capsule est prête.</p><p><a href="'+html.escape(data['url'],quote=True)+'">Voir la vidéo</a></p>')
        save('delivery')
    except Exception as exc:
        store.checkpoint(request_id,'blocked',data,str(exc) if isinstance(exc,Rejected) else 'Erreur fournisseur. Contrôle nécessaire avant reprise.')

def flush_mail(store):
    with store.connect() as db: rows=db.execute('SELECT m.*,l.email FROM mail m JOIN leads l ON l.id=m.lead_id WHERE m.sent=0 ORDER BY m.created LIMIT 10').fetchall()
    for row in rows:
        if row['id'].startswith('verify-') and time.time()-row['created']>900:
            with store.connect() as db: db.execute('UPDATE mail SET sent=-1 WHERE id=?',(row['id'],))
            continue
        # Resend idempotency window is finite: do not resend ambiguous ancient mail.
        if time.time()-row['created']>23*3600:
            with store.connect() as db: db.execute('UPDATE mail SET sent=-1 WHERE id=?',(row['id'],))
            continue
        try:
            p.mail(row['id'],row['email'],row['subject'],row['html'])
            with store.connect() as db:
                db.execute('UPDATE mail SET sent=1 WHERE id=?',(row['id'],))
                if row['id'].startswith('delivery-'): db.execute("UPDATE requests SET status='completed',updated=? WHERE id=?",(time.time(),row['id'][9:]))
        except Exception: pass

def tick(store):
    flush_mail(store)
    with store.connect() as db: rows=db.execute("SELECT id,status,data FROM requests WHERE status NOT IN ('queued','blocked','completed','delivery') ORDER BY updated LIMIT 10").fetchall()
    for row in rows:
        data=json.loads(row['data'])
        if data.get('pending_paid'):
            store.checkpoint(row['id'],'blocked',data,'Résultat fournisseur incertain : vérifier avant toute reprise.')
        else: run(store,row['id'])
    job=store.claim()
    if job: run(store,job)

if __name__=='__main__':
    import fcntl
    store=Store(); lock=open(store.path+'.worker.lock','w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    while True:
        tick(store); time.sleep(15)
