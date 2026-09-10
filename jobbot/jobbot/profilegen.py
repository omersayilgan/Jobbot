"""Turns extracted document facts into a complete, personal jobbot config.

Two stages, deliberately separated:

    gather()    documents -> profile.yaml   (plain facts, meant to be edited)
    generate()  profile.yaml -> config.yaml, letters.yaml, skills_taxonomy.yaml,
                                companies.yaml, narrative.yaml

Because the second stage reads only profile.yaml, correcting a wrong guess is
editing one readable file and re-running `python3 setup.py --regenerate`. No
PDF is parsed twice and no hand-edit is silently overwritten.

Everything here is offline string matching against ontology/professions.yaml.
There is no model in the loop, which means the output is only as good as the
ontology — so when a profession is served badly, the fix is to add a domain
there rather than to change this code.
"""
from __future__ import annotations

import os
import re
import unicodedata
from collections import defaultdict

import yaml

ONTO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ontology")

# Evidence is weighted by how much a source proves. Holding the job title is
# the strongest claim available; a word in a skills list is the weakest.
W_TITLE = 6.0
W_BULLET = 4.0
W_SKILLLINE = 2.5
W_COURSE = 2.0
W_TEXT = 0.7

MAX_DOMAINS = 8
MIN_DOMAINS = 3
ABSOLUTE_FLOOR = 3.0
WEIGHT_TOP = 26
WEIGHT_FLOOR = 10


