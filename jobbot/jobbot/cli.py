"""Command-line entry point."""
from __future__ import annotations

import argparse
import os
import re
import sys
import time

from . import db, dedupe as dedupe_mod, discover, letters, report, scoring, skillreport
from .config import load_companies, load_config
from .models import Job
from .sources import ADAPTERS






def cmd_fetch(args) -> int:
    cfg, registry = load_config(), load_companies()
    place = cfg["filters"].get("location_label", "range")
    conn = db.connect()
    # Application history cannot be re-fetched — snapshot it before anything else.
    db.backup_statuses(conn)
    delay = cfg["fetch"]["delay_between_companies"]

    all_jobs: list[Job] = []
    live_companies: set[str] = set()
    dropped = 0
    entries = [(ats, c) for ats, lst in registry.items() for c in (lst or [])]
    if args.company:
        entries = [e for e in entries if args.company.lower() in e[1]["slug"].lower()]

    for i, (ats, company) in enumerate(entries):
        mod = ADAPTERS.get(ats)
        if not mod:
            print(f"  ! unknown ATS '{ats}' in companies.yaml")
            continue
        name = company.get("name", company["slug"])
        # Anything beyond slug/name is adapter-specific (Workday needs site+host).
        extra = {k: v for k, v in company.items() if k not in ("slug", "name")}
        try:
            raw = mod.fetch(company["slug"], name, cfg, **extra)
        except Exception as exc:
            print(f"  ! {name:22s} fetch failed: {type(exc).__name__}: {exc}")
            continue

        kept = []
        for job in raw:
            ok, _why = scoring.passes_filters(job, cfg)
            if not ok:
                dropped += 1
                continue
            kept.append(scoring.score(job, cfg))

        live_companies.update(j.company for j in raw)
        above = [j for j in kept if j.score >= cfg["filters"]["min_score"]]
        print(f"  {name:22s} {len(raw):4d} posted → {len(kept):3d} in {place}/full-time "
              f"→ {len(above):3d} above score {cfg['filters']['min_score']}")
        all_jobs.extend(kept)

        if i < len(entries) - 1:
            time.sleep(delay)

    before = len(all_jobs)
    all_jobs = dedupe_mod.dedupe(all_jobs)
    merged_now = before - len(all_jobs)
    new, updated = db.upsert(conn, all_jobs)
    removed = db.purge_duplicates(conn) + merged_now
    restored = db.restore_statuses(conn)
    closed = 0
    if not args.company:          # a single-company run cannot judge the rest
        closed = db.mark_closed(conn, {j.uid for j in all_jobs}, live_companies)

    print(f"\n{len(all_jobs)} relevant jobs ({new} new, {updated} refreshed); "
          f"{dropped} filtered out.")
    if removed:
        print(f"{removed} duplicate posting(s) merged.")
    if restored:
        print(f"{restored} application status(es) restored from backup.")
    if closed:
        print(f"{closed} posting(s) no longer on their board — marked closed.")
    s = db.stats(conn)
    done = sum(v for k, v in s.items() if k != "new")
    if done:
        print(f"{done} job(s) already actioned — those stay out of the review queue.")
    print("Next:  python3 run.py review")
    return 0


def cmd_list(args) -> int:
    cfg = load_config()
    conn = db.connect()
    rows = db.query(conn, status=args.status,
                    min_score=args.min_score or cfg["filters"]["min_score"],
                    limit=args.limit)
    if not rows:
        print("No matching jobs. Run: python3 run.py fetch")
        return 0
    print(f"{'SCORE':>5}  {'COMPANY':<20} {'TITLE':<50} {'LOCATION':<22} UID")
    print("-" * 128)
    for r in rows:
        print(f"{r['score']:>5}  {r['company'][:20]:<20} {r['title'][:50]:<50} "
              f"{r['location'][:22]:<22} {r['uid']}")
    print(f"\n{len(rows)} jobs. Build a pack:  python3 run.py pack <UID>")
    return 0


