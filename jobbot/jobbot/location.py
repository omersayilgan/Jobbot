"""Decides whether a posting is commutable from the profile's home area.

ATS location strings are messy: one board posts "Ottobrunn, Bavaria, Germany",
another "Munich", another "Bavaria, Germany" or "Germany - remote". The metro
definition in the profile supplies three lists that sort that out:

    locations           city, suburbs and region names that count as a match
    ambiguous_locations region names that are too broad to accept alone
    location_excludes   places inside that region that are not commutable
    remote_anchors      countries/areas a remote posting may be tied to
"""
from __future__ import annotations


def classify(raw_location: str, allowed: list[str], ambiguous: list[str] | None = None,
             excludes: list[str] | None = None, remote_ok: list[str] | None = None,
             label: str = "your area") -> tuple[bool, str]:
    """Return (is_match, note). `note` explains why, for the review dashboard."""
    loc = (raw_location or "").lower()
    ambiguous = [a.lower() for a in (ambiguous or [])]
    excludes = [e.lower() for e in (excludes or [])]
    remote_ok = [r.lower() for r in (remote_ok or [])]

    if not loc:
        return False, "no location given"

    if "remote" in loc:
        if any(k in loc for k in remote_ok) or any(a in loc for a in allowed):
            return True, "remote (in range)"
        return False, "remote, outside your region"

    hits = [a for a in allowed if a in loc]
    if not hits:
        return False, f"outside {label} ({raw_location})"

    # A hit on the region name alone ("Bavaria") is not enough — the region
    # contains cities that are nowhere near. It only counts if no excluded
    # city is named alongside it.
    concrete = [h for h in hits if h not in ambiguous]
    if not concrete:
        if any(c in loc for c in excludes):
            return False, f"in the region but not near {label} ({raw_location})"
        return True, f"{hits[0].title()} (verify the exact site)"

    return True, concrete[0].title()
