# Rachel Entreprises Cloudflare MVP

This worker is the public lead capture layer around the existing GitHub Actions video engine.

## Flow

1. `POST /api/signup` records a lead and sends a verification link.
2. `GET /verify?token=...` verifies the email and sets a session cookie.
3. `POST /api/request` records one request per verified lead/domain/SIREN and dispatches the GitHub workflow.
4. `GET /api/me` returns the lead and request status.

The video generation remains in `.github/workflows/rachel-entreprises-test.yml`.

## Deploy checklist

1. Create the D1 database.
2. Apply `schema.sql`.
3. Copy `wrangler.toml.example` to `wrangler.toml` and set the D1 id.
4. Set secrets:

```bash
wrangler secret put RESEND_API_KEY
wrangler secret put GITHUB_TOKEN
wrangler secret put ADMIN_TOKEN
```

The GitHub token needs permission to dispatch workflows on `philippelecam-jpg/dco-agent-editorial`.

## API notes

`sourceText` is optional. When present, it is sent to the workflow as `source_text` and bypasses fragile site scraping.

`rachelImage` must be one of:

- `Rachel Tertiaire`
- `Rachel BTP`
- `Rachel Agriculture`
- `Rachel Industrie`
- `Rachel Restauration`
- `Rachel Logistique et Transport`

Default: `Rachel Tertiaire`. Selecting a sector also updates the interface portrait.

## La Fabrik interface

The landing page follows the approved La Fabrik design and adapts to mobile screens.
The first step asks for an email and company website; clicking the button
reveals the name/company fields required by the existing API. An email link then
verifies access and redirects to the capsule form, carrying the website even when
opened on another device. No generation starts before that form is submitted.

The source text and the existing Rachel image choices remain available in the
verified form. Existing requests display their status instead of inviting a second
submission. The play link opens Rachel's YouTube Shorts channel; it is not a sample
video embedded in the page. The portrait uses `assets/Rachel Tertiaire.png`.

This change does not add the YouTube publication callback or automatic result email.

Run the Worker regression checks with Node.js 20 or newer:

```bash
node --test tests/interface.test.mjs
```

Deploy the interface from this directory using your existing configuration:

```bash
wrangler deploy --config wrangler.toml
```

No new secret is required. For the D&Co quota exception, apply the migration below before deploying.

## Décisions & Co repeat demonstrations

Requests for the exact canonical domain `decisionsandco.com` are exempt from the
one-request-per-lead/domain/SIREN rule. Any verified email may request this company.
`www` and scheme variants resolve to the same exemption; lookalike domains and
subdomains are not exempt. Backslashes in pasted HTTP(S) URLs and trailing commas
are normalized before validation.

The verified session's latest D&Co request offers a **Create another capsule**
button. Previous requests are retained. Other companies keep the atomic quota constraints. All companies accept any
verified email, including personal email or a holding company domain.

**Existing D1 databases must apply the migration before deploying the Worker.**
It rebuilds the requests table with partial unique indexes and copies every row.
Running only `schema.sql` cannot remove the old inline uniqueness constraints.
From `lead_pipeline/cloudflare`, run:

```powershell
wrangler d1 execute rachel-entreprises --remote --file=migrations/0001_unlimited_decisionsandco.sql
wrangler deploy --config wrangler.toml
```

Fresh installations can use `schema.sql` directly.

Additional SQLite migration/constraint checks:

```bash
python tests/test_quota_migration.py
```

Email verification confirms access to the mailbox, not a management role in the submitted company.


## Suivi et reprise après échec

Après fusion, depuis le dossier Cloudflare, exécuter une seule fois la migration **avant** le déploiement :

```powershell
wrangler d1 execute rachel-entreprises --remote --file=migrations/0002_request_retry_tracking.sql
wrangler deploy --config wrangler.toml
```

La migration ajoute les champs de suivi sans supprimer les demandes. Elle suppose que la migration 0001 (quotas Décisions & Co) a déjà été appliquée. Une installation neuve peut utiliser directement `schema.sql`, sans ces migrations.

Les nouveaux workflows portent un identifiant de tentative unique. Quand la page de suivi est ouverte, le statut GitHub est consulté toutes les 30 secondes ; le bouton Actualiser permet également une consultation immédiate. Le token GitHub du Worker doit autoriser la lecture des Actions (déjà incluse dans Actions write utilisé pour le lancement).

