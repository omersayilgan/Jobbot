"""JSearch (via RapidAPI) — licensed aggregation of Indeed, LinkedIn, Glassdoor
and ZipRecruiter postings.

This is the sanctioned way to reach the inventory those sites carry. JSearch
licenses and indexes the data; you query JSearch, never the sites themselves,
so there is no terms-of-service breach and no account to get banned.

Free tier is roughly 200 requests/month, so the adapter is deliberately frugal:
one request per configured query, scoped to the profile's city.

    jsearch:
      api_key: "..."          # rapidapi.com key
      queries: [...]
"""
from __future__ import annotations

import time

import requests

from ..models import Job
from .base import strip_html

NAME = "jsearch"
API = "https://jsearch.p.rapidapi.com/search"
HOST = "jsearch.p.rapidapi.com"

DEFAULT_QUERIES = [
    "control engineer munich",
    "gnc engineer munich",
    "embedded software engineer munich",
    "simulation engineer munich",
    "robotics engineer munich",
    "automation engineer munich",
]


def _creds(cfg: dict) -> dict:
    return cfg.get("jsearch") or {}


def probe(slug: str, cfg: dict) -> int | None:
    key = _creds(cfg).get("api_key")
    if not key:
        return None
    try:
        city = cfg.get("filters", {}).get("location_label", "")
        country = (cfg.get("adzuna") or {}).get("country") or "de"
        r = requests.get(API, params={"query": f"engineer {city}".strip(), "page": "1",
                                      "num_pages": "1", "country": country},
                         headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": HOST},
                         timeout=cfg.get("fetch", {}).get("request_timeout", 20))
        if r.status_code == 200:
            return len(r.json().get("data", []))
    except Exception:
        pass
    return None


def fetch(slug: str, company: str, cfg: dict) -> list[Job]:
    creds = _creds(cfg)
    key = creds.get("api_key")
    if not key:
        raise RuntimeError(
            "JSearch key missing — add jsearch.api_key to config.yaml "
            "(free tier at https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch)")

    queries = creds.get("queries") or DEFAULT_QUERIES
    seen: set[str] = set()
    jobs: list[Job] = []

    for q in queries:
        try:
            r = requests.get(
                API,
                params={"query": q, "page": "1", "num_pages": "1",
                        "country": "de", "employment_types": "FULLTIME"},
                headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": HOST},
                timeout=cfg.get("fetch", {}).get("request_timeout", 20))
            if r.status_code != 200:
                break
            results = r.json().get("data") or []
        except Exception:
            break

        for j in results:
            jid = j.get("job_id", "")
            if not jid or jid in seen:
                continue
            seen.add(jid)
            loc = ", ".join(x for x in (j.get("job_city"), j.get("job_state")) if x)
            jobs.append(Job(
                source=NAME,
                company=j.get("employer_name", "") or "Unknown",
                title=j.get("job_title", ""),
                location=loc or j.get("job_country", ""),
                # Prefer the original posting over the aggregator's redirect.
                url=j.get("job_apply_link") or j.get("job_google_link", ""),
                description=strip_html(j.get("job_description")),
                employment_type=j.get("job_employment_type", "") or "",
                posted_at=(j.get("job_posted_at_datetime_utc") or "")[:10],
                external_id=jid,
            ))
        time.sleep(0.5)

    return jobs
