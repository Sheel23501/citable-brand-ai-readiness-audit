#!/usr/bin/env python3
"""run_audit.py: audit one site end to end and write report.json + report.md.

  run_audit.py https://example.com
  run_audit.py https://example.com --workdir audit-example --category saas_software
  run_audit.py --workdir audit-example            # re-run the probes over an existing sample, no fetching
  run_audit.py --workdir audit-example --offline  # never touch the network

The whole pipeline, in stage order:

  sample once   home plus up to five role pages, robots.txt and the sitemap  (auditlib/sampler.py)
  four probes   crawl-render -> fact-extractability -> entity-freshness -> engagement
  compose       merge, dedupe, sort, tag, pre-fill the simulation            (compose.py)
  validate      the handout floor and our superset, non-final                (validate.py)

Each probe runs as its own process with a hard timeout, so one slow or wedged probe cannot
take the run past its wall clock: the run keeps going and the report says which probe did not
finish. The default budget is 300 seconds, split between the sample and the probes and clamped
after every step; nothing here waits on a probe the budget can no longer afford.

Exit 0 when a valid report was written, 1 when the report is invalid or the run failed outright.
Even then a valid report is written: an incomplete audit must never be readable as a clean one.
Standard library only; no traceback ever reaches stdout or stderr.
"""
import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
import time
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import compose as C  # noqa: E402
import validate as V  # noqa: E402
from auditlib.context import AuditContext  # noqa: E402
from auditlib.fetch import normalize_url  # noqa: E402

# stage order (coverage_map.md section 2): access/render, extract, entity/freshness/corroboration, engagement
PROBES = (("crawl-render-audit", "crawl_probe.py"),
          ("fact-extractability-audit", "facts_probe.py"),
          ("entity-freshness-corroboration-audit", "entity_probe.py"),
          ("engagement-audit", "engagement_probe.py"))

WALL_CLOCK = 300.0      # the handout's "under 5 minutes for a typical site"
PROBE_LIMIT = 60.0      # no single probe may hold the run longer than this
SAMPLE_SHARE = 0.55     # the sample is the network-heavy half; the probes mostly read the workdir
COMPOSE_RESERVE = 5.0   # always keep enough to compose, validate and write
PROBE_FLOOR = 8.0       # below this a probe is skipped rather than started and killed


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_workdir(url):
    """report_schema.md section 5: ./audit-<host>-<YYYYMMDD-HHMMSS>/"""
    host = (urlsplit(normalize_url(url)).hostname or "site").replace(":", "_")
    return "audit-%s-%s" % (host, _dt.datetime.now().strftime("%Y%m%d-%H%M%S"))


def _stub(skill, ctx_site, category, error):
    """A probe output that says why this probe has no verdicts, so compose can report it."""
    return {"probe": skill, "probe_version": "0.1.0", "site": ctx_site, "run_at": _now(),
            "site_category": category, "pages_examined": [], "checks": [], "findings": [],
            "artifacts": {}, "error": error}


def run_probe(skill, script, workdir, timeout, category=None, offline=False, no_network=False, verbose=False):
    """Run one probe in its own process. Returns (seconds, error or None). Never raises."""
    out_path = os.path.join(workdir, "probes", skill + ".json")
    cmd = [sys.executable, os.path.join(SKILLS_DIR, skill, "scripts", script),
           "--workdir", workdir, "--out", out_path]
    if category:
        cmd += ["--category", category]
    if offline:
        cmd.append("--offline")
    if no_network and skill == "engagement-audit":
        cmd.append("--no-network")
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max(1.0, timeout))
    except subprocess.TimeoutExpired:
        return time.monotonic() - start, "timed out after %.0f seconds" % timeout
    except Exception as e:  # noqa: BLE001
        return time.monotonic() - start, "could not be started: %s: %s" % (type(e).__name__, e)
    seconds = time.monotonic() - start
    blob = (proc.stdout or "") + (proc.stderr or "")
    if verbose and blob.strip():
        print("  " + blob.strip().replace("\n", "\n  "))
    if "Traceback (most recent call last)" in blob:
        return seconds, "crashed: " + blob.strip().splitlines()[-1][:160]
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return seconds, "exited %d: %s" % (proc.returncode, tail[-1][:160] if tail else "no output")
    if not os.path.exists(out_path):
        return seconds, "wrote no output file"
    return seconds, None


