#!/usr/bin/env python3
"""Test runner for brand-ai-readiness-audit.

Step 3 scope (this file): start every fixture on its own port, verify each one
serves (home, robots.txt, sitemap.xml, 404 behaviour, route overrides), and
validate every _fixture.json against the check registry so fixtures can never
expect a check id that does not exist.

Stages, in the order they run (each added by the step that built the thing it tests):
  manifest   fixture manifests, registry ids, documentation hygiene for every skill      (Steps 3, 11-17)
  serve, variants, robots, htmldoc, extract, fetch, sample                                (Steps 3-5, 8)
  probe_cr, probe_fx, probe_ef, probe_en   each probe on every fixture against `expected`  (Steps 6, 8, 10, 12)
  compose    the dedupe table, ordering, tags, a validated report per fixture              (Step 14)
  validate   floor, superset, --final, 46 deliberately broken reports, the finalize flow   (Steps 15, 17)
  run_audit  the command end to end on every fixture, plus its guards                      (Step 16)
  scripts    every script, every usage path incl. wrong usage: no traceback anywhere       (Step 18)
  live       optional, --live URL ...: real sites, no assertions on content                (Step 19)

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


def _read_json(path, encoding="utf-8"):
    """Read JSON with an explicit encoding and close the handle.

    Windows defaults text mode to cp1252, which raises UnicodeDecodeError on any
    non-Latin-1 byte in captured page text; and a handle leaked by
    json.load(open(...)) makes TemporaryDirectory cleanup fail with WinError 32.
    """
    with open(path, encoding=encoding) as f:
        return json.load(f)


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)



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
        ne = exp.get("not_evaluated") or {}
        res.check(isinstance(ne, dict) and not (set(ne) - ids), "%s: expected.not_evaluated ids all in registry" % n, ", ".join(sorted(set(ne) - ids)))
        clash = set(ne) & (set(exp.get("fail", [])) | set(exp.get("pass_required", [])))
        res.check(not clash, "%s: a check with no verdict is neither expected to fail nor required to pass" % n, ", ".join(sorted(clash)))
        for path, route in meta.get("routes", {}).items():
            pass
    # every engagement check is exercised by at least one fixture that expects it to fail (or, for info checks, to emit a note)
    exercised = set()
    for n in names:
        exp = load_fixture(n).get("expected", {})
        exercised |= set(exp.get("fail", [])) | set(exp.get("info", [])) | set(exp.get("gated", []))
    unexercised = sorted(c for c in ids if c.startswith("en.") and c not in exercised)
    res.check(not unexercised, "fixtures exercise every en.* check as a failure or note", ", ".join(unexercised))
    # documentation hygiene: a skill whose references/ exist must document every registered check of its prefix,
    # and its SKILL.md must point at a script that exists
    skill_prefix = {"crawl-render-audit": "cr.", "fact-extractability-audit": "fx.",
                    "entity-freshness-corroboration-audit": "ef.", "engagement-audit": "en.",
                    "audit-orchestrator": "or."}
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
    # the edge probe announces crawler tokens; no document may still promise that it never does
    retired = ("never impersonates a listed token", "never uses the token of any bot listed")
    stale = []
    for dirpath, _dirs, files in os.walk(ROOT):
        for fn in files:
            if fn.endswith(".md"):
                text = open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace").read()
                stale += ["%s: %r" % (os.path.relpath(os.path.join(dirpath, fn), ROOT), r) for r in retired if r in text]
    res.check(not stale, "no document still claims the audit never announces a crawler token", "; ".join(stale))
    for needle in ("robots.txt allows", "never sent"):
        res.check(needle in open(os.path.join(ROOT, "README.md"), encoding="utf-8").read(), "README Safety states the robots rule for announced tokens (%s)" % needle)
    orch = open(os.path.join(ROOT, "skills", "audit-orchestrator", "SKILL.md"), encoding="utf-8").read()
    for needle in ("run_audit.py", "finalize.py", "compose.py", "validate.py", "references/simulation_rules.md",
                   "offsite_spotcheck.md", "extracted_facts.json", "WebSearch", "--final"):
        res.check(needle in orch, "audit-orchestrator: SKILL.md procedure mentions %s" % needle)
    res.check(orch.index("offsite_spotcheck.md") < orch.index("finalize.py"),
              "audit-orchestrator: the spot-check step precedes the answers step (compose rewrites report.json)")
    rules = open(os.path.join(ROOT, "skills", "audit-orchestrator", "references", "simulation_rules.md"), encoding="utf-8").read()
    for needle in ("verbatim", "20 characters", "answerable: false", "attribution", "invisible", "stale", "bouncing", "snapshots"):
        res.check(needle in rules, "simulation_rules.md covers %s" % needle)
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
    from auditlib.robots import load_bot_tiers
    tiers = load_bot_tiers()
    from auditlib.fetch import PROBE_USER_AGENTS
    for token, tier, agent in PROBE_USER_AGENTS:
        row = tiers.get(token.lower())
        res.check(row is not None and row["tier"] == tier, "probe token %s: tier %s agrees with bot_tiers.md" % (token, tier), str(row))
        res.check(token in agent, "probe token %s: its published user-agent string carries the token" % token)
    # get_as holds the announced token to robots.txt as if it were the real crawler (edge-probe guard):
    # a token the site disallowed is never sent, whoever asks, and the budget is untouched
    from auditlib.fetch import PROBE_USER_AGENTS
    ua = {t: agent for t, _tier, agent in PROBE_USER_AGENTS}
    base = u["bot-blocking-robots"]
    n = f.requests_made
    r = f.get_as(base + "/", ua["GPTBot"], token="GPTBot")
    res.check(r["skipped"] == "robots_disallow_for_token" and r["status"] is None and r["skipped_rule"] == "Disallow: /"
              and f.requests_made == n, "get_as: a token robots.txt disallows is not sent and costs no request")
    r = f.get_as(base + "/", ua["GPTBot"])
    res.check(r.get("announced_token") == "GPTBot" and r["skipped"] == "robots_disallow_for_token" and f.requests_made == n,
              "get_as: the token is inferred from the published user-agent string when not named")
    r = f.get_as(base + "/pricing", ua["Claude-User"], token="Claude-User")
    res.check(r["skipped"] == "robots_disallow_for_token" and r["skipped_rule"] == "Disallow: /pricing" and f.requests_made == n,
              "get_as: the rule is evaluated for the announced token and the exact path")
    r = f.get_as(base + "/", ua["Claude-User"], token="Claude-User")
    res.check(r["status"] == 200 and r.get("announced_token") == "Claude-User" and f.requests_made == n + 1,
              "get_as: the same token on an allowed path is sent once")
    res.check(f.headers.get("User-Agent") is not None and "brand-ai-readiness-audit" in f.headers["User-Agent"],
              "get_as: the audit's own user agent is restored afterwards")
    r = f.get_as(base + "/", "SomeUnknownAgent/1.0")
    res.check(r["skipped"] == "unknown_token" and f.requests_made == n + 1, "get_as: an agent that cannot be named is not sent")
    # the sampler passes the token and records the policy decision with its rule
    from auditlib.sampler import probe_edge_access
    f2 = Fetcher(site=base)
    home = f2.get(base + "/", purpose="page")
    ea = probe_edge_access(f2, base + "/", home, f2.robots())
    res.check([a["token"] for a in ea["policy"]] == ["GPTBot"] and ea["policy"][0]["rule"] == "Disallow: /",
              "edge probe: a disallowed token is recorded as policy with its rule", str(ea.get("policy")))
    rules = {a["token"]: a["robots_rule"] for a in ea["agents"]}
    res.check(sorted(rules) == ["Claude-User", "OAI-SearchBot"] and ea["reason"] is None,
              "edge probe: only allowed tokens are probed", str(ea.get("agents")))
    # RFC 9309 semantics recorded honestly: a token with no group falls to '*' (Allow: /); a token whose own
    # group has no rule for this path is allowed by absence, and no rule is invented for it
    res.check(rules.get("OAI-SearchBot") == "Allow: /" and rules.get("Claude-User") is None,
              "edge probe: the matched rule is recorded, and 'allowed by absence' is recorded as no rule", str(rules))
    f3 = Fetcher(site=u["clean-site"])
    home = f3.get(u["clean-site"] + "/", purpose="page")
    ea = probe_edge_access(f3, u["clean-site"] + "/", home, f3.robots())
    res.check(len(ea["agents"]) == 3 and not ea["policy"], "edge probe: a robots.txt that allows everyone probes all three tokens")
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
        m = _read_json(os.path.join(td, rel))
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
    # the shared tokenizer keeps combining marks, so Indic, Thai and Arabic words are whole words
    from auditlib.htmldoc import words as _hw
    res.check(_hw("दिल्ली के बच्चों के लिए निःशुल्क पढ़ाई") == ["दिल्ली", "के", "बच्चों", "के", "लिए", "निःशुल्क", "पढ़ाई"], "tokenizer: a seven-word Hindi heading is seven words")
    res.check(_hw("Hello world, 12 rue des Archives; e-mail hello@x.example") == ["Hello", "world", "12", "rue", "des", "Archives", "e", "mail", "hello", "x", "example"],
              "tokenizer: Latin text and digits tokenise as before")
    res.check(len(_hw("เปิดทุกวัน")) == 1 and len(_hw("مرحبا بكم")) == 2, "tokenizer: Thai and Arabic words stay whole")
    res.check(Document("<p>दिल्ली के बच्चों के लिए निःशुल्क पढ़ाई</p>").word_count == 7, "word_count uses the shared tokenizer")
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
    # the first viewport starts at the first visible content, not at <body> (dry-run judging, 2026-09-10)
    heavy = Document("<html><body><noscript><p><img src='https://t.example/pixel.php?rec=1' style='border:0'></p></noscript>"
                     + "<svg><title>logo</title><path d='%s'/></svg>" % ("M0 0 L1 1 " * 20000) + "<style>.x{}</style>"
                     "<header><a href='/'>Skip</a></header><main><h1>Steak</h1><a href='/book/'>Book a table</a>"
                     + "<p>text</p>" * 200 + "</main></body></html>", base_url="https://s.example/")
    book = next(l for l in heavy.links if "Book" in l.text)
    res.check(heavy.content_mpos is not None and heavy.body_frac(book.mpos) is not None and heavy.body_frac(book.mpos) < 0.4,
              "body_frac: a link behind 200 KB of inline SVG is still in the first viewport of the content (%.2f)" % (heavy.body_frac(book.mpos) or -1))
    plain = Document("<html><body><h1>T</h1><a href='/a'>A</a></body></html>", base_url="https://s.example/")
    res.check(plain.content_mpos is not None and plain.body_frac(plain.links[0].mpos) < 0.4, "body_frac: a plain page is unchanged")
    # Step 19 rules: a headline is not a menu label; section names need company; sibling subdomains are nav; ties resolve by rule
    head = lambda body, base="https://s.example/": Document("<html><body><nav>%s</nav></body></html>" % body, base_url=base)  # noqa: E731
    cat = categorize([], {"home": head('<a href="/blogs/">News</a><a href="/psf/newsletter/">Newsletter</a>'
                                        '<a href="/x/">Saving the world with Open Data and Python</a>'
                                        '<a href="/success-stories/category/business/">Business</a>', "https://s.org/")}, [], "https://s.org/", 60)
    res.check("nav:world" not in cat["signals"] and "section:world" not in cat["signals"],
              "categorize: a category word inside a headline is not a nav signal", str(cat["signals"]))
    res.check("nav:business" not in cat["signals"] and "section:business" not in cat["signals"],
              "categorize: a single section name does not score", str(cat["signals"]))
    cat = categorize([], {"home": head('<a href="/w/">World</a><a href="/b/">Business</a><a href="/p/">Politics</a><a href="/n/">News</a>',
                                        "https://paper.example/")}, [], "https://paper.example/", 400)
    res.check(cat["value"] == "publisher_media" and "section:world" in cat["signals"] and "section:business" in cat["signals"],
              "categorize: two or more section names make a masthead", str(cat))
    cat = categorize([], {"home": head('<a href="https://docs.proj.example/">Documentation</a><a href="/pricing/">Pricing</a>'
                                        '<a href="https://app.proj.example/login">Log in</a>', "https://www.proj.example/")},
                     [], "https://www.proj.example/", 50)
    res.check(cat["value"] == "saas_software" and "nav:documentation" in cat["signals"] and "nav:log in" in cat["signals"],
              "categorize: nav links to sibling subdomains count as the site's own navigation", str(cat))
    cat = categorize([], {"home": head('<a href="https://elsewhere.example/docs">Documentation</a><a href="/pricing/">Pricing</a>',
                                        "https://www.proj.example/")}, [], "https://www.proj.example/", 50)
    res.check("nav:documentation" not in cat["signals"], "categorize: a link to another domain is not navigation", str(cat["signals"]))
    # equal scores, unequal evidence: a self-declared JSON-LD type outranks three menu labels
    strong = Document('<html><head><script type="application/ld+json">{"@context":"https://schema.org","@type":"NGO","name":"T"}</script></head>'
                      '<body><nav><a href="/n/">News</a><a href="/l/">Latest</a><a href="/s/">Subscribe</a></nav></body></html>',
                      base_url="https://t.example/")
    cat = categorize([], {"home": strong}, [], "https://t.example/", 40)
    res.check(cat["scores"]["publisher_media"] == cat["scores"]["nonprofit_institution"] == 3, "categorize: the strength fixture ties on score (%s)" % cat["scores"])
    res.check(cat["value"] == "nonprofit_institution" and not any(w.startswith("tie:") for w in cat["signals"]) and cat["confidence"] == "medium",
              "categorize: a tie on score resolves to the stronger evidence, with no tie recorded", str(cat))
    # a generic LocalBusiness type is weaker than a specific one, and than three menu labels for another category
    agency = Document('<html><head><script type="application/ld+json">{"@type":"LocalBusiness","name":"C"}</script></head>'
                      '<body><nav><a href="/s/">Services</a><a href="/c/">Clients</a><a href="/w/">Our work</a></nav></body></html>',
                      base_url="https://agency.example/")
    cat = categorize([], {"home": agency}, [], "https://agency.example/", 30)
    res.check(cat["value"] == "professional_services" and cat["scores"]["local_business"] == 2,
              "categorize: a generic LocalBusiness type scores 2 and loses to an agency's own navigation", str(cat))
    diner = Document('<html><head><script type="application/ld+json">{"@type":"Restaurant","name":"D"}</script></head><body></body></html>',
                     base_url="https://diner.example/")
    cat = categorize([], {"home": diner}, [], "https://diner.example/", 30)
    res.check(cat["value"] == "local_business" and cat["scores"]["local_business"] == 3, "categorize: a specific type still scores 3", str(cat))
    # role discovery: a headline containing 'plans' is not the pricing page
    news = Document('<html><body><nav><a href="/en/news/Broadcom-plans-new-vSphere-Standard-1144.html">Broadcom plans new vSphere Standard</a>'
                    '<a href="/plans/">Plans</a></nav></body></html>', base_url="https://p.example/")
    cands = find_role_candidates(news, [], "https://p.example/")
    urls = [c["url"] for c in cands.get("pricing", [])]
    res.check(urls == ["https://p.example/plans/"], "roles: a headline containing 'plans' is not a pricing candidate; the label 'Plans' is", str(urls))
    # a dead-even tie: same score, same evidence strength, same breadth -> table order, recorded, low confidence
    even = head('<a href="/n/">News</a><a href="/l/">Latest</a><a href="/s/">Subscribe</a>'
                '<a href="/d/">Donate</a><a href="/m/">Mission</a><a href="/v/">Volunteer</a>', "https://t.example/")
    cat = categorize([], {"home": even}, [], "https://t.example/", 40)
    res.check(cat["scores"]["publisher_media"] == cat["scores"]["nonprofit_institution"] == 3, "categorize: the even fixture ties (%s)" % cat["scores"])
    res.check(cat["value"] == "publisher_media" and "tie:nonprofit_institution" in cat["signals"] and cat["confidence"] == "low",
              "categorize: a dead-even tie falls to table order, is recorded, and lowers confidence", str(cat))
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
            res.check(m["requests_made"] <= 12 and len(m["pages"]) <= 6, "%s: <=12 requests, <=6 pages (%d, %d)" % (name, m["requests_made"], len(m["pages"])))
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
            # the category fixtures: every role the category has is found from the navigation, in the site's own
            # language or (hindi-nonprofit) from English slugs under Hindi labels; pricing is missing because
            # none of these sites sells plans, and that is recorded, not invented
            if name in ("clean-restaurant-fr", "clean-consultancy", "clean-corporate", "hindi-nonprofit"):
                res.check(set(roles) == {"home", "about", "contact", "product", "blog"} and m["missing_roles"] == ["pricing"],
                          "%s: about, contact, product and blog found; only pricing missing" % name, "%s / %s" % (sorted(roles), m["missing_roles"]))
                res.check(all(roles[r]["source"] == "nav" for r in roles if r != "home"), "%s: role pages came from nav" % name)
            if name == "clean-publisher":
                res.check(set(roles) == {"home", "about", "contact", "blog"} and sorted(m["missing_roles"]) == ["pricing", "product"],
                          "clean-publisher: about, contact and blog found; product and pricing missing", "%s / %s" % (sorted(roles), m["missing_roles"]))
            if name in ("clean-restaurant-fr", "clean-consultancy", "clean-publisher", "clean-corporate"):
                res.check(m["site_category"]["confidence"] == "high", "%s: category confidence high" % name, str(m["site_category"]))
            if name == "hindi-nonprofit":
                res.check(m["site_category"]["confidence"] == "medium" and all(w.startswith(("jsonld:", "url:")) for w in m["site_category"]["signals"]),
                          "hindi-nonprofit: category from JSON-LD and URL patterns only, Hindi labels score nothing", str(m["site_category"]["signals"]))
                res.check(all((p.get("summary") or {}).get("lang") == "hi" and not (p.get("summary") or {}).get("lang_detected") for p in m["pages"]),
                          "hindi-nonprofit: every page declares hi and the Latin stopword detector stays silent")
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
        # (inconclusive, not_evaluated, and policy notes), regardless of status. `gated` ids fail here, at
        # probe level, and are withdrawn by the orchestrator's absence gate (compose stage asserts that).
        fails = {f["check_id"] for f in out["findings"] if f["severity"] != "info"}
        infos = {f["check_id"] for f in out["findings"] if f["severity"] == "info"}
        exp_fail = {c for c in exp["fail"] + exp.get("gated", []) if c.startswith(prefix)}
        exp_info = {c for c in exp["info"] if c.startswith(prefix)}
        statuses = {c["check_id"]: c["status"] for c in out["checks"]}
        res.check(fails == exp_fail, "%s/%s: fail set matches" % (label, name), "got %s expected %s" % (sorted(fails), sorted(exp_fail)))
        res.check(infos == exp_info, "%s/%s: info set matches" % (label, name), "got %s expected %s" % (sorted(infos), sorted(exp_info)))
        bad = [c for c in exp["pass_required"] if c.startswith(prefix) and statuses.get(c) != "pass"]
        res.check(not bad, "%s/%s: pass_required all pass" % (label, name), "%s -> %s" % (bad, [statuses.get(c) for c in bad]))
        # `not_evaluated`: a check that must have no verdict here, with the reason it must give
        reasons = {c["check_id"]: c.get("reason") for c in out["checks"]}
        for cid, reason in sorted((exp.get("not_evaluated") or {}).items()):
            if cid.startswith(prefix):
                res.check(statuses.get(cid) == "not_evaluated" and reasons.get(cid) == reason,
                          "%s/%s: %s has no verdict (%s)" % (label, name, cid, reason), "%s/%s" % (statuses.get(cid), reasons.get(cid)))
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

# The false-positive guards: one well-built site per category the fixtures cover, each of which must produce
# zero defects, a populated recommendations list, and a simulation that can answer every real question.
CLEAN_SITES = ("clean-site", "clean-restaurant-fr", "clean-consultancy", "clean-publisher", "clean-corporate")


def _coverage_reasons(report):
    """check_id -> reason for every check the composed report lists as having no verdict."""
    cov = report.get("coverage") or {}
    out = {}
    for key in ("not_evaluated", "not_applicable_for_category"):
        for e in cov.get(key) or []:
            out[e["check_id"]] = e.get("reason")
    return out


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

    # where to start (rubric section 5, schema 3b): the first quick win, else top priority at the lowest effort
    def _fs(cid, sev, conf, effort, prio, rank):
        f = _mkf(cid, sev, confidence=conf)
        f.update(id="F-%03d" % rank, rank=rank, effort=effort)
        f["suggested_action"]["priority"] = prio
        return f
    fs = [_fs("a.b.c", "medium", "low", "medium", "low", 1), _fs("a.b.d", "low", "high", "low", "low", 2),
          _fs("a.b.e", "low", "high", "medium", "low", 3)]
    res.check(C.start_with(fs, ["F-003"]) == "F-003", "start_with: the first quick win wins")
    res.check(C.start_with(fs, []) == "F-002", "start_with: equal priority resolves to the lowest effort", str(C.start_with(fs, [])))
    fs2 = [_fs("a.b.c", "medium", "medium", "medium", "medium", 1)] + fs[1:]
    res.check(C.start_with(fs2, []) == "F-001", "start_with: a higher priority outranks a lower effort")
    info = _mkf("or.x.y", "info", status="not_evaluated")
    info.update(id="F-001", rank=1)
    res.check(C.start_with([info], []) is None, "start_with: nothing above info means nowhere to start")
    pgs = [{"status": 200, "challenge": False}, {"status": 200, "challenge": False}, {"status": 404, "challenge": False}]
    chk = {"x": {"reason": "role_page_not_sampled"}, "y": {"reason": None}}
    h = C.build_headline(fs, pgs, chk, [], "F-002")
    res.check("2 pages read" in h and "1 medium and 2 low" in h and "Start with F-002" in h and "1 check had no verdict" in h,
              "headline: counts, pages read, where to start, and the gated clause", h)
    res.check(C.build_headline([], pgs, {}, [], None).startswith("No defects on the 2 pages read"), "headline: a clean site says so")
    res.check(C.build_headline(fs, pgs, {}, [{"probe": "x", "error": "boom"}], None).startswith("The run was incomplete"),
              "headline: an incomplete run leads with that")
    crit = [_fs("a.b.f", "critical", "high", "high", "high", 1)] + fs
    res.check(C.build_headline(crit, pgs, {}, [], "F-001").startswith("1 critical finding on the 2 pages read. Start with F-001"),
              "headline: a critical finding leads", C.build_headline(crit, pgs, {}, [], "F-001"))

    # ---- the absence gate (rubric section 3 rule 6): a sample claim is never voiced as a site claim
    def _smp(category, read, missing, links=10):
        pages = [{"role": r, "fetch": {"final_url": "http://s/%s" % r, "status": 200, "is_html": True}} for r in read]
        return {"site_category": {"value": category}, "pages": pages, "missing_roles": list(missing), "internal_links_seen": links}

    def _kf(missing_facts, severity="high"):
        item = {"page": "site", "kind": "computed",
                "value": "pages_searched=2 (home, about); key_facts=4; found=2; missing=%s" % ",".join(missing_facts)}
        return _mkf("fx.facts.key_fact_missing", severity, [], [item], confidence="medium")

    def _gate(findings, sample, category, facts=None):
        checks = {f["check_id"]: {"check_id": f["check_id"], "status": "fail", "reason": None} for f in findings}
        kept = C.apply_absence_gate(findings, checks, sample, category, facts)
        return {f["check_id"]: f for f in kept}, checks

    kept, chk = _gate([_kf(["mission", "location"]), _mkf("ef.entity.nap_missing_plain_text", "medium")],
                      _smp("nonprofit_institution", ["home", "about", "contact", "product", "blog"], []), "nonprofit_institution")
    res.check(len(kept) == 2 and kept["fx.facts.key_fact_missing"]["severity"] == "high"
              and "absence_scope" not in kept["fx.facts.key_fact_missing"], "gate: a full sample changes nothing")
    # a role the category does not expect is never "unreached": a nonprofit has no pricing page to miss
    kept, chk = _gate([_kf(["mission", "location"]), _mkf("fx.content.faq_absent", "low")],
                      _smp("nonprofit_institution", ["home", "about", "contact", "blog"], ["pricing", "product"]), "nonprofit_institution")
    kf = kept["fx.facts.key_fact_missing"]
    res.check(kf["severity"] == "high" and "absence_scope" not in kf and "pricing" not in kf["evidence"],
              "gate: an unexpected role (pricing on a nonprofit) neither caps nor annotates the key-fact finding", kf["evidence"])
    fq = kept["fx.content.faq_absent"]
    res.check(fq.get("absence_scope") == "sample" and fq["confidence"] == "low" and "product page was" in fq["evidence"],
              "gate: faq_absent with the programs page unread is a sample claim naming that page", fq["evidence"])
    # fully blind: no page that could carry the thing was read -> no verdict and no finding
    fs = [_kf(["pricing_or_trial"], "medium"), _mkf("ef.entity.nap_missing_plain_text", "medium"), _mkf("fx.content.faq_absent", "low"),
          _mkf("ef.corroboration.press_page_missing", "medium"), _mkf("en.cta.missing", "medium", ["http://s/home"]),
          _mkf("fx.identity.h1_missing_or_multiple", "low", ["http://s/home"])]
    kept, chk = _gate(fs, _smp("saas_software", ["home"], ["about", "contact", "pricing", "product", "blog"], links=24), "saas_software")
    gone = {"fx.facts.key_fact_missing", "ef.entity.nap_missing_plain_text", "fx.content.faq_absent", "ef.corroboration.press_page_missing"}
    res.check(set(kept) == {"en.cta.missing", "fx.identity.h1_missing_or_multiple"},
              "gate: a home-only sample withdraws every site-level absence claim", str(sorted(kept)))
    res.check(all(chk[c]["status"] == "not_evaluated" for c in gone), "gate: withdrawn checks are not_evaluated in the checks list")
    res.check(chk["fx.facts.key_fact_missing"]["reason"] == "role_page_not_sampled"
              and chk["ef.corroboration.press_page_missing"]["reason"] == "navigation_not_readable",
              "gate: the reasons distinguish an unreached role page from an unreadable navigation")
    res.check(kept["en.cta.missing"]["severity"] == "medium" and kept["en.cta.missing"]["confidence"] == "high",
              "gate: a per-page finding (en.cta.missing) is never gated")
    # partly blind key facts are scoped one fact at a time
    kept, chk = _gate([_kf(["mission", "location"]), _mkf("ef.entity.nap_missing_plain_text", "medium")],
                      _smp("nonprofit_institution", ["home", "about", "product", "blog"], ["contact", "pricing"]), "nonprofit_institution")
    kf = kept["fx.facts.key_fact_missing"]
    res.check(kf["severity"] == "medium" and kf["confidence"] == "medium" and kf.get("absence_scope") == "sample",
              "gate: one confirmed fact is medium (rubric rule 2) and scoped to the sample", "%s/%s" % (kf["severity"], kf["confidence"]))
    res.check("1 of 4 key facts" in kf["title"] and "1 not checked" in kf["title"] and len(kf["title"]) <= 90,
              "gate: the title counts confirmed and unchecked facts", kf["title"])
    res.check("Confirmed missing: mission" in kf["evidence"] and "location (contact page not reached)" in kf["evidence"],
              "gate: the evidence separates confirmed from not checked", kf["evidence"])
    res.check("mission" in kf["suggested_action"]["summary"] and "location" not in kf["suggested_action"]["summary"]
              and kf["suggested_action"]["priority"] == "medium",
              "gate: the action names only the confirmed facts and the priority follows the new severity", json.dumps(kf["suggested_action"]))
    nap = kept["ef.entity.nap_missing_plain_text"]
    res.check(nap["confidence"] == "low" and nap["severity"] == "medium" and nap.get("absence_scope") == "sample"
              and "contact page was" in nap["evidence"], "gate: NAP with the contact page unread is a low-confidence sample claim", nap["evidence"])
    bare = _mkf("fx.facts.key_fact_missing", "high", confidence="medium")
    facts = {"facts": {"mission": {"status": "absent"}, "location": {"status": "absent"},
                       "programs_or_services": {"status": "present"}, "how_to_participate": {"status": "present"}}}
    kept, chk = _gate([bare], _smp("nonprofit_institution", ["home", "about", "product"], ["contact", "pricing", "blog"]),
                      "nonprofit_institution", facts)
    res.check(kept["fx.facts.key_fact_missing"]["severity"] == "medium"
              and "Confirmed missing: mission" in kept["fx.facts.key_fact_missing"]["evidence"],
              "gate: key facts fall back to the facts file when the finding carries no missing= item")
    kept, chk = _gate([_kf(["what_it_does", "pricing_or_trial"])],
                      _smp("saas_software", ["home", "about", "contact", "product", "blog"], ["pricing"]), "saas_software")
    kf = kept["fx.facts.key_fact_missing"]
    res.check(kf["severity"] == "medium" and "pricing_or_trial (pricing page not reached)" in kf["evidence"],
              "gate: a missed pricing page scopes only the pricing fact", kf["evidence"])
    for read, missing, links, want in ((["home", "about", "contact", "product"], ["pricing", "blog"], 8, True),
                                       (["home", "about"], ["contact", "pricing", "product", "blog"], 24, False),
                                       (["home"], ["about", "contact", "pricing", "product", "blog"], 2, False)):
        kept, chk = _gate([_mkf("ef.corroboration.press_page_missing", "low")], _smp("saas_software", read, missing, links), "saas_software")
        res.check(("ef.corroboration.press_page_missing" in kept) == want,
                  "gate: press_page_missing %s with %d home links and %d roles unreached" % ("keeps its verdict" if want else "has no verdict", links, len(missing)))
    kept, chk = _gate([_mkf("fx.content.faq_absent", "low"), _mkf("ef.entity.nap_missing_plain_text", "low")],
                      _smp("portfolio_personal", ["home", "about", "contact"], ["pricing", "product", "blog"]), "portfolio_personal")
    res.check(len(kept) == 2 and all("absence_scope" not in f for f in kept.values()),
              "gate: a portfolio with about and contact read is fully graded")

    # the AI-answer simulation must never quote a window of navigation chrome as a fact (4.1): a fact
    # extractor's context window can land on nav/accessibility controls that merely mention a cue word,
    # and the underlying detector may still record it as present.
    chrome_value = "The Python Network Donate ≡ Menu Search This Site GO A A Smaller Larger Reset"
    prose_value = "You can donate online through our secure portal."
    res.check(C._sentence_shaped(chrome_value) is False, "sentence-shaped: nav chrome is rejected")
    res.check(C._sentence_shaped(prose_value) is True, "sentence-shaped: a real sentence passes")
    chrome_facts = {"facts": {"how_to_participate": {"status": "present", "value": chrome_value}}}
    res.check(C.answer_from_facts(["how_to_participate"], chrome_facts) is None,
              "answer_from_facts: refuses to quote nav chrome even when the fact is marked present")
    prose_facts = {"facts": {"how_to_participate": {"status": "present", "value": prose_value}}}
    res.check(C.answer_from_facts(["how_to_participate"], prose_facts) is not None,
              "answer_from_facts: still quotes a genuine sentence")
    sim = C.build_simulation(chrome_facts, "nonprofit_institution", "example.org", "work/extracted_facts.json")
    involved = [q for q in sim["questions"] if "how_to_participate" in q["facts_used"] or "how_to_participate" in q["missing_facts"]]
    res.check(bool(involved) and all("how_to_participate" not in q["facts_used"] for q in involved),
              "build_simulation: a chrome-shaped fact never lands in facts_used", str(involved))
    res.check(all("how_to_participate" in q["missing_facts"] for q in involved),
              "build_simulation: a chrome-shaped fact counts as missing instead", str(involved))

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
    # the absence gate's fact table mirrors site_categories.md section 1b and the gates are documented conventions
    from auditlib.categories import FACT_ROLES
    from auditlib.sampler import ROLE_ORDER
    all_facts = {fid for facts in KEY_FACTS.values() for fid in facts}
    res.check(set(FACT_ROLES) == all_facts, "FACT_ROLES covers every key fact exactly", str(sorted(set(FACT_ROLES) ^ all_facts)))
    res.check(all(set(v) <= set(ROLE_ORDER) | {"home"} for v in FACT_ROLES.values()), "FACT_ROLES uses only sampler roles")
    res.check("### 1b." in sc, "site_categories.md has section 1b (where each key fact is expected)")
    section1b = sc.split("### 1b.")[-1].split("\n## 2.")[0]
    for fid in sorted(all_facts):
        res.check("`%s`" % fid in section1b, "site_categories 1b names key fact %s" % fid)
    refs = os.path.join(ROOT, "skills", "audit-orchestrator", "references")
    schema = open(os.path.join(refs, "report_schema.md"), encoding="utf-8").read()
    rubric = open(os.path.join(refs, "severity_confidence_rubric.md"), encoding="utf-8").read()
    for reason in C.GATE_REASONS:
        res.check(reason in schema, "report_schema.md documents the gate reason %s" % reason)
    res.check("absence_scope" in schema and "language_scope" in schema, "report_schema.md documents absence_scope and language_scope")
    res.check("Absence scope" in rubric and "Language scope" in rubric, "the rubric lists the absence and language gates as adjustment rules")


def stage_compose(res, farm):
    from auditlib.findings import Registry as _Reg
    expected_checks = len(_Reg().rows)   # derived, never hardcoded: adding a check must not need a test edit
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
                facts = _read_json(os.path.join(td, "work", "extracted_facts.json"), encoding="utf-8")
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
        # the absence gate's contract: `gated` checks lose their verdict (coverage carries the reason, no finding
        # remains), `scoped` findings are marked as sample claims, and `max_severity` / `max_confidence` pin caps
        from auditlib.findings import SEVERITIES as _SEV, CONFIDENCES as _CONF
        reasons = {e["check_id"]: e["reason"] for e in report["coverage"]["not_evaluated"]}
        gated = set(exp.get("gated", []))
        withdrawal_reasons = C.GATE_REASONS + ("language_not_supported",)
        for cid in sorted(gated):
            res.check(reasons.get(cid) in withdrawal_reasons, "compose/%s: %s is withdrawn by a gate" % (name, cid), str(reasons.get(cid)))
        leaked = gated & {f["check_id"] for f in fnds + report["suppressed_findings"]}
        res.check(not leaked, "compose/%s: a gated check produces no finding" % name, str(sorted(leaked)))
        if gated:
            res.check(any(l.startswith("Not checked, because") or "navigation could not be read" in l
                          or "phrase lists behind these checks are English" in l for l in report["limitations"]),
                      "compose/%s: limitations explain the gated checks" % name)
        cov_reasons = _coverage_reasons(report)
        for cid, reason in sorted((exp.get("not_evaluated") or {}).items()):
            res.check(cov_reasons.get(cid) == reason, "compose/%s: coverage records %s as having no verdict (%s)" % (name, cid, reason), str(cov_reasons.get(cid)))
        by_cid = {f["check_id"]: f for f in fnds}
        for cid in exp.get("scoped", []):
            f = by_cid.get(cid)
            res.check(f is not None and f.get("absence_scope") == "sample", "compose/%s: %s is scoped to the sample" % (name, cid),
                      str(f.get("absence_scope")) if f else "no finding")
        for cid, cap in (exp.get("max_severity") or {}).items():
            f = by_cid.get(cid)
            res.check(f is not None and _SEV.index(f["severity"]) >= _SEV.index(cap),
                      "compose/%s: %s severity is at most %s" % (name, cid, cap), f["severity"] if f else "no finding")
        for cid, cap in (exp.get("max_confidence") or {}).items():
            f = by_cid.get(cid)
            res.check(f is not None and _CONF.index(f["confidence"]) >= _CONF.index(cap),
                      "compose/%s: %s confidence is at most %s" % (name, cid, cap), f["confidence"] if f else "no finding")
        for f in fnds:
            res.check(f.get("quick_win") == C.is_quick_win(f), "compose/%s: %s quick-win flag follows the rubric" % (name, f["id"]))
            res.check(f.get("source_skill") and f.get("opportunity_type") in ("technical", "content"),
                      "compose/%s: %s carries its source skill and opportunity type" % (name, f["id"]))
            res.check("_suppressed" not in f and "_max_severity" not in f, "compose/%s: %s has no internal fields" % (name, f["id"]))
        res.check(report["quick_wins"] == [f["id"] for f in fnds if f["quick_win"]], "compose/%s: quick_wins lists the flagged ids" % name)
        # where to start: the headline is in the JSON and the Markdown; the Quick wins section never vanishes while defects exist
        res.check(isinstance(s.get("headline"), str) and s["headline"].strip() and s["headline"] in md,
                  "compose/%s: the summary opens with a headline the Markdown carries" % name)
        sw = s.get("start_with")
        res.check("start_with" in s and sw == C.start_with(fnds, report["quick_wins"]),
                  "compose/%s: start_with follows the rule" % name, str(sw))
        if sw:
            qsec = md.split("## Quick wins")[1].split("## Findings")[0] if "## Quick wins" in md else ""
            res.check(sw in {f["id"] for f in fnds if f["severity"] != "info"} and sw in qsec,
                      "compose/%s: the Quick wins section names where to start (%s)" % (name, sw))
            if not report["quick_wins"]:
                res.check("None qualify" in qsec, "compose/%s: an empty quick-win list says so instead of vanishing" % name)
        else:
            res.check("## Quick wins" not in md, "compose/%s: no Quick wins section when nothing is above info" % name)
        if name == "unsampled-contact-nonprofit":
            kf = next((f["id"] for f in fnds if f["check_id"] == "fx.facts.key_fact_missing"), None)
            res.check(not report["quick_wins"] and sw == kf,
                      "compose/unsampled-contact-nonprofit: no quick win qualifies, so start_with is the confirmed key-fact finding",
                      str((report["quick_wins"], sw, kf)))
        res.check(all(f.get("merged_into") for f in report["suppressed_findings"]),
                  "compose/%s: every folded finding names the finding it went into" % name)
        res.check(report["ai_answer_simulation"]["basis"] == "extracted_facts_only", "compose/%s: simulation basis is fixed" % name)
        # A report leaves the script finished: every answerable question carries an answer that quotes the
        # facts it cites, and the narrative is written. An unanswerable question still carries no answer.
        sim_qs = report["ai_answer_simulation"]["questions"]
        res.check(all(q["answer_from_facts"] is None for q in sim_qs if not q["answerable"]),
                  "compose/%s: an unanswerable question carries no answer" % name)
        res.check(all(q["answer_from_facts"] and q["facts_used"] for q in sim_qs if q["answerable"] and q["facts_used"]),
                  "compose/%s: every answerable question is answered from the facts it names" % name)
        narrative = report["narrative_summary"]
        res.check(isinstance(narrative, str) and 3 <= len(re.findall(r"[.!?](?:\s|$)", narrative)) <= 6,
                  "compose/%s: the narrative is written, in three to six sentences" % name, narrative[:120])
        res.check(len(report["passed_checks"]) == s["checks_passed"], "compose/%s: passed_checks matches the count" % name)
        res.check(s["checks_run"] == expected_checks, "compose/%s: every registered check has a verdict (%d of %d)" % (name, s["checks_run"], expected_checks))
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
        if name in CLEAN_SITES:
            res.check(not [f for f in fnds if f["severity"] != "info"], "compose/%s: no defect is reported" % name,
                      str([f["check_id"] for f in fnds if f["severity"] != "info"]))
            res.check(len(report["proactive_recommendations"]) >= 3, "compose/%s: proactive recommendations are populated" % name)
            res.check(s["checks_passed"] >= 50, "compose/%s: nearly every check passes (%d)" % (name, s["checks_passed"]))
            # an engagement check that honestly has no verdict here (a listing page cannot be graded for related
            # links) makes the stage "partial", and the fixture's not_evaluated contract says which one
            en_open = [c for c, r in (exp.get("not_evaluated") or {}).items() if c.startswith("en.") and r != "not_applicable_for_category"]
            want_stage = "partial" if en_open else "evaluated"
            res.check(report["coverage"]["stages"]["engagement"] == want_stage, "compose/%s: engagement stage %s" % (name, want_stage),
                      str(report["coverage"]["stages"]["engagement"]))
            res.check(report["coverage"]["handout_concepts"]["A"] == "covered", "compose/%s: concept A covered" % name)
            res.check("## Quick wins" not in md, "compose/%s: no quick-wins section on a clean site" % name)
            res.check(not [q for q in report["ai_answer_simulation"]["questions"]
                           if not q["answerable"] and not q.get("informational")],
                      "compose/%s: every real question is answerable from the facts file" % name)
            res.check(report["site_category"]["value"] == farm.metas[name]["category"] and report["site_category"]["confidence"] in ("high", "medium"),
                      "compose/%s: the report states the fixture's category (%s)" % (name, report["site_category"]["value"]))
        if name == "csr-shell":
            sim = [f for f in fnds if f["check_id"] == "or.simulation.question_unanswerable"]
            res.check(sim and sim[0]["severity"] == "info", "compose/csr-shell: unanswerable questions are reported as info")
            res.check(sim and sim[0]["status"] == "not_evaluated" and sim[0].get("reason") == "no_readable_pages",
                      "compose/csr-shell: with nothing readable the simulation is not_evaluated, not 'the site is silent'", str(sim[0].get("reason")))
            open_qs = [q for q in report["ai_answer_simulation"]["questions"] if not q["answerable"] and not q.get("informational")]
            res.check(open_qs and all(q.get("see_finding") in {f["id"] for f in fnds} for q in open_qs),
                      "compose/csr-shell: every unanswerable question points at the finding that explains it",
                      str([q.get("see_finding") for q in open_qs]))
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
        base = _read_json(os.path.join(td, "report.json"), encoding="utf-8")
        facts = _read_json(os.path.join(td, "work", "extracted_facts.json"), encoding="utf-8")
        res.check(V.main(["--workdir", td, "--quiet"]) == 0, "validate: CLI accepts a composed workdir")
        res.check(V.main(["--workdir", td, "--final", "--quiet"]) == 0,
                  "validate: CLI accepts a freshly composed report with --final")
        unfinished = dict(base, narrative_summary="")
        _write_json(os.path.join(td, "unfinished.json"), unfinished)
        res.check(V.main(["--report", os.path.join(td, "unfinished.json"), "--facts", os.path.join(td, "work", "extracted_facts.json"),
                          "--final", "--quiet"]) == 1,
                  "validate: CLI rejects a report whose narrative was emptied with --final")
        good = _finalise(base, facts)
        with open(os.path.join(td, "report.json"), "w", encoding="utf-8") as f:
            json.dump(good, f)
        res.check(V.main(["--workdir", td, "--final", "--quiet"]) == 0, "validate: CLI accepts a finalised report with --final")
        res.check(V.main(["--report", os.path.join(td, "nope.json"), "--quiet"]) == 1, "validate: a missing file is a problem, not a crash")
        with open(os.path.join(td, "bad.json"), "w", encoding="utf-8") as f:
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
    broken("headline missing", setf(["summary", "headline"], ""), "headline", expect_floor=False)
    broken("start_with wrong", setf(["summary", "start_with"], "F-099"), "start_with", expect_floor=False)
    broken("start_with absent", delf(["summary", "start_with"]), "start_with", expect_floor=False)
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
    broken("see_finding naming no finding", lambda r: r["ai_answer_simulation"]["questions"][-1].update(see_finding="F-777"),
           "see_finding", expect_floor=False)
    # finalize.py: the agent writes a small answers file; the script merges, renders and validates --final
    def _load_finalize():
        import importlib.util
        path = os.path.join(ROOT, "skills", "audit-orchestrator", "scripts", "finalize.py")
        spec = importlib.util.spec_from_file_location("finalize", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    F = _load_finalize()
    with tempfile.TemporaryDirectory() as td:
        _build_workdir(farm.urls["weak-engagement"], td)
        C.main(["--workdir", td, "--quiet"])
        answers = {"answers": {q["id"]: {"answer_from_facts": " ".join('"%s"' % facts["facts"][fid]["value"] for fid in q["facts_used"])}
                               for q in good["ai_answer_simulation"]["questions"] if q["answerable"]},
                   "attribution_note": good["ai_answer_simulation"]["attribution_note"],
                   "narrative_summary": good["narrative_summary"]}
        apath = os.path.join(td, "answers.json")
        with open(apath, "w", encoding="utf-8") as f:
            json.dump(answers, f)
        res.check(F.main(["--workdir", td, "--answers", apath, "--quiet"]) == 0, "finalize: merges a verbatim answers file into a final report")
        res.check(V.main(["--workdir", td, "--final", "--quiet"]) == 0, "finalize: the report it wrote passes validate --final")
        merged = _read_json(os.path.join(td, "report.json"), encoding="utf-8")
        res.check(merged["narrative_summary"] == good["narrative_summary"] and all(
            q["answer_from_facts"] for q in merged["ai_answer_simulation"]["questions"] if q["answerable"]),
            "finalize: answers and narrative land on the right fields")
        md = open(os.path.join(td, "report.md"), encoding="utf-8").read()
        res.check("## What this means" in md and good["narrative_summary"][:40] in md, "finalize: the narrative is rendered into the Markdown")
        bad = json.loads(json.dumps(answers))
        first = next(q["id"] for q in good["ai_answer_simulation"]["questions"] if q["answerable"])
        bad["answers"][first] = {"answer_from_facts": "It is an invoicing product for designers, roughly speaking."}
        with open(apath, "w", encoding="utf-8") as f:
            json.dump(bad, f)
        res.check(F.main(["--workdir", td, "--answers", apath, "--quiet"]) == 1, "finalize: a paraphrased answer is rejected")
        bad = json.loads(json.dumps(answers))
        unanswerable = next(q["id"] for q in good["ai_answer_simulation"]["questions"] if not q["answerable"])
        bad["answers"][unanswerable] = {"answer_from_facts": "Probably the best."}
        with open(apath, "w", encoding="utf-8") as f:
            json.dump(bad, f)
        res.check(F.main(["--workdir", td, "--answers", apath, "--quiet"]) == 1, "finalize: an answer on an unanswerable question is refused")
        bad = json.loads(json.dumps(answers))
        bad["narrative_summary"] = ""
        with open(apath, "w", encoding="utf-8") as f:
            json.dump(bad, f)
        res.check(F.main(["--workdir", td, "--answers", apath, "--quiet"]) == 1, "finalize: an empty narrative is not final")
        with open(apath, "w", encoding="utf-8") as f:
            f.write("{oops")
        res.check(F.main(["--workdir", td, "--answers", apath, "--quiet"]) == 1, "finalize: an unreadable answers file is a problem, not a crash")
        res.check(F.main(["--workdir", os.path.join(td, "nowhere"), "--answers", apath, "--quiet"]) == 1, "finalize: a missing report is a problem, not a crash")
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


# ---------------------------------------------------------------- stage: run_audit (the whole pipeline, as a command)
def _load_run_audit():
    import importlib.util
    path = os.path.join(ROOT, "skills", "audit-orchestrator", "scripts", "run_audit.py")
    spec = importlib.util.spec_from_file_location("run_audit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUN_AUDIT = os.path.join(ROOT, "skills", "audit-orchestrator", "scripts", "run_audit.py")


def _run_cli(args, timeout=180):
    import subprocess
    proc = subprocess.run([sys.executable, RUN_AUDIT] + args, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def stage_run_audit(res, farm):
    from auditlib.findings import Registry as _Reg
    expected_checks = len(_Reg().rows)   # derived, never hardcoded: adding a check must not need a test edit
    print("\n== stage: run_audit end to end on every fixture")
    import tempfile
    import time as _time
    V = _load_validate()
    C = _load_compose()
    R = _load_run_audit()
    for name, base in farm.urls.items():
        exp = farm.metas[name]["expected"]
        with tempfile.TemporaryDirectory() as td:
            wd = os.path.join(td, "run")
            t0 = _time.time()
            code, blob = _run_cli([base, "--workdir", wd, "--quiet"])
            elapsed = _time.time() - t0
            res.check(code == 0, "run_audit/%s: exits 0" % name, blob.strip()[-200:])
            res.check("Traceback" not in blob, "run_audit/%s: no traceback in any output" % name, blob.strip()[-200:])
            res.check(elapsed < 60, "run_audit/%s: finishes well inside the 5 minute limit (%.1fs)" % (name, elapsed))
            ok = os.path.exists(os.path.join(wd, "report.json")) and os.path.exists(os.path.join(wd, "report.md"))
            res.check(ok, "run_audit/%s: writes report.json and report.md" % name)
            if not ok:
                continue
            report = _read_json(os.path.join(wd, "report.json"), encoding="utf-8")
            facts_rel = (report.get("ai_answer_simulation") or {}).get("facts_file")
            facts = None
            if facts_rel and os.path.exists(os.path.join(wd, facts_rel)):
                facts = _read_json(os.path.join(wd, facts_rel), encoding="utf-8")
            probs, _ = V.validate_report(report, facts)
            res.check(not probs, "run_audit/%s: the report it wrote is valid" % name, "; ".join(probs[:3]))
            run = report.get("run") or {}
            res.check(len(run.get("probes") or []) == 4 and not [p for p in run["probes"] if p["error"]],
                      "run_audit/%s: all four probes completed" % name,
                      str([(p["probe"], p["error"]) for p in (run.get("probes") or []) if p["error"]]))
            res.check(report["summary"]["checks_run"] == expected_checks, "run_audit/%s: every registered check has a verdict (%d of %d)" % (name, report["summary"]["checks_run"], expected_checks))
            res.check(isinstance(run.get("wall_clock_seconds"), float), "run_audit/%s: records its wall clock" % name)
            seen = {f["check_id"] for f in report["findings"] + report["suppressed_findings"] if f["severity"] != "info"}
            res.check(seen == set(exp["fail"]), "run_audit/%s: the whole pipeline reproduces the fixture's fail set" % name,
                      "got %s expected %s" % (sorted(seen), sorted(exp["fail"])))
            reasons = _coverage_reasons(report)
            withdrawal_reasons = C.GATE_REASONS + ("language_not_supported",)
            for cid in exp.get("gated", []):
                res.check(reasons.get(cid) in withdrawal_reasons,
                          "run_audit/%s: %s has no verdict end to end" % (name, cid), str(reasons.get(cid)))
            for cid, reason in sorted((exp.get("not_evaluated") or {}).items()):
                res.check(reasons.get(cid) == reason, "run_audit/%s: %s has no verdict end to end (%s)" % (name, cid, reason), str(reasons.get(cid)))
            md = open(os.path.join(wd, "report.md"), encoding="utf-8").read()
            res.check(md.startswith("# AI-readiness audit: "), "run_audit/%s: the Markdown is rendered" % name)

    print("\n== stage: run_audit (budget, reuse, offline, and the guards)")
    with tempfile.TemporaryDirectory() as td:
        wd = os.path.join(td, "run")
        code, _ = _run_cli([farm.urls["clean-site"], "--workdir", wd, "--quiet"])
        res.check(code == 0, "run_audit: first pass over clean-site")
        sample = _read_json(os.path.join(wd, "sample.json"), encoding="utf-8")
        code, blob = _run_cli(["--workdir", wd, "--quiet"])
        res.check(code == 0, "run_audit: --workdir alone re-runs the probes", blob[-200:])
        again = _read_json(os.path.join(wd, "sample.json"), encoding="utf-8")
        res.check(again["sampled_at"] == sample["sampled_at"] and again["requests_made"] == sample["requests_made"],
                  "run_audit: --workdir alone does not re-sample the site")
        code, blob = _run_cli(["--workdir", wd, "--offline", "--quiet"])
        res.check(code == 0, "run_audit: --offline completes", blob[-200:])
        report = _read_json(os.path.join(wd, "report.json"), encoding="utf-8")
        reasons = {e["check_id"]: e["reason"] for e in report["coverage"]["not_evaluated"]}
        res.check(reasons.get("en.links.broken_sampled") == "network_disabled",
                  "run_audit: --offline marks the network checks not_evaluated", str(reasons)[:160])
        facts_path = os.path.join(wd, "work", "extracted_facts.json")
        offline_facts = _read_json(facts_path, encoding="utf-8") if os.path.exists(facts_path) else None
        probs, _ = V.validate_report(report, offline_facts)
        res.check(not probs, "run_audit: the offline report is still valid", "; ".join(probs[:3]))
        code, _ = _run_cli(["--workdir", wd, "--no-network", "--quiet"])
        report = _read_json(os.path.join(wd, "report.json"), encoding="utf-8")
        res.check(code == 0 and any(e["check_id"].startswith("en.links") for e in report["coverage"]["not_evaluated"]),
                  "run_audit: --no-network skips only the engagement network checks")
        code, blob = _run_cli(["--workdir", wd, "--time-budget", "9"])
        report = _read_json(os.path.join(wd, "report.json"), encoding="utf-8")
        probs, _ = V.validate_report(report, None)
        res.check(not probs, "run_audit: a starved run still writes a valid report", "; ".join(probs[:3]))
        res.check(any(f["check_id"] == "or.run.probe_error" for f in report["findings"]),
                  "run_audit: a starved run reports or.run.probe_error")
        res.check(all(p["error"] for p in report["run"]["probes"]),
                  "run_audit: a starved run skips the probes rather than killing them")
        res.check("did not finish" in blob, "run_audit: a starved run says so on stdout", blob[-160:])
        code, _ = _run_cli(["--workdir", wd, "--category", "local_business", "--quiet"])
        report = _read_json(os.path.join(wd, "report.json"), encoding="utf-8")
        res.check(code == 0 and report["site_category"]["value"] == "local_business",
                  "run_audit: --category overrides the inferred category everywhere")
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead_port = sock.getsockname()[1]
    sock.close()
    with tempfile.TemporaryDirectory() as td:
        code, blob = _run_cli(["http://127.0.0.1:%d/" % dead_port, "--workdir", os.path.join(td, "run"), "--quiet"])
        res.check("Traceback" not in blob, "run_audit/unreachable: no traceback", blob[-200:])
        report = _read_json(os.path.join(td, "run", "report.json"), encoding="utf-8")
        probs, _ = V.validate_report(report, None)
        res.check(not probs, "run_audit/unreachable: the report is valid", "; ".join(probs[:3]))
        top = report["findings"][0] if report["findings"] else {}
        res.check(top.get("check_id") == "cr.access.http_error" and top.get("severity") == "critical",
                  "run_audit/unreachable: the first finding is the unreachable home page", str(top.get("check_id")))
        res.check(not [f for f in report["findings"] if f["check_id"].startswith(("en.", "fx.")) and f["severity"] != "info"],
                  "run_audit/unreachable: nothing downstream is graded as a defect")
    with tempfile.TemporaryDirectory() as td:
        fake = os.path.join(td, "crawl-render-audit", "scripts")
        os.makedirs(fake)
        with open(os.path.join(fake, "boom.py"), "w", encoding="utf-8") as f:
            f.write("raise SystemError('probe exploded')\n")
        with open(os.path.join(fake, "sleep.py"), "w", encoding="utf-8") as f:
            f.write("import time\ntime.sleep(30)\n")
        real_dir, R.SKILLS_DIR = R.SKILLS_DIR, td
        try:
            wd = os.path.join(td, "wd")
            os.makedirs(os.path.join(wd, "probes"))
            seconds, error = R.run_probe("crawl-render-audit", "boom.py", wd, 30)
            res.check(error and "crashed" in error, "run_audit: a crashing probe is reported, not raised", str(error))
            seconds, error = R.run_probe("crawl-render-audit", "sleep.py", wd, 2)
            res.check(error and "timed out" in error and seconds < 10,
                      "run_audit: a hanging probe is killed at its timeout", "%s after %.1fs" % (error, seconds))
        finally:
            R.SKILLS_DIR = real_dir
    res.check(R.default_workdir("https://example.com/x").startswith("audit-example.com-"),
              "run_audit: the default workdir follows report_schema section 5", R.default_workdir("https://example.com/"))
    res.check(_run_cli(["--quiet"])[0] != 0, "run_audit: no URL and no workdir is an error, not a crash")


# ---------------------------------------------------------------- stage: scripts (every script, every usage path, no traceback)
SCRIPTS = {
    "crawl_probe.py": "crawl-render-audit", "facts_probe.py": "fact-extractability-audit",
    "entity_probe.py": "entity-freshness-corroboration-audit", "engagement_probe.py": "engagement-audit",
    "run_audit.py": "audit-orchestrator", "compose.py": "audit-orchestrator", "validate.py": "audit-orchestrator",
    "finalize.py": "audit-orchestrator", "sample_site.py": "audit-orchestrator", "fetch_url.py": "audit-orchestrator",
}


def _invoke(script, args, cwd=None, timeout=150):
    """Run one script exactly as a SKILL.md would: python3 <path> <args>, from the marketplace root by default."""
    import subprocess
    path = os.path.join(ROOT, "skills", SCRIPTS[script], "scripts", script)
    try:
        proc = subprocess.run([sys.executable, path] + list(args), capture_output=True, text=True,
                              timeout=timeout, cwd=cwd or ROOT)
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT after %ds" % timeout
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def stage_scripts(res, farm):
    print("\n== stage: every script, every usage path: no traceback ever reaches stdout or stderr")
    import socket
    import tempfile
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    refused = "http://127.0.0.1:%d/" % sock.getsockname()[1]
    sock.close()
    good = farm.urls["clean-site"]
    with tempfile.TemporaryDirectory() as td:
        wd = os.path.join(td, "wd")
        code, blob = _invoke("run_audit.py", [good, "--workdir", wd, "--quiet"])
        res.check(code == 0 and "Traceback" not in blob, "scripts: a reference workdir was built", blob[-200:])
        missing = os.path.join(td, "missing")           # a path that does not exist and is writable
        nofile = os.path.join(td, "nofile.json")
        probes = ("crawl_probe.py", "facts_probe.py", "entity_probe.py", "engagement_probe.py")
        # (script, args, allowed exit codes or None for "any, but no traceback")
        matrix = []
        for sc in probes:
            matrix += [(sc, [], (2,)), (sc, ["--help"], (0,)), (sc, ["--bogus-flag"], (2,)),
                       (sc, ["--workdir", missing], (0,)), (sc, ["--workdir", wd], (0,)),
                       (sc, ["--workdir", wd, "--offline"], (0,)), (sc, ["--workdir", wd, "--category", "no_such_category"], (0,)),
                       (sc, ["--url", good, "--workdir", os.path.join(td, "u-" + sc)], (0,)),
                       (sc, ["--url", "not a url at all"], (0,)), (sc, ["--url", refused], (0,)),
                       (sc, ["--url", good, "--workdir", os.path.join(td, "u-" + sc), "--out", os.path.join(td, "o-" + sc + ".json")], (0,))]
        matrix += [
            ("run_audit.py", [], (2,)), ("run_audit.py", ["--help"], (0,)), ("run_audit.py", ["--bogus-flag"], (2,)),
            ("run_audit.py", ["--workdir", missing], (1,)), ("run_audit.py", ["not a url at all", "--workdir", os.path.join(td, "r1"), "--quiet"], None),
            ("run_audit.py", [refused, "--workdir", os.path.join(td, "r2"), "--quiet"], (0,)),
            ("run_audit.py", [good, "--workdir", os.path.join(td, "r3"), "--time-budget", "-5", "--quiet"], (0,)),
            ("run_audit.py", ["--workdir", wd, "--offline", "--quiet"], (0,)),
            ("compose.py", [], (2,)), ("compose.py", ["--help"], (0,)), ("compose.py", ["--workdir", missing, "--quiet"], (0,)),
            ("compose.py", ["--workdir", wd, "--quiet"], (0,)), ("compose.py", ["--workdir", wd, "--render-only", "--quiet"], (0,)),
            ("compose.py", ["--workdir", os.path.join(td, "empty-c"), "--render-only", "--quiet"], (0,)),
            ("compose.py", ["--workdir", wd, "--category", "no_such_category", "--quiet"], (0,)),
            ("validate.py", [], (2,)), ("validate.py", ["--help"], (0,)),
            ("validate.py", ["--workdir", os.path.join(td, "never-written")], (1,)),
            ("validate.py", ["--report", nofile], (1,)), ("validate.py", ["--workdir", wd, "--quiet"], (0,)),
            # a composed report is finished as it leaves compose.py, so --final accepts it
            ("validate.py", ["--workdir", wd, "--final", "--quiet"], (0,)),
            ("finalize.py", [], (2,)), ("finalize.py", ["--help"], (0,)),
            ("finalize.py", ["--workdir", missing, "--answers", nofile], (1,)),
            ("finalize.py", ["--workdir", wd, "--answers", nofile], (1,)),
            # an answers file carrying no answers changes nothing, and the report was already valid
            ("finalize.py", ["--workdir", wd, "--answers", os.path.join(wd, "sample.json")], (0,)),
            ("sample_site.py", [], (2,)), ("sample_site.py", ["--help"], (0,)),
            ("sample_site.py", [good, "--workdir", os.path.join(td, "s1"), "--quiet"], (0,)),
            ("sample_site.py", [good, "--category", "no_such_category"], (2,)),
            ("sample_site.py", ["not a url at all", "--quiet"], None), ("sample_site.py", [refused, "--quiet"], None),
            ("sample_site.py", [good, "--offline", "--quiet"], (0,)),
            ("fetch_url.py", [], (2,)), ("fetch_url.py", ["--help"], (0,)), ("fetch_url.py", [good], (0,)),
            ("fetch_url.py", [good, "--robots"], (0,)), ("fetch_url.py", [good, "--body", "--workdir", os.path.join(td, "f1")], (0,)),
            ("fetch_url.py", ["not a url at all"], None), ("fetch_url.py", [refused], None), ("fetch_url.py", [good, "--offline"], (0,)),
        ]
        for script, args, codes in matrix:
            code, blob = _invoke(script, args)
            label = "%s %s" % (script, " ".join(a if len(a) < 40 else "<path>" for a in args) or "(no args)")
            res.check(code is not None and "Traceback" not in blob, "scripts: %s emits no traceback" % label, blob.strip()[-220:])
            if codes is not None:
                res.check(code in codes, "scripts: %s exits %s" % (label, "/".join(map(str, codes))), "exit %s: %s" % (code, blob.strip()[-160:]))
        # the scripts do not depend on the working directory: every SKILL.md says "from the marketplace root",
        # but an agent that runs them from elsewhere must get the same result
        for script, args in (("crawl_probe.py", ["--workdir", wd]), ("compose.py", ["--workdir", wd, "--quiet"]),
                             ("validate.py", ["--workdir", wd, "--quiet"]), ("run_audit.py", ["--workdir", wd, "--offline", "--quiet"])):
            code, blob = _invoke(script, args, cwd=td)
            res.check(code == 0 and "Traceback" not in blob, "scripts: %s works from a foreign working directory" % script, blob[-200:])
        # every probe's --help documents --url, --workdir and --category, which the orchestrator relies on
        for sc in probes:
            code, blob = _invoke(sc, ["--help"])
            res.check(all(flag in blob for flag in ("--url", "--workdir", "--out", "--offline", "--category")),
                      "scripts: %s --help lists the shared flags" % sc)
    # the shared library never prints: a probe's stdout is its JSON and nothing else
    with tempfile.TemporaryDirectory() as td:
        code, blob = _invoke("crawl_probe.py", ["--url", farm.urls["weak-engagement"], "--workdir", td])
        try:
            json.loads(blob)
            clean = True
        except ValueError:
            clean = False
        res.check(code == 0 and clean, "scripts: a probe's stdout is exactly one JSON document", blob[:160])


# ---------------------------------------------------------------- stage: probe_cr (crawl-render probe on fixtures)
def stage_probe_cr(res, farm):
    print("\n== stage: crawl-render probe on every fixture")
    cp = _load_probe("crawl-render-audit", "crawl_probe.py")
    R = run_probe_on_fixtures(res, farm, "cr.", cp, "cr")
    # policy is not behaviour: the edge probe never announces a token robots.txt disallows, and never grades one
    st = lambda name, cid: next(((c["status"], c.get("reason")) for c in R[name]["checks"] if c["check_id"] == cid), None)  # noqa: E731
    fnd = lambda name, cid: next((f for f in R[name]["findings"] if f["check_id"] == cid), None)  # noqa: E731
    res.check(all(st("edge-enforces-policy", cid) == ("not_evaluated", "probe_tokens_disallowed") for cid in
                  ("cr.access.edge_block", "cr.access.edge_block_training", "cr.access.ua_content_variance")),
              "cr/edge-enforces-policy: every edge check is not_evaluated with reason probe_tokens_disallowed",
              str([st("edge-enforces-policy", c) for c in ("cr.access.edge_block", "cr.access.edge_block_training")]))
    res.check(fnd("edge-enforces-policy", "cr.access.edge_block") is None, "cr/edge-enforces-policy: enforcing one's own robots.txt is never a second finding")
    f = fnd("edge-blocked-mixed", "cr.access.edge_block")
    res.check(f is not None and f["severity"] == "critical", "cr/edge-blocked-mixed: the two robots-allowed citation-tier tokens refused at the edge is critical",
              str(f and f["severity"]))
    res.check(f is not None and "GPTBot not probed" in json.dumps(f["evidence_items"]) and "robots.txt allows these agents" in f["evidence"],
              "cr/edge-blocked-mixed: the evidence names the policy token as not probed and says robots.txt allows the probed ones")
    res.check(f is not None and "GPTBot" not in f["evidence"].split("but", 1)[-1].split(". robots")[0],
              "cr/edge-blocked-mixed: the policy token is not counted among the refused crawlers")
    res.check(st("edge-blocked-mixed", "cr.access.edge_block_training") == ("pass", None), "cr/edge-blocked-mixed: a training token that was policy is not an edge note")
    f = fnd("edge-refuses-auditor", "cr.access.http_error")
    res.check(f is not None and f["status"] == "inconclusive" and f["severity"] == "info" and f.get("reason") == "crawler_access_unknown",
              "cr/edge-refuses-auditor: a refusal the audit cannot explain is inconclusive, never critical", str(f and (f["status"], f["severity"], f.get("reason"))))
    res.check(f is not None and "disallowed by the site's own robots.txt" in f["evidence"], "cr/edge-refuses-auditor: the evidence says why nothing could be probed")
    res.check(not [x for x in R["edge-refuses-auditor"]["findings"] if x["severity"] == "critical"], "cr/edge-refuses-auditor: no critical finding at all")
    # a hung crawler probe is inconclusive, never a critical refusal (adobe.com, dry-run judging)
    import types as _t
    from auditlib.findings import ProbeOutput as _PO
    hung = {"url": "https://x/", "baseline": {"user_agent": "audit", "status": 200, "bytes": 45662},
            "agents": [{"token": "OAI-SearchBot", "tier": "index", "status": None, "bytes": 0, "error": "read_timeout", "challenge": False, "robots_rule": None},
                       {"token": "Claude-User", "tier": "live_answer", "status": None, "bytes": 0, "error": "read_timeout", "challenge": False, "robots_rule": None},
                       {"token": "GPTBot", "tier": "training_only", "status": None, "bytes": 0, "error": "read_timeout", "challenge": False, "robots_rule": None}],
            "policy": [], "reason": None}
    o = _PO("crawl-render-audit", "https://x", "unknown", [])
    cp.check_edge_access(_t.SimpleNamespace(edge_access=hung), o)
    e = next((f for f in o.findings if f["check_id"] == "cr.access.edge_block"), None)
    res.check(e is not None and e["status"] == "inconclusive" and e["severity"] == "info" and e.get("reason") == "probe_timeout",
              "cr/edge: three timed-out probes are inconclusive probe_timeout, not a critical refusal", str(e and (e["status"], e["severity"])))
    res.check(e is not None and "curl -A" in e["suggested_action"]["detail"] and "not a refusal" in e["evidence"], "cr/edge: the timeout note tells the owner how to check")
    hung["agents"][0].update(error=None, status=403)
    o = _PO("crawl-render-audit", "https://x", "unknown", [])
    cp.check_edge_access(_t.SimpleNamespace(edge_access=hung), o)
    e = next(f for f in o.findings if f["check_id"] == "cr.access.edge_block")
    res.check(e["status"] == "fail" and "OAI-SearchBot" in e["evidence"] and "Claude-User" not in e["evidence"].split("but", 1)[-1].split(". robots")[0],
              "cr/edge: a real 403 beside a timeout is a fail that names only the refused token")
    f = fnd("edge-blocked-bots", "cr.access.edge_block")
    res.check(f is not None and f["severity"] == "critical" and "robots.txt allows these agents" in f["evidence"],
              "cr/edge-blocked-bots: the real defect (robots open, edge refuses) is still critical, and its evidence is now true by construction")
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

    # find_participation must prefer a real link over a text-window match that lands on nav chrome. This is
    # the python.org defect: "Donate" inside a flattened nav strip quoted as an answer to "how do I donate?".
    chrome_nav = mk('<nav><div>The Python Network</div><a href="/donate">Donate</a><span>≡</span>'
                     '<div>Menu Search This Site</div><div>GO A A Smaller Larger Reset</div></nav>')
    part = X.find_participation([chrome_nav])
    res.check(part is not None and part["value"] == "Donate" and part["source"] == "link",
              "participation: a real link wins over a chrome text window", str(part))
    prose = mk("<p>Please donate today to help fund our programs.</p>")
    part2 = X.find_participation([prose])
    res.check(part2 is not None and "donate" in part2["value"].lower() and part2["source"] == "text",
              "participation: a genuine sentence is still found in text", str(part2))
    chrome_only = mk('<div>The Network Donate ≡ Menu Search This Site GO A A Smaller Larger Reset</div>')
    res.check(X.find_participation([chrome_only]) is None,
              "participation: a chrome-only window with no link or heading is absent, not quoted")
    us = mk("<p>Contact: 500 Market St, San Francisco, CA 94105</p>")
    res.check(X.find_address([us]) is not None, "address: US street/city/state/zip found")

    # Non-Anglo address formats. A grammar that cannot match one of these does not report "I could not
    # check"; it reports "the address is not there", which is a false claim about the site.
    intl = [("Okhla Industrial Estate, Phase III, New Delhi, India - 110020", "IN pin after country"),
            ("No. 42, 4th Cross, Indiranagar, Bengaluru, Karnataka 560038", "IN pin after state"),
            ("Adresse: Hauptstrasse 12, 10115 Berlin, Deutschland", "DE street-then-number"),
            ("Musterstraße 5, 80331 München", "DE eszett street"),
            ("Sitz der Gesellschaft:\n50667 Köln", "DE postcode with cue, no street"),
            ("Am Markt, 04109 Leipzig, Deutschland", "DE postcode with country adjacent"),
            ("Kerkweg 118, 3512 Utrecht", "NL street-then-number"),
            ("Via Montenapoleone 8, 20121 Milano", "IT via-then-number"),
            ("Calle de Alcala 45, 28014 Madrid", "ES calle-then-number"),
            ("12 Rue de Rivoli, 75001 Paris, France", "FR number-then-rue"),
            ("〒100-0005 東京都千代田区", "JP postal mark")]
    for text, what in intl:
        res.check(X.find_address([mk("<p>%s</p>" % text)]) is not None, "address: %s" % what)

    # A postcode-and-city shape is the same shape as a statistic. Without a postal cue nearby it must not count.
    for text, what in [("Trusted by 40000 Developers worldwide", "headline count"),
                       ("We processed 12000 orders, 45000 Requests handled", "stat after comma"),
                       ("Set your IP address. Limits: 10000 calls, 60000 Requests daily", "IP address is not a postal cue"),
                       ("Download the zip; 45000 Downloads so far", "zip file is not a postcode cue"),
                       ("Founded 1998, 2015 Series B closed", "years")]:
        res.check(X.find_address([mk("<p>%s</p>" % text)]) is None, "address: not an address, %s" % what)

    # Opening hours beyond English. The last two must not match: a day name alone is not opening hours.
    for text, want, what in [("Monday to Friday, 9am - 5pm", True, "EN am/pm range"),
                             ("Mo-Fr 09:00-17:30", True, "DE compact day range"),
                             ("Montag bis Freitag von 9 bis 18 Uhr", True, "DE words"),
                             ("Öffnungszeiten unserer Filiale", True, "DE label"),
                             ("Lun-Ven 9h-18h", True, "FR compact"),
                             ("Ouvert du lundi au vendredi, 9h30 à 18h00", True, "FR h-minutes"),
                             ("Lunes a viernes de 9:00 a 14:00", True, "ES words"),
                             ("Maandag t/m vrijdag 08:30 - 17:00", True, "NL words"),
                             ("Black Friday sale, save 20 percent", False, "Black Friday is not opening hours"),
                             ("So we do 10-15 projects a year", False, "prose that looks like a range")]:
        res.check((X.find_hours([mk("<p>%s</p>" % text)]) is not None) == want, "hours: %s" % what)

    # Phone numbers in national groupings behind a cue in the site's language. The last four must not count:
    # a cue word alone, or digits with no cue, is not a stated phone number.
    for text, want, what in [("Telefon: 0211 - 63 55 33 55", True, "DE pairs with spaced dash"),
                             ("Tél. : 01 23 45 67 89", True, "FR pairs"),
                             ("Teléfono: 91 123 45 67", True, "ES groups"),
                             ("Tel 030/5557-0199", True, "DE slash"),
                             ("Phone: (617) 555-0123", True, "US, unchanged"),
                             ("Call us today for a demo", False, "cue with no number"),
                             ("Telefonische Beratung ab 2024", False, "cue-like word and a year"),
                             ("Tel: 12 34", False, "too few digits"),
                             ("Mobile app version 10.2.3 released 2026-05-14", False, "version and date")]:
        res.check((X.find_phone([mk("<p>%s</p>" % text)]) is not None) == want, "phone: %s" % what)

    # Included page fragments never stand in for a page role.
    from auditlib.sampler import is_page_part
    res.check(is_page_part("https://www.adobe.com/homepage/fragments/loggedout/redesign/default/news/news"),
              "sampler: a /fragments/ path is a page part, not a page")
    res.check(not is_page_part("https://x.example/blog/fragmented-teams") and not is_page_part("https://x.example/components/"),
              "sampler: a slug that merely contains 'fragment', and 'components', stay pages")

    from auditlib.fetch import Fetcher as _F
    _f = _F(site="https://x.example/")
    res.check(_f.host_allowed("de.wikipedia.org") and _f.host_allowed("zh-yue.wikipedia.org"),
              "fetch: every Wikipedia language edition is allowed")
    res.check(not _f.host_allowed("evil.wikipedia.org.attacker.example") and not _f.host_allowed("wikipedia.org.example"),
              "fetch: look-alike hosts are not")

    # A redirect to a language edition is named in limitations; a seed that already named the edition is not.
    _C = _load_compose()
    res.check(_C.language_edition({"url": "https://www.lemonde.fr/", "final_url": "https://www.lemonde.fr/en/"}) == "en",
              "compose: a redirect to /en/ is a language edition")
    res.check(_C.language_edition({"url": "https://x.example/en/", "final_url": "https://x.example/en/"}) is None
              and _C.language_edition({"url": "https://x.example/", "final_url": "https://x.example/blog/"}) is None,
              "compose: no edition when the seed named it, or the path is not a language")

    # Sitemaps: site-wide before specialised, whatever order robots.txt lists them in.
    from auditlib.sampler import _sitemap_rank
    listed = ["https://a.example/cc-product.index.xml", "https://a.example/creativecloud/sitemap-index.xml",
              "https://a.example/home-sitemap.xml", "https://a.example/plans-catalog-sitemap.xml"]
    res.check(sorted(listed, key=_sitemap_rank)[0].endswith("/home-sitemap.xml"),
              "sampler: a root home sitemap is tried before a product index listed first")
    res.check(sorted(["https://b.example/sitemap_news.xml", "https://b.example/sitemap_index.xml"], key=_sitemap_rank)[0]
              .endswith("/sitemap_index.xml"), "sampler: the site index is tried before the news sitemap")

    # Mission stated as "The mission of X is to", and near misses that are not a mission statement.
    res.check(bool(X.MISSION_RE.search("The mission of the Python Software Foundation is to promote, protect, and advance Python.")),
              "mission: 'The mission of X is to' is a mission statement")

    # An organisation the CMS hangs off a link key is still the site owner (elpais.com: copyrightHolder only).
    nested = mk('<script type="application/ld+json">{"@context":"https://schema.org","@type":"WebSite","name":"P",'
                '"copyrightHolder":{"@type":["NewsMediaOrganization","Organization"],"name":"El Diario"}}</script>')
    res.check(X.find_org_node(nested.doc) is not None, "jsonld: an Organization under copyrightHolder is the site owner")
    deep = mk('<script type="application/ld+json">{"@context":"https://schema.org","@type":"Article","headline":"h",'
              '"publisher":{"@type":"Organization","name":"Acme"}}</script>')
    res.check(X.find_org_node(deep.doc) is not None, "jsonld: an Organization under publisher counts")
    none_there = mk('<script type="application/ld+json">{"@context":"https://schema.org","@type":"WebPage","name":"x",'
                    '"about":{"@type":"Organization","name":"Someone Else Ltd"}}</script>')
    res.check(X.find_org_node(none_there.doc) is None,
              "jsonld: an organisation the page merely writes about is not the site owner")
    person = mk('<script type="application/ld+json">{"@context":"https://schema.org","@type":"Article",'
                '"author":{"@type":"Person","name":"Ada Byron"}}</script>')
    res.check(X.find_org_node(person.doc) is None and X.find_org_node(person.doc, allow_person=True) is not None,
              "jsonld: a Person author counts only where a person can be the brand")

    # A screen-reader-only heading is markup, not what a visitor reads.
    hidden = mk('<body><div class="visually-hidden"><h1>Adobe homepage</h1></div><h2>Create at the highest level.</h2></body>')
    res.check(hidden.doc.h1s == ["Adobe homepage"] and hidden.doc.visible_h1s == [],
              "htmldoc: a visually-hidden h1 stays in h1s but not in visible_h1s")
    plain_h1 = mk('<body><h1>Invoicing for freelance designers</h1></body>')
    res.check(plain_h1.doc.visible_h1s == ["Invoicing for freelance designers"],
              "htmldoc: an ordinary h1 is visible")
    sronly = mk('<body><h1 class="sr-only">Site name</h1><h2>Bookkeeping that files itself</h2></body>')
    res.check(sronly.doc.visible_h1s == [] and [h["text"] for h in sronly.doc.visible_headings(("h2",))] == ["Bookkeeping that files itself"],
              "htmldoc: sr-only h1 hidden, the visible h2 is offered instead")
    res.check(not X.MISSION_RE.search("Mission of Burma tour dates announced for the autumn."),
              "mission: a band name is not a mission statement")

    # Menu chrome must not be quoted as an answer, but guillemets are quotation marks in French,
    # Spanish and Italian -- treating them as separators threw away genuine prose and called the fact absent.
    _C2 = _load_compose()
    res.check(not _C2._sentence_shaped("Home | About | Contact | Shop"),
              "simulation: a pipe-separated menu is not sentence-shaped")
    res.check(not _C2._sentence_shaped("Inicio · Blog · Tienda · Contacto"),
              "simulation: a middot-separated menu is not sentence-shaped")
    res.check(_C2._sentence_shaped("Nous publions « des analyses approfondies » chaque jour pour nos abonnés"),
              "simulation: French prose in guillemets is sentence-shaped")

    # Engagement: search boxes by markup, calls to action beyond the category list, contact methods.
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("_ep_t", os.path.join(ROOT, "skills", "engagement-audit", "scripts", "engagement_probe.py"))
    _EP = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_EP)
    _u = "https://x.example/"
    res.check(bool(_EP.has_site_search(Document('<form id="search-block-form" action="/"><input type="text" name="search_block_form">'
                                                '<input type="submit" value="Search"></form>', base_url=_u))),
              "engagement: Drupal's search-block-form is a site search")
    res.check(not _EP.has_site_search(Document('<form id="newsletter" action="/subscribe"><input type="email" name="email"></form>', base_url=_u)),
              "engagement: a newsletter form is not a site search")
    _rx, _vocab = _EP._cta_re("corporate_enterprise")
    res.check(bool(_EP.cta_hits(Document('<body><header><a href="/trial">Free trial</a></header>' + "<p>text</p>" * 40 + "</body>", base_url=_u), _rx, _vocab)),
              "engagement: 'Free trial' is a call to action whatever the category")
    _rx2, _vocab2 = _EP._cta_re("saas_software")
    res.check(bool(_EP.cta_hits(Document("<body>" + "<p>text</p>" * 40 + '<a href="tel:+4921163553355">0211 - 63 55 33 55</a></body>', base_url=_u),
                                _rx2, _vocab2, role="contact")),
              "engagement: a contact page's tel: link is its call to action")

    # A header/nav link is first-viewport whatever its markup position (4.3): iiitd.ac.in's
    # <a>Admission</a> sits at 17.9-42.8% of the markup behind a long utility bar, past the 40% proxy,
    # though it is the first thing a visitor sees in the page's own header.
    _rx3, _vocab3 = _EP._cta_re("nonprofit_institution")
    late_header = Document("<body>" + "<p>filler text here to pad the markup well past the viewport proxy</p>" * 60
                           + '<header><a href="/admission">Admission</a></header>'
                           + "<p>more content after the header</p>" * 5 + "</body>", base_url=_u)
    res.check(bool(_EP.cta_hits(late_header, _rx3, _vocab3)),
              "engagement: a header link counts as first-viewport whatever its markup position")
    # The position proxy still governs an ordinary body link: one buried at the same depth, outside
    # header/nav, must not count -- this is the control that proves the fix did not just stop measuring.
    late_body = Document("<body>" + "<p>filler text here to pad the markup well past the viewport proxy</p>" * 60
                         + '<div><a href="/admission">Admission</a></div>'
                         + "<p>more content after the link</p>" * 5 + "</body>", base_url=_u)
    res.check(not _EP.cta_hits(late_body, _rx3, _vocab3),
              "engagement: an ordinary body link past 40% still does not count")

    # A transport error (DNS/TLS/timeout/refused) is not a broken link (4.2): the audit's own connection
    # failing is not evidence the site is broken, and python.org's /downloads/ios/ (a real 200) was once
    # reported as the site's own broken link because this audit's first attempt saw a tls_error.
    res.check(_EP.classify_fetch({"error": "tls_error"}) == "transport_error", "classify_fetch: tls_error is a transport error, not broken")
    res.check(_EP.classify_fetch({"error": "dns_failure"}) == "transport_error", "classify_fetch: dns_failure is a transport error, not broken")
    res.check(_EP.classify_fetch({"status": 404}) == "broken", "classify_fetch: a real 404 is still broken")
    res.check(_EP.classify_fetch({"status": 500}) == "broken", "classify_fetch: a 5xx is still broken")
    res.check(_EP.classify_fetch({"status": 403}) == "blocked", "classify_fetch: 403 is blocked, not broken")

    import types as _types
    import time as _time2
    from auditlib.findings import ProbeOutput as _PO

    class _FlakyFetcher:
        """Fails with a transport error on the first request to each URL, then serves 200: the retry case."""
        def __init__(self):
            self.seen = set()

        def get(self, url, purpose=None, timeout=None):
            if url not in self.seen:
                self.seen.add(url)
                return {"status": None, "error": "tls_error"}
            return {"status": 200, "error": None}

    class _DeadFetcher:
        """Fails with a transport error on every request: the persists-after-retry case."""
        def get(self, url, purpose=None, timeout=None):
            return {"status": None, "error": "read_timeout"}

    link_home = mk('<body><a href="https://x.example/retry-ok">Retry link</a></body>')
    ctx_stub = _types.SimpleNamespace(pages=[], home=None)
    out1 = _PO("engagement-audit", "https://x.example/", "saas_software", [])
    work1 = {}
    _EP.check_links(ctx_stub, out1, _FlakyFetcher(), [link_home], [], work1, _time2.monotonic() + 30)
    res.check(work1["link_sample"][0]["verdict"] == "ok" and work1["link_summary"]["requested"] == 2,
              "check_links: a transport error clears on one retry and is never reported as broken",
              str(work1["link_summary"]))
    res.check(out1.status_of("en.links.broken_sampled") == "pass", "check_links: the check passes once the retry succeeds")

    out2 = _PO("engagement-audit", "https://x.example/", "saas_software", [])
    work2 = {}
    _EP.check_links(ctx_stub, out2, _DeadFetcher(), [link_home], [], work2, _time2.monotonic() + 30)
    res.check(work2["link_sample"][0]["verdict"] == "transport_error", "check_links: a transport error that persists is never reclassified as broken")
    res.check(out2.status_of("en.links.broken_sampled") == "inconclusive", "check_links: a persisting transport error is inconclusive, not a fail",
              str([f for f in out2.findings if f["check_id"] == "en.links.broken_sampled"]))
    reason2 = next(c.get("reason") for c in out2.checks if c["check_id"] == "en.links.broken_sampled")
    res.check(reason2 == "fetcher_error", "check_links: the inconclusive reason is fetcher_error", reason2)
    res.check(all(f["severity"] == "info" for f in out2.findings if f["check_id"] == "en.links.broken_sampled"),
              "check_links: an inconclusive verdict is always info severity")

    # Header and footer served empty, and the gate that follows from it.
    res.check(Document("<body><header></header><main><p>Hello there, world.</p></main><footer></footer></body>", base_url=_u).empty_chrome
              == ["header", "footer"], "htmldoc: a header and footer served empty are recorded")
    res.check(Document('<body><header><a href="/a">About</a></header><footer>Example Ltd, 1 Road, Town, 2026, all rights reserved</footer></body>',
                       base_url=_u).empty_chrome == [], "htmldoc: a header with links and a footer with text are not empty")
    _fs = [{"check_id": "en.nav.landmark_missing", "status": "fail"}, {"check_id": "cr.robots.index_bot_blocked", "status": "fail"}]
    _cs = {"en.nav.landmark_missing": {"status": "fail"}, "cr.robots.index_bot_blocked": {"status": "fail"}}
    _sm = {"pages": [{"role": "home", "summary": {"empty_chrome": ["header", "footer"], "nav_count": 0, "external_scripts": 2}}]}
    res.check(_C.apply_render_gate(_fs, _cs, _sm) == ["en.nav.landmark_missing"] and [f["check_id"] for f in _fs] == ["cr.robots.index_bot_blocked"]
              and _cs["en.nav.landmark_missing"]["status"] == "not_evaluated",
              "compose: a script-built header withdraws the navigation finding and leaves robots findings alone")
    _sm2 = {"pages": [{"role": "home", "summary": {"empty_chrome": ["header"], "nav_count": 2, "external_scripts": 2}}]}
    res.check(_C.apply_render_gate([{"check_id": "en.nav.landmark_missing", "status": "fail"}], {}, _sm2) == [],
              "compose: an empty header on a page with a real <nav> is not a script-built page")

    # Country domains and private addresses.
    from auditlib.fetch import cctld_language
    res.check(cctld_language("https://www.lemonde.fr/") == "fr" and cctld_language("https://www.sipgate.de/") == "de"
              and cctld_language("https://www.adobe.com/") is None and cctld_language("https://x.ch/") is None,
              "fetch: a country domain names its language only where that is unambiguous")
    _prev = os.environ.pop("BRAND_AUDIT_ALLOW_PRIVATE", None)
    try:
        _g = _F(site="http://127.0.0.1:9/")
        res.check(_g.is_private_host("127.0.0.1") and _g.is_private_host("169.254.169.254") and _g.is_private_host("localhost"),
                  "fetch: loopback, link-local and localhost count as private")
        res.check(not _g.is_private_host("93.184.216.34"), "fetch: a public address is not private")
        res.check(_g.get("http://127.0.0.1:9/").get("error") == "host_not_allowed", "fetch: a private URL is refused before connecting")
    finally:
        if _prev is not None:
            os.environ["BRAND_AUDIT_ALLOW_PRIVATE"] = _prev
    # Phone layouts beyond the Anglo one, and the cue words that make a domestic number count. The pair-grouped
    # French form and the single-digit area codes of Australia and India were invisible to the first grammar.
    for text, what in [("Tél. : +33 1 42 72 00 00 (du mardi au samedi)", "FR international, pairs"),
                       ("Téléphone : 01 42 72 00 00", "FR domestic pairs with Téléphone cue"),
                       ("Tél. : 01 42 72 00 00", "FR domestic pairs with Tél. cue"),
                       ("Telefon: 030 5557 0199", "DE domestic with Telefon cue"),
                       ("Teléfono: +34 91 123 45 67", "ES international"),
                       ("Call us on +61 2 9000 0000, Monday to Friday", "AU single-digit area code"),
                       ("+91 11 2690 7400 (Monday to Saturday)", "IN two-digit area code"),
                       ("Phone: +44 117 496 0123.", "UK international"),
                       ("Call +1 (212) 555-0142 today", "US with parentheses")]:
        res.check(X.find_phone([mk("<p>%s</p>" % text)]) is not None, "phone: %s" % what)
    for text, what in [("Updated 2026-09-12 at 12:00:00", "ISO timestamp"),
                       ("ISBN 978 3 16 148410 0", "ISBN groups"),
                       ("Founded in 1962, listed 1987, revenue 3.1 billion", "years and figures"),
                       ("Order 12 34 56 shipped", "short digit pairs without a cue")]:
        res.check(X.find_phone([mk("<p>%s</p>" % text)]) is None, "phone: not a phone, %s" % what)
    # French street lines put the street word in lower case after the number
    for text, want, what in [("12 rue des Archives, Paris", True, "FR lowercase rue"),
                             ("3 boulevard Saint-Germain", True, "FR boulevard"),
                             ("1 place de la Bourse", True, "FR place with article"),
                             ("finished in 12 place mats", False, "place is not a street here"),
                             ("12 square Feet of space", False, "square feet is not a street")]:
        res.check((X.address_match(text) is not None) == want, "address: %s" % what)
    # a numberOfEmployees written as a QuantitativeValue is a count, not an empty name
    emp = mk('<script type="application/ld+json">{"@context":"https://schema.org","@type":"Corporation","name":"M","url":"https://x.example/","numberOfEmployees":{"@type":"QuantitativeValue","value":12400}}</script>', role="about")
    f = X.find_leadership_or_size([emp])
    res.check(f is not None and f["value"] == "12400 employees" and f["source"] == "jsonld:numberOfEmployees", "leadership_or_size: QuantitativeValue headcount is quotable", str(f))
    fnd = mk('<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"M","url":"https://x.example/","founder":{"@type":"Person","name":"Ada Byron"}}</script>', role="about")
    res.check((X.find_leadership_or_size([fnd]) or {}).get("value") == "Ada Byron", "leadership_or_size: founder Person name is quoted")
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
    # image_only reads labels, never captions or sentences (Step 19 live pass)
    sig = fp.image_fact_signals
    res.check(sig("Google map of Clearleft office location", "Screenshot-2022.webp", "Come over to our place", "address") == [],
              "fx: a seven-word caption is not an address label")
    res.check(sig("An animated image showing location pins dropping onto a street map", "locationdata_v2.gif", "Press Contacts", "address") == [],
              "fx: a caption mentioning location is not an address label")
    res.check(sig("VMware logo on smartphone", "photo.jpeg", "Broadcom plans new vSphere Standard", "pricing") == [],
              "fx: a five-word headline containing 'plans' is not a pricing heading")
    res.check(sig("Pricing", "pricing-table.png", "", "pricing") == ["alt", "filename"], "fx: a short alt and a filename token are labels")
    res.check(sig("", "photo.jpg", "Plans", "pricing") == ["heading"], "fx: a one-word heading 'Plans' is a pricing label")
    res.check(sig("Opening hours", "img_2231.jpg", "", "hours") == ["alt"], "fx: 'Opening hours' alt is a label")
    res.check(fp.IMAGE_FACT_PAGES["address"] == ("contact", "about", "home") and "blog" not in sum(fp.IMAGE_FACT_PAGES.values(), ()),
              "fx: image_only never grades a blog page")
    R = run_probe_on_fixtures(res, farm, "fx.", fp, "fx")
    from auditlib.context import AuditContext
    import tempfile

    def run_with_facts(name):
        with tempfile.TemporaryDirectory() as td:
            ctx = AuditContext.from_url(farm.urls[name], td)
            out = fp.run(ctx).to_dict()
            fpath = os.path.join(td, "work", "extracted_facts.json")
            facts = _read_json(fpath) if os.path.exists(fpath) else None
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
    # Step 19 live pass: open copyright ranges, NAP for unknown, the lookup's second title
    import types as _types
    fake = lambda text: _types.SimpleNamespace(doc=_types.SimpleNamespace(body_text=text))  # noqa: E731
    this_year = ep._today().year
    res.check([y for y, _ in ep.copyright_years(fake("Copyright © 2005-now Clearleft Ltd. All rights reserved."))] == [this_year],
              "ef: '© 2005-now' is the current year, not 2005")
    res.check([y for y, _ in ep.copyright_years(fake("© 2005–present Example"))] == [this_year], "ef: '© 2005–present' is current")
    res.check([y for y, _ in ep.copyright_years(fake("© 2019-2024 Example"))] == [2024], "ef: a closed range counts its later year")
    # identity anchors are not only Anglo registers: a national register mirror or a place listing counts
    auth = ep.authority_hosts("local_business")
    res.check(any(a in "www.tripadvisor.fr" for a in auth) and any(a in "www.societe.com" for a in auth) and any(a in "www.northdata.de" for a in auth),
              "ef: TripAdvisor, societe.com and North Data count as identity anchors")
    res.check(not any(a in "www.instagram.com" for a in auth) and not any(a in "blog.pagerduty.com" for a in auth),
              "ef: a social profile or an unrelated host is not an identity anchor")
    res.check([y for y, _ in ep.copyright_years(fake("© 2019 Example"))] == [2019], "ef: a single year is itself")
    res.check(list(ep.nap_requirement("unknown")) == ["name", "contact (address, phone or email)"], "ef: an unclassified site needs name plus any contact")
    res.check(list(ep.nap_requirement("local_business")) == ["name", "postal address", "phone number"], "ef: a local business still needs address and phone")
    res.check(ep.lookup_alternates("Dishoom Indian Restaurants", [("Dishoom Indian Restaurants", "meta:og:site_name", None), ("Dishoom", "title:common_segment", None)]) == ["Dishoom"],
              "ef: the shorter self-name is the lookup's second title")
    res.check(ep.lookup_alternates("Dishoom", [("Dishoom", "meta", None), ("Dishoom Indian Restaurants", "jsonld", None)]) == [],
              "ef: a longer name is never a second title")
    res.check(ep.lookup_alternates("Acme Ltd", [("Acme Ltd", "meta", None), ("acme ltd", "title:common_segment", None)]) == [],
              "ef: the same name differently cased is not an alternate")
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
        _write_json(os.path.join(td, "work", "offsite_mentions.json"),
                    {"tool": "web_search", "queries": ['"Ledgerly"', '"Ledgerly" Bristol'], "mentions": [{"url": "https://directory.example/ledgerly", "kind": "directory", "agrees_with": ["address"]}, {"url": "https://news.example/a", "kind": "news"}]})
        out = ep.run(ctx).to_dict()
        f = next((x for x in out["findings"] if x["check_id"] == "ef.corroboration.offsite_spotcheck"), None)
        res.check(f is not None and f["status"] == "inconclusive" and f["severity"] == "info" and "2 mentions across 2 queries" in f["title"] and "directory=1" in f["evidence"] and "news=1" in f["evidence"],
                  "ef: offsite file yields an inconclusive info note with counts by kind", f["title"] if f else None)
        res.check(not validate_probe_output(out), "ef: offsite note validates against the schema")


# ---------------------------------------------------------------- stage: probe_en (engagement probe on fixtures)
def stage_probe_en(res, farm):
    print("\n== stage: engagement probe on every fixture")
    ep = _load_probe("engagement-audit", "engagement_probe.py")
    # the per-language call-to-action vocabulary covers the local-business and services verbs, not only sign-up
    rx_fr, _ = ep._cta_re("local_business", lang="fr")
    res.check(rx_fr.search("Réserver une table") and rx_fr.search("Réservez") and rx_fr.search("Appelez-nous") and not rx_fr.search("Nos horaires"),
              "cta vocabulary: French local-business verbs are calls to action, a heading is not")
    rx_de, _ = ep._cta_re("local_business", lang="de")
    res.check(rx_de.search("Tisch reservieren") and rx_de.search("Anfahrt"), "cta vocabulary: German reservieren/Anfahrt")
    rx_en, _ = ep._cta_re("local_business", lang=None)
    res.check(not rx_en.search("Réserver une table"), "cta vocabulary: no French words are searched on an English page")
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
    # Four key pages, not five: the contact page's mailto: link is its call to action, so it passes. The rest
    # of the site offers nothing to act on, and a search box is never a call to action.
    res.check(f is not None and f["severity"] == "medium" and len(f["affected_pages"]) == 4
              and not any("/contact" in u for u in f["affected_pages"])
              and "search" not in json.dumps(f["evidence_items"]).lower().split("matched=0")[0][-40:],
              "en/weak-engagement: cta_missing on the four key pages with nothing to act on", str(f and f["affected_pages"]))
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
    # --offline must hold in workdir mode, where this probe builds its own fetcher: replaying a saved
    # workdir with the network off once counted every unreachable link as a broken one
    with tempfile.TemporaryDirectory() as td:
        AuditContext.from_url(farm.urls["clean-site"], td)
        out = ep.run(AuditContext.from_workdir(td), types.SimpleNamespace(offline=True, no_network=False)).to_dict()
        net = {c["check_id"]: c.get("reason") for c in out["checks"] if c["check_id"].startswith(("en.links", "en.errors"))}
        res.check(all(r == "network_disabled" for r in net.values()) and len(net) == 4,
                  "en: --offline is honoured in workdir mode, not just from the context", str(net))
        res.check(not [f for f in out["findings"] if f["severity"] != "info"],
                  "en: an offline replay reports no defect it could not have observed")
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
        work = _read_json(os.path.join(td, "work", "engagement.json"))
        res.check(work["network"] is False and work["requests_made"] == 0, "en: engagement.json records network=false, zero requests")
    # engagement.json from a normal run has the link sample and the 404 probe
    with tempfile.TemporaryDirectory() as td:
        ep.run(AuditContext.from_url(farm.urls["clean-site"], td))
        work = _read_json(os.path.join(td, "work", "engagement.json"))
        res.check(work["link_summary"]["sampled"] >= 6 and work["link_summary"]["broken"] == 0 and work["probe_404"]["verdict"] == "real_404" and work["probe_404"]["home_link"] is True,
                  "en/clean-site: engagement.json has the link sample and a helpful real 404", str(work.get("link_summary")))
        res.check(work["link_summary"]["requested"] <= 15 and work["requests_made"] <= 16, "en/clean-site: at most 15 link requests plus the 404 probe (%s)" % work["requests_made"])


STAGES = {"manifest": None, "serve": None, "variants": None, "robots": None, "htmldoc": None, "extract": None, "fetch": None, "sample": None, "probe_cr": None, "probe_fx": None, "probe_ef": None, "probe_en": None, "compose": None, "validate": None, "run_audit": None, "scripts": None, "live": None}


def _remove_new_run_dirs(before):
    """CLI cases that exercise the default workdir create audit-<host>/ in the package root; remove this run's."""
    import glob as _glob
    import shutil
    for d in set(_glob.glob(os.path.join(ROOT, "audit-*"))) - before:
        shutil.rmtree(d, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="brand-ai-readiness-audit test runner")
    ap.add_argument("--stage", choices=sorted(STAGES), action="append", help="run only these stages")
    ap.add_argument("--base-port", type=int, default=8100)
    ap.add_argument("--keep", action="store_true", help="leave fixture servers running after tests")
    ap.add_argument("--live", nargs="*", metavar="URL", help="also run the live stage against these sites")
    args = ap.parse_args(argv)
    os.environ["BRAND_AUDIT_EXTERNAL"] = "0"  # the suite never contacts Wikipedia/Wikidata; the entity lookup is unit-tested on canned responses
    os.environ["BRAND_AUDIT_ALLOW_PRIVATE"] = "1"  # fixtures are served on 127.0.0.1; the guard itself is unit-tested with this unset
    import atexit
    import glob as _glob
    atexit.register(_remove_new_run_dirs, set(_glob.glob(os.path.join(ROOT, "audit-*"))))
    stages = args.stage or ["manifest", "serve", "variants", "robots", "htmldoc", "extract", "fetch", "sample", "probe_cr", "probe_fx", "probe_ef", "probe_en", "compose", "validate", "run_audit", "scripts"]
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
        if any(st in stages for st in ("serve", "variants", "fetch", "sample", "probe_cr", "probe_fx", "probe_ef", "probe_en", "compose", "validate", "run_audit", "scripts")):
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
            if "run_audit" in stages:
                stage_run_audit(res, farm)
            if "scripts" in stages:
                stage_scripts(res, farm)
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
