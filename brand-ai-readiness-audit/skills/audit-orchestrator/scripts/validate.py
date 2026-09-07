#!/usr/bin/env python3
"""validate.py: check a report.json against report_schema.md, floor first, then the superset.

  validate.py --workdir audit-example              # <workdir>/report.json and work/extracted_facts.json
  validate.py --report report.json [--facts work/extracted_facts.json]
  validate.py --workdir audit-example --final      # the report the agent hands over: narrative and answers present

Exit 0 when the report is valid, 1 with a list of problems otherwise. Never a traceback: an unreadable
file is itself a problem.

The **floor** is the handout's required shape (report_schema.md section 3a): site, audited_at, summary
counts that add up and match the findings, and the five per-finding fields. It is never relaxed.
The **superset** is what compose writes (3b, section 4): enum values, ordering, unique sequential ids,
every id in the registry, dedupe integrity, the simulation contract (`basis` fixed, no answer that names
or quotes a fact the facts file does not hold), and, with `--final`, a narrative and an answer for every
answerable question. `warnings` are advisory and never fail the run.

Importable: `validate_report(report, facts=None, final=False) -> (problems, warnings)`.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from auditlib.findings import CONFIDENCES, EFFORTS, SEVERITIES, STAGES, Registry  # noqa: E402

ID_RE = re.compile(r"^F-\d{3}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
CHECK_ID_RE = re.compile(r"^[a-z]{2}\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
FINDING_STATUSES = ("fail", "inconclusive", "not_evaluated")
EVIDENCE_KINDS = ("http_status", "http_header", "robots_rule", "html_excerpt", "jsonld_excerpt", "text_excerpt",
                  "computed", "external")
PRIORITIES = ("high", "medium", "low")
MODES = ("invisible", "stale", "bouncing")
PIPELINE = ("retrieval", "ranking", "selection", "attribution", "post_click")
OPPORTUNITY = ("technical", "content")
CONCEPT_STATES = ("covered", "partial", "out_of_scope", "not_evaluated")
STAGE_STATES = ("evaluated", "partial", "not_evaluated")
REPORT_KEYS = ("site", "site_url", "audited_at", "tool", "input_url", "site_category", "pages_sampled", "summary",
               "findings", "quick_wins", "passed_checks", "coverage", "proactive_recommendations",
               "ai_answer_simulation", "narrative_summary", "limitations", "suppressed_findings", "run")
QUOTE_WINDOW = 20


def _sev(s):
    return SEVERITIES.index(s) if s in SEVERITIES else len(SEVERITIES)


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").replace("…", " ")).strip().lower()


def quotes_fact(answer, value):
    """True when the answer carries a verbatim run of the fact's value (the whole value when it is short)."""
    a, v = _norm(answer), _norm(value)
    if not v:
        return False
    if len(v) <= QUOTE_WINDOW:
        return v in a
    return any(v[i:i + QUOTE_WINDOW] in a for i in range(0, len(v) - QUOTE_WINDOW + 1))


# ---------------------------------------------------------------- floor (report_schema.md section 3a)
def check_floor(r, problems):
    p = lambda msg: problems.append("floor: " + msg)  # noqa: E731
    if not isinstance(r, dict):
        p("report is not a JSON object")
        return
    if not isinstance(r.get("site"), str) or not r["site"].strip():
        p("site missing or empty")
    if not isinstance(r.get("audited_at"), str) or not ISO_RE.match(r["audited_at"]):
        p("audited_at missing or not UTC ISO-8601 with Z")
    s = r.get("summary")
    findings = r.get("findings")
    if not isinstance(findings, list):
        p("findings missing or not a list")
        findings = []
    if not isinstance(s, dict):
        p("summary missing")
    else:
        bad = [k for k in ("total_findings", "critical", "high", "medium", "low", "info")
               if not isinstance(s.get(k), int) or isinstance(s.get(k), bool)]
        if bad:
            p("summary counts missing or not integers: %s" % ", ".join(bad))
        else:
            total = sum(s[k] for k in ("critical", "high", "medium", "low", "info"))
            if s["total_findings"] != total:
                p("summary.total_findings (%d) is not the sum of the severity counts (%d)" % (s["total_findings"], total))
            if s["total_findings"] != len(findings):
                p("summary.total_findings (%d) does not match findings length (%d)" % (s["total_findings"], len(findings)))
            actual = {k: sum(1 for f in findings if isinstance(f, dict) and f.get("severity") == k) for k in SEVERITIES}
            off = [k for k in SEVERITIES if actual[k] != s.get(k)]
            if off:
                p("summary counts do not match the findings for: %s" % ", ".join(off))
    seen = set()
    for i, f in enumerate(findings):
        tag = "findings[%d]" % i
        if not isinstance(f, dict):
            p("%s is not an object" % tag)
            continue
        fid = f.get("id")
        if not isinstance(fid, str) or not ID_RE.match(fid):
            p("%s: id missing or not F-###" % tag)
        elif fid in seen:
            p("%s: duplicate id %s" % (tag, fid))
        seen.add(fid)
        if not isinstance(f.get("title"), str) or not f["title"].strip():
            p("%s: title missing or empty" % tag)
        if f.get("severity") not in SEVERITIES:
            p("%s: severity missing or not one of %s" % (tag, "/".join(SEVERITIES)))
        if not isinstance(f.get("evidence"), str) or not f["evidence"].strip():
            p("%s: evidence missing or empty" % tag)
        sa = f.get("suggested_action")
        if not isinstance(sa, dict):
            p("%s: suggested_action missing or not an object" % tag)
        else:
            if not isinstance(sa.get("summary"), str) or not sa["summary"].strip():
                p("%s: suggested_action.summary missing or empty" % tag)
            if sa.get("priority") not in PRIORITIES:
                p("%s: suggested_action.priority missing or not high/medium/low" % tag)


