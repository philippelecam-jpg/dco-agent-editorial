# dco-agent-editorial

## Ponctuation des contenus éditoriaux

Les textes destinés à X, LinkedIn, au site et aux vidéos n'utilisent jamais de tiret cadratin (U+2014). La règle inclut le demi-cadratin (U+2013). Reformuler avec un point, une virgule ou des parenthèses. Conserver les traits d'union nécessaires, les URL et les balises HTML.

Le module `editorial_style.py` porte la consigne commune des prompts et le nettoyage des textes générés.

## Shorts YouTube

Les trois flux produisent des vidéos verticales de 1080 × 1920, avec une cible de 30 à 60 secondes. Le fichier final est contrôlé avec ffprobe avant l'upload. Une accroche concrète apparaît dès la première image dans la zone centrale. Les vidéos Rachel déclarent le contenu synthétique à YouTube.

La cadence commune dans `config/youtube.json` prévoit les Shorts statiques lundi et jeudi, Rachel mardi, et la prospective vendredi. Les déclencheurs cron-job.org existants restent utilisables. Le code ignore les départs hors de ces jours et limite le total à quatre vidéos par semaine. Le paramètre manuel `force_publication` permet une publication hors planning. Le contrôle des titres sur trente jours et la limite d'une prospective « Et si » par semaine restent actifs.

Les playlists publiques existantes sont retrouvées par leur nom exact sur la chaîne autorisée. Les identifiants peuvent aussi être renseignés dans `config/youtube.json` ou dans le secret JSON `YOUTUBE_PLAYLIST_IDS`. Aucun identifiant n'est prérempli tant qu'il n'a pas été vérifié. Le token YouTube doit autoriser `https://www.googleapis.com/auth/youtube.force-ssl` ou `https://www.googleapis.com/auth/youtube`. Le scope `youtube.upload` seul ne permet pas l'ajout aux playlists. Un renouvellement du consentement dans l'outil habituel est nécessaire si le token actuel n'a que ce scope.

Le journal `youtube_publications.json` est écrit immédiatement après l'upload. Si l'ajout à la playlist échoue, la prochaine exécution reprend cette étape avant de considérer une nouvelle vidéo. GitHub sérialise les trois workflows et conserve ce journal même en cas d'échec.

Les vidéos déjà publiées et le nom de la chaîne se gèrent dans YouTube Studio. La première image fait partie du fichier vidéo, indépendamment du choix de miniature proposé par Studio.
