#!/usr/bin/env python3
"""Agent éditorial D&Co — Week-end, version agentique.

Contrairement à agent.py (semaine, workflow déterministe), ce script laisse
Claude choisir le thème, décider de la séquence de publication, et escalader
vers une revue humaine si le sujet est sensible (cf. Annexe 1 Charte IA D&Co,
section 6.2 — Article 50(4) AI Act).

Ne remplace pas agent.py : les deux coexistent, déclenchés par des workflows
GitHub Actions séparés (publish.yml pour la semaine, publish-weekend.yml ici).

Réutilise les fonctions techniques déjà écrites et éprouvées dans agent.py
(génération visuelle, publication X, webhook LinkedIn, historique) — seule
la couche de décision change.
"""

import os
import json
import re
import requests
from datetime import datetime

from agent import (
    KB,
    SIGNATURE,
    PAGES_BASE,
    today_label,
    get_news_ia,
    load_historique,
    save_historique,
    nettoyer_package,
    save_visual,
    save_package,
    git_commit_push,
    generate_visual,
    upload_media_to_x,
    publish_to_x,
    attendre_url,
    notify_make_linkedin,
)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# Mode test : quand DRY_RUN=true, l'agent déroule tout le pipeline normalement
# (génération, visuel, git push du package) mais n'appelle PAS les API externes
# irréversibles (publication réelle sur X et LinkedIn). Permet d'observer le
# comportement complet de l'agent — choix du thème, évaluation de sensibilité,
# séquence d'outils — sans aucun effet visible publiquement.
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
MODEL = "claude-sonnet-4-6"
MAX_TOURS = 8

MENTION_TRANSPARENCE = (
    "Ce post est rédigé, illustré et publié de façon autonome par notre "
    "agent IA éditorial, avec supervision humaine déclenchée en cas de "
    "sujet sensible."
)

# État partagé entre les appels d'outils d'un même run. Une boucle agentique
# mono-run n'a pas besoin de plus qu'un dict module-level — pas de base de
# données ni de session à gérer ici.
ETAT = {
    "historique": [],
    "package": {},
    "agenda": {},
    "image_buf": None,
    "visuel_path": None,
    "visuel_url": "",
    "image_ok": False,
    "tweet_url": "",
}


# ---------------------------------------------------------------------------
# 1. Outils
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "consulter_historique",
        "description": "Consulte les posts publiés récemment (semaine + week-end) pour éviter la redite.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "evaluer_sensibilite_sujet",
        "description": (
            "Évalue si le sujet envisagé touche à un développement économique, "
            "réglementaire ou technologique susceptible de constituer un 'sujet "
            "d'intérêt public' au sens de l'Article 50(4) AI Act. À appeler avant "
            "preparer_contenu. Si sensibilité élevée, appeler escalader_revue_humaine "
            "plutôt que de poursuivre la publication seul."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sujet": {"type": "string"},
                "resume_angle": {"type": "string"},
            },
            "required": ["sujet", "resume_angle"],
        },
    },
    {
        "name": "preparer_contenu",
        "description": (
            "Enregistre le contenu rédigé (thème, sujet, textes X et LinkedIn, "
            "hashtags). Le texte LinkedIn doit se terminer par la signature "
            "'Décisions & Co' — la mention de transparence est ajoutée "
            "automatiquement, ne pas l'écrire toi-même."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "theme": {
                    "type": "string",
                    "enum": ["Regard de fond", "Conviction D&Co", "Actualité décryptée", "Terrain & pratique"],
                    "description": (
                        "Label court affiché sur le visuel (badge). Le sujet réel, lui, "
                        "reste totalement libre dans le champ 'sujet' ci-dessous."
                    ),
                },
                "sujet": {"type": "string"},
                "post_x": {"type": "string", "description": "Max 260 caractères, hashtags exclus."},
                "post_linkedin": {"type": "string", "description": "600-900 caractères."},
                "hashtags": {"type": "string", "description": "Ex: #IA #Gouvernance"},
            },
            "required": ["theme", "sujet", "post_x", "post_linkedin", "hashtags"],
        },
    },
    {
        "name": "generer_et_deployer_visuel",
        "description": (
            "Génère le visuel PNG à partir du contenu préparé, le déploie sur "
            "GitHub Pages, et attend qu'il soit accessible publiquement. "
            "Appeler après preparer_contenu, avant publier_x et publier_linkedin."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "publier_x",
        "description": "Publie le post X avec le visuel généré. Appeler après generer_et_deployer_visuel.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "publier_linkedin",
        "description": "Notifie Make.com pour publier le post LinkedIn avec le visuel. Appeler après publier_x.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "escalader_revue_humaine",
        "description": "Suspend toute publication et notifie le référent (Philippe Le Cam) pour validation manuelle.",
        "input_schema": {
            "type": "object",
            "properties": {"raison": {"type": "string"}},
            "required": ["raison"],
        },
    },
    {
        "name": "terminer_execution",
        "description": "Signale la fin du run (publication faite ou escalade envoyée). Toujours appeler en dernier.",
        "input_schema": {
            "type": "object",
            "properties": {"resume": {"type": "string"}},
            "required": ["resume"],
        },
    },
]