# ---------------------------------------------------------------- superset (sections 3b, 4, the rubric)
def _check_finding(f, tag, reg, p):
    cid = f.get("check_id")
    if not isinstance(cid, str) or not CHECK_ID_RE.match(cid):
        p("%s: check_id missing or malformed" % tag)
        cid = None
    elif cid not in reg:
        p("%s: check_id %s is not in the registry" % (tag, cid))
    if f.get("status") not in FINDING_STATUSES:
        p("%s: status must be fail/inconclusive/not_evaluated, got %r" % (tag, f.get("status")))
    if f.get("status") in ("inconclusive", "not_evaluated") and f.get("severity") != "info":
        p("%s: %s findings are always info" % (tag, f.get("status")))
    if f.get("confidence") not in CONFIDENCES:
        p("%s: confidence not high/medium/low" % tag)
    if f.get("effort") not in EFFORTS:
        p("%s: effort not low/medium/high/n/a" % tag)
    if f.get("effort") == "n/a" and f.get("severity") != "info":
        p("%s: effort n/a is only for info findings" % tag)
    if f.get("confidence") == "low" and f.get("severity") in ("critical", "high"):
        p("%s: low confidence caps severity at medium" % tag)
    mech = f.get("mechanism")
    if mech is not None and mech not in STAGES:
        p("%s: mechanism %r is not a stage" % (tag, mech))
    if cid and cid in reg:
        row = reg[cid]
        if f.get("status") == "fail" and _sev(f.get("severity", "info")) < _sev(row["max_severity"]):
            p("%s: severity %s exceeds the registered maximum %s" % (tag, f.get("severity"), row["max_severity"]))
        if mech != row["stage"]:
            p("%s: mechanism %r does not match the registry stage %r" % (tag, mech, row["stage"]))
    if not isinstance(f.get("title"), str) or len(f.get("title", "")) > 90:
        p("%s: title longer than 90 characters" % tag)
    if not isinstance(f.get("evidence"), str) or len(f.get("evidence", "")) > 300:
        p("%s: evidence sentence longer than 300 characters" % tag)
    pages = f.get("affected_pages")
    if not isinstance(pages, list) or not all(isinstance(u, str) for u in pages):
        p("%s: affected_pages must be a list of URLs" % tag)
        pages = []
    items = f.get("evidence_items")
    if not isinstance(items, list) or not items:
        p("%s: evidence_items must hold at least one item" % tag)
    else:
        for j, it in enumerate(items):
            if not isinstance(it, dict) or it.get("kind") not in EVIDENCE_KINDS or not it.get("page") \
                    or not isinstance(it.get("value"), str):
                p("%s: evidence_items[%d] needs page, a known kind, and a string value" % (tag, j))
            elif len(it["value"]) > 300:
                p("%s: evidence_items[%d] value longer than 300 characters" % (tag, j))
    if not isinstance(f.get("why_it_matters"), str) or not f["why_it_matters"].strip():
        p("%s: why_it_matters missing" % tag)
    sa = f.get("suggested_action") or {}
    if isinstance(sa, dict):
        if not isinstance(sa.get("detail"), str) or not sa["detail"].strip():
            p("%s: suggested_action.detail missing" % tag)
        if sa.get("impact") not in PRIORITIES:
            p("%s: suggested_action.impact not high/medium/low" % tag)
        if sa.get("effort") != f.get("effort"):
            p("%s: suggested_action.effort does not mirror the finding's effort" % tag)
        sev = f.get("severity")
        impact = "high" if sev in ("critical", "high") else ("medium" if sev == "medium" else "low")
        if sev in SEVERITIES and sa.get("impact") != impact:
            p("%s: impact must be derived from severity (%s -> %s)" % (tag, sev, impact))
        expected_priority = impact
        if f.get("confidence") == "low" and impact != "low":
            expected_priority = {"high": "medium", "medium": "low"}[impact]
        if sev in SEVERITIES and sa.get("priority") != expected_priority:
            p("%s: priority must equal impact lowered one level for low confidence (expected %s)" % (tag, expected_priority))
    if cid and f.get("dedupe_key") != cid + "|" + ",".join(sorted(pages)):
        p("%s: dedupe_key is not check_id|sorted pages" % tag)
    refs = f.get("references", [])
    if not isinstance(refs, list) or not all(isinstance(u, str) and u.startswith("http") for u in refs):
        p("%s: references must be absolute URLs" % tag)
    if f.get("round2_mode") is not None and f.get("round2_mode") not in MODES:
        p("%s: round2_mode not invisible/stale/bouncing" % tag)
    if f.get("pipeline_stage") is not None and f.get("pipeline_stage") not in PIPELINE:
        p("%s: pipeline_stage unknown" % tag)
    if f.get("opportunity_type") not in OPPORTUNITY:
        p("%s: opportunity_type not technical/content" % tag)
    if not isinstance(f.get("handout_concepts"), list) or not set(f.get("handout_concepts") or []) <= set("ABCDEF"):
        p("%s: handout_concepts must be a list of letters A-F" % tag)
    if not isinstance(f.get("source_skill"), str) or not f["source_skill"]:
        p("%s: source_skill missing" % tag)