def audit(url=None, workdir=None, category=None, offline=False, no_network=False, time_budget=WALL_CLOCK,
          verbose=False):
    """Sample, probe, compose, validate. Returns (report, workdir, problems, meta). Never raises."""
    start = time.monotonic()
    remaining = lambda: time_budget - (time.monotonic() - start)  # noqa: E731
    meta = {"probes": [], "sampled": False}
    workdir = workdir or default_workdir(url or "site")
    os.makedirs(os.path.join(workdir, "probes"), exist_ok=True)

    site = url or workdir
    if url:
        budget = max(10.0, min(remaining() - COMPOSE_RESERVE, time_budget * SAMPLE_SHARE))
        if verbose:
            print("sampling %s (budget %.0fs) -> %s" % (url, budget, workdir))
        ctx = AuditContext.from_url(url, workdir, offline=offline, category_override=category, time_budget=budget)
        meta["sampled"] = True
        if ctx.error:
            raise RuntimeError(ctx.error)
        site = ctx.site or url
    else:
        ctx = AuditContext.from_workdir(workdir)
        if ctx.error:
            raise RuntimeError(ctx.error)
        site = ctx.site or workdir
    meta["site"] = site
    meta["category"] = category or ctx.category

    for skill, script in PROBES:
        left = remaining() - COMPOSE_RESERVE
        if left < PROBE_FLOOR:
            error, seconds = "skipped: the %.0f second budget was already spent" % time_budget, 0.0
        else:
            seconds, error = run_probe(skill, script, workdir, min(PROBE_LIMIT, left), category=category,
                                       offline=offline, no_network=no_network, verbose=verbose)
        if error:
            with open(os.path.join(workdir, "probes", skill + ".json"), "w", encoding="utf-8") as f:
                json.dump(_stub(skill, site, meta["category"], error), f, indent=2)
        meta["probes"].append({"probe": skill, "seconds": round(seconds, 2), "error": error})
        if verbose:
            print("  %-38s %5.1fs  %s" % (skill, seconds, error or "ok"))

    report = C.compose(workdir, wall_clock=None, input_url=url, category_override=category)
    facts = None
    rel = (report.get("ai_answer_simulation") or {}).get("facts_file")
    if rel and os.path.exists(os.path.join(workdir, rel)):
        try:
            with open(os.path.join(workdir, rel), encoding="utf-8") as f:
                facts = json.load(f)
        except Exception:  # noqa: BLE001
            facts = None
    problems, warnings = V.validate_report(report, facts=facts, final=False)
    report["run"]["wall_clock_seconds"] = round(time.monotonic() - start, 1)
    report["run"]["time_budget_seconds"] = time_budget
    report["run"]["probes"] = meta["probes"]
    if problems:
        report["run"]["validation_problems"] = problems
    if warnings:
        report["run"]["validation_warnings"] = warnings
    return report, workdir, problems, meta


def write_report(report, workdir, out=None, md=None):
    out = out or os.path.join(workdir, "report.json")
    md = md or os.path.join(workdir, "report.md")
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    with open(md, "w", encoding="utf-8") as f:
        f.write(C.render_markdown(report))
    return out, md


def main(argv=None):
    ap = argparse.ArgumentParser(description="Audit a site for AI readiness and on-site engagement.")
    ap.add_argument("url", nargs="?", help="the site to audit (omit to re-use an existing --workdir)")
    ap.add_argument("--url", dest="url_flag", help=argparse.SUPPRESS)
    ap.add_argument("--workdir", help="where to write the run (default ./audit-<host>-<timestamp>/)")
    ap.add_argument("--out", help="report JSON path (default <workdir>/report.json)")
    ap.add_argument("--md", help="report Markdown path (default <workdir>/report.md)")
    ap.add_argument("--category", help="override the inferred site category")
    ap.add_argument("--offline", action="store_true", help="never touch the network")
    ap.add_argument("--no-network", action="store_true", help="sample and grade, but skip the engagement link checks")
    ap.add_argument("--time-budget", type=float, default=WALL_CLOCK, metavar="SECONDS")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    url = args.url or args.url_flag
    if not url and not args.workdir:
        ap.error("give a URL, or --workdir with an existing sample.json")

    workdir = args.workdir or default_workdir(url)
    try:
        report, workdir, problems, meta = audit(
            url=url, workdir=workdir, category=args.category, offline=args.offline,
            no_network=args.no_network, time_budget=args.time_budget, verbose=args.verbose and not args.quiet)
        failed_outright = False
    except Exception as e:  # noqa: BLE001  -- the never-crash guarantee
        report = C._fallback_report(
            workdir, "%s: %s" % (type(e).__name__, e), site_url=url,
            title="The site could not be audited" if url else "The workdir could not be audited",
            action="Check the URL and that the site answers a plain GET, then re-run the audit.")
        problems, failed_outright = [], True
    try:
        out, md = write_report(report, workdir, args.out, args.md)
    except OSError as e:
        print("could not write the report: %s" % e, file=sys.stderr)
        return 1
    if not args.quiet:
        s = report.get("summary") or {}
        run = report.get("run") or {}
        failed = [p["probe"] for p in run.get("probes") or [] if p.get("error")]
        print("%s findings (%s critical, %s high, %s medium, %s low, %s info) from %s checks in %s"
              % (s.get("total_findings"), s.get("critical"), s.get("high"), s.get("medium"), s.get("low"),
                 s.get("info"), s.get("checks_run"),
                 "%ss" % run["wall_clock_seconds"] if run.get("wall_clock_seconds") is not None else "an incomplete run"))
        if failed:
            print("incomplete: %s did not finish; see or.run.probe_error in the report" % ", ".join(failed))
        for x in problems:
            print("PROBLEM  " + x)
        print(out)
        print(md)
    # a degraded run that still produced a valid report is a success: the report says what did not finish
    return 1 if (problems or failed_outright) else 0


if __name__ == "__main__":
    raise SystemExit(main())
