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
  company_name TEXT,
  generation_key TEXT,
  github_run_id TEXT,
  youtube_id TEXT,
  youtube_url TEXT,
  publication_status TEXT DEFAULT 'none',
  delivery_status TEXT DEFAULT 'pending',
  delivery_error TEXT,
  delivery_attempted_at TEXT,
  delivery_lease_until TEXT,
  notified_at TEXT,
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
  updated_at TEXT NOT NULL,
  is_internal INTEGER NOT NULL DEFAULT 0 CHECK(is_internal IN (0,1))
);

CREATE TABLE IF NOT EXISTS whatsapp_inbound (
  message_id TEXT PRIMARY KEY,
  phone_number_id TEXT NOT NULL,
  from_phone TEXT NOT NULL,
  message_type TEXT NOT NULL,
  message_text TEXT,
  received_at TEXT NOT NULL,
  processing_status TEXT NOT NULL DEFAULT 'received'
    CHECK(processing_status IN ('received','processed','ignored','error'))
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_inbound_sender
  ON whatsapp_inbound(from_phone, received_at);

CREATE INDEX IF NOT EXISTS idx_tokens_lead ON verification_tokens(lead_id);
CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status, updated_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_unique_lead ON requests(lead_id)
  WHERE company_domain <> 'decisionsandco.com' AND is_internal=0;
CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_unique_domain ON requests(company_domain)
  WHERE company_domain <> 'decisionsandco.com' AND is_internal=0;
CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_unique_siren ON requests(siren)
  WHERE company_domain <> 'decisionsandco.com' AND is_internal=0;

CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_internal_active ON requests(lead_id) WHERE is_internal=1 AND status IN ('queued','processing');
