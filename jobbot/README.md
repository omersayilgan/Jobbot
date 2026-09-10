# jobbot — job search automation, driven by your own CV

Reads your CV and transcripts, works out what you are actually good at, finds
matching full-time roles near you, scores each one against your evidence,
drafts a tailored cover letter, and tracks every application — so the only
manual step left is a quick review and the submit click.

Nothing about the tool is specific to one person or one field. Point it at a
different folder of documents and it reconfigures itself: a marketing manager
in Berlin and a flight-software engineer in Munich get different scoring rules,
different exclusions, different search queries and different letters, from the
same code.

## The two modes

**Setup mode** (`setup.py`) reads your documents and writes your profile.
**Run mode** (`run.py`) is the daily loop and behaves exactly as it always has.

```bash
pip install -r requirements.txt
sudo apt install poppler-utils        # for pdftotext; skip if you have it

mkdir -p documents                    # put your CV + transcripts here
python3 setup.py                      # read them, generate your profile
python3 run.py fetch                  # pull and score postings
python3 run.py review                 # work the queue in your browser
```

No API keys, no accounts, no model in the loop. The setup step is pure offline
text matching against a bundled ontology of professions, places and grade
scales — your documents never leave the machine.

## What setup.py actually does

1. **Reads every document** in `documents/` (and the parent folder), and
   classifies each as a CV, a transcript, a certificate or a reference.
   PDF, DOCX and plain text all work.
2. **Parses the CV** for name, contacts, city, languages, career stage,
   employment dates, job titles and the bullet points under each role.
3. **Parses the transcripts** — detecting the grade scale first, because 1.0 is
   the best grade in Germany and close to the worst in the US. It handles the
   German 1.0–5.0 scale, Turkish AA–FF, US letters, ECTS, percentages and
   Indian CGPA.
4. **Matches all of it against the ontology** in `jobbot/ontology/` to decide
   which of 33 professional domains you have real evidence for — weighting a
   job title you have held above a tool you once listed, and professional
   evidence above coursework.
5. **Reads the transcripts relatively.** A subject counts as a strength or a
   weakness by its distance from *your own* average, not an absolute cutoff, so
   the layer survives different grading cultures and grade inflation.
6. **Writes a profile** under `profiles/<you>/`:

| File | What it holds |
|---|---|
| `profile.yaml` | Every fact inferred from your documents. The source of truth. |
| `config.yaml` | Scoring rules: domain weights, title bonuses, seniority, language, exclusions. |
| `letters.yaml` | Cover-letter evidence, quoted from your own CV bullets. |
| `skills_taxonomy.yaml` | have / partial / gap per skill, for the gap analysis. |
| `companies.yaml` | Where to fetch postings from. |
| `narrative.yaml` | The wording the generated reports use to talk about you. |

Everything the tool inferred is visible in `profile.yaml`. When it guesses
wrong, fix that one file and run `python3 setup.py --regenerate` — no PDF is
re-parsed and nothing else is touched.

## setup.py commands

| Command | What it does |
|---|---|
| `setup.py` | Read `documents/`, build a profile, make it active. |
| `setup.py --documents DIR` | Read documents from somewhere else. |
| `setup.py --regenerate` | Rebuild the configs from an edited `profile.yaml`. |
| `setup.py --preset munich-deeptech` | Add a curated employer registry from `presets/`. |
| `setup.py --list` | List profiles; `*` marks the active one. |
| `setup.py --use <name>` | Switch the active profile. |
| `setup.py --force` | Overwrite an existing profile. |
| `setup.py --name "..."` / `--slug ...` | Override the name read from the CV. |

Several people can share one checkout: each gets a profile directory and its
own `output/<profile>/` with its own job database and application history.
`run.py profile` shows who the tool is currently working for.

## Where the postings come from

**Aggregators work for anyone, anywhere, with no curation.** setup.py writes
the search queries from your own role families and city, so `run.py fetch`
returns useful results immediately. Arbeitnow needs no key and is on by default
for German-speaking countries; Adzuna, JSearch and Jooble each take a free key.

**Company ATS boards give much better data** — full descriptions rather than
snippets, which is what the scorer and the gap analysis feed on. Grow your own
registry with `run.py discover --url <careers page>`, or start from a preset in
`presets/` if one fits your market.

