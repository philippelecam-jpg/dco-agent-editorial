# Instagram @decisionsandco — consignes pour le pipeline éditorial

À ajouter à la base de connaissances de `dco-agent-editorial`.

## Positionnement
- Cible : dirigeants de PME et d'ETI. Sujet unique : l'IA appliquée à l'entreprise.
- Chaque contenu se termine par une réponse à la question : « Qu'est-ce que ça change pour votre entreprise ? »
- Appel à l'action standard : `→ Votre pré-diagnostic IA : lien en bio`

## Module News Flash (Reels avatar « Rachel »)
- Ne retenir que des actualités en rapport avec l'IA, la donnée, la cybersécurité ou la transformation numérique des entreprises. Écarter les sujets de société sans lien avec l'IA.
- Structure de la légende : titre en question → 2 ou 3 phrases de faits → ligne « Ce que ça change pour une PME : … » → appel à l'action → hashtags.
- Conserver la mention IA (« Rachel, présentatrice IA de Décisions & Co. ») et l'étiquette « Contenu IA ».

## Hashtags (4 à 6 par post, toujours en fin de légende)
- Socle : `#IAenEntreprise #PME #TransformationIA #DecisionsAndCo`
- Selon le thème, ajouter 1 ou 2 tags parmi : `#ETI #GouvernanceIA #AgentsIA #Productivite #Cybersécurité #IAauBureau`

## Couvertures de Reels
- Générées avec `scripts/reel_cover.py` (fond bleu nuit Décisions & Co, rubrique, titre, pastille d'épisode).
- Les textes restent dans la zone centrale 1080×1350, celle qui reste visible dans la grille du profil.
- Rubriques : `L'IA AU BUREAU` (série illustrée), `NEWS FLASH IA` (avatar), `MÉTHODE`, `CAS D'USAGE`.

## Rythme cible
| Format | Fréquence | Source |
|---|---|---|
| Reel « L'IA au bureau » | 1 par semaine | série existante |
| Reel News Flash IA | 2 à 3 par semaine | module News Flash, recadré |
| Carrousel pédagogique (1080×1350, 6 à 9 slides) | 1 par semaine | articles LinkedIn hebdomadaires |
| Story | 1 par jour | citation, chiffre clé ou coulisses, au gabarit des stories à la une |

## Idées de carrousels (à partir des pages du site)
1. Pourquoi les projets IA s'arrêtent en route (page Transformation IA)
2. Gouvernance IA : les 5 décisions du comité de direction
3. Quick wins : choisir son premier cas d'usage
4. Ambassadeurs IA : le rôle des relais internes
5. Vibe coding : quand les métiers créent leurs outils

## Posts épinglés
- Épingler des contenus durables (méthode, série, offre), jamais une actualité.
- Recommandation : carrousel Méthode + épisode 1 « L'IA au bureau » + un Reel offre ou pré-diagnostic.

## Communauté (actions manuelles)
- Suivre 30 à 50 comptes ciblés : Bpifrance, French Tech et écosystème nantais, France Num, clients et partenaires, médias PME et IA.
- Relayer chaque carrousel dans la communauté WhatsApp de dirigeants et sur LinkedIn.
- Répondre aux commentaires dans les 24 h.

## Production autonome des carrousels

Le workflow `instagram_carousel.yml` produit sept slides JPEG de 1080 × 1350
à partir du dernier article archivé depuis moins de quatorze jours. Le créneau
retenu est le jeudi à 12 h, heure de Paris. Une vérification quotidienne reprend
les échecs ou attend un article arrivé en retard, avec un carrousel par semaine
et un article utilisé une seule fois. GitHub Actions peut démarrer avec du retard.

Le journal et les slides sont archivés dans `historique/instagram/carrousels`.
Meta récupère les images dans le dépôt public à une révision immuable. Le jeton
Instagram et la clé Anthropic existants sont réutilisés. Une erreur déclenche
l’alerte Make existante. Une publication dont le résultat est incertain est
rapprochée du compte avant toute reprise pour prévenir les doublons.

Commande locale de prévisualisation facultative, avec la clé Anthropic disponible
et les dépendances requests, Pillow et les polices DejaVu installées

```sh
python instagram_carousel.py --preview --force
```

La mise en production doit vérifier le premier carrousel via Meta. Les tests
locaux couvrent le rendu et les reprises avec des réponses API simulées.
