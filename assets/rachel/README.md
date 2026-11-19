# Catalogue Rachel

Les six portraits sélectionnés sont conservés ici sans retouche ni compression supplémentaire. Le portrait `bureau.png` est la version verticale corrigée. Dimensions des PNG : 941 × 1672 pixels, proches de 9:16. Le rendu vidéo est demandé à HeyGen en 1080 × 1920 puis contrôlé avant l'upload YouTube.

| Portrait | Usage privilégié | Image |
| --- | --- | --- |
| Originale | Décor de référence, utilisable sur tous les thèmes | [originale.png](originale.png) |
| Bureau | Outils IA, usages et organisation | [bureau.png](bureau.png) |
| Studio | Actualité, cybersécurité, incidents | [studio.png](studio.png) |
| Formation | Formation, management, travail collectif | [formation.png](formation.png) |
| Industrie | Production, métiers industriels, logistique | [industrie.png](industrie.png) |
| Prospective | Réflexion sur les futurs possibles, flux prospective uniquement | [prospective.png](prospective.png) |

Les thèmes compatibles, formats autorisés, validations et empreintes des images sont définis dans [le catalogue](../../config/rachel_looks.json). Les priorités départagent seulement les images jamais utilisées ou utilisées à la même date. L'ancien portrait `assets/Rachel.PNG` et le secret `RACHEL_PHOTO_ASSET_ID` restent la solution de secours.

`approved` signifie que le portrait peut être utilisé. `animation_tested` reste à `false` tant que son animation réelle n'a pas été contrôlée ; ce champ informe du suivi et ne bloque pas les nouvelles générations autorisées.

Pour ajouter une variante, déposer son PNG vertical ici, ajouter une entrée au catalogue avec son empreinte SHA-256 et ses thèmes, puis activer `approved` et `enabled` après contrôle visuel. Ne pas écraser une image validée sans mettre à jour son empreinte : le code rejette une image modifiée sans validation du catalogue.