# ---------------------------------------------------------------------------
# 2. Implémentation des outils — branchée sur les vraies fonctions agent.py
# ---------------------------------------------------------------------------

def _consulter_historique():
    ETAT["historique"] = load_historique()
    return ETAT["historique"][-15:]


def _evaluer_sensibilite_sujet(sujet, resume_angle):
    # Recherche par limites de mots (\b) : "loi" ne doit matcher que le mot
    # "loi" isolé, pas la sous-chaîne à l'intérieur de "déploiement". Cf.
    # faux positif constaté en test dry-run le 19/08/2026 — un angle
    # éditorial anodin sur "la lenteur organisationnelle" avait été classé
    # sensible uniquement parce que "déploiement" contient "loi".
    mots_sensibles = ["réglementation", "ai act", "politique", "sanction", "loi", "élection"]
    texte = resume_angle.lower()
    niveau = "élevé" if any(re.search(rf"\b{re.escape(m)}\b", texte) for m in mots_sensibles) else "faible"
    return {"niveau_sensibilite": niveau, "sujet": sujet}


def _preparer_contenu(theme, sujet, post_x, post_linkedin, hashtags):
    package = {
        "theme": theme,
        "sujet": sujet,
        "post_x": post_x,
        "post_linkedin": post_linkedin,
        "hashtags": hashtags,
    }
    package = nettoyer_package(package)

    longueur_avant_mention = len(package.get("post_linkedin", ""))
    if not (600 <= longueur_avant_mention <= 900):
        print(
            f"[ALERTE] post_linkedin hors cible : {longueur_avant_mention} caractères "
            f"(attendu 600-900). Contenu publié quand même — à surveiller si ça se répète."
        )

    # Ajout déterministe de la mention de transparence après la signature,
    # même logique que le patch validé pour agent.py (section 7, Annexe 1).
    post = package.get("post_linkedin", "")
    if SIGNATURE in post:
        post = post.replace(SIGNATURE, f"{SIGNATURE}\n\n{MENTION_TRANSPARENCE}", 1)
    else:
        post = f"{post.rstrip()}\n\n{SIGNATURE}\n\n{MENTION_TRANSPARENCE}"
    package["post_linkedin"] = post

    ETAT["package"] = package
    ETAT["agenda"] = {"theme": theme}
    return {"statut": "contenu enregistré", "sujet": sujet}


