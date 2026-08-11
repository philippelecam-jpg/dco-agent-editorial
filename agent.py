#!/usr/bin/env python3
"""Agent éditorial Décisions & Co — génère, illustre et publie le post X quotidien."""

import os
import json
import re
import textwrap
import requests
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from requests_oauthlib import OAuth1

# --- Config ---
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
X_API_KEY = os.environ["X_API_KEY"]
X_API_SECRET = os.environ["X_API_SECRET"]
X_ACCESS_TOKEN = os.environ["X_ACCESS_TOKEN"]
X_ACCESS_SECRET = os.environ["X_ACCESS_SECRET"]

DAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin",
             "juillet", "août", "septembre", "octobre", "novembre", "décembre"]

# Rotation forcée par jour de semaine
AGENDA_HEBDO = {
    0: {
        "theme": "L'Entreprise OS",
        "instruction": "Traite exclusivement le concept d'Entreprise OS de D&Co — ce que c'est, pourquoi c'est le nouveau système d'exploitation de l'organisation, une de ses trois fonctions (Stocker / Traiter / Diffuser), ou un exemple concret d'application."
    },
    1: {
        "theme": "Terrain et missions clients",
        "instruction": "Traite un retour terrain anonymisé d'une mission D&Co, ou une situation concrète observée chez un client PME/ETI face à l'IA. Sois concret, factuel, sans nommer le client."
    },
    2: {
        "theme": "Méthode Cartographier → Éliciter → Codifier",
        "instruction": "Traite exclusivement la méthodologie D&Co — une des trois étapes, un exemple de ce qu'on trouve quand on cartographie, ce que ça change d'éliciter avant de déployer, ou pourquoi codifier n'est pas du développement logiciel."
    },
    3: {
        "theme": "Gouvernance et réglementation IA",
        "instruction": "Traite la gouvernance IA, la conformité, ou la réglementation (AI Act, RGPD) avec l'angle D&Co : pas de panique, pas de jargon, juste ce que ça change concrètement pour une PME. Si une actualité réglementaire du jour est pertinente, exploite-la."
    },
    4: {
        "theme": "Formation et culture IA",
        "instruction": "Traite la formation IA, la culture IA en entreprise, ou le fossé entre l'enthousiasme IA et la transformation réelle. Ce que la formation change — ou ne change pas — quand elle est mal conçue."
    },
}

KB = """# Knowledge Base — Décisions & Co

## Qui est D&Co
Cabinet de conseil en transformation IA, Nantes + Paris (Île Saint-Louis).
Fondateurs : Philippe Le Cam (président) et Christophe Rozuel.
Équipe : Mélanie Nauleau (formation), Thomas Royer (ingénieur IA), Nolan Deïs (consultant).

## Raison d'être
Aider les PME et ETI françaises (50–2000 collaborateurs) à traverser la transformation IA
sans se perdre dans les outils. On ne vend pas de l'IA.
On prépare les organisations à l'accueillir.

## Conviction centrale
L'IA est un amplificateur. Elle amplifie ce qui existe.
Une organisation qui déploie l'IA sans avoir structuré sa connaissance
n'accélère pas sa performance — elle accélère son désordre.
La préparation précède le déploiement. Toujours.

## L'Entreprise OS
Concept central D&Co. Le nouveau système d'exploitation de l'organisation à l'ère de l'IA.
Trois fonctions : Stocker (connaissance métier gouvernée), Traiter (décisions et processus augmentés),
Diffuser (livrables et communications). Remplace progressivement le SI traditionnel.

## Méthodologie : Cartographier → Éliciter → Codifier
1. Cartographier — comprendre avant de toucher à quoi que ce soit
2. Éliciter — faire sortir la connaissance implicite des têtes
3. Codifier — ancrer la connaissance dans des systèmes durables
C'est une boucle, pas une ligne droite.

## Offre — 4 piliers
1. Conseil en transformation IA (1 150€/j)
2. Formation (Mélanie Nauleau)
3. Développement de solutions IA (Thomas Royer)
4. Gouvernance IA (chartes, AI Act, RGPD)
Produits : Diagnostic IA (5–15k€), Charte IA, Copilot Décisionnel v8cockpit (8 500€ + 900€/mois/15 users)

## Cibles
DG/Dirigeant (interlocuteur idéal), DAF, DRH, DSI.
Secteurs : industrie, transport, services, secteur public.

## Ton
Direct. Ancré. Concret. Exigeant sans être arrogant.
Phrases courtes. Une idée par phrase.
Mots interdits : révolution, disruptif, écosystème, synergies,
"Dans un monde où", "L'IA change tout".
Mots D&Co : matière, connaissance, gouvernance, structurer, codifier, ancrer.
"""

