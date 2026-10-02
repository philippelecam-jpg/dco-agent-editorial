import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
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
  assert(page.includes('name="companyName"'));
  assert(!page.includes("Consulter le résultat GitHub"));
  assert(page.includes('id="done-title"'));
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
  const response = await worker.fetch(new Request(url), { DB: db, PUBLIC_BASE_URL: origin, LEAD_CALLBACK_SECRET: 'test', RESEND_API_KEY: 'test' });
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
    { DB: db, PUBLIC_BASE_URL: origin, LEAD_CALLBACK_SECRET: 'test', RESEND_API_KEY: 'test' },
  );
  assert.equal(response.status, 400);
  assert.equal(response.headers.get("set-cookie"), null);
  assert.match(response.headers.get('content-type'), /text\/html/);
  const page = await response.text();
  assert.match(page, /expiré/);
  assert.match(page, /Recevoir un nouveau lien/);
  assert.match(page, /href="\/\?new-link=1"/);
  assert.equal(response.headers.get('cache-control'), 'no-store');
});

test('invalid verification links show recovery without querying or writing data', async () => {
  const response = await worker.fetch(new Request(origin + '/verify?site=entreprise.fr'), {});
  assert.equal(response.status, 400);
  const body = await response.text();
  assert.match(body, /Ce lien est invalide/);
  assert.match(body, /new-link=1&amp;site=https%3A%2F%2Fentreprise.fr%2F/);
  assert.equal(response.headers.get('set-cookie'), null);
});

test('used links offer recovery without reflecting the token or unsafe site', async () => {
  const response = await worker.fetch(new Request(origin + '/verify?token=private-token&site=javascript%3A%2F%2Fevil'), {
    DB: {prepare() {return {bind() {return this;}, async first() {return null;}};}}
  });
  const body = await response.text();
  assert.match(body, /Recevoir un nouveau lien/);
  assert(!body.includes('private-token'));
  assert(!body.includes('javascript:'));
  assert.match(body, /href="\/\?new-link=1"/);
});

test('recovery opens signup even with an existing session and keeps the supplied site', async () => {
  const page = await (await worker.fetch(new Request(origin), {})).text();
  const script = page.match(/<script>([\s\S]*?)<\/script>/)[1];
  const nodes = new Map();
  const storage = new Map();
  let calls = 0;
  const location = {href: origin + '/?new-link=1&site=https%3A%2F%2Fentreprise.fr%2F'};
  const document = {getElementById(id) {
    if (!nodes.has(id)) nodes.set(id, {value:'', hidden:id==='request-stage'||id==='done-stage', textContent:'', classList:{toggle(){}}, addEventListener(){}});
    return nodes.get(id);
  }};
  vm.runInNewContext(script, {document,location,URL,history:{replaceState(_a,_b,url){location.href=origin+url;}},localStorage:{setItem(k,v){storage.set(k,v);},getItem(k){return storage.get(k);}},setInterval(){},fetch(){calls++;throw new Error('Unexpected session fetch');}});
  assert.equal(calls, 0);
  assert.equal(nodes.get('signup-site').value, 'https://entreprise.fr/');
  assert.equal(nodes.get('session-status').hidden, true);
  assert.match(nodes.get('signup-status').textContent, /nouveau lien/);
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

test("the requested company is dispatched instead of the account company", async () => {
  const db = leadDatabase('philippe@example.com');
  const savedFetch = globalThis.fetch;
  const dispatches = [];
  globalThis.fetch = async (_url, options) => {
    dispatches.push(JSON.parse(options.body));
    return new Response(null, {status: 204});
  };
  try {
    const submit = companyName => worker.fetch(new Request(origin + '/api/request', {
      method: 'POST', headers: {'content-type': 'application/json', cookie: 'rachel_session=test'},
      body: JSON.stringify({site: 'https://baresto.fr/', companyName}),
    }), {DB: db, PUBLIC_BASE_URL: origin, LEAD_CALLBACK_SECRET: 'test', RESEND_API_KEY: 'test'});
    assert.equal((await submit('  Baresto  ')).status, 201);
    assert.equal(dispatches[0].inputs.company_name, 'Baresto');
    assert.equal(dispatches[0].inputs.company_site, 'https://baresto.fr/');
    assert.equal((await submit('')).status, 400);
    assert.equal((await submit('x'.repeat(151))).status, 400);
    assert.equal(dispatches.length, 1);
    assert.equal(db.inserted.length, 1);
    assert.equal((await submit(undefined)).status, 201);
    assert.equal(dispatches[1].inputs.company_name, 'Décisions & Co');
  } finally { globalThis.fetch = savedFetch; }
});

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
        { DB: db, PUBLIC_BASE_URL: origin, LEAD_CALLBACK_SECRET: 'test', RESEND_API_KEY: 'test' },
      );
      assert.equal(response.status, 201, site);
      assert.equal((await response.json()).canRepeat, true);
    }
    assert.equal(db.inserted.length, 6);
    assert.equal(dispatches.length, 6);
    assert.equal(new Set(db.inserted.map((row) => row[0])).size, 6);
    for (const row of db.inserted) assert.equal(row[4], "decisionsandco.com");
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
      }), {DB: db, PUBLIC_BASE_URL: origin, LEAD_CALLBACK_SECRET: 'test', RESEND_API_KEY: 'test'});
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
  }), {DB: db, PUBLIC_BASE_URL: origin, LEAD_CALLBACK_SECRET: 'test', RESEND_API_KEY: 'test'});
  assert.equal(response.status, 400);
  assert.equal(db.inserted.length, 0);
});
