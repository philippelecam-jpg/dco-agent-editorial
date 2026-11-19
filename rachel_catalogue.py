"""Choix et mise à disposition des portraits Rachel pour les deux flux HeyGen."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image

from youtube_short_policy import normal_title, record_date, records

ROOT = Path(__file__).resolve().parent
CATALOGUE = ROOT / "config/rachel_looks.json"
ASSET_CACHE = ROOT / "rachel_assets.json"
ASSETS_URL = "https://api.heygen.com/v3/assets"


def load_catalogue():
    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    if catalogue.get("version") != 1 or not isinstance(catalogue.get("looks"), list):
        raise ValueError("Catalogue Rachel invalide.")
    ids = [look["id"] for look in catalogue["looks"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Identifiants Rachel en double dans le catalogue.")
    return catalogue


def image_path(look):
    path = (ROOT / look["image"]).resolve()
    if not path.is_relative_to((ROOT / "assets/rachel").resolve()):
        raise ValueError("Le portrait doit se trouver dans assets/rachel/.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != look["sha256"]:
        raise ValueError(f"L'image {look['id']} a changé depuis sa validation.")
    with Image.open(path) as image:
        width, height = image.size
        if image.format != "PNG" or min(width, height) < 512 or abs(width / height - 9 / 16) > .005:
            raise ValueError(f"Portrait {look['id']} invalide : PNG vertical proche de 9:16 attendu.")
        image.verify()
    return path


def subject_family(data, kind, catalogue, context=""):
    playlist = data.get("_publication_plan", {}).get("nom", "")
    # La classification éditoriale déjà effectuée est réutilisée sans appel IA supplémentaire.
    if playlist == "Cybersécurité et incidents":
        return "cybersecurite"
    title = normal_title(data.get("titre", ""))
    details = normal_title(" ".join([data.get("resume", ""), context]))
    scores = {}
    for family, rule in catalogue["families"].items():
        score = 0
        for keyword in rule.get("keywords", []):
            pattern = r"\b" + re.escape(normal_title(keyword)) + r"\b"
            score += 3 * bool(re.search(pattern, title)) + bool(re.search(pattern, details))
        scores[family] = score
    best = max(scores, key=scores.get)
    if scores[best]:
        return best
    return catalogue["playlist_families"].get(playlist, "prospective" if kind == "prospective" else "actualite")


def usage_history(rows=None):
    last_used = {}
    latest_id, latest_date = None, None
    for row in records() if rows is None else rows:
        look = row.get("rachel_look", {})
        date = record_date(row)
        if not isinstance(look, dict) or not look.get("id") or not row.get("video_id") or not date:
            continue
        look_id = look["id"]
        # Les doublons entre historique et journal d'upload ne comptent qu'une fois.
        if look_id not in last_used or date > last_used[look_id]:
            last_used[look_id] = date
        if latest_date is None or date > latest_date:
            latest_id, latest_date = look_id, date
    return last_used, latest_id


def select_look(data, kind, context="", catalogue=None, rows=None):
    if kind not in ("avatar", "prospective"):
        raise ValueError("Le catalogue Rachel concerne uniquement les vidéos avatar et prospective.")
    catalogue = load_catalogue() if catalogue is None else catalogue
    family = subject_family(data, kind, catalogue, context)
    candidates = []
    for look in catalogue["looks"]:
        if not look.get("enabled") or not look.get("approved") or kind not in look["formats"]:
            continue
        if family not in look["families"]:
            continue
        try:
            image_path(look)
        except (OSError, ValueError) as error:
            print(f"::warning::Portrait {look['id']} ignoré : {error}")
            continue
        candidates.append(look)
    last_used, last_id = usage_history(rows)
    candidates = [look for look in candidates if look["id"] != last_id]
    if not candidates:
        raise ValueError("Aucune image validée compatible sans répétition consécutive.")
    never = datetime.min.replace(tzinfo=timezone.utc)
    chosen = min(candidates, key=lambda look: (
        last_used.get(look["id"], never), -look.get("priority", 0), look["id"]))
    return chosen, family


def ensure_asset(look):
    path = image_path(look)
    try:
        cache = json.loads(ASSET_CACHE.read_text(encoding="utf-8"))
        if not isinstance(cache.get("assets"), dict):
            raise ValueError("Cache invalide")
    except (OSError, ValueError, AttributeError):
        cache = {"version": 1, "assets": {}}
    cached = cache["assets"].get(look["id"], {})
    if not isinstance(cached, dict):
        cached = {}
    if cached.get("sha256") == look["sha256"] and isinstance(cached.get("asset_id"), str) and cached["asset_id"].strip():
        return cached["asset_id"]
    with path.open("rb") as image:
        response = requests.post(
            ASSETS_URL, headers={"x-api-key": os.environ["HEYGEN_API_KEY"]},
            files={"file": (path.name, image, "image/png")}, timeout=60,
        )
    response.raise_for_status()
    asset_id = response.json()["data"]["asset_id"]
    if not isinstance(asset_id, str) or not asset_id.strip():
        raise ValueError("HeyGen n'a pas retourné d'identifiant pour le portrait.")
    cache["assets"][look["id"]] = {
        "sha256": look["sha256"], "asset_id": asset_id,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    temporary = ASSET_CACHE.with_suffix(".tmp")
    temporary.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(ASSET_CACHE)
    return asset_id


def prepare_rachel_image(data, kind, context=""):
    """Sélectionne une image, la charge une fois dans HeyGen, puis trace le choix réel."""
    try:
        look, family = select_look(data, kind, context)
        asset_id = ensure_asset(look)
        data["_rachel_look"] = {
            "id": look["id"], "image": look["image"], "family": family, "fallback": False,
        }
        print(f"[Rachel] Portrait {look['id']} choisi pour {family}.")
        return asset_id
    except (OSError, ValueError, KeyError, requests.RequestException) as error:
        # L'image historique est déjà disponible dans HeyGen, indépendamment du catalogue.
        fallback = os.environ.get("RACHEL_PHOTO_ASSET_ID", "").strip()
        if not fallback:
            raise RuntimeError("Portrait Rachel indisponible et secret de secours absent.") from error
        data["_rachel_look"] = {
            "id": "originale-secours", "image": "assets/Rachel.PNG", "fallback": True,
        }
        print(f"::warning::Catalogue Rachel indisponible ({error}). Image d'origine utilisée en secours.")
        return fallback