# --- Palettes visuelles par thème ---
THEME_STYLES = {
    "L'Entreprise OS":                    {"accent": "#c8a96e", "label_color": "#c8a96e"},
    "Terrain et missions clients":         {"accent": "#6eb5c8", "label_color": "#6eb5c8"},
    "Méthode Cartographier → Éliciter → Codifier": {"accent": "#6ec88a", "label_color": "#6ec88a"},
    "Gouvernance et réglementation IA":    {"accent": "#c86e6e", "label_color": "#c86e6e"},
    "Formation et culture IA":             {"accent": "#a06ec8", "label_color": "#a06ec8"},
}


def today_label():
    d = datetime.now()
    return f"{DAYS_FR[d.weekday()]} {d.day} {MONTHS_FR[d.month-1]} {d.year}"


def get_agenda_du_jour():
    jour = datetime.now().weekday()
    return AGENDA_HEBDO.get(jour, AGENDA_HEBDO[0])


def load_historique():
    try:
        with open("docs/historique.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_historique(historique, new_entry):
    historique.append(new_entry)
    historique = historique[-30:]
    os.makedirs("docs", exist_ok=True)
    with open("docs/historique.json", "w", encoding="utf-8") as f:
        json.dump(historique, f, ensure_ascii=False, indent=2)


def get_news_ia():
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": ANTHROPIC_API_KEY,
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 500,
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                "messages": [{
                    "role": "user",
                    "content": f"Donne-moi en 5 bullet points les actualités IA les plus importantes du jour ({today_label()}) pertinentes pour les PME et ETI françaises. Focus : outils, usages métier, transformation organisationnelle. Évite de te concentrer uniquement sur la réglementation. Sois factuel et concis."
                }]
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        news = " ".join(b["text"] for b in data.get("content", []) if b.get("type") == "text").strip()
        return news[:1000] if news else "Pas d'actualité disponible."
    except Exception as e:
        print(f"Veille actualité indisponible : {e}")
        return "Pas d'actualité disponible."


def build_system_prompt(historique, news, agenda):
    posts_semaine = [h for h in historique[-10:] if h.get("theme") == agenda["theme"]]
    if posts_semaine:
        recents = "\n".join([f"- {h.get('date','?')} : {h.get('post_x','')[:100]}..." for h in posts_semaine])
        hist_txt = f"\n## Posts déjà publiés sur ce thème (NE PAS répéter)\n{recents}\n"
    else:
        hist_txt = "\n## Premier post sur ce thème cette semaine.\n"

    return f"""Tu es l'agent éditorial de Décisions & Co (D&Co).

{KB}

{hist_txt}

## THÈME IMPOSÉ DU JOUR : {agenda["theme"]}
{agenda["instruction"]}

## Actualité IA du jour
{news}

RÈGLES :
1. Reste sur le thème imposé
2. Angle différent des posts déjà publiés
3. Exploite l'actualité si elle touche au thème
4. Jamais : révolution, disruptif, écosystème, synergies, "Dans un monde où"
5. Pas de promotion directe des offres D&Co

Génère UNIQUEMENT un JSON valide sans markdown :
{{"sujet":"...","post_x":"...","post_linkedin":"...","newsletter":"...","hashtags":"#tag1 #tag2"}}

- post_x : max 240 caractères (sans hashtags, ceux-ci sont dans le champ hashtags), une idée tranchée
- hashtags : 1-2 hashtags pertinents pour le thème
- post_linkedin : 600-900 caractères, accroche forte, paragraphes séparés par \\n\\n, terminer par la signature "@Décisions & Co" sur une ligne séparée
- newsletter : 100-180 mots, signé @Décisions & Co
- Échapper guillemets avec \\" et sauts de ligne avec \\n"""


def generate_content(historique, news, agenda):
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": ANTHROPIC_API_KEY,
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 2000,
            "system": build_system_prompt(historique, news, agenda),
            "messages": [{"role": "user", "content": f"Génère le package éditorial. Date : {today_label()}. Thème : {agenda['theme']}."}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    raw = next((b["text"] for b in data["content"] if b["type"] == "text"), "")
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def wrap_text(draw, text, font, max_width):
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


def generate_visual(post_x, theme, hashtags=""):
    """Génère un visuel 1200x675 branded D&Co."""
    W, H = 1200, 675
    style = THEME_STYLES.get(theme, {"accent": "#c8a96e", "label_color": "#c8a96e"})
    ACCENT = style["accent"]

    img = Image.new("RGB", (W, H), "#0d0d1a")
    draw = ImageDraw.Draw(img)

    # Barre verticale signature
    draw.rectangle([0, 0, 8, H], fill=ACCENT)

    # Header panel
    draw.rectangle([0, 0, W, 110], fill="#13132b")
    draw.rectangle([0, 108, W, 110], fill="#252545")

    # Fonts
    try:
        font_logo  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
        font_theme = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        font_body  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        font_url   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except:
        font_logo = font_theme = font_body = font_small = font_url = ImageFont.load_default()

    draw.text((40, 30), "DÉCISIONS & CO", fill=ACCENT, font=font_logo)
    draw.text((40, 64), f"— {theme.upper()}", fill="#7070a0", font=font_theme)

    # Nettoyer hashtags du texte
    clean = post_x
    for tag in re.findall(r"#\w+", post_x):
        clean = clean.replace(tag, "").strip()
    clean = clean.strip(" ,.")

    lines = wrap_text(draw, clean, font_body, W - 120)
    y = 155
    for line in lines[:7]:
        draw.text((50, y), line, fill="#eeeef5", font=font_body)
        y += 56

    # Footer
    draw.rectangle([40, H-110, W-40, H-109], fill="#252545")
    draw.text((50, H-80), "decisionsandco.com", fill="#7070a0", font=font_url)

    tags = hashtags if hashtags else "#IA #PME"
    bbox = draw.textbbox((0, 0), tags, font=font_small)
    draw.text((W - (bbox[2]-bbox[0]) - 50, H-82), tags, fill=ACCENT, font=font_small)

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def upload_media_to_x(image_buf):
    """Upload une image sur X via l'API v1.1 et retourne le media_id."""
    auth = OAuth1(X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET)
    resp = requests.post(
        "https://upload.twitter.com/1.1/media/upload.json",
        auth=auth,
        files={"media": ("visual.png", image_buf, "image/png")},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["media_id_string"]


def publish_to_x(post_text, hashtags="", media_id=None):
    """Publie un tweet avec image optionnelle."""
    auth = OAuth1(X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET)
    full_text = f"{post_text}\n\n{hashtags}".strip() if hashtags else post_text
    payload = {"text": full_text}
    if media_id:
        payload["media"] = {"media_ids": [media_id]}
    resp = requests.post(
        "https://api.twitter.com/2/tweets",
        auth=auth,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def notify_make_linkedin(package, agenda):
    """Envoie le post LinkedIn à Make pour publication automatique."""
    webhook_url = "https://hook.eu2.make.com/y4lqsrwkq4h6d82t7f6qhf6hhnbcgamh"
    try:
        resp = requests.post(
            webhook_url,
            json={
                "sujet": package.get("sujet", ""),
                "post_linkedin": package.get("post_linkedin", ""),
                "post_x": package.get("post_x", ""),
                "theme": agenda["theme"],
                "date": today_label(),
            },
            timeout=15,
        )
        resp.raise_for_status()
        print(f"LinkedIn notifié via Make : {resp.status_code}")
    except Exception as e:
        print(f"Erreur notification Make LinkedIn : {e}")


def save_package(package, agenda):
    os.makedirs("docs", exist_ok=True)
    with open("docs/package.json", "w", encoding="utf-8") as f:
        json.dump({
            "date": today_label(),
            "theme": agenda["theme"],
            "generated_at": datetime.now().isoformat(),
            **package
        }, f, ensure_ascii=False, indent=2)
    print("Package sauvegardé.")


def main():
    print(f"Agent éditorial D&Co — {today_label()}")

    agenda = get_agenda_du_jour()
    print(f"Thème du jour : {agenda['theme']}")

    historique = load_historique()
    print(f"Historique : {len(historique)} posts")

    print("Veille actualité...")
    news = get_news_ia()
    print(f"Actualité : {news[:100]}...")

    print("Génération du contenu...")
    package = generate_content(historique, news, agenda)
    print(f"Sujet : {package.get('sujet')}")
    print(f"Post X : {package.get('post_x')}")

    save_package(package, agenda)

    # Générer le visuel
    print("Génération du visuel...")
    image_buf = generate_visual(
        post_x=package.get("post_x", ""),
        theme=agenda["theme"],
        hashtags=package.get("hashtags", "#IA"),
    )

    # Uploader l'image
    print("Upload de l'image sur X...")
    media_id = upload_media_to_x(image_buf)
    print(f"Media ID : {media_id}")

    # Publier le tweet avec image
    print("Publication sur X...")
    result = publish_to_x(
        post_text=package["post_x"],
        hashtags=package.get("hashtags", ""),
        media_id=media_id,
    )
    tweet_id = result.get("data", {}).get("id", "unknown")
    tweet_url = f"https://twitter.com/DecisionsAndco/status/{tweet_id}"
    print(f"Tweet publié : {tweet_url}")

    # Notifier Make pour publication LinkedIn
    print("Envoi vers Make LinkedIn...")
    notify_make_linkedin(package, agenda)

    save_historique(historique, {
        "date": today_label(),
        "timestamp": datetime.now().isoformat(),
        "theme": agenda["theme"],
        "sujet": package.get("sujet", ""),
        "post_x": package.get("post_x", ""),
        "tweet_url": tweet_url,
    })
    print("Terminé.")


if __name__ == "__main__":
    main()
