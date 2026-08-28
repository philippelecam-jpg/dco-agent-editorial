#!/usr/bin/env python3
"""
agent_short_video_prospective.py
-----------------------------------
Troisième module de dco-agent-editorial, complémentaire à agent_short_video.py
(fond statique, quotidien) et agent_short_video_avatar.py (avatar Rachel,
grand public, hebdo mercredi). Génère une vidéo de prospective IA de 1min30 :
rotation de 6 grands thèmes -> génération de 3 angles contrastés -> sélection
anti-répétition -> script au registre "et si" (Gaston Berger) -> voix
(ElevenLabs) -> vidéo avatar (HeyGen) -> upload YouTube.

DIFFÉRENCES avec agent_short_video_avatar.py :
    - PAS de source RSS. Le contenu vient d'une rotation de 6 grands thèmes
      (Travail, Technologie, Économie, Social, Gouvernance et pouvoir,
      Éducation et transmission), un par semaine.
    - Pour chaque thème, Claude génère D'ABORD 3 angles distincts et
      contrastés, puis en sélectionne un en évitant ceux déjà traités
      récemment sur ce même thème (historique séparé par thème, pas juste
      une liste globale). C'est le levier anti-cliché : demander
      directement "un angle nouveau" donne souvent une reformulation du
      même angle -- forcer la divergence d'abord donne une vraie variété.
    - Registre éditorial : prospective imaginative ("et si..."), scène
      concrète et visualisable, PAS de résolution business proprette --
      une question ouverte en fin de script. Pas de synthèse de recherche,
      pas d'angle "impact dirigeant" explicite (le dirigeant se reconnaît
      de lui-même dans la scène).
    - Durée cible ~90s (vs 30-45s pour les 2 autres formats) : environ
      190-220 mots de texte voix.
    - Identité visuelle de la miniature différente : trajectoires qui
      divergent (symbolisant les futurs multiples), palette bleu-nuit/
      turquoise, expression posée -- pas le registre "punch actu"
      (drapeaux, chiffres, confrontation) des 2 autres formats.
    - Cadence : hebdomadaire, vendredi (vs mercredi pour l'avatar actu).

CE QUI EST RÉUTILISÉ TEL QUEL (déjà validé en production) :
    - Génération voix ElevenLabs (même voix Perle que les 2 autres formats)
    - Génération vidéo avatar via l'API HeyGen v3 (même photo de référence
      Rachel, même chaîne YouTube)
    - Upload YouTube (Data API v3, même chaîne)
    - Miniature en deux temps : scène visuelle par IA (OpenAI Images,
      SANS texte) + titre posé par-dessus en PIL auto-dimensionné
      (jamais tronqué) -- avec repli PIL pur en cas d'échec de l'IA

Dépendances Python :
    pip install requests pillow

Variables d'environnement attendues (GitHub Actions secrets) :
    ANTHROPIC_API_KEY
    OPENAI_API_KEY
    ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID (mêmes que les 2 autres formats)
    HEYGEN_API_KEY, RACHEL_PHOTO_ASSET_ID (mêmes que le format avatar)
    YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN (même chaîne)

⚠️ Comme pour les 2 autres modules HeyGen/OpenAI : non testé en conditions
réelles au moment de l'écriture (pas de clés API disponibles dans
l'environnement de développement). Premier run réel à valider avec
workflow_dispatch avant de faire confiance au cron.
"""

import os
import json
import re
import time
import base64
import io
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

HISTORY_FILE = Path("short_video_prospective_history.json")
WORKDIR = Path("tmp_short_video_prospective")
WORKDIR.mkdir(exist_ok=True)

HEYGEN_BASE_URL = "https://api.heygen.com/v3"
THUMB_W, THUMB_H = 1280, 720
RACHEL_PHOTO_PATH = "assets/Rachel.PNG"