def cmd_review(args) -> int:
    from . import dashboard
    dashboard.serve(port=args.port, open_browser=not args.no_open)
    return 0


def cmd_pack(args) -> int:
    conn = db.connect()
    cfg = load_config()
    made = 0
    if args.top:
        rows = db.query(conn, status="new", min_score=cfg["filters"]["min_score"],
                        limit=args.top)
    else:
        rows = [r for r in (db.get(conn, u) for u in args.uid) if r]

    for row in rows:
        folder = letters.build_pack(row, cfg, lang=args.lang)
        db.set_status(conn, row["uid"], "shortlisted")
        print(f"  {row['score']:>3}  {row['company']} — {row['title']}\n       {folder}")
        made += 1
    from .config import output_dir
    print(f"\n{made} application pack(s) built in "
          f"{os.path.relpath(os.path.join(output_dir(), 'applications'), os.getcwd())}/")
    return 0 if made else 1


def cmd_report(args) -> int:
    path, n = report.build(args.out)
    print(f"Ranked document with {n} roles written to:\n  {path}")
    return 0


def cmd_reconcile(args) -> int:
    """Recover application history from the pack folders left on disk.

    Every pack you built is a folder under output/applications/, which is a
    durable record of the jobs you worked on even if the database lost them.
    """
    import os

    from .config import ROOT
    from .letters import _slug

    folder = os.path.join(ROOT, "output", "applications")
    if not os.path.isdir(folder):
        print("No output/applications/ folder yet — nothing to reconcile.")
        return 0

    conn = db.connect()
    db.backup_statuses(conn)
    rows = conn.execute("SELECT uid, company, title, status FROM jobs").fetchall()
    index = {(_slug(r["company"]), _slug(r["title"])): r for r in rows}

    target = args.status
    matched = missing = already = 0
    for name in sorted(os.listdir(folder)):
        if "__" not in name:
            continue
        comp, title = name.split("__", 1)
        row = index.get((comp, title))
        if not row:
            print(f"  ? no matching job for pack '{name}'")
            missing += 1
            continue
        if row["status"] != "new":
            already += 1
            continue
        db.set_status(conn, row["uid"], target)
        print(f"  {target:<12} {row['company'][:24]:<24} {row['title'][:44]}")
        matched += 1

    print(f"\n{matched} marked '{target}', {already} already actioned, "
          f"{missing} pack(s) with no matching job.")
    if matched:
        print("Correct any of these with:  python3 run.py status <uid> <new-status>")
    return 0


def cmd_dedupe(args) -> int:
    conn = db.connect()
    db.backup_statuses(conn)
    removed = db.purge_duplicates(conn)
    print(f"{removed} duplicate posting(s) merged." if removed
          else "No duplicates found.")
    return 0


def cmd_skills(args) -> int:
    pdf, html_path = skillreport.build(args.min_fit, args.out)
    print(f"Skills gap analysis written to:\n  {html_path}")
    if pdf:
        print(f"  {pdf}")
    else:
        print("  (no PDF — install WeasyPrint for that: pip install weasyprint)")
    return 0


def cmd_status(args) -> int:
    conn = db.connect()
    if db.set_status(conn, args.uid, args.new_status, args.note or ""):
        print(f"{args.uid} → {args.new_status}")
        return 0
    print(f"No job with uid {args.uid}")
    return 1


def cmd_stats(args) -> int:
    conn = db.connect()
    s = db.stats(conn)
    total = sum(s.values())
    print(f"Tracked jobs: {total}")
    for k, v in sorted(s.items(), key=lambda x: -x[1]):
        print(f"  {k:<13} {v}")
    return 0


