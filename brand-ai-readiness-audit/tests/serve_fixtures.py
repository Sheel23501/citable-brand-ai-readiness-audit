#!/usr/bin/env python3
"""Serve every test fixture as its own local site, one port each.

Usage:
    python3 tests/serve_fixtures.py                 # serve on 8100.. until Ctrl-C
    python3 tests/serve_fixtures.py --base-port 9000
    python3 tests/serve_fixtures.py --list          # print name -> URL and exit

Importable:
    from serve_fixtures import FixtureFarm
    farm = FixtureFarm(base_port=8100); urls = farm.start(); ...; farm.stop()

Each fixture is a directory under tests/fixtures/<name>/ containing a
_fixture.json (see FIXTURE_SCHEMA below), static files, and optionally a
"base" fixture whose files are used when the variant does not override them.

Standard library only. Read-only GET/HEAD server. Never used in production;
it exists so the probes can be tested without touching real websites.
"""
import argparse
import datetime as _dt
import json
import mimetypes
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES_DIR = os.path.join(HERE, "fixtures")

FIXTURE_SCHEMA = {
    "name": "directory name",
    "description": "one line",
    "base": "name of a fixture whose files are used as fallback, or null",
    "category": "site category id the sampler should infer (site_categories.md)",
    "routes": {"/path": {"status": 200, "content_type": "text/html", "file": "relative/file", "headers": {}},
               "*": "optional catch-all applied to any path that matches no route and no static file (a soft-404 site)"},
    "ua_deny": {"match": ["substring of a User-Agent ..."], "status": 403,
                "body": "optional body", "paths": ["optional: only these paths; default all"]},
    "serve_expectations": {"real_404": "false when the fixture deliberately answers 200 for unknown paths (default true)",
                           "404_links_home": "false when the fixture's 404 page deliberately has no home link (default true)"},
    "expected": {
        "fail": ["check_id ... real defects: findings whose severity is above info"],
        "info": ["check_id ... info-severity findings: inconclusive, not_evaluated notes, and policy notes"],
        "pass_required": ["check_id ... that must be pass, used to catch false positives"],
        "gated": ["check_id ... that fails at probe level but the orchestrator's absence gate withdraws (no finding, "
                  "not_evaluated with reason role_page_not_sampled or navigation_not_readable)"],
        "scoped": ["check_id ... whose final finding must carry absence_scope: sample"],
        "max_severity": {"check_id": "the highest severity the final finding may carry"},
        "max_confidence": {"check_id": "the highest confidence the final finding may carry"},
        "not_evaluated": {"check_id": "the reason a check must record for having no verdict on this fixture "
                                      "(not_applicable_for_category, language_not_supported, listing_pages_only, ...); "
                                      "asserted at probe level and in the composed report's coverage"},
        "notes": "free text",
    },
}

TEXT_TYPES = ("text/html", "application/xml", "text/xml", "text/plain", "application/json", "application/ld+json")
mimetypes.add_type("application/xml", ".xml")
mimetypes.add_type("text/plain", ".txt")


def list_fixture_names():
    names = []
    for n in sorted(os.listdir(FIXTURES_DIR)):
        d = os.path.join(FIXTURES_DIR, n)
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "_fixture.json")):
            names.append(n)
    return names


def load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name, "_fixture.json"), encoding="utf-8") as f:
        meta = json.load(f)
    meta.setdefault("base", None)
    meta.setdefault("routes", {})
    meta.setdefault("ua_deny", None)
    meta["dir"] = os.path.join(FIXTURES_DIR, name)
    meta["base_dir"] = os.path.join(FIXTURES_DIR, meta["base"]) if meta["base"] else None
    return meta


def _resolve(meta, rel):
    """Return the absolute file path for a relative path, variant first, then base."""
    rel = rel.lstrip("/")
    for root in (meta["dir"], meta["base_dir"]):
        if root is None:
            continue
        p = os.path.normpath(os.path.join(root, rel))
        if not p.startswith(root):
            continue  # path traversal
        if os.path.isfile(p):
            return p
    return None


def _candidates(path):
    """URL path -> list of relative file paths to try, in order."""
    path = unquote(path)
    if path.endswith("/"):
        return [path + "index.html"]
    return [path, path + ".html", path + "/index.html"]


def _template(body: bytes, base_url: str) -> bytes:
    today = _dt.date.today()
    repl = {
        b"{{BASE}}": base_url.encode(),
        b"{{YEAR}}": str(today.year).encode(),
        b"{{DATE}}": today.isoformat().encode(),
        b"{{DATE_MINUS_10}}": (today - _dt.timedelta(days=10)).isoformat().encode(),
        b"{{DATE_MINUS_400}}": (today - _dt.timedelta(days=400)).isoformat().encode(),
        b"{{STALE_YEAR}}": str(today.year - 3).encode(),
    }
    for k, v in repl.items():
        body = body.replace(k, v)
    return body


