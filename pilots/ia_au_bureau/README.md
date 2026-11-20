# L'IA au bureau : production contrôlée V2

La V2 remplace la réalisation libre par un dialogue monté à partir de plans séparés. Mina et Nino disposent chacun d'un portrait de référence et d'une voix française fixe. Le workflow génère une vidéo privée ; il ne publie rien automatiquement.

## Produire et reprendre

Dans **Actions → IA au bureau - dialogue contrôlé privé**, choisir `realiste` ou `animation`. Le scénario relu est dans `realiste_v2.json` et les quatre portraits dans `assets/ia_bureau/`.

Pour reprendre une exécution interrompue, renseigner `resume_run_id` et le même format. Le workflow restaure l'archive chiffrée avec le secret HeyGen existant. Une rotation de ce secret rend cette archive de reprise illisible ; l'archive CMS de revue reste disponible avec la clé privée conservée hors dépôt. Les archives expirent après 30 jours.

Les étapes déjà acceptées ne sont pas soumises à nouveau. Une réponse perdue pendant un appel payant bloque la reprise jusqu'au rapprochement manuel. Ne pas effacer un marqueur `*_submitting` sans vérifier la demande chez le fournisseur.

## Voix et montage

- Mina : voix publique française féminine Chantal, identifiant fixé dans le scénario.
- Nino : voix publique française masculine Tanguy, identifiant distinct fixé dans le scénario.
- Les voix sont produites séparément par HeyGen Voice. Le catalogue ElevenLabs ne pouvait pas être lu avec la clé actuelle (`voices_read` absent). Rachel garde son intégration ElevenLabs.
- Chaque plan contient un seul personnage et reçoit son fichier audio avant la synchronisation des lèvres.
- FFmpeg exclut la bande-son du rendu et conserve uniquement la piste vocale source. Les répliques sont concaténées avec 240 ms de respiration, sans superposition ni fondu entre les voix.
- Les niveaux sont normalisés et la sortie contient une piste mono unique.
- Une transcription locale avec faster-whisper produit les horaires des sous-titres et compare le dialogue au scénario. Aucun minutage proportionnel inventé. Une différence importante bloque le montage.
- Les sous-titres sont incrustés une seule fois. Aucun titre géant, voile blanc, bandeau « fictif » ou mention répétée de génération n'est ajouté à l'image.

## Contrôle avant publication

Le rapport conserve `human_review_required: true`. Les contrôles automatiques vérifient le texte transcrit, la durée, les limites des sous-titres et l'unicité de la piste audio. Ils ne prouvent pas la qualité subjective d'une voix, l'absence de tout défaut visuel ni une synchronisation labiale parfaite. Visionner et écouter la vidéo entière avant d'approuver sa publication.

La légende de la V2 est courte : accroche, conseil, question et quelques hashtags. Le label IA natif d'Instagram reste activé pour les contenus concernés. La transparence est assurée par la plateforme sans répéter les mêmes mentions dans l'image et la légende.

Les trois premiers pilotes et le réaliste V1 déjà publiés conservent leurs journaux historiques. Le fichier `publications.json` décrit ce lot historique : ne pas en changer les légendes pour tenter de modifier une publication existante. Les corrections de V2 n'altèrent pas les MP4 déjà publiés.

## Calendrier

Mercredi à 12 h 15 : animation. Samedi à 10 h : réaliste. Fuseau Europe/Paris. Il s'agit d'une proposition non activée, détaillée dans [PLANNING.md](PLANNING.md). Le rythme de Rachel n'est pas modifié.

## Références visuelles

Les portraits ont été générés pour des personnages entièrement fictifs. Les déclinaisons réaliste et animée partagent la même identité. Chaque plan conserve la référence du personnage : une variation de décor future demandera une référence cohérente et une nouvelle revue.
