"""ATS and aggregator adapter registry.

Every adapter exposes:
    NAME   : str
    probe(slug, cfg, **kw) -> int | None      # job count if the board exists
    fetch(slug, company, cfg, **kw) -> [Job]
"""
from . import (adzuna, arbeitnow, ashby, greenhouse, jooble, jsearch, lever,
               personio, recruitee, smartrecruiters, workable, workday)

ADAPTERS = {
    m.NAME: m for m in (greenhouse, ashby, personio, lever, recruitee,
                        smartrecruiters, workable, workday, adzuna,
                        arbeitnow, jsearch, jooble)
}

__all__ = ["ADAPTERS"]
