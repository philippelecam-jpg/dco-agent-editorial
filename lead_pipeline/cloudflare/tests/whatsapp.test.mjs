import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import worker from "../src/index.js";

const origin = "https://rachel.test";
const appSecret = "test-app-secret";

function mockDb() {
  const stored = [];
  return {
    stored,
    prepare(sql) {
      return {
        sql,
        bind(...values) { this.values = values; return this; },
      };
    },
    async batch(statements) {
      for (const statement of statements) stored.push({ sql: statement.sql, values: statement.values });
      return [];
    },
  };
}
function signature(body) {
  return "sha256=" + createHmac("sha256", appSecret).update(body).digest("hex");
}

test("Meta GET verification returns the challenge only with the configured token", async () => {
  const url = new URL("/api/whatsapp/webhook", origin);
  url.searchParams.set("hub.mode", "subscribe");
  url.searchParams.set("hub.verify_token", "verify-me");
  url.searchParams.set("hub.challenge", "challenge-123");
  const response = await worker.fetch(new Request(url), { WHATSAPP_VERIFY_TOKEN: "verify-me" });
  assert.equal(response.status, 200);
  assert.equal(await response.text(), "challenge-123");
  const rejected = await worker.fetch(new Request(url), { WHATSAPP_VERIFY_TOKEN: "wrong" });
  assert.equal(rejected.status, 403);
});

test("POST rejects unsigned and oversized/unconfigured events without touching D1", async () => {
  const db = mockDb();
  const invalid = await worker.fetch(new Request(origin + "/api/whatsapp/webhook", {
    method: "POST", body: '{"object":"whatsapp_business_account","entry":[]}',
  }), { DB: db, WHATSAPP_APP_SECRET: appSecret });
  assert.equal(invalid.status, 401);
  const unconfigured = await worker.fetch(new Request(origin + "/api/whatsapp/webhook?hub.mode=subscribe", {
    method: "POST", body: "{}",
  }), { DB: db });
  assert.equal(unconfigured.status, 503);
  assert.equal(db.stored.length, 0);
});

test("signed inbound text is stored once and no outbound action is performed", async () => {
  const db = mockDb();
  const payload = {
    object: "whatsapp_business_account",
    entry: [{
      changes: [{
        field: "messages",
        value: {
          metadata: { phone_number_id: "phone-id" },
          messages: [{
            id: "wamid.test.1",
            from: "33612345678",
            timestamp: "1791392400",
            type: "text",
            text: { body: "Bonjour, je souhaite une capsule" },
          }],
        },
      }],
    }],
  };
  const body = JSON.stringify(payload);
  const makeRequest = () => new Request(origin + "/api/whatsapp/webhook", {
    method: "POST",
    headers: { "x-hub-signature-256": signature(body), "content-type": "application/json" },
    body,
  });
  const first = await worker.fetch(makeRequest(), { DB: db, WHATSAPP_APP_SECRET: appSecret });
  const second = await worker.fetch(makeRequest(), { DB: db, WHATSAPP_APP_SECRET: appSecret });
  assert.equal(first.status, 200);
  assert.deepEqual(await first.json(), { ok: true });
  assert.equal(second.status, 200);
  assert.equal(db.stored.length, 2); // Both requests attempt INSERT OR IGNORE; D1 enforces idempotency.
  assert.equal(db.stored[0].values[0], "wamid.test.1");
  assert.equal(db.stored[0].values[2], "33612345678");
  assert.equal(db.stored[0].values[4], "Bonjour, je souhaite une capsule");
});

test("signed non-text messages store only their type, not media payload", async () => {
  const db = mockDb();
  const body = JSON.stringify({
    object: "whatsapp_business_account",
    entry: [{ changes: [{ value: {
      metadata: { phone_number_id: "phone-id" },
      messages: [{ id: "wamid.image.1", from: "33612345678", timestamp: "1791392400", type: "image", image: { id: "media-id", caption: "private" } }],
    } }] }],
  });
  const response = await worker.fetch(new Request(origin + "/api/whatsapp/webhook", {
    method: "POST", headers: { "x-hub-signature-256": signature(body) }, body,
  }), { DB: db, WHATSAPP_APP_SECRET: appSecret });
  assert.equal(response.status, 200);
  assert.equal(db.stored[0].values[3], "image");
  assert.equal(db.stored[0].values[4], null);
  assert(!JSON.stringify(db.stored).includes("media-id"));
  assert(!JSON.stringify(db.stored).includes("private"));
});
