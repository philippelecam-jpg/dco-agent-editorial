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
