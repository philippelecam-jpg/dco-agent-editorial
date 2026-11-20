"""Pilotes privés : écriture Claude, réalisation Video Agent, aucune publication sociale."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'pilot-output'
CHECKPOINT = OUT / 'checkpoint.json'
BASE = 'https://api.heygen.com/v3'


def save(value, path=CHECKPOINT):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(path)


def heygen(method, route, **kwargs):
    r = requests.request(method, BASE + route,
        headers={'X-Api-Key': os.environ['HEYGEN_API_KEY']}, timeout=(15, 120), **kwargs)
    if not r.ok:
        try:
            code = r.json().get('error', {}).get('code', 'unknown')
        except (ValueError, AttributeError):
            code = 'unknown'
        raise RuntimeError(f'HeyGen {method} {route}: HTTP {r.status_code}, code={code}')
    return r.json()['data']


def claude(system, user):
    r = requests.post('https://api.anthropic.com/v1/messages',
        headers={'x-api-key': os.environ['ANTHROPIC_API_KEY'], 'anthropic-version': '2023-06-01'},
        json={'model': 'claude-sonnet-4-6', 'max_tokens': 3000, 'system': system,
              'messages': [{'role': 'user', 'content': user}]}, timeout=120)
    r.raise_for_status()
    raw = ''.join(x.get('text', '') for x in r.json()['content']).strip()
    return json.loads(raw.removeprefix('```json').removeprefix('```').removesuffix('```').strip())


def validate_story(story):
    scenes = story['scenes']
    if not 4 <= len(scenes) <= 6:
        raise ValueError('Il faut 4 à 6 scènes.')
    words = 0
    speakers = set()
    for scene in scenes:
        if not scene.get('visual') or not scene.get('lines'):
            raise ValueError('Scène incomplète.')
        for line in scene['lines']:
            if line['speaker'] not in {'Mina', 'Nino'} or not line['text'].strip():
                raise ValueError('Dialogue invalide.')
            words += len(line['text'].split())
            speakers.add(line['speaker'])
    if not 75 <= words <= 105 or len(speakers) != 2:
        raise ValueError(f'Prévoir 75 à 105 mots et les deux voix ; reçu {words}.')
    return story


def generate_story(spec, episode, evidence):
    feedback = ''
    for attempt in range(3):
        story = claude(
            "Tu écris des mini-fictions françaises utiles sur l'IA pour dirigeants de PME. "
            "JSON seul : {title, scenes:[{visual, overlay, lines:[{speaker,text}]}]}. "
            "EXACTEMENT 4 scènes, chacune avec 20 à 23 mots parlés (donc 80 à 92 mots au TOTAL), deux voix Mina et Nino, "
            "phrases courtes et naturelles. Une accroche concrète immédiate, une démonstration, une chute. "
            "Les scènes décrivent les actions et cadrages, pas des diapositives. "
            "Ne pas inventer de fait, de résultat de test ou d'interface. Respecte les notes fournies. "
            "Pas de slogan ni d'introduction de marque. Ne mentionne pas les noms de prestataires.",
            json.dumps({'characters': spec['characters'], 'episode': episode,
                        'demonstration_testee': evidence, 'feedback': feedback}, ensure_ascii=False))
        try:
            return validate_story(story)
        except (ValueError, KeyError, TypeError) as exc:
            if attempt == 2:
                raise
            feedback = str(exc) + " Réduis à 85 mots parlés au TOTAL. Voici le JSON précédent à raccourcir sans ajouter de scène : " + json.dumps(story, ensure_ascii=False)


def prompt_for(spec, episode, story):
    prompt = (
        "Create ONE finished 38-second vertical 9:16 animated short, target 30-45 seconds. "
        "All spoken audio and all screen text in French (France). This is a private editorial pilot. "
        "Use exactly TWO original fictional animated characters. Never use stock human avatars. "
        "The characters physically act in the scene, with facial expressions and reactions; "
        "this must be an animated mini-story, not a slideshow of static portraits. "
        "Maintain character identity and clothing throughout. Two distinct consistent French voices, "
        "female for Mina, male for Nino. Use the following dialogue verbatim, with natural pacing, "
        "no filler, no extra spoken lines, and do not read speaker names. "
        "Generate the necessary illustrated assets and animate the scenes. "
        "Add synchronized readable French subtitles, maximum two lines at once, "
        "high contrast, within the middle 80% width, above the bottom 20%. "
        "Keep faces clear of titles; use visual action from the first frame. "
        "Light original instrumental ambience only, speech always clear, no copyrighted song. "
        "Small persistent disclosure: 'Personnages fictifs · Création IA'. "
        "No fabricated product UI. Graphic cards are conceptual illustrations. "
        "Finish the final spoken sentence, no abrupt cut, a half-second breathing space at end.\n"
        + json.dumps({'series': spec['series'], 'characters': spec['characters'],
                      'style': spec['visual_style'], 'setting': episode['setting'],
                      'editorial_constraints': episode['brief'], 'storyboard': story}, ensure_ascii=False)
        + "\nFINAL FRAMING: full-bleed portrait 9:16, no letterboxing, no landscape panels. "
        "Only the two designed cartoon characters, not real human presenters."
    )
    if len(prompt) > 10000:
        raise ValueError('Prompt trop long.')
    return prompt


def submit():
    if CHECKPOINT.exists() or os.environ.get('GITHUB_RUN_ATTEMPT', '1') != '1':
        raise RuntimeError('Création déjà tentée : reprendre uniquement avec poll.')
    spec = json.loads((ROOT / 'pilots/ia_au_bureau/briefs.json').read_text())
    # Authentification en lecture avant les opérations payantes.
    me = heygen('GET', '/users/me')
    state = {'started_at': int(time.time()), 'episodes': [],
             'balance_before': {k:v for k,v in me.items() if any(w in k.lower() for w in ('credit','balance','quota'))}}
    save(state)
    demo = spec['episodes'][0]
    evidence = claude('Extrais uniquement les actions futures des notes. JSON seul : {actions:[{action,responsable,echeance}]}. Pour une échéance absente écrire exactement non précisée. Ne rien inventer.', demo['demo_notes'])
    actual = evidence.get('actions', [])
    if len(actual) != 2 or not any(x['responsable']=='Mina' and x['echeance']=='non précisée' for x in actual) or not any(x['responsable']=='Nino' and x['echeance'].lower()=='vendredi' for x in actual):
        raise ValueError('La démonstration du compte rendu doit être revue avant réalisation.')
    save({'notes': demo['demo_notes'], 'result': evidence}, OUT / 'demonstration.json')
    for episode in spec['episodes']:
        story = generate_story(spec, episode, evidence if episode.get('demo_notes') else None)
        save(story, OUT / (episode['id'] + '-story.json'))
        prompt = prompt_for(spec, episode, story)
        (OUT / (episode['id'] + '-prompt.txt')).write_text(prompt)
        item = {'id': episode['id'], 'title': story['title'], 'status': 'submitting'}
        state['episodes'].append(item)
        save(state)  # Une réponse réseau ambiguë ne doit jamais relancer un POST.
        result = heygen('POST', '/video-agents', json={
            'prompt': prompt, 'orientation': 'portrait', 'mode': 'generate',
            'visibility': 'private', 'incognito_mode': True})
        item.update(session_id=result['session_id'], video_id=result.get('video_id'), status=result['status'])
        save(state)
        print(json.dumps(item, ensure_ascii=False), flush=True)


def poll():
    state = json.loads(CHECKPOINT.read_text())
    deadline = time.monotonic() + 45 * 60
    while time.monotonic() < deadline:
        pending = False
        for item in state['episodes']:
            if item['status'] in ('downloaded', 'failed', 'waiting_for_input'):
                continue
            if not item.get('session_id'):
                raise RuntimeError('Session non confirmée : examiner HeyGen avant toute reprise.')
            session = heygen('GET', '/video-agents/' + item['session_id'])
            item['status'] = session['status']
            item['video_id'] = session.get('video_id') or item.get('video_id')
            if item['status'] in ('failed', 'waiting_for_input'):
                save(state)
                print(item['id'], item['status'], flush=True)
                continue
            if item.get('video_id'):
                video = heygen('GET', '/videos/' + item['video_id'])
                if video['status'] == 'failed':
                    item['status'] = 'failed'
                    item['failure_code'] = video.get('failure_code')
                elif video['status'] == 'completed':
                    r = requests.get(video['video_url'], timeout=180)
                    r.raise_for_status()
                    path = OUT / (item['id'] + '.mp4')
                    path.write_bytes(r.content)
                    probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
                    vs = next(s for s in probe['streams'] if s['codec_type']=='video')
                    item.update(status='downloaded', duration=float(probe['format']['duration']),
                                width=vs['width'], height=vs['height'],
                                has_audio=any(s['codec_type']=='audio' for s in probe['streams']),
                                review_url='https://app.heygen.com/videos/'+item['video_id'])
                    item['technical_pass'] = 30 <= item['duration'] <= 45 and abs(item['width']/item['height']-9/16)<.01 and item['has_audio']
                    for n,fraction in enumerate([.05,.35,.65,.9]):
                        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(item['duration']*fraction),'-i',str(path),'-frames:v','1','-vf','scale=270:480',str(OUT/f"{item['id']}-{n}.jpg")],check=True)
            save(state)
            print(item['id'], item['status'], flush=True)
            pending |= item['status'] not in ('downloaded', 'failed', 'waiting_for_input')
        if not pending:
            break
        time.sleep(30)
    state['finished_at'] = int(time.time())
    me = heygen('GET', '/users/me')
    state['balance_after'] = {k:v for k,v in me.items() if any(w in k.lower() for w in ('credit','balance','quota'))}
    save(state)
    print(json.dumps(state, ensure_ascii=False), flush=True)
    if len(state['episodes']) != 3 or any(x['status']!='downloaded' for x in state['episodes']):
        raise RuntimeError('Pilotes incomplets ; checkpoint conservé pour reprise sans nouvelle génération.')


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('mode', choices=['submit','poll'])
    args=parser.parse_args()
    {'submit':submit,'poll':poll}[args.mode]()