def _load(name: str) -> dict:
    with open(os.path.join(ONTO_DIR, name), "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def ontology() -> dict:
    return _load("professions.yaml")


def locations() -> dict:
    return _load("locations.yaml")


def grades() -> dict:
    return _load("grades.yaml")


def _term_re(term: str) -> re.Pattern:
    t = term.strip().lower()
    if t.endswith("*"):
        return re.compile(r"(?<![a-z0-9äöüß])" + re.escape(t[:-1]))
    return re.compile(r"(?<![a-z0-9äöüß])" + re.escape(t) + r"(?![a-z0-9äöüß])")


def _hits(text: str, terms) -> list[str]:
    low = text.lower()
    return [t for t in terms if _term_re(t).search(low)]


def slugify(text: str) -> str:
    # PDF text often arrives decomposed ("O" + combining diaeresis), so the
    # accented characters have to be folded before they can be substituted.
    s = unicodedata.normalize("NFC", text or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("ı", "i"),
                 ("ş", "s"), ("ğ", "g"), ("ç", "c"), ("é", "e"), ("è", "e"),
                 ("å", "a"), ("ø", "o"), ("ñ", "n")):
        s = s.replace(a, b)
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "profile"


# ---------------------------------------------------------------- stage 1: gather

def _match_metro(text: str, locs: dict) -> tuple[str, dict]:
    """Find which metro the CV points at. Aliases beat suburb names."""
    low = text.lower()
    for key, spec in locs["metros"].items():
        if any(_term_re(a).search(low) for a in spec["aliases"]):
            return key, spec
    for key, spec in locs["metros"].items():
        if any(_term_re(t).search(low) for t in spec.get("towns", [])):
            return key, spec
    return "", {}


def _career_stage(years: float, is_student: bool, text: str) -> str:
    low = text.lower()
    if re.search(r"\b(head of|vp of|director|chief|geschäftsführer|principal engineer|"
                 r"partner|c[te]o)\b", low):
        return "leadership"
    if is_student and years < 2:
        return "student"
    if years < 2:
        return "entry"
    if years < 6:
        return "mid"
    if years < 12:
        return "senior"
    return "principal"


def _domain_evidence(cv, transcripts, onto) -> dict:
    """Score every ontology domain against the documents, keeping the receipts."""
    title_blob = " ".join(cv.job_titles)
    bullet_blob = "\n".join(cv.experience_bullets)
    skill_blob = "\n".join(cv.skill_lines + cv.education_lines)
    course_blob = "\n".join(c.name for t in transcripts for c in t.courses)

    out = {}
    for key, dom in onto["domains"].items():
        all_terms = sorted({t for terms in dom["skills"].values() for t in terms}
                           | set(dom.get("tools") or []))
        score = 0.0
        why: list[str] = []

        t_hits = _hits(title_blob, dom.get("titles", []) + all_terms)
        if t_hits:
            score += W_TITLE * min(len(t_hits), 3)
            why.append(f"job title: {', '.join(sorted(set(t_hits))[:3])}")
        b_hits = _hits(bullet_blob, all_terms)
        if b_hits:
            score += W_BULLET * min(len(b_hits), 4)
            why.append(f"work experience: {', '.join(sorted(set(b_hits))[:5])}")
        s_hits = _hits(skill_blob, all_terms)
        if s_hits:
            score += W_SKILLLINE * min(len(s_hits), 8)
            why.append(f"skills section: {', '.join(sorted(set(s_hits))[:5])}")
        c_hits = _hits(course_blob, dom.get("course_terms", []) + all_terms)
        if c_hits:
            score += W_COURSE * min(len(c_hits), 6)
            why.append(f"coursework: {', '.join(sorted(set(c_hits))[:4])}")
        x_hits = _hits(cv.all_text, all_terms)
        if x_hits:
            score += W_TEXT * min(len(x_hits), 8)

        if t_hits:
            # Having held the title is a different order of evidence from
            # having used the tools once inside someone else's job.
            score *= 1.3
        if score and not (t_hits or b_hits or s_hits):
            score *= 0.5
            why.append("coursework only — no professional or CV evidence")
        if score:
            out[key] = {"score": round(score, 1), "why": why,
                        "hits": sorted(set(t_hits + b_hits + s_hits + x_hits))}
    return out


def _skill_levels(cv, transcripts, onto) -> dict:
    """have / partial / gap per skill, with the sentence that justifies it.

    The distinction that matters to an employer is production evidence versus
    academic exposure, so the source of the hit decides the level rather than
    the mere presence of the word.
    """
    title_blob = " ".join(cv.job_titles)
    bullet_blob = "\n".join(cv.experience_bullets)
    # Thesis and specialisation lines are real evidence, but academic rather
    # than professional — they land as "partial", which is what they are.
    skill_blob = "\n".join(cv.skill_lines + cv.education_bullets)
    course_lookup = [(c.name, c.performance, t.scale)
                     for t in transcripts for c in t.courses]
    levels = {}

    groups = dict(onto["domains"])
    universal = onto.get("universal")
    for key, dom in list(groups.items()) + ([("_universal", universal)] if universal else []):
        for skill, terms in dom["skills"].items():
            in_work = _hits(bullet_blob, terms) or _hits(title_blob, terms)
            in_skills = _hits(skill_blob, terms)
            courses = [(n, p) for n, p, _ in course_lookup if _hits(n, terms)]

            if in_work:
                level, why = "have", f"used in work experience ({', '.join(sorted(set(in_work))[:3])})"
            elif in_skills and courses:
                best = max(courses, key=lambda c: c[1])
                level = "have"
                why = f"listed as a skill and studied ({best[0][:44]})"
            elif in_skills:
                level, why = "partial", (f"claimed on the CV ({', '.join(sorted(set(in_skills))[:3])}) "
                                         f"but no work evidence found")
            elif courses:
                best = max(courses, key=lambda c: c[1])
                level = "partial" if best[1] >= 0.5 else "gap"
                why = f"coursework only ({best[0][:44]})"
            else:
                level, why = "gap", "no evidence in your documents"
            levels[skill] = {"level": level, "why": why,
                             "group": dom.get("label", "Other")}
    return levels


MIN_ACADEMIC_CREDITS = 6.0
MIN_ACADEMIC_COURSES = 2
ACADEMIC_BAND = 0.07


def _academic(transcripts, onto, gr) -> dict:
    """Credit-weighted performance per domain, relative to this person's own mean.

    Absolute cut-offs do not travel: a 2.7 average is respectable in Germany
    and a 3.0 GPA means something else entirely in the US. What is comparable
    is the distance between a subject and the same person's overall record.
    """
    per: dict[str, list] = defaultdict(list)
    for t in transcripts:
        for c in t.courses:
            weight = c.credits if c.credits else 3.0
            for key, dom in onto["domains"].items():
                if _hits(c.name, dom.get("course_terms", [])):
                    per[key].append((c.performance, weight, c.name, c.grade))

    all_courses = [(c.performance, c.credits or 3.0) for t in transcripts for c in t.courses]
    total_w = sum(w for _, w in all_courses)
    mean = sum(p * w for p, w in all_courses) / total_w if total_w else 0.0
    hi, lo = mean + ACADEMIC_BAND, mean - ACADEMIC_BAND

    strong, weak, neutral = [], [], []
    for key, rows in per.items():
        tot_w = sum(w for _, w, _, _ in rows)
        avg = sum(p * w for p, w, _, _ in rows) / tot_w if tot_w else 0.0
        thin = tot_w < MIN_ACADEMIC_CREDITS or len(rows) < MIN_ACADEMIC_COURSES
        entry = {
            "domain": key,
            "label": onto["domains"][key]["label"],
            "performance": round(avg, 3),
            "credits": round(tot_w, 1),
            "courses": [{"name": n, "grade": g, "performance": p}
                        for p, _, n, g in sorted(rows, reverse=True)[:8]],
        }
        entry["courses_counted"] = len(rows)
        if thin:
            neutral.append(entry)
        else:
            (strong if avg >= hi else weak if avg <= lo else neutral).append(entry)

    strong.sort(key=lambda e: -e["performance"])
    weak.sort(key=lambda e: e["performance"])
    return {"mean": round(mean, 3), "strong": strong, "weak": weak, "neutral": neutral}


def weakness_terms(profile: dict, onto: dict) -> dict[str, list[str]]:
    """Terms that mark a subject this person did comparatively badly in.

    Anything a selected domain also claims is removed first, so the academic
    layer only ever down-ranks ground the profile is not standing on.
    """
    selected = {d["key"] for d in profile.get("domains", [])}
    protected: set[str] = set()
    for key in selected:
        dom = onto["domains"].get(key, {})
        for terms in dom.get("skills", {}).values():
            protected |= {t.lower() for t in terms}

    out: dict[str, list[str]] = {}
    for entry in profile.get("academic", {}).get("weak", []):
        dom = onto["domains"].get(entry["domain"])
        if not dom:
            continue
        terms = sorted({t.lower() for group in dom["skills"].values() for t in group}
                       - protected)
        terms = [t for t in terms if len(t) > 3 and not t.endswith("*")]
        if terms:
            out[entry["domain"]] = terms[:22]
    return out


def gather(cv, transcripts, docs, root: str) -> dict:
    """Documents -> the editable facts file."""
    onto, locs, gr = ontology(), locations(), grades()
    text = cv.all_text + "\n" + "\n".join(t.all_text[:3000] for t in transcripts)

    metro_key, metro = _match_metro(text, locs)
    country = metro.get("country", "")
    if not country:
        for code, spec in locs["countries"].items():
            if any(_term_re(n).search(text.lower()) for n in spec["names"][:2]):
                country = code
                break

    ev = _domain_evidence(cv, transcripts, onto)
    ranked = sorted(ev.items(), key=lambda kv: -kv[1]["score"])
    # A specialist can legitimately occupy one dominant domain, but a config
    # built from one domain scores everything else at zero. Keep a floor of
    # MIN_DOMAINS so adjacent roles still surface.
    cutoff = max(5.0, (ranked[0][1]["score"] * 0.12) if ranked else 5.0)

    chosen: list[tuple[str, dict]] = []
    claimed: set[str] = set()
    for key, v in ranked:
        if len(chosen) >= MAX_DOMAINS:
            break
        if v["score"] < cutoff and len(chosen) >= MIN_DOMAINS:
            continue
        if v["score"] < ABSOLUTE_FLOOR:
            continue
        hits = set(v["hits"])
        if chosen and hits and len(hits - claimed) / len(hits) < 0.25:
            v["skipped"] = "evidence already covered by a stronger domain"
            continue
        chosen.append((key, v))
        claimed |= hits

    domains = []
    if chosen:
        top = chosen[0][1]["score"]
        for i, (key, v) in enumerate(chosen):
            share = v["score"] / top
            weight = int(round(WEIGHT_FLOOR + (WEIGHT_TOP - WEIGHT_FLOOR) * share))
            domains.append({
                "key": key,
                "label": onto["domains"][key]["label"],
                "weight": weight,
                "evidence_score": v["score"],
                "evidence": v["why"],
            })

    stage = _career_stage(cv.years_experience, cv.is_student, cv.all_text)
    city = metro.get("label", "")
    if not city:
        m = re.search(r"\b([A-ZÄÖÜ][a-zäöüß]{3,}(?:\s[A-ZÄÖÜ][a-zäöüß]+)?)\s*,\s*"
                      r"(?:germany|deutschland|austria|switzerland|türkiye|turkey)", text)
        city = m.group(1) if m else ""

    extra = [os.path.relpath(d.path, root) for d in docs
             if d.kind in ("transcript", "certificate") and d.kind != "cv"]
    cv_path = os.path.relpath(next((d.path for d in docs if d.kind == "cv"), ""), root) \
        if any(d.kind == "cv" for d in docs) else ""

    return {
        "identity": {
            "full_name": cv.full_name,
            "email": cv.email,
            "phone": cv.phone,
            "address": ", ".join(x for x in (cv.address, city) if x),
            "city": city,
            "metro": metro_key,
            "country": country or "de",
        },
        "status": {
            "career_stage": stage,
            "years_experience": cv.years_experience,
            "is_student": cv.is_student,
            "highest_degree": cv.highest_degree,
            "current_titles": cv.job_titles[:4],
            "employers": cv.employers[:4],
            "headline": _headline(cv, transcripts, stage),
        },
        "languages": cv.languages,
        "documents": {"cv": cv_path, "extra": extra},
        "domains": domains,
        "academic": _academic(transcripts, onto, gr),
        "skills": _skill_levels(cv, transcripts, onto),
        "evidence_bullets": (cv.experience_bullets + cv.education_bullets)[:50],
        "transcripts": [
            {"scale": t.scale, "scale_label": t.scale_label, "institution": t.institution,
             "program": t.program, "overall": t.overall, "courses": len(t.courses)}
            for t in transcripts
        ],
    }


def _article(word: str) -> str:
    """'an M.Sc.' but 'a Master' — the sound decides, not the letter."""
    first = word.strip()[:1].lower()
    if not first:
        return "a"
    if word.strip()[:1].isupper() and first not in "aeiou":
        # Initialisms are read letter by letter: M, F, S, X start with a vowel sound.
        if word.strip()[:2].isupper() or "." in word.strip()[:4]:
            return "an" if first in "aefhilmnorsx" else "a"
    return "an" if first in "aeiou" else "a"


def _headline(cv, transcripts, stage) -> str:
    """One clause describing the person, used in letters and report headers.

    Phrased as a noun phrase with its article, because the letter templates
    read "I am {headline}".
    """
    degree = {"phd": "PhD", "master": "M.Sc.", "bachelor": "B.Sc.",
              "vocational": "vocational qualification"}.get(cv.highest_degree, "")
    program = next((t.program for t in transcripts if t.program), "")
    inst = next((t.institution for t in transcripts if t.institution), "")
    role = cv.job_titles[0] if cv.job_titles else ""
    if stage == "student" and degree:
        base = f"{_article(degree)} {degree} student"
        if program:
            base += f" in {program}"
        if inst:
            base += f" at {inst}"
        return base + ", graduating soon"
    bits = []
    if role:
        bits.append(f"{_article(role)} {role}")
    # A bare "a B.Sc." adds nothing next to a job title; with a subject it does.
    if degree and (program or not role):
        bits.append(f"{_article(degree)} {degree}" + (f" in {program}" if program else ""))
    if cv.years_experience >= 1:
        years = int(round(cv.years_experience))
        bits.append(f"{years} year{'s' if years != 1 else ''} of professional experience")
    if not bits:
        return "a professional in this field"
    if len(bits) == 1:
        return bits[0]
    return ", ".join(bits[:-1]) + " with " + bits[-1] \
        if "years" in bits[-1] else ", ".join(bits)


# ---------------------------------------------------------------- stage 2: generate

def market() -> dict:
    return _load("market.yaml")


LEVEL_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5,
               "Native": 6, "unspecified": 2}