# Rotation fixe sur 6 semaines. L'ordre est cyclique et déterministe
# (pas aléatoire) : chaque thème revient exactement toutes les 6 semaines,
# ce qui est le principe même d'une rotation -- contrairement aux 2 autres
# formats qui piochent dans un pool sans ordre fixe.
THEMES_ROTATION = [
    "Travail",
    "Technologie",
    "Économie",
    "Social",
    "Gouvernance et pouvoir",
    "Éducation et transmission",
]


# ---------------------------------------------------------------------------
# 1. Sélection du thème de la semaine (rotation cyclique déterministe)
# ---------------------------------------------------------------------------
def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {"last_theme_index": -1, "angles_par_theme": {}, "scripts": []}


def save_history(history):
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def pick_theme_of_week(history) -> str:
    """Rotation cyclique déterministe sur les 6 thèmes -- pas de hasard,
    pas de RSS. Le thème suivant est toujours celui d'après dans la liste,
    peu importe combien de temps s'est écoulé (robuste si un run est raté
    une semaine : on reprend simplement à l'index suivant)."""
    next_index = (history.get("last_theme_index", -1) + 1) % len(THEMES_ROTATION)
    history["last_theme_index"] = next_index
    return THEMES_ROTATION[next_index]


# ---------------------------------------------------------------------------
# 2. Génération de 3 angles contrastés + sélection anti-répétition
# ---------------------------------------------------------------------------
def _call_claude(system_prompt: str, user_message: str, max_tokens: int) -> str:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


def generate_three_angles(theme: str) -> list:
    """Fait proposer 3 angles distincts et contrastés sur le thème -- le
    détour obligatoire avant de choisir, qui évite la reformulation du même
    angle qu'on obtiendrait en demandant directement 'un angle nouveau'."""
    system_prompt = (
        "Tu es un consultant en prospective, dans la tradition de Gaston "
        "Berger : imaginer des futurs plausibles pour éclairer le présent, "
        "pas prédire ni rassurer. Pour le grand thème donné, propose "
        "exactement 3 angles de réflexion prospective distincts et "
        "contrastés (pas 3 variations du même angle) -- par exemple pour "
        "'Travail' : impact organisationnel / impact individuel et "
        "psychologique / impact systémique et économique. Chaque angle doit "
        "être formulé en une phrase courte, assez précise pour qu'on sache "
        "immédiatement de quoi il parle.\n\n"
        "Réponds UNIQUEMENT en JSON valide, sans texte autour, au format : "
        '["angle 1", "angle 2", "angle 3"]'
    )
    raw = _call_claude(system_prompt, "Grand thème : %s" % theme, max_tokens=400)
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


def select_angle(theme: str, angles: list, history: dict) -> str:
    """Sélectionne, parmi les 3 angles proposés, celui qui diverge le plus
    des angles déjà traités récemment sur ce même thème (historique propre
    à chaque thème, pas une liste globale -- la répétition qui compte est
    intra-thème, pas inter-thème)."""
    angles_deja_traites = history.get("angles_par_theme", {}).get(theme, [])

    if not angles_deja_traites:
        # Premier passage sur ce thème : aucun historique, on prend le
        # premier angle proposé sans arbitrage nécessaire.
        return angles[0]

    system_prompt = (
        "Voici 3 angles de réflexion prospective proposés sur un thème, et "
        "la liste des angles déjà traités récemment sur ce même thème. "
        "Choisis, parmi les 3 nouveaux angles, celui qui diverge le plus des "
        "angles déjà traités -- pour éviter de répéter la même idée sous "
        "une formulation différente. Réponds UNIQUEMENT avec le numéro de "
        "l'angle choisi (1, 2 ou 3), un entier seul, sans texte autour."
    )
    user_message = (
        "Angles déjà traités récemment sur ce thème :\n- %s\n\n"
        "Nouveaux angles proposés :\n1. %s\n2. %s\n3. %s"
    ) % (
        "\n- ".join(angles_deja_traites[-5:]),
        angles[0], angles[1], angles[2],
    )
    raw = _call_claude(system_prompt, user_message, max_tokens=10)
    try:
        idx = int("".join(ch for ch in raw if ch.isdigit())) - 1
        return angles[idx]
    except (ValueError, IndexError):
        return angles[0]


