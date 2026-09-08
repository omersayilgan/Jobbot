"""Core data model: one normalised job posting, whatever ATS it came from."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Job:
    source: str                 # ats adapter name, e.g. "greenhouse"
    company: str
    title: str
    location: str
    url: str                    # public apply/detail link
    description: str = ""       # plain text, used for scoring
    employment_type: str = ""   # raw ATS string, e.g. "full-time", "permanent"
    posted_at: str = ""
    external_id: str = ""

    # filled in by the scorer
    score: int = 0             # normalised 0-100
    raw_score: int = 0         # unnormalised points, useful for tuning
    matched: dict[str, list[str]] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def uid(self) -> str:
        """Stable id so re-fetching does not create duplicates."""
        basis = f"{self.source}:{self.company}:{self.external_id or self.url}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["uid"] = self.uid
        return d
