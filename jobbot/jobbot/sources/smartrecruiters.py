"""SmartRecruiters — https://api.smartrecruiters.com/v1/companies/{slug}/postings

The list endpoint omits the description, so each posting needs a detail call.
"""
from __future__ import annotations

from ..models import Job
from .base import get, strip_html

NAME = "smartrecruiters"
API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
DETAIL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings/{jid}"


def probe(slug: str, cfg: dict) -> int | None:
    try:
        r = get(API.format(slug=slug), cfg, params={"limit": 10})
        if r.status_code == 200:
            return r.json().get("totalFound")
    except Exception:
        pass
    return None


def _describe(slug: str, jid: str, cfg: dict) -> str:
    try:
        r = get(DETAIL.format(slug=slug, jid=jid), cfg)
        if r.status_code != 200:
            return ""
        sections = ((r.json().get("jobAd") or {}).get("sections") or {})
        return "\n".join(
            strip_html((sections.get(k) or {}).get("text"))
            for k in ("companyDescription", "jobDescription", "qualifications", "additionalInformation")
        ).strip()
    except Exception:
        return ""


def fetch(slug: str, company: str, cfg: dict) -> list[Job]:
    jobs, offset = [], 0
    while True:
        r = get(API.format(slug=slug), cfg, params={"limit": 100, "offset": offset})
        r.raise_for_status()
        data = r.json()
        batch = data.get("content", [])
        if not batch:
            break

        for j in batch:
            loc = j.get("location") or {}
            jid = str(j.get("id", ""))
            jobs.append(Job(
                source=NAME,
                company=company,
                title=j.get("name", ""),
                location=", ".join(x for x in (loc.get("city"), loc.get("country")) if x),
                url=f"https://jobs.smartrecruiters.com/{slug}/{jid}",
                description=_describe(slug, jid, cfg),
                employment_type=(j.get("typeOfEmployment") or {}).get("label", "") or "",
                posted_at=(j.get("releasedDate") or "")[:10],
                external_id=jid,
            ))

        offset += len(batch)
        if offset >= data.get("totalFound", 0):
            break
    return jobs
