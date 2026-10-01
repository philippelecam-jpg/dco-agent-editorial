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
The first step asks for a professional email and company website; clicking the button
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
button. Previous requests are retained. Other companies keep the existing email
match and atomic quota constraints.

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
