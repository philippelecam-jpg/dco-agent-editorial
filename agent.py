#!/usr/bin/env python3
"""Agent éditorial Décisions & Co — génère et publie le post X quotidien."""

import os
import json
import requests
from datetime import datetime
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

# Rotation forcée par jour de semaine — 0=Lundi, 4=Vendredi
AGENDA_HEBDO = {
    0: {  # Lundi
        "theme": "L'Entreprise OS",
        "instruction": "Traite exclusivement le concept d'Entreprise OS de D&Co — ce que c'est, pourquoi c'est le nouveau système d'exploitation de l'organisation, une de ses trois fonctions (Stocker / Traiter / Diffuser), ou un exemple concret d'application."
    },
    1: {  # Mardi
        "theme": "Terrain et missions clients",
        "instruction": "Traite un retour terrain anonymisé d'une mission D&Co, ou une situation concrète observée chez un client PME/ETI face à l'IA. Sois concret, factuel, sans nommer le client."
    },
    2: {  # Mercredi
        "theme": "Méthode Cartographier → Éliciter → Codifier",
        "instruction": "Traite exclusivement la méthodologie D&Co — une des trois étapes, un exemple de ce qu'on trouve quand on cartographie, ce que ça change d'éliciter avant de déployer, ou pourquoi codifier n'est pas du développement logiciel."
    },
    3: {  # Jeudi
        "theme": "Gouvernance et réglementation IA",
        "instruction": "Traite la gouvernance IA, la conformité, ou la réglementation (AI Act, RGPD) avec l'angle D&Co : pas de panique, pas de jargon, juste ce que ça change concrètement pour une PME. Si une actualité réglementaire du jour est pertinente, exploite-la."
    },
    4: {  # Vendredi
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
Situations déclencheuses : "ChatGPT c'est le bazar", "projet IA échoué",
"concurrent nous devance", "AI Act nous inquiète".

## Ton
Direct. Ancré. Concret. Exigeant sans être arrogant.
Phrases courtes. Une idée par phrase.
Mots interdits : révolution, disruptif, écosystème, synergies,
"Dans un monde où", "L'IA change tout".
Mots D&Co : matière, connaissance, gouvernance, structurer, codifier, ancrer.
"""


def today_label():
    d = datetime.now()
    return f"{DAYS_FR[d.weekday()]} {d.day} {MONTHS_FR[d.month-1]} {d.year}"


def get_agenda_du_jour():
    """Retourne le thème imposé pour aujourd'hui."""
    jour = datetime.now().weekday()  # 0=Lundi, 4=Vendredi
    return AGENDA_HEBDO.get(jour, AGENDA_HEBDO[0])


def load_historique():
    """Charge l'historique des posts déjà publiés."""
    try:
        with open("docs/historique.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_historique(historique, new_entry):
    """Sauvegarde le nouvel entry dans l'historique (max 30 entrées)."""
    historique.append(new_entry)
    historique = historique[-30:]
    os.makedirs("docs", exist_ok=True)
    with open("docs/historique.json", "w", encoding="utf-8") as f:
        json.dump(historique, f, ensure_ascii=False, indent=2)


def get_news_ia():
    """Récupère les actualités IA du jour via web search."""
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
        news = " ".join(
            b["text"] for b in data.get("content", []) if b.get("type") == "text"
        ).strip()
        return news[:1000] if news else "Pas d'actualité disponible."
    except Exception as e:
        print(f"Veille actualité indisponible : {e}")
        return "Pas d'actualité disponible."


def build_system_prompt(historique, news, agenda):
    """Construit le prompt système avec agenda, historique et actualité."""

    # Posts de la même semaine sur le même thème
    posts_semaine = [
        h for h in historique[-10:]
        if h.get("theme") == agenda["theme"]
    ]

    if posts_semaine:
        recents_theme = "\n".join([
            f"- {h.get('date', '?')} : {h.get('post_x', '')[:100]}..."
            for h in posts_semaine
        ])
        historique_theme_txt = f"""
## Posts déjà publiés sur ce thème cette semaine (NE PAS répéter ces angles)
{recents_theme}
"""
    else:
        historique_theme_txt = "\n## Premier post sur ce thème cette semaine.\n"

    return f"""Tu es l'agent éditorial de Décisions & Co (D&Co),
cabinet de conseil en transformation IA pour PME/ETI françaises.

{KB}

---

## THÈME IMPOSÉ DU JOUR : {agenda["theme"]}

{agenda["instruction"]}

Tu NE PEUX PAS sortir de ce thème aujourd'hui, sauf si une actualité du jour s'y rattache directement.

{historique_theme_txt}

## Actualité IA du jour (à exploiter SI elle touche au thème imposé)
{news}

---

RÈGLES ABSOLUES :
1. Reste sur le thème imposé du jour
2. Angle différent des posts déjà publiés sur ce thème
3. Si l'actualité touche au thème, exploite-la — sinon ignore-la
4. Varie les formats : affirmation, question, constat en 2-3 lignes
5. Jamais : révolution, disruptif, écosystème, synergies
6. Jamais : "Dans un monde où", "L'IA change tout", "Il est essentiel de"
7. Jamais de promotion directe des offres D&Co

Génère UNIQUEMENT un objet JSON valide, sans markdown, sans texte avant ou après :

{{"sujet":"...","post_x":"...","post_linkedin":"...","newsletter":"..."}}

Contraintes format :
- post_x : max 280 caractères, une idée tranchée, 0-2 hashtags
- post_linkedin : 600-900 caractères, accroche forte, paragraphes courts séparés par \\n\\n
- newsletter : 100-180 mots, ton personnel, signé Philippe Le Cam
- Échapper guillemets avec \\" et sauts de ligne avec \\n"""


def generate_content(historique, news, agenda):
    """Appelle Claude pour générer le package éditorial."""
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
            "messages": [{"role": "user", "content": f"Génère le package éditorial. Date : {today_label()}. Thème du jour : {agenda['theme']}."}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    raw = next((b["text"] for b in data["content"] if b["type"] == "text"), "")
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def publish_to_x(post_text):
    """Publie un tweet via l'API X v2 avec OAuth 1.0a."""
    auth = OAuth1(X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET)
    resp = requests.post(
        "https://api.twitter.com/2/tweets",
        auth=auth,
        json={"text": post_text},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def save_package(package, agenda):
    """Sauvegarde le package du jour en JSON pour l'interface web."""
    os.makedirs("docs", exist_ok=True)
    with open("docs/package.json", "w", encoding="utf-8") as f:
        json.dump({
            "date": today_label(),
            "theme": agenda["theme"],
            "generated_at": datetime.now().isoformat(),
            **package
        }, f, ensure_ascii=False, indent=2)
    print("Package sauvegardé dans docs/package.json")


def main():
    print(f"Agent éditorial D&Co — {today_label()}")

    # Agenda du jour
    agenda = get_agenda_du_jour()
    print(f"Thème du jour : {agenda['theme']}")

    # Charger l'historique
    historique = load_historique()
    print(f"Historique : {len(historique)} posts déjà publiés")

    # Veille actualité
    print("Veille actualité IA du jour...")
    news = get_news_ia()
    print(f"Actualité : {news[:150]}...")

    # Générer le contenu
    print("Génération du contenu...")
    package = generate_content(historique, news, agenda)
    print(f"Sujet : {package.get('sujet', 'N/A')}")
    print(f"Post X ({len(package.get('post_x', ''))} car.) : {package.get('post_x', '')}")

    # Sauvegarder le package
    save_package(package, agenda)

    # Publier sur X
    print("Publication sur X...")
    result = publish_to_x(package["post_x"])
    tweet_id = result.get("data", {}).get("id", "unknown")
    tweet_url = f"https://twitter.com/DecisionsAndco/status/{tweet_id}"
    print(f"Tweet publié : {tweet_url}")

    # Sauvegarder dans l'historique
    save_historique(historique, {
        "date": today_label(),
        "timestamp": datetime.now().isoformat(),
        "theme": agenda["theme"],
        "sujet": package.get("sujet", ""),
        "post_x": package.get("post_x", ""),
        "tweet_url": tweet_url,
    })
    print("Historique mis à jour.")
    print("Terminé.")


if __name__ == "__main__":
    main()
