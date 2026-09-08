"""Arbeitnow — a free public job-board API covering the German market.

No key required. The publisher asks that it not be abused, so this paginates
politely and stops as soon as it has swept the configured page budget.
"""
from __future__ import annotations

import time

from ..models import Job
from .base import get, strip_html

NAME = "arbeitnow"
API = "https://www.arbeitnow.com/api/job-board-api"


def probe(slug: str, cfg: dict) -> int | None:
    try:
        r = get(API, cfg, params={"page": 1})
        if r.status_code == 200:
            return len(r.json().get("data", []))
    except Exception:
        pass
    return None


def fetch(slug: str, company: str, cfg: dict, pages: int = 12) -> list[Job]:
    allowed = [a.lower() for a in cfg["filters"]["locations"]]
    jobs: list[Job] = []
    seen: set[str] = set()

    for page in range(1, pages + 1):
        try:
            r = get(API, cfg, params={"page": page})
            if r.status_code != 200:
                break
            batch = r.json().get("data", [])
        except Exception:
            break
        if not batch:
            break

        for j in batch:
            loc = (j.get("location") or "")
            # Filter before storing: this feed is national, we want one metro.
            if not any(a in loc.lower() for a in allowed):
                continue
            slug_id = j.get("slug", "")
            if slug_id in seen:
                continue
            seen.add(slug_id)

            types = j.get("job_types") or []
            jobs.append(Job(
                source=NAME,
                company=j.get("company_name", "") or "Unknown",
                title=j.get("title", ""),
                location=loc,
                url=j.get("url", ""),
                description=strip_html(j.get("description")),
                employment_type=" ".join(types),
                posted_at=_ts(j.get("created_at")),
                external_id=slug_id,
            ))
        time.sleep(0.4)

    return jobs


def _ts(value) -> str:
    """created_at arrives as a unix timestamp."""
    try:
        import datetime as dt
        return dt.datetime.utcfromtimestamp(int(value)).date().isoformat()
    except Exception:
        return ""
