# L'IA au bureau : animation et format réaliste

Série française sur l'IA en PME, avec Mina et Nino, deux personnages entièrement fictifs. La génération privée et la publication Instagram des épisodes validés sont deux actions distinctes. Le calendrier récurrent proposé dans [PLANNING.md](PLANNING.md) n'est pas activé. Il n'y a pas de publication YouTube automatique pour cette série.

## Identités
Mina est une dirigeante pragmatique (carré auburn, lunettes ambrées, veste bleu pétrole). Nino est son collègue curieux (cheveux bouclés noirs, pull ocre). Les personnages sont fictifs, dans un style 2D éditorial adulte. Les identités sont décrites dans chaque demande ; leur stabilité inter-épisodes reste à contrôler visuellement. Des images de référence pourront être nécessaires après ces essais.

## Trois pilotes
1. **Compte rendu** : transformer des notes en actions avec responsable et échéance ; le champ absent reste « non précisée ». Extraction réellement testée sur des notes fictives via Claude. Les cartes illustrent le résultat, sans prétendre être une capture d'un logiciel.
2. **Réponse fiable** : distinguer une réponse convaincante d'une affirmation vérifiée. Pas de chiffre ni de source inventée.
3. **Achats autonomes** : fiction explicite sur un assistant préparant une commande sous validation humaine.

## Chaîne de production
Le script `scripts/ia_pilots.py submit` vérifie l'accès HeyGen, teste l'extraction, écrit chaque scénario avec Claude et soumet au maximum trois sessions Video Agent. Chaque session est privée. Les scripts comportent quatre à six scènes et deux voix, pour 75 à 105 mots parlés.

Le mode `poll` récupère les sessions existantes uniquement. Il attend jusqu'à 45 minutes, télécharge les vidéos et mesure durée, ratio et présence audio. Il produit quatre images de contrôle par vidéo. Il ne crée ni ne republie de vidéo.

Le workflow **IA au bureau - génération privée et reprise** propose `animation` (trois scénarios Claude) ou `realiste` (un scénario relu, dans `scripts/ia_realistic.py`). La synthèse vocale et le montage multiscène sont confiés à Video Agent ; Rachel continue d'utiliser ElevenLabs et son montage FFmpeg.

Pour récupérer des rendus existants, renseigner `resume_run_id` et le nom de leur checkpoint. Cette reprise n'appelle pas la génération. Un résultat technique conforme ne vaut pas validation éditoriale : le workflow conserve aussi les vidéos hors cible pour permettre leur revue.

## Publication Instagram

Le workflow manuel **IA au bureau - publier les pilotes validés sur Instagram** lit `publications.json`. Les trois premiers pilotes ont été autorisés par l'utilisateur pour publication le 20 novembre 2026 ; leurs légendes précisent les limites des démonstrations. Les durées réelles de 38,0 s, 28,0 s et 29,4 s sont acceptées pour ce lot, malgré l'objectif initial de 30–45 s.

Les épisodes futurs doivent être contrôlés entièrement et ajoutés explicitement au manifeste avec `approved: true`. La vérification automatique porte sur le compte, le format portrait, la piste audio, la durée et la taille ; elle ne contrôle pas le contenu du dialogue ni la qualité des sous-titres. Les voix et sous-titres des premiers pilotes demandent encore une revue humaine complète avant une production récurrente sans supervision.

La publication récupère le MP4 déjà rendu via HeyGen et utilise l'intégration Instagram existante, sans Make. Chaque conteneur est journalisé dans `historique/instagram/ia-bureau-<episode>.json` sur `main` avant l'appel final de publication. Une reprise recherche la légende exacte et refuse de republier une tentative ambiguë. Le lien et le label IA sont vérifiés auprès de Meta. Les vidéos Rachel et les pilotes partagent le même verrou de publication Instagram.

Pour une tentative bloquée, vérifier le Reel dans Instagram et le journal avant toute modification. Ne pas effacer un journal pour forcer une nouvelle publication.

## Reprise et confidentialité
Le workflow conserve un checkpoint dès la soumission des sessions. Une réponse ambiguë lors d'un POST ne déclenche aucune nouvelle soumission automatique. Si un lancement échoue, vérifier ce checkpoint et les sessions HeyGen avant de soumettre les épisodes manquants. Ne pas relancer `submit` pour des épisodes déjà acceptés.

Les MP4, scénarios et captures sont archivés avec chiffrement CMS destiné au certificat public de revue. La clé privée reste hors dépôt. Le checkpoint public ne contient aucun jeton ni URL de téléchargement signée. Les fichiers rendus restent aussi récupérables dans le compte HeyGen.

## Critères d'évaluation
- Durée réelle 30–45 secondes et ratio 9:16.
- Identité des personnages, décors variés, animation effective et continuité.
- Français naturel, deux voix distinctes, fin des phrases préservée.
- Sous-titres synchronisés, contrastés et hors des commandes des applications.
- Fidélité au scénario et distinction entre démonstration et fiction.
- Coût réel et temps de rendu mesurables. La durée cible dans le prompt n'est pas une garantie fournisseur.
- Revue humaine nécessaire avant toute activation de la publication automatique.

Documentation de l'intégration : https://developers.heygen.com/docs/video-agent et https://developers.heygen.com/reference/create-video-agent-session
