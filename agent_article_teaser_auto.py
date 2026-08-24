#!/usr/bin/env python3
"""Agent éditorial D&Co — détection automatique des nouveaux articles publiés
sur decisionsandco.com et publication du teaser LinkedIn correspondant.

Contrairement à agent_article_teaser.py (déclenchement manuel avec l'URL en
argument), ce script tourne seul sur un cron : il scrute la page
https://www.decisionsandco.com/actualites.html, compare la liste des URLs
d'articles à une liste déjà connue (articles/known_urls.json, committée dans
le repo), et traite uniquement les URLs jamais vues.

Toutes les informations nécessaires (titre, extrait, image, catégorie) sont
extraites directement des blocs <article class="news-card"> de cette page de
listing — pas besoin d'une deuxième requête par article ni de régénérer un
visuel : l'image est déjà publique sur le site.

Pour chaque nouvel article détecté :
1. Extrait titre, extrait, image, catégorie depuis le bloc de listing.
2. Génère un teaser LinkedIn court via Claude.
3. Poste vers le webhook Make existant, SANS le champ "type" — le payload
   prend la même forme que les posts quotidiens et retombe sur la route
   fallback du Router (branche LinkedIn), sans toucher au filtre
   "Article Hebdo" ni au scénario Gmail.

Premier lancement (bootstrap) : si articles/known_urls.json n'existe pas
encore, TOUS les articles actuellement en ligne sont enregistrés comme
"déjà connus" SANS déclencher de teaser — sinon le premier run posterait un
teaser pour chacun des articles déjà publiés. Seuls les articles publiés
APRÈS ce premier lancement génèrent un teaser automatique.
"""

import os
import re
import sys
import json
import html
from urllib.parse import quote

import requests

from agent import (
    ANTHROPIC_API_KEY,
    MAKE_WEBHOOK_URL,
    MAKE_API_KEY,
    today_label,
    nettoyer_texte,
)

MODEL = "claude-sonnet-4-6"
LISTING_URL = "https://www.decisionsandco.com/actualites.html"
SITE_BASE = "https://www.decisionsandco.com"
KNOWN_URLS_PATH = "articles/known_urls.json"

BLOC_ARTICLE_RE = re.compile(r'<article class="news-card".*?</article>', re.DOTALL)
HREF_RE = re.compile(r'<a href="(/actualites/[a-z0-9\-]+)"')
TITRE_RE = re.compile(r'<h2 class="news-title">(.*?)</h2>', re.DOTALL)
EXTRAIT_RE = re.compile(r'<p class="news-excerpt">(.*?)</p>', re.DOTALL)
IMAGE_RE = re.compile(r'<img src="(/images/[^"]+)"')
CATEGORIE_RE = re.compile(r'<span class="news-category">(.*?)</span>')


def load_known_urls():
    try:
        with open(KNOWN_URLS_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return None  # None distingue "jamais initialisé" de "vide"


def save_known_urls(urls):
    os.makedirs("articles", exist_ok=True)
    with open(KNOWN_URLS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(urls), f, ensure_ascii=False, indent=2)


def nettoyer_html(texte):
    """Décode les entités HTML (&#39; etc.) et retire les balises résiduelles."""
    texte = re.sub(r"<[^>]+>", "", texte)
    return html.unescape(texte).strip()


def lister_articles_publies():
    """Scrute la page de listing et retourne un dict {url_absolue: infos}."""
    resp = requests.get(LISTING_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    articles = {}
    for bloc in BLOC_ARTICLE_RE.findall(resp.text):
        href_m = HREF_RE.search(bloc)
        if not href_m:
            continue  # carte sans lien interne (ex. lien externe LinkedIn) : ignorée
        url = SITE_BASE + href_m.group(1)

        titre_m = TITRE_RE.search(bloc)
        extrait_m = EXTRAIT_RE.search(bloc)
        image_m = IMAGE_RE.search(bloc)
        categorie_m = CATEGORIE_RE.search(bloc)

        articles[url] = {
            "titre": nettoyer_html(titre_m.group(1)) if titre_m else "",
            "extrait": nettoyer_html(extrait_m.group(1)) if extrait_m else "",
            "image_url": (SITE_BASE + quote(image_m.group(1))) if image_m else "",
            "categorie": nettoyer_html(categorie_m.group(1)) if categorie_m else "",
        }
    return articles


def generate_teaser(infos_article, article_url):
    system = f"""Tu es l'agent éditorial de Décisions & Co (D&Co). Tu rédiges un post LinkedIn COURT (pas un article) qui donne envie de lire un article déjà publié sur le site D&Co.

## Article concerné
Titre : {infos_article['titre']}
Extrait : {infos_article['extrait']}
Catégorie : {infos_article['categorie']}
URL : {article_url}

RÈGLES :
1. 3 à 5 phrases maximum, format post LinkedIn (pas de titre, pas de markdown).
2. Accroche forte dès la première phrase — pas de "Découvrez notre nouvel article".
3. Donne un aperçu concret de l'angle de l'article, pas juste son titre reformulé.
4. Termine par une invitation claire à cliquer sur le lien (le lien lui-même sera ajouté séparément, ne l'écris pas dans le texte).
5. Jamais : révolution, disruptif, écosystème, synergies, "Dans un monde où".

Génère UNIQUEMENT un JSON valide, sans markdown autour :
{{"post_linkedin":"...","sujet":"...","hashtags":"#tag1 #tag2 #tag3"}}

- post_linkedin : le texte du post, SANS l'URL (elle sera ajoutée après)
- sujet : texte alternatif court pour l'image (accessibilité)
- hashtags : 3 à 5 hashtags pertinents
- Échapper les guillemets avec \\" et les sauts de ligne avec \\n"""

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
            "messages": [{
                "role": "user",
                "content": f"Génère le teaser pour l'article \"{infos_article['titre']}\".",
            }],
        },
        timeout=60,
    )
    if resp.status_code >= 400:
        print(f"[ERREUR API] Statut HTTP {resp.status_code}")
        print(f"[ERREUR API] Corps de la réponse : {resp.text[:2000]}")
    resp.raise_for_status()
    data = resp.json()
    raw = next((b["text"] for b in data["content"] if b["type"] == "text"), "")
    raw = raw.replace("```json", "").replace("```", "").strip()
    package = json.loads(raw)
    for champ in ("post_linkedin", "sujet"):
        if champ in package:
            package[champ] = nettoyer_texte(package[champ])

    package["post_linkedin"] = f"{package['post_linkedin']}\n\n{article_url}"
    return package


