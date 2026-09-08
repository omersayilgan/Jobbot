"""Workday CXS job boards — where the big aerospace and industrial employers post.

Workday's list endpoint returns no description, so scoring needs a second call
per posting. To keep that affordable we search by Munich-area place name first,
filter on the returned location, and only then fetch details for survivors.

Registry entry shape:
    - {slug: ag, site: Airbus, host: wd3, name: "Airbus"}
"""
from __future__ import annotations

import time

import requests

from ..models import Job
from .base import strip_html

NAME = "workday"
LIST = "https://{slug}.{host}.myworkdayjobs.com/wday/cxs/{slug}/{site}/jobs"
DETAIL = "https://{slug}.{host}.myworkdayjobs.com/wday/cxs/{slug}/{site}{path}"
PUBLIC = "https://{slug}.{host}.myworkdayjobs.com/{site}{path}"

# Searched one at a time; Workday matches these against the location facet.
SEARCH_TERMS = ("Munich", "München", "Ottobrunn", "Taufkirchen", "Garching",
                "Manching", "Unterschleissheim", "Ismaning")

PAGE = 20
MAX_DETAILS = 160         # ceiling on detail calls per company, per run


def _post(url: str, cfg: dict, payload: dict):
    return requests.post(
        url, json=payload,
        timeout=cfg.get("fetch", {}).get("request_timeout", 20),
        headers={
            "User-Agent": cfg.get("fetch", {}).get("user_agent", "jobbot/1.0"),
            "Content-Type": "application/json",
            "Accept": "application/json",
        })


def probe(slug: str, cfg: dict, site: str = "Careers", host: str = "wd3") -> int | None:
    try:
        r = _post(LIST.format(slug=slug, host=host, site=site), cfg,
                  {"appliedFacets": {}, "limit": 1, "offset": 0})
        if r.status_code == 200:
            return r.json().get("total")
    except Exception:
        pass
    return None


def _munich_terms(cfg: dict) -> list[str]:
    return [a.lower() for a in cfg["filters"]["locations"]]


def fetch(slug: str, company: str, cfg: dict, site: str = "Careers",
          host: str = "wd3") -> list[Job]:
    list_url = LIST.format(slug=slug, host=host, site=site)
    allowed = _munich_terms(cfg)
    seen: dict[str, dict] = {}

    for term in SEARCH_TERMS:
        offset = 0
        while True:
            r = _post(list_url, cfg, {"appliedFacets": {}, "limit": PAGE,
                                      "offset": offset, "searchText": term})
            if r.status_code != 200:
                break
            data = r.json()
            posts = data.get("jobPostings", [])
            if not posts:
                break

            for p in posts:
                loc = (p.get("locationsText") or "").lower()
                path = p.get("externalPath")
                # "2 Locations" hides the detail — keep it, the detail call resolves it.
                if not path or path in seen:
                    continue
                if any(a in loc for a in allowed) or "location" in loc:
                    seen[path] = p

            offset += PAGE
            if offset >= min(data.get("total", 0), 200):
                break
            time.sleep(0.2)

    jobs: list[Job] = []
    for path, p in list(seen.items())[:MAX_DETAILS]:
        try:
            d = requests.get(
                DETAIL.format(slug=slug, host=host, site=site, path=path),
                timeout=cfg.get("fetch", {}).get("request_timeout", 20),
                headers={"Accept": "application/json",
                         "User-Agent": cfg.get("fetch", {}).get("user_agent", "jobbot/1.0")})
            info = d.json().get("jobPostingInfo", {}) if d.status_code == 200 else {}
        except Exception:
            info = {}

        location = info.get("location") or p.get("locationsText") or ""
        if not any(a in location.lower() for a in allowed):
            continue

        jobs.append(Job(
            source=NAME,
            company=company,
            title=info.get("title") or p.get("title", ""),
            location=location,
            url=info.get("externalUrl") or PUBLIC.format(
                slug=slug, host=host, site=site, path=path),
            description=strip_html(info.get("jobDescription")),
            employment_type=info.get("timeType", "") or "",
            posted_at=(info.get("startDate") or "")[:10],
            external_id=info.get("jobReqId") or (p.get("bulletFields") or [""])[0],
        ))
        time.sleep(0.15)

    return jobs
