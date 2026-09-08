"""Duplicate detection across sources.

Aggregators repost the same vacancy repeatedly: under a slightly different
title, with the gender tag rewritten, with the city appended, or fronted by a
recruitment agency instead of the hiring company. Three passes catch these
without collapsing genuinely different roles.

The measure is Jaccard similarity on token *sets*, deliberately not containment.
Containment treats "Software Engineer" and "Software Engineer - Backend" as
identical, because the first title's tokens are a subset of the second's — an
early version of this made exactly that mistake and reported 60 duplicates where
there were 2. Jaccard scores that pair 2/3, correctly below threshold.
"""
from __future__ import annotations

import re

LEGAL_SUFFIX = re.compile(
    r"\b(gmbh|ag|se|kg|mbh|inc|ltd|llc|bv|nv|sa|srl|co|kgaa|ohg|ug|plc|group)\b", re.I)

# The gender notation varies between repostings of one role: (m/f/d), (w/m/d),
# (f/m/x), (all genders), (d/m/w)...
GENDER_TAG = re.compile(
    r"[\(\[]\s*(?:[mwfdxa](?:\s*/\s*[mwfdx])+|all\s+genders|alle\s+geschlechter"
    r"|m\s*/\s*w\s*/\s*d)\s*[\)\]]", re.I)

CITY_TAIL = re.compile(
    r"\s*(?:[-–|,]\s*)?\b(?:in|bei|near|standort)?\s*"
    r"(?:m(?:ü|ue)nchen|munich|ottobrunn|garching|taufkirchen|gilching)\s*$", re.I)

TITLE_JACCARD = 0.85      # same company, near-identical title
DESC_JACCARD = 0.75       # different company (agency fronting), same posting

# Aggregators and agencies never win a tie: applying direct is always better.
AGGREGATORS = {"adzuna", "jsearch", "jooble", "arbeitnow"}


def norm_company(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", LEGAL_SUFFIX.sub("", text or "").lower())


def norm_title(text: str) -> str:
    t = GENDER_TAG.sub(" ", text or "")
    t = CITY_TAIL.sub("", t)
    return re.sub(r"[^a-z0-9]+", "", t.lower())


def _tokens(text: str) -> set[str]:
    t = GENDER_TAG.sub(" ", text or "")
    return {w for w in re.findall(r"[a-zA-ZäöüßÄÖÜ]{3,}", t.lower())}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _rank(job) -> tuple:
    """Higher is better: acted-on beats untouched, direct beats aggregator,
    fuller description beats a snippet, higher score breaks the tie."""
    status = getattr(job, "status", None) or "new"
    return (
        status != "new",
        job.source not in AGGREGATORS,
        len(job.description or ""),
        job.score,
    )


def find_duplicates(jobs: list) -> list[tuple[int, int]]:
    """Return (keep_index, drop_index) pairs."""
    drops: list[tuple[int, int]] = []
    dropped: set[int] = set()

    # Pass 1 — identical apply URL.
    by_url: dict[str, int] = {}
    for i, j in enumerate(jobs):
        u = (j.url or "").strip().lower()
        if not u:
            continue
        if u in by_url:
            a, b = by_url[u], i
            keep, drop = (a, b) if _rank(jobs[a]) >= _rank(jobs[b]) else (b, a)
            by_url[u] = keep
            drops.append((keep, drop))
            dropped.add(drop)
        else:
            by_url[u] = i

    # Pass 2 — same employer, near-identical title.
    by_company: dict[str, list[int]] = {}
    for i, j in enumerate(jobs):
        if i in dropped:
            continue
        by_company.setdefault(norm_company(j.company), []).append(i)

    for group in by_company.values():
        for x in range(len(group)):
            for y in range(x + 1, len(group)):
                a, b = group[x], group[y]
                if a in dropped or b in dropped:
                    continue
                ta, tb = norm_title(jobs[a].title), norm_title(jobs[b].title)
                same = ta == tb or jaccard(_tokens(jobs[a].title),
                                           _tokens(jobs[b].title)) >= TITLE_JACCARD
                if same:
                    keep, drop = (a, b) if _rank(jobs[a]) >= _rank(jobs[b]) else (b, a)
                    drops.append((keep, drop))
                    dropped.add(drop)

    # Pass 3 — same title, different employer name, same underlying posting.
    # This is the recruitment agency fronting a company's vacancy.
    by_title: dict[str, list[int]] = {}
    for i, j in enumerate(jobs):
        if i in dropped:
            continue
        by_title.setdefault(norm_title(j.title), []).append(i)

    for group in by_title.values():
        if len(group) < 2:
            continue
        for x in range(len(group)):
            for y in range(x + 1, len(group)):
                a, b = group[x], group[y]
                if a in dropped or b in dropped:
                    continue
                if norm_company(jobs[a].company) == norm_company(jobs[b].company):
                    continue
                da, dbb = jobs[a].description or "", jobs[b].description or ""
                # Snippets are too short to judge similarity reliably.
                if len(da) < 400 or len(dbb) < 400:
                    continue
                if jaccard(_tokens(da), _tokens(dbb)) >= DESC_JACCARD:
                    keep, drop = (a, b) if _rank(jobs[a]) >= _rank(jobs[b]) else (b, a)
                    drops.append((keep, drop))
                    dropped.add(drop)

    return drops


def dedupe(jobs: list) -> list:
    drops = find_duplicates(jobs)
    dropped = {d for _, d in drops}
    return [j for i, j in enumerate(jobs) if i not in dropped]
