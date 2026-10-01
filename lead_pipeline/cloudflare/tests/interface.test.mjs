import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

const origin = "https://fabrik.test";

test("the JavaScript actually emitted in the page parses", async () => {
  const response = await worker.fetch(new Request(origin), {});
  assert.equal(response.status, 200);
  const page = await response.text();
  const script = page.match(/<script>([\s\S]*?)<\/script>/)[1];
  assert.doesNotThrow(() => new Function(script));
  const ids = [...page.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length);
  assert(page.includes("La Fabrik"));
  assert(page.includes("Rachel_Enterprise.png"));
});

test("rejected async handlers return JSON instead of escaping the worker", async () => {
  const response = await worker.fetch(
    new Request(origin + "/api/signup", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{broken",
    }),
    {},
  );
  assert.equal(response.status, 400);
  assert.equal(typeof (await response.json()).error, "string");
});

test("email verification redirects to the interface with a normalized site", async () => {
  const db = {
    prepare(sql) {
      return {
        bind() {
          return this;
        },
        async first() {
          return sql.startsWith("SELECT") ? { lead_id: "lead-test" } : null;
        },
        async run() {
          return {};
        },
      };
    },
  };
  const url = new URL("/verify", origin);
  url.searchParams.set("token", "test-token");
  url.searchParams.set("site", "entreprise.fr");
  const response = await worker.fetch(new Request(url), { DB: db });
  assert.equal(response.status, 303);
  assert.equal(
    new URL(response.headers.get("location")).searchParams.get("site"),
    "https://entreprise.fr/",
  );
  assert.match(
    response.headers.get("set-cookie"),
    /HttpOnly; SameSite=Lax; Secure/,
  );
});

test("an expired email link does not set a session cookie", async () => {
  const db = {
    prepare() {
      return {
        bind() {
          return this;
        },
        async first() {
          return null;
        },
      };
    },
  };
  const response = await worker.fetch(
    new Request(origin + "/verify?token=expired"),
    { DB: db },
  );
  assert.equal(response.status, 400);
  assert.equal(response.headers.get("set-cookie"), null);
  assert.match((await response.json()).error, /expiré/);
});
