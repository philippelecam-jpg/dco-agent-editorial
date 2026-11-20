"""Un pilote réaliste privé. Aucun appel de publication sociale."""
import os
import time
import ia_pilots as p


def submit():
    if p.CHECKPOINT.exists() or os.environ.get('GITHUB_RUN_ATTEMPT', '1') != '1':
        raise RuntimeError('Création déjà tentée : reprendre le checkpoint, jamais un nouveau POST.')
    p.heygen('GET', '/users/me')
    prompt = """Create ONE finished 38-second vertical 9:16 PHOTOREALISTIC live-action-style short.
French dialogue, French subtitles. Two entirely original synthetic fictional adult colleagues,
NOT real people or celebrities, NOT cartoon, NOT a stock presenter speaking alone.
Mina: woman about 40, auburn bob, amber round glasses, petrol-blue blazer, cream shirt.
Nino: man about 32, medium brown skin, short black curls, ochre sweater, navy trousers.
Maintain exact faces and clothing, realistic hands, natural expressions, plausible motion,
soft daylight in a contemporary small-business meeting room. Cinematic but everyday realism.
Four coherent moving scenes, alternating medium shots, close-ups and a final wide shot.
Two distinct natural French voices. Speak the following lines exactly, no additions.
1. Mina sets a thick folder on a table, Nino sits beside her.
Mina: J'ai dix pages de notes, mais qui fait quoi après cette réunion ?
Nino: Demandons à l'IA de préparer un tableau d'actions.
2. Nino types on a laptop, Mina points to the notes. No fabricated product interface.
Nino: Pour chaque action : un responsable, une échéance. Si la date manque, indique non précisée.
Mina: Et je vérifie avec mes notes.
3. Close-up of two simple physical cards: 'Devis : Nino, vendredi' and 'Fournisseur : Mina, date à fixer'.
Nino: Exactement. Une consigne ne garantit pas une réponse juste.
Mina: Le devis part vendredi. Pour le fournisseur, nous devons encore décider.
4. Mina closes the folder, both stand up, warm understated smile.
Nino: L'IA prépare, nous validons.
Mina: Enfin un compte rendu qui sert à agir !
Use synchronized accurate French subtitles throughout, maximum two lines, high contrast,
above the bottom 20%, leave faces clear. No overlapping duplicate captions.
Small persistent label 'Personnages fictifs · Création IA'. No brand logos, no fake product UI.
Keep dialogue audible, minimal original background ambience, no copyrighted music.
Target 35-42 seconds, natural pace, finish last line, half-second ending. Full-bleed portrait.
This is a PRIVATE review pilot. Generate realistic synthetic actors and multiscene action.
"""
    p.OUT.mkdir(exist_ok=True)
    (p.OUT / '04-realiste-prompt.txt').write_text(prompt)
    item = {'id': '04-realiste', 'title': 'L’IA prépare, nous validons', 'status': 'submitting'}
    state = {'started_at': int(time.time()), 'expected_episodes': 1, 'episodes': [item]}
    p.save(state)
    result = p.heygen('POST', '/video-agents', json={
        'prompt': prompt, 'orientation': 'portrait', 'mode': 'generate',
        'visibility': 'private', 'incognito_mode': True})
    item.update(session_id=result['session_id'], video_id=result.get('video_id'), status=result['status'])
    p.save(state)
    print('Pilote réaliste soumis ; checkpoint conservé.', flush=True)


if __name__ == '__main__':
    raise SystemExit("Génération V1 désactivée. Utiliser scripts/ia_controlled.py build.")