def _generer_et_deployer_visuel():
    package = ETAT["package"]
    # Nom de fichier unique par EXÉCUTION, pas seulement par jour. Le CDN de
    # GitHub Pages met en cache par chemin de fichier et ignore le paramètre
    # de requête (?v=...) utilisé pour le cache-busting — donc deux runs le
    # même jour écrasaient le même fichier, et Make.com/LinkedIn récupérait
    # l'image mise en cache d'un run précédent plutôt que la nouvelle.
    # Constaté en production le 19/08/2026 (image "catalogue DGE" livrée sur
    # un post "IBM + OpenAI"). L'heure précise dans le nom rend cette
    # collision impossible.
    date_slug = datetime.now().strftime("%Y-%m-%d-%H%M%S") + "-weekend"

    image_buf = generate_visual(
        post_x=package.get("post_x", ""),
        theme=package.get("theme", ""),
        hashtags=package.get("hashtags", "#IA"),
    )
    visuel_path, visuel_rel = save_visual(image_buf, date_slug)

    version = datetime.now().strftime("%H%M%S")
    visuel_url = f"{PAGES_BASE}/{visuel_rel}?v={version}"
    package["visuel_url"] = visuel_url
    save_package(package, ETAT["agenda"])

    git_commit_push(
        ["docs/package.json", visuel_path],
        f"Visuel et package week-end du {date_slug}",
    )

    image_ok = attendre_url(visuel_url)

    ETAT["image_buf"] = image_buf
    ETAT["visuel_path"] = visuel_path
    ETAT["visuel_url"] = visuel_url
    ETAT["image_ok"] = image_ok

    return {"visuel_url": visuel_url, "deploye": image_ok}


def _publier_x():
    package = ETAT["package"]

    if DRY_RUN:
        tweet_url = "[DRY_RUN] Aucune publication réelle — X non appelé."
        print(f"[DRY_RUN] publier_x aurait publié : {package['post_x'][:120]}...")
        ETAT["tweet_url"] = tweet_url
        return {"tweet_url": tweet_url, "dry_run": True}

    media_id = upload_media_to_x(ETAT["image_buf"])
    result = publish_to_x(
        post_text=package["post_x"],
        hashtags=package.get("hashtags", ""),
        media_id=media_id,
    )
    tweet_id = result.get("data", {}).get("id", "unknown")
    tweet_url = f"https://twitter.com/DecisionsAndco/status/{tweet_id}"
    ETAT["tweet_url"] = tweet_url
    return {"tweet_url": tweet_url}


def _publier_linkedin():
    if DRY_RUN:
        print("[DRY_RUN] publier_linkedin aurait notifié Make.com — appel réel ignoré.")
        return {"statut": "notifié (dry_run)", "dry_run": True}

    notify_make_linkedin(
        ETAT["package"],
        ETAT["agenda"],
        image_url=ETAT["visuel_url"] if ETAT["image_ok"] else "",
        has_image=ETAT["image_ok"],
    )
    return {"statut": "notifié"}


def _escalader_revue_humaine(raison):
    # À brancher sur une notification réelle (mail, Slack) si souhaité.
    print(f"[ESCALADE WEEK-END] {raison}")
    return {"statut": "escalade envoyée, en attente de validation humaine"}


def _terminer_execution(resume):
    package = ETAT.get("package") or {}
    if DRY_RUN:
        print(f"[DRY_RUN] terminer_execution — historique.json non modifié (test).")
    elif package.get("sujet"):
        save_historique(ETAT["historique"], {
            "date": today_label(),
            "timestamp": datetime.now().isoformat(),
            "theme": package.get("theme", "Week-end"),
            "sujet": package.get("sujet", ""),
            "post_x": package.get("post_x", ""),
            "tweet_url": ETAT.get("tweet_url", ""),
            "visuel_url": ETAT.get("visuel_url", ""),
        })
    print(f"[FIN WEEK-END] {resume}")
    return {"statut": "terminé"}


DISPATCH = {
    "consulter_historique": lambda i: _consulter_historique(),
    "evaluer_sensibilite_sujet": lambda i: _evaluer_sensibilite_sujet(i["sujet"], i["resume_angle"]),
    "preparer_contenu": lambda i: _preparer_contenu(
        i["theme"], i["sujet"], i["post_x"], i["post_linkedin"], i["hashtags"]
    ),
    "generer_et_deployer_visuel": lambda i: _generer_et_deployer_visuel(),
    "publier_x": lambda i: _publier_x(),
    "publier_linkedin": lambda i: _publier_linkedin(),
    "escalader_revue_humaine": lambda i: _escalader_revue_humaine(i["raison"]),
    "terminer_execution": lambda i: _terminer_execution(i["resume"]),
}


