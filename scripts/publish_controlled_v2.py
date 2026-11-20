"""Publication unique de la V2 réaliste explicitement validée."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from instagram_reels import Instagram,MetaError,save_entry,publish
from ia_instagram_publish import persist
import ia_controlled as c

def main():
    config=c.load_config()
    video=c.OUT/'IA-au-bureau-realiste-V2.mp4'
    data=video.read_bytes()
    report=c.probe(video)
    assert abs(float(report['format']['duration'])-33.04)<0.1
    assert len([s for s in report['streams'] if s['codec_type']=='audio'])==1
    client=Instagram(os.environ['INSTAGRAM_ACCESS_TOKEN'])
    account=client.account_id()
    assert account=='17841462641742654'
    caption=config['caption']
    path=Path('historique/instagram/ia-bureau-compte-rendu-realiste-v2.json')
    entry=json.loads(path.read_text()) if path.exists() else {'episode':config['id'],'caption':caption,'source_run_id':'44776656793'}
    if entry['caption']!=caption:
        raise ValueError('Légende différente du journal.')
    attempt=os.environ['GITHUB_RUN_ID']+':'+os.environ['GITHUB_RUN_ATTEMPT']
    previous=client.find_published(account,caption)
    if previous: entry.update(statut='publie',media_id=previous)
    if not entry.get('media_id'):
        if entry.get('statut') or entry.get('container_id'):
            raise MetaError('Tentative antérieure à rapprocher avant toute nouvelle publication.')
        entry.update(statut='transfert_demande',video_sha256=hashlib.sha256(data).hexdigest())
        save_entry(path,entry)
        persist()
        container=client.create_and_upload(account,caption,data)
        entry.update(statut='publication_demandee',account_id=account,container_id=container,tentative=attempt)
        save_entry(path,entry)
        persist()
        client.wait_until_ready(container)
    save_entry(path,entry)
    persist()
    try: publish(client,{'caption':caption},path,entry,attempt)
    finally: persist()

if __name__=='__main__': main()