# ---------------------------------------------------------------------------
# 3. Génération du script (registre prospectif "et si")
# ---------------------------------------------------------------------------
def _clean_script(script_data: dict) -> dict:
    try:
        from agent import nettoyer_texte
        script_data["titre"] = nettoyer_texte(script_data["titre"])
        script_data["texte_voix"] = nettoyer_texte(script_data["texte_voix"])
    except Exception as e:
        print("[nettoyer_texte] Indisponible (%s) -- nettoyage minimal appliqué." % e)
        script_data["titre"] = re.sub(r"\s*[\u2014\u2013]\s*", ", ", script_data["titre"])
        script_data["texte_voix"] = re.sub(r"\s*[\u2014\u2013]\s*", ", ", script_data["texte_voix"])
    return script_data


def generate_script(theme: str, angle: str) -> dict:
    """Génère le script de ~90s dans le registre prospectif validé :
    ouverture en scène concrète et visualisable ('et si...'), bascule
    ('ce n'est pas de la fiction lointaine'), question ouverte en fin --
    PAS de résolution business proprette, PAS de mention explicite du
    dirigeant comme cible (il se reconnaît de lui-même)."""
    system_prompt = (
        "Tu écris le script d'une vidéo de prospective IA de 90 secondes "
        "pour Rachel, présentatrice de la chaîne. Le public est constitué "
        "de dirigeants de PME/ETI, mais NE LES NOMME JAMAIS explicitement "
        "comme cible -- ils doivent se reconnaître d'eux-mêmes dans la "
        "scène décrite, sans qu'on leur dise 'pour vous, dirigeant'.\n\n"
        "REGISTRE -- prospective au sens de Gaston Berger, pas pronostic "
        "business : le but est de provoquer l'imaginaire, l'étonnement, "
        "pas de rassurer avec une conclusion actionnable propre. C'est un "
        "'et si...', pas un plan d'action.\n\n"
        "STRUCTURE OBLIGATOIRE :\n"
        "1. Ouverture en scène concrète et visualisable, commençant "
        "idéalement par 'Et si...' -- quelque chose qu'on peut se "
        "représenter mentalement, pas un constat abstrait.\n"
        "2. Une bascule qui ancre cette scène dans le réel : 'Ce n'est pas "
        "de la science-fiction lointaine, les briques existent déjà "
        "aujourd'hui' (ou formulation équivalente).\n"
        "3. Une ou deux phrases qui approfondissent la scène ou en "
        "explorent une conséquence inattendue.\n"
        "4. Termine SUR UNE QUESTION OUVERTE, pas sur une réponse ni un "
        "conseil pratique. La question doit rester avec la personne après "
        "la vidéo, pas se résoudre proprement.\n\n"
        "Ton chaleureux mais habité, presque conteur. Phrases courtes, "
        "rythme naturel à l'oral, fait pour être lu à voix haute par "
        "Rachel à la première personne. Environ 190 à 220 mots.\n\n"
        "Réponds UNIQUEMENT en JSON valide, sans texte autour, au format "
        'exact : {"titre": "...", "texte_voix": "..."} où titre fait moins '
        "de 60 caractères et donne envie de cliquer sans tout dévoiler."
    )
    user_message = "Grand thème : %s\nAngle retenu : %s" % (theme, angle)
    raw = _call_claude(system_prompt, user_message, max_tokens=700)
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return _clean_script(json.loads(raw))


