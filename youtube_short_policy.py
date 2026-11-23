"""Règles communes aux Shorts statiques, Rachel et prospective."""
import json
import math
import os
import re
import subprocess
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

from editorial_style import REGLE_TIRETS, sans_tirets_longs

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config/youtube.json"
JOURNAL = ROOT / "youtube_publications.json"
HISTORIES = (
    ROOT / "short_video_history.json",
    ROOT / "short_video_avatar_history.json",
    ROOT / "short_video_prospective_history.json",
)
API = "https://www.googleapis.com/youtube/v3"
PARIS = ZoneInfo("Europe/Paris")
END_PAUSE_SECONDS = 1.0
MAX_VOICE_SECONDS = 58.0
SCRIPT_RULES = (
    REGLE_TIRETS + " La première phrase énonce un fait concret documenté, "
    "un nom d'entreprise avec sa conséquence directe, ou une situation métier concrète. "
    "Aucune question abstraite en ouverture. "
    "Le titre nomme le sujet dès le début et contient au maximum 60 caractères. "
    "La formule Et si est facultative et réservée à la prospective, après l'accroche ou dans le titre. "
    "Le texte parlé compte 75 à 100 mots, pour une durée cible de 30 à 55 secondes. "
    "Varie les ouvertures : scène précise, fait vérifiable, conséquence concrète ou situation inattendue. "
    "Bannis les formules passe-partout Et si un matin, Imaginez un matin, "
    "Ce n'est pas de la science-fiction lointaine et les briques existent déjà. "
    "Relie chaque transition au sujet avec un exemple précis, sans inventer de preuve. "
    "Varie aussi la conclusion : question ouverte, conséquence précise ou image finale. "
    "La dernière phrase est courte (18 mots maximum), complète et ponctuée. "
    "N'ajoute ni points de suspension ni indication de pause à lire : le montage ajoute la respiration finale. "
    "La première phrase de texte_voix sert d'accroche à l'écran. "
    "Elle doit être complète, affirmative et tenir en 12 mots maximum. "
    "Ajoute au JSON resume "
    "(2 à 3 phrases, mot-clé principal dans la première), et mots_cles "
    "(5 à 8 mots-clés précis liés au sujet). N'invente aucun fait."
)


def config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def records():
    entries = []
    for path in (*HISTORIES, JOURNAL):
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            entries.extend(value.get("scripts", []) if isinstance(value, dict) else value)
    return entries


def record_date(row):
    value = row.get("date", "")
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    # Les historiques antérieurs utilisaient datetime.now() sur des runners UTC.
    return date.replace(tzinfo=date.tzinfo or timezone.utc).astimezone(PARIS)


def unique_recent(days=30):
    cutoff = datetime.now(PARIS) - timedelta(days=days)
    return {
        row["video_id"]: row for row in records()
        if row.get("video_id") and record_date(row) and record_date(row) >= cutoff
    }.values()


def publication_due(kind):
    if os.environ.get("FORCE_PUBLICATION", "").lower() == "true":
        return True
    now = datetime.now(PARIS)
    if now.weekday() not in config()["jours_publication"][kind]:
        print(f"[Cadence] Pas de publication {kind} prévue aujourd’hui.")
        return False
    recent = list(unique_recent(7))
    if any(record_date(row).date() == now.date() for row in recent):
        print("[Cadence] Une vidéo est déjà publiée aujourd’hui.")
        return False
    same_week = [row for row in recent if record_date(row).isocalendar()[:2] == now.isocalendar()[:2]]
    if len(same_week) >= config()["maximum_par_semaine"]:
        print("[Cadence] Quatre publications déjà réalisées cette semaine.")
        return False
    return True


def normal_title(title):
    text = unicodedata.normalize("NFKD", title.casefold())
    return " ".join(re.findall(r"[a-z0-9]+", "".join(c for c in text if not unicodedata.combining(c))))


def script_edges(data):
    text = data.get("texte_voix", "").strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return {
        "accroche": data.get("accroche") or sentences[0],
        "conclusion": sentences[-1] if text else data.get("conclusion", ""),
    }


def recent_script_edges(limit=12):
    # Les anciens historiques sans texte restent utilisables, sans inventer leurs phrases.
    rows = sorted(records(), key=lambda row: record_date(row) or datetime.min.replace(tzinfo=PARIS), reverse=True)
    recent, seen = [], set()
    for row in rows:
        edges = script_edges(row)
        identity = row.get("video_id") or row.get("titre")
        if identity in seen or not any(edges.values()):
            continue
        seen.add(identity)
        recent.append({"titre": row.get("titre", ""), **edges})
        if len(recent) == limit:
            break
    return recent


