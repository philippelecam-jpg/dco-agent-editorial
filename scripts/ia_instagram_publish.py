"""Publier uniquement les pilotes explicitement validés, avec journal avant POST final."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from instagram_reels import Instagram, MetaError, save_entry, publish
from ia_pilots import heygen


def persist():
    # Le cwd est un checkout distinct de main, jamais celui de la branche de code.
    subprocess.run(['bash', str(ROOT / 'scripts/persist_instagram_journal.sh')], check=True)


def validate_manifest(manifest):
    if manifest.get('account') != 'decisionsandco':
        raise ValueError('Compte inattendu.')
    seen = set()
    for item in manifest['episodes']:
        if (item.get('approved') is not True or not re.fullmatch(r'[a-z0-9-]+', item['id'])
                or not re.fullmatch(r'[a-f0-9]{32}', item['video_id'])
                or not 0 < len(item['caption']) <= 2200 or item['id'] in seen):
            raise ValueError('Manifeste non validé ou invalide.')
        seen.add(item['id'])


def download_video(video_id):
    result = heygen('GET', '/videos/' + video_id)
    if result['status'] != 'completed':
        raise RuntimeError('Le rendu n’est pas terminé.')
    response = requests.get(result['video_url'], timeout=180)
    response.raise_for_status()
    data = response.content
    if not 0 < len(data) <= 100_000_000:
        raise ValueError('Taille de vidéo invalide.')
    with tempfile.NamedTemporaryFile(suffix='.mp4') as video:
        video.write(data)
        video.flush()
        probe = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', video.name]))
    streams = probe['streams']
    visual = next(s for s in streams if s['codec_type'] == 'video')
    # Les trois pilotes de 28 à 38 s ont été explicitement demandés pour publication.
    if not (20 <= float(probe['format']['duration']) <= 60
            and abs(visual['width'] / visual['height'] - 9 / 16) < .01
            and any(s['codec_type'] == 'audio' for s in streams)):
        raise ValueError('Contrôle technique du MP4 non satisfait.')
    return data


def publish_item(client, account_id, item, attempt):
    path = Path('historique/instagram') / ('ia-bureau-' + item['id'] + '.json')
    entry = json.loads(path.read_text()) if path.exists() else {
        'episode': item['id'], 'heygen_video_id': item['video_id'], 'caption': item['caption']}
    if entry.get('heygen_video_id') != item['video_id'] or entry.get('caption') != item['caption']:
        raise ValueError('Source ou légende différente du journal : reprise manuelle nécessaire.')
    previous = client.find_published(account_id, item['caption'])
    if previous:
        entry.update(statut='publie', media_id=previous)
    if not entry.get('media_id'):
        # Une tentative précédente reste bloquée même si le POST a perdu sa réponse.
        if entry.get('container_id') or entry.get('statut'):
            raise MetaError('Tentative antérieure non rapprochée : ne pas publier à nouveau.')
        container = client.create_and_upload(account_id, item['caption'], download_video(item['video_id']))
        entry.update(statut='publication_demandee', account_id=account_id,
                     container_id=container, tentative=attempt)
        save_entry(path, entry)
        persist()
        client.wait_until_ready(container)
    save_entry(path, entry)
    persist()
    try:
        publish(client, item, path, entry, attempt)
    finally:
        persist()


def main():
    manifest = json.loads((ROOT / 'pilots/ia_au_bureau/publications.json').read_text())
    validate_manifest(manifest)
    client = Instagram(os.environ['INSTAGRAM_ACCESS_TOKEN'])
    account_id = client.account_id()
    if account_id != '17841462641742654':
        raise ValueError('Identifiant de compte inattendu.')
    attempt = os.environ['GITHUB_RUN_ID'] + ':' + os.environ['GITHUB_RUN_ATTEMPT']
    for item in manifest['episodes']:
        publish_item(client, account_id, item, attempt)


if __name__ == '__main__':
    main()
