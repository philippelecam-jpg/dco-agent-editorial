ALTER TABLE requests ADD COLUMN is_internal INTEGER NOT NULL DEFAULT 0 CHECK(is_internal IN (0,1));
DROP INDEX IF EXISTS idx_requests_unique_lead;
DROP INDEX IF EXISTS idx_requests_unique_domain;
DROP INDEX IF EXISTS idx_requests_unique_siren;
CREATE UNIQUE INDEX idx_requests_unique_lead ON requests(lead_id) WHERE company_domain <> 'decisionsandco.com' AND is_internal=0;
CREATE UNIQUE INDEX idx_requests_unique_domain ON requests(company_domain) WHERE company_domain <> 'decisionsandco.com' AND is_internal=0;
CREATE UNIQUE INDEX idx_requests_unique_siren ON requests(siren) WHERE company_domain <> 'decisionsandco.com' AND is_internal=0;
CREATE UNIQUE INDEX idx_requests_internal_active ON requests(lead_id) WHERE is_internal=1 AND status IN ('queued','processing');