def script_context(feedback=""):
    context = (
        "\n\nVarie la construction des premières et dernières phrases par rapport aux publications récentes. "
        "Ne reprends pas leurs formules, même en changeant simplement le nom de l'entreprise. "
        "Exemples déjà publiés (à ne pas recopier) :\n"
        + json.dumps(recent_script_edges(), ensure_ascii=False)
    )
    if feedback:
        context += "\n\nRévision demandée avant toute génération de voix :\n" + feedback
    return context


def check_script_variety(data):
    spoken = normal_title(data["texte_voix"])
    for formula in ("et si un matin", "imaginez un matin", "imagine un matin",
                    "ce n est pas de la science fiction", "les briques existent deja"):
        if re.search(r"\b" + re.escape(formula) + r"\b", spoken):
            raise ValueError(f"Formule répétitive à remplacer par un détail propre au sujet : {formula}.")
    ending = data["texte_voix"].rstrip(' \"\'»”')
    if not ending.endswith((".", "!", "?")) or ending.endswith("..."):
        raise ValueError("La narration doit finir par une phrase complète, sans points de suspension.")
    edges = script_edges(data)
    if len(edges["conclusion"].split()) > 18:
        raise ValueError("La dernière phrase doit tenir en 18 mots maximum, avec une chute naturelle.")
    for row in recent_script_edges():
        for key, phrase in edges.items():
            current, previous = normal_title(phrase), normal_title(row.get(key, ""))
            if previous and SequenceMatcher(None, current, previous).ratio() >= .86:
                raise ValueError(f"{key.capitalize()} trop proche d'une publication récente : {row[key]}")


def generate_validated_script(generate, prospective=False):
    """Trois essais maximum, avec retour précis, avant les appels voix et vidéo payants."""
    feedback = ""
    for attempt in range(3):
        data = None
        try:
            data = generate(feedback)
            return prepare_script(data, prospective=prospective)
        except (ValueError, KeyError) as error:
            if attempt == 2:
                raise ValueError(f"Script refusé après trois propositions : {error}") from error
            print(f"[Script] Nouvelle rédaction demandée : {error}")
            feedback = f"Réécris le script complet en corrigeant ce point : {error}"
            if isinstance(data, dict):
                feedback += "\nProposition à corriger : " + json.dumps(
                    {key: data.get(key) for key in ("titre", "texte_voix")}, ensure_ascii=False)


def generate_validated_narration(generate, voice, path, preflight, prospective=False):
    """Réécrit au plus deux fois une narration hors durée avant tout rendu vidéo."""
    duration_feedback = ""
    for attempt in range(3):
        data = generate_validated_script(
            lambda feedback: generate(duration_feedback + "\n" + feedback), prospective=prospective)
        preflight(data)
        audio = voice(data["texte_voix"], path)
        try:
            check_audio_duration(audio)
            return data, audio
        except ValueError:
            if attempt == 2:
                raise
            duration = media_duration(audio)
            target_words = max(1, round(len(data["texte_voix"].split()) * 42 / duration))
            duration_feedback = (
                f"La narration précédente dure {duration:.2f} secondes. "
                f"Réécris environ {target_words} mots pour viser 42 secondes, "
                "avec une accroche courte et une fin complète. "
                "Garde le même sujet et corrige sa longueur sans inventer de faits. "
                "Ce nombre de mots remplace la consigne habituelle de longueur.\n"
                "Proposition à corriger : " + json.dumps(data, ensure_ascii=False))
            print(f"[Durée] Réécriture demandée après une voix de {duration:.2f} s.", flush=True)


def reject_duplicate(title, rows=None):
    title = normal_title(title)
    for row in unique_recent() if rows is None else rows:
        previous = normal_title(row.get("titre", ""))
        words, old_words = set(title.split()), set(previous.split())
        overlap = len(words & old_words) / max(1, len(words | old_words))
        if previous and (SequenceMatcher(None, title, previous).ratio() >= .82 or overlap >= .72):
            raise ValueError(f"Titre proche d’une vidéo des 30 derniers jours : {row['titre']}")