def _sort_key(f):
    return (_sev(f.get("severity", "info")),
            CONFIDENCES.index(f["confidence"]) if f.get("confidence") in CONFIDENCES else 3,
            -len(f.get("affected_pages") or []), f.get("check_id", ""))


def _quick_win(f):
    return (f.get("severity") in ("critical", "high", "medium") and f.get("effort") == "low"
            and f.get("confidence") != "low" and f.get("status") == "fail")


def check_superset(r, problems, warnings, reg, facts=None, final=False):
    p = lambda msg: problems.append("superset: " + msg)  # noqa: E731
    w = warnings.append
    if not isinstance(r, dict):
        return
    for k in REPORT_KEYS:
        if k not in r:
            p("missing top-level field %s" % k)
    if not isinstance(r.get("site_url"), str) or (r["site_url"] and not r["site_url"].startswith(("http://", "https://"))):
        p("site_url must be an absolute origin (empty only when the run never reached the site)")
    tool = r.get("tool")
    if not isinstance(tool, dict) or not tool.get("name") or not tool.get("version"):
        p("tool must carry name and version")
    sc = r.get("site_category")
    if not isinstance(sc, dict) or not sc.get("value") or sc.get("confidence") not in CONFIDENCES:
        p("site_category needs value and confidence")
    for i, pg in enumerate(r.get("pages_sampled") or []):
        if not isinstance(pg, dict) or not pg.get("role") or not pg.get("url"):
            p("pages_sampled[%d] needs role and url" % i)

    findings = [f for f in (r.get("findings") or []) if isinstance(f, dict)]
    for i, f in enumerate(findings):
        _check_finding(f, "findings[%d]" % i, reg, p)
        if f.get("rank") != i + 1:
            p("findings[%d]: rank must be %d" % (i, i + 1))
        if f.get("id") != "F-%03d" % (i + 1):
            p("findings[%d]: id must be F-%03d after sorting" % (i, i + 1))
        if not isinstance(f.get("quick_win"), bool):
            p("findings[%d]: quick_win must be a boolean" % i)
        elif f["quick_win"] != _quick_win(f):
            p("findings[%d]: quick_win flag contradicts the rubric" % i)
    if findings != sorted(findings, key=_sort_key):
        p("findings are not in schema order (severity, confidence, page count, check_id)")
    if r.get("quick_wins") != [f.get("id") for f in findings if f.get("quick_win")]:
        p("quick_wins does not list exactly the flagged findings in rank order")

    # summary check counts
    s = r.get("summary") or {}
    if isinstance(s, dict) and all(isinstance(s.get(k), int) for k in
                                   ("checks_run", "checks_passed", "checks_failed", "checks_inconclusive", "checks_not_evaluated")):
        if s["checks_run"] != s["checks_passed"] + s["checks_failed"] + s["checks_inconclusive"] + s["checks_not_evaluated"]:
            p("summary.checks_run is not the sum of the check status counts")
        if s["checks_passed"] != len(r.get("passed_checks") or []):
            p("summary.checks_passed does not match passed_checks length")
        if s["checks_run"] < len(reg.ids()):
            w("only %d of %d registered checks have a verdict" % (s["checks_run"], len(reg.ids())))
    else:
        p("summary is missing the checks_* counts")

    # passed checks: registry ids, never a finding
    finding_ids = {f.get("check_id") for f in findings}
    for i, c in enumerate(r.get("passed_checks") or []):
        if not isinstance(c, dict) or c.get("check_id") not in reg:
            p("passed_checks[%d]: unknown check_id" % i)
        elif c["check_id"] in finding_ids:
            p("passed_checks[%d]: %s is also a finding" % (i, c["check_id"]))
        elif not c.get("title") or not c.get("source_skill"):
            p("passed_checks[%d]: needs title and source_skill" % i)

    # dedupe integrity
    ids = {f.get("id") for f in findings}
    keys = {f.get("dedupe_key") for f in findings}
    by_id = {f.get("id"): f for f in findings}
    for i, f in enumerate(r.get("suppressed_findings") or []):
        tag = "suppressed_findings[%d]" % i
        if not isinstance(f, dict):
            p("%s: not an object" % tag)
            continue
        _check_finding(f, tag, reg, p)
        if f.get("merged_into") not in ids:
            p("%s: merged_into %r is not a finding id" % (tag, f.get("merged_into")))
        elif f.get("dedupe_key") not in (by_id[f["merged_into"]].get("merged_from") or []):
            p("%s: the primary %s does not list it under merged_from" % (tag, f["merged_into"]))
        if f.get("dedupe_key") in keys:
            p("%s: %s appears both kept and folded" % (tag, f.get("dedupe_key")))

    # coverage
    cov = r.get("coverage")
    if not isinstance(cov, dict):
        p("coverage missing")
    else:
        hc = cov.get("handout_concepts") or {}
        if set(hc) != set("ABCDEF") or any(v not in CONCEPT_STATES for v in hc.values()):
            p("coverage.handout_concepts must map A-F to covered/partial/out_of_scope/not_evaluated")
        st = cov.get("stages") or {}
        if set(st) != set(STAGES) or any(v not in STAGE_STATES for v in st.values()):
            p("coverage.stages must map the seven stages to evaluated/partial/not_evaluated")
        for i, e in enumerate(cov.get("not_evaluated") or []):
            if not isinstance(e, dict) or e.get("check_id") not in reg or not e.get("reason"):
                p("coverage.not_evaluated[%d]: needs a registry check_id and a reason" % i)

    # recommendations: opportunities, never a restated finding
    titles = {_norm(f.get("title")) for f in findings}
    for i, rec in enumerate(r.get("proactive_recommendations") or []):
        tag = "proactive_recommendations[%d]" % i
        if not isinstance(rec, dict) or not rec.get("title") or not rec.get("rationale"):
            p("%s: needs title and rationale" % tag)
            continue
        if rec.get("mechanism") not in STAGES or rec.get("effort") not in ("low", "medium", "high") \
                or rec.get("priority") not in PRIORITIES:
            p("%s: mechanism/effort/priority out of range" % tag)
        if _norm(rec["title"]) in titles:
            p("%s: restates finding title %r" % (tag, rec["title"]))

    # limitations
    lim = r.get("limitations")
    if not isinstance(lim, list) or not lim or not all(isinstance(x, str) and x for x in lim):
        p("limitations must be a non-empty list of sentences")
    else:
        if not lim[0].startswith("This report reflects a single point-in-time fetch"):
            p("limitations must open with the point-in-time statement")
        if not any("served HTML only" in x or "did not complete" in x for x in lim):
            p("limitations must state that the audit reads served HTML only")

    if not isinstance(r.get("narrative_summary"), str):
        p("narrative_summary must be a string (empty until the agent writes it)")
    run = r.get("run")
    if not isinstance(run, dict) or not isinstance(run.get("probe_errors"), list):
        p("run.probe_errors must be a list")

    check_simulation(r.get("ai_answer_simulation"), p, w, facts, final)
    if final:
        narrative = r.get("narrative_summary") or ""
        if not narrative.strip():
            p("--final: narrative_summary is empty")
        else:
            n = len(re.findall(r"[.!?](?:\s|$)", narrative))
            if not 3 <= n <= 6:
                w("narrative_summary has about %d sentences; the orchestrator asks for 3-6" % n)


