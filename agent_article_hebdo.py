#!/usr/bin/env python3
"""Agent éditorial D&Co — génération hebdomadaire d'un brouillon d'article LinkedIn.

Contrairement à agent.py (posts quotidiens, publication directe sur X et
LinkedIn) et agent_weekend_agentique.py (variante agentique du même flux),
ce script ne publie JAMAIS rien sur LinkedIn.

Pourquoi : LinkedIn ne propose aucune API publique pour créer un article
long format (Pulse, avec titre + image de couverture + corps riche). Seule
l'interface web permet de le faire. Automatiser cette étape reviendrait à
piloter un navigateur pour imiter un humain sur l'interface LinkedIn — un
usage que les CGU LinkedIn interdisent et que leurs systèmes anti-bot sont
conçus pour détecter, avec un risque de restriction de compte disproportionné
par rapport au gain.

Ce script s'arrête donc volontairement avant la publication : il génère le
titre, le corps et le visuel de couverture, les commit dans le repo pour
archive, et envoie le tout par email via Make. Philippe copie-colle ensuite
manuellement dans l'éditeur LinkedIn (2 minutes, zéro exposition).

Déclenché par .github/workflows/publish-article-hebdo.yml, chaque mercredi.
Réutilise les briques techniques d'agent.py (KB, palette visuelle, logo,
nettoyage de texte) — seule la couche génération longue + email diffère.
"""

import os
import json
import base64
import re
from datetime import datetime
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import requests

from agent import (
    KB,
    SIGNATURE,
    today_label,
    nettoyer_texte,
    wrap_text,
    hex_to_rgb,
    recolor_logo,
    LOGO_PATH,
    THEME_PALETTES,
    THEME_LABELS,
    THEME_ASSETS,
)

# --- Config ---
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
# Réutilise le webhook LinkedIn existant (même secret que agent.py) plutôt
# qu'un webhook dédié : un seul scénario Make gère les deux flux, distingués
# en aval par un Router sur la présence du champ "titre" (propre aux
# articles) vs "post_linkedin" (propre aux posts quotidiens). Évite de
# consommer un 2e/3e scénario actif sur un plan Make à quota limité.
MAKE_WEBHOOK_URL = os.environ["MAKE_WEBHOOK_URL"]
MAKE_API_KEY = os.environ["MAKE_API_KEY"]

MODEL = "claude-sonnet-4-6"
HISTORIQUE_DIR = "articles"
HISTORIQUE_PATH = f"{HISTORIQUE_DIR}/historique_articles.json"

# Mode test : DRY_RUN=true déroule tout le pipeline (génération, visuel, commit)
# mais n'envoie pas l'email — utile pour vérifier le rendu sans solliciter Make.
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

# Rotation hebdomadaire déterministe sur 5 thèmes de fond — les mêmes thèmes
# que les posts quotidiens (agenda_hebdo dans agent.py), traités ici en
# profondeur plutôt qu'en accroche courte. Réutilise donc directement les
# palettes, labels et visuels associés à ces thèmes (THEME_PALETTES etc.),
# sans les redéfinir.
ARTICLE_THEMES = [
    {
        "theme": "L'Entreprise OS",
        "instruction": (
            "Développe en profondeur le concept d'Entreprise OS : pourquoi le "
            "système d'information traditionnel ne suffit plus, les trois "
            "fonctions (Stocker / Traiter / Diffuser), et un exemple structuré "
            "de mise en œuvre chez une PME ou une ETI."
        ),
    },
    {
        "theme": "Méthode Cartographier → Éliciter → Codifier",
        "instruction": (
            "Développe la méthodologie D&Co étape par étape : ce qui se passe "
            "concrètement à chaque phase, les pièges les plus fréquents, et "
            "pourquoi l'ordre des trois étapes n'est pas négociable."
        ),
    },
    {
        "theme": "Gouvernance et réglementation IA",
        "instruction": (
            "Prends un sujet de gouvernance ou de réglementation IA (AI Act, "
            "RGPD, charte IA interne) et explique en profondeur ce que ça "
            "implique concrètement pour une PME ou une ETI, sans jargon "
            "juridique, avec un plan d'action lisible."
        ),
    },
    {
        "theme": "Terrain et missions clients",
        "instruction": (
            "Développe un retour d'expérience terrain anonymisé, en "
            "profondeur : contexte, difficulté rencontrée, décision prise, "
            "résultat obtenu. Format étude de cas, sans jamais nommer le client."
        ),
    },
    {
        "theme": "Formation et culture IA",
        "instruction": (
            "Développe pourquoi la formation IA échoue souvent en entreprise, "
            "ce qui la rend réellement efficace, et une trajectoire réaliste "
            "de montée en compétence collective."
        ),
    },
]