# ---------------------------------------------------------------------------
# 4. Voix (ElevenLabs) -- identique aux 2 autres formats
# ---------------------------------------------------------------------------
def generate_voice(text: str, out_path: Path) -> Path:
    api_key = os.environ["ELEVENLABS_API_KEY"]
    voice_id = os.environ["ELEVENLABS_VOICE_ID"]
    resp = requests.post(
        "https://api.elevenlabs.io/v1/text-to-speech/%s" % voice_id,
        headers={"xi-api-key": api_key, "content-type": "application/json"},
        json={
            "text": text,
            "model_id": "eleven_flash_v2_5",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=60,
    )
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    return out_path


# ---------------------------------------------------------------------------
# 5. Génération vidéo avatar -- API HeyGen v3 (identique au format avatar)
# ---------------------------------------------------------------------------
def upload_audio_to_heygen(audio_path: Path) -> str:
    api_key = os.environ["HEYGEN_API_KEY"]
    with open(audio_path, "rb") as f:
        resp = requests.post(
            "%s/assets" % HEYGEN_BASE_URL,
            headers={"x-api-key": api_key},
            files={"file": ("voice.mp3", f, "audio/mpeg")},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json()["data"]["asset_id"]


def generate_avatar_video(photo_asset_id: str, audio_asset_id: str, titre: str) -> str:
    api_key = os.environ["HEYGEN_API_KEY"]
    resp = requests.post(
        "%s/videos" % HEYGEN_BASE_URL,
        headers={"x-api-key": api_key, "content-type": "application/json"},
        json={
            "type": "image",
            "image": {"type": "asset_id", "asset_id": photo_asset_id},
            "audio_asset_id": audio_asset_id,
            "title": titre[:100],
            "resolution": "1080p",
            "aspect_ratio": "16:9",
        },
        timeout=30,
    )
    if resp.status_code >= 400:
        print("[generate_avatar_video] Erreur HTTP %s -- corps de la réponse :" % resp.status_code)
        print(resp.text[:2000])
    resp.raise_for_status()
    video_id = resp.json()["data"]["video_id"]

    max_wait_seconds = 600  # un peu plus long que les 2 autres formats : la
    # vidéo dure ~90s au lieu de 30-45s, le rendu HeyGen peut prendre plus de temps
    waited = 0
    poll_interval = 15
    while waited < max_wait_seconds:
        status_resp = requests.get(
            "%s/videos/%s" % (HEYGEN_BASE_URL, video_id),
            headers={"x-api-key": api_key},
            timeout=30,
        )
        status_resp.raise_for_status()
        data = status_resp.json()["data"]
        status = data.get("status")
        if status == "completed":
            return data["video_url"]
        if status == "failed":
            raise RuntimeError("Génération HeyGen échouée : %s" % data.get("error", "raison inconnue"))
        time.sleep(poll_interval)
        waited += poll_interval

    raise TimeoutError("Génération HeyGen toujours en cours après %ds." % max_wait_seconds)


def download_video(url: str, out_path: Path) -> Path:
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    return out_path


# ---------------------------------------------------------------------------
# 6. Miniature -- même mécanisme à deux temps que le format avatar, mais
#    identité visuelle "prospective" (trajectoires divergentes) et non
#    "actu" (drapeaux/icônes contextuelles)
# ---------------------------------------------------------------------------
def _wrap_text(draw, text: str, font, max_width: int) -> list:
    words = text.split()
    lines, current = [], []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] > max_width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _fit_title(draw, titre: str, font_path: str, max_width: int, max_height: int,
                start_size=130, min_size=36):
    titre_ajuste = re.sub(r"\s+([?!;:])", r"\1", titre)
    size = start_size
    while size >= min_size:
        try:
            font = ImageFont.truetype(font_path, size)
        except Exception:
            font = ImageFont.load_default()
            return font, [titre_ajuste.upper()]
        lines = _wrap_text(draw, titre_ajuste.upper(), font, max_width)
        line_height = int(size * 1.15)
        if len(lines) * line_height <= max_height:
            return font, lines
        size -= 4
    font = ImageFont.truetype(font_path, min_size) if size >= min_size else ImageFont.load_default()
    return font, _wrap_text(draw, titre_ajuste.upper(), font, max_width)


def _draw_title_and_badge(canvas, titre: str, left_w: int):
    """Identique au mécanisme du format avatar -- même garantie de
    fiabilité (jamais tronqué), badge 'IA' repris pour l'identité de marque
    partagée entre les 3 formats du dispositif."""
    draw = ImageDraw.Draw(canvas, "RGBA")
    FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    margin = 56
    text_max_width = left_w - 2 * margin
    text_max_height = THUMB_H - 270

    font_title, lines = _fit_title(draw, titre, FONT_PATH, text_max_width, text_max_height)
    line_height = int(font_title.size * 1.15)
    y = (THUMB_H - len(lines) * line_height) // 2 - 30
    for line in lines:
        draw.text((margin + 3, y + 3), line, font=font_title, fill=(0, 0, 0, 200))
        draw.text((margin, y), line, font=font_title, fill=(255, 255, 255, 255))
        y += line_height

    badge_cx, badge_cy, badge_r = margin + 34, THUMB_H - 70, 34
    for glow_r in range(badge_r + 14, badge_r, -2):
        alpha = int(60 * (glow_r - badge_r) / 14)
        draw.ellipse(
            [(badge_cx - glow_r, badge_cy - glow_r), (badge_cx + glow_r, badge_cy + glow_r)],
            outline=(0, 168, 168, alpha), width=2,
        )
    draw.ellipse(
        [(badge_cx - badge_r, badge_cy - badge_r), (badge_cx + badge_r, badge_cy + badge_r)],
        outline=(0, 168, 168, 255), width=3,
    )
    try:
        font_badge = ImageFont.truetype(FONT_PATH, 26)
    except Exception:
        font_badge = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "IA", font=font_badge)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((badge_cx - bw / 2, badge_cy - bh / 2 - bbox[1]), "IA",
               font=font_badge, fill=(0, 168, 168, 255))
    return canvas