def make_handler(meta, base_url):
    class FixtureHandler(BaseHTTPRequestHandler):
        server_version = "FixtureServer/0.1"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # quiet unless FIXTURE_VERBOSE=1
            if os.environ.get("FIXTURE_VERBOSE"):
                sys.stderr.write("[%s] %s\n" % (meta["name"], fmt % args))

        def _send(self, status, ctype, body, extra_headers=None):
            if ctype.split(";")[0] in TEXT_TYPES:
                body = _template(body, base_url)
                if "charset" not in ctype:
                    ctype += "; charset=utf-8"
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _not_found(self):
            p = _resolve(meta, "404.html")
            if p:
                with open(p, "rb") as f:
                    self._send(404, "text/html", f.read())
            else:
                self._send(404, "text/html",
                           b"<!doctype html><html lang=\"en\"><head><title>Not found</title></head>"
                           b"<body><h1>Page not found</h1><p><a href=\"/\">Back to home</a></p></body></html>")

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            path = urlsplit(self.path).path or "/"
            # 0. user-agent gate: a CDN/WAF refusing a named crawler regardless of robots.txt
            deny = meta.get("ua_deny")
            if deny:
                ua = self.headers.get("User-Agent", "")
                paths = deny.get("paths")
                if (not paths or path in paths) and any(m.lower() in ua.lower() for m in deny.get("match", [])):
                    body = (deny.get("body") or "<!doctype html><title>Forbidden</title><p>Forbidden</p>").encode("utf-8")
                    self._send(deny.get("status", 403), "text/html", body)
                    return
            # 1. explicit route override
            route = meta["routes"].get(path)
            if route:
                body = b""
                if route.get("file"):
                    p = _resolve(meta, route["file"])
                    if p:
                        with open(p, "rb") as f:
                            body = f.read()
                elif route.get("body") is not None:
                    body = route["body"].encode("utf-8")
                self._send(route.get("status", 200), route.get("content_type", "text/html"), body, route.get("headers"))
                return
            # 2. static file, variant then base
            for rel in _candidates(path):
                p = _resolve(meta, rel)
                if p:
                    ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
                    with open(p, "rb") as f:
                        self._send(200, ctype, f.read())
                    return
            # 3. catch-all route (a deliberate soft-404 fixture)
            star = meta["routes"].get("*")
            if star:
                body = b""
                if star.get("file"):
                    p = _resolve(meta, star["file"])
                    if p:
                        with open(p, "rb") as f:
                            body = f.read()
                elif star.get("body") is not None:
                    body = star["body"].encode("utf-8")
                self._send(star.get("status", 200), star.get("content_type", "text/html"), body, star.get("headers"))
                return
            self._not_found()

    return FixtureHandler


class FixtureFarm:
    """Starts one ThreadingHTTPServer per fixture on base_port, base_port+1, ..."""

    def __init__(self, base_port=8100, host="127.0.0.1", only=None):
        self.base_port = base_port
        self.host = host
        self.only = set(only) if only else None
        self.servers = {}
        self.threads = {}
        self.urls = {}
        self.metas = {}

    def plan(self):
        names = [n for n in list_fixture_names() if not self.only or n in self.only]
        return {n: "http://%s:%d" % (self.host, self.base_port + i) for i, n in enumerate(names)}

    def start(self):
        for name, url in self.plan().items():
            meta = load_fixture(name)
            port = int(url.rsplit(":", 1)[1])
            srv = ThreadingHTTPServer((self.host, port), make_handler(meta, url))
            srv.daemon_threads = True
            t = threading.Thread(target=srv.serve_forever, name="fixture-" + name, daemon=True)
            t.start()
            self.servers[name], self.threads[name], self.urls[name], self.metas[name] = srv, t, url, meta
        return dict(self.urls)

    def stop(self):
        for srv in self.servers.values():
            srv.shutdown()
            srv.server_close()
        self.servers.clear()
        self.threads.clear()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-port", type=int, default=8100)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--only", nargs="*", help="fixture names to serve (default all)")
    ap.add_argument("--list", action="store_true", help="print the name -> URL plan and exit")
    args = ap.parse_args(argv)
    farm = FixtureFarm(base_port=args.base_port, host=args.host, only=args.only)
    if args.list:
        for n, u in farm.plan().items():
            print("%-28s %s" % (n, u))
        return 0
    urls = farm.start()
    for n, u in urls.items():
        print("%-28s %s   (%s)" % (n, u, farm.metas[n].get("description", "")))
    print("Serving %d fixtures. Ctrl-C to stop." % len(urls))
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        farm.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
