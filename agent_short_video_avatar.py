#!/usr/bin/env python3
"""
agent_short_video_avatar.py
-----------------------------
Second module de dco-agent-editorial, complémentaire à agent_short_video.py.
Génère une vidéo courte avec Rachel (avatar animé sur photo de référence) qui
parle face caméra : script (Claude, angle grand public) -> voix (ElevenLabs,
Perle) -> vidéo avatar (API HeyGen v3) -> upload YouTube (Data API v3).

DIFFÉRENCES avec agent_short_video.py (format "fond statique") :
    - Public visé : grand public concerné/impacté par l'IA, PAS uniquement
      les dirigeants PME/ETI. Angle pédagogique et accessible.
    - Cadence : hebdomadaire, automatisée (cron), sans intervention manuelle.
    - Format natif 16:9, PAS de recadrage vertical — publiée comme vidéo
      courte classique, pas comme YouTube Short au sens strict (qui impose
      un format vertical). Choix assumé : pas de perte de cadrage liée à un
      crop automatique sur le visage.
    - Génération vidéo via l'API HeyGen (api.heygen.com), documentée
      publiquement — PAS via ElevenLabs Creative (cette dernière n'expose
      pas d'API REST publique pour ce cas d'usage, contrairement à ce qu'un
      prototype avait laissé penser à tort — endpoints corrigés ici).

POINT DE VIGILANCE — versions d'API HeyGen :
    La documentation HeyGen distingue plusieurs générations d'API (v1/v2
    "Legacy AI Studio" et v3 "New AI Studio"), avec des endpoints différents
    selon le plan de compte. Ce script utilise les endpoints v3, les plus
    récents et les mieux documentés au moment de l'écriture. AVANT
    D'ACTIVER LE CRON, fais un premier test manuel (workflow_dispatch) pour
    confirmer que ces endpoints répondent bien avec ton compte HeyGen -- si
    tu obtiens des 404, consulte https://docs.heygen.com pour vérifier quelle
    génération d'API ton plan expose, et ajuste HEYGEN_BASE_URL ci-dessous.

Dépendances Python :
    pip install requests feedparser

Variables d'environnement attendues (GitHub Actions secrets) :
    ANTHROPIC_API_KEY
    ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID (réutilise les mêmes que le
        module "fond statique" -- même identité vocale Rachel/Perle)
    HEYGEN_API_KEY : clé API d'un compte HeyGen (compte séparé d'ElevenLabs,
        à créer sur heygen.com -- Settings > API)
    RACHEL_TALKING_PHOTO_ID : l'ID de la photo de Rachel, uploadée une seule
        fois vers HeyGen (voir upload_rachel_photo_once() en bas de fichier)
    YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
        (réutilise les mêmes que le module "fond statique" -- même chaîne)

IMPORTANT -- étapes manuelles uniques, non automatisables :
    1. Créer un compte HeyGen, générer une clé API (Settings > API)
    2. Exécuter upload_rachel_photo_once() en local UNE FOIS pour obtenir
       RACHEL_TALKING_PHOTO_ID (voir fonction en bas de fichier)
    3. Premier test manuel via workflow_dispatch AVANT d'activer le cron,
       pour confirmer que les endpoints v3 fonctionnent avec ce compte
"""

import os
import json
import re
import time
from datetime import datetime
from pathlib import Path

import requests
import feedparser

RSS_FEEDS = [
    "https://www.actuia.com/feed/",
    "https://www.01net.com/actualites/feed/",
    "https://www.blogdumoderateur.com/feed/",
    "https://www.clubic.com/feed/news.rss",
]

HISTORY_FILE = Path("short_video_avatar_history.json")
WORKDIR = Path("tmp_short_video_avatar")
WORKDIR.mkdir(exist_ok=True)

HEYGEN_BASE_URL = "https://api.heygen.com/v3"

FALLBACK_THEMES = [
    "Ce que l'IA change déjà dans votre quotidien",
    "Une idée reçue sur l'intelligence artificielle, déconstruite",
    "Comment reconnaître un contenu généré par IA",
    "Ce que l'IA ne sait pas faire, et pourquoi ça compte",
    "Une question simple sur l'IA que tout le monde se pose",
]


def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {"themes_used": [], "news_used_links": [], "scripts": []}


def save_history(history):
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_candidate_news(history, max_items=15):
    import random
    seen_links = set(history.get("news_used_links", []))
    candidates = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception:
            continue
        for entry in feed.entries[:10]:
            link = entry.get("link", "")
            if not link or link in seen_links:
                continue
            candidates.append({
                "titre": entry.get("title", "").strip(),
                "resume": entry.get("summary", "").strip(),
                "lien": link,
                "source": feed.feed.get("title", url),
            })
    random.shuffle(candidates)
    return candidates[:max_items]


