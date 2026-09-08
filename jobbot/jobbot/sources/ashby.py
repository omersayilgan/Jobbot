"""Ashby job boards — https://api.ashbyhq.com/posting-api"""
from __future__ import annotations

from ..models import Job
from .base import get, strip_html

NAME = "ashby"
API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def probe(slug: str, cfg: dict) -> int | None:
    try:
        r = get(API.format(slug=slug), cfg)
        if r.status_code == 200:
            return len(r.json().get("jobs", []))
    except Exception:
        pass
    return None


def fetch(slug: str, company: str, cfg: dict) -> list[Job]:
    r = get(API.format(slug=slug), cfg, params={"includeCompensation": "true"})
    r.raise_for_status()

    jobs = []
    for j in r.json().get("jobs", []):
        jobs.append(Job(
            source=NAME,
            company=company,
            title=j.get("title", ""),
            location=j.get("location", "") or "",
            url=j.get("jobUrl") or j.get("applyUrl", ""),
            description=strip_html(j.get("descriptionHtml") or j.get("descriptionPlain")),
            employment_type=j.get("employmentType", "") or "",
            posted_at=(j.get("publishedAt") or "")[:10],
            external_id=str(j.get("id", "")),
        ))
    return jobs
