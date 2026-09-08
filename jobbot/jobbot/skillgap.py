"""Skill-demand and gap analysis over the stored job descriptions.

Two deliberate choices about counting:

1. **Document frequency, not term frequency.** A posting that says "Python"
   nine times is one job wanting Python, not nine.
2. **Company reach alongside job count.** Helsing alone accounts for ~40% of
   the best-fit postings; without tracking distinct employers its house style
   would masquerade as market demand.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict

import yaml

from . import db
from .config import ROOT

MIN_FIT = 38          # tiers 1-3: the roles actually worth preparing for


def _load_taxonomy() -> dict:
    with open(os.path.join(ROOT, "skills_taxonomy.yaml"), "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["groups"]


def _matcher(term: str):
    """Whole-token match, tolerant of the punctuation in c++, ci/cd, do-178."""
    t = term.strip().lower()
    return re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])")


def analyse(min_fit: int = MIN_FIT) -> dict:
    conn = db.connect()
    rows = conn.execute(
        "SELECT company, title, description, score FROM jobs WHERE score >= ?",
        (min_fit,)).fetchall()

    corpus = [(r["company"], f"{r['title']}\n{r['description'] or ''}".lower(), r["score"])
              for r in rows]
    total_jobs = len(corpus)
    total_companies = len({c for c, _, _ in corpus})

    taxonomy = _load_taxonomy()
    results = []
    for group, skills in taxonomy.items():
        for name, spec in skills.items():
            patterns = [_matcher(t) for t in spec["terms"]]
            jobs = 0
            per_company: defaultdict[str, int] = defaultdict(int)
            fits: list[int] = []
            for company, text, score in corpus:
                if any(p.search(text) for p in patterns):
                    jobs += 1
                    per_company[company] += 1
                    fits.append(score)
            companies = set(per_company)

            if not jobs:
                continue
            results.append({
                "group": group,
                "name": name,
                "level": spec["level"],
                "note": spec.get("note", ""),
                "jobs": jobs,
                "companies": len(companies),
                "share": jobs / total_jobs,
                "company_share": len(companies) / total_companies,
                # Average fit of the roles asking for it: a skill demanded by
                # your strongest matches matters more than a common one.
                "avg_fit": sum(fits) / len(fits),
                "top_fit": max(fits),
                # Share of mentions coming from the single loudest employer.
                "top_company": max(per_company.items(), key=lambda kv: kv[1])[0],
                "top_company_share": max(per_company.values()) / jobs,
            })

    # Importance blends how widely a skill is asked for, how many distinct
    # employers ask, and how well those roles suit you.
    for r in results:
        r["importance"] = round(
            100 * (0.45 * r["share"] + 0.35 * r["company_share"]
                   + 0.20 * (r["avg_fit"] / 100.0)), 1)

    # A skill 25 of whose 30 mentions come from one employer is that employer's
    # house style, not market demand — counting distinct employers alone misses
    # this, because four employers where one supplies 83% still reads as "four".
    # Separating the two is the whole point: you would learn CI/CD for six
    # companies, not Rust for one.
    for r in results:
        r["concentrated"] = r["top_company_share"] >= 0.6 and r["jobs"] >= 5

    results.sort(key=lambda r: -r["importance"])
    return {
        "results": results,
        "total_jobs": total_jobs,
        "total_companies": total_companies,
        "min_fit": min_fit,
    }