# ---------------------------------------------------------------------------
# 3. Prompt et boucle agentique
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = f"""Tu es l'agent éditorial week-end de Décisions & Co (D&Co).

{KB}

C'est le week-end : pas de thème imposé par une rotation fixe. Choisis un
angle plus libre que la semaine — un regard personnel, une réflexion de fond,
un contenu qui a sa place un samedi ou un dimanche plutôt qu'un lundi matin.
Reste dans la voix D&Co (direct, concret, sans emphase, sans tirets cadratin,
sans mots interdits : révolution, disruptif, écosystème, synergies).

Procédure obligatoire, dans cet ordre :
1. consulter_historique — pour ne pas répéter un sujet déjà traité, semaine ou week-end.
2. evaluer_sensibilite_sujet — sur l'angle que tu envisages.
3. Si sensibilité élevée : escalader_revue_humaine, puis terminer_execution. Ne publie jamais seul un sujet sensible.
4. Si sensibilité faible : preparer_contenu, puis generer_et_deployer_visuel, puis publier_x, puis publier_linkedin, puis terminer_execution.

Le texte LinkedIn doit faire 600 à 900 caractères (hors mention de transparence,
qui est ajoutée automatiquement après ce total), et toujours se terminer par la signature "Décisions & Co"
(la mention de transparence est ajoutée automatiquement par le système,
ne l'écris pas toi-même).
"""


def call_claude(messages):
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": ANTHROPIC_API_KEY,
        },
        json={
            "model": MODEL,
            "max_tokens": 2000,
            "system": SYSTEM_PROMPT,
            "tools": TOOLS,
            "messages": messages,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    print(f"Agent éditorial D&Co (week-end, agentique) — {today_label()}")
    print(f"Mode : {'DRY RUN (aucune publication réelle)' if DRY_RUN else 'PRODUCTION (publication réelle)'}")
    print("Veille actualité...")
    news = get_news_ia()
    print(f"Actualité : {news[:100]}...")

    messages = [
        {
            "role": "user",
            "content": (
                f"Actualité du jour à considérer si pertinente : {news}\n\n"
                "Produis et publie le contenu éditorial du week-end en suivant "
                "la procédure obligatoire décrite dans tes instructions."
            ),
        }
    ]

    for tour in range(1, MAX_TOURS + 1):
        print(f"\n--- Tour {tour} ---")
        data = call_claude(messages)
        content_blocks = data["content"]
        messages.append({"role": "assistant", "content": content_blocks})

        for block in content_blocks:
            if block["type"] == "text" and block["text"].strip():
                print(f"[Claude] {block['text']}")

        if data.get("stop_reason") != "tool_use":
            print("Fin de boucle sans appel à terminer_execution — à investiguer côté prompt.")
            break

        tool_results = []
        termine = False
        for block in content_blocks:
            if block["type"] != "tool_use":
                continue
            nom_outil, entree = block["name"], block["input"]
            print(f"[Outil appelé] {nom_outil}({entree})")
            try:
                resultat = DISPATCH[nom_outil](entree)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": json.dumps(resultat, ensure_ascii=False, default=str),
                })
            except Exception as e:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": f"Erreur : {e}",
                    "is_error": True,
                })
            if nom_outil == "terminer_execution":
                termine = True

        messages.append({"role": "user", "content": tool_results})

        if termine:
            print("\nExécution week-end terminée proprement.")
            return

    print(f"\nPlafond de {MAX_TOURS} tours atteint sans terminer_execution — arrêt forcé.")
    _escalader_revue_humaine("Boucle agentique week-end non terminée dans le nombre de tours imparti.")


if __name__ == "__main__":
    main()
