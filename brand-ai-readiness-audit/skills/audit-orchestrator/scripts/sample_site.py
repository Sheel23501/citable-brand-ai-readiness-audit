#!/usr/bin/env python3
"""Sample a site (home + up to 5 role pages), infer its category, write snapshots and sample.json.

    python3 sample_site.py https://example.com --workdir audit-example
    python3 sample_site.py https://example.com --category saas_software   # override inference
    python3 sample_site.py https://example.com --offline                  # prove the offline path
    python3 sample_site.py https://example.com --quiet                    # one-line summary only

Prints the sample manifest (fetch_policy.md section 8) as JSON. Never raises.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auditlib.fetch import Fetcher  # noqa: E402
from auditlib.sampler import sample_site  # noqa: E402

CATEGORIES = ("ecommerce", "saas_software", "local_business", "professional_services", "publisher_media",
              "portfolio_personal", "nonprofit_institution", "corporate_enterprise", "unknown")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url")
    ap.add_argument("--workdir", help="where snapshots/, fetch/ and sample.json are written (default: no files)")
    ap.add_argument("--category", choices=CATEGORIES, help="override category inference")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="print a one-line summary instead of the manifest")
    ap.add_argument("--no-robots-obey", action="store_true", help="tests only")
    args = ap.parse_args(argv)
    f = Fetcher(workdir=args.workdir, site=args.url, offline=args.offline, obey_robots=not args.no_robots_obey)
    m = sample_site(f, args.url, category_override=args.category, save=bool(args.workdir))
    if args.quiet:
        roles = [p["role"] for p in m["pages"] if p["fetch"].get("status") == 200]
        print("%s  category=%s(%s)  pages=%s  missing=%s  robots=%s  sitemap=%s  requests=%d" % (
            m["site"], m["site_category"]["value"], m["site_category"]["confidence"], ",".join(roles),
            ",".join(m["missing_roles"]) or "-", m["robots"]["state"], m["sitemap"]["state"], m["requests_made"]))
    else:
        print(json.dumps(m, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
