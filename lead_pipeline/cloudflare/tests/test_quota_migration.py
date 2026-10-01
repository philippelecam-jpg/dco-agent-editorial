"""Exercise the real SQLite constraints before and after the D1 migration."""
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class QuotaMigrationTests(unittest.TestCase):
    def insert(self, db, key, lead, domain, siren=None):
        db.execute("""INSERT INTO requests
            (id,lead_id,company_site,company_domain,siren,rachel_image,github_run_status,status,created_at,updated_at)
            VALUES(?,?,?,?,?,'Rachel Tertiaire','dispatched','queued','2026-10-01','2026-10-01')""",
            (key, lead, 'https://' + domain, domain, siren))

    def check_constraints(self, db):
        self.insert(db, 'dco-repeat', 'lead-dco', 'decisionsandco.com', '123456789')
        self.insert(db, 'dco-other-email', 'lead-other', 'decisionsandco.com', '123456789')
        self.insert(db, 'ordinary', 'lead-dco', 'example.fr', '123456789')
        for key, lead, host, siren in [
            ('duplicate-email', 'lead-dco', 'other.fr', None),
            ('duplicate-site', 'new-lead', 'example.fr', None),
            ('duplicate-siren', 'new-lead', 'other.fr', '123456789'),
        ]:
            with self.assertRaises(sqlite3.IntegrityError):
                self.insert(db, key, lead, host, siren)

    def test_existing_database_preserves_history_and_excludes_dco_from_quota(self):
        db = sqlite3.connect(':memory:')
        # Reproduce the original inline constraints in the deployed database.
        schema = (ROOT / 'schema.sql').read_text().split('CREATE UNIQUE INDEX')[0]
        schema = schema.replace('lead_id TEXT NOT NULL,\n  company_site', 'lead_id TEXT NOT NULL UNIQUE,\n  company_site')
        schema = schema.replace('company_domain TEXT NOT NULL,', 'company_domain TEXT NOT NULL UNIQUE,')
        schema = schema.replace('siren TEXT,', 'siren TEXT UNIQUE,')
        db.executescript(schema)
        self.insert(db, 'dco-original', 'lead-dco', 'decisionsandco.com', '123456789')
        before = db.execute('SELECT * FROM requests').fetchall()
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert(db, 'blocked-before', 'lead-dco', 'decisionsandco.com')
        db.executescript((ROOT / 'migrations/0001_unlimited_decisionsandco.sql').read_text())
        self.assertEqual(db.execute('SELECT * FROM requests').fetchall(), before)
        self.check_constraints(db)
        db.close()

    def test_fresh_schema_has_the_same_constraints(self):
        db = sqlite3.connect(':memory:')
        db.executescript((ROOT / 'schema.sql').read_text())
        self.check_constraints(db)
        db.close()

if __name__ == '__main__':
    unittest.main()
