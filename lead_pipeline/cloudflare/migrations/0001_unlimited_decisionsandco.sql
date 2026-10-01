-- Apply once to the existing D1 database before deploying the new Worker.
-- All requests are preserved; only uniqueness for decisionsandco.com changes.
CREATE TABLE requests_unlimited_migration (
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
INSERT INTO requests_unlimited_migration
  (id,lead_id,company_site,company_domain,siren,source_text,rachel_image,
   github_run_status,github_dispatch_at,status,error,created_at,updated_at)
SELECT id,lead_id,company_site,company_domain,siren,source_text,rachel_image,
       github_run_status,github_dispatch_at,status,error,created_at,updated_at
FROM requests;
DROP TABLE requests;
ALTER TABLE requests_unlimited_migration RENAME TO requests;
CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status, updated_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_unique_lead ON requests(lead_id)
  WHERE company_domain <> 'decisionsandco.com';
CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_unique_domain ON requests(company_domain)
  WHERE company_domain <> 'decisionsandco.com';
CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_unique_siren ON requests(siren)
  WHERE company_domain <> 'decisionsandco.com';
