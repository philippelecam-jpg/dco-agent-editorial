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
  assert(page.includes("Rachel%20Tertiaire.png"));
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

function leadDatabase(address) {
  const inserted = [];
  return {
    inserted,
    prepare(sql) {
      let values;
      return {
        bind(...args) {
          values = args;
          return this;
        },
        async first() {
          return {
            id: "verified-lead",
            email: address,
            company: "Décisions & Co",
          };
        },
        async run() {
          if (sql.includes("INSERT INTO requests")) inserted.push(values);
          return {};
        },
      };
    },
  };
}

test("verified emails can repeatedly request D&Co across pasted URL variants", async () => {
  const db = leadDatabase("test@another-company.fr");
  const savedFetch = globalThis.fetch;
  const dispatches = [];
  globalThis.fetch = async (_url, options) => {
    dispatches.push(JSON.parse(options.body));
    return new Response(null, { status: 204 });
  };
  try {
    for (const site of [
      "decisionsandco.com",
      "www.decisionsandco.com",
      "https://www.decisionsandco.com",
      "https://decisionsandco.com",
      "https:\\www.decisionsandco.com",
      "https:\\\\decisionsandco.com,",
    ]) {
      const response = await worker.fetch(
        new Request(origin + "/api/request", {
          method: "POST",
          headers: {
            "content-type": "application/json",
            cookie: "rachel_session=test",
          },
          body: JSON.stringify({
            site,
            rachelImage: "Rachel Tertiaire",
            siren: "123456789",
          }),
        }),
        { DB: db },
      );
      assert.equal(response.status, 201, site);
      assert.equal((await response.json()).canRepeat, true);
    }
    assert.equal(db.inserted.length, 6);
    assert.equal(dispatches.length, 6);
    assert.equal(new Set(db.inserted.map((row) => row[0])).size, 6);
    for (const row of db.inserted) assert.equal(row[3], "decisionsandco.com");
  } finally {
    globalThis.fetch = savedFetch;
  }
});

test("different email domains are accepted without granting unlimited requests", async () => {
  const savedFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(null, {status: 204});
  try {
    for (const site of ['https://decisionsandco.com.example.fr', 'https://other-company.fr', 'https://test.decisionsandco.com']) {
      const db = leadDatabase('dirigeant@gmail.com');
      const response = await worker.fetch(new Request(origin + '/api/request', {
        method: 'POST', headers: {'content-type': 'application/json', cookie: 'rachel_session=test'},
        body: JSON.stringify({site}),
      }), {DB: db});
      assert.equal(response.status, 201);
      assert.equal((await response.json()).canRepeat, false);
      assert.equal(db.inserted.length, 1);
    }
  } finally { globalThis.fetch = savedFetch; }
});

test("an unverified email still cannot submit a request", async () => {
  const db = leadDatabase('dirigeant@gmail.com');
  const response = await worker.fetch(new Request(origin + '/api/request', {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({site: 'https://other-company.fr'}),
  }), {DB: db});
  assert.equal(response.status, 400);
  assert.equal(db.inserted.length, 0);
});
