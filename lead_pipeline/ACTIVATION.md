# Premier raccordement Rachel Entreprises

## Test utilisant les secrets existants

Le workflow **Rachel Entreprises — premier test** réutilise les noms de secrets de votre workflow Rachel. Il n’en copie ni n’en affiche la valeur. Aucune programmation automatique n’est ajoutée.

Après intégration dans main : Actions → Rachel Entreprises — premier test → Run workflow.

1. Mode `check` : vérifie uniquement la présence des accès ; aucun appel payant. Cette vérification ne prouve pas la validité des clés.
2. Mode `video` : collecte le site, rédige et vérifie le script, génère la voix et Rachel. Télécharger ensuite l’artefact `rachel-capsule-<run_id>`, contenant MP4 et rapport. Aucun email, aucun téléversement YouTube.
3. Mode `youtube_private` : même test avec téléversement privé sur la chaîne existante. Jamais de diffusion publique via ce workflow.

Société et site par défaut : Décisions & Co, https://www.decisionsandco.com. Il s’agit d’un premier essai sur votre propre entreprise.

Chaque lancement de génération constitue une nouvelle demande payante. Le workflow refuse une nouvelle tentative du même run (`run_attempt > 1`) afin de ne pas relancer automatiquement une génération facturée. Une nouvelle exécution volontaire peut aussi créer une nouvelle vidéo : contrôler le résultat précédent avant de la lancer. Les checkpoints restent accessibles dans les journaux de travail du runner seulement, pas dans les artefacts ; le moteur serveur persistant est nécessaire pour les reprises durables.

Les secrets de test sont ANTHROPIC_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, HEYGEN_API_KEY, RACHEL_PHOTO_ASSET_ID, YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN. Le modèle et les endpoints sont ceux du pipeline de référence ; un test réel reste nécessaire.

## Mise en service du portail public

Depuis le dossier lead_pipeline, suivre README.md et config.example.env. Installer les deux services sur le serveur cible, raccorder Resend et Turnstile, configurer le domaine HTTPS et le volume privé persistant. Le portail Sites demeure une démonstration indépendante ; les secrets de GitHub Actions ne deviennent pas accessibles au serveur par magie et doivent être installés dans son gestionnaire de secrets.

Le code frontend livré reste en mode démo lorsqu’il est servi statiquement. Le backend sert sa propre configuration live sur /config.js. Les données prospects restent dans /data, jamais dans GitHub.

## Installation prête à adapter

Voir deploy/INSTALLATION.md pour la recette sur serveur existant, le contrôle sans appels payants et la variante HTTPS intégrée.
