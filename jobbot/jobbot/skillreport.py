"""Renders the skill-gap analysis as a printable PDF (via WeasyPrint)."""
from __future__ import annotations

import datetime as _dt
import html
import os

from . import skillgap
from .config import output_dir

# What to do about a gap is generated from the live counts and the profile's
# own narrative templates, so the advice cites this market rather than a
# remembered one. The templates live in profiles/<you>/narrative.yaml.


def _action(r: dict, data: dict, nar: dict) -> str:
    tpl = nar.get("action_templates") or {}
    in_profile = set(nar.get("in_profile_domains") or [])
    core = r.get("group") in in_profile
    ctx = {
        "skill": r["name"], "group": r["group"], "jobs": r["jobs"],
        "companies": r["companies"], "total_jobs": data["total_jobs"],
        "total_companies": data["total_companies"],
        "top_company": r["top_company"], "note": (r.get("note") or "").rstrip("."),
    }

    if r["level"] == "have":
        key = "have"
    elif r["level"] == "partial":
        key = "partial_broad" if r["jobs"] >= 5 else "partial_narrow"
    elif r["concentrated"]:
        key = "gap_concentrated"
    elif r["jobs"] >= 5:
        key = "gap_broad"
    else:
        key = "gap_narrow"

    text = tpl.get(key, "")
    try:
        text = text.format(**ctx)
    except (KeyError, IndexError):
        return ""
    if core and r["level"] != "have" and tpl.get("gap_core"):
        try:
            text += " " + tpl["gap_core"].format(**ctx)
        except (KeyError, IndexError):
            pass
    return text


LEVEL_LABEL = {"have": "Have", "partial": "Partial", "gap": "Gap"}


def _language_finding(nar: dict, min_fit: int) -> str:
    """How many of these postings genuinely demand the local language."""
    import re as _re

    from . import db
    lang = nar.get("local_language") or "the local language"
    level = nar.get("local_language_level") or "your level"
    terms = (nar.get("language_finding") or {}).get("strict_terms") or []
    conn = db.connect()
    rows = conn.execute("SELECT description FROM jobs WHERE score >= ?",
                        (min_fit,)).fetchall()
    if not rows:
        return f"No postings stored yet, so nothing can be said about {lang} requirements."
    if not terms:
        return (f"{lang} is the local language here and no strict-requirement wordings "
                f"are configured, so this could not be measured.")
    pat = _re.compile("|".join(_re.escape(t) for t in terms), _re.I)
    hits = sum(1 for r in rows if pat.search(r["description"] or ""))
    share = hits / len(rows)
    verdict = (f"On this evidence {lang} is <b>not</b> what is gating your shortlist."
               if share < 0.25 else
               f"{lang} is a real constraint on this shortlist, not a marginal one."
               if share > 0.5 else
               f"{lang} gates a meaningful minority of these roles.")
    return (f"<b>{hits} of {len(rows)}</b> of these roles ask for fluent or C1-level "
            f"{lang}; you are at {level}. {verdict}")


def _eligibility_finding(min_fit: int) -> str:
    """Clearance, citizenship and export-control clauses, with who writes them.

    These are stated conditions rather than skills, and they are the one thing
    on a posting that preparation cannot change — so they are reported as
    counts and named employers instead of being turned into advice.
    """
    import re as _re

    from . import db
    checks = {
        "security clearance": [r"security clearance", r"sicherheits(?:überprüfung|ueberpruefung)",
                               r"\bsüg\b", r"verschlusssache", r"nato secret"],
        "citizenship or residency": [r"eu citizenship", r"eu national", r"citizenship required",
                                     r"staatsangehörigkeit", r"permanent residen"],
        "export control": [r"export control", r"\bitar\b", r"dual-use", r"exportkontrolle"],
    }
    conn = db.connect()
    rows = conn.execute("SELECT company, description FROM jobs WHERE score >= ?",
                        (min_fit,)).fetchall()
    out = []
    for label, pats in checks.items():
        pat = _re.compile("|".join(pats), _re.I)
        firms = sorted({r["company"] for r in rows if pat.search(r["description"] or "")})
        if firms:
            shown = ", ".join(firms[:4]) + (f" and {len(firms) - 4} more" if len(firms) > 4 else "")
            out.append(f"<li><b>{label.capitalize()}</b> — named by {len(firms)} employer(s): "
                       f"{shown}.</li>")
    if not out:
        return ("<li>No clearance, citizenship or export-control clauses appear in these "
                "postings.</li>")
    return "".join(out)


def _esc(t) -> str:
    return html.escape(str(t))


def _bar(pct: float, cls: str) -> str:
    return (f'<span class="bar"><i class="{cls}" '
            f'style="width:{max(3, min(100, pct)):.0f}%"></i></span>')


