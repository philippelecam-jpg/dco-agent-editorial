# dco-agent-editorial

## L'IA au bureau

Les deux nouveaux workflows manuels produisent des pilotes privés (animation ou rendu réaliste avec personnages fictifs) et publient les épisodes explicitement validés sur Instagram. La génération et la publication sont séparées, avec reprise des rendus et journal antidoublon. Voir [le mode d'emploi](pilots/ia_au_bureau/README.md) et [la proposition de calendrier](pilots/ia_au_bureau/PLANNING.md). Cette nouvelle série n'a pas de récurrence activée.

## Ponctuation des contenus éditoriaux

Les textes destinés à X, LinkedIn, au site et aux vidéos n'utilisent jamais de tiret cadratin (U+2014). La règle inclut le demi-cadratin (U+2013). Reformuler avec un point, une virgule ou des parenthèses. Conserver les traits d'union nécessaires, les URL et les balises HTML.

Le module `editorial_style.py` porte la consigne commune des prompts et le nettoyage des textes générés.

## Shorts YouTube

Les trois flux produisent des vidéos verticales de 1080 × 1920, avec une cible de 30 à 60 secondes. Le fichier final est contrôlé avec ffprobe avant l'upload. Une accroche concrète apparaît dès la première image dans la zone centrale. Les vidéos Rachel déclarent le contenu synthétique à YouTube.

La cadence commune dans `config/youtube.json` prévoit les Shorts statiques lundi et jeudi, Rachel mardi, et la prospective vendredi. Les déclencheurs cron-job.org existants restent utilisables. Le code ignore les départs hors de ces jours et limite le total à quatre vidéos par semaine. Le paramètre manuel `force_publication` permet une publication hors planning. Le contrôle des titres sur trente jours et la limite d'une prospective « Et si » par semaine restent actifs.

Les playlists publiques existantes sont retrouvées par leur nom exact sur la chaîne autorisée. Les identifiants peuvent aussi être renseignés dans `config/youtube.json` ou dans le secret JSON `YOUTUBE_PLAYLIST_IDS`. Aucun identifiant n'est prérempli tant qu'il n'a pas été vérifié. Le token YouTube doit autoriser `https://www.googleapis.com/auth/youtube.force-ssl` ou `https://www.googleapis.com/auth/youtube`. Le scope `youtube.upload` seul ne permet pas l'ajout aux playlists. Un renouvellement du consentement dans l'outil habituel est nécessaire si le token actuel n'a que ce scope.

Le journal `youtube_publications.json` est écrit immédiatement après l'upload. Si l'ajout à la playlist échoue, la prochaine exécution reprend cette étape avant de considérer une nouvelle vidéo. Si le token manque uniquement du droit d’ajout aux playlists, une alerte est journalisée et les nouvelles vidéos peuvent être publiées selon la cadence prévue. GitHub sérialise les trois workflows et conserve ce journal même en cas d'échec.

Les vidéos déjà publiées et le nom de la chaîne se gèrent dans YouTube Studio. La première image fait partie du fichier vidéo, indépendamment du choix de miniature proposé par Studio.

La configuration HeyGen v3 utilise `aspect_ratio: 9:16` et `resolution: 1080p`. Les dimensions réelles sont contrôlées sur le fichier reçu.

### Variété des scripts et fin des vidéos

Les trois formats partagent les règles de rédaction de `youtube_short_policy.py`. Les introductions et conclusions varient selon le sujet. La prospective conserve son registre imaginatif, avec une hypothèse clairement distinguée des faits. « Et si » devient facultatif et la transition sur la « science-fiction lointaine » est exclue. La dernière phrase doit être complète, ponctuée et courte (18 mots maximum).

Les accroches et conclusions des douze dernières publications disposant de ces informations sont fournies au rédacteur, tous formats confondus. Une répétition proche ou une formule interdite entraîne une nouvelle rédaction, avec le motif du refus, dans une limite de trois propositions avant tout appel à ElevenLabs ou HeyGen. Les phrases sont conservées dans `youtube_publications.json` dès l'upload, même si l'ajout à la playlist échoue, puis dans les historiques existants en fin d'exécution. Les anciennes entrées restent valides ; leurs phrases absentes ne sont pas reconstituées.

La voix vise 30 à 55 secondes et le contrôle accepte jusqu'à 58 secondes pour réserver la fin. Le montage conserve toute la narration, ajoute une seconde de silence et maintient la dernière image. Aucun fondu ne masque le dernier mot. Si le rendu dépasse la place disponible sous 60 secondes, l'envoi est bloqué au lieu de tronquer la voix. Pour Rachel et la prospective, la durée de la piste HeyGen est comparée à celle du fichier ElevenLabs ; un raccourcissement supérieur à 150 ms bloque l'envoi et apparaît dans les logs. Ce contrôle de durée ne remplace pas l'écoute de la dernière phrase du premier rendu réel.

Les déclencheurs GitHub et les horaires cron-job.org restent inchangés. Vérification locale sans publication : `python -m unittest discover -s tests -v` (ffmpeg et ffprobe requis).

### Variantes visuelles de Rachel

Les six portraits sont dans [`assets/rachel/`](assets/rachel/README.md) et leur référentiel dans [`config/rachel_looks.json`](config/rachel_looks.json). Le module `rachel_catalogue.py` les sélectionne pour les flux avatar et prospective. Les Shorts statiques conservent leur fond graphique.

La sélection réutilise la playlist attribuée au sujet, complétée par les mots-clés du titre, du résumé et du thème prospectif. Parmi les portraits validés compatibles, elle exclut celui de la dernière publication Rachel, tous formats confondus, puis choisit le moins récemment publié. Une image jamais utilisée passe avant une image déjà utilisée ; la priorité du catalogue départage les égalités. Seules les publications ayant un identifiant YouTube font avancer cette rotation.

L'image choisie est envoyée automatiquement à `POST /v3/assets` lors de sa première utilisation. Son identifiant HeyGen et son empreinte sont conservés dans `rachel_assets.json`, sauvegardé par les deux workflows même après un échec. Aucun nouvel identifiant à saisir dans les secrets. Une modification validée de l'image provoque un nouvel upload. Si une image devient indisponible dans HeyGen, supprimer son entrée dans ce cache pour la renvoyer au prochain usage.

Le choix réel est enregistré sous `rachel_look` dans le journal YouTube dès l'upload, puis dans l'historique du format. Si le catalogue ou l'upload d'image est indisponible, le code émet une alerte et utilise le portrait historique via `RACHEL_PHOTO_ASSET_ID`. Cette solution de secours peut exceptionnellement répéter l'image d'origine et est explicitement signalée dans l'historique.

Les horaires et les corps des appels cron-job.org restent identiques. Les images sont intégrées, mais leur premier rendu animé doit encore être contrôlé dans HeyGen ; `animation_tested` permet de suivre ce contrôle dans le catalogue.

## Reels Instagram de Rachel

Les workflows Avatar et Prospective publient aussi sur [@decisionsandco](https://www.instagram.com/decisionsandco/) après l’envoi YouTube. La cadence reste celle des Shorts Rachel. Le flux statique est exclu. Le Reel réutilise le MP4 vertical, reçoit une légende composée du titre et du résumé, et déclare que Rachel est générée par IA. La publication et son label sont vérifiés auprès de Meta. Le lien est conservé dans `historique/instagram/<id YouTube>.json`.

Le workflow utilise la connexion unifiée Meta et le secret Actions `INSTAGRAM_ACCESS_TOKEN` déjà configuré. L’archive du MP4 est chiffrée avec une clé dérivée de ce jeton et conservée pendant 30 jours. Une rotation du jeton rend les anciennes archives illisibles avec le nouveau jeton.

Pour reprendre un échec Instagram, ouvre **Actions → Rachel / Publication Instagram → Run workflow** et saisis dans `source_run_id` le numéro de l’exécution Avatar ou Prospective qui contient l’archive `rachel-reel-<id exécution>`. Cette reprise réutilise le fichier. Si Meta a reçu une demande de publication dont le résultat reste incertain, le workflow recherche d’abord le Reel par sa légende. Il bloque un nouvel envoi en cas d’ambiguïté. Vérifie alors la présence de la vidéo dans Instagram avant toute autre action.
