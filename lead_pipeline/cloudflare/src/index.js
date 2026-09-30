const COOKIE = "rachel_session";
const RACHEL_IMAGES = new Set(["Rachel Entreprises", "Rachel Super U", "Rachel originale"]);

function json(payload, status = 200, headers = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
      ...headers,
    },
  });
}

function html(body, status = 200, headers = {}) {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
      ...headers,
    },
  });
}

function now() {
  return new Date().toISOString();
}

function clean(value) {
  return String(value || "").trim();
}

function requireText(value, min, max, label) {
  const text = clean(value).replace(/\s+/g, " ");
  if (text.length < min || text.length > max) throw new Error(`${label} invalide.`);
  return text;
}

function email(value) {
  const text = clean(value).toLowerCase();
  if (text.length > 254 || !/^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}$/.test(text)) {
    throw new Error("Adresse email invalide.");
  }
  return text;
}

function siteUrl(value) {
  const raw = clean(value);
  if (!raw || /\s/.test(raw)) throw new Error("Adresse du site invalide.");
  const url = new URL(raw.includes("://") ? raw : `https://${raw}`);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error("Site public requis.");
  if (url.port && !["80", "443"].includes(url.port)) throw new Error("Site public requis.");
  url.protocol = "https:";
  url.hash = "";
  if (!url.pathname) url.pathname = "/";
  return url.toString();
}

function domainFromUrl(value) {
  const host = new URL(siteUrl(value)).hostname.toLowerCase().replace(/^www\./, "");
  if (!/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/.test(host)) throw new Error("Nom de domaine invalide.");
  return host;
}

function professionalEmailMatches(address, siteDomain) {
  const mailDomain = address.split("@")[1];
  return mailDomain === siteDomain || mailDomain.endsWith(`.${siteDomain}`);
}

async function sha256(value) {
  const data = new TextEncoder().encode(value);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(hash)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

function token() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function cookieValue(request, name) {
  const cookie = request.headers.get("cookie") || "";
  const match = cookie.match(new RegExp(`(?:^|; )${name}=([^;]+)`));
  return match ? decodeURIComponent(match[1]) : "";
}

async function readJson(request) {
  if (!request.headers.get("content-type")?.includes("application/json")) throw new Error("Format JSON requis.");
  const text = await request.text();
  if (!text || text.length > 16000) throw new Error("Demande trop volumineuse.");
  return JSON.parse(text);
}

async function sendMail(env, to, subject, messageHtml) {
  if (!env.RESEND_API_KEY) return { skipped: true };
  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.RESEND_API_KEY}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      from: env.EMAIL_FROM,
      to,
      subject,
      html: messageHtml,
    }),
  });
  if (!response.ok) throw new Error("Envoi email indisponible.");
  return response.json();
}

async function dispatchWorkflow(env, inputs) {
  const owner = env.GITHUB_OWNER || "philippelecam-jpg";
  const repo = env.GITHUB_REPO || "dco-agent-editorial";
  const workflow = env.GITHUB_WORKFLOW_ID || "rachel-entreprises-test.yml";
  const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "content-type": "application/json",
      "user-agent": "dco-rachel-entreprises",
    },
    body: JSON.stringify({
      ref: env.GITHUB_REF || "main",
      inputs,
    }),
  });
  if (!response.ok) throw new Error(`GitHub dispatch refusé (${response.status}).`);
}

async function currentLead(env, request) {
  const session = cookieValue(request, COOKIE);
  if (!session) throw new Error("Session absente.");
  const sessionHash = await sha256(session);
  const row = await env.DB.prepare(`
    SELECT leads.* FROM leads
    JOIN verification_tokens ON verification_tokens.lead_id = leads.id
    WHERE verification_tokens.token_hash = ? AND verification_tokens.used_at IS NOT NULL
  `).bind(sessionHash).first();
  if (!row) throw new Error("Session invalide.");
  return row;
}

