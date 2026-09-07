"""Shared command-line entry for probe scripts: --url or --workdir in, probe JSON out, never a traceback."""
import argparse
import json
import os
import sys
from urllib.parse import urlsplit

from .context import AuditContext
from .fetch import normalize_url
from .findings import validate_probe_output


def probe_main(probe_name, run_fn, doc, argv=None, extra_args=None):
    ap = argparse.ArgumentParser(description=(doc or "").strip().split("\n")[0])
    ap.add_argument("--url", help="audit this URL (samples the site first, writes a workdir)")
    ap.add_argument("--workdir", help="workdir with sample.json + snapshots/ (from sample_site.py or the orchestrator)")
    ap.add_argument("--out", help="write the probe JSON here instead of stdout")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--category", help="override the inferred site category")
    ap.add_argument("--no-robots-obey", action="store_true", help="tests only")
    if extra_args:
        extra_args(ap)
    args = ap.parse_args(argv)
    try:
        if args.url:
            wd = args.workdir or ("audit-%s" % (urlsplit(normalize_url(args.url)).hostname or "site").replace(":", "_"))
            ctx = AuditContext.from_url(args.url, wd, offline=args.offline, category_override=args.category,
                                        obey_robots=not args.no_robots_obey)
        elif args.workdir:
            ctx = AuditContext.from_workdir(args.workdir)
            if args.category:
                ctx.category = args.category
        else:
            ap.error("give --url or --workdir")
        out = run_fn(ctx, args) if _wants_args(run_fn) else run_fn(ctx)
        d = out.to_dict()
        problems = validate_probe_output(d)
        if problems:
            d["error"] = ((d.get("error") or "") + " schema: " + "; ".join(problems[:5])).strip()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001  -- the never-crash guarantee
        d = {"probe": probe_name, "probe_version": "0.1.0", "site": args.url or args.workdir, "run_at": None,
             "site_category": "unknown", "pages_examined": [], "checks": [], "findings": [], "artifacts": {},
             "error": "%s: %s" % (type(e).__name__, e)}
    text = json.dumps(d, indent=2, ensure_ascii=False)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote %s (%d findings, error=%s)" % (args.out, len(d["findings"]), d.get("error")))
    else:
        print(text)
    return 0


def _wants_args(fn):
    try:
        return fn.__code__.co_argcount >= 2
    except AttributeError:
        return False