def build(min_fit: int = 38, path: str | None = None) -> tuple[str, str]:
    from .config import load_narrative
    nar = load_narrative()
    data = skillgap.analyse(min_fit)
    rows = data["results"]

    gaps = [r for r in rows if r["level"] == "gap"]
    partials = [r for r in rows if r["level"] == "partial"]
    haves = [r for r in rows if r["level"] == "have"]

    # A gap named by fewer than five roles is not yet a priority, whatever its
    # importance score — the evidence base is too thin to act on.
    MIN_EVIDENCE = 5
    broad_gaps = [r for r in gaps
                  if not r["concentrated"] and r["jobs"] >= MIN_EVIDENCE]
    narrow_gaps = [r for r in gaps if r["concentrated"]]
    rare_gaps = [r for r in gaps
                 if not r["concentrated"] and r["jobs"] < MIN_EVIDENCE]

    def row_html(r, rank=None):
        note = r.get("note") or ""
        action = _action(r, data, nar)
        extra = ""
        if note:
            extra += f'<p class="note">{_esc(note)}</p>'
        if action:
            extra += f'<p class="action"><b>Do this:</b> {_esc(action)}</p>'
        conc = ('<span class="flag">one employer</span>'
                if r["concentrated"] else "")
        return f"""<tr>
          <td class="rank">{rank if rank else ''}</td>
          <td class="skill"><b>{_esc(r['name'])}</b>{conc}
              <span class="grp">{_esc(r['group'])}</span>{extra}</td>
          <td class="num">{r['jobs']}<span class="sub">of {data['total_jobs']}</span></td>
          <td class="num">{r['companies']}<span class="sub">of {data['total_companies']}</span></td>
          <td class="num">{r['avg_fit']:.0f}</td>
          <td class="imp">{_bar(r['importance'] * 2, 'l-' + r['level'])}
              <span class="impn">{r['importance']:.0f}</span></td>
        </tr>"""

    def table(items, numbered=True):
        body = "".join(row_html(r, i + 1 if numbered else None)
                       for i, r in enumerate(items))
        return f"""<table>
          <thead><tr>
            <th></th><th>Skill</th><th class="num">Jobs</th>
            <th class="num">Employers</th><th class="num">Avg fit</th>
            <th>Importance</th>
          </tr></thead><tbody>{body}</tbody></table>"""

    today = _dt.date.today().strftime("%d %B %Y")
    doc = _TEMPLATE
    doc = doc.replace("__DATE__", today)
    doc = doc.replace("__JOBS__", str(data["total_jobs"]))
    doc = doc.replace("__COMPANIES__", str(data["total_companies"]))
    doc = doc.replace("__MINFIT__", str(min_fit))
    doc = doc.replace("__NGAPS__", str(len(broad_gaps)))
    doc = doc.replace("__BROAD__", table(broad_gaps))
    doc = doc.replace("__NARROW__", table(narrow_gaps))
    doc = doc.replace("__PARTIAL__", table(partials))
    doc = doc.replace("__RARE__", ", ".join(
        f"{_esc(r['name'])} ({r['jobs']})" for r in rare_gaps) or "none")
    doc = doc.replace("__HAVE__", table(haves, numbered=False))
    doc = doc.replace("__TOP3__", "".join(
        f"<li><b>{_esc(r['name'])}</b> — asked for by {r['jobs']} roles across "
        f"{r['companies']} employers</li>" for r in broad_gaps[:3]))
    place = nar.get("place") or "your area"
    person = nar.get("person") or ""
    strengths = nar.get("academic_strengths") or []
    top_focus = nar.get("top_focus") or []

    # The "short version" paragraph is the one piece of interpretation in the
    # document, so it is composed from what the numbers actually say.
    if broad_gaps:
        gap_names = ", ".join(g["name"] for g in broad_gaps[:3])
        summary = (f"Your strongest ground &mdash; {', '.join(top_focus[:2]) or 'your core field'}"
                   f" &mdash; is already competitive here. What separates you from these "
                   f"postings is {gap_names}.")
    else:
        summary = ("No gap in this ontology is named by enough of these roles to "
                   "prioritise. On this evidence your preparation is not what is "
                   "limiting you &mdash; volume of applications is.")
    if strengths:
        summary += (f" Your transcript backs this up: {strengths[0]} is among your "
                    f"best-graded subjects.")

    concentrated = [r for r in rows if r["concentrated"]]
    loudest = concentrated[0]["top_company"] if concentrated else ""
    method_reach = (
        f"<b>Employer reach is tracked separately.</b> {loudest} writes a large share "
        f"of the best-fit postings, so its house requirements would otherwise read as "
        f"market-wide demand. Section 2 exists to separate the two."
        if loudest else
        "<b>Employer reach is tracked separately.</b> A single prolific employer can "
        "make its house style look like market demand, so distinct employers are "
        "counted alongside raw job counts.")

    doc = doc.replace("__GERMAN__", _language_finding(nar, min_fit))
    doc = doc.replace("__ELIGIBILITY__", _eligibility_finding(min_fit))
    doc = doc.replace("__SUMMARY__", summary)
    doc = doc.replace("__METHODREACH__", method_reach)
    doc = doc.replace("__PLACE__", _esc(place))
    doc = doc.replace("__PERSON__", _esc(person))
    doc = doc.replace("__LOCALLANG__", _esc(nar.get("local_language") or "the local language"))

    out_html = os.path.join(output_dir(), "skills_gap_analysis.html")
    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(doc)

    out_pdf = path or os.path.join(output_dir(), "skills_gap_analysis.pdf")
    try:
        from weasyprint import HTML
    except ImportError:
        # The HTML is the real artefact; the PDF is a convenience. Losing the
        # optional dependency should not lose the analysis.
        return "", out_html
    HTML(string=doc, base_url=output_dir()).write_pdf(out_pdf)
    return out_pdf, out_html


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Skills Gap Analysis</title>
<style>
@page {
  size: A4; margin: 17mm 16mm 16mm 16mm;
  @bottom-center {
    content: "Skills gap analysis — __PERSON__ — page " counter(page) " of " counter(pages);
    font-family: "DejaVu Sans", sans-serif; font-size: 7.5pt; color: #8A93A0;
  }
}
* { box-sizing: border-box; }
body {
  font-family: "DejaVu Sans", "Liberation Sans", sans-serif;
  font-size: 9.1pt; line-height: 1.46; color: #16202B; margin: 0;
}
h1 { font-size: 20pt; letter-spacing: -.5pt; margin: 0 0 3mm; line-height: 1.12; }
h2 {
  font-size: 12pt; margin: 9mm 0 1mm; padding-bottom: 1.4mm;
  border-bottom: 1.6pt solid #16202B; letter-spacing: -.2pt;
  break-after: avoid;
}
h2.first { margin-top: 5mm; }
h3 { font-size: 9.6pt; margin: 5mm 0 1.5mm; color: #2B3947; break-after: avoid; }
p { margin: 0 0 2.2mm; }
.eyebrow {
  font-size: 7.6pt; letter-spacing: 1.3pt; text-transform: uppercase;
  color: #6B7684; margin: 0 0 2mm;
}
.lede { font-size: 10pt; color: #33414F; max-width: 145mm; }
.meta { font-size: 8pt; color: #6B7684; margin-top: 2mm; }
.summary {
  background: #F2F5F8; border-left: 2.6pt solid #14508C;
  padding: 4mm 5mm; margin: 5mm 0 0;
}
.summary ul { margin: 1.5mm 0 0; padding-left: 5mm; }
.summary li { margin-bottom: 1mm; }
table { width: 100%; border-collapse: collapse; margin-top: 2mm; }
thead th {
  font-size: 7.4pt; text-transform: uppercase; letter-spacing: .5pt;
  color: #6B7684; text-align: left; padding: 0 2mm 1.4mm;
  border-bottom: .8pt solid #C9D2DC; font-weight: normal;
}
tbody tr { break-inside: avoid; }
td { padding: 2.4mm 2mm; border-bottom: .5pt solid #E3E9EF; vertical-align: top; }
td.rank {
  width: 7mm; color: #9AA4B2; font-size: 8.4pt; text-align: right;
  padding-right: 1.5mm;
}
td.skill { width: 96mm; }
td.skill b { font-size: 9.6pt; }
.grp { display: block; font-size: 7.4pt; color: #8A93A0; margin-top: .4mm; }
.note { font-size: 8.2pt; color: #4A5867; margin: 1.2mm 0 0; font-style: italic; }
.action { font-size: 8.3pt; color: #16202B; margin: 1.4mm 0 0; }
.action b { color: #14508C; }
.num { text-align: right; white-space: nowrap; font-size: 9.4pt; }
.sub { display: block; font-size: 7pt; color: #9AA4B2; }
.imp { width: 26mm; white-space: nowrap; }
.bar {
  display: inline-block; width: 15mm; height: 2.6mm; background: #E3E9EF;
  border-radius: 1.3mm; overflow: hidden; vertical-align: middle;
}
.bar i { display: block; height: 100%; }
.l-gap { background: #B3452F; } .l-partial { background: #B07818; }
.l-have { background: #1B7A4B; }
.impn { font-size: 8.4pt; color: #4A5867; margin-left: 1.6mm; vertical-align: middle; }
.flag {
  font-size: 6.8pt; text-transform: uppercase; letter-spacing: .5pt;
  background: #F6E7DC; color: #96431F; padding: .5mm 1.4mm;
  border-radius: 1mm; margin-left: 2mm; vertical-align: 1mm;
}
.callout {
  border: .8pt solid #D8C6A8; background: #FBF7EF; padding: 4mm 5mm;
  margin: 3mm 0 0; break-inside: avoid;
}
.callout h3 { margin-top: 0; }
.method { font-size: 8.2pt; color: #4A5867; }
.method li { margin-bottom: 1.4mm; }
</style></head><body>

<p class="eyebrow">Prepared from __JOBS__ live __PLACE__ job descriptions &middot; __DATE__</p>
<h1>What these jobs ask for, and what you are missing</h1>
<p class="lede">Every skill below was counted across the __JOBS__ best-fitting
roles currently open in the __PLACE__ area, drawn from __COMPANIES__ employers.
Ranked by how much closing the gap would change your prospects.</p>
<p class="meta">Scope: roles scoring __MINFIT__ or above against your CV and
transcripts — tiers 1&ndash;3 of the ranked shortlist. Weaker matches are excluded
so the priorities reflect jobs you could realistically win.</p>

<div class="summary">
  <b>The short version</b>
  <ul>__TOP3__</ul>
  <p style="margin:2mm 0 0; font-size:8.6pt;">__SUMMARY__</p>
</div>

<h2 class="first">1. Gaps worth closing &mdash; wanted across many employers</h2>
<p>These are ranked by importance: how many roles ask, how many distinct
employers ask, and how well those roles otherwise fit you.</p>
__BROAD__

<h2>2. Gaps concentrated at a single employer</h2>
<p>These look significant by raw count but come from one company's postings.
Learn them only if you are targeting that employer specifically &mdash; otherwise
they are a poor use of your time.</p>
__NARROW__

<h2>3. Partial &mdash; you have the theory, not the evidence</h2>
<p>The cheapest wins on this document. In each case you already studied the
subject; what is missing is something demonstrable a recruiter can see.</p>
__PARTIAL__

<h2>4. Strengths to lead with</h2>
<p>Confirmed in your CV and transcripts, and asked for by these roles. Put these
first in your cover letters &mdash; they are why you rank where you do.</p>
__HAVE__

<h2>5. Eligibility and language &mdash; read before drawing conclusions</h2>
<div class="callout">
  <h3>How much __LOCALLANG__ these roles actually require</h3>
  <p>__GERMAN__</p>
  <p><b>The honest caveat:</b> that result partly reflects what this tool can
  see. Employers with public job-board APIs skew toward English-speaking
  companies; smaller and public-sector employers who do require the local
  language are largely invisible to it. So read this as &ldquo;__LOCALLANG__ is
  not gating the roles on your list&rdquo;, not as &ldquo;__LOCALLANG__ does not
  matter in __PLACE__&rdquo;. Improving it still widens the market beyond what
  this document covers.</p>
</div>

<div class="callout">
  <h3>Stated conditions you cannot prepare for</h3>
  <p>These are not skills. They are conditions written into the advert, and no
  amount of preparation changes them &mdash; so they are reported as counts and
  named employers rather than as advice.</p>
  <ul>__ELIGIBILITY__</ul>
  <p>Where one of these applies to you, ask the employer directly rather than
  withdrawing on an assumption. Recruiters answer this question routinely, and
  the wording in an advert is often broader than the rule behind it.</p>
</div>

<p class="method" style="margin-top:3mm;"><b>Mentioned too rarely to prioritise:</b>
__RARE__ &mdash; named by fewer than five roles each, which is too thin an evidence
base to act on.</p>

<h2>6. How this was measured</h2>
<ul class="method">
  <li><b>Document frequency, not word frequency.</b> A posting naming Python
  nine times counts once. Raw word counts would have made recruiting boilerplate
  the top &ldquo;skill&rdquo; in this analysis.</li>
  <li>__METHODREACH__</li>
  <li><b>Importance</b> = 45% share of roles + 35% share of employers + 20% average
  fit of the roles asking. A skill demanded by your strongest matches outranks a
  commoner one demanded by weak matches.</li>
  <li><b>Levels are judgements, not measurements.</b> They were inferred from
  your CV and transcripts by <code>setup.py</code>, which distinguishes work
  evidence from coursework. Correct any of them in your profile's
  <code>skills_taxonomy.yaml</code> and re-run
  <code>python3 run.py skills</code>.</li>
  <li><b>Limits.</b> Only employers with a public job-board API are covered, and a
  skill absent from an advert is not always absent from the job.</li>
</ul>
</body></html>
"""