def prepare_script(data, prospective=False):
    if not isinstance(data, dict):
        raise ValueError("Le script doit être un objet JSON.")
    for key in ("titre", "texte_voix", "resume"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"Script incomplet : {key}.")
        data[key] = sans_tirets_longs(data[key]).strip()
    if len(data["titre"]) > 60:
        raise ValueError("Le titre dépasse 60 caractères.")
    if not prospective and re.match(r"et si\b", data["titre"], re.I):
        raise ValueError("La formule Et si est réservée à la prospective.")
    opening = re.match(
        r'''.+?[.!?]+(?:[^\S\r\n]*[»”"])?(?=\s|$)''',
        data["texte_voix"],
        flags=re.DOTALL,
    )
    hook = opening.group() if opening else ""
    if (not normal_title(hook) or len(hook.strip(' «»“”"').split()) > 12
            or any(mark in hook for mark in ("?", "...", "…"))):
        raise ValueError("La première phrase de texte_voix doit être concrète, affirmative "
                         "et complète, en 12 mots maximum.")
    data["accroche"] = hook
    keywords = data.get("mots_cles")
    if not isinstance(keywords, list) or not 5 <= len(keywords) <= 8 or any(
        not isinstance(word, str) or not word.strip() for word in keywords
    ) or len({word.strip().casefold() for word in keywords}) < 5:
        raise ValueError("Cinq à huit mots-clés distincts liés au sujet sont attendus.")
    check_script_variety(data)
    reject_duplicate(data["titre"])
    return data


def inspect_video(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,width,height,sample_aspect_ratio:stream_side_data=rotation:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    video = next((stream for stream in data["streams"] if stream["codec_type"] == "video"), {})
    duration = float(data.get("format", {}).get("duration", 0))
    rotation = any(float(side.get("rotation", 0)) % 360 for side in video.get("side_data_list", []))
    if (video.get("width"), video.get("height")) != (1080, 1920) or rotation:
        raise ValueError("Envoi bloqué : vidéo attendue en 1080 × 1920 sans rotation.")
    if video.get("sample_aspect_ratio", "1:1") not in ("1:1", "N/A"):
        raise ValueError("Envoi bloqué : les pixels doivent être carrés.")
    if not math.isfinite(duration) or not 0 < duration <= 60:
        raise ValueError(f"Envoi bloqué : durée de {duration} s, maximum 60 s.")
    return duration


def media_duration(path, audio_only=False):
    result = subprocess.run(
        ["ffprobe", "-v", "error", *(["-select_streams", "a:0"] if audio_only else []),
         "-show_entries", "stream=duration:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if audio_only and not streams:
        raise ValueError("La vidéo reçue ne contient aucune piste audio.")
    value = streams[0].get("duration") if audio_only else None
    duration = float(value if value not in (None, "N/A") else data["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Durée média invalide : {duration} s.")
    return duration


def check_audio_duration(path):
    duration = media_duration(path)
    if not 30 <= duration <= MAX_VOICE_SECONDS:
        raise ValueError(f"Voix hors cible 30 à {MAX_VOICE_SECONDS:g} s ({duration} s). "
                         "Raccourcir ou allonger le script avant le rendu, sans couper la voix.")
    return duration


def finished_duration(duration):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Durée de narration invalide.")
    # Arrondi vers le haut à 25 images/s et marge pour le conteneur AAC/MP4.
    target = math.ceil((duration + END_PAUSE_SECONDS) * 25) / 25
    if target > 59.9:
        raise ValueError("Pas assez de place pour la pause finale sous 60 s. "
                         "Raccourcir le script, jamais tronquer la narration.")
    return target


def render_static_short(image_path, audio_path, output):
    target = finished_duration(media_duration(audio_path))
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-framerate", "25", "-i", str(image_path),
        "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0",
        "-vf", "scale=1080:1920,setsar=1", "-af", f"apad=whole_dur={target}",
        "-t", str(target), "-c:v", "libx264", "-tune", "stillimage", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output),
    ], check=True)
    inspect_video(output)
    return output


def hook_image(text, path, transparent=True):
    image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0) if transparent else (13, 20, 33, 255))
    draw = ImageDraw.Draw(image)
    for size in range(76, 35, -2):
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", size)
        lines, current = [], ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= 780:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        if len(lines) * (size + 16) <= 340:
            break
    if any(draw.textlength(line, font=font) > 780 for line in lines) or len(lines) * (size + 16) > 340:
        raise ValueError("Accroche trop longue pour la zone lisible.")
    top = 1180 - len(lines) * (size + 16) // 2
    draw.rounded_rectangle((95, top - 25, 915, top + len(lines) * (size + 16) + 25), radius=20, fill=(13, 20, 33, 235))
    for index, line in enumerate(lines):
        draw.text((505, top + index * (size + 16)), line, font=font, fill="white", anchor="mt")
    image.save(path)
    return path