## Adding to the ontology

The tool is only as good as `jobbot/ontology/`, and those files are plain YAML
meant to be edited:

- `professions.yaml` — 33 domains, each with the terms that identify it in a
  posting, the job titles that mean the role *is* that domain, and the words
  that identify it in a transcript course name. Copy the shape of an existing
  entry to add a field; nothing in the code hardcodes a domain name.
- `locations.yaml` — 26 metro areas with their suburbs and the nearby cities
  that are *not* commutable. Unlisted city? It falls back to the city name plus
  its country, which works, just less forgivingly.
- `grades.yaml` — grade scales and how to recognise them.
- `market.yaml` — title exclusions, seniority bands, language requirements,
  agency names and the letter skeletons.

A term that is an ordinary English word in another context will poison the
analysis — `fluent` matched every advert asking for fluent German before it was
qualified to `ansys fluent`. If a skill shows up with an implausible job count,
that is almost always the cause.

## Daily workflow

```bash
python3 run.py fetch      # pull + score every posting (~1 min)
python3 run.py review     # open the review queue in your browser
```

In the review queue each card shows the fit score, which of your skill clusters
the posting matched, and why. Four buttons: **Open posting**, **Build
application pack**, **Mark applied**, **Skip**.

"Build application pack" creates `output/applications/<company>__<role>/`:

```
cover_letter_en.txt   tailored letter, in the posting's own language
cv.pdf                your CV
Transcript.pdf        supporting documents named in your profile
APPLY.md              apply link, fit breakdown, submit checklist
```

The letter is assembled, not generated: the scorer already knows which of your
domains the posting asked for, so the letter leads with the bullets from your
own CV that prove exactly those, in the posting's own language.

Read the letter, tweak the company paragraph, export to PDF, submit.

## All commands

| Command | What it does |
|---|---|
| `run.py fetch` | Pull and score all postings. `--company <slug>` for just one. |
| `run.py review` | Review dashboard at localhost:8765. `--port`, `--no-open`. |
| `run.py list` | Ranked table in the terminal. `--status`, `--min-score`, `--limit`. |
| `run.py pack <uid>` | Build pack(s). `--top 10` for the ten best, `--lang de/en` to force language. |
| `run.py status <uid> applied` | Update status: `shortlisted`, `applied`, `rejected`, `interview`, `offer`, `skipped`. |
| `run.py stats` | Pipeline summary. |
| `run.py profile` | Show the active profile. `--use <name>` to switch. |
| `run.py discover <slug>` | Find which ATS a company uses, to add it to the registry. |
| `run.py skills` | PDF analysis of the skills these jobs demand and where your gaps are. `--min-fit` sets the score cutoff (default 38). |
| `run.py reconcile` | Rebuild application history from the pack folders on disk. |
| `run.py dedupe` | Merge duplicate postings already stored. |

Re-running `fetch` never overwrites a status you set — decisions you have
already made about a posting are preserved.

## Skills gap analysis

```bash
python3 run.py skills
```

Writes `output/skills_gap_analysis.pdf`: what the best-fitting roles actually
ask for, ranked by how much closing each gap would change your prospects.

Two counting decisions make the output trustworthy. It counts **document
frequency, not word frequency** — a posting naming Python nine times is one job
wanting Python; raw counts would rank recruiting boilerplate top. And it tracks
**how concentrated each demand is**: Helsing writes ~40% of the best-fit
postings, so its house requirements (Rust, reinforcement learning, distributed
systems) would otherwise read as market-wide. Anything where one employer
supplies 60%+ of mentions is separated into its own section.

Your proficiency levels live in `skills_taxonomy.yaml` (`have` / `partial` /
`gap`). Edit them as you learn things and re-run.

## How scoring works

Each posting gets 0–100 from four signals, all configured in `config.yaml`:

1. **Title family** (up to 40 pts) — a Control/GNC or embedded title outranks a
   generic one. The role's actual identity matters more than a keyword buried
   in a requirements list.
2. **Skill clusters** (up to ~126 pts) — `control`, `simulation`, `embedded`,
   `automation`, `robotics`, `aerospace`, `software`, each drawn from your CV
   and weighted. A cluster needs three distinct term hits for full credit, so a
   single passing mention of "Python" does not inflate a bad match.
