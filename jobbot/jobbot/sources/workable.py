"""Workable job boards — https://apply.workable.com/api/v1/widget/accounts/{slug}"""
from __future__ import annotations

from ..models import Job
from .base import get, strip_html

NAME = "workable"
API = "https://apply.workable.com/api/v1/widget/accounts/{slug}"


def probe(slug: str, cfg: dict) -> int | None:
    try:
        r = get(API.format(slug=slug), cfg, params={"details": "true"})
        if r.status_code == 200:
            return len(r.json().get("jobs", []))
    except Exception:
        pass
    return None


def fetch(slug: str, company: str, cfg: dict) -> list[Job]:
    r = get(API.format(slug=slug), cfg, params={"details": "true"})
    r.raise_for_status()

    jobs = []
    for j in r.json().get("jobs", []):
        loc = ", ".join(x for x in (j.get("city"), j.get("country")) if x)
        jobs.append(Job(
            source=NAME,
            company=company,
            title=j.get("title", ""),
            location=loc,
            url=j.get("url") or j.get("application_url", ""),
            description=strip_html(j.get("description")) + " " +
                        strip_html(j.get("requirements")),
            employment_type=j.get("employment_type", "") or "",
            posted_at=(j.get("published_on") or "")[:10],
            external_id=str(j.get("shortcode") or j.get("id", "")),
        ))
    return jobs