def generate_thumbnail_ai(titre: str, out_path: Path) -> Path:
    """Scène générée par IA (SANS texte) avec le motif visuel prospectif
    validé -- trajectoires qui divergent, palette bleu-nuit/turquoise,
    expression posée -- puis titre posé par-dessus en PIL garanti."""
    api_key = os.environ["OPENAI_API_KEY"]

    prompt = (
        "Créer un arrière-plan de vignette premium au format paysage 16:9, "
        "dans un registre analytique et prospectif -- sobre, feutré, "
        "réflexion stratégique. PAS de drapeaux, PAS de score, PAS de "
        "confrontation, PAS d'icônes d'actualité.\n\n"
        "IMPORTANT -- NE JAMAIS ÉCRIRE DE TEXTE, TITRE, LETTRE, MOT OU "
        "CHIFFRE NULLE PART DANS L'IMAGE.\n\n"
        "Utiliser la photo de la personne fournie comme référence fidèle : "
        "conserver son visage, sa coiffure, mais avec une expression posée "
        "et réfléchie plutôt qu'un sourire éclatant. La placer sur la "
        "partie droite de l'image (environ 40%), cadrage buste, entièrement "
        "visible.\n\n"
        "Sur la partie gauche (environ 60%), fond bleu-nuit profond avec un "
        "motif de lignes fines qui se ramifient et divergent progressivement "
        "depuis un point commun vers plusieurs directions -- symbolisant "
        "plusieurs futurs possibles. Lumière cinématographique douce, "
        "dégradés subtils, quelques particules lumineuses discrètes le long "
        "des trajectoires. Cette zone doit rester dégagée au centre pour "
        "l'ajout ultérieur d'un texte.\n\n"
        "Palette : bleu-nuit profond, touches turquoise/cyan discrètes, "
        "aucune couleur vive ou saturée. Style épuré, premium, crédible."
    )

    with open(RACHEL_PHOTO_PATH, "rb") as photo_file:
        resp = requests.post(
            "https://api.openai.com/v1/images/edits",
            headers={"Authorization": "Bearer %s" % api_key},
            files={"image": ("rachel.png", photo_file, "image/png")},
            data={"model": "gpt-image-1", "prompt": prompt, "size": "1536x1024",
                  "quality": "high", "n": 1},
            timeout=120,
        )
    if resp.status_code >= 400:
        print("[generate_thumbnail_ai] Erreur HTTP %s -- corps de la réponse :" % resp.status_code)
        print(resp.text[:2000])
    resp.raise_for_status()

    b64_data = resp.json()["data"][0]["b64_json"]
    img = Image.open(io.BytesIO(base64.b64decode(b64_data))).convert("RGB")
    target_ratio = THUMB_W / THUMB_H
    src_ratio = img.width / img.height
    if src_ratio > target_ratio:
        new_width = int(img.height * target_ratio)
        left = (img.width - new_width) // 2
        img = img.crop((left, 0, left + new_width, img.height))
    else:
        new_height = int(img.width / target_ratio)
        top = (img.height - new_height) // 2
        img = img.crop((0, top, img.width, top + new_height))
    canvas = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)

    LEFT_W = int(THUMB_W * 0.58)
    _draw_title_and_badge(canvas, titre, LEFT_W)
    canvas.save(out_path, "JPEG", quality=92)
    return out_path


