"""SQLite-backed sync state: watermark, ID cross-reference, retry queue and run log."""
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS watermark (name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS id_xref (
    external_id TEXT PRIMARY KEY, crm_id TEXT NOT NULL, payload_hash TEXT NOT NULL, synced_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS retry_queue (
    external_id TEXT PRIMARY KEY, reason TEXT NOT NULL, attempts INTEGER NOT NULL, last_tried TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sync_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT, mode TEXT,
    fetched INTEGER, created INTEGER, updated INTEGER, unchanged INTEGER, failed INTEGER);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StateStore:
    def __init__(self, path: str = "sync_state.db"):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    # watermark
    def get_watermark(self) -> str:
        row = self.db.execute("SELECT value FROM watermark WHERE name='customers'").fetchone()
        return row[0] if row else ""

    def set_watermark(self, value: str):
        self.db.execute("INSERT INTO watermark VALUES('customers', ?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (value,))
        self.db.commit()

    # id cross-reference
    def lookup(self, external_id: str):
        return self.db.execute("SELECT crm_id, payload_hash FROM id_xref WHERE external_id=?", (external_id,)).fetchone()

    def remember(self, external_id: str, crm_id: str, h: str):
        self.db.execute("""INSERT INTO id_xref VALUES(?,?,?,?) ON CONFLICT(external_id) DO UPDATE SET
                           crm_id=excluded.crm_id, payload_hash=excluded.payload_hash, synced_at=excluded.synced_at""",
                        (external_id, crm_id, h, utcnow()))
        self.db.commit()

    # retry queue
    def queue_retry(self, external_id: str, reason: str):
        self.db.execute("""INSERT INTO retry_queue VALUES(?,?,1,?) ON CONFLICT(external_id) DO UPDATE SET
                           reason=excluded.reason, attempts=attempts+1, last_tried=excluded.last_tried""",
                        (external_id, reason, utcnow()))
        self.db.commit()

    def clear_retry(self, external_id: str):
        self.db.execute("DELETE FROM retry_queue WHERE external_id=?", (external_id,))
        self.db.commit()

    def pending_retries(self, max_attempts: int = 5) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT external_id FROM retry_queue WHERE attempts < ?", (max_attempts,))]

    def retry_report(self):
        return self.db.execute("SELECT external_id, reason, attempts FROM retry_queue ORDER BY external_id").fetchall()

    # run log
    def log_run(self, started: str, mode: str, s: dict):
        self.db.execute("INSERT INTO sync_runs(started_at, finished_at, mode, fetched, created, updated, unchanged, failed) VALUES(?,?,?,?,?,?,?,?)",
                        (started, utcnow(), mode, s["fetched"], s["created"], s["updated"], s["unchanged"], s["failed"]))
        self.db.commit()
