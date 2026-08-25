#!/usr/bin/env python3
"""D&Co — publication automatique de l'article hebdomadaire sur decisionsandco.com.

Ce module est appelé depuis agent_article_hebdo.py une fois le brouillon
LinkedIn généré (package, theme, slug, date_slug). Il ne réécrit PAS le
contenu de fond : il le restructure au format attendu par le site
(frontmatter Astro + corps HTML), génère une couverture dédiée via l'API
Images d'OpenAI (même style que les illustrations déjà publiées sur le
site), puis committe le résultat sur une branche dédiée du repo
decisionsandco.com et ouvre une Pull Request.

Rien n'est jamais poussé directement sur `main` : la mise en ligne reste un
choix humain (merge de la PR). Le déploiement (npm run build + rsync) est
ensuite automatique via le workflow deploy.yml déjà en place sur ce repo,
dès que la PR est mergée.

Variables d'environnement attendues :
- ANTHROPIC_API_KEY  (déjà utilisée par agent_article_hebdo.py)
- OPENAI_API_KEY      clé API OpenAI, pour la génération d'image
- SITE_REPO           "owner/decisionsandco.com" (repo du site)
- SITE_REPO_PAT       token GitHub à portée fine sur ce repo,
                       droits "Contents: Read and write" +
                       "Pull requests: Read and write"

Si SITE_REPO ou SITE_REPO_PAT sont absents, la publication site est
silencieusement sautée (permet de déployer ce module sans casser le
pipeline existant tant que les secrets ne sont pas configurés).
"""

import os
import re
import json
import base64
import subprocess
import tempfile
from io import BytesIO

import requests
from PIL import Image

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
SITE_REPO = os.environ.get("SITE_REPO", "")
SITE_REPO_PAT = os.environ.get("SITE_REPO_PAT", "")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

MODEL = "claude-sonnet-4-6"
IMAGE_MODEL = "gpt-image-1"

# Liste fermée — doit rester identique à l'enum `category` de
# src/content/config.ts sur decisionsandco.com. À resynchroniser
# manuellement si ce schéma évolue côté site.
CATEGORIES = [
    "Formation IA",
    "Innovation IA",
    "Innovation",
    "Intelligence Artificielle",
    "Analyse",
    "Événement",
    "Transformation IA",
    "Réglementation IA",
    "Veille",
]

DEFAULT_CATEGORY = "Transformation IA"


def _echapper(texte):
    return (texte or "").replace('"', '\\"')


def build_site_prompt(package, theme):
    return f"""Tu restructures un article déjà rédigé pour LinkedIn afin de le publier sur le site decisionsandco.com. NE RÉINVENTE PAS le contenu : restructure et enrichis la mise en forme, sans changer le fond ni l'angle ni ajouter de faits nouveaux.

ARTICLE SOURCE (déjà validé, format LinkedIn) :
Titre : {package.get('titre', '')}
Chapo : {package.get('chapo', '')}
Corps :
{package.get('corps', '')}

CE QU'IL FAUT PRODUIRE :
1. "corps_html" : le corps ci-dessus reformaté en HTML (pas de Markdown). Chaque ligne de titre de section devient <h2>...</h2>, chaque paragraphe devient <p>...</p>. Tu peux transformer AU MAXIMUM une section clé en encart <div class="definition-box"><h3>...</h3><p>...</p></div> si le contenu s'y prête naturellement (une définition, un point de méthode) — sinon n'en mets aucun. N'invente aucun fait, aucun chiffre, aucune section nouvelle.
2. "subtitle" : une phrase de valeur qui complète le titre, ton éditorial site web (pas une redite du chapo LinkedIn).
3. "description" : résumé de l'article en 2 phrases maximum, 600 caractères MAX — respecte strictement cette limite.
4. "category" : choisis EXACTEMENT une valeur parmi cette liste fermée, aucune autre valeur n'est acceptée : {json.dumps(CATEGORIES, ensure_ascii=False)}
5. "coverAlt" : description factuelle et accessible de l'image de couverture, une phrase, sans mentionner qu'elle est générée par IA.
6. "image_prompt" : en anglais, 1 à 2 phrases, pour générer une illustration abstraite et professionnelle sur le thème "{theme['theme']}" — style épuré et conceptuel, cohérent avec des couvertures d'articles déjà publiées sur un site de conseil en IA. Pas de texte incrusté dans l'image, pas de visage humain reconnaissable.

Réponds UNIQUEMENT en JSON valide, sans markdown autour :
{{"corps_html":"...","subtitle":"...","description":"...","category":"...","coverAlt":"...","image_prompt":"..."}}
Échappe les guillemets avec \\" et les sauts de ligne avec \\n."""


def generate_site_content(package, theme):
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": ANTHROPIC_API_KEY,
        },
        json={
            "model": MODEL,
            "max_tokens": 4000,
            "messages": [{
                "role": "user",
                "content": build_site_prompt(package, theme),
            }],
        },
        timeout=90,
    )
    resp.raise_for_status()
    texte = resp.json()["content"][0]["text"].strip()
    texte = re.sub(r"^```(?:json)?\s*|\s*```$", "", texte)
    data = json.loads(texte)

    if data.get("category") not in CATEGORIES:
        print(f"Catégorie renvoyée invalide ({data.get('category')!r}) — repli sur {DEFAULT_CATEGORY!r}.")
        data["category"] = DEFAULT_CATEGORY

    if len(data.get("description", "")) > 600:
        data["description"] = data["description"][:597].rstrip() + "..."

    return data