def render_avatar_short(source, hook, output, reference_audio=None):
    # Un fichier paysage inattendu est rejeté avant tout recadrage.
    duration = inspect_video(source)
    received_audio = media_duration(source, audio_only=True)
    if reference_audio is not None:
        original_audio = media_duration(reference_audio)
        print(f"[Durée] Voix originale {original_audio:.2f} s, piste HeyGen {received_audio:.2f} s.")
        if received_audio + .15 < original_audio:
            raise ValueError("La piste HeyGen est plus courte que la voix originale. "
                             "Vérifier la fin du rendu avant publication.")
    target = finished_duration(max(duration, received_audio))
    overlay = hook_image(hook, output.with_suffix(".png"))
    subprocess.run([
        "ffmpeg", "-y", "-i", str(source), "-i", str(overlay),
        "-filter_complex", "[0:v]fps=25,tpad=stop_mode=clone:stop=-1[held];"
        "[held][1:v]overlay=0:0:enable='lt(t,3)'[v];"
        f"[0:a:0]apad=whole_dur={target}[a]",
        "-map", "[v]", "-map", "[a]", "-t", str(target), "-c:v", "libx264", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-b:a", "128k",
        "-movflags", "+faststart", str(output),
    ], check=True)
    inspect_video(output)
    return output


def description(data):
    tags = []
    for tag in data.get("hashtags", data["mots_cles"]):
        tag = re.sub(r"[^\w]", "", tag).removeprefix("#")
        if tag and tag.casefold() != "decisionsandco" and tag not in tags:
            tags.append(tag)
    return (
        f"{data['resume']}\n\n"
        "Décisions & Co accompagne les PME et ETI dans leur transformation IA.\n"
        "En savoir plus : https://decisionsandco.com\n"
        "Abonnez-vous pour recevoir chaque nouvelle analyse.\n\n"
        + " ".join(f"#{tag}" for tag in [*tags[:2], "DecisionsAndCo"])
    )


def metadata(data, avatar=False):
    tags = list(dict.fromkeys([*data["mots_cles"], "DecisionsAndCo"]))
    return {
        "snippet": {
            "title": data["titre"], "description": description(data), "tags": tags,
            "categoryId": "28", "defaultLanguage": "fr", "defaultAudioLanguage": "fr",
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False,
                   **({"containsSyntheticMedia": True} if avatar else {})},
    }


def _get(token, endpoint, **params):
    response = requests.get(
        f"{API}/{endpoint}", headers={"Authorization": f"Bearer {token}"},
        params=params, timeout=30,
    )
    response.raise_for_status()
    return response.json()


def resolve_playlists(token):
    configured = {**config()["playlists"], **json.loads(os.environ.get("YOUTUBE_PLAYLIST_IDS") or "{}")}
    # Retrouve les playlists déjà présentes sur la chaîne, sans en créer.
    channel = _get(token, "channels", part="id", mine="true")["items"][0]["id"]
    page = None
    while True:
        result = _get(token, "playlists", part="snippet,status", channelId=channel, maxResults=50,
                      **({"pageToken": page} if page else {}))
        for row in result["items"]:
            title = row["snippet"]["title"]
            if title in configured and row["status"]["privacyStatus"] == "public":
                configured[title] = configured[title] or row["id"]
        page = result.get("nextPageToken")
        if not page:
            break
    return configured


def classify_playlist(data, prospective=False):
    names = list(config()["playlists"])
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
        json={"model": "claude-sonnet-4-6", "max_tokens": 100,
              "system": "Classe le sujet parmi les playlists autorisées. Réponds uniquement avec le nom exact. "
                        "La prospective doit aller dans la playlist Prospective : et si… ?.",
              "messages": [{"role": "user", "content": json.dumps({
                  "titre": data["titre"], "resume": data["resume"],
                  "prospective": prospective, "playlists": names}, ensure_ascii=False)}]},
        timeout=45,
    )
    response.raise_for_status()
    choice = "".join(block["text"] for block in response.json()["content"] if block["type"] == "text").strip()
    if choice not in names or (prospective and choice != names[-1]) or (not prospective and choice == names[-1]):
        raise ValueError("Classification de playlist invalide.")
    return choice


def save_journal(entries):
    temporary = JOURNAL.with_suffix(".tmp")
    temporary.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(JOURNAL)


class PlaylistPermissionRequired(RuntimeError):
    """Le token autorise l'upload mais nécessite un nouveau consentement pour les playlists."""


