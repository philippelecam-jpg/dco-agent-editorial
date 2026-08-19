#!/usr/bin/env python3
"""
test_escalade_notification.py — Vérifie que la chaîne de notification GitHub
(création d'issue + assignation) déclenche bien un e-mail, avant de mettre
un dispositif d'escalade humaine en production.

Conçu pour être réutilisable tel quel sur n'importe quel dépôt client :
aucune dépendance au code de dco-agent-editorial, uniquement un jeton
GitHub et le nom du dépôt. Fait partie du kit de mise en place du dispositif
d'escalade humaine (Annexe Charte IA, section supervision).

Usage minimal :
    export GITHUB_TOKEN=ghp_votre_jeton
    python3 test_escalade_notification.py --repo owner/repo --assignee username

Usage par variables d'environnement (identique à ce qu'utilise le workflow
GitHub Actions réel — pratique pour tester avec exactement la même config) :
    export GITHUB_TOKEN=ghp_votre_jeton
    export GITHUB_REPOSITORY=owner/repo
    export GITHUB_ISSUE_ASSIGNEE=username
    python3 test_escalade_notification.py

Le jeton doit avoir le scope 'repo' (compte personnel) ou être le
GITHUB_TOKEN fourni automatiquement par un run GitHub Actions (dans ce cas,
la permission 'issues: write' doit être déclarée dans le workflow).
"""

import os
import sys
import argparse
from datetime import datetime

import requests


def creer_issue_test(repo, token, assignee=None, labels=None, cleanup=False):
    labels = labels or ["escalade-ia", "test"]
    horodatage = datetime.now().strftime("%d/%m/%Y à %H:%M")

    payload = {
        "title": f"[TEST] Vérification notification d'escalade — {horodatage}",
        "body": (
            "Ceci est une issue de **test**, créée manuellement pour vérifier la "
            "chaîne de notification d'escalade humaine avant sa mise en production.\n\n"
            "Si vous recevez un e-mail de notification pour cette issue "
            "(assignation), la chaîne fonctionne correctement de bout en bout.\n\n"
            "Cette issue peut être fermée sans suite une fois la vérification faite."
        ),
        "labels": labels,
    }
    if assignee:
        payload["assignees"] = [assignee]

    print(f"-> Création d'une issue de test sur {repo}...")
    try:
        resp = requests.post(
            f"https://api.github.com/repos/{repo}/issues",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            json=payload,
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        print(f"X Erreur réseau lors de l'appel à l'API GitHub : {e}")
        sys.exit(1)

    if resp.status_code >= 300:
        print(f"X Échec — statut HTTP {resp.status_code}")
        print(resp.text[:500])
        if resp.status_code == 401:
            print("  -> Jeton invalide ou expiré.")
        elif resp.status_code == 403:
            print("  -> Jeton valide mais sans les droits nécessaires (scope 'repo', "
                  "ou permission 'issues: write' manquante si jeton d'Actions).")
        elif resp.status_code == 404:
            print("  -> Dépôt introuvable, ou jeton sans accès à ce dépôt.")
        sys.exit(1)

    data = resp.json()
    issue_url = data.get("html_url")
    issue_number = data.get("number")
    print(f"OK Issue créée : {issue_url}")

    assignees_reels = [a["login"] for a in data.get("assignees", [])]
    if assignee:
        if assignee in assignees_reels:
            print(f"OK Assignation confirmée à '{assignee}'")
        else:
            print(f"! '{assignee}' n'apparaît PAS dans les assignés réels ({assignees_reels or 'aucun'}).")
            print("  Vérifiez que ce compte a bien un accès (collaborateur ou membre) à ce dépôt —")
            print("  GitHub ignore silencieusement une assignation à un compte sans accès,")
            print("  l'issue est créée mais reste non assignée.")
    else:
        print("i Aucun --assignee demandé — pas de vérification d'assignation à faire.")

    print()
    print("Prochaine étape : vérifiez la boîte mail du compte assigné (et les spams)")
    print("dans les minutes qui suivent. Si rien n'arrive alors que l'assignation est")
    print("confirmée ci-dessus, le problème est dans les réglages de notification du")
    print("compte GitHub (github.com/settings/notifications, catégorie 'Participating,")
    print("@mentions and custom' -> Email), pas dans ce script ni dans le code de l'agent.")

    if cleanup:
        print()
        print("-> Fermeture automatique de l'issue de test (--cleanup)...")
        try:
            close_resp = requests.patch(
                f"https://api.github.com/repos/{repo}/issues/{issue_number}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                json={"state": "closed"},
                timeout=15,
            )
            if close_resp.status_code < 300:
                print("OK Issue de test fermée.")
            else:
                print(f"! Fermeture automatique échouée (statut {close_resp.status_code}) — à fermer manuellement.")
        except requests.exceptions.RequestException as e:
            print(f"! Fermeture automatique impossible (erreur réseau : {e}) — à fermer manuellement.")

    return issue_url


def main():
    parser = argparse.ArgumentParser(
        description="Teste la chaîne de notification d'escalade humaine (issue GitHub assignée)."
    )
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"),
                         help="Dépôt cible, format owner/repo (défaut : variable GITHUB_REPOSITORY)")
    parser.add_argument("--assignee", default=os.environ.get("GITHUB_ISSUE_ASSIGNEE"),
                         help="Utilisateur GitHub à assigner (défaut : variable GITHUB_ISSUE_ASSIGNEE)")
    parser.add_argument("--labels", nargs="*", default=None,
                         help="Labels à appliquer (défaut : escalade-ia test)")
    parser.add_argument("--cleanup", action="store_true",
                         help="Ferme automatiquement l'issue de test juste après sa création")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("X GITHUB_TOKEN manquant. Exportez-le avant de lancer ce script :")
        print("    export GITHUB_TOKEN=ghp_votre_jeton_personnel")
        print("  (Settings -> Developer settings -> Personal access tokens, scope 'repo' suffisant)")
        sys.exit(1)

    if not args.repo:
        print("X Dépôt non spécifié. Utilisez --repo owner/repo, ou exportez GITHUB_REPOSITORY.")
        sys.exit(1)

    if not args.assignee:
        print("! Aucun --assignee fourni : l'issue sera créée sans assignation, donc")
        print("  aucun e-mail de notification d'assignation ne sera déclenché par ce test.")
        print()

    creer_issue_test(args.repo, token, assignee=args.assignee, labels=args.labels, cleanup=args.cleanup)


if __name__ == "__main__":
    main()
