#!/usr/bin/env python3
"""
agent_short_video.py
---------------------
Module complémentaire de dco-agent-editorial.
Génère un YouTube Short quotidien : script court (Claude) -> voix (ElevenLabs)
-> vidéo verticale statique brandée (ffmpeg) -> upload YouTube (Data API v3).

V1 volontairement simple : pas de sous-titres synchronisés mot-par-mot,
juste titre + hashtags affichés en incrustation fixe pendant toute la vidéo.
On complexifiera (captions timées) seulement si le format prouve sa valeur.

Dépendances Python :
    pip install requests anthropic google-auth google-auth-oauthlib google-api-python-client pillow

Dépendance système : ffmpeg (à installer dans le workflow GitHub Actions)

Variables d'environnement attendues (GitHub Actions secrets) :
    ANTHROPIC_API_KEY
    ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
    YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN

IMPORTANT — étape manuelle unique et non automatisable :
    Le refresh token YouTube (YOUTUBE_REFRESH_TOKEN) doit être généré une seule
    fois via un flux OAuth2 avec consentement humain (impossible à scripter
    sans navigateur). Voir la fonction get_refresh_token_once() en bas de
    fichier : à exécuter en local, une seule fois, pour obtenir le token à
    coller dans les secrets GitHub.

Intégration avec agent.py :
    Ce script tente d'importer get_palette() et recolor_logo() depuis agent.py
    (déjà présent dans le repo) pour rester visuellement cohérent avec les
    posts quotidiens et l'article hebdo. Si l'import échoue (agent.py absent
    ou fonctions renommées), un fallback local prend le relais — la vidéo sera
    générée quand même, juste avec une palette par défaut.
"""

import os
import json
import base64
import random
import subprocess
import textwrap
from datetime import datetime
from pathlib import Path

import requests
import feedparser
from PIL import Image, ImageDraw, ImageFont

# Flux RSS IA/tech/business FR — mêmes sources que agent_news_flash.py,
# pour garder une seule liste de confiance à travers tout le dispositif.
RSS_FEEDS = [
    "https://www.actuia.com/feed/",
    "https://www.01net.com/actualites/feed/",
    "https://www.blogdumoderateur.com/feed/",
    "https://www.clubic.com/feed/news.rss",
]

# ---------------------------------------------------------------------------
# Intégration branding (best effort avec agent.py existant)
# ---------------------------------------------------------------------------
try:
    from agent import get_palette, recolor_logo  # réutilise le module existant
    HAS_BRANDING_MODULE = True
except Exception:
    # Volontairement large : agent.py exécute du code au moment de l'import
    # (lecture de secrets X/Twitter notamment), donc toute erreur ici — pas
    # seulement ImportError — doit basculer sur le fallback plutôt que de
    # faire échouer tout le pipeline pour un problème de branding visuel.
    HAS_BRANDING_MODULE = False

    def get_palette():
        # Fallback si agent.py n'est pas importable dans ce contexte
        return {
            "bg": (13, 20, 33),
            "accent": (0, 168, 168),
            "text": (255, 255, 255),
            "subtext": (170, 185, 200),
        }

    def recolor_logo(logo_path, color):
        return None  # pas de logo si le module de branding n'est pas dispo


HISTORY_FILE = Path("short_video_history.json")
WORKDIR = Path("tmp_short_video")
WORKDIR.mkdir(exist_ok=True)

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920

# Fallback évergreen — utilisé uniquement si tous les flux RSS échouent
# ou si aucune actu fraîche n'est disponible (rare, mais on ne bloque jamais
# la publication pour ça).
FALLBACK_THEMES = [
    "L'Entreprise OS : l'organisation pilotée par l'IA",
    "Méthode Cartographier -> Éliciter -> Codifier",
    "Gouvernance IA en PME/ETI",
    "Retours de terrain : missions clients D&Co",
    "Culture IA et formation des équipes",
]