Après un échec confirmé, « Modifier et réessayer » restaure entreprise, site, source, secteur et SIREN. La même demande est réutilisée : les quotas ne bloquent pas cette reprise. La génération peut toutefois entraîner de nouveaux appels payants. Une nouvelle clé de tentative et une mise à jour conditionnelle empêchent une double relance. Une capsule générée avec succès n’est jamais relancée par ce bouton, même si l’envoi de l’artifact échoue ensuite ; le lien GitHub permet de consulter les résultats. Le statut inconnu ou une indisponibilité GitHub ne débloquent pas la demande automatiquement.

Les anciens essais ne contiennent pas d’identifiant de suivi. Ouvrir `/admin`, saisir le secret **ADMIN_TOKEN** configuré sur le Worker et la référence de la demande. Après vérification manuelle que le workflow est terminé en échec et qu’aucune vidéo n’a été créée, confirmer et cliquer Débloquer. Pour un déblocage immédiat, ajouter le lien ou l’identifiant du workflow GitHub échoué : le serveur vérifie le workflow du moteur, sa date (de -1 à +15 minutes autour du lancement de la demande), sa fin en échec et l’absence d’une étape de génération réussie. Pour ces anciens essais sans clé, l’administrateur confirme explicitement que le workflow est celui de la demande et qu’aucune vidéo n’a été créée. Sans lien GitHub, le délai d’une heure reste applicable. Le token est envoyé dans l’en-tête Authorization, jamais dans l’URL ni stocké dans le navigateur. Les demandes sont conservées, puis la page prospect propose une correction et une reprise.

Tests Node du suivi avec une base SQLite réelle : Node 22.13+ (ou Node 24), `node --test tests/*.test.mjs` depuis ce dossier.


## Publication YouTube et email de restitution

Les nouvelles demandes de l’interface utilisent `youtube_unlisted` : génération du MP4, téléversement sur la chaîne liée aux accès OAuth existants, attente du traitement YouTube et de la visibilité non répertoriée, retour signé au Worker puis email Resend. Une vidéo non répertoriée est accessible avec le lien mais n’est pas listée sur la chaîne publique.

Configuration après fusion, avant le premier test :

1. Créer une valeur aléatoire longue (au moins 32 caractères), la conserver dans un gestionnaire de mots de passe.
2. Ajouter **la même valeur** en secret `LEAD_CALLBACK_SECRET` dans GitHub, Settings → Secrets and variables → Actions, et sur le Worker :

```powershell
wrangler secret put LEAD_CALLBACK_SECRET
```

3. Appliquer une seule fois la migration, puis déployer depuis ce dossier :

```powershell
wrangler d1 execute rachel-entreprises --remote --file=migrations/0003_youtube_delivery.sql
wrangler deploy --config wrangler.toml
```

Les migrations 0001 et 0002 doivent déjà être appliquées. Une installation neuve utilise `schema.sql` directement. Aucun nouvel accès OAuth YouTube n’est requis si les secrets YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET et YOUTUBE_REFRESH_TOKEN existants fonctionnent avec la bonne chaîne.

La vidéo et le rapport restent en artifacts. Un échec de publication conserve le MP4 et propose « Publier la capsule sur YouTube » ou « Finaliser la publication YouTube ». Il n’appelle pas Claude, ElevenLabs ou HeyGen. Si un upload a un résultat incertain, il faut vérifier YouTube avant tout nouveau téléversement. Un identifiant YouTube déjà connu est réutilisé pour vérifier la disponibilité, sans réuploader.

Pour publier un test **déjà généré** depuis GitHub Actions : lancer le workflow Rachel Entreprises en mode `youtube_existing`, renseigner `video_run_id` avec le numéro du run source (dernier nombre dans son URL). Les champs company_name et company_site peuvent être renseignés avec Baresto ; le titre et les sources de publication sont pris dans le rapport source. L’artifact doit encore être disponible (rétention actuelle : 7 jours). Laisser les champs de retour automatique vides pour un test manuel : le lien est dans les logs `published` et le nouveau `report.json`. Un test manuel sans référence La Fabrik n’envoie pas d’email prospect. Le bouton de publication dans l’interface, lorsqu’un run suivi existe, relie en revanche la publication à la demande et à l’email.

Le retour `/api/capsule-result` est signé HMAC-SHA256 avec timestamp, référence et clé de tentative. Une tentative obsolète ou une signature incorrecte est refusée. Aucun email prospect ne transite dans les inputs du workflow : le destinataire est lu dans D1 à partir de la demande vérifiée.

