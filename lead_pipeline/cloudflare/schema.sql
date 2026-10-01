CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  company TEXT NOT NULL,
  verified_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verification_tokens (
  token_hash TEXT PRIMARY KEY,
  lead_id TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS requests (
  id TEXT PRIMARY KEY,
  lead_id TEXT NOT NULL,
  company_site TEXT NOT NULL,
  company_domain TEXT NOT NULL,
  siren TEXT,
  source_text TEXT,
  rachel_image TEXT NOT NULL,
  github_run_status TEXT NOT NULL,
  github_dispatch_at TEXT,
  status TEXT NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tokens_lead ON verification_tokens(lead_id);
CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status, updated_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_unique_lead ON requests(lead_id)
  WHERE company_domain <> 'decisionsandco.com';
CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_unique_domain ON requests(company_domain)
  WHERE company_domain <> 'decisionsandco.com';
CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_unique_siren ON requests(siren)
  WHERE company_domain <> 'decisionsandco.com';