# ---------------------------------------------------------------------------
# 1. Sélection de l'actualité du jour (RSS) + génération du script (Claude)
# ---------------------------------------------------------------------------
def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {"themes_used": [], "news_used_links": [], "scripts": []}


def save_history(history):
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_candidate_news(history, max_items=15) -> list:
    """Récupère les entrées récentes des flux RSS IA/tech, en excluant
    celles déjà utilisées (par lien, sur l'historique complet)."""
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


def pick_theme(history):
    """Conservé pour compatibilité — sert uniquement au fallback évergreen."""
    recent = history.get("themes_used", [])[-3:]
    candidates = [t for t in FALLBACK_THEMES if t not in recent] or FALLBACK_THEMES
    return random.choice(candidates)


def select_best_news(candidates: list) -> dict:
    """Demande à Claude de choisir, parmi les candidats, l'actu avec le plus
    d'impact stratégique pour un dirigeant de PME/ETI. Retourne l'item choisi
    (dict) ou None si la liste est vide."""
    if not candidates:
        return None

    api_key = os.environ["ANTHROPIC_API_KEY"]
    listing = "\n".join(
        f"{i+1}. {c['titre']} — {c['resume'][:150]}" for i, c in enumerate(candidates)
    )
    system_prompt = (
        "Tu sélectionnes, parmi une liste d'actualités IA/tech du jour, celle "
        "qui a le plus d'impact stratégique concret pour un dirigeant de "
        "PME/ETI français. Réponds UNIQUEMENT avec le numéro de l'actu choisie, "
        "un entier seul, sans aucun texte autour."
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
        return candidates[0]  # fallback simple si le parsing échoue


def generate_script_from_news(news_item: dict) -> dict:
    """Retourne {"titre": str, "texte_voix": str, "hashtags": [str, ...]}
    à partir d'une actu réelle, avec l'angle différenciant validé sur le
    module News Flash : jamais un résumé du fait, toujours son implication
    concrète pour un dirigeant de PME/ETI."""
    api_key = os.environ["ANTHROPIC_API_KEY"]
    system_prompt = (
        "Tu écris le script d'un YouTube Short de 30 à 45 secondes pour "
        "Décisions & Co (D&Co), cabinet de conseil en transformation IA pour "
        "PME/ETI. Ton direct, incarné, orienté dirigeant — jamais promotionnel, "
        "jamais jargon creux. Le texte doit être fait pour être LU À VOIX HAUTE : "
        "phrases courtes, rythme naturel, pas de mise en forme.\n\n"
        "RÈGLE CENTRALE : ne résume PAS l'actualité fournie. Prends position sur "
        "ce qu'elle CHANGE concrètement pour un dirigeant de PME/ETI — une "
        "décision à reconsidérer, un risque à anticiper, une opportunité à "
        "saisir. L'actu est un point de départ, pas le sujet du short.\n\n"
        f"Actualité du jour : {news_item['titre']}\n"
        f"Résumé : {news_item['resume'][:400]}\n\n"
        "Réponds UNIQUEMENT en JSON valide, sans texte autour, au format exact : "
        '{"titre": "...", "texte_voix": "...", "hashtags": ["...", "...", "..."]}'
        " où texte_voix fait entre 70 et 110 mots (30-45s à débit naturel), "
        "titre fait moins de 60 caractères, et hashtags contient 3 à 5 tags "
        "pertinents sans le symbole #."
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
    return json.loads(raw_text)


def generate_script(theme: str) -> dict:
    """Fallback évergreen — conservé si aucune actu fraîche n'est disponible."""
    api_key = os.environ["ANTHROPIC_API_KEY"]
    system_prompt = (
        "Tu écris le script d'un YouTube Short de 30 à 45 secondes pour "
        "Décisions & Co (D&Co), cabinet de conseil en transformation IA pour "
        "PME/ETI. Ton direct, incarné, orienté dirigeant — jamais promotionnel, "
        "jamais jargon creux. Le texte doit être fait pour être LU À VOIX HAUTE : "
        "phrases courtes, rythme naturel, pas de mise en forme. "
        "Thème du jour : " + theme + ". "
        "Réponds UNIQUEMENT en JSON valide, sans texte autour, au format exact : "
        '{"titre": "...", "texte_voix": "...", "hashtags": ["...", "...", "..."]}'
        " où texte_voix fait entre 70 et 110 mots (30-45s à débit naturel), "
        "titre fait moins de 60 caractères, et hashtags contient 3 à 5 tags "
        "pertinents sans le symbole #."
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
    return json.loads(raw_text)


# ---------------------------------------------------------------------------
# 2. Voix (ElevenLabs)
# ---------------------------------------------------------------------------
def generate_voice(text: str, out_path: Path) -> Path:
    api_key = os.environ["ELEVENLABS_API_KEY"]
    voice_id = os.environ["ELEVENLABS_VOICE_ID"]

    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": api_key, "content-type": "application/json"},
        json={
            "text": text,
            "model_id": "eleven_flash_v2_5",  # requis pour le français
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=60,
    )
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    return out_path


def get_audio_duration(audio_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


# ---------------------------------------------------------------------------
# 3. Fond visuel brandé statique (PIL)
# ---------------------------------------------------------------------------
def build_background_image(titre: str, hashtags: list, out_path: Path) -> Path:
    palette = get_palette()
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), palette["bg"])
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 72)
        font_tags = ImageFont.truetype("DejaVuSans.ttf", 40)
    except OSError:
        font_title = ImageFont.load_default()
        font_tags = ImageFont.load_default()

    # Bande d'accent en haut
    draw.rectangle([(0, 0), (VIDEO_WIDTH, 16)], fill=palette["accent"])

    # Titre centré, wrap automatique
    wrapped = textwrap.wrap(titre, width=22)
    y = VIDEO_HEIGHT // 2 - (len(wrapped) * 90) // 2
    for line in wrapped:
        bbox = draw.textbbox((0, 0), line, font=font_title)
        w = bbox[2] - bbox[0]
        draw.text(((VIDEO_WIDTH - w) / 2, y), line, font=font_title, fill=palette["text"])
        y += 90

    # Hashtags en bas, avec retour à la ligne automatique (évite le
    # dépassement hors cadre observé en V1 sur les listes de 4-5 tags).
    MARGIN = 60
    max_line_width = VIDEO_WIDTH - 2 * MARGIN

    def text_width(s, font):
        bbox = draw.textbbox((0, 0), s, font=font)
        return bbox[2] - bbox[0]

    tags_with_hash = [f"#{t}" for t in hashtags]
    tag_lines = []
    current_line = ""
    for tag in tags_with_hash:
        candidate = f"{current_line}  {tag}".strip()
        if text_width(candidate, font_tags) <= max_line_width:
            current_line = candidate
        else:
            if current_line:
                tag_lines.append(current_line)
            current_line = tag
    if current_line:
        tag_lines.append(current_line)

    y_tags = VIDEO_HEIGHT - 60 - (len(tag_lines) * 55)
    for line in tag_lines:
        w = text_width(line, font_tags)
        draw.text(((VIDEO_WIDTH - w) / 2, y_tags), line, font=font_tags, fill=palette["subtext"])
        y_tags += 55

    # Logo si le module de branding est disponible — on journalise
    # explicitement les deux cas d'échec possibles plutôt que de les avaler
    # silencieusement, pour pouvoir diagnostiquer depuis les logs GitHub
    # Actions sans avoir à reproduire le run en local.
    if HAS_BRANDING_MODULE:
        try:
            logo = recolor_logo("assets/logo.png", palette["text"])
            if logo:
                logo.thumbnail((260, 260))
                img.paste(logo, (VIDEO_WIDTH // 2 - logo.width // 2, 120), logo)
            else:
                print("[build_background_image] recolor_logo() a retourné None — "
                      "vérifier le chemin assets/logo.png dans le repo.")
        except Exception as e:
            print(f"[build_background_image] Logo non appliqué : {e}")
    else:
        print("[build_background_image] HAS_BRANDING_MODULE=False — "
              "l'import de agent.py a échoué ou get_palette/recolor_logo "
              "sont absents. Pas de logo sur ce run.")

    img.save(out_path)
    return out_path


# ---------------------------------------------------------------------------
# 4. Assemblage vidéo (ffmpeg)
# ---------------------------------------------------------------------------
def build_video(image_path: Path, audio_path: Path, duration: float, out_path: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(image_path),
            "-i", str(audio_path),
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-t", str(duration + 0.5),
            "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}",
            str(out_path),
        ],
        check=True,
    )
    return out_path


# ---------------------------------------------------------------------------
# 5. Upload YouTube (Data API v3, upload resumable simplifié)
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


def upload_short(video_path: Path, titre: str, description: str, tags: list) -> str:
    access_token = get_access_token()

    metadata = {
        "snippet": {
            "title": titre[:100],
            "description": description,
            "tags": tags,
            "categoryId": "22",  # People & Blogs
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }

    init_resp = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization": f"Bearer {access_token}",
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
        upload_url,
        headers={"Content-Type": "video/mp4"},
        data=video_data,
        timeout=300,
    )
    upload_resp.raise_for_status()
    return upload_resp.json()["id"]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def main():
    history = load_history()

    news_item = None
    try:
        candidates = fetch_candidate_news(history)
        news_item = select_best_news(candidates)
    except Exception as e:
        print(f"[1/5] Flux RSS indisponibles ({e}) — repli sur thème évergreen")

    if news_item:
        print(f"[1/5] Actu retenue : {news_item['titre']} ({news_item['source']})")
        script_data = generate_script_from_news(news_item)
    else:
        theme = pick_theme(history)
        print(f"[1/5] Aucune actu fraîche — thème évergreen retenu : {theme}")
        script_data = generate_script(theme)
        history["themes_used"].append(theme)
        history["themes_used"] = history["themes_used"][-10:]

    print(f"[2/5] Script généré : {script_data['titre']}")

    audio_path = generate_voice(script_data["texte_voix"], WORKDIR / "voice.mp3")
    duration = get_audio_duration(audio_path)
    print(f"[3/5] Voix générée ({duration:.1f}s)")

    image_path = build_background_image(
        script_data["titre"], script_data["hashtags"], WORKDIR / "background.png"
    )
    video_path = build_video(image_path, audio_path, duration, WORKDIR / "short.mp4")
    print("[4/5] Vidéo assemblée")

    description = script_data["texte_voix"] + "\n\n" + " ".join(
        f"#{t}" for t in script_data["hashtags"]
    )
    video_id = upload_short(
        video_path, script_data["titre"], description, script_data["hashtags"]
    )
    print(f"[5/5] Short publié : https://youtube.com/shorts/{video_id}")

    if news_item:
        history.setdefault("news_used_links", []).append(news_item["lien"])
        history["news_used_links"] = history["news_used_links"][-100:]

    history["scripts"].append({
        "date": datetime.now().isoformat(),
        "source": "actualite" if news_item else "evergreen",
        "titre": script_data["titre"],
        "video_id": video_id,
    })
    save_history(history)


def get_refresh_token_once():
    """À exécuter UNE SEULE FOIS, en local, jamais dans GitHub Actions.
    Nécessite un fichier client_secret.json téléchargé depuis Google Cloud
    Console (Identifiants OAuth 2.0, type 'Application de bureau')."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(
        "client_secret.json",
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    creds = flow.run_local_server(port=0)
    print("Refresh token à copier dans le secret YOUTUBE_REFRESH_TOKEN :")
    print(creds.refresh_token)


if __name__ == "__main__":
    main()
