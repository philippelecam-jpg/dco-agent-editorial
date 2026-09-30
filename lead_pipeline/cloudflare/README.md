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

- `Rachel Entreprises`
- `Rachel Super U`
- `Rachel originale`
