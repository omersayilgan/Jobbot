"""Generates a standalone ranked HTML document of every scored match.

The review dashboard needs the local server running to record decisions; this
is a single self-contained file you can publish, keep open in a tab, or read
offline while working down the list.
"""
from __future__ import annotations

import datetime as _dt
import json
import os

from . import db
from .config import load_config, output_dir

# Tier floors are chosen from the live score distribution, not round numbers:
# 75+ isolates the direct control/GNC/flight-software hits, 55+ the roles whose
# core stack you already have, 38+ the adjacent engineering.
TIERS = [
    (75, "Apply first",
     "Direct hits on control, GNC and flight software — what your thesis, your "
     "Roketsan work and your best-graded modules were literally training for."),
    (55, "Strong fit",
     "Clear overlap with your core stack. Expect to rewrite a paragraph of the "
     "letter, but you meet the substance of what they ask for."),
    (38, "Worth a look",
     "Adjacent roles: the engineering sits in your world, but the emphasis falls "
     "somewhere you have less graded evidence. Read the posting before investing."),
    (0, "Long shots",
     "Thinner overlap, or weighed down by a C1-German requirement or a subject "
     "your transcript is lighter on. Apply if the company itself appeals."),
]


def _tier_of(score: int) -> int:
    for i, (floor, _, _) in enumerate(TIERS):
        if score >= floor:
            return i
    return len(TIERS) - 1


def build(path: str | None = None) -> tuple[str, int]:
    cfg = load_config()
    conn = db.connect()
    rows = db.query(conn, min_score=cfg["filters"]["min_score"], limit=2000)

    # Jobs you have acted on are reported separately — they must never reappear
    # in the queue as if they were new.
    ACTIONED = ("applied", "shortlisted", "interview", "offer",
                "rejected", "skipped", "closed")

    payload = []
    for r in rows:
        matched = json.loads(r["matched"] or "{}")
        payload.append({
            "uid": r["uid"], "t": r["title"], "c": r["company"],
            "l": r["location"], "u": r["url"], "s": r["score"],
            "d": r["posted_at"] or "", "st": r["status"],
            "m": {k: v[:4] for k, v in matched.items()},
            "w": json.loads(r["reasons"] or "[]"),
            "tier": _tier_of(r["score"]),
            "done": r["status"] in ACTIONED,
        })

    tracked = conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
    companies = len({r["company"] for r in rows})
    open_count = sum(1 for p in payload if not p["done"])
    done_count = len(payload) - open_count

    tpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")
    with open(tpl_path, "r", encoding="utf-8") as fh:
        doc = fh.read()

    doc = (doc.replace("__DATA__", json.dumps(payload, ensure_ascii=False))
              .replace("__TIERS__", json.dumps(
                  [{"floor": f, "name": n, "blurb": b} for f, n, b in TIERS],
                  ensure_ascii=False))
              .replace("__COUNT__", str(open_count))
              .replace("__DONE__", str(done_count))
              .replace("__TRACKED__", str(tracked))
              .replace("__COMPANIES__", str(companies))
              .replace("__DATE__", _dt.date.today().strftime("%d %B %Y")))

    path = path or os.path.join(output_dir(), "munich_engineering_roles.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path, len(rows)
