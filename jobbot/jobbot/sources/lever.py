"""Lever job boards — https://api.lever.co/v0/postings/{slug}"""
from __future__ import annotations

from ..models import Job
from .base import get, strip_html

NAME = "lever"
API = "https://api.lever.co/v0/postings/{slug}"


def probe(slug: str, cfg: dict) -> int | None:
    try:
        r = get(API.format(slug=slug), cfg, params={"mode": "json"})
        if r.status_code == 200:
            data = r.json()
            return len(data) if isinstance(data, list) else None
    except Exception:
        pass
    return None


def fetch(slug: str, company: str, cfg: dict) -> list[Job]:
    r = get(API.format(slug=slug), cfg, params={"mode": "json"})
    r.raise_for_status()

    jobs = []
    for j in r.json():
        cats = j.get("categories") or {}
        jobs.append(Job(
            source=NAME,
            company=company,
            title=j.get("text", ""),
            location=cats.get("location", "") or "",
            url=j.get("hostedUrl") or j.get("applyUrl", ""),
            description=j.get("descriptionPlain") or strip_html(j.get("description")),
            employment_type=cats.get("commitment", "") or "",
            posted_at="",
            external_id=str(j.get("id", "")),
        ))
    return jobs