def generate_cover_openai(image_prompt):
    """Génère la couverture via l'API Images d'OpenAI (gpt-image-1).

    Demande explicitement du webp, MAIS reconvertit systématiquement le
    résultat via Pillow avant de le retourner : certains modèles de cette
    famille (gpt-image-2 notamment) renvoient du PNG malgré une demande de
    webp (bug connu côté API/SDK). La conversion locale garantit le format
    final quel que soit ce que l'API renvoie réellement.
    """
    resp = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": IMAGE_MODEL,
            "prompt": image_prompt,
            "size": "1536x1024",
            "output_format": "webp",
            "quality": "high",
        },
        timeout=120,
    )
    resp.raise_for_status()
    b64 = resp.json()["data"][0]["b64_json"]
    raw = base64.b64decode(b64)

    img = Image.open(BytesIO(raw)).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="WEBP", quality=90)
    buf.seek(0)
    return buf


def build_markdown(package, site_data, slug, date_slug):
    lignes = [
        "---",
        f'title: "{_echapper(package.get("titre", ""))}"',
        f'subtitle: "{_echapper(site_data.get("subtitle", ""))}"',
        f'description: "{_echapper(site_data.get("description", ""))}"',
        f"publishedAt: {date_slug}",
        f'category: "{site_data.get("category", DEFAULT_CATEGORY)}"',
        f'cover: "/images/content/{slug}.webp"',
        f'coverAlt: "{_echapper(site_data.get("coverAlt", ""))}"',
        "featured: false",
        "draft: false",
        "---",
        "",
    ]
    return "\n".join(lignes) + site_data.get("corps_html", "")


def _run(*args, cwd=None):
    return subprocess.run(args, check=True, capture_output=True, text=True, cwd=cwd)


def publish_to_site(package, theme, slug, date_slug):
    """Point d'entrée appelé depuis agent_article_hebdo.py.

    Retourne l'URL de la PR ouverte, ou None si la publication site a été
    sautée (secrets absents, DRY_RUN) ou a échoué (l'appelant doit
    intercepter les exceptions pour ne jamais casser le flux LinkedIn).
    """
    if not SITE_REPO or not SITE_REPO_PAT:
        print("SITE_REPO / SITE_REPO_PAT absents — publication site sautée.")
        return None

    print("Génération de la version site (HTML + métadonnées)...")
    site_data = generate_site_content(package, theme)
    print(f"Catégorie retenue : {site_data.get('category')}")

    image_buf = None
    if OPENAI_API_KEY and not DRY_RUN:
        print("Génération de la couverture via l'API Images OpenAI...")
        image_buf = generate_cover_openai(site_data["image_prompt"])
    else:
        print("[DRY_RUN ou clé OpenAI absente] Couverture non générée.")

    markdown = build_markdown(package, site_data, slug, date_slug)
    branch = f"article/{date_slug}-{slug}"

    if DRY_RUN:
        print(f"[DRY_RUN] Branche prévue : {branch}")
        print(markdown[:600] + ("..." if len(markdown) > 600 else ""))
        return None

    with tempfile.TemporaryDirectory() as tmp:
        clone_url = f"https://x-access-token:{SITE_REPO_PAT}@github.com/{SITE_REPO}.git"
        _run("git", "clone", "--depth", "1", clone_url, tmp)
        _run("git", "checkout", "-b", branch, cwd=tmp)
        _run("git", "config", "user.name", "Agent Editorial DCo", cwd=tmp)
        _run("git", "config", "user.email", "agent@decisionsandco.com", cwd=tmp)

        md_path = os.path.join(tmp, "src", "content", "articles", f"{slug}.md")
        os.makedirs(os.path.dirname(md_path), exist_ok=True)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown)

        if image_buf is not None:
            img_path = os.path.join(tmp, "public", "images", "content", f"{slug}.webp")
            os.makedirs(os.path.dirname(img_path), exist_ok=True)
            with open(img_path, "wb") as f:
                f.write(image_buf.read())

        _run("git", "add", ".", cwd=tmp)
        _run("git", "commit", "-m", f"Article : {package.get('titre', '')}", cwd=tmp)
        _run("git", "push", "-u", "origin", branch, cwd=tmp)

    print("Ouverture de la Pull Request...")
    pr_resp = requests.post(
        f"https://api.github.com/repos/{SITE_REPO}/pulls",
        headers={
            "Authorization": f"Bearer {SITE_REPO_PAT}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "title": f"Article : {package.get('titre', '')}",
            "head": branch,
            "base": "main",
            "body": (
                f"Article généré automatiquement — thème « {theme['theme']} ».\n\n"
                f"**Catégorie proposée :** {site_data.get('category')}\n\n"
                "À relire avant merge : titre, catégorie, description, image de couverture. "
                "Le déploiement (build + rsync) se déclenche automatiquement au merge."
            ),
        },
        timeout=30,
    )
    pr_resp.raise_for_status()
    pr_url = pr_resp.json().get("html_url", "")
    print(f"PR ouverte : {pr_url}")
    return pr_url