GENERIC_TITLE_WORDS = {
    "engineering": ["engineer", "ingenieur", "entwickler", "developer", "techniker"],
    "software": ["engineer", "developer", "entwickler", "software engineer"],
    "science": ["scientist", "researcher", "wissenschaftlicher mitarbeiter", "analyst"],
    "business": ["manager", "analyst", "specialist", "referent", "consultant"],
    "healthcare": ["specialist", "practitioner", "fachkraft", "clinician"],
    "education": ["teacher", "trainer", "dozent", "lecturer"],
    "creative": ["designer", "gestalter", "creative"],
    "operations": ["technician", "techniker", "operator", "specialist"],
}

TITLE_TIERS = [40, 34, 30, 28, 26, 24, 24, 24]


def _strip_star(terms) -> list[str]:
    return [t for t in terms if not t.endswith("*")]


def _domain_terms(dom: dict, limit: int = 60) -> list[str]:
    seen: list[str] = []
    for terms in dom["skills"].values():
        for t in terms:
            if t not in seen:
                seen.append(t)
    return seen[:limit]


def _local_language(profile: dict, locs: dict) -> tuple[str, str, str]:
    """(language code, display name, the person's level in it)."""
    country = profile["identity"].get("country") or "de"
    code = (locs["countries"].get(country) or {}).get("language", "en")
    names = {"de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
             "nl": "Dutch", "pl": "Polish", "tr": "Turkish", "cs": "Czech", "en": "English"}
    name = names.get(code, code.upper())
    level = ""
    for lang, lvl in (profile.get("languages") or {}).items():
        if lang.lower() == name.lower():
            level = lvl
            break
    return code, name, level or "unspecified"