def get_theme_semaine(historique):
    """Rotation déterministe sur le numéro de semaine ISO.

    Garde-fou : si le thème calculé a déjà été traité lors des deux derniers
    articles (semaine sautée, rattrapage manuel...), on passe au suivant du
    cycle plutôt que de répéter.
    """
    semaine = datetime.now().isocalendar()[1]
    idx = semaine % len(ARTICLE_THEMES)
    theme = ARTICLE_THEMES[idx]
    recents = {h.get("theme") for h in historique[-2:]}
    if theme["theme"] in recents:
        idx = (idx + 1) % len(ARTICLE_THEMES)
        theme = ARTICLE_THEMES[idx]
    return theme


def load_historique():
    try:
        with open(HISTORIQUE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_historique(historique, entry):
    historique.append(entry)
    historique = historique[-20:]
    os.makedirs(HISTORIQUE_DIR, exist_ok=True)
    with open(HISTORIQUE_PATH, "w", encoding="utf-8") as f:
        json.dump(historique, f, ensure_ascii=False, indent=2)


def build_system_prompt(historique, theme):
    deja = [h for h in historique[-8:] if h.get("theme") == theme["theme"]]
    if deja:
        recents = "\n".join(
            f"- {h.get('date', '?')} : {h.get('titre', '')}" for h in deja
        )
        hist_txt = (
            f"\n## Articles déjà publiés sur ce thème (angle DIFFÉRENT obligatoire)\n"
            f"{recents}\n"
        )
    else:
        hist_txt = "\n## Premier article sur ce thème.\n"

    return f"""Tu es l'agent éditorial de Décisions & Co (D&Co). Tu rédiges cette fois un ARTICLE LinkedIn long format (pas un post court).

{KB}
{hist_txt}
## THÈME DE LA SEMAINE : {theme['theme']}
{theme['instruction']}

RÈGLES ÉDITORIALES :
1. Format article long : 700 à 1100 mots, plusieurs sections.
2. Chaque section commence par une ligne de titre courte (3 à 6 mots, sans numérotation, sans #), suivie d'un saut de ligne, puis le paragraphe.
3. Accroche forte dans les 2 premières phrases : donne envie de lire la suite.
4. Conclusion avec une ouverture ou une question, jamais un simple résumé plat.
5. Jamais : révolution, disruptif, écosystème, synergies, "Dans un monde où".
6. Pas de promotion directe des offres D&Co : un article installe la confiance, il ne vend pas.
7. AUCUN markdown : pas de **gras**, pas de #titres. Les titres de section sont de simples lignes courtes isolées par un saut de ligne — LinkedIn n'interprète pas le markdown et afficherait les astérisques en clair.
8. Signature en toute fin d'article, sur sa propre ligne : "{SIGNATURE}"

Génère UNIQUEMENT un JSON valide, sans markdown autour :
{{"titre":"...","chapo":"...","corps":"...","hashtags":"#tag1 #tag2 #tag3"}}

- titre : 6 à 12 mots, percutant, sans point final
- chapo : 1 à 2 phrases d'accroche (150 caractères max), affichées sous le titre
- corps : texte complet de l'article, paragraphes et sections séparés par \\n\\n
- hashtags : 3 à 5 hashtags pertinents pour le thème
- Échapper les guillemets avec \\" et les sauts de ligne avec \\n"""


def generate_article(historique, theme):
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
            "system": build_system_prompt(historique, theme),
            "messages": [{
                "role": "user",
                "content": f"Génère l'article. Date : {today_label()}. Thème : {theme['theme']}.",
            }],
        },
        timeout=90,
    )
    if resp.status_code >= 400:
        print(f"[ERREUR API] Statut HTTP {resp.status_code} sur generate_article")
        print(f"[ERREUR API] Corps de la réponse : {resp.text[:2000]}")
    resp.raise_for_status()
    data = resp.json()
    raw = next((b["text"] for b in data["content"] if b["type"] == "text"), "")
    raw = raw.replace("```json", "").replace("```", "").strip()
    package = json.loads(raw)
    for champ in ("titre", "chapo", "corps"):
        if champ in package:
            package[champ] = nettoyer_texte(package[champ])
    return package


