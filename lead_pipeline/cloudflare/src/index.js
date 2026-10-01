const COOKIE = "rachel_session";
const RACHEL_IMAGES = new Set([
  "Rachel Entreprises",
  "Rachel Super U",
  "Rachel originale",
]);

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
  if (text.length < min || text.length > max)
    throw new Error(`${label} invalide.`);
  return text;
}

function email(value) {
  const text = clean(value).toLowerCase();
  if (
    text.length > 254 ||
    !/^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}$/.test(text)
  ) {
    throw new Error("Adresse email invalide.");
  }
  return text;
}

function siteUrl(value) {
  const raw = clean(value);
  if (!raw || /\s/.test(raw)) throw new Error("Adresse du site invalide.");
  const url = new URL(raw.includes("://") ? raw : `https://${raw}`);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password
  )
    throw new Error("Site public requis.");
  if (url.port && !["80", "443"].includes(url.port))
    throw new Error("Site public requis.");
  url.protocol = "https:";
  url.hash = "";
  if (!url.pathname) url.pathname = "/";
  return url.toString();
}

function domainFromUrl(value) {
  const host = new URL(siteUrl(value)).hostname
    .toLowerCase()
    .replace(/^www\./, "");
  if (!/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/.test(host))
    throw new Error("Nom de domaine invalide.");
  return host;
}

function professionalEmailMatches(address, siteDomain) {
  const mailDomain = address.split("@")[1];
  return mailDomain === siteDomain || mailDomain.endsWith(`.${siteDomain}`);
}

async function sha256(value) {
  const data = new TextEncoder().encode(value);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(hash)]
    .map((x) => x.toString(16).padStart(2, "0"))
    .join("");
}

function token() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function cookieValue(request, name) {
  const cookie = request.headers.get("cookie") || "";
  const match = cookie.match(new RegExp(`(?:^|; )${name}=([^;]+)`));
  return match ? decodeURIComponent(match[1]) : "";
}

