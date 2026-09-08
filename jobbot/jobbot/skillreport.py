"""Renders the skill-gap analysis as a printable PDF (via WeasyPrint)."""
from __future__ import annotations

import datetime as _dt
import html
import os

from . import skillgap
from .config import output_dir

# What to actually do about each gap. Kept here rather than in the taxonomy so
# the taxonomy stays purely about detection.
ACTIONS = {
    "Functional safety":
        "Read ISO 26262 part 6 and DO-178C DAL definitions, then re-frame your "
        "Roketsan HIL work in safety terms (requirements → test → evidence). "
        "A short course certificate is cheap and shows intent.",
    "CI/CD":
        "Highest effort-to-reward item on this list. Put your thesis Simulink "
        "and Python code in GitLab with a pipeline that runs tests and builds "
        "on every push. One weekend; visible on your CV forever.",
    "Distributed systems":
        "Mostly Helsing's house requirement. Worth a conceptual grounding "
        "(gRPC, message brokers, DDS) only if you target them specifically.",
    "Reinforcement learning":
        "Entirely Helsing. Ignore unless you are set on their AI roles.",
    "Rust":
        "Concentrated at Helsing. Do not learn it before the broader gaps.",
    "Perception / CV":
        "Pairs naturally with your ROS grade. Working through OpenCV plus a "
        "small point-cloud project would open the Munich robotics cluster "
        "(NavVis, RobCo, Magazino, Agile Robots).",
    "Machine learning":
        "Broad but shallow demand in your target roles. A practical PyTorch "
        "grounding is enough; you are not competing for research posts.",
    "Aerospace standards":
        "ECSS and DO-178C vocabulary matters at Isar, RFA and The Exploration "
        "Company. Reading the standard summaries costs a day and lets you "
        "speak the language in interviews.",
    "ROS 2":
        "You have ROS 1 at grade 1.0; industry has moved on. Porting one of "
        "your lab projects to ROS 2 converts an existing strength into a "
        "current one — very high value for the effort.",
    "FPGA / HDL":
        "You deployed generated code to Xilinx but never wrote HDL. Only worth "
        "it if you target avionics hardware roles specifically.",
    "AUTOSAR":
        "Automotive-specific. Skip unless you pivot toward Munich's car industry.",
    "Kubernetes/cloud":
        "Peripheral to control and embedded work. Lowest priority here.",
    "Bus protocols":
        "You have RS-485 and serial; CAN is the common missing piece in both "
        "space and automotive. A cheap CAN transceiver and a weekend closes it.",
    "RTOS":
        "Real-Time Systems 2.0 gives you the theory. Flashing FreeRTOS or "
        "Zephyr onto an STM32 turns coursework into something demonstrable.",
    "Test automation":
        "Extend your V-Model thesis work with pytest and a CI runner — this "
        "and CI/CD are the same weekend's work.",
    "Requirements / MBSE":
        "Named at the primes (Airbus, Leonardo). Learn the DOORS/SysML "
        "vocabulary; tool access is usually given on the job.",
    "German (fluent)":
        "Counter-intuitively NOT urgent for the roles on your shortlist — see "
        "the eligibility section. Worth pursuing to widen the market beyond "
        "what this tool can see, but do not delay a single application for it.",
    "Security clearance":
        "Not a skill and not something you can prepare for. See the eligibility "
        "note — check directly with the employer rather than self-selecting out.",
    "EU/German citizenship":
        "A structural gate at defence primes, not a preparation item. Focus "
        "energy on civil space, robotics and industrial automation, where it "
        "rarely applies.",
}

LEVEL_LABEL = {"have": "Have", "partial": "Partial", "gap": "Gap"}


def _german_finding() -> str:
    """The German-language result is counter-intuitive enough to need its own text."""
    from . import db
    conn = db.connect()
    rows = conn.execute(
        "SELECT company, description FROM jobs WHERE score >= 38").fetchall()
    import re as _re
    strict = _re.compile(
        r"fließend deutsch|verhandlungssicher|deutsch c1|german c1|c1 german|"
        r"fluent german|fluent in german|business level german|"
        r"sehr gute deutschkenntnisse|proficient in german")
    hits = [r for r in rows if strict.search((r["description"] or "").lower())]
    return (f"<b>{len(hits)} of {len(rows)}</b> of these roles ask for fluent or "
            f"C1 German.")


def _esc(t) -> str:
    return html.escape(str(t))


def _bar(pct: float, cls: str) -> str:
    return (f'<span class="bar"><i class="{cls}" '
            f'style="width:{max(3, min(100, pct)):.0f}%"></i></span>')