def generate_thumbnail_fallback(titre: str, out_path: Path) -> Path:
    """Repli 100% PIL, mêmes garanties que les 2 autres formats -- utilisé
    si la génération IA échoue (quota, contenu refusé, erreur réseau)."""
    LEFT_W = int(THUMB_W * 0.58)
    RIGHT_W = THUMB_W - LEFT_W

    canvas = Image.new("RGB", (THUMB_W, THUMB_H), (13, 20, 33))
    draw = ImageDraw.Draw(canvas, "RGBA")
    for x in range(LEFT_W):
        t = x / LEFT_W
        shade = int(13 + 10 * (1 - abs(t - 0.5) * 2))
        draw.line([(x, 0), (x, THUMB_H)], fill=(shade, shade + 6, shade + 20))

    glow_cx, glow_cy = int(LEFT_W * 0.5), int(THUMB_H * 0.42)
    for r in range(280, 0, -20):
        alpha = int(18 * (1 - r / 280))
        draw.ellipse([(glow_cx - r, glow_cy - r), (glow_cx + r, glow_cy + r)],
                     fill=(0, 168, 168, alpha))

    photo = Image.open(RACHEL_PHOTO_PATH).convert("RGB")
    src_ratio = photo.width / photo.height
    target_ratio = RIGHT_W / THUMB_H
    if src_ratio > target_ratio:
        new_width = int(photo.height * target_ratio)
        left = (photo.width - new_width) // 2
        photo = photo.crop((left, 0, left + new_width, photo.height))
    else:
        new_height = int(photo.width / target_ratio)
        top = (photo.height - new_height) // 2
        photo = photo.crop((0, top, photo.width, top + new_height))
    photo = photo.resize((RIGHT_W, THUMB_H), Image.LANCZOS)
    canvas.paste(photo, (LEFT_W, 0))

    _draw_title_and_badge(canvas, titre, LEFT_W)
    canvas.save(out_path, "JPEG", quality=92)
    return out_path


