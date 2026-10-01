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

No schema migration or new secret is required.