async function handleSignup(env, request) {
  const data = await readJson(request);
  const address = email(data.email);
  const name = requireText(data.name, 2, 100, "Nom");
  const company = requireText(data.company, 2, 150, "Société");
  const leadId = crypto.randomUUID();
  const created = now();
  await env.DB.prepare(`
    INSERT INTO leads(id,email,name,company,created_at)
    VALUES(?,?,?,?,?)
    ON CONFLICT(email) DO UPDATE SET name=excluded.name, company=excluded.company
  `).bind(leadId, address, name, company, created).run();
  const lead = await env.DB.prepare("SELECT id FROM leads WHERE email=?").bind(address).first();
  const rawToken = token();
  await env.DB.prepare("UPDATE verification_tokens SET used_at=? WHERE lead_id=? AND used_at IS NULL")
    .bind(created, lead.id).run();
  await env.DB.prepare("INSERT INTO verification_tokens(token_hash,lead_id,expires_at,created_at) VALUES(?,?,?,?)")
    .bind(await sha256(rawToken), lead.id, new Date(Date.now() + 15 * 60 * 1000).toISOString(), created).run();
  const link = `${env.PUBLIC_BASE_URL}/verify?token=${encodeURIComponent(rawToken)}`;
  await sendMail(env, address, "Votre accès à Rachel Entreprises", `<p>Votre lien personnel est valable 15 minutes.</p><p><a href="${link}">Accéder à mon espace</a></p>`);
  return json({ message: "Si cette adresse est valide, vous recevrez un lien d’accès." });
}

async function handleVerify(env, request) {
  const url = new URL(request.url);
  const rawToken = clean(url.searchParams.get("token"));
  if (!rawToken) throw new Error("Lien invalide.");
  const tokenHash = await sha256(rawToken);
  const row = await env.DB.prepare("SELECT * FROM verification_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at>?")
    .bind(tokenHash, now()).first();
  if (!row) throw new Error("Lien expiré ou déjà utilisé.");
  await env.DB.prepare("UPDATE verification_tokens SET used_at=? WHERE token_hash=?").bind(now(), tokenHash).run();
  await env.DB.prepare("UPDATE leads SET verified_at=? WHERE id=?").bind(now(), row.lead_id).run();
  const cookie = `${COOKIE}=${encodeURIComponent(rawToken)}; Path=/; HttpOnly; SameSite=Lax; Secure; Max-Age=604800`;
  return html("<p>Email vérifié. Vous pouvez revenir à Rachel Entreprises.</p>", 200, { "set-cookie": cookie });
}

async function handleRequest(env, request) {
  const lead = await currentLead(env, request);
  const data = await readJson(request);
  const companySite = siteUrl(data.site);
  const companyDomain = domainFromUrl(companySite);
  if (!professionalEmailMatches(lead.email, companyDomain)) {
    throw new Error("Utilisez une adresse professionnelle correspondant au domaine du site.");
  }
  const sourceText = clean(data.sourceText).replace(/\s+/g, " ");
  if (sourceText && (sourceText.length < 120 || sourceText.length > 12000)) {
    throw new Error("La source texte doit contenir entre 120 et 12 000 caractères.");
  }
  const rachelImage = clean(data.rachelImage || "Rachel Entreprises");
  if (!RACHEL_IMAGES.has(rachelImage)) throw new Error("Image Rachel inconnue.");
  const siren = clean(data.siren);
  if (siren && !/^\d{9}$/.test(siren)) throw new Error("SIREN invalide.");
  const id = crypto.randomUUID();
  const created = now();
  await env.DB.prepare(`
    INSERT INTO requests(id,lead_id,company_site,company_domain,siren,source_text,rachel_image,github_run_status,status,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?)
  `).bind(id, lead.id, companySite, companyDomain, siren || null, sourceText || null, rachelImage, "dispatching", "queued", created, created).run();
  await dispatchWorkflow(env, {
    mode: "video",
    company_name: lead.company,
    company_site: companySite,
    source_text: sourceText,
    rachel_image: rachelImage,
  });
  await env.DB.prepare("UPDATE requests SET github_run_status=?, github_dispatch_at=?, updated_at=? WHERE id=?")
    .bind("dispatched", now(), now(), id).run();
  return json({ id, status: "queued" }, 201);
}

async function handleMe(env, request) {
  const lead = await currentLead(env, request);
  const currentRequest = await env.DB.prepare("SELECT * FROM requests WHERE lead_id=? ORDER BY created_at DESC LIMIT 1")
    .bind(lead.id).first();
  return json({
    name: lead.name,
    company: lead.company,
    request: currentRequest,
  });
}