def attach_playlist(token, video_id, playlist_id):
    # Vérification préalable pour rendre les reprises idempotentes.
    result = _get(token, "playlistItems", part="id", playlistId=playlist_id, videoId=video_id, maxResults=1)
    if result.get("items"):
        return
    response = requests.post(
        f"{API}/playlistItems", params={"part": "snippet"},
        headers={"Authorization": f"Bearer {token}"},
        json={"snippet": {"playlistId": playlist_id,
                          "resourceId": {"kind": "youtube#video", "videoId": video_id}}},
        timeout=30,
    )
    if response.status_code == 403:
        reasons = {item.get("reason") for item in response.json().get("error", {}).get("errors", [])}
        if "insufficientPermissions" in reasons:
            raise PlaylistPermissionRequired("Le token YouTube nécessite le droit youtube.force-ssl pour les playlists.")
    response.raise_for_status()


def retry_playlists(token):
    entries = json.loads(JOURNAL.read_text()) if JOURNAL.exists() else []
    for row in entries:
        if row["statut"] == "playlist_en_attente":
            try:
                attach_playlist(token, row["video_id"], row["playlist_id"])
            except PlaylistPermissionRequired as error:
                print(f"::warning::{error} Vidéo {row['video_id']} conservée dans la file d’attente.")
                return
            row["statut"] = "publié"
            save_journal(entries)


def upload_short(path, data, token, kind):
    inspect_video(path)
    reject_duplicate(data["titre"])
    plan = data.get("_publication_plan") or prepare_publication(data, token, kind)
    playlist_name, playlist_id = plan["nom"], plan["id"]
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "X-Upload-Content-Type": "video/mp4"},
        json=metadata(data, avatar=kind != "statique"), timeout=30,
    )
    init.raise_for_status()
    with path.open("rb") as stream:
        result = requests.put(init.headers["Location"], headers={"Content-Type": "video/mp4"},
                              data=stream, timeout=300)
    result.raise_for_status()
    video_id = result.json()["id"]
    entries = json.loads(JOURNAL.read_text()) if JOURNAL.exists() else []
    entries.append({
        "date": datetime.now(timezone.utc).isoformat(), "titre": data["titre"],
        "video_id": video_id, "format": kind, "playlist": playlist_name,
        "playlist_id": playlist_id, "statut": "playlist_en_attente",
        **script_edges(data),
        **({"rachel_look": data["_rachel_look"]} if data.get("_rachel_look") else {}),
    })
    save_journal(entries)
    print(f"[YouTube] Vidéo envoyée : https://youtube.com/shorts/{video_id}", flush=True)
    try:
        attach_playlist(token, video_id, playlist_id)
    except PlaylistPermissionRequired as error:
        print(f"::warning::{error} Vidéo {video_id} publiée, ajout à la playlist en attente.")
        return video_id
    entries[-1]["statut"] = "publié"
    save_journal(entries)
    return video_id


def prepare_publication(data, token, kind):
    playlists = resolve_playlists(token)
    playlist_name = classify_playlist(data, prospective=kind == "prospective")
    if not isinstance(playlists.get(playlist_name), str) or not playlists[playlist_name].strip():
        raise ValueError(f"Identifiant de playlist manquant : {playlist_name}")
    # Contrôle distant incluant les vidéos publiées par d'autres outils.
    channels = _get(token, "channels", part="contentDetails", mine="true")
    uploads = channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    previous = []
    page = None
    while True:
        listing = _get(token, "playlistItems", part="snippet", playlistId=uploads, maxResults=50,
                       **({"pageToken": page} if page else {}))
        for item in listing["items"]:
            snippet = item["snippet"]
            previous.append({"date": snippet["publishedAt"], "titre": snippet["title"],
                             "video_id": snippet["resourceId"]["videoId"]})
        page = listing.get("nextPageToken")
        if not page or not listing["items"] or (record_date(previous[-1]) and record_date(previous[-1]) < datetime.now(PARIS) - timedelta(days=30)):
            break
    recent = [row for row in previous if record_date(row) and record_date(row) >= datetime.now(PARIS) - timedelta(days=30)]
    reject_duplicate(data["titre"], recent)
    if kind == "prospective" and os.environ.get("FORCE_PUBLICATION", "").lower() != "true" and any(
        normal_title(row["titre"]).startswith("et si ") and
        record_date(row).isocalendar()[:2] == datetime.now(PARIS).isocalendar()[:2]
        for row in recent
    ):
        raise ValueError("Une vidéo Et si est déjà publiée cette semaine.")
    plan = {"nom": playlist_name, "id": playlists[playlist_name]}
    data["_publication_plan"] = plan
    return plan
