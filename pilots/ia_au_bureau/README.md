# L'IA au bureau — pilotes privés

Trois essais de 30 à 45 secondes pour une série animée française sur l'IA en PME. Aucun raccord au calendrier ni aucune publication YouTube/Instagram n'est activé.

## Identités
Mina est une dirigeante pragmatique (carré auburn, lunettes ambrées, veste bleu pétrole). Nino est son collègue curieux (cheveux bouclés noirs, pull ocre). Les personnages sont fictifs, dans un style 2D éditorial adulte. Les identités sont décrites dans chaque demande ; leur stabilité inter-épisodes reste à contrôler visuellement. Des images de référence pourront être nécessaires après ces essais.

## Trois pilotes
1. **Compte rendu** : transformer des notes en actions avec responsable et échéance ; le champ absent reste « non précisée ». Extraction réellement testée sur des notes fictives via Claude. Les cartes illustrent le résultat, sans prétendre être une capture d'un logiciel.
2. **Réponse fiable** : distinguer une réponse convaincante d'une affirmation vérifiée. Pas de chiffre ni de source inventée.
3. **Achats autonomes** : fiction explicite sur un assistant préparant une commande sous validation humaine.

## Chaîne de production
Le script `scripts/ia_pilots.py submit` vérifie l'accès HeyGen, teste l'extraction, écrit chaque scénario avec Claude et soumet au maximum trois sessions Video Agent. Chaque session est privée. Les scripts comportent quatre à six scènes et deux voix, pour 75 à 105 mots parlés.

Le mode `poll` récupère les sessions existantes uniquement. Il attend jusqu'à 45 minutes, télécharge les vidéos et mesure durée, ratio et présence audio. Il produit quatre images de contrôle par vidéo. Il ne crée ni ne republie de vidéo.

La publication sociale existante de Rachel n'est pas appelée. La synthèse vocale et le montage multiscène de ces pilotes sont confiés à Video Agent ; la branche Rachel continue d'utiliser ElevenLabs et son montage FFmpeg.

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
