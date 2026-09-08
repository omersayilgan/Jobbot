"""Builds a tailored cover letter for one posting, with no LLM involved.

Tailoring comes from selection rather than generation: the scorer already
knows which of your skill clusters a posting asked for, so the letter leads
with the evidence bullets for exactly those clusters, in the posting's own
language.
"""
from __future__ import annotations

import datetime as _dt
import textwrap
import json
import os
import re
import shutil

import yaml

from .config import ROOT, load_config, resolve

GERMAN_MARKERS = ("wir suchen", "deine aufgaben", "ihre aufgaben", "dein profil",
                  "das bringst du mit", "unser angebot", "kenntnisse", "berufserfahrung",
                  "mitarbeiter", "stelle", "einstellung", "abgeschlossenes studium")


def _bank() -> dict:
    with open(os.path.join(ROOT, "letters.yaml"), "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def detect_language(job_row) -> str:
    """German posting -> German letter. Default English (most Munich deep-tech)."""
    text = f"{job_row['title']} {job_row['description'] or ''}".lower()
    hits = sum(1 for m in GERMAN_MARKERS if m in text)
    return "de" if hits >= 2 else "en"


WRAP = 78


def _reflow(text: str) -> str:
    """Wrap prose to a readable column width.

    Templates keep each paragraph on one long line, so anything over the
    limit is prose worth wrapping; short lines (date, ref, signature block)
    are already correct and are left exactly as they are.
    """
    out = []
    for line in text.split("\n"):
        if len(line) > WRAP:
            out.extend(textwrap.wrap(line, WRAP, break_long_words=False, break_on_hyphens=False))
        else:
            out.append(line)
    return "\n".join(out)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60]


def compose(job_row, cfg: dict | None = None, lang: str | None = None) -> tuple[str, str]:
    """Return (language, letter_text) for a DB row."""
    cfg = cfg or load_config()
    bank = _bank()
    lang = lang or detect_language(job_row)
    p = cfg["profile"]

    matched = json.loads(job_row["matched"] or "{}")
    # Rank matched clusters by their configured weight — argue the strongest first.
    weights = {k: v["weight"] for k, v in cfg["skills"].items()}
    ranked = sorted(matched.keys(), key=lambda c: -weights.get(c, 0))
    top = [c for c in ranked if c in bank["evidence"]][:3]
    if not top:                       # nothing matched: fall back to core profile
        top = ["control", "simulation"]

    evidence = "\n\n".join(bank["evidence"][c][lang] for c in top)
    focus = bank["focus_names"].get(top[0], {}).get(lang, top[0])
    ref = f"\nRef: {job_row['external_id']}" if job_row["external_id"] else ""

    letter = bank["templates"][lang].format(
        date=_dt.date.today().strftime("%d %B %Y" if lang == "en" else "%d.%m.%Y"),
        title=job_row["title"], company=job_row["company"], ref=ref,
        focus=focus, evidence=evidence,
        german_level=p.get("german_level", "B1"),
        full_name=p["full_name"], phone=p["phone"],
        email=p["email"], address=p["address"],
    )
    return lang, _reflow(letter.strip()) + "\n"


def build_pack(job_row, cfg: dict | None = None, lang: str | None = None) -> str:
    """Create output/applications/<company>-<title>/ with everything to send."""
    cfg = cfg or load_config()
    lang, letter = compose(job_row, cfg, lang)

    folder = os.path.join(
        ROOT, "output", "applications",
        f"{_slug(job_row['company'])}__{_slug(job_row['title'])}")
    os.makedirs(folder, exist_ok=True)

    with open(os.path.join(folder, f"cover_letter_{lang}.txt"), "w", encoding="utf-8") as fh:
        fh.write(letter)

    # Copy CV + supporting documents so the folder is self-contained.
    docs = [cfg["profile"]["cv_path"]] + list(cfg["profile"].get("extra_documents") or [])
    for d in docs:
        src = resolve(d)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(folder, os.path.basename(src)))

    reasons = json.loads(job_row["reasons"] or "[]")
    with open(os.path.join(folder, "APPLY.md"), "w", encoding="utf-8") as fh:
        fh.write(f"""# {job_row['title']} — {job_row['company']}

**Apply here:** {job_row['url']}

| | |
|---|---|
| Fit score | **{job_row['score']}/100** |
| Location | {job_row['location']} |
| Source | {job_row['source']} |
| Posted | {job_row['posted_at'] or 'n/a'} |
| Letter language | {lang.upper()} |

## Why this was matched
""" + "\n".join(f"- {r}" for r in reasons) + f"""

## Checklist
- [ ] Read the posting in full at the link above
- [ ] Adjust `cover_letter_{lang}.txt` — check the company paragraph is specific
- [ ] Convert the letter to PDF
- [ ] Submit
- [ ] Mark applied: `python3 run.py status {job_row['uid']} applied`
""")
    return folder
