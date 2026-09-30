# Installation sur le serveur Rachel

Le portail et le worker tournent ensemble sur un serveur avec Docker Compose et un disque persistant. Le portail sert lui-même l’interface en mode live. Il n’est pas nécessaire de modifier le site de démonstration ChatGPT.

## Préparer

Depuis le dépôt mis à jour, ouvrir `lead_pipeline`. Copier `config.example.env` dans `.env` (hors Git, permissions 600). Renseigner les accès Rachel existants dans ce fichier ou dans le gestionnaire de secrets du serveur. Les secrets GitHub ne sont pas exportables par le connecteur.

Renseigner aussi Resend (domaine d’envoi vérifié), les deux clés Turnstile associées au domaine du portail, et un ADMIN_TOKEN aléatoire de 32 caractères minimum. Générer le jeton avec `python -c 'import secrets; print(secrets.token_urlsafe(32))'`, puis le conserver hors des journaux.

Pour le premier essai : `MAX_DAILY_REQUESTS=1`, `YOUTUBE_PRIVACY=unlisted`. Définir `PUBLIC_BASE_URL=https://rachel.votre-domaine.fr` sans slash final. Une vidéo non répertoriée reste accessible à toute personne possédant son lien.

## Valider sans appel payant

```sh
docker compose build
docker compose run --rm portal python -m backend.preflight
```

Le résultat doit montrer deux listes vides. Ce contrôle vérifie la configuration locale, pas la validité des clés ni les permissions des comptes.

## Avec un reverse proxy déjà installé

```sh
docker compose up -d
```

Configurer le proxy HTTPS vers `127.0.0.1:8000`. Garder ce port inaccessible depuis Internet. Ajouter au proxy une limitation par IP des routes `/api/signup` et `/api/verify`. Le serveur applicatif ne fait pas confiance à X-Forwarded-For ; ses limites par pair réseau s’appliquent donc globalement aux visiteurs derrière un proxy.

## Sans reverse proxy

Pointer le DNS du sous-domaine vers le serveur. Ajouter `PORTAL_HOST=rachel.votre-domaine.fr` dans `.env`. Les ports 80 et 443 doivent être libres et accessibles. Cette variante n’ajoute pas de limite par IP au proxy ; les limites globales du moteur et Turnstile restent actifs. Ajouter une protection au proxy avant une ouverture à grande échelle.

```sh
docker compose -f compose.yaml -f deploy/compose.https.yaml up -d --build
```

Caddy obtient le certificat HTTPS automatiquement. Garder la même combinaison de fichiers Compose pour les commandes ultérieures de cette variante.

## Recette réelle

1. Ouvrir `https://rachel.votre-domaine.fr/api/health` : ready doit être true.
2. Sur le portail, saisir une adresse professionnelle de votre entreprise et passer Turnstile.
3. Recevoir le lien Resend, le suivre puis saisir le site correspondant à l’email.
4. Confirmer les conditions et demander la capsule. Cette étape déclenche une génération facturée.
5. Vérifier le lien YouTube non répertorié sur le portail et dans l’email final, les sources et la durée.
6. Vérifier qu’une seconde demande avec le même email ou domaine est refusée.

Une demande test réserve définitivement son email/domaine dans cette base. Utiliser une base distincte pour la recette si vous souhaitez ensuite tester la même entreprise en production. Ne pas effacer les réservations de production pour relancer un traitement incertain.

## Exploitation

Un seul worker ; ne pas multiplier les instances. Le volume `rachel-data` conserve SQLite et les fichiers vidéo. Les journaux sont consultables avec `docker compose logs --tail=100 portal worker` ; ne pas joindre `.env` à un message. L’API `/api/admin` donne les états et les unités de consommation avec Authorization: Bearer ADMIN_TOKEN.

Pour une sauvegarde cohérente, arrêter les deux services, sauvegarder l’ensemble du volume `rachel-data` dans un emplacement privé puis redémarrer. Vérifier une restauration dans une installation isolée, sans worker connecté aux fournisseurs. Ne pas détruire le volume avec `down -v`.

Après recette, choisir `YOUTUBE_PRIVACY=public` si la publication publique est souhaitée et ajuster le plafond quotidien. Appliquer avec `docker compose up -d`. Une modification de secret ou d’environnement exige la recréation des services.