L’envoi Resend utilise une clé d’idempotence et un verrou temporaire ; une livraison déjà acceptée n’est pas renvoyée. Un échec d’email n’affecte pas la vidéo : le lien reste visible et la consultation du statut reprend l’envoi dans la fenêtre de dédoublonnage. Après 23 heures sans confirmation, une vérification manuelle Resend est requise. « Envoyé » signifie accepté par Resend, pas nécessairement arrivé en boîte de réception. Avec `onboarding@resend.dev`, seuls les destinataires autorisés pour les tests Resend fonctionnent ; vérifier un domaine d’envoi avant d’ouvrir le dispositif aux prospects.

Si YouTube garde la vidéo privée ou ne confirme pas sa disponibilité, aucun lien prospect n’est envoyé. Vérifier le traitement et les éventuelles restrictions du projet API dans YouTube Studio. La capsule n’est pas régénérée automatiquement.

### Reprendre après un upload YouTube réussi

Ne relancez pas la génération ou l’upload. Après avoir mis la même valeur de `LEAD_CALLBACK_SECRET` dans GitHub Actions et dans le Worker, ouvrez `/admin`, puis « Finaliser une vidéo YouTube existante ». Renseignez le token administrateur, la référence de demande et les 11 caractères de l’identifiant YouTube confirmé dans Studio. Le mode `youtube_finalize` télécharge le rapport existant, vérifie uniquement le statut YouTube et transmet un retour signé pour livrer le lien. Aucun appel de génération ni nouvel upload ; aucun changement de schéma D1. Le token n’est pas conservé par la page.

Le contrôle utilise `videos.list(part=status)` ; `processingDetails`, réservé au propriétaire, n’est pas demandé. La vidéo doit être `processed` et publique ou non répertoriée avant livraison. Les erreurs Google affichent uniquement leur code de motif, sans corps de réponse ni secret.

### Essais internes

Appliquer une seule fois `wrangler d1 execute rachel-entreprises --remote --file=migrations/0004_internal_tests.sql`, puis déployer le Worker. Depuis `/admin`, « Nouvel essai interne » exige ADMIN_TOKEN et une session email déjà vérifiée dans le même navigateur. Choisir l’entreprise, le site, l’actualité facultative et l’image Rachel. Les essais internes sont marqués `is_internal=1`, conservés dans l’historique, exclus des quotas prospects et livrés au compte connecté. Ils peuvent appeler les fournisseurs payants. Seul un autre essai interne actif bloque le prochain essai ; les anciennes demandes prospects ne bloquent pas cette file séparée. Avant de refuser un nouvel essai, le Worker synchronise le statut GitHub de l’essai interne actif. Un résultat inconnu ou un suivi indisponible conserve le blocage et affiche l’entreprise ainsi que la référence à vérifier ; un index empêche deux essais internes actifs simultanés pour le même compte. La route publique ne peut pas accorder ce statut. Les essais internes échoués se relancent depuis l’administration.


## WhatsApp Cloud API — réception entrante (préparation)

Le Worker expose `GET` et `POST /api/whatsapp/webhook`. Le contrôle Meta du callback utilise `WHATSAPP_VERIFY_TOKEN`. Les notifications `POST` sont acceptées uniquement après vérification de `X-Hub-Signature-256` avec le secret d’application `WHATSAPP_APP_SECRET`.

Les messages texte entrants sont dédupliqués par leur identifiant WhatsApp et enregistrés dans D1 avec le numéro expéditeur et l’heure. Pour les pièces jointes, seul le type est conservé ; le média n’est ni téléchargé ni enregistré. Les événements de statut ne déclenchent aucune action. Cet endpoint **n’envoie aucune réponse WhatsApp**, ne démarre aucune génération vidéo et n’écrit aucun email.

Avant activation Meta :
1. définir les secrets `WHATSAPP_VERIFY_TOKEN` et `WHATSAPP_APP_SECRET` sur le Worker ;
2. appliquer `migrations/0005_whatsapp_inbound.sql` à la base D1 existante (une installation neuve inclut déjà la table dans `schema.sql`) ;
3. déployer le Worker ;
4. vérifier le callback Meta avec `https://<domaine-du-worker>/api/whatsapp/webhook` et le même token ;
5. s’abonner au champ `messages`.

Dans Meta, la route ne doit être configurée qu’après ce déploiement. Un message entrant sera enregistré, mais aucune conversation automatisée ne répondra tant que l’orchestration et l’envoi sortant ne seront pas ajoutés et autorisés. Ajouter aussi une information de confidentialité adaptée avant de proposer le lien WhatsApp aux prospects.

Tests locaux : `node --test tests/whatsapp.test.mjs`. Les tests utilisent un faux D1 et une signature HMAC locale ; ils n’appellent pas Meta.
