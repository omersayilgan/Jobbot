"""Jooble — job aggregator with a free API key on request.

    jooble:
      api_key: "..."      # from https://jooble.org/api/about
"""
from __future__ import annotations

import time

import requests

from ..models import Job
from .base import strip_html

NAME = "jooble"
API = "https://jooble.org/api/{key}"

DEFAULT_QUERIES = ["control engineer", "embedded software", "GNC engineer",
                   "simulation engineer", "robotics engineer", "automation engineer"]


def _key(cfg: dict) -> str:
    return (cfg.get("jooble") or {}).get("api_key", "")


def _where(cfg: dict) -> str:
    """Search city — the profile's own, not a hardcoded one."""
    return (cfg.get("jooble") or {}).get("location") \
        or cfg.get("filters", {}).get("location_label") \
        or (cfg.get("profile") or {}).get("city") or ""


def probe(slug: str, cfg: dict) -> int | None:
    key = _key(cfg)
    if not key:
        return None
    try:
        r = requests.post(API.format(key=key),
                          json={"keywords": "engineer", "location": _where(cfg)},
                          timeout=cfg.get("fetch", {}).get("request_timeout", 20))
        if r.status_code == 200:
            return r.json().get("totalCount")
    except Exception:
        pass
    return None


def fetch(slug: str, company: str, cfg: dict) -> list[Job]:
    key = _key(cfg)
    if not key:
        raise RuntimeError("Jooble key missing — add jooble.api_key to config.yaml "
                           "(free at https://jooble.org/api/about)")

    queries = ((cfg.get("jooble") or {}).get("queries")
               or (cfg.get("adzuna") or {}).get("queries") or DEFAULT_QUERIES)
    seen: set[str] = set()
    jobs: list[Job] = []

    for q in queries:
        try:
            r = requests.post(API.format(key=key),
                              json={"keywords": q, "location": _where(cfg), "radius": "25"},
                              timeout=cfg.get("fetch", {}).get("request_timeout", 20))
            if r.status_code != 200:
                break
            results = r.json().get("jobs") or []
        except Exception:
            break

        for j in results:
            jid = str(j.get("id", ""))
            if not jid or jid in seen:
                continue
            seen.add(jid)
            jobs.append(Job(
                source=NAME,
                company=j.get("company", "") or "Unknown",
                title=j.get("title", ""),
                location=j.get("location", ""),
                url=j.get("link", ""),
                description=strip_html(j.get("snippet")),
                employment_type=j.get("type", "") or "",
                posted_at=(j.get("updated") or "")[:10],
                external_id=jid,
            ))
        time.sleep(0.4)

    return jobs
