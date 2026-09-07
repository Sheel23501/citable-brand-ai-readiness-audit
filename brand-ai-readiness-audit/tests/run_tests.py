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
        res.check(st == 404, "%s: unknown path returns real 404" % name, str(st))
        res.check(b'href="/"' in body, "%s: 404 page links home" % name)
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


STAGES = {"manifest": None, "serve": None, "variants": None, "robots": None, "htmldoc": None, "extract": None, "fetch": None, "sample": None, "probe_cr": None, "probe_fx": None, "probe_ef": None, "live": None}


def main(argv=None):
    ap = argparse.ArgumentParser(description="brand-ai-readiness-audit test runner")
    ap.add_argument("--stage", choices=sorted(STAGES), action="append", help="run only these stages")
    ap.add_argument("--base-port", type=int, default=8100)
    ap.add_argument("--keep", action="store_true", help="leave fixture servers running after tests")
    ap.add_argument("--live", nargs="*", metavar="URL", help="also run the live stage against these sites")
    args = ap.parse_args(argv)
    os.environ["BRAND_AUDIT_EXTERNAL"] = "0"  # the suite never contacts Wikipedia/Wikidata; the entity lookup is unit-tested on canned responses
    stages = args.stage or ["manifest", "serve", "variants", "robots", "htmldoc", "extract", "fetch", "sample", "probe_cr", "probe_fx", "probe_ef"]
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
        if any(st in stages for st in ("serve", "variants", "fetch", "sample", "probe_cr", "probe_fx", "probe_ef")):
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
