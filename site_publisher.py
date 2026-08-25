#!/usr/bin/env python3
"""D&Co — publication automatique de l'article hebdomadaire sur decisionsandco.com.

Ce module est appelé depuis agent_article_hebdo.py une fois le brouillon
LinkedIn généré (package, theme, slug, date_slug). Il ne réécrit PAS le
contenu de fond : il le restructure au format attendu par le site
(frontmatter Astro + corps HTML), génère une couverture dédiée via l'API
Images d'OpenAI (même style que les illustrations déjà publiées sur le
site), commit le résultat sur une branche dédiée du repo
decisionsandco.com, ouvre une Pull Request, puis :

- si aucune anomalie n'est détectée (voir detect_anomalies) : merge la PR
  automatiquement — le déploiement (build + rsync) se déclenche alors
  immédiatement via deploy.yml, sans action humaine ;
- si une anomalie est détectée (catégorie invalide repli sur défaut,
  description tronquée, HTML mal formé, contenu suspect ou trop court...) :
  la PR reste ouverte et reçoit un commentaire listant les anomalies —
  c'est la seule situation où une relecture manuelle est nécessaire avant
  merge.

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
import time
from io import BytesIO

import requests
from PIL import Image

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
SITE_REPO = os.environ.get("SITE_REPO", "")
SITE_REPO_PAT = os.environ.get("SITE_REPO_PAT", "")
# Réutilisés depuis le flux email existant (notify_make_email dans
# agent_article_hebdo.py) : mêmes secrets, aucun nouveau à créer.
MAKE_WEBHOOK_URL = os.environ.get("MAKE_WEBHOOK_URL", "")
MAKE_API_KEY = os.environ.get("MAKE_API_KEY", "")
# Désactivée par défaut : le filtre côté Router Make (type = alerte_site)
# n'est pas encore configuré. Passer à "true" une fois ce filtre en place
# pour réactiver l'alerte sans toucher au code.
ALERTE_EMAIL_SITE = os.environ.get("ALERTE_EMAIL_SITE", "false").lower() == "true"
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

MODEL = "claude-sonnet-4-6"
IMAGE_MODEL = "gpt-image-1"

SITE_ARTICLE_BASE = "https://www.decisionsandco.com/actualites"
SITE_IMAGE_BASE = "https://www.decisionsandco.com/images/content"
# Même fichier que celui géré par agent_article_teaser_auto.py (scraping
# quotidien) — on y ajoute l'URL nous-mêmes dès qu'on la tease avec succès,
# pour que ce scraper ne la republie pas en double le lendemain. Ce
# scraper reste un filet de secours pour les articles mergés manuellement
# après escalade (cas où ce module ne déclenche jamais le teaser).
KNOWN_URLS_PATH = "articles/known_urls.json"

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

# Styles visuels parmi lesquels le modèle choisit celui qui convient le
# mieux à chaque article — évite que toutes les couvertures se ressemblent
# (ce qui arrivait quand un seul style était imposé en dur).
STYLES_VISUELS = {
    "abstrait_conceptuel": (
        "Clean abstract conceptual illustration, dark background, minimal geometric "
        "shapes (circles, triangles, grids, connecting lines) representing the idea. "
        "No text, no human figures."
    ),
    "photo_realiste": (
        "Realistic editorial photography style, professional office or meeting scene, "
        "natural lighting, generic anonymous people shown from a distance, from behind, "
        "or with faces not in sharp focus — never a close-up identifiable face. "
        "Stock-photography feel."
    ),
    "schema_technique": (
        "Clean technical schema/diagram on a light background, icons connected by "
        "arrows or flow lines, professional color palette, information-design feel. "
        "No text labels."
    ),
    "grille_icones": (
        "Colorful grid or collage of simple flat icons representing key concepts of "
        "the article, light background, professional and modern, organized in a "
        "clear grid layout. No text."
    ),
}
DEFAULT_STYLE = "abstrait_conceptuel"

# Encadré "À propos" — texte identique sur tous les articles existants du
# site (vérifié sur plusieurs exemples), donc figé en dur : jamais généré
# par le modèle, zéro risque de variation ou de HTML mal formé.
ABOUT_BOX = (
    '<div class="article-about-section">\n'
    "<p><strong>À propos de Decisions & Co :</strong> Cabinet de conseil spécialisé dans "
    "l'accompagnement des dirigeants sur les enjeux d'intelligence artificielle, nous "
    "proposons des diagnostics IA ROIste, des missions de gouvernance IA et des "
    "programmes d'acculturation pour les équipes dirigeantes.</p>\n"
    "</div>"
)


def build_faq_yaml(faq_items):
    """Bloc YAML `faq:` du frontmatter, à partir de la liste de Q/R.

    Retourne une chaîne vide si la liste est vide (le champ est alors omis
    du frontmatter, ce qui est valide selon le schéma).
    """
    if not faq_items:
        return ""
    lignes = ["faq:"]
    for item in faq_items:
        q = _echapper(item.get("question", ""))
        r = _echapper(item.get("answer", ""))
        lignes.append(f'  - question: "{q}"')
        lignes.append(f'    answer: "{r}"')
    return "\n".join(lignes)


def build_faq_html(faq_items):
    """Bloc HTML `.faq-section` visible, à partir de la MÊME liste que
    build_faq_yaml — jamais deux textes générés séparément par le modèle,
    pour garantir une duplication frontmatter/corps toujours identique
    (c'est précisément le piège que la spec signale explicitement : des
    données structurées invisibles dans le corps sont contraires aux
    guidelines Google).
    """
    if not faq_items:
        return ""
    parties = ['<div class="faq-section">', "<h4>❓ Questions fréquentes</h4>"]
    for item in faq_items:
        parties.append('<div class="faq-item">')
        parties.append(f'<div class="faq-question">{item.get("question", "")}</div>')
        parties.append(f'<div class="faq-answer">{item.get("answer", "")}</div>')
        parties.append("</div>")
    parties.append("</div>")
    return "\n".join(parties)


def build_cta_box(cta_titre, cta_texte):
    """Construit l'encadré CTA bleu de fin d'article, conforme à la classe
    CSS `cta-section` (spec août 2026) — pas l'ancienne `cta-box`.

    Seuls cta_titre et cta_texte varient (générés par le modèle, adaptés au
    sujet de l'article) — toute la structure HTML autour (balises, classe
    CSS, paragraphe de présentation, lien) est fixe et écrite ici, jamais
    produite par le modèle.
    """
    return (
        '<div class="cta-section">\n'
        f"<h3>{cta_titre}</h3>\n"
        f"<p>{cta_texte}</p>\n"
        "<p>Chez <strong>Decisions & Co</strong>, nous accompagnons les dirigeants dans "
        "l'adoption raisonnée et performante de ces nouvelles technologies IA.</p>\n"
        '<p><a href="/offres" class="internal-link">Découvrez notre diagnostic IA ROIste →</a></p>\n'
        "</div>"
    )


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
1. "corps_html" : le corps ci-dessus reformaté en HTML (pas de Markdown, pas de "#", pas de "**gras**" Markdown). Pas de <h1> (généré automatiquement par le site à partir du titre). Sections principales en <h2>, sous-sections éventuelles en <h3>. Paragraphes en <p>, emphase en <strong>/<em>. Guillemets français « » pour les citations ou expressions, apostrophes typographiques ' acceptées telles quelles.
   Tu peux utiliser AU MAXIMUM 2 encarts stylés au total parmi cette liste, et seulement s'ils s'imposent naturellement (jamais pour remplir) :
   - <div class="highlight-box"><p><strong>🎯 En bref :</strong> ...</p></div> — résumé d'ouverture, juste après le premier paragraphe
   - <div class="definition-box"><h4>💡 Définition : ...</h4><p>...</p></div> — pour définir un terme clé
   - <div class="expert-tip"><h4>💡 ...</h4><p>...</p></div> — conseil ou point d'attention
   - <div class="case-study"><h4>🎯 ...</h4><p>...</p></div> — exemple concret ou cas pratique
   N'invente aucun fait, aucun chiffre, aucune section nouvelle qui ne soit pas déjà dans le corps source.
2. "titre_site" : le titre "{package.get('titre', '')}" repris tel quel SAUF s'il dépasse 120 caractères, auquel cas raccourcis-le en préservant le sens (sinon renvoie-le identique).
3. "subtitle" : une phrase de valeur qui complète le titre, ton éditorial site web (pas une redite du chapo LinkedIn).
4. "description" : résumé de l'article en 2 phrases maximum, 600 caractères MAX — respecte strictement cette limite.
5. "category" : choisis EXACTEMENT une valeur parmi cette liste fermée, aucune autre valeur n'est acceptée : {json.dumps(CATEGORIES, ensure_ascii=False)}
6. "coverAlt" : description factuelle et accessible de l'image de couverture, une phrase, sans mentionner qu'elle est générée par IA.
7. "style_visuel" : choisis EXACTEMENT une valeur parmi cette liste fermée, celle qui convient le mieux au contenu de CET article précis (varie le choix d'un article à l'autre, ne reste pas systématiquement sur la même valeur) : {json.dumps(list(STYLES_VISUELS.keys()), ensure_ascii=False)}
   - "abstrait_conceptuel" : illustration abstraite épurée, fond sombre, formes géométriques
   - "photo_realiste" : photographie professionnelle réaliste (bureau, réunion), personnes anonymes non identifiables
   - "schema_technique" : schéma/diagramme technique propre, icônes et flèches, fond clair
   - "grille_icones" : collage d'icônes colorées représentant les concepts clés, fond clair
8. "image_prompt" : en anglais, 1 à 2 phrases, décrivant précisément le visuel à générer DANS LE STYLE CHOISI ci-dessus, cohérent avec le thème "{theme['theme']}". Pas de texte incrusté dans l'image. Si le style choisi est "photo_realiste", ne jamais décrire un visage identifiable en gros plan — uniquement des scènes génériques, de loin ou de dos.
9. "cta_titre" : une accroche courte (5 à 10 mots), avec un emoji au début, reliant le sujet précis de cet article à l'IA — formulée comme une question ou une invitation. Exemples de ton (ne pas copier) : "🚀 Vos processus sont-ils prêts pour l'IA agentique ?", "🚀 L'IA Agent : votre prochain avantage concurrentiel ?"
10. "cta_texte" : 1 à 2 phrases qui relient le sujet précis de cet article à l'accompagnement Decisions & Co, SANS répéter mot à mot une phrase déjà présente dans le corps.
11. "faq" : une liste de 0 à 3 paires question/réponse SEULEMENT si le sujet de l'article s'y prête vraiment naturellement (questions qu'un dirigeant se poserait concrètement en lisant cet article précis) — sinon renvoie une liste vide []. Format : [{{"question":"...","answer":"..."}}]. Ne réponds jamais par une évidence ou une reformulation du titre.

Réponds UNIQUEMENT en JSON valide, sans markdown autour :
{{"corps_html":"...","titre_site":"...","subtitle":"...","description":"...","category":"...","coverAlt":"...","style_visuel":"...","image_prompt":"...","cta_titre":"...","cta_texte":"...","faq":[]}}
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
        data["_category_fallback"] = True

    if data.get("style_visuel") not in STYLES_VISUELS:
        print(f"Style visuel renvoyé invalide ({data.get('style_visuel')!r}) — repli sur {DEFAULT_STYLE!r}.")
        data["style_visuel"] = DEFAULT_STYLE
        data["_style_fallback"] = True

    if len(data.get("description", "")) > 600:
        data["description"] = data["description"][:597].rstrip() + "..."
        data["_description_truncated"] = True

    if len(data.get("titre_site", "")) > 120:
        data["titre_site"] = data["titre_site"][:117].rstrip() + "..."
        data["_titre_truncated"] = True

    faq_brute = data.get("faq", [])
    if not isinstance(faq_brute, list):
        print(f"Champ faq renvoyé invalide (pas une liste) — ignoré, aucune FAQ pour cet article.")
        data["faq"] = []
        data["_faq_malformee"] = True
    else:
        faq_valides = [
            item for item in faq_brute
            if isinstance(item, dict) and item.get("question", "").strip() and item.get("answer", "").strip()
        ]
        if len(faq_valides) != len(faq_brute):
            data["_faq_malformee"] = True
        data["faq"] = faq_valides[:3]

    return data


# Motifs qui trahissent une génération incomplète ou un texte non nettoyé.
# Phrases longues : recherche en sous-chaîne, aucun risque de faux positif.
PLACEHOLDER_PHRASES = [
    "à compléter", "a completer", "lorem ipsum", "[insérer", "[insert", "placeholder",
]
# Tokens courts/génériques : recherche en mot entier uniquement (\b...\b),
# sinon un mot ordinaire contenant ces lettres par hasard déclencherait un
# faux positif (ex. "xxx" en sous-chaîne d'un mot quelconque).
PLACEHOLDER_TOKENS = ["todo", "tbd", "xxx"]


def detect_anomalies(site_data, package):
    """Liste les raisons de ne PAS merger automatiquement la PR.

    Liste vide = publication automatique. Sinon, la PR reste ouverte pour
    relecture humaine et reçoit un commentaire listant ces anomalies.
    """
    anomalies = []

    if site_data.get("_category_fallback"):
        anomalies.append(
            f"Catégorie renvoyée par le modèle invalide — repli automatique sur {DEFAULT_CATEGORY!r}, à vérifier."
        )
    if site_data.get("_style_fallback"):
        anomalies.append(
            f"Style visuel renvoyé par le modèle invalide — repli automatique sur {DEFAULT_STYLE!r}, à vérifier."
        )
    if site_data.get("_description_truncated"):
        anomalies.append("Description tronquée automatiquement (dépassait 600 caractères) — relecture recommandée.")
    if site_data.get("_titre_truncated"):
        anomalies.append("Titre tronqué automatiquement (dépassait 120 caractères) — relecture recommandée.")
    if site_data.get("_faq_malformee"):
        anomalies.append("Au moins une entrée FAQ renvoyée par le modèle était malformée — ignorée, à vérifier si la FAQ restante a du sens.")

    if not site_data.get("subtitle", "").strip():
        anomalies.append("Subtitle manquant ou vide.")
    if not site_data.get("description", "").strip():
        anomalies.append("Description manquante ou vide.")
    if not site_data.get("cta_titre", "").strip() or not site_data.get("cta_texte", "").strip():
        anomalies.append("Titre ou texte du CTA de fin d'article manquant ou vide.")

    corps = site_data.get("corps_html", "")
    if len(corps) < 400:
        anomalies.append(f"Corps HTML anormalement court ({len(corps)} caractères) — génération probablement incomplète.")

    corps_lower = corps.lower()
    for motif in PLACEHOLDER_PHRASES:
        if motif in corps_lower:
            anomalies.append(f"Texte suspect détecté dans le corps : {motif!r}.")
    for motif in PLACEHOLDER_TOKENS:
        if re.search(rf"\b{re.escape(motif)}\b", corps_lower):
            anomalies.append(f"Texte suspect détecté dans le corps : {motif!r}.")

    for tag in ("h2", "p", "div"):
        ouvrantes = corps.count(f"<{tag}")
        fermantes = corps.count(f"</{tag}>")
        if ouvrantes != fermantes:
            anomalies.append(
                f"Balises <{tag}> déséquilibrées ({ouvrantes} ouvrantes / {fermantes} fermantes) — HTML potentiellement invalide."
            )

    return anomalies


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
        f'title: "{_echapper(site_data.get("titre_site") or package.get("titre", ""))}"',
        f'subtitle: "{_echapper(site_data.get("subtitle", ""))}"',
        f'description: "{_echapper(site_data.get("description", ""))}"',
        f"publishedAt: {date_slug}",
        f'category: "{site_data.get("category", DEFAULT_CATEGORY)}"',
        f'cover: "/images/content/{slug}.webp"',
        f'coverAlt: "{_echapper(site_data.get("coverAlt", ""))}"',
        "featured: false",
        "draft: false",
    ]
    faq_items = site_data.get("faq", [])
    faq_yaml = build_faq_yaml(faq_items)
    if faq_yaml:
        lignes.append(faq_yaml)
    lignes += ["---", ""]

    faq_html = build_faq_html(faq_items)
    corps_complet = site_data.get("corps_html", "")
    if faq_html:
        corps_complet += "\n\n" + faq_html
    corps_complet += (
        "\n\n"
        + build_cta_box(site_data.get("cta_titre", ""), site_data.get("cta_texte", ""))
        + "\n\n"
        + ABOUT_BOX
    )
    return "\n".join(lignes) + corps_complet


def notify_make_alerte(pr_url, anomalies, package, theme, date_slug):
    """Envoie une alerte email via le même webhook Make que le brouillon
    hebdo (notify_make_email dans agent_article_hebdo.py), avec un type de
    payload distinct ("alerte_site") pour que le Router Make puisse la
    distinguer des branches existantes.

    ⚠️ Cette fonction envoie le payload ; côté Make, une branche dédiée à
    ce type ("alerte_site") doit être ajoutée au scénario existant (filtre
    sur type = alerte_site → email) pour qu'un email soit effectivement
    envoyé. Tant que ce filtre n'existe pas, le webhook recevra bien le
    payload mais aucune action Make ne se déclenchera derrière.
    """
    if not MAKE_WEBHOOK_URL or not MAKE_API_KEY:
        print("MAKE_WEBHOOK_URL / MAKE_API_KEY absents — alerte non envoyée.")
        return

    payload = {
        "type": "alerte_site",
        "date": date_slug,
        "theme": theme.get("theme", ""),
        "titre": package.get("titre", ""),
        "pr_url": pr_url,
        "anomalies": anomalies,
    }

    if DRY_RUN:
        print(f"[DRY_RUN] Alerte non envoyée. {len(anomalies)} anomalie(s) — PR : {pr_url}")
        return

    resp = requests.post(
        MAKE_WEBHOOK_URL,
        headers={"x-make-apikey": MAKE_API_KEY},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    print(f"Alerte anomalie notifiée via Make : {resp.status_code}")


def _load_known_urls():
    try:
        with open(KNOWN_URLS_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_known_urls(urls):
    os.makedirs("articles", exist_ok=True)
    with open(KNOWN_URLS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(urls), f, ensure_ascii=False, indent=2)


def _attendre_deploiement(url, tentatives=15, pause=12):
    """Poll l'URL jusqu'à 200, jusqu'à ~3 minutes — même ordre de grandeur
    que la latence de déploiement déjà observée en pratique (build + rsync
    via deploy.yml)."""
    for _ in range(tentatives):
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(pause)
    return False


def generate_teaser_linkedin(titre, description, category, article_url):
    system = f"""Tu es l'agent éditorial de Décisions & Co (D&Co). Tu rédiges un post LinkedIn COURT (pas un article) qui donne envie de lire un article déjà publié sur le site D&Co.

