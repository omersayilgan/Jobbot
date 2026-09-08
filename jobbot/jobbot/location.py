"""Decides whether a posting is commutable from Munich.

ATS location strings are messy: Isar Aerospace posts "Ottobrunn, Bavaria,
Germany", Helsing posts "Munich", others post "Bavaria, Germany" or
"Germany - remote". This module normalises that.
"""
from __future__ import annotations

# "Bavaria" on its own is ambiguous — these cities are Bavarian but not
# commutable, so a bare Bavaria match is rejected when one of them appears.
NON_MUNICH_BAVARIA = (
    "nuremberg", "nürnberg", "nuernberg", "würzburg", "wuerzburg", "regensburg",
    "ingolstadt", "erlangen", "bayreuth", "bamberg", "passau",
    "aschaffenburg", "kempten", "landshut", "rosenheim", "schweinfurt", "fürth",
)

REMOTE_OK = ("germany", "deutschland", "europe", "emea", "anywhere")


def classify(raw_location: str, allowed: list[str]) -> tuple[bool, str]:
    """Return (is_match, note). `note` explains why, for the review dashboard."""
    loc = (raw_location or "").lower()
    if not loc:
        return False, "no location given"

    # Remote roles anchored to Germany/Europe are acceptable.
    if "remote" in loc:
        if any(k in loc for k in REMOTE_OK) or any(a in loc for a in allowed):
            return True, "remote (DE/EU)"
        return False, "remote outside DE/EU"

    hits = [a for a in allowed if a in loc]
    if not hits:
        return False, f"outside Munich area ({raw_location})"

    # A bare Bavaria/Bayern hit needs a real city to back it up.
    concrete = [h for h in hits if h not in ("bavaria", "bayern")]
    if not concrete:
        if any(c in loc for c in NON_MUNICH_BAVARIA):
            return False, f"Bavaria but not Munich ({raw_location})"
        return True, "Bavaria (verify exact site)"

    return True, concrete[0].title()
