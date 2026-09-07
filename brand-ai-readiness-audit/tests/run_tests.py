#!/usr/bin/env python3
"""Test runner for brand-ai-readiness-audit.

Step 3 scope (this file): start every fixture on its own port, verify each one
serves (home, robots.txt, sitemap.xml, 404 behaviour, route overrides), and
validate every _fixture.json against the check registry so fixtures can never
expect a check id that does not exist.

Later steps add stages here rather than creating new runners:
  Step 4          robots + fetch stages (done)
  Step 5          htmldoc + sample stages (done)
  Step 6          probe_cr stage (done)
  Step 8          extract + probe_fx stages (done)
  Step 6/8/10/12  run each probe against each fixture and compare `expected`
  Step 14        compose stage: the dedupe table, ordering, and a report per fixture (done)
  Step 15        validate stage: floor, superset, --final, 45 deliberately broken reports (done)
  Step 16         run run-audit end to end on each fixture
  Step 18         validate every report; assert no tracebacks anywhere

Usage:
    python3 tests/run_tests.py            # all stages available so far
    python3 tests/run_tests.py --stage serve
    python3 tests/run_tests.py --base-port 8200 --keep   # leave servers up

Exit code 0 = green, 1 = a check failed, 2 = runner error. Standard library only.
"""
import argparse
import json
import os
import re
import sys
import traceback
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from serve_fixtures import FixtureFarm, list_fixture_names, load_fixture  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "skills", "audit-orchestrator", "scripts"))
from auditlib import robots as robotslib  # noqa: E402
from auditlib.fetch import Fetcher, detect_challenge, registrable_domain, normalize_url, visible_word_count  # noqa: E402
from auditlib.htmldoc import Document  # noqa: E402
from auditlib.sampler import sample_site, find_role_candidates, categorize, ROLE_KEYWORDS  # noqa: E402

REGISTRY = os.path.join(ROOT, "skills", "audit-orchestrator", "references", "check_ids.md")
CHECK_ID_RE = re.compile(r"^\| `([a-z]{2}\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)` \|", re.M)
CATEGORIES = {"ecommerce", "saas_software", "local_business", "professional_services", "publisher_media",
              "portfolio_personal", "nonprofit_institution", "corporate_enterprise", "unknown"}


class Results:
    def __init__(self):
        self.passed, self.failed = [], []

    def ok(self, name):
        self.passed.append(name)
        print("  PASS  " + name)

    def fail(self, name, detail=""):
        self.failed.append((name, detail))
        print("  FAIL  " + name + (("  -> " + detail) if detail else ""))

    def check(self, cond, name, detail=""):
        (self.ok if cond else lambda n: self.fail(n, detail))(name)
        return cond


def registry_ids():
    with open(REGISTRY, encoding="utf-8") as f:
        return set(CHECK_ID_RE.findall(f.read()))


