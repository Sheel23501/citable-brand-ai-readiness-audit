#!/usr/bin/env python3
"""Fetch one URL under the audit fetch policy and print the FetchResult as JSON.

    python3 fetch_url.py https://example.com/            # FetchResult (no body)
    python3 fetch_url.py https://example.com/ --robots   # also the parsed robots.txt and per-token grading
    python3 fetch_url.py https://example.com/ --body     # include the first 2000 chars of text
    python3 fetch_url.py https://example.com/ --offline  # prove the offline path

Exit code is always 0 unless the arguments are wrong: the helper never raises.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auditlib.fetch import Fetcher, visible_word_count  # noqa: E402
from auditlib.robots import load_bot_tiers, grade_tokens  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url")
    ap.add_argument("--robots", action="store_true")
    ap.add_argument("--body", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--no-robots-obey", action="store_true", help="do not skip robots-disallowed URLs (tests only)")
    ap.add_argument("--workdir", help="save body under <workdir>/snapshots/ and write fetch/manifest.json")
    args = ap.parse_args(argv)
    f = Fetcher(workdir=args.workdir, site=args.url, offline=args.offline, obey_robots=not args.no_robots_obey)
    r = f.get(args.url, purpose="page", save_as="snapshots/page.html" if args.workdir else None)
    out = dict(r)
    out["visible_words"] = visible_word_count(r.body)
    if args.body:
        out["text_head"] = r.text[:2000]
    if args.robots:
        rob = f.robots()
        out["robots"] = rob.to_dict()
        out["robots"]["audit_token_allowed_root"] = rob.is_allowed("/", "brand-ai-readiness-audit")
        out["bot_grading"] = grade_tokens(rob, load_bot_tiers(), key_paths=["/", "/pricing", "/about", "/contact"])
    out["requests_made"] = f.requests_made
    if args.workdir:
        out["manifest"] = f.save_manifest()
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
