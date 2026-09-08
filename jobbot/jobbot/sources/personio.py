"""Personio career pages — https://{slug}.jobs.personio.de/xml

Personio rate-limits hard (HTTP 429). Always go through the throttled helper.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ..models import Job
from .base import get, strip_html

NAME = "personio"
API = "https://{slug}.jobs.personio.de/xml"
JOB_URL = "https://{slug}.jobs.personio.de/job/{jid}"


def _positions(text: str):
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    return root.findall(".//position")


def probe(slug: str, cfg: dict) -> int | None:
    try:
        r = get(API.format(slug=slug), cfg, accept="application/xml", host_delay=2.0)
        if r.status_code == 200 and "<position>" in r.text:
            return len(_positions(r.text))
    except Exception:
        pass
    return None


def _text(node, tag: str) -> str:
    el = node.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


def fetch(slug: str, company: str, cfg: dict) -> list[Job]:
    delay = cfg.get("fetch", {}).get("delay_between_companies", 2.0)
    r = get(API.format(slug=slug), cfg, accept="application/xml", host_delay=delay)
    r.raise_for_status()

    jobs = []
    for p in _positions(r.text):
        jid = _text(p, "id")

        # Description lives in nested <jobDescription><name/><value/> pairs.
        parts = []
        for jd in p.findall(".//jobDescription"):
            parts.append(_text(jd, "name"))
            parts.append(strip_html(_text(jd, "value")))

        offices = [_text(p, "office")] + [
            (o.text or "").strip() for o in p.findall(".//additionalOffices/office")
        ]

        jobs.append(Job(
            source=NAME,
            company=_text(p, "subcompany") or company,
            title=_text(p, "name"),
            location=", ".join(o for o in offices if o),
            url=JOB_URL.format(slug=slug, jid=jid),
            description="\n".join(x for x in parts if x),
            # Personio splits these: employmentType=permanent, schedule=full-time
            employment_type=f"{_text(p, 'schedule')} {_text(p, 'employmentType')}".strip(),
            posted_at=_text(p, "createdAt")[:10],
            external_id=jid,
        ))
    return jobs
