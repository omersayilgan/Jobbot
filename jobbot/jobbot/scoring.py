"""Scores a posting against the profile generated from your documents.

Score is a 0-100 fit estimate built from five signals, all of them configured
per person by setup.py rather than hardcoded here:
  1. title family  — what the role fundamentally is (largest single lever)
  2. skill overlap — which of your evidenced domains the posting asks for
  3. seniority     — matched to your career stage, in both directions
  4. transcript    — subjects you demonstrably did well and badly in
  5. language      — a local-language requirement above your level costs points
"""
from __future__ import annotations

import re

from .location import classify
from .models import Job

# Raw points can exceed 100 on a very strong posting (observed max ~123 with the academic layer).
# Normalising against this figure keeps the top of the ranking discriminative
# instead of collapsing the best six jobs into a tie at 100.
SCORE_FULL_MARKS = 125

FULLTIME_NEG = ("part-time", "part time", "teilzeit", "internship", "praktikum",
                "working student", "werkstudent", "temporary", "befristet auf",
                "contract", "freelance", "minijob")
FULLTIME_POS = ("full-time", "full time", "full_time", "vollzeit", "permanent",
                "unbefristet", "festanstellung", "regular")


def _find(haystack: str, terms) -> list[str]:
    """Whole-word-ish containment match; handles multi-word terms and umlauts.

    A term ending in `*` is a stem, matched as a prefix — German compounds
    ("Aeroelastik", "Flugantriebe") swallow the trailing word boundary that a
    plain term depends on.
    """
    found = []
    for t in terms:
        t = str(t).lower()
        if t.endswith("*"):
            pattern = r"(?<![a-z0-9äöüß])" + re.escape(t[:-1])
        else:
            pattern = r"(?<![a-z0-9äöüß])" + re.escape(t) + r"(?![a-z0-9äöüß])"
        if re.search(pattern, haystack):
            found.append(t)
    return found


def passes_filters(job: Job, cfg: dict) -> tuple[bool, str]:
    """Hard gates. Returns (kept, reason_if_dropped)."""
    f = cfg["filters"]
    title = job.title.lower()

    for bad in f.get("exclude_titles", []):
        if bad.lower() in title:
            return False, f"excluded title keyword: '{bad}'"

    ok, note = classify(
        job.location,
        [a.lower() for a in f.get("locations", [])],
        ambiguous=f.get("ambiguous_locations", []),
        excludes=f.get("location_excludes", []),
        remote_ok=f.get("remote_anchors", []),
        label=f.get("location_label", "your area"))
    if not ok:
        return False, note
    job.reasons.append(f"Location: {note}")

    if f.get("full_time_only", True):
        blob = f"{job.employment_type} {job.title}".lower()
        if any(n in blob for n in FULLTIME_NEG):
            return False, f"not full-time ({job.employment_type or job.title})"
        # Most boards simply omit the field; only reject on an explicit signal.
        head = job.description[:1500].lower()
        if any(n in head for n in FULLTIME_NEG) and not any(p in blob for p in FULLTIME_POS):
            return False, "description indicates part-time/temporary"

    return True, ""


def score(job: Job, cfg: dict) -> Job:
    title = job.title.lower()
    body = f"{job.title}\n{job.description}".lower()
    total = 0

    # ---- 1. title family -------------------------------------------------
    best_title = 0
    for pts, terms in sorted(cfg["title_bonus"].items(), key=lambda x: -int(x[0])):
        hit = _find(title, terms)
        if hit:
            best_title = max(best_title, int(pts))
            job.reasons.append(f"Title match '{hit[0]}' (+{pts})")
            break
    total += best_title

    # ---- 2. skill clusters ----------------------------------------------
    # Aggregators (Adzuna) return a ~500-char snippet where an ATS returns the
    # full posting. Scale the evidence bar to the text actually available, or
    # short listings get buried regardless of how good the role is.
    need = 3 if len(job.description) >= 1200 else 2
    for cluster, spec in cfg["skills"].items():
        hits = _find(body, spec["terms"])
        if not hits:
            continue
        job.matched[cluster] = hits[:8]
        depth = min(len(hits), need) / float(need)
        pts = round(spec["weight"] * depth)
        total += pts
        job.reasons.append(f"{cluster}: {', '.join(hits[:4])} (+{pts})")

    # ---- 3. seniority ----------------------------------------------------
    for pts, terms in cfg["seniority"].get("boost", {}).items():
        if _find(body, terms):
            total += int(pts)
            job.reasons.append(f"Early-career friendly (+{pts})")
            break
    for pts, terms in sorted(cfg["seniority"].get("penalty", {}).items(), key=lambda x: int(x[0])):
        hit = _find(body, terms)
        if hit:
            total += int(pts)
            job.reasons.append(f"Seniority '{hit[0]}' ({pts})")
            break

    # ---- 4. transcript strengths and weaknesses --------------------------
    for pts, terms in cfg.get("academic", {}).get("strength", {}).items():
        hit = _find(body, terms)
        if hit:
            total += int(pts)
            job.reasons.append(f"Graded strength '{hit[0]}' (+{pts})")
            break
    for pts, terms in sorted(cfg.get("academic", {}).get("weakness", {}).items(),
                             key=lambda x: int(x[0])):
        hit = _find(body, terms)
        if hit:
            total += int(pts)
            job.reasons.append(f"Weaker on transcript: '{hit[0]}' ({pts})")
            break

    # ---- 5. local-language requirement -----------------------------------
    for pts, terms in sorted(cfg["language"].get("penalty", {}).items(), key=lambda x: int(x[0])):
        hit = _find(body, terms)
        if hit:
            total += int(pts)
            lang = cfg["language"].get("local_language", "the local language")
            mine = cfg["language"].get("your_level", "your level")
            job.reasons.append(
                f"{lang} requirement '{hit[0]}' ({pts}) — you are {mine}")
            break
    for pts, terms in cfg["language"].get("boost", {}).items():
        if _find(body, terms):
            total += int(pts)
            job.reasons.append(f"English-speaking workplace (+{pts})")
            break

    # ---- 6. staffing intermediaries --------------------------------------
    ag = cfg.get("agencies", {})
    comp = job.company.lower()
    hit = next((n for n in ag.get("names", []) if n in comp), None)
    if hit:
        total += int(ag.get("penalty", -15))
        job.reasons.append(f"Staffing agency ('{hit}') — apply direct if you can "
                           f"({ag.get('penalty', -15)})")

    job.raw_score = total
    job.score = max(0, min(100, round(total * 100 / SCORE_FULL_MARKS)))
    return job