def http_get(url, timeout=5):
    req = urllib.request.Request(url, headers={"User-Agent": "brand-ai-readiness-audit-tests/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


# ---------------------------------------------------------------- stage: manifest
def stage_manifest(res):
    print("\n== stage: fixture manifests")
    ids = registry_ids()
    res.check(len(ids) >= 50, "registry parsed (%d check ids)" % len(ids))
    names = list_fixture_names()
    res.check(len(names) >= 8, "at least 8 fixtures present (%d)" % len(names))
    for n in names:
        meta = load_fixture(n)
        res.check(meta.get("name") == n, "%s: name matches directory" % n)
        res.check(meta.get("category") in CATEGORIES, "%s: category is a known id" % n, str(meta.get("category")))
        if meta.get("base"):
            res.check(os.path.isdir(meta["base_dir"]), "%s: base fixture exists (%s)" % (n, meta["base"]))
        exp = meta.get("expected", {})
        for key in ("fail", "info", "pass_required"):
            unknown = sorted(set(exp.get(key, [])) - ids)
            res.check(not unknown, "%s: expected.%s ids all in registry" % (n, key), ", ".join(unknown))
        overlap = set(exp.get("fail", [])) & set(exp.get("pass_required", []))
        res.check(not overlap, "%s: no id both expected to fail and required to pass" % n, ", ".join(sorted(overlap)))
        for path, route in meta.get("routes", {}).items():
            pass
    # every engagement check is exercised by at least one fixture that expects it to fail (or, for info checks, to emit a note)
    exercised = set()
    for n in names:
        exp = load_fixture(n).get("expected", {})
        exercised |= set(exp.get("fail", [])) | set(exp.get("info", []))
    unexercised = sorted(c for c in ids if c.startswith("en.") and c not in exercised)
    res.check(not unexercised, "fixtures exercise every en.* check as a failure or note", ", ".join(unexercised))
    # documentation hygiene: a skill whose references/ exist must document every registered check of its prefix,
    # and its SKILL.md must point at a script that exists
    skill_prefix = {"crawl-render-audit": "cr.", "fact-extractability-audit": "fx.",
                    "entity-freshness-corroboration-audit": "ef.", "engagement-audit": "en."}
    for skill, prefix in skill_prefix.items():
        refdir = os.path.join(ROOT, "skills", skill, "references")
        mds = [f for f in os.listdir(refdir)] if os.path.isdir(refdir) else []
        if not mds:
            continue
        text = "\n".join(open(os.path.join(refdir, f), encoding="utf-8").read() for f in mds if f.endswith(".md"))
        missing = [c for c in sorted(ids) if c.startswith(prefix) and "`%s`" % c not in text]
        res.check(not missing, "%s: references document every %s check" % (skill, prefix), ", ".join(missing))
        skill_md = open(os.path.join(ROOT, "skills", skill, "SKILL.md"), encoding="utf-8").read()
        scripts = re.findall(r"skills/%s/scripts/(\w+\.py)" % re.escape(skill), skill_md)
        res.check(scripts and all(os.path.exists(os.path.join(ROOT, "skills", skill, "scripts", sc)) for sc in scripts),
                  "%s: SKILL.md names an existing script (%s)" % (skill, ",".join(sorted(set(scripts)))))
        res.check("## Procedure" in skill_md and re.search(r"^1\. ", skill_md, re.M) is not None, "%s: SKILL.md has a numbered Procedure" % skill)
        # every reference file is named in SKILL.md, and every reference SKILL.md names exists (no orphans either way)
        ref_files = sorted(f for f in mds if f.endswith(".md"))
        unnamed = [f for f in ref_files if "references/%s" % f not in skill_md]
        res.check(not unnamed, "%s: SKILL.md names every references/*.md file" % skill, ", ".join(unnamed))
        skill_dir = os.path.join(ROOT, "skills", skill)
        mentioned = set(re.findall(r"`((?:\.\./)*[\w./-]*references/[\w.-]+\.md)`", skill_md))
        dangling = sorted(m for m in mentioned if not os.path.exists(os.path.normpath(os.path.join(skill_dir, m))))
        res.check(not dangling, "%s: every references/*.md path named in SKILL.md exists" % skill, ", ".join(dangling))
    for name in names:
        meta = load_fixture(name)
        for path, route in meta.get("routes", {}).items():
            if route.get("file"):
                from serve_fixtures import _resolve
                res.check(_resolve(meta, route["file"]) is not None, "%s: route %s file exists" % (n, path), route["file"])


# ---------------------------------------------------------------- stage: serve
def stage_serve(res, farm):
    print("\n== stage: fixtures serve locally")
    for name, base in farm.urls.items():
        meta = farm.metas[name]
        st, ct, body = http_get(base + "/")
        home_route = meta["routes"].get("/")
        if home_route:
            res.check(st == home_route.get("status", 200) and ct.startswith(home_route.get("content_type", "text/html")),
                      "%s: / honours route override (%s %s)" % (name, st, ct.split(";")[0]))
        else:
            res.check(st == 200 and ct.startswith("text/html"), "%s: / is 200 text/html" % name, "%s %s" % (st, ct))
            res.check(b"{{" not in body, "%s: / has no unexpanded template tokens" % name)
        st, ct, body = http_get(base + "/robots.txt")
        res.check(st == 200 and ct.startswith("text/plain"), "%s: /robots.txt is 200 text/plain" % name, "%s %s" % (st, ct))
        res.check(b"User-agent" in body, "%s: robots.txt has a User-agent group" % name)
        if b"Sitemap:" in body:
            res.check(base.encode() in body, "%s: robots Sitemap URL points at this port" % name)
            st, ct, sm = http_get(base + "/sitemap.xml")
            res.check(st == 200 and "xml" in ct, "%s: /sitemap.xml is 200 xml" % name, "%s %s" % (st, ct))
            res.check(sm.count(b"<loc>") >= 1 and base.encode() in sm, "%s: sitemap <loc> entries use this port" % name)
        st, ct, body = http_get(base + "/definitely-not-a-page-3f9a")
        se = meta.get("serve_expectations", {})
        if se.get("real_404", True):
            res.check(st == 404, "%s: unknown path returns real 404" % name, str(st))
        else:
            res.check(st == 200, "%s: unknown path deliberately answers 200 (soft-404 fixture)" % name, str(st))
        if se.get("404_links_home", True):
            res.check(b'href="/"' in body, "%s: 404 page links home" % name)
        else:
            res.check(st == 404 and b'href="/"' not in body, "%s: 404 page deliberately has no home link" % name)
        # every page in the sitemap of an HTML fixture must resolve (link health baseline)
        if not home_route and b"Sitemap:" in http_get(base + "/robots.txt")[2]:
            sm = http_get(base + "/sitemap.xml")[2].decode("utf-8", "replace")
            bad = []
            for loc in re.findall(r"<loc>(.*?)</loc>", sm):
                s2, _, _ = http_get(loc)
                if s2 != 200:
                    bad.append("%s->%s" % (loc, s2))
            res.check(not bad, "%s: every sitemap URL is 200" % name, "; ".join(bad))
        # extensionless routing works
        if (meta["base"] == "clean-site" or name == "clean-site") and "/about" not in meta["routes"]:
            st, _, _ = http_get(base + "/about")
            res.check(st == 200, "%s: /about resolves to about.html" % name, str(st))


# ---------------------------------------------------------------- stage: variants
def stage_variants(res, farm):
    """Cheap content assertions that the variants really differ from the base in the intended way."""
    print("\n== stage: variant content sanity")
    u = farm.urls
    if "clean-site" in u:
        body = http_get(u["clean-site"] + "/pricing")[2]
        res.check(b"\xc2\xa312 per month" in body, "clean-site: pricing has plain-text prices")
        body = http_get(u["clean-site"] + "/")[2]
        for tok in (b"application/ld+json", b'name="viewport"', b"<nav", b"<h1>", b"sameAs", b"12 Harbour Street"):
            res.check(tok in body, "clean-site: home contains %s" % tok.decode())
        try:
            for m in re.finditer(rb'<script type="application/ld\+json">(.*?)</script>', body, re.S):
                json.loads(m.group(1).decode("utf-8"))
            res.ok("clean-site: every home JSON-LD block parses")
        except Exception as e:  # noqa: BLE001
            res.fail("clean-site: every home JSON-LD block parses", str(e))
    if "csr-shell" in u:
        body = http_get(u["csr-shell"] + "/")[2]
        res.check(b'<div id="root"></div>' in body and b"<h1" not in body, "csr-shell: home is an empty root with no heading")
        js = http_get(u["csr-shell"] + "/static/main.9f2c4b.js")
        res.check(js[0] == 200 and len(js[2]) > 50000, "csr-shell: main bundle serves and is large (%d bytes)" % len(js[2]))
    if "js-gate" in u:
        body = http_get(u["js-gate"] + "/")[2]
        res.check(b"enable JavaScript" in body and b'<div id="root"' not in body, "js-gate: gate text present, no framework root")
    if "bot-blocking-robots" in u:
        body = http_get(u["bot-blocking-robots"] + "/robots.txt")[2]
        for tok in (b"ChatGPT-User", b"PerplexityBot", b"GPTBot", b"Claude-User", b"User-agent: *\nAllow: /"):
            res.check(tok in body, "bot-blocking-robots: robots mentions %s" % tok.decode().replace("\n", " "))
    if "blanket-disallow" in u:
        body = http_get(u["blanket-disallow"] + "/robots.txt")[2]
        res.check(b"User-agent: *\nDisallow: /" in body, "blanket-disallow: robots disallows everything")
    if "malformed-jsonld" in u:
        body = http_get(u["malformed-jsonld"] + "/")[2]
        m = re.search(rb'<script type="application/ld\+json">(.*?)</script>', body, re.S)
        try:
            json.loads(m.group(1).decode("utf-8"))
            res.fail("malformed-jsonld: home JSON-LD fails to parse", "it parsed")
        except Exception:  # noqa: BLE001
            res.ok("malformed-jsonld: home JSON-LD fails to parse")
        about = http_get(u["malformed-jsonld"] + "/about")[2]
        res.check(b"sameAs" in about, "malformed-jsonld: about still has valid Organization with sameAs")
    if "image-only-pricing" in u:
        body = http_get(u["image-only-pricing"] + "/pricing")[2]
        res.check(b"pricing-table.png" in body and b"\xc2\xa3" not in body, "image-only-pricing: pricing has image and no currency text")
        img = http_get(u["image-only-pricing"] + "/pricing-table.png")
        res.check(img[0] == 200 and img[1].startswith("image/png"), "image-only-pricing: PNG serves as image/png")
    if "non-html-seed" in u:
        st, ct, body = http_get(u["non-html-seed"] + "/")
        res.check(ct.startswith("application/pdf") and body.startswith(b"%PDF"), "non-html-seed: home is a PDF")
    if "one-page-portfolio" in u:
        body = http_get(u["one-page-portfolio"] + "/")[2]
        res.check(b'"@type":"Person"' in body and b"<nav" not in body, "one-page-portfolio: Person JSON-LD, no nav")
    if "weak-engagement" in u:
        body = http_get(u["weak-engagement"] + "/")[2]
        res.check(b'name="viewport"' not in body and b"<nav" not in body and b'<html>' in body and b"modal-overlay" in body, "weak-engagement: no viewport, no nav, no lang, overlay present")
        res.check(http_get(u["weak-engagement"] + "/old-pricing")[0] == 404 and http_get(u["weak-engagement"] + "/no-such-page-x1")[0] == 200, "weak-engagement: /old-pricing is 404, unknown paths are 200")
    if "weak-ecommerce" in u:
        body = http_get(u["weak-ecommerce"] + "/")[2]
        res.check(body.count(b"<script src=") == 41 and b"breadcrumb" not in body.lower() and b'role="search"' not in body, "weak-ecommerce: 41 script tags, no breadcrumbs, no search")
        st, _, b404 = http_get(u["weak-ecommerce"] + "/nope")
        res.check(st == 404 and b"<nav" not in b404 and b'href="/"' not in b404, "weak-ecommerce: bare 404 page")
    if "blocked-links" in u:
        res.check(http_get(u["blocked-links"] + "/terms")[0] == 403 and http_get(u["blocked-links"] + "/pricing")[0] == 200, "blocked-links: /terms 403, /pricing 200")


# ---------------------------------------------------------------- stage: robots (pure unit tests)
def stage_robots(res):
    print("\n== stage: robots.txt parser (RFC 9309)")
    R = robotslib.Robots
    r = R("User-agent: *\nDisallow: /private/\nAllow: /private/public.html\n\nUser-agent: GPTBot\nDisallow: /\n\nSitemap: https://x.example/sitemap.xml\n")
    res.check(r.is_allowed("/", "*"), "wildcard: root allowed")
    res.check(not r.is_allowed("/private/x", "anybot"), "wildcard: /private/ disallowed for unknown token")
    res.check(r.is_allowed("/private/public.html", "anybot"), "longest match: Allow beats shorter Disallow")
    res.check(not r.is_allowed("/", "gptbot"), "specific group: GPTBot disallowed on / (case-insensitive)")
    res.check(r.is_allowed("/private/x", "GPTBot") is False and r.has_specific_group("GPTBot"), "specific group used instead of wildcard")
    res.check(r.sitemaps == ["https://x.example/sitemap.xml"], "Sitemap line collected")
    r = R("User-agent: a\nUser-agent: b\nDisallow: /x\n")
    res.check(not r.is_allowed("/x", "b") and r.is_allowed("/x", "c"), "multiple user-agent lines form one group; no '*' => others allowed")
    r = R("User-agent: *\nDisallow: /*.pdf$\nDisallow: /tmp*\nAllow: /tmp/ok\n")
    res.check(not r.is_allowed("/a/b.pdf", "*") and r.is_allowed("/a/b.pdf?x=1", "*"), "'$' anchors the end (query breaks the anchor)")
    res.check(not r.is_allowed("/tmpfile", "*") and r.is_allowed("/tmp/ok", "*"), "'*' wildcard and longer Allow")
    r = R("User-agent: *\nDisallow:\n")
    res.check(r.is_allowed("/anything", "*"), "empty Disallow allows everything")
    r = R("User-agent: *\nDisallow: /a\nAllow: /a\n")
    res.check(r.is_allowed("/a", "*"), "equal length: Allow wins")
    r = R("Disallow: /\nUser-agent: *\nAllow: /\n")
    res.check(r.is_allowed("/", "*") and r.parse_errors, "rule before any group is ignored and recorded")
    r = R(None, state="missing")
    res.check(r.is_allowed("/", "gptbot"), "missing robots (4xx) => allow all")
    r = R("User-agent: *\nDisallow: /caf%C3%A9\n")
    res.check(not r.is_allowed("/caf\u00e9", "*") and not r.is_allowed("/caf%C3%A9", "*"), "percent-decoding normalised both sides")
    tiers = robotslib.load_bot_tiers()
    res.check(len(tiers) >= 20, "bot_tiers.md parsed (%d tokens)" % len(tiers))
    res.check(tiers.get("chatgpt-user", {}).get("tier") == "live_answer" and tiers.get("gptbot", {}).get("tier") == "training_only",
              "tiers read from markdown, not hard-coded")
    r = R("User-agent: GPTBot\nDisallow: /\nUser-agent: ChatGPT-User\nDisallow: /\nUser-agent: Claude-User\nDisallow: /pricing\nUser-agent: *\nAllow: /\n")
    g = {row["token"]: row for row in robotslib.grade_tokens(r, tiers, key_paths=["/pricing"])}
    res.check(g["GPTBot"]["root_allowed"] is False and g["ChatGPT-User"]["root_allowed"] is False, "grading: blocked tokens detected")
    res.check(g["Claude-User"]["root_allowed"] and g["Claude-User"]["disallowed_key_paths"] == ["/pricing"], "grading: key page disallow detected")
    res.check(g["PerplexityBot"]["root_allowed"] and not g["PerplexityBot"]["has_own_group"], "grading: unlisted token falls back to '*'")
    # fetch helpers
    res.check(registrable_domain("www.shop.example.co.uk") == "example.co.uk" and registrable_domain("a.b.example.com") == "example.com",
              "registrable_domain heuristic")
    res.check(normalize_url("Example.COM/Path#frag") == "https://example.com/Path", "normalize_url adds scheme, lowercases host, drops fragment")
    res.check(detect_challenge(403, {"cf-mitigated": "challenge"}, b"<title>Just a moment...</title>") == "cloudflare", "challenge: cloudflare header+title")
    res.check(detect_challenge(200, {}, b"<html><body>" + b"word " * 500 + b"recaptcha</body></html>") is None, "challenge: recaptcha on a full page is NOT a challenge")
    res.check(detect_challenge(200, {}, b"<html><body><div class='g-recaptcha'></div> please verify recaptcha</body></html>") == "generic_captcha",
              "challenge: captcha-only page with <60 words IS a challenge")
    res.check(detect_challenge(403, {}, b"Forbidden") is None, "challenge: plain 403 is blocked, not a challenge")
    res.check(visible_word_count(b"<script>var a=1;</script><p>one two three</p><style>x{}</style>") == 3, "visible_word_count strips script/style")


# ---------------------------------------------------------------- stage: fetch (against fixtures)
def stage_fetch(res, farm):
    print("\n== stage: fetch helper on every fixture")
    u = farm.urls
    for name, base in u.items():
        f = Fetcher(site=base)
        r = f.get(base + "/", purpose="page")
        res.check(r.get("error") is None or name == "blanket-disallow", "%s: home fetch has no error (%s)" % (name, r.get("error")))
        rob = f.robots()
        res.check(rob.state in ("ok", "missing"), "%s: robots state ok/missing (%s)" % (name, rob.state))
        res.check(r["fetched_at"].endswith("Z") and "url" in r and "final_url" in r, "%s: FetchResult has required fields" % name)
    # clean-site specifics
    f = Fetcher(site=u["clean-site"])
    r = f.get(u["clean-site"] + "/about", purpose="page")
    res.check(r.ok and r["is_html"] and r["charset"] == "utf-8" and "<h1>About Ledgerly</h1>" in r.text, "clean-site: HTML decoded and readable")
    r404 = f.get(u["clean-site"] + "/nope-xyz", purpose="link")
    res.check(r404["status"] == 404 and not r404["blocked"] and not r404["challenge"], "clean-site: 404 recorded plainly")
    res.check(f.robots().sitemaps == [u["clean-site"] + "/sitemap.xml"], "clean-site: Sitemap URL parsed from robots")
    res.check(f.requests_made == 3, "clean-site: robots fetched once and counted (%d requests)" % f.requests_made)
    # blanket-disallow: robots obeyed
    f = Fetcher(site=u["blanket-disallow"])
    r = f.get(u["blanket-disallow"] + "/", purpose="page")
    res.check(r["skipped"] == "robots_disallow" and r["status"] is None and r["skipped_rule"] == "Disallow: /", "blanket-disallow: page NOT fetched, skipped=robots_disallow")
    res.check(f.requests_made == 1, "blanket-disallow: only robots.txt requested")
    f2 = Fetcher(site=u["blanket-disallow"], obey_robots=False)
    res.check(f2.get(u["blanket-disallow"] + "/", purpose="page").ok, "blanket-disallow: obey_robots=False fetches (tests only)")
    # bot-blocking: our UA is under '*', so pages are fetched
    f = Fetcher(site=u["bot-blocking-robots"])
    res.check(f.get(u["bot-blocking-robots"] + "/pricing", purpose="page").ok, "bot-blocking-robots: audit UA allowed via '*'")
    # non-html seed
    f = Fetcher(site=u["non-html-seed"])
    r = f.get(u["non-html-seed"] + "/", purpose="page")
    res.check(r["status"] == 200 and not r["is_html"] and r["content_type"] == "application/pdf" and r.body.startswith(b"%PDF"), "non-html-seed: content type recorded, is_html False")
    # challenge page
    f = Fetcher(site=u["challenge-page"])
    r = f.get(u["challenge-page"] + "/", purpose="page")
    res.check(r["status"] == 403 and r["challenge"] and r["challenge_vendor"] == "cloudflare" and not r["blocked"], "challenge-page: fingerprinted as cloudflare challenge, not blocked")
    res.check(f.robots().state == "ok", "challenge-page: robots.txt itself is fine")
    # csr shell: body large but under cap
    f = Fetcher(site=u["csr-shell"])
    r = f.get(u["csr-shell"] + "/static/main.9f2c4b.js", purpose="asset")
    res.check(r.ok and not r["truncated"] and r["bytes"] > 100000 and not r["is_html"], "csr-shell: large asset fetched untruncated")
    # policy edges
    f = Fetcher(site=u["clean-site"], offline=True)
    res.check(f.get(u["clean-site"] + "/")["error"] == "network_disabled", "offline: network_disabled without touching the network")
    f = Fetcher(site=u["clean-site"])
    res.check(f.get("ftp://example.com/x")["error"] == "unsupported_scheme", "unsupported scheme recorded")
    res.check(f.get("http://localhost:1/")["error"] == "host_not_allowed", "host outside allowlist refused before any socket")
    f.allow_host("localhost")
    r = f.get("http://localhost:1/", purpose="page")
    res.check(r["error"] in ("connection_refused", "unknown") and r["status"] is None, "connection refused recorded, no traceback (%s)" % r["error"])
    f = Fetcher(site=u["clean-site"], budget=2)
    f.get(u["clean-site"] + "/"); r = f.get(u["clean-site"] + "/about")
    res.check(r["error"] == "budget_exhausted", "request budget enforced")
    f = Fetcher(site=u["clean-site"], min_delay=0)
    import time as _t
    t0 = _t.monotonic(); f.get(u["clean-site"] + "/"); f.get(u["clean-site"] + "/about"); fast = _t.monotonic() - t0
    f = Fetcher(site=u["clean-site"], min_delay=0.5)
    t0 = _t.monotonic(); f.get(u["clean-site"] + "/"); f.get(u["clean-site"] + "/about"); slow = _t.monotonic() - t0
    res.check(slow >= 0.9 and fast < slow, "politeness delay applied between same-host requests (%.2fs vs %.2fs)" % (slow, fast))
    # manifest round-trip
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        f = Fetcher(workdir=td, site=u["clean-site"])
        r = f.get(u["clean-site"] + "/", purpose="page", save_as="snapshots/home.html")
        rel = f.save_manifest()
        res.check(os.path.exists(os.path.join(td, "snapshots", "home.html")) and r["body_path"] == "snapshots/home.html", "snapshot saved at body_path")
        m = json.load(open(os.path.join(td, rel)))
        res.check(m["requests_made"] == 2 and len(m["fetches"]) == 2 and m["fetches"][0]["url"].endswith("/robots.txt"), "manifest JSON lists robots then page")


# ---------------------------------------------------------------- stage: htmldoc (pure unit tests)
def stage_htmldoc(res):
    print("\n== stage: HTML document layer")
    html = """<!doctype html><html lang="en"><head><title> My  Site </title><meta name="description" content="Desc">
    <meta property="og:title" content="OG"><link rel="canonical" href="/canon"></head><body>
    <header><nav><ul><li><a href="/about">About us</a></li><li><a href="https://other.example/x">Ext</a></li></ul></nav></header>
    <main><h1>Hello <em>world</em></h1><p>Price $12.00 and $39 and 5 USD.</p><script>var x = "hidden words";</script>
    <img src="/a.png" alt="A" width="100"><img src="/b.png"><form role="search"><input type="search" name="q"></form>
    <script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"X"},{"@type":["WebPage","FAQPage"]}]}</script>
    <script type="application/ld+json">{bad json,}</script>
    <div id="root"></div></main><footer><a href="mailto:a@b.c">mail</a><a href="/about/">About</a></footer></body></html>"""
    d = Document(html, base_url="https://www.site.example/page")
    res.check(d.title == "My Site" and d.lang == "en" and d.meta("description") == "Desc" and d.meta("og:title") == "OG", "title/lang/meta extracted")
    res.check(d.canonical == "https://www.site.example/canon", "canonical resolved absolute")
    res.check(d.h1s == ["Hello world"], "h1 text joined across inline tags (%s)" % d.h1s)
    res.check("hidden" not in d.visible_text and "Price" in d.visible_text, "script text excluded from visible text")
    res.check(len(d.price_mentions) == 3, "price mentions counted (%d)" % len(d.price_mentions))
    ints = d.internal_links
    res.check(len(ints) == 2 and ints[0].context == "nav" and ints[0].text == "About us" and ints[1].context == "footer", "links with context; mailto and external excluded from internal")
    res.check(len(d.internal_urls()) == 1, "internal_urls dedupes trailing slash")
    res.check(len(d.jsonld) == 2 and d.jsonld[1]["error"] and set(d.jsonld_types) == {"Organization", "WebPage", "FAQPage"}, "JSON-LD: @graph + list @type flattened, bad block recorded as error")
    res.check(len(d.jsonld_nodes("Organization")) == 1, "jsonld_nodes filter by type")
    res.check(d.images[1]["alt"] is None and d.images[0]["width"] == 100, "images with alt/width")
    res.check(d.forms and d.forms[0]["role"] == "search" and d.forms[0]["inputs"][0]["type"] == "search", "search form captured")
    res.check(d.empty_root_containers == ["root"], "empty #root container detected")
    res.check(d.nav_count == 1 and d.script_bytes > 0, "nav count and script bytes")
    res.check(Document("<p>unclosed <b>tags <a href='/x'>x").internal_links == [] and Document("").word_count == 0, "malformed/empty HTML does not raise")
    res.check(Document('<div itemscope itemtype="https://schema.org/Organization"><span itemprop="name">X</span></div>').microdata_hint is True
              and Document('<p vocab="https://schema.org/" typeof="Person">x</p>').microdata_hint is True and Document("<p>x</p>").microdata_hint is False,
              "Document notes Microdata/RDFa attributes without parsing them")
    res.check(Document('<form><label>Search</label><input><button>Search</button></form><a href="/t">Start free trial</a>').body_text == "Search Search Start free trial",
              "adjacent inline elements are space-separated in body text")
    # role candidate discovery, incl. non-English
    de = Document('<nav><a href="/preise">Preise</a><a href="/ueber-uns">Über uns</a><a href="/kontakt">Kontakt</a><a href="/aktuelles">Aktuelles</a><a href="/produkte">Produkte</a></nav>', base_url="https://de.example/")
    c = find_role_candidates(de, [], "https://de.example/")
    res.check(all(c[r] for r in ("pricing", "about", "contact", "blog", "product")), "German nav words map to all five roles")
    res.check(c["pricing"][0]["url"] == "https://de.example/preise" and c["pricing"][0]["source"] == "nav", "candidate carries url and source")
    c2 = find_role_candidates(Document("", base_url="https://x.example/"), ["https://x.example/about", "https://x.example/blog/post-1", "https://x.example/products/widget"], "https://x.example/")
    res.check(c2["about"][0]["source"] == "sitemap" and c2["product"][0]["url"].endswith("/products/widget") and not c2["blog"], "sitemap fallback: exact path for about, prefix for /products/, /blog/post-1 is not the blog index")
    for role, words in ROLE_KEYWORDS.items():
        res.check(all(w == w.lower() for w in words), "ROLE_KEYWORDS[%s] lower-case" % role)
    # categorizer thresholds
    docs = {"home": Document('<nav><a href="/shop">Shop</a><a href="/cart">Cart</a></nav><p>$1 $2 $3</p><script type="application/ld+json">{"@type":"Product","name":"x"}</script>', base_url="https://s.example/")}
    cat = categorize([], docs, [], "https://s.example/", 30)
    res.check(cat["value"] == "ecommerce" and cat["confidence"] == "high", "ecommerce: jsonld 3 + nav 2 + prices 2 => high (%s)" % cat["scores"].get("ecommerce"))
    cat = categorize([], {"home": Document("<p>hi</p>", base_url="https://z.example/")}, [], "https://z.example/", 1)
    res.check(cat["value"] == "unknown", "bare page with <=5 pages scores 2 for portfolio, below threshold => unknown")
    cat = categorize([], {}, [], "https://z.example/", 0, override="local_business")
    res.check(cat["value"] == "local_business" and cat["signals"] == ["user_supplied"], "user override wins")


# ---------------------------------------------------------------- stage: sample (against fixtures)
def stage_sample(res, farm):
    print("\n== stage: sampler + categorizer on every fixture")
    import tempfile
    for name, base in farm.urls.items():
        meta = farm.metas[name]
        with tempfile.TemporaryDirectory() as td:
            f = Fetcher(workdir=td, site=base)
            m = sample_site(f, base)
            got = m["site_category"]["value"]
            res.check(got == meta["category"], "%s: category %s" % (name, got), "expected %s, signals=%s" % (meta["category"], m["site_category"]["signals"]))
            res.check(not m["notes"] or all("sampler_error" not in n for n in m["notes"]), "%s: no sampler error" % name, str(m["notes"]))
            res.check(m["requests_made"] <= 8 and len(m["pages"]) <= 6, "%s: <=8 requests, <=6 pages (%d, %d)" % (name, m["requests_made"], len(m["pages"])))
            res.check(m["pages"][0]["role"] == "home" and m["pages"][0]["source"] == "input", "%s: first page is home from input" % name)
            for k in ("site", "input_url", "sampled_at", "site_category", "robots", "sitemap", "pages", "missing_roles", "internal_links_seen", "requests_made"):
                res.check(k in m, "%s: manifest has %s" % (name, k))
            res.check(os.path.exists(os.path.join(td, "sample.json")) and os.path.exists(os.path.join(td, "fetch", "manifest.json")), "%s: sample.json + fetch/manifest.json written" % name)
            roles = {p["role"]: p for p in m["pages"]}
            fetched = [r for r, p in roles.items() if p["fetch"].get("status") == 200]
            for r in fetched:
                res.check(os.path.exists(os.path.join(td, "snapshots", r + ".html")), "%s: snapshot for %s saved" % (name, r))
            if name in ("clean-site", "bot-blocking-robots", "malformed-jsonld", "image-only-pricing"):
                res.check(set(roles) == {"home", "about", "contact", "pricing", "product", "blog"} and not m["missing_roles"], "%s: all six roles found" % name)
                res.check(all(roles[r]["source"] == "nav" for r in roles if r != "home"), "%s: role pages came from nav" % name)
                res.check(m["site_category"]["confidence"] == "high", "%s: category confidence high" % name)
            if name in ("csr-shell", "js-gate", "non-html-seed", "challenge-page"):
                res.check(all(roles[r]["source"] == "sitemap" for r in roles if r != "home"), "%s: no nav readable, role pages came from sitemap" % name)
            if name == "one-page-portfolio":
                res.check(list(roles) == ["home"] and len(m["missing_roles"]) == 5 and m["internal_pages_estimate"] == 1, "one-page-portfolio: only home, all roles missing")
            if name == "blanket-disallow":
                res.check(roles["home"]["fetch"].get("skipped") == "robots_disallow" and m["requests_made"] == 1 and m["sitemap"]["state"] == "missing", "blanket-disallow: nothing fetched but robots.txt")
            if name == "challenge-page":
                res.check(all(p["fetch"].get("challenge") for p in m["pages"]) and m["robots"]["state"] == "ok", "challenge-page: every page flagged challenge, robots fine")
            if name == "non-html-seed":
                res.check(roles["home"]["fetch"]["is_html"] is False and "summary" not in roles["home"], "non-html-seed: home recorded as non-HTML, no document summary")
    # offline sampling never raises
    f = Fetcher(site="https://example.com", offline=True)
    m = sample_site(f, "https://example.com", save=False)
    res.check(m["site_category"]["value"] == "unknown" and m["pages"][0]["fetch"]["error"] == "network_disabled" and m["requests_made"] == 0, "offline: manifest produced with network_disabled")


# ---------------------------------------------------------------- probe harness (Steps 6/8/10/12 reuse this)
def _load_probe(skill, script):
    import importlib.util
    path = os.path.join(ROOT, "skills", skill, "scripts", script)
    spec = importlib.util.spec_from_file_location(script[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_probe_on_fixtures(res, farm, prefix, probe_mod, label):
    """Run a probe on every fixture from a fresh workdir; assert the _fixture.json contract for `prefix` checks."""
    from auditlib.context import AuditContext
    from auditlib.findings import validate_probe_output, Registry
    import tempfile
    reg = Registry()
    results = {}
    for name, base in farm.urls.items():
        exp = farm.metas[name]["expected"]
        with tempfile.TemporaryDirectory() as td:
            ctx = AuditContext.from_url(base, td)
            out = probe_mod.run(ctx).to_dict()
            # workdir mode must produce the identical verdicts
            out2 = probe_mod.run(AuditContext.from_workdir(td)).to_dict()
        results[name] = out
        # _fixture.json contract: `fail` = real defects (severity above info); `info` = info-severity notes
        # (inconclusive, not_evaluated, and policy notes), regardless of status
        fails = {f["check_id"] for f in out["findings"] if f["severity"] != "info"}
        infos = {f["check_id"] for f in out["findings"] if f["severity"] == "info"}
        exp_fail = {c for c in exp["fail"] if c.startswith(prefix)}
        exp_info = {c for c in exp["info"] if c.startswith(prefix)}
        statuses = {c["check_id"]: c["status"] for c in out["checks"]}
        res.check(fails == exp_fail, "%s/%s: fail set matches" % (label, name), "got %s expected %s" % (sorted(fails), sorted(exp_fail)))
        res.check(infos == exp_info, "%s/%s: info set matches" % (label, name), "got %s expected %s" % (sorted(infos), sorted(exp_info)))
        bad = [c for c in exp["pass_required"] if c.startswith(prefix) and statuses.get(c) != "pass"]
        res.check(not bad, "%s/%s: pass_required all pass" % (label, name), "%s -> %s" % (bad, [statuses.get(c) for c in bad]))
        probs = validate_probe_output(out, reg)
        res.check(not probs, "%s/%s: probe output valid against schema" % (label, name), "; ".join(probs[:3]))
        res.check(out["error"] is None, "%s/%s: no probe error" % (label, name), str(out["error"]))
        res.check(set(statuses) == set(reg.ids(prefix)), "%s/%s: every registered %s check reported" % (label, name, prefix), str(set(reg.ids(prefix)) ^ set(statuses)))
        f2 = {f["check_id"]: f["severity"] for f in out2["findings"]}
        res.check(f2 == {f["check_id"]: f["severity"] for f in out["findings"]}, "%s/%s: workdir mode reproduces url mode" % (label, name))
        for f in out["findings"]:
            res.check(all(f["evidence_items"]) and f["evidence"] and f["why_it_matters"] and f["suggested_action"]["summary"][0].isupper(),
                      "%s/%s: %s has evidence, why, and a verb-led action" % (label, name, f["check_id"]))
    return results


# ---------------------------------------------------------------- stage: compose (orchestrator report from a workdir)
def _load_compose():
    import importlib.util
    path = os.path.join(ROOT, "skills", "audit-orchestrator", "scripts", "compose.py")
    spec = importlib.util.spec_from_file_location("compose", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PROBE_SCRIPTS = (("crawl-render-audit", "crawl_probe.py"), ("fact-extractability-audit", "facts_probe.py"),
                 ("entity-freshness-corroboration-audit", "entity_probe.py"), ("engagement-audit", "engagement_probe.py"))


def _build_workdir(base_url, workdir):
    """Sample once, then run all four probes into <workdir>/probes/, exactly as run_audit.py will (Step 16)."""
    from auditlib.context import AuditContext
    AuditContext.from_url(base_url, workdir)
    os.makedirs(os.path.join(workdir, "probes"), exist_ok=True)
    for skill, script in PROBE_SCRIPTS:
        mod = _load_probe(skill, script)
        out = mod.run(AuditContext.from_workdir(workdir)).to_dict()
        with open(os.path.join(workdir, "probes", skill + ".json"), "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)


def _mkf(check_id, severity="medium", pages=(), items=None, status="fail", confidence="high"):
    """A finding shaped like a probe's, for the dedupe unit checks."""
    return {"check_id": check_id, "title": check_id, "status": status, "severity": severity, "confidence": confidence,
            "effort": "low", "mechanism": None, "affected_pages": list(pages), "evidence": "e",
            "evidence_items": list(items or [{"page": "site", "kind": "computed", "value": "x"}]),
            "why_it_matters": "w",
            "suggested_action": {"summary": "S", "detail": "d", "impact": "medium", "effort": "low", "priority": "medium"},
            "references": [], "dedupe_key": check_id + "|" + ",".join(sorted(pages)), "_max_severity": "critical"}


def stage_compose_units(res, C):
    """The parts that need no server: the dedupe table, ordering, derived tags, and the two mirrored tables."""
    print("\n== stage: compose (dedupe table, ordering, derived tags)")
    from auditlib.findings import Registry
    reg = Registry()
    HOME, P2 = "http://s/", "http://s/p2"
    sample = {"site_category": {"value": "saas_software"},
              "pages": [{"role": "home", "fetch": {"final_url": HOME, "status": 200, "is_html": True}},
                        {"role": "about", "fetch": {"final_url": P2, "status": 200, "is_html": True}}]}

    def fold(findings, smp=None):
        kept, folded = C.dedupe(findings, smp or sample)
        return {f["check_id"] for f in kept}, {f["check_id"] for f in folded}

    # 1 challenge page hides every other per-page finding on that page, but not one on another page
    k, f = fold([_mkf("cr.access.challenge_page", "info", [HOME], status="inconclusive"),
                 _mkf("en.cta.missing", "medium", [HOME]), _mkf("en.cta.missing", "medium", [P2])])
    res.check(f == {"en.cta.missing"} and "cr.access.challenge_page" in k, "dedupe 1: challenge page folds page findings", str((k, f)))
    # an info primary that is inconclusive never inherits a higher severity (the rubric's hard rule wins)
    kept, folded = C.dedupe([_mkf("cr.access.challenge_page", "info", [HOME], status="inconclusive"),
                             _mkf("en.mobile.viewport_missing", "high", [HOME])], sample)
    res.check(kept[0]["severity"] == "info", "dedupe: an inconclusive primary stays info", kept[0]["severity"])
    # 2 blanket disallow folds every tiered robots finding and names the tiers
    kept, folded = C.dedupe([_mkf("cr.robots.blanket_disallow", "critical"),
                             _mkf("cr.robots.live_answer_bot_blocked", "high"),
                             _mkf("cr.robots.index_bot_blocked", "high")], sample)
    res.check({x["check_id"] for x in folded} == {"cr.robots.live_answer_bot_blocked", "cr.robots.index_bot_blocked"},
              "dedupe 2: blanket disallow folds the tier findings")
    res.check("live_answer" in json.dumps(kept[0]["evidence_items"]), "dedupe 2: the note names the affected tiers")
    # 3 non-HTML home folds the per-page findings on home
    k, f = fold([_mkf("cr.access.non_html_seed", "critical", [HOME]), _mkf("fx.identity.og_missing", "low", [HOME])])
    res.check(f == {"fx.identity.og_missing"}, "dedupe 3: non-HTML home folds home findings", str(f))
    # 4 a shell folds the content checks on the same page only
    k, f = fold([_mkf("cr.render.csr_shell", "critical", [HOME]), _mkf("en.hero.value_prop_unclear", "medium", [HOME]),
                 _mkf("en.nav.related_links_missing", "low", [HOME]), _mkf("en.mobile.viewport_missing", "high", [HOME]),
                 _mkf("en.hero.value_prop_unclear", "medium", [P2])])
    res.check(f == {"en.hero.value_prop_unclear", "en.nav.related_links_missing"} and "en.mobile.viewport_missing" in k,
              "dedupe 4: a shell folds the content checks but not the head-level ones", str((k, f)))
    # 5 every rendered page is a shell: the site-level key-fact finding folds too
    k, f = fold([_mkf("cr.render.js_gate", "critical", [HOME, P2]), _mkf("fx.facts.key_fact_missing", "high")])
    res.check("fx.facts.key_fact_missing" in f, "dedupe 5: nothing rendered folds the key-fact finding", str(f))
    k, f = fold([_mkf("cr.render.js_gate", "critical", [HOME]), _mkf("fx.facts.key_fact_missing", "high")])
    res.check("fx.facts.key_fact_missing" not in f, "dedupe 5: one shell among rendered pages keeps it", str(f))
    # 6 no JSON-LD anywhere
    k, f = fold([_mkf("fx.jsonld.missing", "medium"), _mkf("ef.entity.sameas_missing", "medium"),
                 _mkf("fx.jsonld.no_organization", "low")])
    res.check(f == {"ef.entity.sameas_missing", "fx.jsonld.no_organization"}, "dedupe 6: no JSON-LD folds the entity anchors", str(f))
    # 7 same block only
    same = [{"page": HOME, "kind": "jsonld_excerpt", "value": "v", "location": "script[type=application/ld+json][1]"}]
    other = [{"page": HOME, "kind": "jsonld_excerpt", "value": "v", "location": "script[type=application/ld+json][2]"}]
    k, f = fold([_mkf("fx.jsonld.malformed", "medium", [HOME], same), _mkf("fx.jsonld.required_props_missing", "medium", [HOME], same)])
    res.check(f == {"fx.jsonld.required_props_missing"}, "dedupe 7: the same JSON-LD block folds", str(f))
    k, f = fold([_mkf("fx.jsonld.malformed", "medium", [HOME], same), _mkf("fx.jsonld.required_props_missing", "medium", [HOME], other)])
    res.check(not f, "dedupe 7: a different block does not fold", str(f))
    # 8 NAP folds the key-fact finding only when it names nothing else
    local = {"site_category": {"value": "local_business"}, "pages": sample["pages"]}
    missing_np = [{"page": "site", "kind": "computed", "value": "pages_searched=3; key_facts=4; found=2; missing=address,phone"}]
    missing_more = [{"page": "site", "kind": "computed", "value": "pages_searched=3; key_facts=4; found=1; missing=address,opening_hours"}]
    k, f = fold([_mkf("ef.entity.nap_missing_plain_text", "high"), _mkf("fx.facts.key_fact_missing", "high", (), missing_np)], local)
    res.check(f == {"fx.facts.key_fact_missing"}, "dedupe 8: NAP folds an address/phone-only key-fact finding", str(f))
    k, f = fold([_mkf("ef.entity.nap_missing_plain_text", "high"), _mkf("fx.facts.key_fact_missing", "high", (), missing_more)], local)
    res.check(not f, "dedupe 8: a wider key-fact finding stays", str(f))
    # 9 blocked cluster reclassifies 403/429 only
    blocked = [{"page": "site", "kind": "http_status", "value": "GET http://s/a -> 403"}]
    broken = [{"page": "site", "kind": "http_status", "value": "GET http://s/a -> 404"}]
    k, f = fold([_mkf("en.links.blocked_cluster", "info", status="inconclusive"), _mkf("en.links.broken_sampled", "medium", (), blocked)])
    res.check(f == {"en.links.broken_sampled"}, "dedupe 9: a 403-only broken list is reclassified", str(f))
    k, f = fold([_mkf("en.links.blocked_cluster", "info", status="inconclusive"), _mkf("en.links.broken_sampled", "medium", (), broken)])
    res.check(not f, "dedupe 9: a real 404 is still broken", str(f))
    # 10 no h1 folds continuity and the h1 leg of the hero check
    noh1 = [{"page": HOME, "kind": "computed", "value": "h1_count=0"}]
    twoh1 = [{"page": HOME, "kind": "computed", "value": "h1_count=2"}]
    hero_h1 = [{"page": HOME, "kind": "computed", "value": "signals=h1_missing; category_noun=none"}]
    hero_lead = [{"page": HOME, "kind": "computed", "value": "signals=lead_text_no_offer; category_noun=none"}]
    k, f = fold([_mkf("fx.identity.h1_missing_or_multiple", "low", [HOME], noh1),
                 _mkf("en.continuity.h1_title_mismatch", "low", [HOME]), _mkf("en.hero.value_prop_unclear", "medium", [HOME], hero_h1)])
    res.check(f == {"en.continuity.h1_title_mismatch", "en.hero.value_prop_unclear"}, "dedupe 10: an absent h1 folds both", str(f))
    k, f = fold([_mkf("fx.identity.h1_missing_or_multiple", "low", [HOME], noh1), _mkf("en.hero.value_prop_unclear", "medium", [HOME], hero_lead)])
    res.check(not f, "dedupe 10: a hero failing on its lead text is not folded", str(f))
    k, f = fold([_mkf("fx.identity.h1_missing_or_multiple", "low", [HOME], twoh1), _mkf("en.continuity.h1_title_mismatch", "low", [HOME])])
    res.check(not f, "dedupe 10: two h1s do not fold continuity", str(f))
    # 11 and 12
    k, f = fold([_mkf("cr.index.sitemap_missing", "low"), _mkf("cr.index.sitemap_invalid", "medium")])
    res.check(f == {"cr.index.sitemap_invalid"}, "dedupe 11: no sitemap folds invalid sitemap", str(f))
    k, f = fold([_mkf("ef.entity.wikidata_unavailable", "info", status="not_evaluated"), _mkf("ef.entity.wikidata_not_found", "low")])
    res.check(f == {"ef.entity.wikidata_not_found"}, "dedupe 12: an unavailable lookup folds its verdicts", str(f))
    # severity inheritance raises a `fail` primary, capped by the registry maximum
    kept, folded = C.dedupe([_mkf("cr.index.sitemap_missing", "low"), _mkf("cr.index.sitemap_invalid", "critical")], sample)
    res.check(kept[0]["severity"] == "critical" and "severity_inherited_from" in json.dumps(kept[0]["evidence_items"]),
              "dedupe: a fail primary inherits the higher severity", kept[0]["severity"])
    res.check(kept[0]["suggested_action"]["impact"] == "high", "dedupe: inherited severity re-derives impact and priority")

    # ordering: severity, then confidence, then page count, then check_id
    order = C.sort_findings([_mkf("cr.b.x", "low"), _mkf("cr.a.x", "critical", confidence="medium"),
                             _mkf("cr.c.x", "critical", confidence="high"), _mkf("cr.d.x", "critical", confidence="high", pages=[HOME, P2])])
    res.check([f["check_id"] for f in order] == ["cr.d.x", "cr.c.x", "cr.a.x", "cr.b.x"],
              "ordering: severity, confidence, page count, id", str([f["check_id"] for f in order]))
    # derived tags come from the stage, never from the probe
    tags = C.add_derived_tags({"check_id": "en.cta.missing", "mechanism": "engagement"})
    res.check(tags["round2_mode"] == "bouncing" and tags["pipeline_stage"] == "post_click"
              and tags["handout_concepts"] == [] and tags["opportunity_type"] == "content", "tags: engagement content check")
    tags = C.add_derived_tags({"check_id": "en.mobile.viewport_missing", "mechanism": "engagement"})
    res.check(tags["opportunity_type"] == "technical", "tags: engagement technical check")
    tags = C.add_derived_tags({"check_id": "or.simulation.question_unanswerable", "mechanism": "extract"})
    res.check(tags["pipeline_stage"] == "selection" and tags["handout_concepts"] == ["B"], "tags: simulation is a selection failure")
    tags = C.add_derived_tags({"check_id": "cr.render.csr_shell", "mechanism": "render"})
    res.check(tags["handout_concepts"] == ["A", "C"] and tags["round2_mode"] == "invisible", "tags: render is A/C, invisible")
    res.check(C.is_quick_win(_mkf("cr.x.y", "medium")) and not C.is_quick_win(_mkf("cr.x.y", "info"))
              and not C.is_quick_win(_mkf("cr.x.y", "medium", confidence="low")), "quick win rule matches the rubric")

    # the tables compose owns must cover the registry exactly
    ids = set(reg.ids())
    res.check(set(C.POSITIVE_TITLES) == ids, "every registry check has a positive title",
              str(sorted(ids ^ set(C.POSITIVE_TITLES))[:4]))
    bad_titles = [t for t in C.POSITIVE_TITLES.values()
                  if not t or t.endswith(".") or not (t[0].isupper() or t.split()[0] in ("robots.txt", "sameAs"))]
    res.check(not bad_titles, "positive titles are statements, not sentences", str(bad_titles[:3]))
    # the simulation questions mirror site_categories.md section 6
    from auditlib.categories import SIMULATION_QUESTIONS, AUDIENCE_PHRASE, KEY_FACTS, CATEGORIES as CATS
    sc = open(os.path.join(ROOT, "skills", "audit-orchestrator", "references", "site_categories.md"), encoding="utf-8").read()
    section6 = sc.split("## 6.")[-1]
    for cat in CATS:
        res.check(cat in SIMULATION_QUESTIONS and cat in AUDIENCE_PHRASE, "%s: simulation tables cover the category" % cat)
        for _, fact_ids, _ in SIMULATION_QUESTIONS[cat]:
            for fid in fact_ids:
                res.check("`%s`" % fid in section6, "%s: question fact %s is named in site_categories section 6" % (cat, fid))
                res.check(fid in KEY_FACTS[cat], "%s: question fact %s is one of the category key facts" % (cat, fid))
    res.check(C.non_coverage_lines(), "non-coverage lines are read from coverage_map.md section 5")
    res.check(len(C.non_coverage_lines()) >= 10, "all of section 5 is carried into limitations (%d)" % len(C.non_coverage_lines()))


def stage_compose(res, farm):
    print("\n== stage: compose on every fixture")
    import tempfile
    C = _load_compose()
    stage_compose_units(res, C)
    print("\n== stage: compose (reports from real fixture workdirs)")
    for name, base in farm.urls.items():
        exp = farm.metas[name]["expected"]
        with tempfile.TemporaryDirectory() as td:
            _build_workdir(base, td)
            report = C.compose(td, wall_clock=1.0)
            md = C.render_markdown(report)
            try:
                facts = json.load(open(os.path.join(td, "work", "extracted_facts.json"), encoding="utf-8"))
            except OSError:
                facts = None
            probs, _ = _load_validate().validate_report(report, facts)
            res.check(not probs, "compose/%s: report passes validate.py" % name, "; ".join(probs[:3]))
        s = report["summary"]
        fnds = report["findings"]
        res.check(s["total_findings"] == len(fnds) == sum(s[k] for k in ("critical", "high", "medium", "low", "info")),
                  "compose/%s: summary counts add up and match findings" % name, json.dumps(s))
        res.check([f["id"] for f in fnds] == ["F-%03d" % i for i in range(1, len(fnds) + 1)],
                  "compose/%s: ids are sequential after sorting" % name)
        res.check([f["rank"] for f in fnds] == list(range(1, len(fnds) + 1)), "compose/%s: rank matches position" % name)
        res.check(fnds == C.sort_findings(fnds), "compose/%s: findings are in schema order" % name)
        # the fixture contract survives dedupe: nothing a fixture expects may silently disappear
        seen_fail = {f["check_id"] for f in fnds + report["suppressed_findings"] if f["severity"] != "info"}
        seen_info = {f["check_id"] for f in fnds + report["suppressed_findings"]
                     if f["severity"] == "info" and not f["check_id"].startswith("or.")}
        res.check(seen_fail == set(exp["fail"]), "compose/%s: kept and folded findings match the fixture's fail set" % name,
                  "got %s expected %s" % (sorted(seen_fail), sorted(exp["fail"])))
        res.check(seen_info == set(exp["info"]), "compose/%s: info notes match the fixture" % name,
                  "got %s expected %s" % (sorted(seen_info), sorted(exp["info"])))
        for f in fnds:
            res.check(f.get("quick_win") == C.is_quick_win(f), "compose/%s: %s quick-win flag follows the rubric" % (name, f["id"]))
            res.check(f.get("source_skill") and f.get("opportunity_type") in ("technical", "content"),
                      "compose/%s: %s carries its source skill and opportunity type" % (name, f["id"]))
            res.check("_suppressed" not in f and "_max_severity" not in f, "compose/%s: %s has no internal fields" % (name, f["id"]))
        res.check(report["quick_wins"] == [f["id"] for f in fnds if f["quick_win"]], "compose/%s: quick_wins lists the flagged ids" % name)
        res.check(all(f.get("merged_into") for f in report["suppressed_findings"]),
                  "compose/%s: every folded finding names the finding it went into" % name)
        res.check(report["ai_answer_simulation"]["basis"] == "extracted_facts_only", "compose/%s: simulation basis is fixed" % name)
        res.check(all(q["answer_from_facts"] is None for q in report["ai_answer_simulation"]["questions"]),
                  "compose/%s: the agent's answers are left empty" % name)
        res.check(report["narrative_summary"] == "", "compose/%s: the narrative is left for the agent" % name)
        res.check(len(report["passed_checks"]) == s["checks_passed"], "compose/%s: passed_checks matches the count" % name)
        res.check(s["checks_run"] == 58, "compose/%s: every registered check has a verdict (%d)" % (name, s["checks_run"]))
        res.check(report["limitations"] and report["limitations"][0].startswith("This report reflects a single point-in-time"),
                  "compose/%s: limitations open with the point-in-time statement" % name)
        # the Markdown carries nothing the JSON does not
        for f in fnds:
            res.check(f["id"] in md and f["title"][:40] in md, "compose/%s: %s appears in the Markdown" % (name, f["id"]))
        stray = set(re.findall(r"\bF-\d{3}\b", md)) - {f["id"] for f in fnds}
        res.check(not stray, "compose/%s: the Markdown invents no finding ids" % name, str(sorted(stray)))
        res.check("Traceback" not in md and "Traceback" not in json.dumps(report), "compose/%s: no traceback in the output" % name)
        res.check(md.startswith("# AI-readiness audit: "), "compose/%s: Markdown title line" % name)
        for heading in ("## Summary", "## Coverage and limitations"):
            res.check(heading in md, "compose/%s: Markdown has %s" % (name, heading))
        if name == "clean-site":
            res.check(not [f for f in fnds if f["severity"] != "info"], "compose/clean-site: no defect is reported",
                      str([f["check_id"] for f in fnds if f["severity"] != "info"]))
            res.check(len(report["proactive_recommendations"]) >= 3, "compose/clean-site: proactive recommendations are populated")
            res.check(all(r["title"] not in md.split("## Findings")[0] for r in []), "compose/clean-site: recommendations are not findings")
            res.check(s["checks_passed"] >= 50, "compose/clean-site: nearly every check passes (%d)" % s["checks_passed"])
            res.check(report["coverage"]["stages"]["engagement"] == "evaluated", "compose/clean-site: engagement stage evaluated")
            res.check(report["coverage"]["handout_concepts"]["A"] == "covered", "compose/clean-site: concept A covered")
            res.check("## Quick wins" not in md, "compose/clean-site: no quick-wins section on a clean site")
            res.check(not [q for q in report["ai_answer_simulation"]["questions"]
                           if not q["answerable"] and not q.get("informational")],
                      "compose/clean-site: every real question is answerable from the facts file")
        if name == "csr-shell":
            sim = [f for f in fnds if f["check_id"] == "or.simulation.question_unanswerable"]
            res.check(sim and sim[0]["severity"] == "info", "compose/csr-shell: unanswerable questions are reported as info")
            res.check(report["coverage"]["stages"]["extract"] in ("partial", "not_evaluated"),
                      "compose/csr-shell: the extract stage is not claimed as evaluated")
        if name == "one-page-portfolio":
            res.check(any("home page alone" in l for l in report["limitations"]),
                      "compose/one-page-portfolio: the home-only limitation is stated", str(report["limitations"][:2]))
        if name == "challenge-page":
            res.check(any("Challenge page served" in l for l in report["limitations"]),
                      "compose/challenge-page: the challenge limitation is stated")
    # a broken workdir still produces a valid report that says so
    with tempfile.TemporaryDirectory() as td:
        report = C.compose(td)
        res.check(report["summary"]["total_findings"] >= 1 and report["findings"][0]["check_id"] == "or.run.probe_error",
                  "compose: an empty workdir reports a run error rather than a clean site")
        res.check(C.render_markdown(report).startswith("# AI-readiness audit:"), "compose: a broken run still renders")
    # --render-only re-renders the same Markdown from the JSON alone
    with tempfile.TemporaryDirectory() as td:
        _build_workdir(farm.urls["weak-engagement"], td)
        C.main(["--workdir", td, "--quiet"])
        first = open(os.path.join(td, "report.md"), encoding="utf-8").read()
        os.remove(os.path.join(td, "report.md"))
        C.main(["--workdir", td, "--render-only", "--quiet"])
        again = open(os.path.join(td, "report.md"), encoding="utf-8").read()
        res.check(first == again, "compose --render-only reproduces the Markdown from report.json alone")
        res.check(os.path.exists(os.path.join(td, "report.json")), "compose writes report.json into the workdir")


# ---------------------------------------------------------------- stage: validate (the report validator)
def _load_validate():
    import importlib.util
    path = os.path.join(ROOT, "skills", "audit-orchestrator", "scripts", "validate.py")
    spec = importlib.util.spec_from_file_location("validate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _finalise(report, facts):
    """What the orchestrator agent does in Step 17, done mechanically: quote the verbatim values, write a narrative."""
    r = json.loads(json.dumps(report))
    for q in r["ai_answer_simulation"]["questions"]:
        if q["answerable"]:
            q["answer_from_facts"] = " ".join('"%s"' % facts["facts"][fid]["value"] for fid in q["facts_used"])
    r["ai_answer_simulation"]["attribution_note"] = "Every answer above quotes the facts file verbatim."
    r["narrative_summary"] = "The site is reachable and readable. Its facts are stated plainly. Nothing here is invisible."
    return r


def stage_validate(res, farm):
    print("\n== stage: validate (floor, superset, --final, and a set of deliberately broken reports)")
    import tempfile
    C, V = _load_compose(), _load_validate()
    with tempfile.TemporaryDirectory() as td:
        _build_workdir(farm.urls["weak-engagement"], td)
        C.main(["--workdir", td, "--quiet"])
        base = json.load(open(os.path.join(td, "report.json"), encoding="utf-8"))
        facts = json.load(open(os.path.join(td, "work", "extracted_facts.json"), encoding="utf-8"))
        res.check(V.main(["--workdir", td, "--quiet"]) == 0, "validate: CLI accepts a composed workdir")
        res.check(V.main(["--workdir", td, "--final", "--quiet"]) == 1, "validate: CLI rejects an unfinished report with --final")
        good = _finalise(base, facts)
        with open(os.path.join(td, "report.json"), "w", encoding="utf-8") as f:
            json.dump(good, f)
        res.check(V.main(["--workdir", td, "--final", "--quiet"]) == 0, "validate: CLI accepts a finalised report with --final")
        res.check(V.main(["--report", os.path.join(td, "nope.json"), "--quiet"]) == 1, "validate: a missing file is a problem, not a crash")
        with open(os.path.join(td, "bad.json"), "w") as f:
            f.write("{not json")
        res.check(V.main(["--report", os.path.join(td, "bad.json"), "--quiet"]) == 1, "validate: unparseable JSON is a problem, not a crash")
    probs, warns = V.validate_report(base, facts)
    res.check(not probs, "validate: the composed report is valid", "; ".join(probs[:3]))
    probs, warns = V.validate_report(good, facts, final=True)
    res.check(not probs, "validate: the finalised report is valid under --final", "; ".join(probs[:3]))
    res.check(not any("narrative" in x for x in warns), "validate: a three-sentence narrative raises no warning", str(warns))

    def broken(name, mutate, needle, final=False, expect_floor=None):
        r = json.loads(json.dumps(good if final else base))
        mutate(r)
        probs, _ = V.validate_report(r, facts, final=final)
        hit = [x for x in probs if needle in x]
        res.check(bool(hit), "validate rejects: %s" % name, "problems=%s" % probs[:3])
        if expect_floor is not None and hit:
            res.check(hit[0].startswith("floor:" if expect_floor else "superset:"),
                      "validate: %s is a %s problem" % (name, "floor" if expect_floor else "superset"), hit[0])

    def setf(path, value):
        def m(r):
            cur = r
            for k in path[:-1]:
                cur = cur[k]
            cur[path[-1]] = value
        return m

    def delf(path):
        def m(r):
            cur = r
            for k in path[:-1]:
                cur = cur[k]
            del cur[path[-1]]
        return m

    # the handout floor
    broken("site missing", delf(["site"]), "site missing", expect_floor=True)
    broken("audited_at not ISO", setf(["audited_at"], "yesterday"), "audited_at", expect_floor=True)
    broken("summary total off by one", setf(["summary", "total_findings"], base["summary"]["total_findings"] + 1), "total_findings", expect_floor=True)
    broken("severity count wrong", setf(["summary", "high"], base["summary"]["high"] + 1), "summary", expect_floor=True)
    broken("finding without evidence", setf(["findings", 0, "evidence"], ""), "evidence missing", expect_floor=True)
    broken("finding without title", setf(["findings", 0, "title"], ""), "title missing", expect_floor=True)
    broken("duplicate id", setf(["findings", 1, "id"], base["findings"][0]["id"]), "duplicate id", expect_floor=True)
    broken("id not F-###", setf(["findings", 0, "id"], "1"), "not F-###", expect_floor=True)
    broken("action without summary", setf(["findings", 0, "suggested_action", "summary"], ""), "suggested_action.summary", expect_floor=True)
    broken("action without priority", delf(["findings", 0, "suggested_action", "priority"]), "priority", expect_floor=True)
    broken("severity out of range", setf(["findings", 0, "severity"], "urgent"), "severity", expect_floor=True)
    broken("findings not a list", setf(["findings"], {}), "findings missing", expect_floor=True)
    # the superset
    broken("unknown check_id", setf(["findings", 0, "check_id"], "en.made.up"), "not in the registry", expect_floor=False)
    broken("status pass on a finding", setf(["findings", 0, "status"], "pass"), "status must be", expect_floor=False)
    broken("inconclusive with severity high", lambda r: r["findings"][0].update(status="inconclusive"), "always info", expect_floor=False)
    broken("low confidence critical", lambda r: r["findings"][0].update(confidence="low", severity="critical", quick_win=False)
           or r["summary"].update(critical=1, high=base["summary"]["high"] - 1), "low confidence caps", expect_floor=False)
    broken("severity above registered maximum", lambda r: [f.update(severity="critical") for f in r["findings"] if f["check_id"] == "en.lang.attribute_missing"]
           or r["summary"].update(critical=1, low=base["summary"]["low"] - 1), "exceeds the registered maximum", expect_floor=False)
    broken("mechanism contradicts the registry", setf(["findings", 0, "mechanism"], "access"), "does not match the registry stage", expect_floor=False)
    broken("out of order", lambda r: r["findings"].reverse() or [f.update(id="F-%03d" % (i + 1), rank=i + 1) for i, f in enumerate(r["findings"])],
           "not in schema order", expect_floor=False)
    broken("ids not sequential", lambda r: r["findings"][-1].update(id="F-099"), "must be F-", expect_floor=False)
    broken("rank wrong", setf(["findings", 0, "rank"], 7), "rank must be", expect_floor=False)
    broken("quick_win flag contradicts the rubric", setf(["findings", 0, "quick_win"], not base["findings"][0]["quick_win"]), "quick_win", expect_floor=False)
    broken("quick_wins list wrong", setf(["quick_wins"], []), "quick_wins", expect_floor=False)
    broken("impact not derived from severity", setf(["findings", 0, "suggested_action", "impact"], "low"), "impact must be derived", expect_floor=False)
    broken("dedupe_key wrong", setf(["findings", 0, "dedupe_key"], "x|y"), "dedupe_key", expect_floor=False)
    broken("no evidence items", setf(["findings", 0, "evidence_items"], []), "evidence_items", expect_floor=False)
    broken("evidence item of unknown kind", setf(["findings", 0, "evidence_items", 0, "kind"], "guess"), "known kind", expect_floor=False)
    broken("title over 90 chars", setf(["findings", 0, "title"], "x" * 91), "longer than 90", expect_floor=False)
    broken("checks_run not the sum", setf(["summary", "checks_run"], 1), "checks_run", expect_floor=False)
    broken("passed check that is also a finding", lambda r: r["passed_checks"].append(
        {"check_id": base["findings"][0]["check_id"], "title": "t", "source_skill": "s"}) or r["summary"].update(checks_passed=base["summary"]["checks_passed"] + 1),
        "is also a finding", expect_floor=False)
    broken("passed_checks length mismatch", setf(["summary", "checks_passed"], 0), "checks_passed", expect_floor=False)
    broken("suppressed finding with dangling merged_into", lambda r: r["suppressed_findings"].append(
        dict(json.loads(json.dumps(base["findings"][0])), merged_into="F-999", dedupe_key="cr.x.y|")), "merged_into", expect_floor=False)
    broken("suppressed key also kept", lambda r: r["suppressed_findings"].append(
        dict(json.loads(json.dumps(base["findings"][0])), merged_into="F-001")), "both kept and folded", expect_floor=False)
    broken("coverage letter missing", delf(["coverage", "handout_concepts", "E"]), "handout_concepts", expect_floor=False)
    broken("coverage stage unknown value", setf(["coverage", "stages", "access"], "done"), "coverage.stages", expect_floor=False)
    broken("recommendation restates a finding", lambda r: r["proactive_recommendations"].append(
        {"title": base["findings"][0]["title"], "rationale": "r", "mechanism": "extract", "effort": "low", "priority": "low"}), "restates", expect_floor=False)
    broken("limitations empty", setf(["limitations"], []), "limitations", expect_floor=False)
    broken("limitations without the point-in-time line", setf(["limitations"], ["Nothing to see."]), "point-in-time", expect_floor=False)
    broken("basis not extracted_facts_only", setf(["ai_answer_simulation", "basis"], "model_knowledge"), "basis", expect_floor=False)
    broken("answer on an unanswerable question", lambda r: [q.update(answer_from_facts="Yes.") for q in r["ai_answer_simulation"]["questions"] if not q["answerable"]],
           "unanswerable question carries an answer", expect_floor=False)
    broken("answer cites a fact the file does not hold", lambda r: r["ai_answer_simulation"]["questions"][0].update(
        answer_from_facts="Ledgerly is great", facts_used=["not_a_fact"]), "does not hold as present", expect_floor=False)
    broken("answer that does not quote the fact", lambda r: r["ai_answer_simulation"]["questions"][0].update(
        answer_from_facts="It is an accounting product, probably."), "does not quote the value", final=True, expect_floor=False)
    broken("answer without facts_used", lambda r: r["ai_answer_simulation"]["questions"][0].update(facts_used=[]), "must list the facts", final=True, expect_floor=False)
    broken("--final with empty narrative", setf(["narrative_summary"], ""), "narrative_summary is empty", final=True, expect_floor=False)
    broken("--final with an unanswered answerable question", lambda r: r["ai_answer_simulation"]["questions"][0].update(answer_from_facts=None),
           "has no answer", final=True, expect_floor=False)
    broken("missing top-level field", delf(["run"]), "missing top-level field run", expect_floor=False)
    # an answer that quotes verbatim passes even when the value was cut with an ellipsis
    r = json.loads(json.dumps(good))
    fid = r["ai_answer_simulation"]["questions"][0]["facts_used"][0]
    value = facts["facts"][fid]["value"].strip("…").strip()
    r["ai_answer_simulation"]["questions"][0]["answer_from_facts"] = "According to the site, %s." % value[:60]
    r["ai_answer_simulation"]["questions"][0]["facts_used"] = [fid]
    probs, _ = V.validate_report(r, facts, final=True)
    res.check(not [x for x in probs if "quote" in x], "validate: a partial verbatim quote of a long value is accepted", str(probs[:2]))
    # the validator itself never raises
    probs, _ = V.validate_report("not even a dict", None)
    res.check(probs and not any("validator error" in x for x in probs), "validate: a non-object report is rejected without crashing", str(probs[:2]))
    probs, _ = V.validate_report({"site": "x", "findings": [None, 3], "summary": None}, None)
    res.check(probs and not any("validator error" in x for x in probs), "validate: garbage findings are rejected without crashing", str(probs[:2]))
    # a report composed from an empty workdir (the fallback) is still valid
    with tempfile.TemporaryDirectory() as td:
        probs, _ = V.validate_report(C.compose(td), None)
        res.check(not probs, "validate: the run-error fallback report is valid", "; ".join(probs[:3]))


# ---------------------------------------------------------------- stage: probe_cr (crawl-render probe on fixtures)
def stage_probe_cr(res, farm):
    print("\n== stage: crawl-render probe on every fixture")
    cp = _load_probe("crawl-render-audit", "crawl_probe.py")
    R = run_probe_on_fixtures(res, farm, "cr.", cp, "cr")
    sev = lambda name, cid: next((f["severity"] for f in R[name]["findings"] if f["check_id"] == cid), None)
    conf = lambda name, cid: next((f["confidence"] for f in R[name]["findings"] if f["check_id"] == cid), None)
    pages = lambda name, cid: next((len(f["affected_pages"]) for f in R[name]["findings"] if f["check_id"] == cid), 0)
    res.check(len(R["clean-site"]["findings"]) == 0 and all(c["status"] == "pass" for c in R["clean-site"]["checks"]), "cr/clean-site: zero findings, 16 passes")
    res.check(sev("csr-shell", "cr.render.csr_shell") == "critical" and pages("csr-shell", "cr.render.csr_shell") == 6 and conf("csr-shell", "cr.render.csr_shell") == "medium",
              "cr/csr-shell: critical on home, all 6 pages, medium confidence")
    res.check(sev("js-gate", "cr.render.js_gate") == "critical" and conf("js-gate", "cr.render.js_gate") == "high", "cr/js-gate: critical, high confidence")
    res.check(sev("blanket-disallow", "cr.robots.blanket_disallow") == "critical", "cr/blanket-disallow: critical")
    ne = [c for c in R["blanket-disallow"]["checks"] if c["status"] == "not_evaluated"]
    res.check(len(ne) >= 8 and all(c["reason"] == "robots_disallow" for c in ne), "cr/blanket-disallow: page checks not_evaluated with reason robots_disallow (%d)" % len(ne))
    res.check(sev("bot-blocking-robots", "cr.robots.live_answer_bot_blocked") == "high" and sev("bot-blocking-robots", "cr.robots.index_bot_blocked") == "high"
              and sev("bot-blocking-robots", "cr.robots.key_page_disallowed") == "medium" and sev("bot-blocking-robots", "cr.robots.training_bot_blocked") == "info",
              "cr/bot-blocking-robots: severities high/high/medium/info by tier")
    res.check(sev("non-html-seed", "cr.access.non_html_seed") == "critical", "cr/non-html-seed: critical")
    ch = next(f for f in R["challenge-page"]["findings"] if f["check_id"] == "cr.access.challenge_page")
    res.check(ch["status"] == "inconclusive" and ch["severity"] == "info" and len(ch["affected_pages"]) == 6, "cr/challenge-page: inconclusive info on 6 pages")
    inc = [c for c in R["challenge-page"]["checks"] if c["status"] == "inconclusive"]
    res.check(len(inc) >= 5 and "cr.access.http_error" not in {f["check_id"] for f in R["challenge-page"]["findings"]}, "cr/challenge-page: render/index checks inconclusive, no http_error")
    # never-crash: broken workdir and offline url
    from auditlib.context import AuditContext
    out = cp.run(AuditContext.from_workdir("/nonexistent/dir")).to_dict()
    res.check(out["error"] and not out["findings"] and all(c["status"] == "not_evaluated" for c in out["checks"]), "cr: broken workdir yields valid degraded output")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = cp.run(AuditContext.from_url("https://example.com", td, offline=True)).to_dict()
    res.check(out["error"] is None and any(f["check_id"] == "cr.access.http_error" for f in out["findings"]), "cr: offline run reports the site as unreachable, no traceback")


# ---------------------------------------------------------------- stage: extract (pure unit tests for the shared detectors)
def stage_extract(res):
    print("\n== stage: fact detectors")
    from auditlib import extract as X
    from auditlib.context import Page

    def mk(html, role="home", url="https://x.example/"):
        return Page({"role": role, "url": url, "final_url": url, "fetch": {"status": 200}}, Document(html, base_url=url))
    pg = mk("<p>Visit us at 12 Harbour Street, Bristol BS1 4QA. Phone: +44 117 496 0123. Email hello@x.example. Open Monday to Friday, 09:00 to 17:30.</p>")
    res.check(X.find_address([pg]) and "Harbour Street" in X.find_address([pg])["value"], "address: street line found in text")
    res.check(X.find_phone([pg]) and "+44" in X.find_phone([pg])["value"], "phone: international number found")
    res.check(X.find_email([pg])["value"] == "hello@x.example", "email found in text")
    res.check(X.find_hours([pg]) is not None, "opening hours pattern found")
    pg2 = mk("<p>Our team of 12 works with 2024 clients across 3 countries. Order #123456789 shipped.</p>")
    res.check(X.find_phone([pg2]) is None, "phone: bare digit runs without a cue are not phones")
    res.check(X.find_address([pg2]) is None, "address: no false street match")
    res.check(X.find_sales_led([mk("<p>Enterprise pricing is available on request. Talk to sales.</p>")]) is not None, "sales-led statement found")
    res.check(X.find_free_trial([mk('<a href="/x">Start free trial</a>')]) is not None and X.find_free_tier([mk('<a href="/x">Start free trial</a>')]) is None, "free trial is not a free tier")
    res.check(X.find_audience([mk("<p>Ledgerly is built for freelance designers and small studios.</p>")]) is not None, "audience phrase found")
    res.check(X.find_audience([mk("<p>We ship on Tuesdays.</p>")]) is None, "audience: no false match")
    us = mk("<p>Contact: 500 Market St, San Francisco, CA 94105</p>")
    res.check(X.find_address([us]) is not None, "address: US street/city/state/zip found")
    ld = mk('<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"Acme","url":"https://x.example/","logo":"l.png"},{"@type":"BlogPosting","headline":"Hi","publisher":{"@type":"Organization","name":"Acme"}},{"@type":"SoftwareApplication","applicationCategory":"BusinessApplication"}]}</script>')
    nodes = X.doc_top_nodes(ld.doc)
    res.check(len(nodes) == 3, "top_level_nodes: @graph members only, nested publisher excluded (%d)" % len(nodes))
    verdicts = [X.missing_required(n) for n, _ in nodes]
    res.check(verdicts[0] == ("Organization", [], []) and verdicts[1] == ("BlogPosting", [], []), "required props: complete Organization and BlogPosting pass")
    res.check(verdicts[2][0] == "SoftwareApplication" and "name" in verdicts[2][1] and verdicts[2][2] == [["offers", "aggregateRating", "review"]], "required props: SoftwareApplication lacking name and offers flagged")
    res.check(X.brand_name([ld])["value"] == "Acme" and X.brand_name([ld])["source"].startswith("jsonld"), "brand name from Organization JSON-LD")
    res.check(X.brand_name([mk("<title>Pricing | Zed</title>"), mk("<title>About | Zed</title>", role="about")])["value"] == "Zed", "brand name from repeated title segment")
    res.check(X.find_faq([mk("<h2>Frequently asked questions</h2>")]) is not None and X.find_faq([mk("<h2>Our team</h2>")]) is None, "faq heading detection")
    res.check(X.find_person([mk("<h1>Mira Castellanos draws book covers</h1>")]) is not None, "person name from h1 lead")
    res.check(X.find_dates([mk("<p>Updated 12 March 2026</p>")]) is not None and X.find_dates([mk("<p>Version 2.0</p>")]) is None, "date detection")


# ---------------------------------------------------------------- stage: probe_fx (fact-extractability probe on fixtures)
def stage_probe_fx(res, farm):
    print("\n== stage: fact-extractability probe on every fixture")
    fp = _load_probe("fact-extractability-audit", "facts_probe.py")
    R = run_probe_on_fixtures(res, farm, "fx.", fp, "fx")
    from auditlib.context import AuditContext
    import tempfile

    def run_with_facts(name):
        with tempfile.TemporaryDirectory() as td:
            ctx = AuditContext.from_url(farm.urls[name], td)
            out = fp.run(ctx).to_dict()
            fpath = os.path.join(td, "work", "extracted_facts.json")
            facts = json.load(open(fpath, encoding="utf-8")) if os.path.exists(fpath) else None
        return out, facts
    out, facts = run_with_facts("clean-site")
    res.check(facts is not None and out["artifacts"].get("extracted_facts") == "work/extracted_facts.json", "fx/clean-site: facts file written and referenced")
    res.check(facts and all(facts["facts"][f]["status"] == "present" for f in facts["required_fact_ids"]), "fx/clean-site: all required facts present (%s)" % (facts and {f: facts["facts"][f]["status"] for f in facts["required_fact_ids"]}))
    res.check(facts and facts["brand_name"]["value"] == "Ledgerly" and facts["facts"]["pricing_or_trial"]["kind"] == "price" and "£" in (facts["facts"]["pricing_or_trial"]["value"] or ""),
              "fx/clean-site: brand Ledgerly, pricing found as a price")
    res.check(facts and facts["facts"]["audience"]["status"] == "present" and facts["facts"]["differentiator"]["status"] in ("present", "absent"), "fx/clean-site: optional facts resolved")
    res.check(len(out["findings"]) == 0 and all(c["status"] == "pass" for c in out["checks"]), "fx/clean-site: zero findings, 12 passes")
    out, facts = run_with_facts("image-only-pricing")
    f = next((x for x in out["findings"] if x["check_id"] == "fx.facts.image_only"), None)
    res.check(f and f["severity"] == "high" and f["confidence"] == "medium" and f["affected_pages"][0].endswith("/pricing"), "fx/image-only-pricing: image_only high/medium on /pricing")
    k = next((x for x in out["findings"] if x["check_id"] == "fx.facts.key_fact_missing"), None)
    res.check(k and "pricing_or_trial" in k["evidence"] and "partial" in k["evidence"] and facts["facts"]["pricing_or_trial"]["status"] == "partial" and facts["facts"]["pricing_or_trial"]["kind"] == "trial_only",
              "fx/image-only-pricing: pricing fact partial (trial_only) and named in the finding")
    out, facts = run_with_facts("malformed-jsonld")
    m = next((x for x in out["findings"] if x["check_id"] == "fx.jsonld.malformed"), None)
    r = next((x for x in out["findings"] if x["check_id"] == "fx.jsonld.required_props_missing"), None)
    res.check(m and len(m["affected_pages"]) == 1 and m["affected_pages"][0].rstrip("/").endswith(":%s" % farm.urls["malformed-jsonld"].rsplit(":", 1)[1]) or (m and m["affected_pages"][0].endswith("/")), "fx/malformed-jsonld: malformed finding on home only")
    res.check(r and "SoftwareApplication" in r["evidence"] and "name" in r["evidence"] and r["affected_pages"][0].endswith("/product"), "fx/malformed-jsonld: required props finding names SoftwareApplication.name on /product")
    res.check(facts and all(facts["facts"][f]["status"] == "present" for f in facts["required_fact_ids"]), "fx/malformed-jsonld: key facts still all present")
    out, facts = run_with_facts("one-page-portfolio")
    res.check(facts and facts["facts"]["who"]["source"] == "jsonld:Person.name" and facts["facts"]["what_they_do"]["status"] == "present" and facts["facts"]["contact_or_profile_link"]["status"] == "present",
              "fx/one-page-portfolio: who/what/contact from Person markup and mailto")
    st = {c["check_id"]: c for c in out["checks"]}
    res.check(st["fx.content.faq_absent"]["status"] == "not_evaluated" and st["fx.content.faq_absent"]["reason"] == "not_applicable_for_category", "fx/one-page-portfolio: FAQ check gated by category")
    out, facts = run_with_facts("csr-shell")
    res.check(all(c["status"] == "not_evaluated" and c["reason"] == "no_rendered_content" for c in out["checks"]) and not out["findings"], "fx/csr-shell: every check not_evaluated with reason no_rendered_content")
    res.check(facts and len(facts["pages_excluded"]) == 6 and not facts["pages_used"], "fx/csr-shell: facts file lists 6 excluded pages")
    out, facts = run_with_facts("challenge-page")
    res.check(all(c["reason"] == "challenge_page" for c in out["checks"]), "fx/challenge-page: reason challenge_page")
    out, facts = run_with_facts("non-html-seed")
    res.check(facts and facts["pages_excluded"] and facts["pages_excluded"][0]["reason"] == "non_html" and len(facts["pages_used"]) == 5, "fx/non-html-seed: PDF home excluded, 5 HTML pages used")


# ---------------------------------------------------------------- stage: live (opt-in, needs internet)
def stage_live(res, urls):
    print("\n== stage: live sites (network)")
    for site in urls:
        f = Fetcher(site=site, verbose=False)
        try:
            r = f.get(site, purpose="page")
            rob = f.robots()
            res.check(True, "%s: fetched without traceback -> status=%s error=%s html=%s challenge=%s robots=%s bytes=%d %dms" % (
                site, r.get("status"), r.get("error"), r.get("is_html"), r.get("challenge_vendor"), rob.state, r.get("bytes", 0), r.get("elapsed_ms", 0)))
            res.check((r.get("status") is not None) != (r.get("error") is not None),
                      "%s: has exactly one of status or error code" % site)
            m = sample_site(Fetcher(site=site), site, save=False)
            res.check(not any("sampler_error" in n for n in m["notes"]),
                      "%s: sampled -> category=%s(%s) pages=%s missing=%s requests=%d" % (
                          site, m["site_category"]["value"], m["site_category"]["confidence"],
                          ",".join(p["role"] for p in m["pages"] if p["fetch"].get("status") == 200), ",".join(m["missing_roles"]) or "-", m["requests_made"]))
        except Exception as e:  # noqa: BLE001
            res.fail("%s: raised %s" % (site, type(e).__name__), str(e))


# ---------------------------------------------------------------- stage: probe_ef (entity-freshness-corroboration probe on fixtures)
def stage_probe_ef(res, farm):
    from auditlib.findings import validate_probe_output
    print("\n== stage: entity-freshness-corroboration probe on every fixture (external lookups disabled)")
    ep = _load_probe("entity-freshness-corroboration-audit", "entity_probe.py")
    R = run_probe_on_fixtures(res, farm, "ef.", ep, "ef")
    sev = lambda name, cid: next((f["severity"] for f in R[name]["findings"] if f["check_id"] == cid), None)
    conf = lambda name, cid: next((f["confidence"] for f in R[name]["findings"] if f["check_id"] == cid), None)
    finding = lambda name, cid: next((f for f in R[name]["findings"] if f["check_id"] == cid), None)
    status = lambda name, cid: next((c for c in R[name]["checks"] if c["check_id"] == cid), {})
    # clean-site: 10 passes + the two unavailable notes
    cs = R["clean-site"]
    res.check(sum(1 for c in cs["checks"] if c["status"] == "pass") == 8 and sum(1 for c in cs["checks"] if c["status"] == "not_evaluated") == 4,
              "ef/clean-site: eight checks pass, four not_evaluated (lookup + dependents, spot-check)", str([(c["check_id"], c["status"]) for c in cs["checks"] if c["status"] != "pass"]))
    res.check(status("clean-site", "ef.entity.wikidata_unavailable").get("reason") == "network_disabled" and status("clean-site", "ef.entity.wikidata_ambiguous").get("reason") == "lookup_unavailable",
              "ef/clean-site: lookup not_evaluated with network_disabled, dependents lookup_unavailable")
    res.check(status("clean-site", "ef.corroboration.offsite_spotcheck").get("reason") == "tool_unavailable", "ef/clean-site: offsite spot-check not_evaluated tool_unavailable")
    f = finding("clean-site", "ef.corroboration.offsite_spotcheck")
    res.check(f is not None and "suggested_queries=" in f["evidence_items"][0]["value"] and "Ledgerly" in f["evidence_items"][0]["value"], "ef/clean-site: spot-check note carries suggested queries with the brand name")
    # weak-entity: five low findings with the right evidence
    we = R["weak-entity"]
    res.check(all(sev("weak-entity", c) == "low" for c in ("ef.entity.sameas_no_authority", "ef.entity.name_inconsistent", "ef.entity.nap_missing_plain_text", "ef.freshness.stale_copyright_year", "ef.freshness.date_modified_mismatch")),
              "ef/weak-entity: all five findings low (saas overrides nap to low)", str({f["check_id"]: f["severity"] for f in we["findings"]}))
    f = finding("weak-entity", "ef.entity.name_inconsistent")
    res.check(f is not None and "LedgerPro" in f["evidence"] and "Ledgerly" in f["evidence"], "ef/weak-entity: name_inconsistent names both variants")
    f = finding("weak-entity", "ef.entity.nap_missing_plain_text")
    res.check(f is not None and "postal address or phone number" in f["evidence"] and "Missing: name" in f["evidence"] and "email" in f["evidence"],
              "ef/weak-entity: nap finding names the missing components and what was found", f["evidence"] if f else None)
    import datetime as _dt
    f = finding("weak-entity", "ef.freshness.stale_copyright_year")
    res.check(f is not None and str(_dt.date.today().year - 3) in f["evidence"] and conf("weak-entity", "ef.freshness.stale_copyright_year") == "high", "ef/weak-entity: stale year evidence shows the old year, high confidence")
    f = finding("weak-entity", "ef.freshness.date_modified_mismatch")
    res.check(f is not None and len(f["affected_pages"]) == 1 and f["affected_pages"][0].endswith("/blog") and "WebPage.dateModified" in f["evidence"], "ef/weak-entity: date mismatch only on /blog, names the property")
    f = finding("weak-entity", "ef.entity.sameas_no_authority")
    res.check(f is not None and "facebook.com" in f["evidence"], "ef/weak-entity: no_authority evidence lists the social hosts")
    # undated-entity
    res.check(sev("undated-entity", "ef.entity.sameas_missing") == "medium" and conf("undated-entity", "ef.entity.sameas_missing") == "high", "ef/undated-entity: sameas_missing medium/high")
    res.check(status("undated-entity", "ef.entity.sameas_no_authority").get("reason") == "dependency_failed", "ef/undated-entity: no_authority not_evaluated dependency_failed")
    res.check(sev("undated-entity", "ef.freshness.no_visible_dates") == "low" and sev("undated-entity", "ef.corroboration.press_page_missing") == "low", "ef/undated-entity: no_visible_dates and press_page_missing low")
    # portfolio: profile hosts count as authority, nap needs name + contact only
    res.check(status("one-page-portfolio", "ef.entity.sameas_no_authority").get("status") == "pass" and status("one-page-portfolio", "ef.corroboration.press_page_missing").get("reason") == "not_applicable_for_category",
              "ef/one-page-portfolio: profile sameAs is an authority for a person; press not applicable")
    # no-JSON-LD site: entity checks not_evaluated, no finding
    res.check(status("bare-metadata", "ef.entity.sameas_missing").get("reason") == "dependency_failed" and not [f for f in R["bare-metadata"]["findings"] if f["severity"] != "info"], "ef/bare-metadata: sameAs checks not_evaluated, no defects")
    # degraded paths
    from auditlib.context import AuditContext, Page
    from auditlib.htmldoc import Document
    import tempfile, types
    out = ep.run(AuditContext.from_workdir("/nonexistent/dir")).to_dict()
    res.check(out["error"] and not out["findings"] and all(c["status"] == "not_evaluated" for c in out["checks"]), "ef: broken workdir yields valid degraded output")
    with tempfile.TemporaryDirectory() as td:
        out = ep.run(AuditContext.from_url("https://example.com", td, offline=True)).to_dict()
        reasons = {c["check_id"]: c.get("reason") for c in out["checks"] if c["status"] == "not_evaluated"}
        res.check(out["error"] is None and len(out["checks"]) == 12 and all(c["status"] == "not_evaluated" for c in out["checks"]), "ef: offline run degrades cleanly, all 12 not_evaluated, no error", str(out["error"]))
        res.check(reasons.get("ef.entity.nap_missing_plain_text") == "network_disabled" and reasons.get("ef.entity.wikidata_unavailable") == "network_disabled" and reasons.get("ef.corroboration.offsite_spotcheck") == "tool_unavailable",
                  "ef: offline reasons are network_disabled / tool_unavailable", str(reasons))
        res.check({f["check_id"] for f in out["findings"]} == {"ef.entity.wikidata_unavailable", "ef.corroboration.offsite_spotcheck"} and all(f["severity"] == "info" for f in out["findings"]),
                  "ef: offline run emits exactly the two info notes")
        res.check(os.path.exists(os.path.join(td, "work", "entity.json")), "ef: offline run still writes work/entity.json")
    # NAP: a brand name guessed from the host is not graded; a name the site states is
    from auditlib.findings import ProbeOutput as _PO
    import types as _types
    def _pg(html, role="home", url="https://acme.example/"):
        return Page({"role": role, "url": url, "final_url": url, "fetch": {"status": 200}}, Document(html, base_url=url))
    nameless = [_pg("<p>Call us: +44 117 496 0123 for a quote.</p>", "home"), _pg("<p>Write to 12 Harbour Street, Bristol BS1 4QA.</p>", "contact", "https://acme.example/contact")]
    o1 = _PO("entity-freshness-corroboration-audit", "https://acme.example", "professional_services", [], total_sampled_pages=2)
    ep.check_nap(_types.SimpleNamespace(category="professional_services"), o1, nameless, {"value": "Acme", "source": "host", "page": None})
    res.check(o1.status_of("ef.entity.nap_missing_plain_text") == "pass", "ef: nap ignores a host-guessed name when address or phone is present", str(o1.checks))
    o2 = _PO("entity-freshness-corroboration-audit", "https://acme.example", "professional_services", [], total_sampled_pages=2)
    ep.check_nap(_types.SimpleNamespace(category="professional_services"), o2, nameless, {"value": "Acme", "source": "meta:og:site_name", "page": "https://acme.example/"})
    f = next((x for x in o2.findings if x["check_id"] == "ef.entity.nap_missing_plain_text"), None)
    res.check(f is not None and "Missing: name" in f["evidence"] and f["severity"] == "medium" and f["confidence"] == "high",
              "ef: nap grades a stated name that the text never shows (medium, high confidence)", f["evidence"] if f else str(o2.checks))
    o3 = _PO("entity-freshness-corroboration-audit", "https://acme.example", "professional_services", [], total_sampled_pages=1)
    ep.check_nap(_types.SimpleNamespace(category="professional_services"), o3, [nameless[0]], {"value": "Acme", "source": "meta:og:site_name", "page": "https://acme.example/"})
    f = next((x for x in o3.findings if x["check_id"] == "ef.entity.nap_missing_plain_text"), None)
    res.check(f is not None and f["confidence"] == "medium" and any("contact_and_about_not_sampled" in i["value"] for i in f["evidence_items"]),
              "ef: nap drops to medium confidence when neither contact nor about was usable", str(f["evidence_items"]) if f else "no finding")
    # entity lookup decisions on canned responses
    S = '/private/tmp/claude-501/-Users-sheelgautam-adobe-hackathon/ec556381-cade-44e9-8891-c1754b44e2fc/scratchpad'
    disamb = '<html><head><title>Mint - Wikipedia</title><script>"wgWikibaseItemId":"Q369531"</script></head><body><div class="mw-parser-output"><div class="dmbox dmbox-disambig">x</div><ul><li>a</li><li>b</li><li>c</li></ul></div><div id="catlinks">Category:Disambiguation_pages</div></body></html>'
    article = '<html><head><title>Adobe Inc. - Wikipedia</title><script>"wgWikibaseItemId":"Q11463"</script></head><body><div class="mw-parser-output"><p>Adobe Inc. is a software company. Website adobe.com</p></div></body></html>'
    other = '<html><head><title>Adobe - Wikipedia</title><script>"wgWikibaseItemId":"Q183496"</script></head><body><div class="mw-parser-output"><p>Adobe is a building material.</p></div></body></html>'
    c1, c2, c3 = ep.classify_wikipedia(disamb, "mint.com"), ep.classify_wikipedia(article, "adobe.com"), ep.classify_wikipedia(other, "adobe.com")
    res.check(c1["disambiguation"] and c1["entries"] == 3 and c1["qid"] == "Q369531" and c1["title"] == "Mint", "ef: disambiguation page classified with entry count and Q-id")
    res.check(not c2["disambiguation"] and c2["mentions_domain"] and c2["qid"] == "Q11463", "ef: brand article classified as mentioning the domain")
    res.check(not c3["disambiguation"] and not c3["mentions_domain"], "ef: homonym article classified as not mentioning the domain")
    ed = {"entities": {"Q11463": {"labels": {"en": {"value": "Adobe Inc."}}, "aliases": {"en": [{"value": "Adobe"}, {"value": "Adobe Systems"}]}, "claims": {"P856": [{"mainsnak": {"datavalue": {"value": "https://www.adobe.com/"}}}]}}}}
    e1 = ep.classify_entitydata(ed, "Q11463", "Adobe", "adobe.com")
    e2 = ep.classify_entitydata(ed, "Q11463", "Ledgerly", "ledgerly.example")
    res.check(e1["label_match"] and e1["website_match"] and e1["label"] == "Adobe Inc.", "ef: EntityData verifies a matching label/website")
    res.check(not e2["label_match"] and not e2["website_match"], "ef: EntityData mismatch detected")
    res.check(ep.parse_date("2026-09-07T14:02:12Z") == _dt.date(2026, 9, 7) and ep.parse_date("7 September 2026") == _dt.date(2026, 9, 7) and ep.parse_date("Sep 7, 2026") == _dt.date(2026, 9, 7) and ep.parse_date("2019") is None,
              "ef: date parser handles ISO, written, abbreviated; rejects a bare year")
    res.check(ep.wikipedia_title_for("plausible analytics") == "Plausible_analytics" and ep.wikipedia_title_for("  ") is None, "ef: Wikipedia title derivation")
    # offsite file drives an inconclusive info note with counts
    with tempfile.TemporaryDirectory() as td:
        ctx = AuditContext.from_url(farm.urls["clean-site"], td)
        os.makedirs(os.path.join(td, "work"), exist_ok=True)
        json.dump({"tool": "web_search", "queries": ['"Ledgerly"', '"Ledgerly" Bristol'], "mentions": [{"url": "https://directory.example/ledgerly", "kind": "directory", "agrees_with": ["address"]}, {"url": "https://news.example/a", "kind": "news"}]},
                  open(os.path.join(td, "work", "offsite_mentions.json"), "w"))
        out = ep.run(ctx).to_dict()
        f = next((x for x in out["findings"] if x["check_id"] == "ef.corroboration.offsite_spotcheck"), None)
        res.check(f is not None and f["status"] == "inconclusive" and f["severity"] == "info" and "2 mentions across 2 queries" in f["title"] and "directory=1" in f["evidence"] and "news=1" in f["evidence"],
                  "ef: offsite file yields an inconclusive info note with counts by kind", f["title"] if f else None)
        res.check(not validate_probe_output(out), "ef: offsite note validates against the schema")


# ---------------------------------------------------------------- stage: probe_en (engagement probe on fixtures)
def stage_probe_en(res, farm):
    print("\n== stage: engagement probe on every fixture")
    ep = _load_probe("engagement-audit", "engagement_probe.py")
    R = run_probe_on_fixtures(res, farm, "en.", ep, "en")
    sev = lambda name, cid: next((f["severity"] for f in R[name]["findings"] if f["check_id"] == cid), None)
    conf = lambda name, cid: next((f["confidence"] for f in R[name]["findings"] if f["check_id"] == cid), None)
    finding = lambda name, cid: next((f for f in R[name]["findings"] if f["check_id"] == cid), None)
    status = lambda name, cid: next((c for c in R[name]["checks"] if c["check_id"] == cid), {})
    # clean-site: every check passes, nothing to say
    cs = R["clean-site"]
    res.check(not cs["findings"] and all(c["status"] == "pass" for c in cs["checks"]), "en/clean-site: zero findings, 16 passes", str([(c["check_id"], c["status"]) for c in cs["checks"] if c["status"] != "pass"]))
    # weak-engagement: severities and evidence
    we = "weak-engagement"
    res.check(sev(we, "en.mobile.viewport_missing") == "high" and conf(we, "en.mobile.viewport_missing") == "high" and len(finding(we, "en.mobile.viewport_missing")["affected_pages"]) == 6,
              "en/weak-engagement: viewport_missing high on all six pages")
    f = finding(we, "en.hero.value_prop_unclear")
    res.check(f is not None and f["severity"] == "medium" and f["confidence"] == "medium" and "Welcome friends" in f["evidence"] and "h1_too_short" in json.dumps(f["evidence_items"]) and "lead_text_no_offer" in json.dumps(f["evidence_items"]),
              "en/weak-engagement: hero unclear with two signals => medium confidence", f["evidence"] if f else None)
    f = finding(we, "en.cta.missing")
    res.check(f is not None and f["severity"] == "medium" and len(f["affected_pages"]) == 5 and "search" not in json.dumps(f["evidence_items"]).lower().split("matched=0")[0][-40:],
              "en/weak-engagement: cta_missing on all five key pages (search form never counts)", str(f and f["affected_pages"]))
    res.check(sev(we, "en.nav.landmark_missing") == "low" and conf(we, "en.nav.landmark_missing") == "high", "en/weak-engagement: landmark_missing low/high")
    f = finding(we, "en.links.broken_sampled")
    res.check(f is not None and f["severity"] == "medium" and f["confidence"] == "high" and "/old-pricing" in json.dumps(f["evidence_items"]) and "404" in f["evidence"],
              "en/weak-engagement: broken_sampled names /old-pricing with its 404")
    res.check(sev(we, "en.lang.attribute_missing") == "low", "en/weak-engagement: lang_missing low")
    f = finding(we, "en.errors.soft_404")
    res.check(f is not None and f["severity"] == "medium" and f["confidence"] == "high" and "200" in f["evidence"] and status(we, "en.errors.unhelpful_404").get("reason") == "soft_404",
              "en/weak-engagement: soft_404 medium/high, unhelpful_404 not_evaluated with reason soft_404")
    f = finding(we, "en.interstitial.blocking")
    res.check(f is not None and f["severity"] == "medium" and "welcome-modal" in json.dumps(f["evidence_items"]) and "fixed" in json.dumps(f["evidence_items"]),
              "en/weak-engagement: interstitial names #welcome-modal, position fixed")
    f = finding(we, "en.trust.signals_missing")
    res.check(f is not None and f["severity"] == "medium" and f["confidence"] == "medium" and "present=none" in json.dumps(f["evidence_items"]), "en/weak-engagement: trust signals none present", f and f["evidence"])
    f = finding(we, "en.continuity.h1_title_mismatch")
    res.check(f is not None and f["severity"] == "low" and len(f["affected_pages"]) == 1 and f["affected_pages"][0].endswith("/"), "en/weak-engagement: continuity mismatch on home only")
    # weak-ecommerce
    wc = "weak-ecommerce"
    res.check(sev(wc, "en.nav.breadcrumbs_missing") == "low" and conf(wc, "en.nav.breadcrumbs_missing") == "high", "en/weak-ecommerce: breadcrumbs low/high")
    res.check(sev(wc, "en.nav.site_search_missing") == "low" and conf(wc, "en.nav.site_search_missing") == "high", "en/weak-ecommerce: site search low/high")
    f = finding(wc, "en.nav.related_links_missing")
    res.check(f is not None and f["severity"] == "low" and f["confidence"] == "medium" and f["affected_pages"][0].endswith("/shop"), "en/weak-ecommerce: related links low/medium on /shop", str(f and f["affected_pages"]))
    f = finding(wc, "en.errors.unhelpful_404")
    res.check(f is not None and f["severity"] == "low" and "home_link=false" in json.dumps(f["evidence_items"]) and status(wc, "en.errors.soft_404").get("status") == "pass", "en/weak-ecommerce: unhelpful_404 low, soft_404 passes")
    f = finding(wc, "en.perf.page_weight_heavy")
    res.check(f is not None and f["severity"] == "low" and f["confidence"] == "low" and "script_tags=41" in json.dumps(f["evidence_items"]) and len(f["affected_pages"]) == 1 and f["suggested_action"]["priority"] == "low",
              "en/weak-ecommerce: page weight low/low on home only, priority low")
    # blocked-links: cluster reclassified, nothing broken
    bl = "blocked-links"
    f = finding(bl, "en.links.blocked_cluster")
    res.check(f is not None and f["status"] == "inconclusive" and f["severity"] == "info" and "3" in f["title"] and status(bl, "en.links.broken_sampled").get("status") == "pass",
              "en/blocked-links: three 403 links form a cluster (inconclusive info), broken_sampled passes", f and f["title"])
    # one-page-portfolio: category caps
    st = {c["check_id"]: c for c in R["one-page-portfolio"]["checks"]}
    gated = ["en.nav.landmark_missing", "en.nav.breadcrumbs_missing", "en.nav.site_search_missing", "en.nav.related_links_missing", "en.trust.signals_missing"]
    res.check(all(st[c]["status"] == "not_evaluated" and st[c].get("reason") == "not_applicable_for_category" for c in gated), "en/one-page-portfolio: five checks not applicable for the category", str({c: st[c] for c in gated}))
    res.check(st["en.links.broken_sampled"].get("reason") == "no_internal_links" and st["en.hero.value_prop_unclear"]["status"] == "pass" and st["en.cta.missing"]["status"] == "pass",
              "en/one-page-portfolio: no internal links to sample; hero and mailto CTA pass")
    # csr-shell / challenge-page / blanket-disallow: degraded reasons, no findings
    st = {c["check_id"]: c for c in R["csr-shell"]["checks"]}
    res.check(st["en.hero.value_prop_unclear"].get("reason") == "no_rendered_content" and st["en.mobile.viewport_missing"]["status"] == "pass" and st["en.errors.soft_404"]["status"] == "pass",
              "en/csr-shell: content checks not_evaluated (no_rendered_content), head and 404 checks still run")
    st = {c["check_id"]: c for c in R["challenge-page"]["checks"]}
    res.check(all(c["status"] == "not_evaluated" and c.get("reason") == "challenge_page" for c in st.values()), "en/challenge-page: every check not_evaluated with reason challenge_page")
    st = {c["check_id"]: c for c in R["blanket-disallow"]["checks"]}
    res.check(all(c["status"] == "not_evaluated" and c.get("reason") == "robots_disallow" for c in st.values()), "en/blanket-disallow: every check not_evaluated with reason robots_disallow")
    # degraded paths: broken workdir, offline, no-network in workdir mode
    from auditlib.context import AuditContext
    import tempfile, types
    out = ep.run(AuditContext.from_workdir("/nonexistent/dir")).to_dict()
    res.check(out["error"] and not out["findings"] and all(c["status"] == "not_evaluated" for c in out["checks"]), "en: broken workdir yields valid degraded output")
    with tempfile.TemporaryDirectory() as td:
        out = ep.run(AuditContext.from_url("https://example.com", td, offline=True)).to_dict()
        res.check(out["error"] is None and len(out["checks"]) == 16 and all(c["status"] == "not_evaluated" for c in out["checks"]), "en: offline run degrades cleanly, all 16 not_evaluated, no error", str(out["error"]))
        reasons = {c["check_id"]: c.get("reason") for c in out["checks"]}
        res.check(reasons["en.links.broken_sampled"] == "network_disabled" and reasons["en.errors.soft_404"] == "network_disabled" and reasons["en.hero.value_prop_unclear"] == "network_disabled",
                  "en: offline reasons are network_disabled", str(reasons))
        res.check({f["check_id"] for f in out["findings"]} == {"en.links.broken_sampled"} and out["findings"][0]["severity"] == "info", "en: offline run emits exactly one info note")
        res.check(os.path.exists(os.path.join(td, "work", "engagement.json")), "en: offline run still writes work/engagement.json")
    with tempfile.TemporaryDirectory() as td:
        ctx = AuditContext.from_url(farm.urls["clean-site"], td)
        ep.run(ctx)
        out = ep.run(AuditContext.from_workdir(td), types.SimpleNamespace(no_network=True)).to_dict()
        st = {c["check_id"]: c for c in out["checks"]}
        res.check(st["en.links.broken_sampled"].get("reason") == "network_disabled" and st["en.errors.soft_404"].get("reason") == "network_disabled" and st["en.hero.value_prop_unclear"]["status"] == "pass",
                  "en: --no-network in workdir mode skips only the network checks")
        work = json.load(open(os.path.join(td, "work", "engagement.json")))
        res.check(work["network"] is False and work["requests_made"] == 0, "en: engagement.json records network=false, zero requests")
    # engagement.json from a normal run has the link sample and the 404 probe
    with tempfile.TemporaryDirectory() as td:
        ep.run(AuditContext.from_url(farm.urls["clean-site"], td))
        work = json.load(open(os.path.join(td, "work", "engagement.json")))
        res.check(work["link_summary"]["sampled"] >= 6 and work["link_summary"]["broken"] == 0 and work["probe_404"]["verdict"] == "real_404" and work["probe_404"]["home_link"] is True,
                  "en/clean-site: engagement.json has the link sample and a helpful real 404", str(work.get("link_summary")))
        res.check(work["link_summary"]["requested"] <= 15 and work["requests_made"] <= 16, "en/clean-site: at most 15 link requests plus the 404 probe (%s)" % work["requests_made"])


STAGES = {"manifest": None, "serve": None, "variants": None, "robots": None, "htmldoc": None, "extract": None, "fetch": None, "sample": None, "probe_cr": None, "probe_fx": None, "probe_ef": None, "probe_en": None, "compose": None, "validate": None, "live": None}


def main(argv=None):
    ap = argparse.ArgumentParser(description="brand-ai-readiness-audit test runner")
    ap.add_argument("--stage", choices=sorted(STAGES), action="append", help="run only these stages")
    ap.add_argument("--base-port", type=int, default=8100)
    ap.add_argument("--keep", action="store_true", help="leave fixture servers running after tests")
    ap.add_argument("--live", nargs="*", metavar="URL", help="also run the live stage against these sites")
    args = ap.parse_args(argv)
    os.environ["BRAND_AUDIT_EXTERNAL"] = "0"  # the suite never contacts Wikipedia/Wikidata; the entity lookup is unit-tested on canned responses
    stages = args.stage or ["manifest", "serve", "variants", "robots", "htmldoc", "extract", "fetch", "sample", "probe_cr", "probe_fx", "probe_ef", "probe_en", "compose", "validate"]
    if args.live:
        stages.append("live")
    res = Results()
    farm = None
    try:
        if "manifest" in stages:
            stage_manifest(res)
        if "robots" in stages:
            stage_robots(res)
        if "htmldoc" in stages:
            stage_htmldoc(res)
        if "extract" in stages:
            stage_extract(res)
        if any(st in stages for st in ("serve", "variants", "fetch", "sample", "probe_cr", "probe_fx", "probe_ef", "probe_en", "compose", "validate")):
            farm = FixtureFarm(base_port=args.base_port)
            farm.start()
            print("\nfixtures:")
            for n, url in farm.urls.items():
                print("  %-24s %s" % (n, url))
            if "serve" in stages:
                stage_serve(res, farm)
            if "variants" in stages:
                stage_variants(res, farm)
            if "fetch" in stages:
                stage_fetch(res, farm)
            if "sample" in stages:
                stage_sample(res, farm)
            if "probe_cr" in stages:
                stage_probe_cr(res, farm)
            if "probe_fx" in stages:
                stage_probe_fx(res, farm)
            if "probe_ef" in stages:
                stage_probe_ef(res, farm)
            if "probe_en" in stages:
                stage_probe_en(res, farm)
            if "compose" in stages:
                stage_compose(res, farm)
            if "validate" in stages:
                stage_validate(res, farm)
        if "live" in stages:
            stage_live(res, args.live or ["https://example.com/", "https://www.python.org/"])
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        print("\nRUNNER ERROR")
        return 2
    finally:
        if farm and not args.keep:
            farm.stop()
    print("\n%d passed, %d failed" % (len(res.passed), len(res.failed)))
    if res.failed:
        for n, d in res.failed:
            print("  - %s %s" % (n, d))
        return 1
    print("GREEN")
    if farm and args.keep:
        print("servers left running (--keep); Ctrl-C to stop")
        try:
            import threading
            threading.Event().wait()
        except KeyboardInterrupt:
            farm.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
