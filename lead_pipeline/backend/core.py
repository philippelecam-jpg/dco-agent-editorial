"""Durable reservations and email verification; Python 3.11 standard library."""
import hashlib, ipaddress, json, os, re, secrets, socket, sqlite3, time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

class Rejected(ValueError):
    pass

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def email(value):
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}", value):
        raise Rejected('Adresse email invalide.')
    return value

def domain(value):
    parsed = urlsplit(value if '://' in value else 'https://' + value)
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.port not in (None, 80, 443):
        raise Rejected('Indiquez un site public HTTP ou HTTPS.')
    host = (parsed.hostname or '').lower().rstrip('.').encode('idna').decode()
    if host.startswith('www.'): host = host[4:]
    try:
        ipaddress.ip_address(host)
        raise Rejected('Une adresse IP ne peut pas identifier une entreprise.')
    except ValueError as exc:
        if isinstance(exc, Rejected): raise
    if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}', host):
        raise Rejected('Nom de domaine invalide.')
    if host.endswith(('.localhost', '.local', '.internal', '.test')):
        raise Rejected('Le site doit être public.')
    return host

def site_url(value):
    """Normalize pasted input without discarding www, path or query."""
    if not isinstance(value,str): raise Rejected('Adresse du site invalide.')
    value=value.strip()
    if not value or any(char.isspace() for char in value): raise Rejected('Adresse du site invalide.')
    parsed=urlsplit(value if '://' in value else 'https://'+value)
    domain(value)  # Shared validation; canonical domain is used only for uniqueness.
    host=(parsed.hostname or '').lower().rstrip('.').encode('idna').decode()
    return urlunsplit(('https',host,parsed.path or '/',parsed.query,''))

def public_ips(host):
    addresses = sorted({r[4][0] for r in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise Rejected('Adresse réseau non publique.')
    return addresses

class Store:
    def __init__(self, path=None):
        self.path = path or os.getenv('DATABASE_PATH', 'data/leads.sqlite3')
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS leads(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,name TEXT NOT NULL,company TEXT NOT NULL,verified INTEGER DEFAULT 0,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY,lead_id TEXT NOT NULL,kind TEXT NOT NULL,expires REAL NOT NULL,used INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,lead_id TEXT UNIQUE NOT NULL,domain TEXT UNIQUE NOT NULL,siren TEXT UNIQUE,status TEXT NOT NULL,data TEXT NOT NULL DEFAULT '{}',error TEXT,created REAL NOT NULL,updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY,request_id TEXT,provider TEXT,operation TEXT,units TEXT,created REAL);
            CREATE TABLE IF NOT EXISTS mail(id TEXT PRIMARY KEY,lead_id TEXT,subject TEXT,html TEXT,sent INTEGER DEFAULT 0,created REAL);
            CREATE TABLE IF NOT EXISTS rate_limits(key TEXT PRIMARY KEY,count INTEGER NOT NULL,expires REAL NOT NULL);
            ''')
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        return db
    def limit(self, key, maximum=5, seconds=3600):
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM rate_limits WHERE expires < ?', (now,))
            db.execute('INSERT INTO rate_limits VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1', (key, now+seconds))
            count = db.execute('SELECT count FROM rate_limits WHERE key=?', (key,)).fetchone()[0]
        if count > maximum: raise Rejected('Trop de tentatives. Réessayez plus tard.')
    def signup(self, address, name, company):
        address = email(address)
        name, company = name.strip(), company.strip()
        if not (2 <= len(name) <= 100 and 2 <= len(company) <= 150): raise Rejected('Nom et société requis.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM leads WHERE email=?', (address,)).fetchone()
            lead_id = row['id'] if row else secrets.token_hex(16)
            if not row: db.execute('INSERT INTO leads(id,email,name,company,created) VALUES (?,?,?,?,?)', (lead_id,address,name,company,time.time()))
            token = secrets.token_urlsafe(32)
            db.execute("UPDATE tokens SET used=1 WHERE lead_id=? AND kind='verify'", (lead_id,))
            db.execute('INSERT INTO tokens VALUES (?,?,?, ?,0)', (digest(token),lead_id,'verify',time.time()+900))
        return lead_id, token
    def verify(self, token):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM tokens WHERE hash=? AND kind='verify' AND used=0 AND expires>?", (digest(token),time.time())).fetchone()
            if not row: raise Rejected('Lien expiré ou déjà utilisé. Demandez un nouveau lien.')
            db.execute('UPDATE tokens SET used=1 WHERE hash=?', (digest(token),))
            db.execute('UPDATE leads SET verified=1 WHERE id=?', (row['lead_id'],))
            session = secrets.token_urlsafe(32)
            db.execute('INSERT INTO tokens VALUES (?,?,?, ?,0)', (digest(session),row['lead_id'],'session',time.time()+86400*7))
        return session
    def lead(self, session):
        with self.connect() as db:
            row = db.execute("SELECT l.* FROM leads l JOIN tokens t ON t.lead_id=l.id WHERE t.hash=? AND t.kind='session' AND t.expires>? AND l.verified=1", (digest(session),time.time())).fetchone()
        if not row: raise Rejected('Vérifiez votre email pour accéder à cet espace.')
        return dict(row)
    def reserve(self, session, site, acknowledged, siren=None):
        lead = self.lead(session)
        source_url = site_url(site)
        host = domain(source_url)
        if acknowledged is not True: raise Rejected('Confirmez avoir lu les conditions de diffusion.')
        mail_host = domain(lead['email'].split('@')[1])
        if mail_host != host and not mail_host.endswith('.'+host):
            raise Rejected('Utilisez une adresse professionnelle correspondant au domaine du site.')
        if siren and not re.fullmatch(r'\d{9}', siren): raise Rejected('SIREN invalide.')
        now, request_id = time.time(), secrets.token_hex(16)
        try:
            with self.connect() as db:
                db.execute('INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?)', (request_id,lead['id'],host,siren,'queued',json.dumps({'acknowledged_at':now,'terms_version':'2026-09-v1','site_url':source_url}),None,now,now))
        except sqlite3.IntegrityError:
            raise Rejected('Une démonstration a déjà été demandée avec cet email, ce site ou ce SIREN.')
        return request_id
    def request_for(self, lead_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM requests WHERE lead_id=?', (lead_id,)).fetchone()
        return dict(row) if row else None
    def get(self, request_id):
        with self.connect() as db:
            row = db.execute('SELECT r.*,l.email,l.name,l.company FROM requests r JOIN leads l ON l.id=r.lead_id WHERE r.id=?', (request_id,)).fetchone()
        return dict(row) if row else None
    def checkpoint(self, request_id, status, data, error=None):
        with self.connect() as db:
            db.execute('UPDATE requests SET status=?,data=?,error=?,updated=? WHERE id=?', (status,json.dumps(data,ensure_ascii=False),error,time.time(),request_id))
    def usage(self, request_id, provider, operation, units):
        with self.connect() as db:
            db.execute('INSERT INTO usage(request_id,provider,operation,units,created) VALUES (?,?,?,?,?)', (request_id,provider,operation,json.dumps(units),time.time()))
    def queue_mail(self, key, lead_id, subject, html):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO mail VALUES (?,?,?,?,0,?)', (key,lead_id,subject,html,time.time()))
    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT id FROM requests WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row: db.execute("UPDATE requests SET status='research',updated=? WHERE id=?", (time.time(),row['id']))
        return row['id'] if row else None