def build(min_fit: int = 38, path: str | None = None) -> tuple[str, str]:
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
        action = ACTIONS.get(r["name"], "")
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
    doc = doc.replace("__GERMAN__", _german_finding())

    out_html = os.path.join(output_dir(), "skills_gap_analysis.html")
    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(doc)

    out_pdf = path or os.path.join(output_dir(), "skills_gap_analysis.pdf")
    from weasyprint import HTML
    HTML(string=doc, base_url=output_dir()).write_pdf(out_pdf)
    return out_pdf, out_html


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Skills Gap Analysis</title>
<style>
@page {
  size: A4; margin: 17mm 16mm 16mm 16mm;
  @bottom-center {
    content: "Skills gap analysis — Ömer Sayilgan — page " counter(page) " of " counter(pages);
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

<p class="eyebrow">Prepared from __JOBS__ live Munich job descriptions &middot; __DATE__</p>
<h1>What these jobs ask for, and what you are missing</h1>
<p class="lede">Every skill below was counted across the __JOBS__ best-fitting
engineering roles currently open in the Munich area, drawn from __COMPANIES__
employers. Ranked by how much closing the gap would change your prospects.</p>
<p class="meta">Scope: roles scoring __MINFIT__ or above against your CV and
transcripts — tiers 1&ndash;3 of the ranked shortlist. Weaker matches are excluded
so the priorities reflect jobs you could realistically win.</p>

<div class="summary">
  <b>The short version</b>
  <ul>__TOP3__</ul>
  <p style="margin:2mm 0 0; font-size:8.6pt;">Your control, simulation and PLC
  foundations are already competitive. What separates you from these postings is
  not more control theory &mdash; it is modern software practice and the safety
  vocabulary the aerospace employers write into every advert.</p>
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
  <h3>Your German is not what is holding these roles back</h3>
  <p>__GERMAN__ The Munich deep-tech and aerospace employers you rank well
  against operate in English, and several say so explicitly. B1 is not the
  barrier here that it is often assumed to be, and it should not stop you
  applying to anything on your shortlist.</p>
  <p><b>The honest caveat:</b> that result partly reflects what this tool can
  see. Employers with public job-board APIs skew toward English-speaking
  scale-ups; the Mittelstand and public-sector employers who do require German
  are largely invisible to it. So read this as &ldquo;German is not gating the
  roles on your list&rdquo;, not as &ldquo;German does not matter in Munich&rdquo;.
  Improving it still widens the market beyond what this document covers.</p>
</div>

<div class="callout">
  <h3>The clearance clause at Isar Aerospace</h3>
  <p>Isar Aerospace attaches the same sentence to every posting: &ldquo;Due to
  security clearance requirements, affiliations with countries listed under
  &sect;&nbsp;13 para. 1 no. 17 S&Uuml;G may affect the application process.&rdquo;
  S&Uuml;G is the German Security Clearance Act. The list of states it refers to
  is maintained by the Federal Ministry of the Interior and is <b>not public</b>,
  so nothing here tells you whether it applies to you.</p>
  <p>Two things follow. First, the same adverts state plainly that all qualified
  applicants are encouraged to apply, and they do not prioritise nationality.
  Second, this is a question for Isar's recruiters, not for guesswork &mdash; ask
  them directly rather than withdrawing on an assumption. You have already
  applied to several of their roles, which is the right move.</p>
  <p>Airbus differs: its Munich-area adverts require suitability for an
  <i>erweiterte Sicherheits&uuml;berpr&uuml;fung</i> and very good written and
  spoken German. Those are stated conditions rather than ambiguous ones.</p>
</div>

<p class="method" style="margin-top:3mm;"><b>Mentioned too rarely to prioritise:</b>
__RARE__ &mdash; named by fewer than five roles each, which is too thin an evidence
base to act on.</p>

<h2>6. How this was measured</h2>
<ul class="method">
  <li><b>Document frequency, not word frequency.</b> A posting naming Python
  nine times counts once. Raw word counts would have made recruiting boilerplate
  the top &ldquo;skill&rdquo; in this analysis.</li>
  <li><b>Employer reach is tracked separately.</b> Helsing alone writes roughly
  40% of the best-fit postings, so its house requirements &mdash; Rust,
  reinforcement learning, distributed systems &mdash; would otherwise read as
  market-wide demand. Section 2 exists to separate the two.</li>
  <li><b>Importance</b> = 45% share of roles + 35% share of employers + 20% average
  fit of the roles asking. A skill demanded by your strongest matches outranks a
  commoner one demanded by weak matches.</li>
  <li><b>Levels are judgements, not measurements.</b> They come from your CV, the
  TUM Leistungsnachweis and the METU transcript. Edit
  <code>skills_taxonomy.yaml</code> and re-run
  <code>python3 run.py skills</code> as they change.</li>
  <li><b>Limits.</b> Only employers with a public job-board API are covered, and a
  skill absent from an advert is not always absent from the job.</li>
</ul>
</body></html>
"""
