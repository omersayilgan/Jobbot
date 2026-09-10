"""Adzuna aggregator API — the legitimate route to job-board breadth.

Adzuna indexes postings from across the German market (including many that
also appear on Indeed and StepStone) and offers a free API tier. Unlike
scraping LinkedIn or Indeed, this is a documented, sanctioned interface.

Register free at https://developer.adzuna.com/ and put the credentials in
config.yaml:

    adzuna:
      app_id: "xxxxxxxx"
      app_key: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
      queries: ["control engineer", "embedded software", ...]

Registry entry shape (one per search query is unnecessary — the adapter reads
its query list straight from config):
    adzuna:
      - {slug: de, name: "Adzuna DE"}
"""
from __future__ import annotations

import time

from ..models import Job
from .base import get, strip_html

NAME = "adzuna"
API = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

# Only used when the profile carries no queries of its own — setup.py writes
# them from the person's actual role families.
DEFAULT_QUERIES = ["engineer", "developer", "analyst", "manager", "specialist"]


def probe(slug: str, cfg: dict) -> int | None:
    creds = cfg.get("adzuna") or {}
    if not creds.get("app_id") or not creds.get("app_key"):
        return None
    try:
        r = get(API.format(country=slug or "de", page=1), cfg, params={
            "app_id": creds["app_id"], "app_key": creds["app_key"],
            "results_per_page": 1, "where": creds.get("where") or "germany"})
        if r.status_code == 200:
            return r.json().get("count")
    except Exception:
        pass
    return None


def fetch(slug: str, company: str, cfg: dict) -> list[Job]:
    creds = cfg.get("adzuna") or {}
    if not creds.get("app_id") or not creds.get("app_key"):
        raise RuntimeError(
            "Adzuna credentials missing — add adzuna.app_id / app_key to "
            "config.yaml (free key at https://developer.adzuna.com/)")

    country = slug or creds.get("country") or "de"
    queries = creds.get("queries") or DEFAULT_QUERIES
    radius = creds.get("distance_km", 25)
    seen: set[str] = set()
    jobs: list[Job] = []

    for q in queries:
        for page in (1, 2):
            try:
                r = get(API.format(country=country, page=page), cfg, params={
                    "app_id": creds["app_id"], "app_key": creds["app_key"],
                    "results_per_page": 50, "what": q,
                    "where": creds.get("where") or "germany",
                    "distance": radius, "full_time": 1,
                    "content-type": "application/json"})
                if r.status_code != 200:
                    break
                results = r.json().get("results", [])
            except Exception:
                break

            if not results:
                break

            for j in results:
                jid = str(j.get("id", ""))
                if not jid or jid in seen:
                    continue
                seen.add(jid)
                jobs.append(Job(
                    source=NAME,
                    company=(j.get("company") or {}).get("display_name", "") or "Unknown",
                    title=j.get("title", ""),
                    location=(j.get("location") or {}).get("display_name", ""),
                    url=j.get("redirect_url", ""),
                    description=strip_html(j.get("description")),
                    employment_type=j.get("contract_time", "") or "",
                    posted_at=(j.get("created") or "")[:10],
                    external_id=jid,
                ))
            time.sleep(0.3)

    return jobs
