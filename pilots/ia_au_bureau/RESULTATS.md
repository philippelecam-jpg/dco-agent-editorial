# État de la série L'IA au bureau

Vérification du 20 novembre 2026.

## Code et pipeline

Intégration sur `main` par la PR #46 : https://github.com/philippelecam-jpg/dco-agent-editorial/pull/46

Commit d'intégration : `f1fd0e19bdf4f799972974533586c489a727de00`.

37 tests passent sur la version intégrée. La génération privée (animation ou réaliste) et la publication Instagram des épisodes validés ont chacune un workflow manuel. La reprise d'un rendu existant ne relance pas sa génération.

## Publications Instagram vérifiées

| Pilote | Lien | Label IA |
| --- | --- | --- |
| Compte rendu → actions | https://www.instagram.com/reel/Df-BplRICjA/ | Confirmé par Meta |
| Réponse fiable | https://www.instagram.com/reel/Df-BviZINGm/ | Confirmé par Meta |
| Achats autonomes | https://www.instagram.com/reel/Df-B1TNIC4H/ | Confirmé par Meta |

Exécution réussie : https://github.com/philippelecam-jpg/dco-agent-editorial/actions/runs/44767800612

Les légendes corrigent les raccourcis des dialogues et distinguent démonstration, limites des modèles et fiction. Les identifiants et liens sont conservés dans `historique/instagram/ia-bureau-*.json`. Les vidéos ont fait l'objet de contrôles techniques et de vues échantillonnées ; aucune écoute intégrale n'est revendiquée.

## Calendrier

Proposition : mercredi à 12 h 15 et samedi à 10 h, heure de Paris, en complément de Rachel mardi et vendredi. Les nouveaux créneaux ne sont pas activés. Le détail des quatre semaines est dans `pilots/ia_au_bureau/PLANNING.md`.

## Complément réaliste privé

Le pilote « L'IA prépare, nous validons » est terminé : 31,88 secondes, 720 × 1280, piste audio présente, contrôle technique conforme. Personnages entièrement fictifs. Rendu photoréaliste confirmé sur quatre images échantillonnées ; cette vérification ne constitue pas une écoute intégrale ni une validation complète de la synchronisation.



Aucune publication sociale de ce quatrième pilote n'a été effectuée. Les sous-titres et la présentation graphique peuvent encore être harmonisés avant une série récurrente. Le premier workflow de récupération manquait de FFmpeg ; le rendu existant a été récupéré par le workflow corrigé sans relancer de génération.

