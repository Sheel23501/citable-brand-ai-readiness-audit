#!/usr/bin/env python3
"""finalize.py: merge the agent's answers and narrative into report.json, re-render, validate --final.

  finalize.py --workdir audit-example --answers answers.json

The orchestrator agent never edits report.json by hand. It writes a small answers file:

  {
    "answers": {
      "q1": {"answer_from_facts": "According to the site, \\"Ledgerly helps freelance designers ...\\"",
             "facts_used": ["what_it_does", "who_it_is_for"]},
      "q3": {"answer_from_facts": "..."}
    },
    "attribution_note": "one or two sentences",
    "narrative_summary": "three to six sentences"
  }

and this script puts each answer on the matching question (only questions with `answerable: true`
take an answer; `facts_used` is optional and defaults to the facts compose listed), sets the
attribution note and the narrative, re-renders report.md from the JSON, and runs the validator
in --final mode. Exit 0 when the final report is valid, 1 with the problems listed otherwise;
report.json is written either way so the agent can fix and re-run. Never raises.

Rules for what an answer may contain: references/simulation_rules.md.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import compose as C  # noqa: E402
import validate as V  # noqa: E402


def apply_answers(report, answers):
    """Merge an answers document into a report in place. Returns a list of merge problems."""
    problems = []
    sim = report.get("ai_answer_simulation") or {}
    by_id = {q.get("id"): q for q in sim.get("questions") or []}
    given = answers.get("answers") or {}
    if not isinstance(given, dict):
        return ["answers must be an object keyed by question id (q1, q2, ...)"]
    for qid, a in given.items():
        q = by_id.get(qid)
        if q is None:
            problems.append("%s: no such question" % qid)
            continue
        if not isinstance(a, dict):
            problems.append("%s: answer entry must be an object" % qid)
            continue
        if not q.get("answerable"):
            problems.append("%s: the question is not answerable from the facts file; leave it unanswered" % qid)
            continue
        text = a.get("answer_from_facts")
        if not isinstance(text, str) or not text.strip():
            problems.append("%s: answer_from_facts must be a non-empty string" % qid)
            continue
        q["answer_from_facts"] = text.strip()
        if a.get("facts_used"):
            if not isinstance(a["facts_used"], list):
                problems.append("%s: facts_used must be a list of fact ids" % qid)
            else:
                q["facts_used"] = list(a["facts_used"])
    for key in ("attribution_note", "narrative_summary"):
        val = answers.get(key)
        if val is not None:
            if not isinstance(val, str):
                problems.append("%s must be a string" % key)
            elif key == "attribution_note":
                sim["attribution_note"] = val.strip()
            else:
                report[key] = val.strip()
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description="Merge the agent's answers into report.json and validate --final.")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--answers", required=True, help="JSON file with answers, attribution_note, narrative_summary")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    report_path = os.path.join(args.workdir, "report.json")
    md_path = os.path.join(args.workdir, "report.md")
    problems = []
    try:
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
    except Exception as e:  # noqa: BLE001
        print("PROBLEM  report.json unreadable: %s" % e)
        return 1
    try:
        with open(args.answers, encoding="utf-8") as f:
            answers = json.load(f)
    except Exception as e:  # noqa: BLE001
        print("PROBLEM  answers file unreadable: %s" % e)
        return 1
    try:
        problems += apply_answers(report, answers if isinstance(answers, dict) else {})
        facts = None
        rel = (report.get("ai_answer_simulation") or {}).get("facts_file")
        if rel and os.path.exists(os.path.join(args.workdir, rel)):
            with open(os.path.join(args.workdir, rel), encoding="utf-8") as f:
                facts = json.load(f)
        more, warnings = V.validate_report(report, facts=facts, final=True)
        problems += more
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(C.render_markdown(report))
    except Exception as e:  # noqa: BLE001  -- never a traceback
        problems.append("finalize error: %s: %s" % (type(e).__name__, e))
        warnings = []
    if not args.quiet:
        for x in problems:
            print("PROBLEM  " + x)
        for x in warnings:
            print("warning  " + x)
        print("%s: %s" % (report_path, "final report valid" if not problems else "%d problem%s" % (
            len(problems), "" if len(problems) == 1 else "s")))
        print(md_path)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
