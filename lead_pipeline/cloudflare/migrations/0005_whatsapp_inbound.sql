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