def generate_cover(titre, theme, chapo=""):
    """Génère un visuel de couverture 1200x627 (format recommandé LinkedIn
    Article) — reprend la charte visuelle des posts quotidiens (palette,
    logo recoloré) mais avec une mise en page dédiée au titre long."""
    W, H = 1200, 627
    palette = THEME_PALETTES.get(theme, THEME_PALETTES["L'Entreprise OS"])
    asset_path = THEME_ASSETS.get(theme, THEME_ASSETS["L'Entreprise OS"])

    try:
        photo = Image.open(asset_path).convert("RGBA")
    except Exception:
        photo = Image.new("RGBA", (W, H), (20, 20, 40, 255))
    photo = photo.resize((W, H), Image.LANCZOS)
    photo = photo.filter(ImageFilter.GaussianBlur(radius=3))

    r, g, b, a = palette["overlay"]
    overlay = Image.new("RGBA", (W, H), (r, g, b, min(a + 20, 235)))
    img = Image.alpha_composite(photo, overlay).convert("RGB")

    gradient = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(gradient)
    for y in range(H // 2):
        alpha = int(150 * (1 - y / (H // 2)))
        g_draw.line([(0, H - y - 1), (W, H - y - 1)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), gradient).convert("RGB")

    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 50)
        font_chapo = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        font_tag = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 17)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except Exception:
        font_title = font_chapo = font_tag = font_small = ImageFont.load_default()

    accent_rgb = hex_to_rgb(palette["accent"])

    # Pill thème en haut à gauche
    label = THEME_LABELS.get(theme, theme[:20].upper())
    tag_bbox = draw.textbbox((0, 0), label, font=font_tag)
    tag_w = tag_bbox[2] - tag_bbox[0] + 28
    tag_h_px = tag_bbox[3] - tag_bbox[1] + 14
    tag_bg_rgb = hex_to_rgb(palette["tag_bg"])
    draw.rounded_rectangle([50, 44, 50 + tag_w, 44 + tag_h_px], radius=6, fill=tag_bg_rgb)
    tag_fg_rgb = hex_to_rgb(palette["tag_fg"])
    draw.text((64, 51), label, fill=tag_fg_rgb, font=font_tag)

    # Titre, bas de l'image, ligne d'accent à gauche
    lines = wrap_text(draw, titre, font_title, 1080)[:4]
    line_h = 60
    total_h = len(lines) * line_h
    y_start = H - total_h - 130

    draw.rectangle([50, y_start - 10, 57, y_start + total_h + 10], fill=accent_rgb)

    for i, line in enumerate(lines):
        y = y_start + i * line_h
        draw.text((83, y + 2), line, fill=(0, 0, 0, 180), font=font_title)
        draw.text((80, y), line, fill="#ffffff", font=font_title)

    if chapo:
        chapo_lines = wrap_text(draw, chapo, font_chapo, 1080)[:2]
        cy = y_start + total_h + 20
        for line in chapo_lines:
            draw.text((80, cy), line, fill=(225, 225, 225), font=font_chapo)
            cy += 32

    # Logo bas à gauche, recoloré à la teinte du thème
    try:
        logo_raw = Image.open(LOGO_PATH).convert("RGBA")
        logo_w = 140
        logo_h = int(logo_w * logo_raw.size[1] / logo_raw.size[0])
        logo_tinted = recolor_logo(logo_raw, accent_rgb).resize((logo_w, logo_h), Image.LANCZOS)
        logo_y = H - logo_h - 26
        img.paste(logo_tinted, (50, logo_y), logo_tinted)
        draw.text((50 + logo_w + 16, logo_y + (logo_h - 16) // 2), "decisionsandco.com", fill=(220, 220, 220), font=font_small)
    except Exception:
        draw.text((50, H - 40), "DÉCISIONS & CO", fill=accent_rgb, font=font_small)

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def slugify(titre):
    slug = titre.lower()
    slug = re.sub(r"[àâä]", "a", slug)
    slug = re.sub(r"[éèêë]", "e", slug)
    slug = re.sub(r"[îï]", "i", slug)
    slug = re.sub(r"[ôö]", "o", slug)
    slug = re.sub(r"[ùûü]", "u", slug)
    slug = re.sub(r"ç", "c", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug[:60]


def write_draft_files(package, image_buf, date_slug, slug):
    dossier = f"{HISTORIQUE_DIR}/drafts/{date_slug}-{slug}"
    os.makedirs(dossier, exist_ok=True)

    md_path = f"{dossier}/article.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {package['titre']}\n\n")
        f.write(f"*{package.get('chapo', '')}*\n\n")
        f.write(f"{package['corps']}\n\n")
        f.write(f"{package.get('hashtags', '')}\n")

    img_path = f"{dossier}/cover.png"
    image_buf.seek(0)
    with open(img_path, "wb") as f:
        f.write(image_buf.read())
    image_buf.seek(0)

    return dossier, md_path, img_path


def git_commit_push(paths, message):
    try:
        import subprocess

        def run(*args):
            return subprocess.run(args, check=True, capture_output=True, text=True)

        run("git", "config", "user.name", "agent-editorial-dco")
        run("git", "config", "user.email", "agent@decisionsandco.com")
        run("git", "add", *paths)

        statut = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
        if statut.returncode == 0:
            print("Rien à committer.")
            return False

        run("git", "commit", "-m", message)
        run("git", "push")
        print("Brouillon d'article commité et poussé.")
        return True
    except Exception as e:
        detail = getattr(e, "stderr", "") or str(e)
        print(f"Commit/push impossible : {detail}")
        return False


def notify_make_email(package, theme, image_buf, dossier):
    """Envoie le brouillon complet par email via le webhook Make existant —
    titre, chapo, corps, hashtags, et le visuel de couverture en pièce jointe
    (base64). Le champ "titre" est ce qui permet au Router du scénario Make
    de distinguer ce payload de celui des posts quotidiens (qui portent
    "post_linkedin" mais jamais "titre") et de le router vers la branche email
    plutôt que vers la branche de publication LinkedIn.

    Contrairement au webhook des posts quotidiens, celui-ci n'a besoin
    d'aucune URL publique pour l'image : elle voyage directement dans le
    payload, donc pas d'attente de déploiement GitHub Pages.
    """
    image_buf.seek(0)
    image_b64 = base64.b64encode(image_buf.read()).decode("utf-8")
    image_buf.seek(0)

    payload = {
        "type": "article",
        "date": today_label(),
        "theme": theme["theme"],
        "titre": package.get("titre", ""),
        "chapo": package.get("chapo", ""),
        "corps": package.get("corps", ""),
        "hashtags": package.get("hashtags", ""),
        "cover_filename": "cover.png",
        "cover_base64": image_b64,
        "repo_path": dossier,
    }

    if DRY_RUN:
        print(f"[DRY_RUN] Email non envoyé. Payload prêt ({len(image_b64)} caractères d'image base64).")
        return

    resp = requests.post(
        MAKE_WEBHOOK_URL,
        headers={"x-make-apikey": MAKE_API_KEY},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    print(f"Email notifié via Make : {resp.status_code}")


def main():
    print(f"Agent éditorial D&Co — brouillon article hebdomadaire — {today_label()}")

    historique = load_historique()
    print(f"Historique : {len(historique)} articles")

    theme = get_theme_semaine(historique)
    print(f"Thème de la semaine : {theme['theme']}")

    print("Génération de l'article...")
    package = generate_article(historique, theme)
    print(f"Titre : {package.get('titre')}")

    print("Génération du visuel de couverture...")
    image_buf = generate_cover(
        titre=package.get("titre", ""),
        theme=theme["theme"],
        chapo=package.get("chapo", ""),
    )

    date_slug = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(package.get("titre", "article"))
    dossier, md_path, img_path = write_draft_files(package, image_buf, date_slug, slug)
    print(f"Brouillon écrit dans {dossier}")

    print("Commit du brouillon...")
    git_commit_push([md_path, img_path], f"Brouillon article LinkedIn du {date_slug} — {package.get('titre', '')}")

    print("Envoi du brouillon par email via Make...")
    notify_make_email(package, theme, image_buf, dossier)

    save_historique(historique, {
        "date": today_label(),
        "timestamp": datetime.now().isoformat(),
        "theme": theme["theme"],
        "titre": package.get("titre", ""),
        "dossier": dossier,
    })
    print("Terminé. Aucune publication LinkedIn effectuée — brouillon en attente de votre validation.")


if __name__ == "__main__":
    main()