def notify_make_teaser(package, theme, image_url):
    """Poste vers le webhook Make existant avec le format 'post quotidien'
    (PAS de champ 'type'), pour retomber sur la route fallback du Router."""
    resp = requests.post(
        MAKE_WEBHOOK_URL,
        headers={"x-make-apikey": MAKE_API_KEY},
        json={
            "sujet": package.get("sujet", ""),
            "post_linkedin": package.get("post_linkedin", ""),
            "post_x": "",
            "theme": theme,
            "date": today_label(),
            "image_url": image_url,
            "has_image": bool(image_url),
        },
        timeout=15,
    )
    resp.raise_for_status()
    print(f"Teaser notifié via Make : {resp.status_code}")


def git_commit_push(paths, message):
    import subprocess

    def run(*args):
        return subprocess.run(args, check=True, capture_output=True, text=True)

    run("git", "config", "user.name", "agent-editorial-dco")
    run("git", "config", "user.email", "agent@decisionsandco.com")
    run("git", "add", *paths)

    statut = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if statut.returncode == 0:
        print("Rien à committer.")
        return
    run("git", "commit", "-m", message)
    run("git", "push")
    print("known_urls.json mis à jour et poussé.")


def main():
    print(f"Détection des nouveaux articles — {today_label()}")

    articles_en_ligne = lister_articles_publies()
    print(f"{len(articles_en_ligne)} article(s) trouvé(s) sur le site.")

    urls_connues = load_known_urls()

    if urls_connues is None:
        print(
            "Premier lancement : initialisation de known_urls.json avec les "
            "articles déjà en ligne, SANS générer de teaser."
        )
        save_known_urls(set(articles_en_ligne.keys()))
        git_commit_push([KNOWN_URLS_PATH], "Initialisation known_urls.json (bootstrap, sans teaser)")
        print("Terminé (bootstrap).")
        return

    nouvelles_urls = set(articles_en_ligne.keys()) - urls_connues
    if not nouvelles_urls:
        print("Aucun nouvel article détecté.")
        return

    print(f"{len(nouvelles_urls)} nouvel(aux) article(s) détecté(s) : {sorted(nouvelles_urls)}")

    for article_url in sorted(nouvelles_urls):
        print(f"\n--- Traitement : {article_url} ---")
        infos_article = articles_en_ligne[article_url]
        try:
            print(f"Titre : {infos_article['titre']}")

            package = generate_teaser(infos_article, article_url)
            print(f"Teaser : {package['post_linkedin'][:80]}...")

            notify_make_teaser(
                package,
                theme=infos_article.get("categorie", ""),
                image_url=infos_article["image_url"],
            )

            urls_connues.add(article_url)
        except Exception as e:
            print(f"Erreur sur {article_url}, article ignoré cette fois : {e}")
            # On ne l'ajoute pas à urls_connues : il sera retraité au prochain
            # run plutôt que silencieusement oublié.

    save_known_urls(urls_connues)
    git_commit_push(
        [KNOWN_URLS_PATH],
        f"Teasers publiés pour {len(nouvelles_urls)} nouvel(aux) article(s)",
    )
    print("\nTerminé.")


if __name__ == "__main__":
    main()