def _exclusions(profile: dict, onto: dict, mkt: dict) -> list[str]:
    """Base exclusions minus anything the person's own field needs kept."""
    stage = profile["status"]["career_stage"]
    out: list[str] = list(mkt["exclude"]["always"])
    out += mkt["exclude"]["by_stage"].get(stage, mkt["exclude"]["by_stage"]["entry"])

    families = {onto["domains"][d["key"]]["family"] for d in profile["domains"]
                if d["key"] in onto["domains"]}
    own_titles = " ".join(t.lower() for d in profile["domains"]
                          for t in onto["domains"].get(d["key"], {}).get("titles", []))
    own_titles += " " + " ".join(t.lower() for t in profile["status"].get("current_titles", []))

    for block, words in mkt["exclude"]["functions"].items():
        dom = onto["domains"].get(block)
        # Skip the whole block if this is the person's own field, or if any of
        # its words appear in a title they have actually held.
        if block in {d["key"] for d in profile["domains"]}:
            continue
        if dom and dom["family"] in families and dom["family"] not in ("engineering", "software"):
            continue
        keep = [w for w in words if w.lower() not in own_titles]
        if len(keep) < len(words):
            continue                       # they hold one of these titles: leave the family alone
        out += words

    seen, uniq = set(), []
    for w in out:
        if w.lower() not in seen:
            seen.add(w.lower())
            uniq.append(w)
    return uniq


