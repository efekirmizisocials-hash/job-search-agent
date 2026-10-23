"""SQLite job queue with additive migrations and durable submission states."""
import argparse
from contextlib import contextmanager
from dataclasses import asdict, fields
from datetime import date
import hashlib
import json
import sqlite3

from config import DB_PATH
from ats import canonical_url, detect_ats, is_open_ats
from sources.base import Job

SCHEMA = """CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
    first_seen TEXT DEFAULT (datetime('now')), status TEXT NOT NULL DEFAULT 'seen',
    match_reason TEXT, deadline TEXT, applied_at TEXT
)"""
COLUMNS = {
    'deadline': 'TEXT', 'company': "TEXT DEFAULT ''", 'source': "TEXT DEFAULT 'salto'",
    'score': 'REAL DEFAULT 0', 'verdict': "TEXT DEFAULT ''", 'gates': "TEXT DEFAULT '{}'",
    'apply_url': "TEXT DEFAULT ''", 'ats': "TEXT DEFAULT ''", 'docs_path': "TEXT DEFAULT ''",
    'job_data': "TEXT DEFAULT '{}'", 'identity_key': "TEXT DEFAULT ''",
}


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn):
    existing = {r['name'] for r in conn.execute('PRAGMA table_info(listings)')}
    for name, declaration in COLUMNS.items():
        if name not in existing:
            conn.execute(f'ALTER TABLE listings ADD COLUMN {name} {declaration}')
    conn.execute('CREATE INDEX IF NOT EXISTS listing_identity ON listings(identity_key)')
    conn.execute('CREATE TABLE IF NOT EXISTS job_urls (url TEXT PRIMARY KEY, listing_id TEXT NOT NULL)')


def init_db():
    with get_conn() as conn:
        conn.execute(SCHEMA)
        _migrate(conn)


def job_identity(job: Job) -> str:
    from vendor.job_key import make_key
    key = make_key(job.company, job.title, job.url)
    # Same role at different locations must remain distinct vacancies.
    if job.location.strip():
        location = ' '.join(job.location.casefold().split())
        key += '-' + hashlib.sha256(location.encode()).hexdigest()[:8]
    return key


def resolve_job_id(job: Job) -> str:
    key = job_identity(job)
    urls = [canonical_url(u) for u in (job.apply_url, job.url) if u]
    with get_conn() as conn:
        for url in urls:
            row = conn.execute('SELECT listing_id FROM job_urls WHERE url=?', (url,)).fetchone()
            if row:
                return row['listing_id']
            row = conn.execute('SELECT id FROM listings WHERE url=? OR apply_url=?', (url, url)).fetchone()
            if row:
                return row['id']
        rows = conn.execute('SELECT id,apply_url FROM listings WHERE identity_key=?', (key,)).fetchall()
        for row in rows:
            # Distinct employer ATS requisition URLs are not the same vacancy.
            if (is_open_ats(job.apply_url) and is_open_ats(row['apply_url'] or '')
                    and canonical_url(job.apply_url) != canonical_url(row['apply_url'])):
                continue
            return row['id']
        if rows:
            key += '-' + hashlib.sha256(canonical_url(job.apply_url or job.url).encode()).hexdigest()[:10]
    return key


def already_seen(listing_id: str) -> bool:
    with get_conn() as conn:
        return conn.execute('SELECT 1 FROM listings WHERE id=?', (listing_id,)).fetchone() is not None


def record_listing(listing_id, title, url, status, match_reason='', deadline=None):
    """Legacy-compatible status update; preserves all job metadata."""
    with get_conn() as conn:
        conn.execute('''INSERT INTO listings(id,title,url,status,match_reason,deadline)
            VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            status=excluded.status,match_reason=excluded.match_reason,
            deadline=COALESCE(excluded.deadline,listings.deadline)''',
            (listing_id, title, url, status, match_reason, deadline))


def record_job(job: Job, listing_id: str, result: dict, status: str):
    with get_conn() as conn:
        conn.execute('''INSERT INTO listings
            (id,title,url,status,match_reason,deadline,company,source,score,verdict,gates,
             apply_url,ats,job_data,identity_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO NOTHING''',
            (listing_id, job.title, job.url, status, result.get('reason',''), job.deadline,
             job.company, job.source, result.get('score',0), result.get('verdict',''),
             json.dumps(result.get('gates',{})), job.apply_url, detect_ats(job.apply_url),
             json.dumps(asdict(job)), job_identity(job)))
        for url in (job.url, job.apply_url):
            if url:
                conn.execute('INSERT OR IGNORE INTO job_urls VALUES (?,?)', (canonical_url(url), listing_id))


def entry_job(entry: dict) -> Job:
    data = json.loads(entry.get('job_data') or '{}')
    if not data:
        data = {k: entry[k] for k in ('id','title','url','source','company','apply_url','deadline') if k in entry}
    valid = {f.name for f in fields(Job)}
    return Job(**{k:v for k,v in data.items() if k in valid})


def set_status(listing_id: str, status: str, reason: str = '', docs_path: str | None = None):
    with get_conn() as conn:
        conn.execute('''UPDATE listings SET status=?,match_reason=?,docs_path=COALESCE(?,docs_path)
                        WHERE id=?''', (status,reason,docs_path,listing_id))


def claim_submission(listing_id: str) -> bool:
    """Durably record intent BEFORE clicking; crashes must never cause re-submission."""
    with get_conn() as conn:
        result = conn.execute("UPDATE listings SET status='submitting' WHERE id=? AND status='suitable'", (listing_id,))
        return result.rowcount == 1


def get_application_queue(limit: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute('''SELECT * FROM listings WHERE status='suitable'
            AND (deadline IS NULL OR deadline='' OR deadline>=?)
            ORDER BY score DESC, (deadline IS NULL OR deadline=''), deadline ASC, id LIMIT ?''',
            (date.today().isoformat(), limit)).fetchall()
        return [dict(r) for r in rows]


def get_by_status(status: str) -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute('''SELECT * FROM listings WHERE status=?
            ORDER BY (deadline IS NULL OR deadline=''), deadline, first_seen, id''', (status,))]


def get_pending():
    return get_by_status('pending')


def get_manual():
    return get_by_status('ready_manual')


def requeue(listing_id: str):
    with get_conn() as conn:
        conn.execute("UPDATE listings SET status='suitable' WHERE id=? AND status IN ('pending','failed')", (listing_id,))


def mark_skipped(listing_id: str, note='rejected by user via Telegram'):
    set_status(listing_id, 'skipped', note)


def mark_applied(listing_id: str):
    with get_conn() as conn:
        conn.execute("UPDATE listings SET status='applied',applied_at=datetime('now') WHERE id=?", (listing_id,))


def print_status():
    with get_conn() as conn:
        for row in conn.execute('SELECT * FROM listings ORDER BY score DESC,deadline,id'):
            print(f"[{row['status']}] {row['score'] or 0:.1f} | {row['deadline'] or '?'} | {row['title']}")
            if row['match_reason']:
                print(f"  {row['match_reason']}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--init', action='store_true')
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    if args.init:
        init_db()
    if args.status:
        print_status()
