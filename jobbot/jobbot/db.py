"""SQLite store. Tracks every job seen plus your application status."""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Iterable

from .config import output_dir
from .models import Job

STATUSES = ("new", "shortlisted", "applied", "rejected", "interview", "offer",
            "skipped", "closed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    uid             TEXT PRIMARY KEY,
    source          TEXT, company TEXT, title TEXT, location TEXT,
    url             TEXT, description TEXT, employment_type TEXT,
    posted_at       TEXT, external_id TEXT,
    score           INTEGER, matched TEXT, reasons TEXT,
    status          TEXT DEFAULT 'new',
    note            TEXT DEFAULT '',
    first_seen      TEXT DEFAULT CURRENT_TIMESTAMP,
    status_changed  TEXT
);
CREATE INDEX IF NOT EXISTS idx_score  ON jobs(score DESC);
CREATE INDEX IF NOT EXISTS idx_status ON jobs(status);
"""


def _path() -> str:
    return os.path.join(output_dir(), "jobs.db")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert(conn: sqlite3.Connection, jobs: Iterable[Job]) -> tuple[int, int]:
    """Insert new jobs, refresh score/description on ones already seen.

    Your status/note are never overwritten — a re-fetch must not undo a
    decision you already made about a posting.
    """
    new = updated = 0
    for j in jobs:
        row = conn.execute("SELECT uid FROM jobs WHERE uid=?", (j.uid,)).fetchone()
        payload = (
            j.source, j.company, j.title, j.location, j.url, j.description,
            j.employment_type, j.posted_at, j.external_id, j.score,
            json.dumps(j.matched, ensure_ascii=False),
            json.dumps(j.reasons, ensure_ascii=False),
        )
        if row:
            conn.execute("""
                UPDATE jobs SET source=?, company=?, title=?, location=?, url=?,
                       description=?, employment_type=?, posted_at=?, external_id=?,
                       score=?, matched=?, reasons=? WHERE uid=?""",
                payload + (j.uid,))
            updated += 1
        else:
            conn.execute("""
                INSERT INTO jobs (uid, source, company, title, location, url, description,
                       employment_type, posted_at, external_id, score, matched, reasons)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (j.uid,) + payload)
            new += 1
    conn.commit()
    return new, updated


def query(conn, *, status: str | None = None, min_score: int = 0, limit: int = 200):
    sql = "SELECT * FROM jobs WHERE score >= ?"
    args: list = [min_score]
    if status:
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY score DESC, company ASC LIMIT ?"
    args.append(limit)
    return conn.execute(sql, args).fetchall()


def get(conn, uid: str):
    return conn.execute("SELECT * FROM jobs WHERE uid=?", (uid,)).fetchone()


def set_status(conn, uid: str, status: str, note: str = "") -> bool:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    cur = conn.execute(
        "UPDATE jobs SET status=?, status_changed=datetime('now'), "
        "note=CASE WHEN ?='' THEN note ELSE ? END WHERE uid=?",
        (status, note, note, uid))
    conn.commit()
    return cur.rowcount > 0


def backup_statuses(conn) -> str:
    """Snapshot every non-'new' status to JSON.

    Application history is the one thing here that cannot be re-fetched, so it
    gets written to disk before anything destructive runs.
    """
    rows = conn.execute(
        "SELECT uid, company, title, url, status, note, status_changed "
        "FROM jobs WHERE status != 'new'").fetchall()
    path = os.path.join(output_dir(), "status_backup.json")
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                existing = {r["uid"]: r for r in json.load(fh)}
        except Exception:
            existing = {}
    for r in rows:
        existing[r["uid"]] = dict(r)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(list(existing.values()), fh, ensure_ascii=False, indent=1)
    return path


def restore_statuses(conn) -> int:
    """Re-apply a status backup. Matches on uid first, then company+title."""
    path = os.path.join(output_dir(), "status_backup.json")
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as fh:
        saved = json.load(fh)

    restored = 0
    for rec in saved:
        cur = conn.execute("SELECT status FROM jobs WHERE uid=?", (rec["uid"],)).fetchone()
        if cur:
            if cur["status"] == "new":
                conn.execute("UPDATE jobs SET status=?, note=?, status_changed=? WHERE uid=?",
                             (rec["status"], rec.get("note", ""),
                              rec.get("status_changed"), rec["uid"]))
                restored += 1
            continue
        # uid changes when a source or requisition id changes; fall back to identity
        hit = conn.execute(
            "SELECT uid FROM jobs WHERE lower(company)=lower(?) AND lower(title)=lower(?) "
            "AND status='new'", (rec.get("company", ""), rec.get("title", ""))).fetchone()
        if hit:
            conn.execute("UPDATE jobs SET status=?, note=?, status_changed=? WHERE uid=?",
                         (rec["status"], rec.get("note", ""),
                          rec.get("status_changed"), hit["uid"]))
            restored += 1
    conn.commit()
    return restored


def purge_duplicates(conn) -> int:
    """Remove duplicate rows already stored, using the shared dedupe rules."""
    from . import dedupe as _dd

    class _Row:
        __slots__ = ("uid", "company", "title", "url", "description",
                     "source", "score", "status")

        def __init__(self, r):
            for k in self.__slots__:
                setattr(self, k, r[k])

    rows = [_Row(r) for r in conn.execute(
        "SELECT uid, company, title, url, description, source, score, status FROM jobs")]
    drops = _dd.find_duplicates(rows)

    removed = 0
    for _keep, drop in drops:
        cur = conn.execute("DELETE FROM jobs WHERE uid=?", (rows[drop].uid,))
        removed += cur.rowcount
    conn.commit()
    return removed


# Only a company's own job board is authoritative about what is still open.
# An aggregator returns whatever its query matched today, so a posting missing
# from this run's results usually means the query ranked differently — not that
# the job closed. Closing on that signal silently deletes live opportunities.
AUTHORITATIVE_SOURCES = ("greenhouse", "ashby", "personio", "lever",
                         "recruitee", "smartrecruiters", "workable", "workday")


def mark_closed(conn, seen_uids: set[str], live_companies: set[str]) -> int:
    """Flag postings that vanished from a company's own board as closed.

    Only companies whose fetch succeeded are considered, so a network error
    never mass-closes a company's jobs. Anything you have already acted on
    keeps its status — knowing you applied matters more than knowing it closed.
    """
    if not live_companies:
        return 0
    placeholders = ",".join("?" * len(live_companies))
    src = ",".join("?" * len(AUTHORITATIVE_SOURCES))
    rows = conn.execute(
        f"SELECT uid FROM jobs WHERE status='new' AND source IN ({src}) "
        f"AND company IN ({placeholders})",
        AUTHORITATIVE_SOURCES + tuple(live_companies)).fetchall()

    closed = 0
    for r in rows:
        if r["uid"] not in seen_uids:
            conn.execute("UPDATE jobs SET status='closed', "
                         "status_changed=datetime('now') WHERE uid=?", (r["uid"],))
            closed += 1
    conn.commit()
    return closed


def stats(conn) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) c FROM jobs GROUP BY status").fetchall()
    return {r["status"]: r["c"] for r in rows}