def _language_block(profile: dict, locs: dict, mkt: dict) -> dict:
    code, name, level = _local_language(profile, locs)
    reqs = mkt["language_requirements"].get(code)
    block: dict = {"local_language": name, "your_level": level, "penalty": {}, "boost": {}}
    if not reqs:
        return block
    mine = LEVEL_ORDER.get(level, 2)
    if mine >= LEVEL_ORDER["C1"]:
        return block                        # a strict requirement costs them nothing
    p = mkt["language_penalty"]
    strict = p["strict_near"] if mine == LEVEL_ORDER["B2"] else p["strict_far"]
    block["penalty"][strict] = list(reqs["strict"])
    if mine < LEVEL_ORDER["B2"]:
        block["penalty"][p["mild"]] = list(reqs["mild"])
    block["boost"][p["english_boost"]] = list(reqs["english_ok"])
    return block


def _queries(profile: dict, onto: dict, city: str) -> tuple[list[str], list[str]]:
    """Aggregator search strings, from the role families the person fits."""
    plain, located = [], []
    for d in profile["domains"][:5]:
        dom = onto["domains"].get(d["key"])
        if not dom:
            continue
        for title in dom.get("titles", [])[:2]:
            if title not in plain:
                plain.append(title)
                located.append(f"{title} {city}".strip().lower())
    return plain[:10], located[:6]


def gen_config(profile: dict, onto: dict, locs: dict, mkt: dict) -> dict:
    ident, status = profile["identity"], profile["status"]
    metro = locs["metros"].get(ident.get("metro"), {})
    country = locs["countries"].get(ident.get("country") or "de", {})
    city = ident.get("city") or metro.get("label", "")

    if metro:
        places = list(dict.fromkeys(metro["aliases"] + metro.get("towns", [])
                                    + metro.get("region", [])))
        excludes = list(metro.get("region_excludes", []))
        ambiguous = list(metro.get("region", []))
    else:
        places = [p for p in [city.lower()] if p]
        excludes, ambiguous = [], []

    skills = {}
    for d in profile["domains"]:
        dom = onto["domains"].get(d["key"])
        if dom:
            skills[d["key"]] = {"weight": d["weight"], "terms": _domain_terms(dom)}

    title_bonus: dict[int, list[str]] = {}
    for i, d in enumerate(profile["domains"]):
        dom = onto["domains"].get(d["key"])
        if not dom:
            continue
        pts = TITLE_TIERS[min(i, len(TITLE_TIERS) - 1)]
        title_bonus.setdefault(pts, []).extend(dom.get("titles", []))
    families = [onto["domains"][d["key"]]["family"] for d in profile["domains"]
                if d["key"] in onto["domains"]]
    generic = GENERIC_TITLE_WORDS.get(families[0] if families else "engineering", ["specialist"])
    title_bonus[14] = generic
    title_bonus = {k: list(dict.fromkeys(v)) for k, v in sorted(title_bonus.items(), reverse=True)}

    pools = []
    for entry in profile["academic"]["strong"][:4]:
        dom = onto["domains"].get(entry["domain"])
        if dom:
            pools.append(_strip_star(_domain_terms(dom, 24)))
    strength_terms: list[str] = []
    for i in range(max((len(p) for p in pools), default=0)):
        for pool in pools:
            if i < len(pool):
                strength_terms.append(pool[i])
    academic: dict = {}
    if strength_terms:
        academic["strength"] = {14: list(dict.fromkeys(strength_terms))[:32]}
    weak = weakness_terms(profile, onto)
    if weak:
        penalties = [-20, -15, -13, -13]
        academic["weakness"] = {}
        for i, (_key, terms) in enumerate(weak.items()):
            academic["weakness"][penalties[min(i, 3)]] = _strip_star(terms)

    plain_q, located_q = _queries(profile, onto, city)

    cfg = {
        "profile": {
            "full_name": ident["full_name"],
            "email": ident["email"],
            "phone": ident["phone"],
            "address": ident["address"],
            "city": city,
            "headline": status["headline"],
            "cv_path": profile["documents"]["cv"],
            "extra_documents": profile["documents"]["extra"],
            "languages": profile.get("languages") or {},
        },
        "filters": {
            "full_time_only": True,
            "location_label": metro.get("label") or city or "your area",
            "locations": places,
            "ambiguous_locations": ambiguous,
            "location_excludes": excludes,
            "remote_anchors": list(country.get("names", [])),
            "exclude_titles": _exclusions(profile, onto, mkt),
            "min_score": 20,
        },
        "skills": skills,
        "title_bonus": title_bonus,
        "seniority": mkt["seniority"].get(status["career_stage"], mkt["seniority"]["entry"]),
        "language": _language_block(profile, locs, mkt),
        "agencies": mkt["agencies"],
        "academic": academic,
        "adzuna": {"app_id": "", "app_key": "", "country": country.get("adzuna"),
                   "where": city.lower(), "distance_km": 25, "queries": plain_q},
        "jsearch": {"api_key": "", "queries": located_q},
        "jooble": {"api_key": ""},
        "fetch": mkt["fetch"],
    }
    return cfg


