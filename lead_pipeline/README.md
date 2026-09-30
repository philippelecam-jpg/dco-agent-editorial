# Rachel Entreprises — V1

Le portail Sites est une démonstration privée, explicitement simulée. Aucune saisie n’est transmise ou conservée après rechargement, aucun email ni appel fournisseur n’est envoyé, aucune vidéo n’est publiée.

## Moteur livré

Serveur Python même origine ; email vérifié par lien de 15 minutes à usage unique ; jetons hachés et cookie HttpOnly. SQLite persistante : unicité email, domaine et SIREN facultatif, réservation atomique. Worker unique avec checkpoints, identifiants fournisseurs et unités de consommation. Collecte du site officiel et /actualites ou /news, rédaction Claude et vérification indépendante, ElevenLabs, HeyGen, ffprobe pour contrôler les 30 secondes, YouTube puis email Resend. API administration protégée pour consultation et reprises non ambiguës.

Les adaptateurs sont fondés sur agent_short_video_avatar.py du dépôt dco-agent-editorial consulté le 30 septembre 2026. Le dépôt éditorial original n’a pas été modifié. Ses secrets ne sont pas récupérables via le connecteur.

## Mise en service

1. Copier ce sous-projet dans un dépôt privé ou dans lead_pipeline/ du dépôt éditorial, en adaptant les chemins Docker si nécessaire.
2. Copier config.example.env vers .env et renseigner les secrets hors Git. Réutiliser la voix, la photo Rachel et OAuth YouTube ; clés dédiées aux leads si disponibles.
3. Configurer Resend (domaine d’envoi vérifié) et Turnstile (domaine du portail).
4. Définir PUBLIC_BASE_URL à l’origine HTTPS exacte du portail, sans chemin, et un ADMIN_TOKEN aléatoire long.
5. Lancer docker compose up -d --build. Le volume /data est partagé entre serveur et worker. Un verrou interdit deux workers.
6. Placer un reverse proxy HTTPS devant 127.0.0.1:8000, jamais exposer ce port directement. Appliquer aussi une limite par IP au proxy : la V1 limite par adresse du pair réseau.
7. Premier test contrôlé avec YOUTUBE_PRIVACY=unlisted, puis public après vérification. private ne termine pas la livraison au prospect.

Le backend sert dist/ et /config.js en mode live avec des cookies de même origine. Le portail Sites privé ne devient pas opérationnel par un simple changement de visibilité : le backend doit être installé sur votre infrastructure. Les demandes réelles restent bloquées si les intégrations manquent.

## Vérification

python -m unittest discover -s tests -v

python -m compileall backend

14 tests couvrent unicité concurrente, jetons expirés/rejoués, sessions non vérifiées, correspondance email/site, URL réseau, sources inventées, durée et checkpoints. Aucun test réel auprès des fournisseurs n’a été effectué. Docker et le reverse proxy n’ont pas été exécutés ici.

## API

GET /api/health ; POST /api/signup {name,company,email,captcha} ; POST /api/verify {token} ; GET /api/me ; POST /api/request {site,siren?,acknowledged:true}.

GET /api/admin et POST /api/admin/retry {id} exigent Authorization: Bearer ADMIN_TOKEN. La reprise est refusée si le résultat d’un appel payant ou de publication est incertain (pending_paid). Réconciliation nécessaire auprès du fournisseur, sans relancer aveuglément.

## Limites à traiter avant ouverture publique

Recherche de presse externe et découverte des chemins d’actualités non implémentées ; V1 fondée sur le site officiel. Identité SIREN déclarée non validée auprès d’un registre. Domaines multiples non rapprochés sans SIREN. Emails génériques ou domaine différent refusés. Contrôles IA sans garantie absolue, cas ambigus suspendus. Format 16:9 comme l’existant, pas un Short vertical ; aucun portrait du dirigeant ni visuel tiers récupéré, pas de miniature payante. La vidéo conserve le cadrage Rachel du pipeline actuel.

Consommation enregistrée en unités ; coût financier exact à calculer avec vos contrats. Les erreurs d’appels payants sont bloquées pour éviter les doubles facturations/publications. Les emails non résolus après 23 heures doivent être contrôlés avant reprise, car l’idempotence du fournisseur est bornée. Pas de campagne commerciale ni newsletter automatique.

À finaliser : test bout en bout réel, administration graphique, alertes, sauvegardes/restauration et politique de conservation, procédure de rectification/retrait et validation des conditions de diffusion. Le volume contient des données personnelles : protéger et sauvegarder ; ne jamais committer data/ ou .env.
