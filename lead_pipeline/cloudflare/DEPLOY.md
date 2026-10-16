# Déployer Rachel Entreprises sur Cloudflare

Ce guide part du principe que le dossier courant est `lead_pipeline/cloudflare`.

## 1. Installer et connecter Wrangler

```bash
npm create cloudflare@latest -- --help
npm install -g wrangler
wrangler login
```

## 2. Créer la base D1

```bash
wrangler d1 create rachel-entreprises
```

Cloudflare retourne un `database_id`. Copier ce `database_id` dans `wrangler.toml`.

## 3. Préparer la configuration

```bash
cp wrangler.toml.example wrangler.toml
```

Dans `wrangler.toml`, remplacer :

```toml
database_id = "replace-with-cloudflare-d1-id"
```

Puis vérifier les variables :

```toml
PUBLIC_BASE_URL = "https://rachel.decisionsandco.fr"
GITHUB_OWNER = "philippelecam-jpg"
GITHUB_REPO = "dco-agent-editorial"
GITHUB_WORKFLOW_ID = "rachel-entreprises-test.yml"
GITHUB_REF = "main"
EMAIL_FROM = "Rachel Entreprises <rachel@decisionsandco.fr>"
```

## 4. Appliquer le schéma D1

```bash
wrangler d1 execute rachel-entreprises --file=schema.sql
```

## 5. Ajouter les secrets

```bash
wrangler secret put RESEND_API_KEY
wrangler secret put GITHUB_TOKEN
wrangler secret put ADMIN_TOKEN
```

Le `GITHUB_TOKEN` doit pouvoir déclencher le workflow `rachel-entreprises-test.yml` sur le dépôt `philippelecam-jpg/dco-agent-editorial`.

## 6. Déployer

```bash
wrangler deploy
```

## 7. Tester

```bash
curl https://rachel.decisionsandco.fr/api/health
```

Réponse attendue :

```json
{"ok":true}
```

Puis ouvrir :

```text
https://rachel.decisionsandco.fr/
```

## 8. Parcours de test conseillé

1. Saisir un email professionnel, un nom et une société.
2. Cliquer le lien reçu par email.
3. Saisir le site de la société.
4. Ajouter `source_text` si le site bloque la collecte.
5. Choisir l'image Rachel.
6. Lancer la génération.
7. Vérifier que le workflow GitHub `Rachel Entreprises — premier test` démarre.

## Notes opérationnelles

- Une seule demande est autorisée par email, domaine et SIREN.
- Si `source_text` est renseigné, le workflow l'utilise comme source factuelle et ne dépend pas du scraping du site.
- Le suivi fin du statut vidéo reste à compléter dans une prochaine version : pour l'instant, le Worker déclenche GitHub Actions et conserve la demande en D1.


## Préparer le callback WhatsApp (après revue du code)

Ajouter les secrets sans les inscrire dans `wrangler.toml` :

```powershell
wrangler secret put WHATSAPP_VERIFY_TOKEN
wrangler secret put WHATSAPP_APP_SECRET
wrangler d1 execute rachel-entreprises --remote --file=migrations/0005_whatsapp_inbound.sql
wrangler deploy --config wrangler.toml
```

Puis configurer dans Meta l’URL `https://rachel-entreprises.decisionsandco.workers.dev/api/whatsapp/webhook` (ou le domaine HTTPS réellement associé au Worker) et le même token de vérification. S’abonner au champ `messages`. Ne pas tester avec « Envoyer un message » avant d’avoir explicitement choisi un numéro destinataire.

Le callback vérifie la signature Meta et consigne les messages entrants dans D1. Il ne répond pas au prospect et ne déclenche pas le moteur vidéo. Les tests unitaires se lancent depuis ce dossier avec `node --test tests/whatsapp.test.mjs`.

## Correction de délivrabilité des emails La Fabrik (16 octobre 2026)

Le Worker conserve l'adresse vérifiée de EMAIL_FROM et utilise le nom visible
« La Fabrik — Décisions & Co ». Les emails d'accès et de livraison contiennent
une version HTML et une version texte. Les liens et leur durée de validité
restent identiques. SPF/DKIM/DMARC étaient PASS sur le message Gmail examiné ;
cela ne garantit pas le placement en boîte de réception.

### Mettre le correctif en production depuis le clone existant

Dans PowerShell, avec le wrangler.toml local et la session Cloudflare existants :

```powershell
cd C:\Users\phili\Documents\dco-agent-editorial
git pull --ff-only
cd lead_pipeline\cloudflare
node --test tests/*.test.mjs
wrangler deploy --config wrangler.toml
```

Ne pas remplacer wrangler.toml par l'exemple : conserver le database_id,
PUBLIC_BASE_URL et les secrets de production. Aucune migration D1 nécessaire.

### Resend

Dans Domains → decisionsandco.com → Configuration, vérifier Click Tracking
et Open Tracking. Pour ces emails transactionnels, désactiver le tracking
si activé (ce réglage concerne tous les emails envoyés avec ce domaine).
Examiner Emails → message concerné → Insights.
Ces réglages de compte ne sont pas modifiés par le déploiement du code.

### Domaine web personnalisé

Si PUBLIC_BASE_URL utilise encore workers.dev, associer d'abord
lafabrik.decisionsandco.com au Worker dans Cloudflare → Settings → Domains
& Routes → Custom Domain, après vérification de la gestion DNS de la zone.
Attendre le certificat HTTPS, puis vérifier /api/health sur le nouveau domaine.
Seulement ensuite, remplacer PUBLIC_BASE_URL dans le wrangler.toml local par
https://lafabrik.decisionsandco.com et redéployer. Ne pas modifier le domaine
d'envoi email et ne pas supprimer l'accès workers.dev pendant la transition.
Une connexion peut être nécessaire sur le nouveau domaine (cookies distincts).
Ce domaine est une proposition, pas une adresse déjà provisionnée.

### Validation de réception

Tester un lien d'accès sur une boîte Gmail et une boîte Outlook contrôlées :
réception/indésirables, identité de l'expéditeur, SPF/DKIM/DMARC PASS,
lien le plus récent fonctionnel et ancien lien refusé après nouvelle demande.
Pour la livraison, utiliser la prochaine capsule ou un test contrôlé, sans
relancer une génération payante uniquement pour tester la messagerie.
Le statut Resend « delivered » ne prouve pas le placement en boîte principale.
Si le spam persiste, relever les IDs Resend et les résultats Insights pour
diagnostic avec le support. Ne pas partager les jetons d'accès personnels.