# ---------------------------------------------------------------- letters

def _tidy_course(name: str) -> str:
    """Transcripts often shout; a cover letter should not."""
    n = re.sub(r"\s{2,}", " ", (name or "").strip(" .,-"))
    letters = [c for c in n if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.8:
        n = n.title()
    return n


IRREGULAR_VERBS = {"built", "led", "ran", "wrote", "took", "made", "set", "won",
                   "grew", "drove", "held", "taught", "sold", "kept", "met",
                   "spent", "chose", "brought", "began", "drew", "rebuilt", "shipped"}

# A grade in brackets belongs in the "academically backed by" sentence, which
# only ever cites subjects the person did well in — never inside prose quoted
# from the CV, where a mediocre mark would be argued as a strength.
GRADE_IN_TEXT = re.compile(r"\(\s*[0-5][.,][0-9]\s*\)|\b[A-F][A-F]\b\s*\)")


def _is_action(bullet: str) -> bool:
    """Does this bullet start with a verb, so it can follow 'includes:'?"""
    first = re.split(r"[\s,:]", bullet.strip(), 1)[0].strip(".,;:")
    if not first or not first[:1].isupper():
        return False
    low = first.lower()
    return low.endswith(("ed", "ing")) or low in IRREGULAR_VERBS


def _sentence_list(bullets: list[str], limit: int = 3) -> tuple[str, list[str]]:
    """Split bullets into a verb-led clause list and standalone statements.

    Bullets that start with a verb ("Designed a controller...") can be folded
    into one sentence after "includes:"; bullets that start with a label
    ("Master's Thesis: ...") cannot, because lowercasing them mangles a proper
    noun. Keeping the two apart is what stops the letter reading like a
    mail-merge accident.
    """
    clauses, standalone = [], []
    for b in bullets[:limit]:
        text = re.sub(r"\s+", " ", b.strip()).rstrip(".;")
        if not text:
            continue
        if _is_action(text):
            clauses.append(text[0].lower() + text[1:])
        else:
            standalone.append(text.rstrip(".") + ".")
    if not clauses:
        joined = ""
    elif len(clauses) == 1:
        joined = clauses[0]
    else:
        joined = "; ".join(clauses[:-1]) + "; and " + clauses[-1]
    return joined, standalone


def gen_letters(profile: dict, onto: dict, mkt: dict, cv_language: str,
                locs: dict) -> dict:
    code, lang_name, level = _local_language(profile, locs)
    langs = ["en"] + ([code] if code != "en" and code in mkt["letter_templates"] else [])

    evidence: dict = {}
    focus_names: dict = {}
    claimed: set[str] = set()
    usable = [b for b in profile.get("evidence_bullets", [])
              if not GRADE_IN_TEXT.search(b)]
    for d in profile["domains"]:
        key = d["key"]
        dom = onto["domains"].get(key)
        if not dom:
            continue
        terms = _domain_terms(dom)
        mine = [b for b in usable if _hits(b, terms) and b not in claimed]
        claimed.update(mine[:3])
        courses = [c for e in profile["academic"]["strong"] + profile["academic"]["neutral"]
                   if e["domain"] == key for c in e["courses"][:3]]

        body, extra = _sentence_list(mine)
        tail = (" " + " ".join(extra)) if extra else ""
        clean = [c for c in courses if not re.search(r"[A-Za-z]\.[A-Za-z]", c["name"])]
        graded = ", ".join(f"{_tidy_course(c['name'])[:46]} ({c['grade']})"
                           for c in (clean or courses)[:3])

        per_lang = {}
        for lang in langs:
            if lang == "en":
                lead = f"My hands-on work in {dom['focus']['en']} includes"
                acad = f" Academically this is backed by {graded}." if graded else ""
                if body:
                    text = f"{lead}: {body}.{tail}{acad}"
                elif extra:
                    text = f"{tail.strip()}{acad}"
                elif graded:
                    text = (f"My background in {dom['focus']['en']} is academic so far:"
                            f" {graded}.")
                else:
                    text = ""
            else:
                lead_de = f"Meine praktische Erfahrung in {dom['focus'].get(lang, dom['focus']['en'])} umfasst"
                acad_de = f" Fachlich untermauert durch {graded}." if graded else ""
                if body:
                    text = f"{lead_de}: {body}.{tail}{acad_de}"
                elif extra:
                    text = f"{tail.strip()}{acad_de}"
                elif graded:
                    text = (f"Mein Hintergrund in "
                            f"{dom['focus'].get(lang, dom['focus']['en'])}"
                            f" ist bislang akademisch: {graded}.")
                else:
                    text = ""
            per_lang[lang] = text
        if any(per_lang.values()):
            evidence[key] = per_lang
        focus_names[key] = {lang: dom["focus"].get(lang, dom["focus"]["en"]) for lang in langs}

    notes = {}
    mine_level = LEVEL_ORDER.get(level, 2)
    for lang in langs:
        tpl = mkt["language_notes"].get(lang, mkt["language_notes"]["en"])
        if code == "en":
            notes[lang] = tpl["english_only"]
        elif mine_level >= LEVEL_ORDER["C1"]:
            notes[lang] = tpl["strong_local"].format(local_language=lang_name, level=level)
        else:
            notes[lang] = tpl["weak_local"].format(local_language=lang_name, level=level)

    return {
        "languages": langs,
        # True when the letter body would carry text in a different language
        # from the letter itself — the checklist then asks you to translate it.
        "needs_translation": {lang: (lang != "en" and cv_language != lang) for lang in langs},
        "templates": {lang: mkt["letter_templates"][lang] for lang in langs},
        "language_notes": notes,
        "evidence": evidence,
        "focus_names": focus_names,
    }


# ---------------------------------------------------------------- taxonomy

def gen_taxonomy(profile: dict, onto: dict) -> dict:
    """Every skill in the ontology, levelled by this person's evidence.

    Vocabulary comes from the ontology and only the judgement comes from the
    profile, so correcting a bad search term in the ontology reaches every
    existing profile on the next `--regenerate`. A skill the profile has never
    seen — a newly added one — defaults to a gap.

    Skills no posting mentions are dropped by the analysis itself, so breadth
    here costs nothing and lets the report see demand outside the profile.
    """
    known = profile.get("skills") or {}
    groups: dict = {}
    domains = list(onto["domains"].values())
    if onto.get("universal"):
        domains.append(onto["universal"])
    for dom in domains:
        group = dom.get("label", "Other")
        for skill, terms in dom["skills"].items():
            spec = known.get(skill) or {}
            entry = {"level": spec.get("level", "gap"),
                     "terms": _strip_star(terms)}
            note = spec.get("why") or ("no evidence in your documents"
                                       if not spec else "")
            if note:
                entry["note"] = note
            groups.setdefault(group, {})[skill] = entry
    return {"groups": groups}


# ---------------------------------------------------------------- companies

def gen_companies(profile: dict, locs: dict, preset: dict | None) -> dict:
    country = profile["identity"].get("country") or "de"
    spec = locs["countries"].get(country, {})
    reg: dict = {}
    if preset:
        for ats, entries in preset.items():
            if entries:
                reg.setdefault(ats, []).extend(entries)
    if spec.get("adzuna"):
        reg.setdefault("adzuna", []).append({"slug": spec["adzuna"],
                                             "name": f"Adzuna {spec['adzuna'].upper()}"})
    if country in ("de", "at", "ch"):
        reg.setdefault("arbeitnow", []).append({"slug": "de", "name": "Arbeitnow DE"})
    reg.setdefault("jsearch", [])
    reg.setdefault("jooble", [])
    return reg


# ---------------------------------------------------------------- narrative

def gen_narrative(profile: dict, onto: dict, locs: dict, mkt: dict) -> dict:
    """Report wording, generated so the analysis talks about this person."""
    doms = profile["domains"]
    top = [onto["domains"][d["key"]]["label"] for d in doms[:3] if d["key"] in onto["domains"]]
    top_focus = [onto["domains"][d["key"]]["focus"]["en"] for d in doms[:3]
                 if d["key"] in onto["domains"]]
    weakest = [e["label"] for e in profile["academic"]["weak"][:3]]
    strongest = [e["label"] for e in profile["academic"]["strong"][:3]]
    metro = locs["metros"].get(profile["identity"].get("metro"), {})
    place = metro.get("label") or profile["identity"].get("city") or "your area"
    code, lang_name, level = _local_language(profile, locs)
    in_profile = {onto["domains"][d["key"]]["label"] for d in doms
                  if d["key"] in onto["domains"]}

    tiers = [
        {"floor": 75, "label": "Apply first",
         "text": f"Direct hits on {', '.join(top_focus[:2]) or 'your core field'} — "
                 f"what your experience and best-graded work were training for."},
        {"floor": 55, "label": "Strong fit",
         "text": "Clear overlap with your core stack. Expect to rewrite a paragraph of "
                 "the letter, but you meet the substance of what they ask for."},
        {"floor": 38, "label": "Worth a look",
         "text": "Adjacent roles: the work sits in your world, but the emphasis falls "
                 "somewhere you have less demonstrable evidence. Read the posting "
                 "before investing time."},
        {"floor": 0, "label": "Long shots",
         "text": "Thinner overlap, or weighed down by a language requirement or a "
                 + (f"subject your transcript is lighter on ({weakest[0]})."
                    if weakest else "subject you have less evidence for.")},
    ]

    return {
        "person": profile["identity"]["full_name"],
        "headline": profile["status"]["headline"],
        "place": place,
        "local_language": lang_name,
        "local_language_level": level,
        "top_domains": top,
        "top_focus": top_focus,
        "academic_strengths": strongest,
        "academic_weaknesses": weakest,
        "in_profile_domains": sorted(in_profile),
        "tiers": tiers,
        # Templates for the "what to do about this gap" column. Formatted with
        # the live counts, so the advice cites real numbers rather than guesses.
        "action_templates": {
            "gap_broad": "Asked for by {companies} of the {total_companies} employers here. "
                         "The broadest gap on this list — closing it changes which roles "
                         "you can credibly apply to, not just how one letter reads.",
            "gap_concentrated": "Almost all of these mentions come from {top_company}. "
                                "That is one employer's house style, not market demand — "
                                "learn it only if you are set on them.",
            "gap_narrow": "Asked for by {jobs} role(s), from {companies} employer(s). "
                          "Worth a conceptual grounding rather than real investment.",
            "gap_core": "This sits inside {group}, which is your own field — a gap here "
                        "is more visible to an interviewer than the same gap elsewhere. "
                        "Treat it as a priority.",
            "partial_broad": "You have adjacent evidence ({note}). Turning that into one "
                             "demonstrable artefact — a repository, a certificate, a "
                             "finished side project — converts a 'partial' into a 'have' "
                             "for {jobs} roles at once.",
            "partial_narrow": "Adjacent evidence already ({note}); low effort to finish, "
                              "but only {jobs} role(s) here ask for it.",
            "have": "Already evidenced. Make sure the CV says so in the posting's own "
                    "vocabulary — {jobs} of these roles use this exact term.",
        },
        "language_finding": {
            "code": code,
            "strict_terms": (mkt["language_requirements"].get(code) or {}).get("strict", []),
        },
    }


def generate(profile: dict, cv_language: str = "en", preset: dict | None = None) -> dict:
    onto, locs, mkt = ontology(), locations(), market()
    return {
        "config.yaml": gen_config(profile, onto, locs, mkt),
        "letters.yaml": gen_letters(profile, onto, mkt, cv_language, locs),
        "skills_taxonomy.yaml": gen_taxonomy(profile, onto),
        "companies.yaml": gen_companies(profile, locs, preset),
        "narrative.yaml": gen_narrative(profile, onto, locs, mkt),
    }
