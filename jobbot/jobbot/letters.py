"""Builds a tailored cover letter for one posting, with no LLM involved.

Tailoring comes from selection rather than generation: the scorer already knows
which of the profile's domains a posting asked for, so the letter leads with
the evidence for exactly those domains — and that evidence is drawn from the
person's own CV bullets by setup.py, in their own words.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import textwrap

from .config import load_config, load_letters, output_dir, resolve

# Wordings that mark a posting as written in a given language. Only the
# languages the profile can actually write a letter in are ever tested.
POSTING_MARKERS = {
    "de": ("wir suchen", "deine aufgaben", "ihre aufgaben", "dein profil", "ihr profil",
           "das bringst du mit", "unser angebot", "kenntnisse", "berufserfahrung",
           "mitarbeiter", "abgeschlossenes studium", "wir bieten", "deine qualifikation"),
    "fr": ("nous recherchons", "vos missions", "votre profil", "profil recherché",
           "nous offrons", "compétences", "expérience professionnelle"),
    "es": ("buscamos", "tus funciones", "tu perfil", "ofrecemos", "requisitos",
           "experiencia laboral"),
    "it": ("cerchiamo", "le tue mansioni", "il tuo profilo", "offriamo", "requisiti"),
    "nl": ("wij zoeken", "jouw taken", "jouw profiel", "wij bieden", "vereisten"),
    "pl": ("poszukujemy", "twoje zadania", "twój profil", "oferujemy", "wymagania"),
    "tr": ("aradığımız", "görev tanımı", "aranan nitelikler", "sunduklarımız"),
    "cs": ("hledáme", "vaše náplň", "váš profil", "nabízíme", "požadujeme"),
}

WRAP = 78


def detect_language(job_row, available: list[str]) -> str:
    """Write in the posting's own language when the profile can."""
    text = f"{job_row['title']} {job_row['description'] or ''}".lower()
    best, best_hits = "en", 0
    for lang in available:
        if lang == "en":
            continue
        hits = sum(1 for m in POSTING_MARKERS.get(lang, ()) if m in text)
        if hits >= 2 and hits > best_hits:
            best, best_hits = lang, hits
    return best


def _reflow(text: str) -> str:
    """Wrap prose to a readable column width.

    Templates keep each paragraph on one long line, so anything over the limit
    is prose worth wrapping; short lines (date, ref, signature block) are
    already correct and are left exactly as they are.
    """
    out = []
    for line in text.split("\n"):
        if len(line) > WRAP:
            out.extend(textwrap.wrap(line, WRAP, break_long_words=False,
                                     break_on_hyphens=False))
        else:
            out.append(line)
    return "\n".join(out)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60]


def compose(job_row, cfg: dict | None = None, lang: str | None = None) -> tuple[str, str]:
    """Return (language, letter_text) for a DB row."""
    cfg = cfg or load_config()
    bank = load_letters()
    available = bank.get("languages") or ["en"]
    lang = lang or detect_language(job_row, available)
    if lang not in bank.get("templates", {}):
        lang = "en"
    p = cfg["profile"]

    matched = json.loads(job_row["matched"] or "{}")
    # Rank matched domains by their configured weight — argue the strongest first.
    weights = {k: v["weight"] for k, v in cfg["skills"].items()}
    ranked = sorted(matched.keys(), key=lambda c: -weights.get(c, 0))
    top = [c for c in ranked if c in bank["evidence"]][:3]
    # Thin match — or a posting scored under an older profile whose domain
    # names have since changed. Top up from the profile's strongest domains so
    # the letter always argues from at least two pieces of evidence.
    for key in cfg["skills"]:
        if len(top) >= 2:
            break
        if key in bank["evidence"] and key not in top:
            top.append(key)
    # Lead with the strongest domain regardless of how the top-up filled in.
    top.sort(key=lambda c: -weights.get(c, 0))

    evidence = "\n\n".join(t for c in top
                           if (t := bank["evidence"][c].get(lang, "").strip()))
    focus = (bank["focus_names"].get(top[0], {}).get(lang, "") if top else "") \
        or "this work"
    ref = f"\nRef: {job_row['external_id']}" if job_row["external_id"] else ""

    letter = bank["templates"][lang].format(
        date=_dt.date.today().strftime("%d %B %Y" if lang == "en" else "%d.%m.%Y"),
        title=(job_row["title"] or "").strip(), company=job_row["company"], ref=ref,
        focus=focus, evidence=evidence,
        headline=p.get("headline", "an engineer"),
        city=p.get("city", ""),
        language_note=bank.get("language_notes", {}).get(lang, ""),
        full_name=p["full_name"], phone=p.get("phone", ""),
        email=p.get("email", ""), address=p.get("address", ""),
    )
    return lang, _reflow(letter.strip()) + "\n"


def build_pack(job_row, cfg: dict | None = None, lang: str | None = None) -> str:
    """Create output/<profile>/applications/<company>__<role>/ with everything to send."""
    cfg = cfg or load_config()
    bank = load_letters()
    lang, letter = compose(job_row, cfg, lang)

    folder = os.path.join(
        output_dir(), "applications",
        f"{_slug(job_row['company'])}__{_slug(job_row['title'])}")
    os.makedirs(folder, exist_ok=True)

    with open(os.path.join(folder, f"cover_letter_{lang}.txt"), "w", encoding="utf-8") as fh:
        fh.write(letter)

    # Copy CV + supporting documents so the folder is self-contained.
    docs = [cfg["profile"].get("cv_path")] + list(cfg["profile"].get("extra_documents") or [])
    missing = []
    for d in docs:
        if not d:
            continue
        src = resolve(d)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(folder, os.path.basename(src)))
        else:
            missing.append(d)

    reasons = json.loads(job_row["reasons"] or "[]")
    translate = bank.get("needs_translation", {}).get(lang)
    notes = ""
    if translate:
        notes += (f"\n> **This letter is in {lang.upper()}, but the evidence paragraphs are "
                  f"quoted from your CV in another language.** Translate them before "
                  f"sending, or force English with `--lang en`.\n")
    if missing:
        notes += ("\n> **Missing attachment(s):** " + ", ".join(missing) +
                  " — fix the paths in your profile's config.yaml.\n")

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
{notes}
## Why this was matched
""" + "\n".join(f"- {r}" for r in reasons) + f"""

## Checklist
- [ ] Read the posting in full at the link above
- [ ] Adjust `cover_letter_{lang}.txt` — check the company paragraph is specific
{"- [ ] Translate the evidence paragraphs" if translate else ""}
- [ ] Convert the letter to PDF
- [ ] Submit
- [ ] Mark applied: `python3 run.py status {job_row['uid']} applied`
""")
    return folder
