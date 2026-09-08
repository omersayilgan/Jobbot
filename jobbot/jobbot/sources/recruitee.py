"""Recruitee career pages — https://{slug}.recruitee.com/api/offers/"""
from __future__ import annotations

from ..models import Job
from .base import get, strip_html

NAME = "recruitee"
API = "https://{slug}.recruitee.com/api/offers/"


def probe(slug: str, cfg: dict) -> int | None:
    try:
        r = get(API.format(slug=slug), cfg)
        if r.status_code == 200:
            return len(r.json().get("offers", []))
    except Exception:
        pass
    return None


def fetch(slug: str, company: str, cfg: dict) -> list[Job]:
    r = get(API.format(slug=slug), cfg)
    r.raise_for_status()

    jobs = []
    for j in r.json().get("offers", []):
        loc = ", ".join(x for x in (j.get("city"), j.get("country_code")) if x)
        jobs.append(Job(
            source=NAME,
            company=company,
            title=j.get("title", ""),
            location=loc,
            url=j.get("careers_url") or j.get("url", ""),
            description=strip_html(j.get("description")),
            employment_type=j.get("employment_type_code", "") or "",
            posted_at=(j.get("published_at") or "")[:10],
            external_id=str(j.get("id", "")),
        ))
    return jobs
