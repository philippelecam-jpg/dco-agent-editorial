"""Livre sur Instagram les montages déjà publiés par les deux agents Rachel."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import requests

from editorial_style import sans_tirets_longs


GRAPH = "https://graph.facebook.com/v27.0"
USERNAME = "decisionsandco"
ARCHIVE = Path("tmp_instagram_reel")
JOURNAL = Path("historique/instagram")
ARCHIVE_CONTEXT = b"dco-rachel-instagram-reel-v1"
MP4_LIMIT = 100_000_000


CTA = "→ Votre pré-diagnostic IA : lien en bio"
SOCLE_HASHTAGS = ("IAenEntreprise", "PME", "TransformationIA", "DecisionsAndCo")
MAX_HASHTAGS = 6


def hashtags_for(script):
    """Hashtags du script puis socle D&Co, sans doublon (insensible à la casse), 6 au plus."""
    tags, seen = [], set()
    for raw in list(script.get("hashtags") or []) + list(SOCLE_HASHTAGS):
        tag = re.sub(r"[^\wÀ-ÿ]", "", str(raw).lstrip("#"))
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    # Le socle passe avant les tags du script au-delà de la limite.
    socle = [t for t in tags if t.lower() in {s.lower() for s in SOCLE_HASHTAGS}]
    autres = [t for t in tags if t not in socle][:MAX_HASHTAGS - len(socle)]
    return " ".join("#" + t for t in autres + socle)


def caption_for(script):
    title = sans_tirets_longs(script["titre"]).strip()
    summary = sans_tirets_longs(script["resume"]).strip()
    enjeu = sans_tirets_longs(script.get("enjeu_pme") or "").strip()
    takeaway = "\n\nCe que ça change pour une PME : " + enjeu if enjeu else ""
    signature = "\n\nRachel, présentatrice IA de Décisions & Co."
    footer = "\n\n" + CTA + "\n" + hashtags_for(script)
    available = 2200 - len(title) - len(takeaway) - len(signature) - len(footer) - 2
    if len(summary) > available:
        summary = summary[:available - 1].rsplit(" ", 1)[0] + "…"
    return title + "\n\n" + summary + takeaway + signature + footer


def archive_cipher(token):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(hashlib.sha256(ARCHIVE_CONTEXT + b"\0" + token.encode()).digest())


def stage_reel(video_path, script, video_id):
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not token:
        print("::warning::Instagram ignoré : le secret INSTAGRAM_ACCESS_TOKEN est absent.")
        return
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Identifiant YouTube invalide pour l’archive Instagram.")
    if not 0 < video_path.stat().st_size <= MP4_LIMIT:
        raise ValueError("Taille du MP4 hors limite pour l’archive Instagram.")
    metadata = json.dumps({"youtube_id": video_id, "caption": caption_for(script)},
                          ensure_ascii=False).encode("utf-8")
    nonce = os.urandom(12)
    ciphertext = archive_cipher(token).encrypt(nonce, video_path.read_bytes(), metadata)
    ARCHIVE.mkdir(exist_ok=True)
    (ARCHIVE / "manifest.json").write_bytes(metadata)
    (ARCHIVE / "reel.enc").write_bytes(nonce + ciphertext)


def read_archive():
    metadata = (ARCHIVE / "manifest.json").read_bytes()
    manifest = json.loads(metadata)
    if (not re.fullmatch(r"[A-Za-z0-9_-]{11}", manifest["youtube_id"])
            or not 0 < len(manifest["caption"]) <= 2200):
        raise ValueError("Le manifeste Instagram est invalide.")
    return manifest, metadata


def save_entry(path, entry):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class MetaError(RuntimeError):
    pass


class Instagram:
    def __init__(self, token):
        self.token = token

    def request(self, method, url, *, step, upload_headers=None, **kwargs):
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if upload_headers is not None:
            headers.update(upload_headers)
        try:
            response = requests.request(
                method, url, headers=headers, timeout=(10, 90), allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise MetaError(f"{step} : aucun retour de Meta.") from None
        try:
            data = response.json()
        except ValueError:
            raise MetaError(f"{step} : réponse illisible (HTTP {response.status_code}).") from None
        if not isinstance(data, dict):
            raise MetaError(f"{step} : réponse inattendue de Meta.")
        if not 200 <= response.status_code < 300 or data.get("error"):
            details = data.get("error") or {}
            details = details if isinstance(details, dict) else {}
            code = details.get("code")
            subcode = details.get("error_subcode")
            suffix = f", code Meta {code}" if isinstance(code, int) else ""
            if isinstance(subcode, int):
                suffix += f", sous-code {subcode}"
            raise MetaError(f"{step} : HTTP {response.status_code}{suffix}.")
        return data

    def account_id(self):
        after = None
        for _ in range(5):
            params = {"fields": "id,username", "limit": 100}
            if after:
                params["after"] = after
            result = self.request("GET", f"{GRAPH}/me/assigned_instagram_accounts",
                                  params=params, step="Recherche du compte")
            for account in result["data"]:
                identifier = str(account.get("id", ""))
                if account.get("username", "").casefold() == USERNAME and identifier.isdecimal():
                    return identifier
            paging = result.get("paging", {})
            after = paging.get("cursors", {}).get("after")
            if not paging.get("next") or not after:
                break
        raise MetaError(f"Le compte @{USERNAME} n’est pas accessible avec ce jeton.")

    def find_published(self, account_id, caption):
        result = self.request("GET", f"{GRAPH}/{account_id}/media",
                              params={"fields": "id,caption", "limit": 50}, step="Recherche du Reel")
        matches = [item["id"] for item in result["data"] if item.get("caption") == caption]
        if len(matches) > 1:
            raise MetaError("Plusieurs Reels correspondent à cette légende. Vérification manuelle requise.")
        return matches[0] if matches else None

    def create_and_upload(self, account_id, caption, video):
        result = self.request("POST", f"{GRAPH}/{account_id}/media", step="Création du conteneur Reel",
                              data={"media_type": "REELS", "upload_type": "resumable",
                                    "is_ai_generated": "true", "caption": caption})
        container_id = str(result.get("id", ""))
        uri = result.get("uri", "")
        endpoint = urlsplit(uri)
        if (not container_id.isdecimal() or endpoint.scheme != "https"
                or endpoint.netloc != "rupload.facebook.com" or not endpoint.path.startswith("/ig-api-upload/")
                or endpoint.path.rsplit("/", 1)[-1] != container_id):
            raise MetaError("Meta a renvoyé une adresse de transfert invalide.")
        result = self.request("POST", uri, step="Transfert du MP4", data=video, upload_headers={
            "Authorization": f"OAuth {self.token}", "Content-Type": "application/octet-stream",
            "offset": "0", "file_size": str(len(video)),
        })
        if result.get("success") is not True:
            raise MetaError("Meta n’a pas confirmé la réception du MP4.")
        return container_id

    def status(self, container_id):
        if not str(container_id).isdecimal():
            raise MetaError("Identifiant de conteneur invalide.")
        result = self.request("GET", f"{GRAPH}/{container_id}", params={"fields": "status_code"},
                              step="État du conteneur")
        return result.get("status_code")

    def wait_until_ready(self, container_id):
        for attempt in range(6):
            state = self.status(container_id)
            if state == "FINISHED":
                return
            if state != "IN_PROGRESS":
                raise MetaError("Meta a arrêté le traitement du conteneur Reel.")
            if attempt < 5:
                time.sleep(60)
        raise MetaError("Meta traite toujours le conteneur après cinq minutes.")

    def publish(self, account_id, container_id):
        result = self.request("POST", f"{GRAPH}/{account_id}/media_publish", step="Publication du Reel",
                              data={"creation_id": container_id})
        return result.get("id")

    def verify(self, media_id):
        if not str(media_id).isdecimal():
            raise MetaError("Identifiant de Reel invalide.")
        result = self.request("GET", f"{GRAPH}/{media_id}", step="Vérification du Reel",
                              params={"fields": "permalink,media_product_type,is_ai_generated"})
        permalink = result.get("permalink", "")
        url = urlsplit(permalink)
        if (url.scheme != "https" or url.netloc not in {"instagram.com", "www.instagram.com"}
                or result.get("media_product_type") != "REELS"):
            raise MetaError("Meta n’a pas encore confirmé le lien du Reel publié.")
        return permalink, result.get("is_ai_generated") is True


def prepare(client, manifest, metadata, path, entry, attempt):
    from cryptography.exceptions import InvalidTag

    if entry.get("media_id"):
        return
    account_id = client.account_id()
    caption = manifest["caption"]
    previous = client.find_published(account_id, caption)
    if previous:
        entry.update(statut="publie", media_id=previous)
        save_entry(path, entry)
        return
    if entry.get("container_id"):
        state = client.status(entry["container_id"])
        if state == "PUBLISHED":
            raise MetaError("Meta indique une publication déjà effectuée. Le lien reste à rapprocher du journal.")
        if state not in {"ERROR", "EXPIRED"}:
            raise MetaError("Une publication a déjà été demandée. Vérifier le compte avant toute nouvelle tentative.")
    encrypted = (ARCHIVE / "reel.enc").read_bytes()
    try:
        video = archive_cipher(client.token).decrypt(encrypted[:12], encrypted[12:], metadata)
    except (InvalidTag, ValueError):
        raise MetaError("Archive illisible avec ce jeton. Utiliser le jeton qui a chiffré le MP4.") from None
    container_id = client.create_and_upload(account_id, caption, video)
    client.wait_until_ready(container_id)
    entry.update(statut="publication_demandee", account_id=account_id, container_id=container_id,
                 tentative=attempt, source_run_id=os.environ.get("SOURCE_RUN_ID", ""))
    save_entry(path, entry)


def publish(client, manifest, path, entry, attempt):
    media_id = entry.get("media_id")
    if not media_id:
        if entry.get("tentative") != attempt or entry.get("statut") != "publication_demandee":
            raise MetaError("Le journal ne contient pas de demande de publication pour cette tentative.")
        account_id = entry["account_id"]
        container_id = entry["container_id"]
        state = client.status(container_id)
        if state == "PUBLISHED":
            media_id = client.find_published(account_id, manifest["caption"])
        elif state == "FINISHED":
            try:
                media_id = client.publish(account_id, container_id)
            except MetaError as error:
                print(f"::warning::{error} Recherche du Reel avant toute reprise.", flush=True)
            if not media_id:
                media_id = client.find_published(account_id, manifest["caption"])
        if not media_id:
            raise MetaError("Publication non confirmée. La demande reste dans le journal pour éviter un doublon.")
        entry.update(statut="publie", media_id=media_id)
        save_entry(path, entry)
    if entry.get("permalink") and entry.get("label_ia") is True:
        print(f"Reel déjà enregistré : {entry['permalink']}")
        return
    for index in range(4):
        try:
            link, label = client.verify(media_id)
            entry.update(permalink=link, label_ia=label)
            save_entry(path, entry)
            if label:
                print(f"Reel publié avec le label IA confirmé : {link}", flush=True)
                return
        except MetaError as error:
            print(f"::warning::{error}", flush=True)
        if index < 3:
            time.sleep(5)
    raise MetaError("Reel publié. Le lien ou le label IA reste à confirmer.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "publish"))
    args = parser.parse_args()
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not token:
        parser.exit(1, "Le secret INSTAGRAM_ACCESS_TOKEN est absent ou vide.\n")
    try:
        manifest, metadata = read_archive()
        video_id = manifest["youtube_id"]
        path = JOURNAL / f"{video_id}.json"
        entry = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"youtube_id": video_id}
        attempt = f"{os.environ['GITHUB_RUN_ID']}:{os.environ['GITHUB_RUN_ATTEMPT']}"
        client = Instagram(token)
        if args.action == "prepare":
            prepare(client, manifest, metadata, path, entry, attempt)
        else:
            publish(client, manifest, path, entry, attempt)
    except (OSError, ValueError, KeyError, MetaError) as error:
        parser.exit(1, f"Instagram : {error}\n")


if __name__ == "__main__":
    main()