def check_simulation(sim, p, w, facts, final):
    if not isinstance(sim, dict):
        p("ai_answer_simulation missing")
        return
    if sim.get("basis") != "extracted_facts_only":
        p("ai_answer_simulation.basis must be exactly extracted_facts_only")
    qs = sim.get("questions")
    if not isinstance(qs, list):
        p("ai_answer_simulation.questions must be a list")
        return
    fact_map = ((facts or {}).get("facts") or {}) if isinstance(facts, dict) else {}
    present = {fid for fid, f in fact_map.items() if isinstance(f, dict) and f.get("status") == "present"}
    for i, q in enumerate(qs):
        tag = "ai_answer_simulation.questions[%d]" % i
        if not isinstance(q, dict) or not q.get("question") or not isinstance(q.get("answerable"), bool) \
                or not isinstance(q.get("facts_used"), list) or not isinstance(q.get("missing_facts"), list):
            p("%s: needs question, answerable, facts_used, missing_facts" % tag)
            continue
        ans = q.get("answer_from_facts")
        if ans is not None and not isinstance(ans, str):
            p("%s: answer_from_facts must be null or a string" % tag)
            continue
        if not q["answerable"]:
            if ans:
                p("%s: an unanswerable question carries an answer" % tag)
            if not q["missing_facts"]:
                p("%s: unanswerable but missing_facts is empty" % tag)
            continue
        if q["missing_facts"]:
            p("%s: answerable but missing_facts is not empty" % tag)
        if final and not ans:
            p("--final: %s is answerable but has no answer" % tag)
        if ans:
            if not q["facts_used"]:
                p("%s: an answer must list the facts it used" % tag)
            if facts is None:
                p("%s: cannot verify the answer without the facts file" % tag)
                continue
            for fid in q["facts_used"]:
                if fid not in present:
                    p("%s: cites fact %r which the facts file does not hold as present" % (tag, fid))
                elif not quotes_fact(ans, fact_map[fid].get("value")):
                    p("%s: the answer does not quote the value of fact %r verbatim" % (tag, fid))
    if final and not (sim.get("attribution_note") or "").strip():
        w("--final: attribution_note is empty")


