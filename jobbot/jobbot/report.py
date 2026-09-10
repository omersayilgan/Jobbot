"""Generates a standalone ranked HTML document of every scored match.

The review dashboard needs the local server running to record decisions; this
is a single self-contained file you can publish, keep open in a tab, or read
offline while working down the list.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re

from . import db
from .config import load_config, load_narrative, output_dir

# Tier floors sit where the live score distribution separates, not on round
# numbers: 75+ isolates direct hits on the profile's core domains, 55+ the roles
# whose stack the person already has, 38+ the adjacent ones. The wording is
# generated per profile by setup.py.
FALLBACK_TIERS = [
    (75, "Apply first", "Direct hits on your core field."),
    (55, "Strong fit", "Clear overlap with your stack."),
    (38, "Worth a look", "Adjacent roles worth reading before investing time."),
    (0, "Long shots", "Thinner overlap. Apply if the company itself appeals."),
]


def _tiers() -> list[tuple[int, str, str]]:
    spec = (load_narrative() or {}).get("tiers")
    if not spec:
        return FALLBACK_TIERS
    return [(int(t["floor"]), t["label"], t["text"]) for t in spec]


def _tier_of(score: int, tiers) -> int:
    for i, (floor, _, _) in enumerate(tiers):
        if score >= floor:
            return i
    return len(tiers) - 1


def _sources(cfg: dict) -> str:
    """Name the documents the ranking was actually built from."""
    docs = [cfg["profile"].get("cv_path")] + list(cfg["profile"].get("extra_documents") or [])
    names = [os.path.basename(d) for d in docs if d]
    if not names:
        return "your profile"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def build(path: str | None = None) -> tuple[str, int]:
    cfg = load_config()
    tiers = _tiers()
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
            "tier": _tier_of(r["score"], tiers),
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
                  [{"floor": f, "name": n, "blurb": b} for f, n, b in tiers],
                  ensure_ascii=False))
              .replace("__COUNT__", str(open_count))
              .replace("__DONE__", str(done_count))
              .replace("__TRACKED__", str(tracked))
              .replace("__COMPANIES__", str(companies))
              .replace("__DATE__", _dt.date.today().strftime("%d %B %Y"))
              .replace("__PLACE__", cfg["filters"].get("location_label", "your area"))
              .replace("__SOURCES__", _sources(cfg)))

    label = (cfg.get("filters", {}).get("location_label") or "role").lower()
    slug = re.sub(r"[^a-z0-9]+", "_", label).strip("_") or "role"
    path = path or os.path.join(output_dir(), f"{slug}_shortlist.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path, len(rows)