async function readJson(request) {
  if (!request.headers.get("content-type")?.includes("application/json"))
    throw new Error("Format JSON requis.");
  const text = await request.text();
  if (!text || text.length > 16000)
    throw new Error("Demande trop volumineuse.");
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
  const response = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`,
    {
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
    },
  );
  if (!response.ok)
    throw new Error(`GitHub dispatch refusé (${response.status}).`);
}

async function currentLead(env, request) {
  const session = cookieValue(request, COOKIE);
  if (!session) throw new Error("Session absente.");
  const sessionHash = await sha256(session);
  const row = await env.DB.prepare(
    `
    SELECT leads.* FROM leads
    JOIN verification_tokens ON verification_tokens.lead_id = leads.id
    WHERE verification_tokens.token_hash = ? AND verification_tokens.used_at IS NOT NULL
  `,
  )
    .bind(sessionHash)
    .first();
  if (!row) throw new Error("Session invalide.");
  return row;
}

async function handleSignup(env, request) {
  const data = await readJson(request);
  const address = email(data.email);
  const signupSite = data.site ? siteUrl(data.site) : null;
  const name = requireText(data.name, 2, 100, "Nom");
  const company = requireText(data.company, 2, 150, "Société");
  const leadId = crypto.randomUUID();
  const created = now();
  await env.DB.prepare(
    `
    INSERT INTO leads(id,email,name,company,created_at)
    VALUES(?,?,?,?,?)
    ON CONFLICT(email) DO UPDATE SET name=excluded.name, company=excluded.company
  `,
  )
    .bind(leadId, address, name, company, created)
    .run();
  const lead = await env.DB.prepare("SELECT id FROM leads WHERE email=?")
    .bind(address)
    .first();
  const rawToken = token();
  await env.DB.prepare(
    "UPDATE verification_tokens SET used_at=? WHERE lead_id=? AND used_at IS NULL",
  )
    .bind(created, lead.id)
    .run();
  await env.DB.prepare(
    "INSERT INTO verification_tokens(token_hash,lead_id,expires_at,created_at) VALUES(?,?,?,?)",
  )
    .bind(
      await sha256(rawToken),
      lead.id,
      new Date(Date.now() + 15 * 60 * 1000).toISOString(),
      created,
    )
    .run();
  const linkUrl = new URL("/verify", env.PUBLIC_BASE_URL);
  linkUrl.searchParams.set("token", rawToken);
  if (signupSite) linkUrl.searchParams.set("site", signupSite);
  const link = linkUrl.toString();
  await sendMail(
    env,
    address,
    "Votre accès à Rachel Entreprises",
    `<p>Votre lien personnel est valable 15 minutes.</p><p><a href="${link}">Accéder à mon espace</a></p>`,
  );
  return json({
    message: "Si cette adresse est valide, vous recevrez un lien d’accès.",
  });
}

async function handleVerify(env, request) {
  const url = new URL(request.url);
  const rawToken = clean(url.searchParams.get("token"));
  if (!rawToken) throw new Error("Lien invalide.");
  const tokenHash = await sha256(rawToken);
  const row = await env.DB.prepare(
    "SELECT * FROM verification_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at>?",
  )
    .bind(tokenHash, now())
    .first();
  if (!row) throw new Error("Lien expiré ou déjà utilisé.");
  await env.DB.prepare(
    "UPDATE verification_tokens SET used_at=? WHERE token_hash=?",
  )
    .bind(now(), tokenHash)
    .run();
  await env.DB.prepare("UPDATE leads SET verified_at=? WHERE id=?")
    .bind(now(), row.lead_id)
    .run();
  const cookie = `${COOKIE}=${encodeURIComponent(rawToken)}; Path=/; HttpOnly; SameSite=Lax; Secure; Max-Age=604800`;
  const destination = new URL("/", request.url);
  const site = url.searchParams.get("site");
  if (site) {
    try {
      destination.searchParams.set("site", siteUrl(site));
    } catch (_) {}
  }
  return new Response(null, {
    status: 303,
    headers: {
      location: destination.toString(),
      "set-cookie": cookie,
      "cache-control": "no-store",
      "referrer-policy": "no-referrer",
    },
  });
}

async function handleRequest(env, request) {
  const lead = await currentLead(env, request);
  const data = await readJson(request);
  const companySite = siteUrl(data.site);
  const companyDomain = domainFromUrl(companySite);
  if (!professionalEmailMatches(lead.email, companyDomain)) {
    throw new Error(
      "Utilisez une adresse professionnelle correspondant au domaine du site.",
    );
  }
  const sourceText = clean(data.sourceText).replace(/\s+/g, " ");
  if (sourceText && (sourceText.length < 120 || sourceText.length > 12000)) {
    throw new Error(
      "La source texte doit contenir entre 120 et 12 000 caractères.",
    );
  }
  const rachelImage = clean(data.rachelImage || "Rachel Entreprises");
  if (!RACHEL_IMAGES.has(rachelImage))
    throw new Error("Image Rachel inconnue.");
  const siren = clean(data.siren);
  if (siren && !/^\d{9}$/.test(siren)) throw new Error("SIREN invalide.");
  const id = crypto.randomUUID();
  const created = now();
  await env.DB.prepare(
    `
    INSERT INTO requests(id,lead_id,company_site,company_domain,siren,source_text,rachel_image,github_run_status,status,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?)
  `,
  )
    .bind(
      id,
      lead.id,
      companySite,
      companyDomain,
      siren || null,
      sourceText || null,
      rachelImage,
      "dispatching",
      "queued",
      created,
      created,
    )
    .run();
  await dispatchWorkflow(env, {
    mode: "video",
    company_name: lead.company,
    company_site: companySite,
    source_text: sourceText,
    rachel_image: rachelImage,
  });
  await env.DB.prepare(
    "UPDATE requests SET github_run_status=?, github_dispatch_at=?, updated_at=? WHERE id=?",
  )
    .bind("dispatched", now(), now(), id)
    .run();
  return json({ id, status: "queued" }, 201);
}

async function handleMe(env, request) {
  const lead = await currentLead(env, request);
  const currentRequest = await env.DB.prepare(
    "SELECT * FROM requests WHERE lead_id=? ORDER BY created_at DESC LIMIT 1",
  )
    .bind(lead.id)
    .first();
  return json({
    name: lead.name,
    company: lead.company,
    request: currentRequest,
  });
}

function page() {
  return html(String.raw`<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>La Fabrik — Décisions & Co</title>
<meta name="description" content="Votre entreprise en 30 secondes, présentée par Rachel. La Fabrik, par Décisions & Co.">
<style>
:root{color-scheme:light;--ink:#101a30;--muted:#687287;--teal:#197d86;--line:#e0e3e8;--paper:#fdfcfb}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:Arial,Helvetica,sans-serif}a{color:inherit}button,input,select,textarea{font:inherit}button,a,input,textarea,select,summary{outline-offset:5px}button:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid var(--teal)}[hidden]{display:none!important}.wrap{max-width:1320px;margin:auto;padding:0 44px}.top{display:flex;align-items:center;justify-content:space-between;padding-top:30px;padding-bottom:30px}.brand{text-decoration:none}.wordmark{font:600 48px/1 Georgia,serif;letter-spacing:-2px}.byline{display:block;font-size:10px;letter-spacing:3px;margin-top:10px}.channel{font:18px Georgia,serif;text-decoration:none;border-bottom:1px solid var(--line);padding-bottom:5px}.hero{display:grid;grid-template-columns:1fr 1.05fr;gap:52px;align-items:start;padding:30px 0 42px}h1{font:500 clamp(42px,5.2vw,73px)/1.06 Georgia,serif;letter-spacing:-2.5px;margin:18px 0 20px}h1 span{display:block}.subtitle{color:#49566e;line-height:1.6;font-size:16px;margin:0 0 25px;max-width:560px}.card{padding:24px;border:1px solid var(--line);border-radius:16px;background:white;box-shadow:0 8px 28px #101a3005}.card h2{font:28px Georgia,serif;margin:0 0 12px}.hint{color:var(--muted);font-size:14px;line-height:1.6;margin:0 0 20px}label{display:block;font-size:13px;margin-bottom:8px;color:#344159}.field{margin-bottom:18px}input:not([type=checkbox]),textarea,select{display:block;width:100%;border:1px solid #d6dbe3;border-radius:8px;padding:12px 13px;color:var(--ink);background:white;min-height:45px}input::placeholder,textarea::placeholder{color:#9299a7}input:focus,textarea:focus,select:focus{outline:2px solid #197d8640;border-color:var(--teal)}textarea{min-height:140px;resize:vertical}.consent{display:flex;align-items:flex-start;gap:10px;font-size:12px;line-height:1.5;margin:10px 0 18px;color:var(--muted)}.consent input{margin:2px 0 0;accent-color:var(--teal)}button.primary{width:100%;border:0;border-radius:8px;color:white;background:var(--teal);font-weight:600;padding:15px;cursor:pointer;min-height:48px}button.primary:hover{background:#12646c}button:disabled{opacity:.65;cursor:wait}.note{font-size:12px;color:var(--muted);text-align:center;margin:15px 0 0}.status{font-size:14px;line-height:1.6;padding:14px;border-radius:8px;background:#eef7f6;color:#225d60;margin-top:16px;overflow-wrap:anywhere}.status.error{background:#fff1ef;color:#9a3430}.row{display:grid;grid-template-columns:1fr 1fr;gap:14px}.preview{position:relative;border-radius:14px;overflow:hidden;min-height:530px;height:100%;background:#dce3e5;isolation:isolate}.preview img{width:100%;height:100%;position:absolute;object-fit:cover;object-position:50% 30%;z-index:-2}.preview:after{content:"";position:absolute;inset:55% 0 0;background:linear-gradient(transparent,#101a30b5);z-index:-1}.pill{position:absolute;top:22px;left:22px;color:white;background:#101a3055;border:1px solid #ffffff60;border-radius:30px;padding:9px 14px;font-size:13px}.play{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);height:72px;width:72px;display:grid;place-items:center;border-radius:50%;background:#ffffffeb;color:var(--ink)}.play svg{width:24px;height:24px;margin-left:4px}.caption{position:absolute;bottom:32px;left:28px;font:30px Georgia,serif;color:white}.duration{position:absolute;right:20px;bottom:25px;background:#101a3080;color:white;padding:6px 9px;border-radius:5px;font-size:13px}.steps{list-style:none;padding:30px 0;margin:0;display:grid;grid-template-columns:1fr 1fr 1.1fr;gap:24px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.steps li{display:flex;gap:16px;align-items:center}.number{border:1px solid var(--line);border-radius:50%;width:34px;height:34px;display:grid;place-items:center;flex-shrink:0;font:17px Georgia,serif}.icon{width:36px;height:36px;flex-shrink:0;color:var(--teal)}.step-title{font:18px/1.4 Georgia,serif}.step-note{display:block;font:11px Arial,sans-serif;color:var(--muted);margin-top:5px}footer{display:flex;justify-content:space-between;gap:20px;padding:24px 0;color:var(--muted);font-size:11px;line-height:1.6}details{border-top:1px solid var(--line);padding-top:15px;margin-bottom:18px}summary{font-size:13px;cursor:pointer;color:var(--teal);margin-bottom:15px}.back{border:0;background:none;color:var(--teal);cursor:pointer;padding:10px 0}.loading{font-size:12px;color:var(--muted);margin:8px 0}noscript p{background:#fff1ef;padding:15px}.reference{font-size:11px;color:var(--muted);margin-top:15px;overflow-wrap:anywhere}
@media(min-width:1000px){.preview{min-height:570px}}@media(max-width:900px){.wrap{padding:0 24px}.hero{gap:26px}.wordmark{font-size:40px}h1{font-size:52px}.preview{min-height:520px}.caption{font-size:24px}.steps{gap:15px}.steps li{gap:10px}.step-title{font-size:16px}.icon{width:28px}}@media(max-width:680px){.wrap{padding:0 20px}.top{padding:24px 0}.wordmark{font-size:36px}.channel{font-size:15px}.hero{grid-template-columns:1fr;padding-top:10px;gap:28px}h1{font-size:48px;letter-spacing:-1.8px;margin-top:5px}.subtitle{font-size:15px}.card{padding:20px}.preview{min-height:420px}.steps{grid-template-columns:1fr;gap:24px;padding:28px 0}.steps li{gap:18px}.step-title{font-size:19px}.icon{width:34px}footer{flex-direction:column;gap:5px}.row{grid-template-columns:1fr}}
</style></head><body>
<div class="wrap"><header class="top"><a class="brand" href="/" aria-label="La Fabrik, accueil"><span class="wordmark">La Fabrik</span><span class="byline">PAR DÉCISIONS & CO</span></a><a class="channel" href="https://www.youtube.com/@Rachel-DecisionsAndCo" target="_blank" rel="noopener noreferrer">Avec Rachel ↗</a></header>
<main><div class="hero"><section><h1>Votre entreprise.<span>En 30 secondes.</span></h1><p class="subtitle">Une capsule personnalisée, présentée par Rachel et publiée sur YouTube.</p><div class="card">
<div id="signup-stage"><form id="signup"><div class="field"><label for="email">Email professionnel</label><input id="email" name="email" type="email" autocomplete="email" maxlength="254" required></div><div class="field"><label for="signup-site">Site web de votre entreprise</label><input id="signup-site" name="site" type="text" inputmode="url" autocomplete="url" placeholder="https://votre-entreprise.fr" required></div>
<div id="identity-fields" hidden><div class="row"><div class="field"><label for="name">Prénom et nom</label><input id="name" name="name" autocomplete="name" minlength="2" maxlength="100" required disabled></div><div class="field"><label for="company">Votre entreprise</label><input id="company" name="company" autocomplete="organization" minlength="2" maxlength="150" required disabled></div></div></div>
<label class="consent"><input id="consent" type="checkbox" required><span>Je demande une capsule de démonstration et sa publication sur YouTube.</span></label><button class="primary" type="submit">Créer ma capsule</button><p class="note" id="signup-note">Une capsule offerte par entreprise. Email vérifié avant génération.</p></form><div id="signup-status" class="status" role="status" aria-live="polite" hidden></div></div>
<div id="request-stage" hidden><h2>Votre sujet, votre capsule.</h2><p id="welcome" class="hint">Votre email est vérifié. Complétez votre demande.</p><form id="request"><div class="field"><label for="site">Site web de votre entreprise</label><input id="site" name="site" inputmode="url" placeholder="https://votre-entreprise.fr" required></div><div class="field"><label for="sourceText">Votre actualité <span class="hint">(facultatif)</span></label><textarea id="sourceText" name="sourceText" maxlength="12000" placeholder="Collez une actualité ou un texte factuel. Utile si le site est inaccessible."></textarea></div><details><summary>Personnaliser la présentation</summary><div class="field"><label for="rachelImage">Présentation de Rachel</label><select id="rachelImage" name="rachelImage"><option>Rachel Entreprises</option><option>Rachel Super U</option><option>Rachel originale</option></select></div><div class="field"><label for="siren">SIREN (facultatif)</label><input id="siren" name="siren" pattern="[0-9]{9}" maxlength="9" inputmode="numeric"></div></details><button class="primary" type="submit">Lancer ma capsule</button><p class="note">Une seule demande par entreprise.</p></form><div id="request-status" class="status" role="status" aria-live="polite" hidden></div></div>
<div id="done-stage" hidden><h2>Votre demande est enregistrée.</h2><p id="done-copy" class="hint">La préparation de votre capsule est lancée.</p><div id="done-status" class="status" role="status" aria-live="polite"></div><p id="request-id" class="reference"></p><a id="video-link" class="channel" hidden target="_blank" rel="noopener noreferrer">Voir ma capsule ↗</a><button id="refresh" type="button" class="back">Actualiser le statut ↻</button></div>
<p id="session-status" class="loading" role="status">Vérification de votre accès…</p><noscript><p>Activez JavaScript pour demander votre capsule.</p></noscript></div></section>
<div class="preview"><img src="https://raw.githubusercontent.com/philippelecam-jpg/dco-agent-editorial/main/assets/Rachel_Enterprise.png" alt="Rachel, présentatrice IA de Décisions & Co" fetchpriority="high"><span class="pill">Rachel · Présentatrice IA</span><a class="play" href="https://www.youtube.com/@Rachel-DecisionsAndCo/shorts" target="_blank" rel="noopener noreferrer" aria-label="Découvrir les vidéos de Rachel sur YouTube"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M5 3v18l16-9z"/></svg></a><span class="caption">Votre actualité en vidéo</span><span class="duration">0:30</span></div></div>
<ol class="steps" aria-label="Comment ça marche"><li><span class="number">1</span><svg class="icon" viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="8" width="29" height="23" rx="2"/><path d="m4 9 13 11L31 9"/><circle cx="31" cy="30" r="7"/><path d="m28 33 6-6"/></svg><span class="step-title">Email + site web</span></li><li><span class="number">2</span><svg class="icon" viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m18 4 4 11 11 4-11 4-4 11-4-11-11-4 11-4zM33 1l2 5 5 2-5 2-2 5-2-5-5-2 5-2z"/></svg><span class="step-title">L’IA prépare votre sujet</span></li><li><span class="number">3</span><svg class="icon" viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="2" y="5" width="36" height="30" rx="5"/><path d="m16 12 11 8-11 8z"/></svg><span class="step-title">Votre capsule sur YouTube<span class="step-note">Personnalisée pour votre entreprise</span></span></li></ol></main>
<footer><span>Créée avec La Fabrik, la fabrique éditoriale de Décisions & Co.</span><span>Une démonstration par entreprise · Présentatrice IA</span></footer></div>
<script>
'use strict';
const $=id=>document.getElementById(id);
const show=(id,message,error=false)=>{const node=$(id);node.textContent=message;node.classList.toggle('error',error);node.hidden=false;};
const stage=name=>{['signup','request','done'].forEach(key=>$(key+'-stage').hidden=key!==name);};
const normalizeSite=value=>{const raw=value.trim();const url=new URL(raw.includes('://')?raw:'https://'+raw);if(!['http:','https:'].includes(url.protocol)||url.username||url.password||!url.hostname.includes('.'))throw new Error('Indiquez un site web public valide.');url.protocol='https:';url.hash='';return url.href;};
const api=async(url,payload)=>{const response=await fetch(url,payload?{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)}:{});const text=await response.text();let data;try{data=JSON.parse(text);}catch(_){throw new Error('Le service est momentanément indisponible. Réessayez dans quelques instants.');}if(!response.ok)throw new Error(data.error||'La demande a échoué.');return data;};
const busy=(form,value,label)=>{const button=form.querySelector('button[type=submit]');if(value){button.dataset.label=button.textContent;button.textContent=label;}else{button.textContent=button.dataset.label||button.textContent;}button.disabled=value;};
const saveSite=value=>{try{localStorage.setItem('fabrik_site',value);}catch(_){};};
const rememberedSite=()=>{const fromLink=new URL(location.href).searchParams.get('site');if(fromLink){try{const site=normalizeSite(fromLink);saveSite(site);history.replaceState(null,'','/');return site;}catch(_){}}try{return localStorage.getItem('fabrik_site')||'';}catch(_){return '';}};
const saved=rememberedSite();$('signup-site').value=saved;$('site').value=saved;
let identityOpen=false;
$('signup').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;let site;try{site=normalizeSite($('signup-site').value);}catch(error){show('signup-status',error.message,true);return;}$('signup-site').value=site;saveSite(site);if(!identityOpen){identityOpen=true;$('identity-fields').hidden=false;$('name').disabled=false;$('company').disabled=false;$('signup-note').textContent='Complétez votre nom et votre entreprise pour recevoir votre lien.';form.querySelector('button').textContent='Recevoir mon lien';$('name').focus();return;}busy(form,true,'Envoi du lien…');show('signup-status','Envoi en cours…');try{await api('/api/signup',Object.fromEntries(new FormData(form)));show('signup-status','Votre lien d’accès a été demandé. Vérifiez votre messagerie et les indésirables. Il est valable 15 minutes.');}catch(error){show('signup-status',error.message,true);}finally{busy(form,false);}});
const statuses={queued:'Votre capsule est en attente de génération.',processing:'Votre capsule est en préparation.',generating:'Votre capsule est en préparation.',completed:'Votre capsule est prête.',published:'Votre capsule est publiée.',failed:'La génération a rencontré un problème.',blocked:'La demande nécessite une vérification.'};
const renderRequest=request=>{stage('done');$('done-status').textContent=statuses[request.status]||'Votre demande est enregistrée.';$('request-id').textContent='Référence : '+request.id;$('done-copy').textContent='Retrouvez ici le statut de votre demande.';$('video-link').hidden=true;if(request.youtube_url){try{const url=new URL(request.youtube_url);if(url.protocol==='https:'&&['www.youtube.com','youtube.com','youtu.be'].includes(url.hostname)){$('video-link').href=url.href;$('video-link').hidden=false;}}catch(_){}}};
async function loadSession(){try{const data=await api('/api/me');if(data.request){renderRequest(data.request);}else{stage('request');$('welcome').textContent=data.company+' · Email vérifié. Complétez votre demande.';}}catch(error){if(!['Session absente.','Session invalide.'].includes(error.message)){show('session-status','Impossible de vérifier votre accès. '+error.message,true);return;}}$('session-status').hidden=true;}
$('request').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;const payload=Object.fromEntries(new FormData(form));try{payload.site=normalizeSite(payload.site);if(payload.sourceText.trim()&&payload.sourceText.trim().length<120)throw new Error('Ajoutez au moins 120 caractères à votre texte d’actualité.');}catch(error){show('request-status',error.message,true);return;}saveSite(payload.site);busy(form,true,'Enregistrement…');show('request-status','Votre demande est en cours d’enregistrement…');try{const data=await api('/api/request',payload);renderRequest(data);}catch(error){show('request-status',error.message,true);}finally{busy(form,false);}});
$('refresh').addEventListener('click',async()=>{$('refresh').disabled=true;try{await loadSession();}finally{$('refresh').disabled=false;}});
loadSession();
</script></body></html>`);
}

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      if (request.method === "GET" && url.pathname === "/") return page();
      if (request.method === "GET" && url.pathname === "/api/health")
        return json({ ok: true });
      if (request.method === "POST" && url.pathname === "/api/signup")
        return await handleSignup(env, request);
      if (request.method === "GET" && url.pathname === "/verify")
        return await handleVerify(env, request);
      if (request.method === "GET" && url.pathname === "/api/me")
        return await handleMe(env, request);
      if (request.method === "POST" && url.pathname === "/api/request")
        return await handleRequest(env, request);
      return json({ error: "Page introuvable." }, 404);
    } catch (error) {
      return json({ error: error.message || "Service indisponible." }, 400);
    }
  },
};