## Article concerné
Titre : {titre}
Description : {description}
Catégorie : {category}
URL : {article_url}

RÈGLES :
1. 3 à 5 phrases maximum, format post LinkedIn (pas de titre, pas de markdown).
2. Accroche forte dès la première phrase — pas de "Découvrez notre nouvel article".
3. Donne un aperçu concret de l'angle de l'article, pas juste son titre reformulé.
4. Termine par une invitation claire à cliquer sur le lien (le lien lui-même sera ajouté séparément, ne l'écris pas dans le texte).
5. Jamais : révolution, disruptif, écosystème, synergies, "Dans un monde où".

Génère UNIQUEMENT un JSON valide, sans markdown autour :
{{"post_linkedin":"...","sujet":"..."}}
Échappe les guillemets avec \\" et les sauts de ligne avec \\n."""

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": ANTHROPIC_API_KEY,
        },
        json={
            "model": MODEL,
            "max_tokens": 1000,
            "system": system,
            "messages": [{"role": "user", "content": f'Génère le teaser pour l\'article "{titre}".'}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    raw = next((b["text"] for b in resp.json()["content"] if b["type"] == "text"), "")
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    package = json.loads(raw)
    package["post_linkedin"] = f"{package.get('post_linkedin', '')}\n\n{article_url}"
    return package


def notify_make_teaser(package, category, image_url, date_slug):
    """Même format de payload que agent_article_teaser_auto.py (post_x,
    post_linkedin, image_url, has_image) — SANS champ "type", pour retomber
    sur la route fallback déjà configurée dans le Router Make, sans rien
    ajouter côté Make."""
    resp = requests.post(
        MAKE_WEBHOOK_URL,
        headers={"x-make-apikey": MAKE_API_KEY},
        json={
            "sujet": package.get("sujet", ""),
            "post_linkedin": package.get("post_linkedin", ""),
            "post_x": "",
            "theme": category,
            "date": date_slug,
            "image_url": image_url,
            "has_image": bool(image_url),
        },
        timeout=15,
    )
    resp.raise_for_status()
    print(f"Teaser notifié via Make : {resp.status_code}")


def trigger_teaser_apres_publication(package, site_data, slug, date_slug):
    """Déclenche le teaser LinkedIn juste après un merge automatique
    réussi — pas de scraping, pas d'attente du lendemain : le slug, le
    titre et la catégorie sont déjà connus à cet instant précis.
    """
    if DRY_RUN:
        print("[DRY_RUN] Teaser LinkedIn non déclenché.")
        return

    article_url = f"{SITE_ARTICLE_BASE}/{slug}"
    image_url = f"{SITE_IMAGE_BASE}/{slug}.webp"

    print(f"Attente du déploiement de l'article ({article_url})...")
    if not _attendre_deploiement(article_url):
        print("Article pas encore déployé après l'attente — teaser sauté, le scraper quotidien le rattrapera demain.")
        return

    print("Article déployé — génération du teaser LinkedIn...")
    titre = site_data.get("titre_site") or package.get("titre", "")
    teaser_pkg = generate_teaser_linkedin(
        titre, site_data.get("description", ""), site_data.get("category", ""), article_url
    )
    notify_make_teaser(teaser_pkg, site_data.get("category", ""), image_url, date_slug)

    connues = _load_known_urls()
    connues.add(article_url)
    _save_known_urls(connues)
    print(f"{article_url} ajouté à {KNOWN_URLS_PATH} (évite un double teaser via le scraper quotidien).")


def merge_pr(pr_number, branch):
    """Merge la PR automatiquement (squash), puis supprime la branche.

    GitHub calcule le statut "mergeable" de façon asynchrone juste après la
    création de la PR : un retry court absorbe le cas où l'appel arrive
    avant que ce calcul soit terminé.
    """
    derniere_erreur = None
    for tentative in range(3):
        try:
            resp = requests.put(
                f"https://api.github.com/repos/{SITE_REPO}/pulls/{pr_number}/merge",
                headers={
                    "Authorization": f"Bearer {SITE_REPO_PAT}",
                    "Accept": "application/vnd.github+json",
                },
                json={"merge_method": "squash"},
                timeout=30,
            )
            resp.raise_for_status()
            print("PR mergée automatiquement — le déploiement va se déclencher.")
            break
        except requests.HTTPError as e:
            derniere_erreur = e
            time.sleep(3)
    else:
        raise derniere_erreur

    # Best-effort : supprime la branche mergée sans faire échouer le run si
    # ça rate (ce n'est qu'un ménage, pas une étape critique).
    try:
        requests.delete(
            f"https://api.github.com/repos/{SITE_REPO}/git/refs/heads/{branch}",
            headers={"Authorization": f"Bearer {SITE_REPO_PAT}"},
            timeout=15,
        )
    except Exception:
        pass


def comment_pr(pr_number, anomalies):
    body = (
        "⚠️ **Publication automatique interrompue avant merge** — anomalie(s) détectée(s), relecture nécessaire :\n\n"
        + "\n".join(f"- {a}" for a in anomalies)
    )
    resp = requests.post(
        f"https://api.github.com/repos/{SITE_REPO}/issues/{pr_number}/comments",
        headers={
            "Authorization": f"Bearer {SITE_REPO_PAT}",
            "Accept": "application/vnd.github+json",
        },
        json={"body": body},
        timeout=15,
    )
    resp.raise_for_status()


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
        anomalies_preview = detect_anomalies(site_data, package)
        print(f"[DRY_RUN] Branche prévue : {branch}")
        if anomalies_preview:
            print("[DRY_RUN] Anomalies qui déclencheraient une escalade (PR ouverte + alerte email) :")
            for a in anomalies_preview:
                print(f"  - {a}")
        else:
            print("[DRY_RUN] Aucune anomalie — la PR aurait été mergée automatiquement.")
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
    anomalies = detect_anomalies(site_data, package)
    corps_pr = (
        f"Article généré automatiquement — thème « {theme['theme']} ».\n\n"
        f"**Catégorie proposée :** {site_data.get('category')}\n\n"
        f"**Style visuel :** {site_data.get('style_visuel')}\n\n"
    )
    if anomalies:
        corps_pr += (
            "⚠️ Anomalie(s) détectée(s) — merge automatique désactivé pour cette PR, "
            "relecture nécessaire avant merge manuel (voir commentaire ci-dessous)."
        )
    else:
        corps_pr += (
            "Aucune anomalie détectée — cette PR sera mergée automatiquement. "
            "Le déploiement (build + rsync) se déclenche alors immédiatement."
        )

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
            "body": corps_pr,
        },
        timeout=30,
    )
    pr_resp.raise_for_status()
    pr_data = pr_resp.json()
    pr_url = pr_data.get("html_url", "")
    pr_number = pr_data.get("number")
    print(f"PR ouverte : {pr_url}")

    if anomalies:
        print("Anomalies détectées — la PR reste ouverte pour relecture :")
        for a in anomalies:
            print(f"  - {a}")
        try:
            comment_pr(pr_number, anomalies)
        except Exception as e:
            print(f"Impossible de commenter la PR (elle reste ouverte quand même) : {e}")
        if ALERTE_EMAIL_SITE:
            try:
                notify_make_alerte(pr_url, anomalies, package, theme, date_slug)
            except Exception as e:
                print(f"Alerte email impossible (la PR reste quand même ouverte) : {e}")
        else:
            print("Alerte email désactivée (ALERTE_EMAIL_SITE non activé) — le commentaire sur la PR reste le seul signal.")
    else:
        print("Aucune anomalie détectée — merge automatique...")
        try:
            merge_pr(pr_number, branch)
        except Exception as e:
            print(f"Merge automatique impossible, la PR reste ouverte pour merge manuel : {e}")
            return pr_url  # pas de teaser si le merge n'a pas eu lieu

        try:
            trigger_teaser_apres_publication(package, site_data, slug, date_slug)
        except Exception as e:
            print(f"Déclenchement du teaser impossible (l'article reste publié normalement) : {e}")

    return pr_url
