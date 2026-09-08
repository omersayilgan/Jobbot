"""Find which ATS a company uses, so the registry can grow without guesswork.

Two modes:
    python3 run.py discover isaraerospace                  # probe a slug
    python3 run.py discover --url https://acme.com/careers # fingerprint a page

The URL mode is the reliable one: it reads the careers page and looks for the
job-board host the page actually links to.
"""
from __future__ import annotations

import re

import requests

from .config import load_config
from .sources import ADAPTERS

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Ordered most to least specific; first match on a line wins.
FINGERPRINTS = [
    ("workday", r"https://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)"),
    ("greenhouse", r"(?:boards|job-boards)\.(?:eu\.)?greenhouse\.io/(?:embed/job_board\?for=)?([a-zA-Z0-9]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([a-z0-9-]+)"),
    ("personio", r"https://([a-z0-9-]+)\.jobs\.personio\.(?:de|com)"),
    ("lever", r"jobs\.lever\.co/([a-z0-9-]+)"),
    ("workable", r"([a-z0-9-]+)\.workable\.com"),
    ("recruitee", r"([a-z0-9-]+)\.recruitee\.com"),
    ("smartrecruiters", r"jobs\.smartrecruiters\.com/([A-Za-z0-9]+)"),
]


def variants(slug: str) -> list[str]:
    s = slug.strip().lower().replace(" ", "")
    out = [s, s.replace("-", ""), s.replace("-", "_")]
    if "-" not in s:
        for suffix in ("aerospace", "robots", "robotics", "systems", "fusion",
                       "technologies", "tech", "labs", "space", "energy"):
            if s.endswith(suffix) and len(s) > len(suffix):
                out.append(f"{s[:-len(suffix)]}-{suffix}")
    return list(dict.fromkeys(out))


def _yaml_for(ats: str, slug: str, name: str, site: str = "", host: str = "") -> str:
    if ats == "workday":
        return (f"  {ats}:\n    - {{slug: {slug}, site: {site}, host: {host}, "
                f'name: "{name}"}}')
    return f'  {ats}:\n    - {{slug: {slug}, name: "{name}"}}'


def from_url(url: str) -> list[tuple]:
    """Read a careers page and report the job board it links to."""
    print(f"Fingerprinting {url}\n")
    try:
        html = requests.get(url, headers={"User-Agent": UA}, timeout=20,
                            allow_redirects=True).text
    except Exception as exc:
        print(f"  Could not load the page: {type(exc).__name__}: {exc}")
        return []

    found, seen = [], set()
    for ats, pattern in FINGERPRINTS:
        for m in re.finditer(pattern, html):
            groups = m.groups()
            key = (ats,) + groups
            if key in seen:
                continue
            seen.add(key)

            if ats == "workday":
                slug, host, site = groups
                # Language codes appear in the same slot as the site name.
                if re.fullmatch(r"[a-z]{2}-[A-Z]{2}", site):
                    continue
                print(f"  FOUND  workday  slug={slug} site={site} host={host}")
                found.append((ats, slug, site, host))
            else:
                print(f"  FOUND  {ats:16s} slug={groups[0]}")
                found.append((ats, groups[0], "", ""))

    if not found:
        print("  No known job board linked from that page.")
        print("  Many career sites render listings in JavaScript — open the page,")
        print("  click through to an actual job, and run this on that URL instead.")
    else:
        name = re.sub(r"^www\.|\.(com|de|net|io|space|ai)$", "",
                      re.sub(r"^https?://", "", url).split("/")[0]).title()
        print("\nAdd to companies.yaml:")
        for ats, slug, site, host in found[:3]:
            print(_yaml_for(ats, slug, name, site, host))
    return found


def run(slug: str) -> list[tuple]:
    cfg = load_config()
    found = []
    probeable = {k: v for k, v in ADAPTERS.items() if k not in ("workday", "adzuna")}
    print(f"Probing '{slug}' across {len(probeable)} ATS platforms...\n")

    for ats_name, mod in probeable.items():
        for v in variants(slug):
            try:
                count = mod.probe(v, cfg)
            except Exception:
                count = None
            if count:
                print(f"  FOUND  {ats_name:16s} slug='{v}'  {count} open roles")
                found.append((ats_name, v, count))
                break

    if not found:
        print("  No public job board found under that slug.")
        print("  Try fingerprinting the careers page instead:")
        print(f"    python3 run.py discover --url https://<company>/careers")
    else:
        print("\nAdd to companies.yaml:")
        for ats_name, v, _ in found:
            print(_yaml_for(ats_name, v, slug.title()))
    return found
