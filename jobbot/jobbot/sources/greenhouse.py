"""Greenhouse job boards — https://boards-api.greenhouse.io"""
from __future__ import annotations

from ..models import Job
from .base import get, strip_html

NAME = "greenhouse"
API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def probe(slug: str, cfg: dict) -> int | None:
    """Return job count if this slug is a live Greenhouse board, else None."""
    try:
        r = get(API.format(slug=slug), cfg)
        if r.status_code == 200:
            return len(r.json().get("jobs", []))
    except Exception:
        pass
    return None


def fetch(slug: str, company: str, cfg: dict) -> list[Job]:
    # content=true returns the full description in one call — needed for scoring.
    r = get(API.format(slug=slug), cfg, params={"content": "true"})
    r.raise_for_status()

    jobs = []
    for j in r.json().get("jobs", []):
        jobs.append(Job(
            source=NAME,
            company=j.get("company_name") or company,
            title=j.get("title", ""),
            location=(j.get("location") or {}).get("name", ""),
            url=j.get("absolute_url", ""),
            description=strip_html(j.get("content")),
            posted_at=(j.get("first_published") or j.get("updated_at") or "")[:10],
            external_id=str(j.get("id", "")),
        ))
    return jobs
