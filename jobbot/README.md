# jobbot — Munich engineering job search automation

Finds full-time engineering roles in the Munich area, scores them against your
CV, drafts a tailored cover letter for each, and tracks every application —
so the only manual step left is a quick review and the submit click.

## Why it works this way

This tool pulls from **official public ATS APIs** — the same endpoints that
power each company's own careers page — and stops just short of the submit
button. You keep a 30-second review per job; everything else is automated.

### On LinkedIn and Indeed

Their postings are reachable; their sites are not.

**Do not scrape either.** LinkedIn's User Agreement prohibits automated access
and enforcement costs you the account you need for the job search itself.
Indeed closed its Publisher API to new applicants in 2023 and its RSS endpoint
returns HTTP 403 to programmatic clients.

**Use a licensed aggregator instead.** `jsearch` queries JSearch on RapidAPI,
which licenses and indexes Indeed, LinkedIn, Glassdoor and ZipRecruiter
postings. You query JSearch, never those sites, so there is no terms breach and
no account to ban. Add a key to `config.yaml` and an entry under `jsearch:` in
`companies.yaml` to switch it on — the free tier is ~200 requests/month, so the
query list is deliberately short.

`adzuna`, `arbeitnow` and `jooble` cover the same ground from other angles.
Arbeitnow needs no key at all and is on by default.

Alongside all of this, set up saved-search email alerts on LinkedIn and Indeed
directly. That is a supported feature and it reaches employers no API does.

## Setup

```bash
pip install -r requirements.txt
```

That's it — no API keys, no accounts, no browser automation.

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
Transcript.pdf        supporting documents
GoetheInstitut_B1.pdf
APPLY.md              apply link, fit breakdown, submit checklist
```

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