# ---------------------------------------------------------------- entry points
def validate_report(report, facts=None, final=False, registry=None):
    """Return (problems, warnings). Empty problems = valid. Never raises."""
    problems, warnings = [], []
    try:
        reg = registry or Registry()
        check_floor(report, problems)
        check_superset(report, problems, warnings, reg, facts=facts, final=final)
    except Exception as e:  # noqa: BLE001  -- a validator that crashes has validated nothing
        problems.append("validator error: %s: %s" % (type(e).__name__, e))
    return problems, warnings


def _load(path, label, problems):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        problems.append("%s unreadable: %s" % (label, e))
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate a report.json against report_schema.md.")
    ap.add_argument("--workdir", help="workdir holding report.json and work/extracted_facts.json")
    ap.add_argument("--report", help="report.json path (overrides --workdir)")
    ap.add_argument("--facts", help="extracted-facts file (default: the path the report names, under --workdir)")
    ap.add_argument("--final", action="store_true", help="require the agent's narrative and simulation answers")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    if not args.report and not args.workdir:
        ap.error("give --workdir or --report")
    problems, warnings = [], []
    report_path = args.report or os.path.join(args.workdir, "report.json")
    report = _load(report_path, "report", problems)
    facts = None
    if report is not None:
        facts_path = args.facts
        if not facts_path:
            rel = ((report.get("ai_answer_simulation") or {}).get("facts_file")) if isinstance(report, dict) else None
            base = args.workdir or os.path.dirname(os.path.abspath(report_path))
            if rel:
                facts_path = os.path.join(base, rel)
        if facts_path and os.path.exists(facts_path):
            facts = _load(facts_path, "facts file", problems)
        elif args.final:
            warnings.append("no facts file found; simulation answers cannot be verified")
        more, warn = validate_report(report, facts=facts, final=args.final)
        problems += more
        warnings += warn
    if not args.quiet:
        for x in problems:
            print("PROBLEM  " + x)
        for x in warnings:
            print("warning  " + x)
        print("%s: %d problem%s, %d warning%s%s" % (report_path, len(problems), "" if len(problems) == 1 else "s",
                                                   len(warnings), "" if len(warnings) == 1 else "s",
                                                   " (final)" if args.final else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