function page() {
  return html(`<!doctype html>
<html lang="fr">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rachel Entreprises</title>
<style>
  :root { color-scheme: light; --ink:#162033; --muted:#5f6b7a; --line:#d9dee8; --accent:#1d4ed8; --soft:#f5f7fb; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:var(--ink); background:#fff; }
  main { max-width: 1040px; margin: 0 auto; padding: 48px 20px 64px; }
  header { display:grid; gap: 12px; max-width: 760px; margin-bottom: 32px; }
  h1 { margin:0; font-size: clamp(32px, 5vw, 56px); line-height:1; letter-spacing:0; }
  h2 { margin:0 0 16px; font-size: 22px; }
  p { color:var(--muted); line-height:1.55; }
  .grid { display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; align-items:start; }
  section { border:1px solid var(--line); border-radius:8px; padding:22px; background:#fff; }
  label { display:block; font-size: 14px; font-weight: 650; margin: 14px 0 6px; }
  input, textarea, select { width:100%; border:1px solid var(--line); border-radius:6px; padding:12px; font:inherit; background:#fff; color:var(--ink); }
  textarea { min-height: 120px; resize: vertical; }
  button { margin-top:16px; border:0; border-radius:6px; padding:12px 16px; font:inherit; font-weight:700; color:#fff; background:var(--accent); cursor:pointer; }
  button:disabled { opacity:.55; cursor:not-allowed; }
  .status { margin-top:16px; padding:12px; border-radius:6px; background:var(--soft); color:var(--muted); white-space:pre-wrap; }
  .hidden { display:none; }
  .fine { font-size:13px; color:var(--muted); }
  @media (max-width: 800px) { .grid { grid-template-columns: 1fr; } main { padding-top: 28px; } }
</style>
<body>
  <main>
    <header>
      <h1>Rachel Entreprises</h1>
      <p>Créez une capsule vidéo de démonstration à partir de votre site ou d’un texte source factuel. Un email professionnel est vérifié avant toute génération.</p>
    </header>
    <div class="grid">
      <section id="signup-card">
        <h2>1. Demander un accès</h2>
        <form id="signup">
          <label for="email">Email professionnel</label>
          <input id="email" name="email" type="email" autocomplete="email" required>
          <label for="name">Nom</label>
          <input id="name" name="name" autocomplete="name" required>
          <label for="company">Société</label>
          <input id="company" name="company" autocomplete="organization" required>
          <button type="submit">Recevoir le lien</button>
        </form>
        <div id="signup-status" class="status hidden"></div>
      </section>
      <section id="request-card">
        <h2>2. Préparer la capsule</h2>
        <form id="request">
          <label for="site">Site officiel ou page publique</label>
          <input id="site" name="site" placeholder="https://www.entreprise.fr" required>
          <label for="siren">SIREN optionnel</label>
          <input id="siren" name="siren" inputmode="numeric" maxlength="9">
          <label for="rachelImage">Image Rachel</label>
          <select id="rachelImage" name="rachelImage">
            <option>Rachel Entreprises</option>
            <option>Rachel Super U</option>
            <option>Rachel originale</option>
          </select>
          <label for="sourceText">Source texte optionnelle</label>
          <textarea id="sourceText" name="sourceText" placeholder="À utiliser si le site bloque la collecte : collez un texte factuel de 120 à 12 000 caractères."></textarea>
          <p class="fine">Une seule demande est possible par email, domaine et SIREN.</p>
          <button type="submit">Lancer la génération</button>
        </form>
        <div id="request-status" class="status hidden"></div>
      </section>
    </div>
  </main>
  <script>
    const show = (id, message) => {
      const node = document.getElementById(id);
      node.textContent = message;
      node.classList.remove("hidden");
    };
    const post = async (url, payload) => {
      const response = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Erreur");
      return data;
    };
    document.getElementById("signup").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      try {
        await post("/api/signup", Object.fromEntries(form));
        show("signup-status", "Lien envoyé si l’adresse est valide. Vérifiez votre messagerie.");
      } catch (error) {
        show("signup-status", error.message);
      }
    });
    document.getElementById("request").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const payload = Object.fromEntries(form);
      try {
        const data = await post("/api/request", payload);
        show("request-status", "Demande enregistrée. Identifiant : " + data.id);
      } catch (error) {
        show("request-status", error.message);
      }
    });
    (async () => {
      try {
        const response = await fetch("/api/me");
        if (!response.ok) return;
        const data = await response.json();
        const message = data.request
          ? "Connecté : " + data.company + "\\nDernière demande : " + data.request.status
          : "Connecté : " + data.company + "\\nVous pouvez lancer une demande.";
        show("request-status", message);
      } catch (_) {}
    })();
  </script>
</body>
</html>`);
}

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      if (request.method === "GET" && url.pathname === "/") return page();
      if (request.method === "GET" && url.pathname === "/api/health") return json({ ok: true });
      if (request.method === "POST" && url.pathname === "/api/signup") return handleSignup(env, request);
      if (request.method === "GET" && url.pathname === "/verify") return handleVerify(env, request);
      if (request.method === "GET" && url.pathname === "/api/me") return handleMe(env, request);
      if (request.method === "POST" && url.pathname === "/api/request") return handleRequest(env, request);
      return json({ error: "Page introuvable." }, 404);
    } catch (error) {
      return json({ error: error.message || "Service indisponible." }, 400);
    }
  },
};