def select_best_news(candidates):
    if not candidates:
        return None
    api_key = os.environ["ANTHROPIC_API_KEY"]
    listing = "\n".join(
        "%d. %s -- %s" % (i + 1, c["titre"], c["resume"][:150]) for i, c in enumerate(candidates)
    )
    system_prompt = (
        "Tu sélectionnes, parmi une liste d'actualités IA/tech du jour, celle "
        "qui serait la plus intéressante à expliquer simplement à un public "
        "généraliste (pas des experts, pas uniquement des dirigeants) : de "
        "quoi susciter la curiosité, comprendre un enjeu qui les concerne "
        "directement, ou déconstruire une idée reçue. Réponds UNIQUEMENT avec "
        "le numéro de l'actu choisie, un entier seul, sans aucun texte autour."
    )
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 10,
            "system": system_prompt,
            "messages": [{"role": "user", "content": listing}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    raw = resp.json()["content"][0]["text"].strip()
    try:
        idx = int("".join(ch for ch in raw if ch.isdigit())) - 1
        return candidates[idx]
    except (ValueError, IndexError):
        return candidates[0]


def _clean_titre_et_texte(script_data):
    try:
        from agent import nettoyer_texte
        script_data["titre"] = nettoyer_texte(script_data["titre"])
        script_data["texte_voix"] = nettoyer_texte(script_data["texte_voix"])
    except Exception as e:
        print("[nettoyer_texte] Indisponible (%s) -- nettoyage minimal appliqué." % e)
        script_data["titre"] = re.sub(r"\s*[\u2014\u2013]\s*", ", ", script_data["titre"])
        script_data["texte_voix"] = re.sub(r"\s*[\u2014\u2013]\s*", ", ", script_data["texte_voix"])
    return script_data


def generate_script_from_news(news_item):
    api_key = os.environ["ANTHROPIC_API_KEY"]
    system_prompt = (
        "Tu écris le script d'une courte vidéo (30 à 45 secondes) pour "
        "Rachel, présentatrice de la chaîne. Elle s'adresse à un public "
        "généraliste concerné ou curieux de l'intelligence artificielle -- "
        "pas uniquement des dirigeants d'entreprise, pas des experts. Ton "
        "chaleureux, clair, pédagogique, jamais condescendant. Le texte doit "
        "être fait pour être LU À VOIX HAUTE, à la première personne (Rachel "
        "parle directement à la caméra) : phrases courtes, rythme naturel, "
        "pas de mise en forme.\n\n"
        "RÈGLE CENTRALE : explique l'actu simplement, avec un angle qui donne "
        "envie de comprendre, pas un jargon technique. Une image, une "
        "comparaison, ou une question qui parle à tout le monde.\n\n"
        "Actualité du jour : %s\n"
        "Résumé : %s\n\n"
        "Réponds UNIQUEMENT en JSON valide, sans texte autour, au format exact : "
        '{"titre": "...", "texte_voix": "...", "hashtags": ["...", "...", "..."]}'
        " où texte_voix fait entre 70 et 110 mots (30-45s à débit naturel, "
        "commence naturellement comme si Rachel parlait), titre fait moins "
        "de 60 caractères, et hashtags contient 3 à 5 tags sans le symbole #."
    ) % (news_item["titre"], news_item["resume"][:400])
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 500,
            "system": system_prompt,
            "messages": [{"role": "user", "content": "Génère le script du jour."}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    raw_text = resp.json()["content"][0]["text"].strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return _clean_titre_et_texte(json.loads(raw_text))


def generate_script_evergreen(theme):
    api_key = os.environ["ANTHROPIC_API_KEY"]
    system_prompt = (
        "Tu écris le script d'une courte vidéo (30 à 45 secondes) pour "
        "Rachel, présentatrice de la chaîne. Public généraliste concerné ou "
        "curieux de l'IA. Ton chaleureux, clair, pédagogique. Première "
        "personne, fait pour être lu à voix haute. Thème du jour : " + theme + ". "
        "Réponds UNIQUEMENT en JSON valide, sans texte autour, au format exact : "
        '{"titre": "...", "texte_voix": "...", "hashtags": ["...", "...", "..."]}'
        " où texte_voix fait entre 70 et 110 mots, titre fait moins de 60 "
        "caractères, et hashtags contient 3 à 5 tags sans le symbole #."
    )
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 500,
            "system": system_prompt,
            "messages": [{"role": "user", "content": "Génère le script du jour."}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    raw_text = resp.json()["content"][0]["text"].strip()
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return _clean_titre_et_texte(json.loads(raw_text))


def generate_voice(text, out_path):
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


def upload_audio_to_heygen(audio_path):
    """Upload l'audio ElevenLabs vers HeyGen et retourne son asset_id.
    Doc : POST /v3/assets (multipart/form-data)."""
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


def generate_avatar_video(talking_photo_id, audio_asset_id, titre):
    """Lance la génération HeyGen, attend sa fin, retourne l'URL de la vidéo.
    Doc : POST /v3/videos avec type='image' + audio_asset_id (mutuellement
    exclusif avec script+voice_id, puisqu'on fournit déjà l'audio ElevenLabs).
    aspect_ratio='16:9' : format natif, PAS de recadrage nécessaire ensuite."""
    api_key = os.environ["HEYGEN_API_KEY"]

    resp = requests.post(
        "%s/videos" % HEYGEN_BASE_URL,
        headers={"x-api-key": api_key, "content-type": "application/json"},
        json={
            "type": "image",
            "image": {"type": "talking_photo", "talking_photo_id": talking_photo_id},
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

    max_wait_seconds = 480
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


def download_video(url, out_path):
    resp = requests.get(url, timeout=180)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    return out_path


def get_access_token():
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


def upload_video(video_path, titre, description, tags):
    access_token = get_access_token()
    metadata = {
        "snippet": {"title": titre[:100], "description": description, "tags": tags, "categoryId": "22"},
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


def main():
    talking_photo_id = os.environ["RACHEL_TALKING_PHOTO_ID"]
    history = load_history()

    news_item = None
    try:
        candidates = fetch_candidate_news(history)
        news_item = select_best_news(candidates)
    except Exception as e:
        print("[1/6] Flux RSS indisponibles (%s) -- repli sur thème évergreen" % e)

    if news_item:
        print("[1/6] Actu retenue : %s (%s)" % (news_item["titre"], news_item["source"]))
        script_data = generate_script_from_news(news_item)
    else:
        import random
        recent = history.get("themes_used", [])[-3:]
        theme = random.choice([t for t in FALLBACK_THEMES if t not in recent] or FALLBACK_THEMES)
        print("[1/6] Aucune actu fraîche -- thème évergreen : %s" % theme)
        script_data = generate_script_evergreen(theme)
        history.setdefault("themes_used", []).append(theme)
        history["themes_used"] = history["themes_used"][-10:]

    print("[2/6] Script généré : %s" % script_data["titre"])

    audio_path = generate_voice(script_data["texte_voix"], WORKDIR / "voice.mp3")
    print("[3/6] Voix générée")

    audio_asset_id = upload_audio_to_heygen(audio_path)
    print("[4/6] Audio uploadé vers HeyGen (asset %s)" % audio_asset_id)

    print("[5/6] Génération de la vidéo avatar (peut prendre plusieurs minutes)...")
    video_url = generate_avatar_video(talking_photo_id, audio_asset_id, script_data["titre"])
    video_path = download_video(video_url, WORKDIR / "avatar.mp4")
    print("[5/6] Vidéo avatar générée (16:9 natif, aucun recadrage)")

    description = script_data["texte_voix"] + "\n\n" + " ".join(
        "#%s" % t for t in script_data["hashtags"]
    )
    video_id = upload_video(video_path, script_data["titre"], description, script_data["hashtags"])
    print("[6/6] Vidéo publiée : https://youtube.com/watch?v=%s" % video_id)

    if news_item:
        history.setdefault("news_used_links", []).append(news_item["lien"])
        history["news_used_links"] = history["news_used_links"][-100:]
    history.setdefault("scripts", []).append({
        "date": datetime.now().isoformat(),
        "source": "actualite" if news_item else "evergreen",
        "titre": script_data["titre"],
        "video_id": video_id,
    })
    save_history(history)


def upload_rachel_photo_once(photo_path="rachel.png"):
    """À exécuter UNE SEULE FOIS, en local, pour créer la 'talking photo'
    HeyGen à partir de la photo de référence de Rachel et obtenir son ID
    permanent. Doc : POST /v1/talking_photo (multipart/form-data, endpoint
    upload sur un sous-domaine différent : upload.heygen.com).

    Usage :
        python -c "from agent_short_video_avatar import upload_rachel_photo_once; upload_rachel_photo_once('rachel.png')"
    """
    api_key = os.environ["HEYGEN_API_KEY"]
    with open(photo_path, "rb") as f:
        resp = requests.post(
            "https://upload.heygen.com/v1/talking_photo",
            headers={"x-api-key": api_key, "Content-Type": "image/png"},
            data=f.read(),
            timeout=60,
        )
    resp.raise_for_status()
    talking_photo_id = resp.json()["data"]["talking_photo_id"]
    print("Talking Photo ID à copier dans le secret RACHEL_TALKING_PHOTO_ID :")
    print(talking_photo_id)


if __name__ == "__main__":
    main()