def cmd_profile(args) -> int:
    """Show, list or switch the active profile."""
    from .config import PROFILES_DIR, active_profile, load_config, set_active
    if args.use:
        if not os.path.isdir(os.path.join(PROFILES_DIR, args.use)):
            print(f"No profile '{args.use}'.")
            return 1
        set_active(args.use)
        print(f"Active profile is now '{args.use}'.")
        return 0

    slug = active_profile()
    if not slug:
        print("No profile configured. Run:  python3 setup.py")
        return 1
    cfg = load_config()
    p, f = cfg["profile"], cfg["filters"]
    print(f"Active profile : {slug}")
    print(f"Name           : {p['full_name']}")
    print(f"Headline       : {p.get('headline', '')}")
    print(f"Searching      : {f.get('location_label', '?')}")
    print(f"Domains        : {', '.join(cfg['skills'])}")
    print(f"Output         : output/{slug}/")
    if os.path.isdir(PROFILES_DIR):
        others = [d for d in sorted(os.listdir(PROFILES_DIR))
                  if os.path.isdir(os.path.join(PROFILES_DIR, d)) and d != slug]
        if others:
            print(f"\nOther profiles : {', '.join(others)}")
            print("Switch with    : python3 run.py profile --use <name>")
    return 0


def cmd_discover(args) -> int:
    if args.url:
        discover.from_url(args.url)
    elif args.slug:
        discover.run(args.slug)
    else:
        print("Give a company slug, or --url <careers page>")
        return 1
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="run.py", description="Job search automation, driven by your own CV")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="pull + score jobs from every company")
    f.add_argument("--company", help="limit to one company slug")
    f.set_defaults(func=cmd_fetch)

    l = sub.add_parser("list", help="print ranked matches")
    l.add_argument("--status", default=None)
    l.add_argument("--min-score", type=int, default=0)
    l.add_argument("--limit", type=int, default=40)
    l.set_defaults(func=cmd_list)

    r = sub.add_parser("review", help="open the review dashboard")
    r.add_argument("--port", type=int, default=8765)
    r.add_argument("--no-open", action="store_true")
    r.set_defaults(func=cmd_review)

    k = sub.add_parser("pack", help="build application pack(s)")
    k.add_argument("uid", nargs="*")
    k.add_argument("--top", type=int, help="build packs for the top N new jobs")
    k.add_argument("--lang", choices=["en", "de"], help="force letter language")
    k.set_defaults(func=cmd_pack)

    sk = sub.add_parser("skills", help="PDF analysis of demanded skills and your gaps")
    sk.add_argument("--min-fit", type=int, default=38,
                    help="only analyse roles scoring at least this (default 38)")
    sk.add_argument("--out", help="output PDF path")
    sk.set_defaults(func=cmd_skills)

    rc = sub.add_parser("reconcile",
                        help="recover application history from pack folders")
    rc.add_argument("--status", default="applied", choices=db.STATUSES,
                    help="status to assign (default: applied)")
    rc.set_defaults(func=cmd_reconcile)

    dd = sub.add_parser("dedupe", help="merge duplicate postings already stored")
    dd.set_defaults(func=cmd_dedupe)

    rp = sub.add_parser("report", help="write the ranked HTML document")
    rp.add_argument("--out", help="output path")
    rp.set_defaults(func=cmd_report)

    s = sub.add_parser("status", help="update application status")
    s.add_argument("uid")
    s.add_argument("new_status", choices=db.STATUSES)
    s.add_argument("--note", default="")
    s.set_defaults(func=cmd_status)

    sub.add_parser("stats", help="pipeline summary").set_defaults(func=cmd_stats)

    pr = sub.add_parser("profile", help="show or switch the active profile")
    pr.add_argument("--use", help="make this profile active")
    pr.set_defaults(func=cmd_profile)

    d = sub.add_parser("discover", help="find a company's ATS")
    d.add_argument("slug", nargs="?")
    d.add_argument("--url", help="fingerprint a careers page instead of guessing")
    d.set_defaults(func=cmd_discover)

    args = p.parse_args(argv)
    from .config import ProfileError
    try:
        return args.func(args)
    except ProfileError as exc:
        print(f"\n{exc}\n")
        return 1