3. **Seniority** — entry-level and graduate wording scores up; "Principal",
   "Head of" and "10+ years" score down.
4. **German level** — postings demanding C1/verhandlungssicher German are
   down-weighted rather than hidden, since you are B1. They still appear, just
   below the realistic ones.

Raw points are normalised against 115 so the top of the ranking stays
discriminative instead of piling up at 100.

Hard filters run before scoring: Munich commute area (including Ottobrunn,
Parsdorf, Garching, Taufkirchen and the rest of the metro — Isar Aerospace does
not post as "Munich"), full-time only, and an excluded-title list that drops
internships, working-student roles, sales and HR postings.

**Tune it by editing `config.yaml`.** Lower `min_score` to widen the net, add
terms to any skill cluster, or adjust the German penalty as your level improves.

## Turning on Adzuna (optional, free, 2 minutes)

Adzuna is an aggregator with a documented free API tier and broad German
coverage — the legitimate way to widen beyond company career pages.

1. Register at <https://developer.adzuna.com/> for an app ID and key.
2. Paste them into the `adzuna:` block in `config.yaml`.
3. Add `- {slug: de, name: "Adzuna DE"}` under `adzuna:` in `companies.yaml`.

The adapter runs your configured query list against Munich with a 25 km radius
and full-time filter, then scores the results like any other source.

## Adding companies

The registry in `companies.yaml` ships with 56 verified entries across nine ATS
platforms. Two ways to grow it:

```bash
python3 run.py discover --url https://www.airbus.com/en/careers   # reliable
python3 run.py discover isaraerospace                             # guess a slug
```

The `--url` form reads the careers page and reports the job board it actually
links to, printing the exact YAML to paste in — including Workday's
`slug` / `site` / `host` triple. Use it whenever slug-guessing fails, which is
most of the time for large employers.

This is the highest-leverage way to improve results: **more companies in the
registry means more matches.** When you spot a Munich company you like, run
`discover` on it.

## Weekly automation (optional)

```bash
crontab -e
# Monday 08:00: refresh the queue
0 8 * * 1 cd ~/Desktop/"Automatic Job Application"/jobbot && python3 run.py fetch
```

## Supported platforms

Company boards: Greenhouse, Ashby, Personio, Lever, Recruitee, SmartRecruiters,
Workable and **Workday**.

Aggregators: **Adzuna**, **Arbeitnow** (free, no key, enabled by default),
**JSearch** (Indeed/LinkedIn/Glassdoor inventory, needs a key) and **Jooble**.

Only company boards are treated as authoritative about what is still open. An
aggregator returns whatever its query matched today, so a posting missing from
one run does not mean the job closed — close-detection ignores those sources
deliberately.

Workday matters most: it is where the large aerospace and industrial employers
post. Because its list endpoint omits descriptions, the adapter searches by
Munich-area place name, filters on location, then fetches details only for the
survivors — which keeps a company like Airbus to a few dozen requests instead
of a few thousand.

## Duplicate detection

Aggregators repost the same vacancy under different titles, rewritten gender
tags, appended city names, or a recruitment agency's name instead of the
employer's. `jobbot/dedupe.py` runs three passes: identical apply URL; same
employer with a near-identical title; and same title across different employer
names where the descriptions match closely (the agency-fronting case).

Similarity is Jaccard on token *sets*, not containment. Containment treats
"Software Engineer" and "Software Engineer - Backend" as the same job because
the first title's tokens are a subset of the second's — an early version made
exactly that mistake and reported 60 duplicates where there were 2.

Run it standalone with `python3 run.py dedupe`.

## Known limits

- **Bundesagentur für Arbeit** would add strong coverage of established German
  employers, but its public API now returns 403 from every endpoint and auth
  form tried — the old public key was retired. If it reopens it drops straight
  in as another adapter.
- **SAP SuccessFactors** tenants (common among German industrials) expose no
  consistent public JSON endpoint and are not covered.
- Some career sites render their listings entirely in JavaScript, so
  `discover --url` finds nothing on the landing page. Click into an individual
  job and fingerprint that URL instead.
- Cover letters are assembled from your CV evidence bank in `letters.yaml`, not
  generated. That makes them accurate and repeatable, but the company-specific
  paragraph is deliberately generic — **always edit it before sending.**