# ---------------------------------------------------------------------------
# 7. Upload YouTube -- identique aux 2 autres formats, même chaîne
# ---------------------------------------------------------------------------
def get_access_token() -> str:
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": os.environ["YOUTUBE_CLIENT_ID"],
            "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
            "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def upload_video(video_path: Path, titre: str, description: str) -> str:
    access_token = get_access_token()
    metadata = {
        "snippet": {"title": titre[:100], "description": description,
                    "tags": ["prospectiveIA", "IA", "futur", "DecisionsAndCo"],
                    "categoryId": "22"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    init_resp = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization": "Bearer %s" % access_token,
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
        },
        json=metadata,
        timeout=30,
    )
    init_resp.raise_for_status()
    upload_url = init_resp.headers["Location"]
    with open(video_path, "rb") as f:
        video_data = f.read()
    upload_resp = requests.put(
        upload_url, headers={"Content-Type": "video/mp4"}, data=video_data, timeout=300
    )
    upload_resp.raise_for_status()
    return upload_resp.json()["id"]


def upload_thumbnail(video_id: str, thumbnail_path: Path):
    access_token = get_access_token()
    with open(thumbnail_path, "rb") as f:
        resp = requests.post(
            "https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId=%s" % video_id,
            headers={"Authorization": "Bearer %s" % access_token, "Content-Type": "image/jpeg"},
            data=f.read(),
            timeout=60,
        )
    if resp.status_code >= 400:
        print("[upload_thumbnail] Miniature refusée (%s)." % resp.status_code)
        return False
    print("[upload_thumbnail] Miniature appliquée.")
    return True


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def main():
    history = load_history()

    theme = pick_theme_of_week(history)
    print("[1/7] Thème de la semaine : %s" % theme)

    angles = generate_three_angles(theme)
    print("[2/7] 3 angles proposés : %s" % " | ".join(angles))

    angle_retenu = select_angle(theme, angles, history)
    print("[3/7] Angle retenu : %s" % angle_retenu)

    script_data = generate_script(theme, angle_retenu)
    print("[4/7] Script généré : %s" % script_data["titre"])

    audio_path = generate_voice(script_data["texte_voix"], WORKDIR / "voice.mp3")
    audio_asset_id = upload_audio_to_heygen(audio_path)
    print("[5/7] Voix générée et uploadée (asset %s)" % audio_asset_id)

    photo_asset_id = os.environ["RACHEL_PHOTO_ASSET_ID"]
    print("[6/7] Génération de la vidéo avatar (peut prendre plusieurs minutes)...")
    video_url = generate_avatar_video(photo_asset_id, audio_asset_id, script_data["titre"])
    video_path = download_video(video_url, WORKDIR / "prospective.mp4")
    print("[6/7] Vidéo avatar générée")

    description = (
        script_data["texte_voix"]
        + "\n\n#ProspectiveIA #IntelligenceArtificielle #Futur #DecisionsAndCo"
    )
    video_id = upload_video(video_path, script_data["titre"], description)
    print("[7/7] Vidéo publiée : https://youtube.com/watch?v=%s" % video_id)

    thumb_path = WORKDIR / "thumbnail.jpg"
    try:
        generate_thumbnail_ai(script_data["titre"], thumb_path)
        print("[thumbnail] Générée via IA.")
    except Exception as e:
        print("[thumbnail] IA indisponible (%s) -- repli PIL." % e)
        try:
            generate_thumbnail_fallback(script_data["titre"], thumb_path)
        except Exception as e2:
            print("[thumbnail] Non appliquée (%s)." % e2)
            thumb_path = None
    if thumb_path:
        try:
            upload_thumbnail(video_id, thumb_path)
        except Exception as e:
            print("[thumbnail] Upload échoué (%s)." % e)

    history.setdefault("angles_par_theme", {}).setdefault(theme, []).append(angle_retenu)
    history["angles_par_theme"][theme] = history["angles_par_theme"][theme][-10:]
    history.setdefault("scripts", []).append({
        "date": datetime.now().isoformat(),
        "theme": theme,
        "angle": angle_retenu,
        "titre": script_data["titre"],
        "video_id": video_id,
    })
    save_history(history)


if __name__ == "__main__":
    main()
