"""Dialogue privé contrôlé : une identité, une voix et un fichier audio par plan."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
import io
import zipfile
import re
import unicodedata
from difflib import SequenceMatcher
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'controlled-output'
CONFIG = ROOT / 'pilots/ia_au_bureau/realiste_v2.json'
BASE = 'https://api.heygen.com/v3'
ARCHIVE_CONTEXT = b'ia-bureau-controlled-restart-v1'


def restart_cipher():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(hashlib.sha256(ARCHIVE_CONTEXT + b'\0' + os.environ['HEYGEN_API_KEY'].encode()).digest())


def archive_restart():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in OUT.iterdir():
            if path.is_file():
                archive.writestr(path.name, path.read_bytes())
    nonce = os.urandom(12)
    (ROOT / 'controlled-restart.enc').write_bytes(nonce + restart_cipher().encrypt(nonce, buffer.getvalue(), ARCHIVE_CONTEXT))


def restore_restart():
    data = (ROOT / 'controlled-restart.enc').read_bytes()
    payload = restart_cipher().decrypt(data[:12], data[12:], ARCHIVE_CONTEXT)
    OUT.mkdir(exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            if Path(name).name != name or name in {'.', '..'}:
                raise ValueError('Chemin de reprise invalide.')
            (OUT / name).write_bytes(archive.read(name))


def save(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def api(method, route, **kwargs):
    try:
        r = requests.request(method, BASE + route, headers={'x-api-key': os.environ['HEYGEN_API_KEY']},
                             timeout=(15, 180), **kwargs)
    except requests.RequestException:
        raise RuntimeError('Réponse HeyGen incertaine : checkpoint conservé, aucun POST automatique répété.') from None
    if not r.ok:
        try:
            code = r.json().get('error', {}).get('code', 'unknown')
        except (ValueError, AttributeError):
            code = 'unknown'
        raise RuntimeError(f'HeyGen HTTP {r.status_code}, code {code}')
    return r.json()['data']


def download(url, path):
    try:
        r = requests.get(url, timeout=(15, 180))
        if not r.ok:
            raise RuntimeError(f'Téléchargement HTTP {r.status_code}')
        path.write_bytes(r.content)
    except requests.RequestException:
        raise RuntimeError('Téléchargement interrompu ; reprendre les fichiers existants.') from None


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))


def duration(path):
    return float(probe(path)['format']['duration'])


def load_config():
    config = json.loads(CONFIG.read_text())
    style = os.environ.get('PILOT_FORMAT', 'realiste')
    if style not in {'realiste', 'animation'}:
        raise ValueError('Format inconnu.')
    if style == 'animation':
        config['id'] = config['id'].replace('realiste', 'anime')
        for character in config['characters'].values():
            character['image'] = character['image'].replace('realiste', 'anime')
    chars = config['characters']
    if chars['Mina']['voice_id'] == chars['Nino']['voice_id']:
        raise ValueError('Les personnages doivent avoir deux voix distinctes.')
    if not 2 <= len(config['scenes']) <= 8:
        raise ValueError('Nombre de scènes invalide.')
    for scene in config['scenes']:
        if scene['speaker'] not in chars or not scene['text'].strip():
            raise ValueError('Une seule voix explicitement attribuée par scène est requise.')
    return config


def once(state, entry, key, callback):
    """Une réponse perdue bloque la reprise payante au lieu de générer un doublon."""
    if key in entry:
        return entry[key]
    marker = key + '_submitting'
    if entry.get(marker):
        raise RuntimeError(f'Tentative {key} incertaine : rapprochement manuel requis.')
    entry[marker] = True
    save(state, OUT / 'checkpoint.json')
    entry[key] = callback()
    entry.pop(marker)
    save(state, OUT / 'checkpoint.json')
    return entry[key]


def upload(path):
    with path.open('rb') as stream:
        result = api('POST', '/assets', files={'file': (path.name, stream,
                     'image/jpeg' if path.suffix == '.jpg' else 'audio/wav')})
    return result['asset_id']


def prepare(config):
    OUT.mkdir(exist_ok=True)
    style = os.environ.get('PILOT_FORMAT', 'realiste')
    digest = hashlib.sha256(CONFIG.read_bytes() + (b'animation' if style == 'animation' else b'')).hexdigest()
    checkpoint = OUT / 'checkpoint.json'
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state['config_sha256'] != digest:
            raise ValueError('Le scénario a changé depuis la création du checkpoint.')
    else:
        if os.environ.get('GITHUB_RUN_ATTEMPT', '1') != '1':
            raise RuntimeError('Reprendre avec l’archive existante, sans nouvelle génération.')
        state = {'config_sha256': digest, 'assets': {}, 'scenes': [{} for _ in config['scenes']]}
        save(state, checkpoint)
    # Contrôle du catalogue avant tout appel payant. Aucune sélection automatique de remplacement.
    for name, char in config['characters'].items():
        matches = api('GET', '/models/audio/voices', params={
            'type': 'public', 'language': char['language'], 'gender': char['gender'], 'limit': 50})
        if not any(v['voice_id'] == char['voice_id'] and v.get('status') == 'ACTIVE' for v in matches):
            raise ValueError(f'La voix fixe de {name} n’est pas disponible dans le catalogue attendu.')
        once(state, state['assets'], name, lambda c=char: upload(ROOT / c['image']))
    for i, scene in enumerate(config['scenes']):
        entry = state['scenes'][i]
        char = config['characters'][scene['speaker']]
        entry.update(speaker=scene['speaker'], voice_id=char['voice_id'])
        speech = once(state, entry, 'speech', lambda s=scene, c=char: api('POST', '/models/audio/tts', json={
            'text': s['text'], 'voice_id': c['voice_id'], 'language': 'fr', 'model': 'heygen-voice-1'}))
        audio = OUT / f'{i:02d}.wav'
        if not audio.exists():
            download(speech['audio_url'], audio)
        entry['audio_duration'] = duration(audio)
        once(state, entry, 'audio_asset_id', lambda: upload(audio))
        result = once(state, entry, 'render', lambda: api('POST', '/videos', json={
            'type': 'image', 'image': {'type': 'asset_id', 'asset_id': state['assets'][scene['speaker']]},
            'audio_asset_id': entry['audio_asset_id'], 'title': f"{config['id']}-{i:02d}",
            'resolution': '1080p', 'aspect_ratio': '9:16', 'expressiveness': 'medium',
            'motion_prompt': 'Natural restrained conversation, subtle facial expressions and small head movements. '
                             'One person only. Keep identity, clothing, background and clear lighting unchanged. '
                             'No titles, overlays, labels, visual transitions, or white fade.'}))
        entry['video_id'] = result['video_id']
        save(state, checkpoint)
        print(f'Plan {i+1} : références de voix et animation disponibles pour {scene["speaker"]}.', flush=True)
    return state


def poll(state):
    deadline = time.monotonic() + 40 * 60
    while time.monotonic() < deadline:
        pending = False
        for i, entry in enumerate(state['scenes']):
            path = OUT / f'{i:02d}-raw.mp4'
            subtitles = OUT / f'{i:02d}.srt'
            if path.exists():
                continue
            result = api('GET', '/videos/' + entry['video_id'])
            if result['status'] == 'failed':
                raise RuntimeError(f'Animation du plan {i+1} échouée.')
            if result['status'] == 'completed':
                if not path.exists():
                    download(result['video_url'], path)
                if result.get('subtitle_url') and not subtitles.exists():
                    download(result['subtitle_url'], subtitles)
                if duration(path) + .15 < entry['audio_duration']:
                    raise ValueError(f'Animation trop courte au plan {i+1}.')
                print(f'Plan {i+1} récupéré.', flush=True)
            else:
                pending = True
        if not pending:
            return
        time.sleep(20)
    raise TimeoutError('Rendus encore en cours. Reprendre depuis l’archive privée.')


def subtitle_cues(words, offset, clip_duration):
    """Groupes courts horodatés par le moteur vocal, sans timing inventé."""
    if not words:
        raise ValueError('Horodatages de la voix absents : sous-titres à revoir.')
    result, group = [], []
    last_end = 0
    for word in words:
        start, end = float(word['start_time']), float(word['end_time'])
        if start < last_end - .05 or end < start or end > clip_duration + .1:
            raise ValueError('Horodatages vocaux incohérents.')
        last_end = end
        if group and (len(' '.join(w['text'] for w in group + [word])) > 62 or len(group) >= 9):
            result.append((offset + float(group[0]['start_time']), offset + float(group[-1]['end_time']),
                           ' '.join(w['text'] for w in group)))
            group = []
        group.append(word)
    if group:
        result.append((offset + float(group[0]['start_time']), offset + float(group[-1]['end_time']),
                       ' '.join(w['text'] for w in group)))
    return result


def normalized_tokens(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c))
    return re.findall(r'\w+', text)


def verify_transcript(expected, heard):
    ratio = SequenceMatcher(None, normalized_tokens(expected), normalized_tokens(heard)).ratio()
    if ratio < .88:
        raise ValueError(f'Dialogue transcrit différent du scénario ({ratio:.0%}). Revue nécessaire.')
    return ratio


def align_audio(config, state):
    model = None
    for i, entry in enumerate(state['scenes']):
        target = OUT / f'{i:02d}-alignment.json'
        if not target.exists():
            if model is None:
                from faster_whisper import WhisperModel
                model = WhisperModel('small', device='cpu', compute_type='int8')
            segments, info = model.transcribe(str(OUT / f'{i:02d}.wav'), language='fr',
                                              beam_size=5, word_timestamps=True, vad_filter=True)
            words = [{'text': word.word.strip(), 'start_time': word.start, 'end_time': word.end}
                     for segment in segments for word in segment.words]
            save(words, target)
        words = json.loads(target.read_text())
        entry['transcript_match'] = verify_transcript(config['scenes'][i]['text'], ' '.join(w['text'] for w in words))
        # On utilise les mots reconnus et leurs horaires, jamais une durée estimée.
        entry['aligned_words'] = words
        print(f'Plan {i+1} : transcription vérifiée ({entry["transcript_match"]:.0%}).', flush=True)
    save(state, OUT / 'checkpoint.json')


def ass_time(value):
    ticks = round(value * 100)
    return f'{ticks//360000}:{ticks//6000%60:02d}:{ticks//100%60:02d}.{ticks%100:02d}'


def srt_cues(path, offset, clip_duration, expected_text):
    def seconds(stamp):
        h, m, s = stamp.replace(',', '.').split(':')
        return int(h)*3600 + int(m)*60 + float(s)
    raw = path.read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    cues, last_end = [], 0
    for block in re.split(r'\n\s*\n', raw.strip()):
        lines = block.splitlines()
        timing = next((i for i,l in enumerate(lines) if '-->' in l), None)
        if timing is None:
            continue
        start_s, end_s = lines[timing].split('-->')
        start, end = seconds(start_s.strip()), seconds(end_s.strip().split()[0])
        text = re.sub(r'<[^>]+>', '', ' '.join(lines[timing+1:])).strip()
        if start < last_end - .05 or end <= start or end > clip_duration + .3 or len(text) > 105:
            raise ValueError('Sous-titres hors limites ou trop longs pour un plan.')
        cues.append((offset + start, offset + min(end, clip_duration), text))
        last_end = end
    if not cues:
        raise ValueError('La transcription du plan ne correspond pas suffisamment au dialogue prévu.')
    verify_transcript(expected_text, ' '.join(c[2] for c in cues))
    return cues


def segment_command(raw, audio, output, seconds):
    # L'audio de HeyGen est explicitement exclu. Pas de mixage ni de fondu entre les voix.
    return ['ffmpeg', '-v', 'error', '-y', '-i', str(raw), '-i', str(audio),
            '-map', '0:v:0', '-map', '1:a:0',
            '-vf', 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=25,tpad=stop_mode=clone:stop_duration=1',
            '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11,apad', '-t', str(seconds),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p',
            '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '1', str(output)]


def assemble(config, state):
    cues, offset, segments = [], 0, []
    for i, entry in enumerate(state['scenes']):
        # 240 ms de respiration ; la dernière image reste visible, sans dupliquer une voix.
        seconds = math.ceil((entry['audio_duration'] + .24) * 25) / 25
        segment = OUT / f'{i:02d}-segment.mkv'
        subprocess.run(segment_command(OUT / f'{i:02d}-raw.mp4', OUT / f'{i:02d}.wav', segment, seconds), check=True)
        segments.append(segment)
        if entry.get('aligned_words'):
            cues.extend(subtitle_cues(entry['aligned_words'], offset, entry['audio_duration']))
        elif entry['speech'].get('original_words'):
            cues.extend(subtitle_cues(entry['speech']['original_words'], offset, entry['audio_duration']))
        else:
            cues.extend(srt_cues(OUT / f'{i:02d}.srt', offset, entry['audio_duration'], config['scenes'][i]['text']))
        entry.update(timeline_start=offset, timeline_end=offset + seconds)
        offset += seconds
    if not 25 <= offset <= 60:
        raise ValueError(f'Durée finale à revoir : {offset:.2f} secondes.')
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,46,&H00FFFFFF,&H00FFFFFF,&H00181818,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,90,90,390,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = []
    for start, end, text in cues:
        text = text.replace('{', '').replace('}', '').replace('\\', '').replace('\n', ' ')
        events.append(f'Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{text}')
    (OUT / 'subtitles.ass').write_text(header + '\n'.join(events), encoding='utf-8')
    (OUT / 'concat.txt').write_text('\n'.join("file '" + p.name + "'" for p in segments))
    final = OUT / ('IA-au-bureau-' + os.environ.get('PILOT_FORMAT', 'realiste') + '-V2.mp4')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(OUT / 'concat.txt'),
                    '-vf', f"ass={OUT / 'subtitles.ass'}", '-map', '0:v:0', '-map', '0:a:0',
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '19', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(final)], check=True)
    report = probe(final)
    if len([s for s in report['streams'] if s['codec_type'] == 'audio']) != 1:
        raise ValueError('Il faut exactement une piste audio finale.')
    state['final'] = {'duration': duration(final), 'width': 1080, 'height': 1920,
                      'audio_tracks': 1, 'human_review_required': True, 'social_publication': False}
    save(state, OUT / 'checkpoint.json')
    save(config, OUT / 'scenario.json')
    for i, fraction in enumerate([.01, .15, .35, .6, .8, .96]):
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(offset * fraction), '-i', str(final),
                        '-frames:v', '1', '-vf', 'scale=270:480', str(OUT / f'review-{i}.jpg')], check=True)
    print(f'V2 privée terminée : {offset:.2f} s ; une piste audio, deux voix attribuées.', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['build', 'assemble', 'archive', 'restore'])
    args = parser.parse_args()
    if args.mode in {'archive', 'restore'}:
        return {'archive': archive_restart, 'restore': restore_restart}[args.mode]()
    config = load_config()
    state = prepare(config) if args.mode == 'build' else json.loads((OUT / 'checkpoint.json').read_text())
    if args.mode == 'build':
        poll(state)
    align_audio(config, state)
    assemble(config, state)


if __name__ == '__main__':
    main()
