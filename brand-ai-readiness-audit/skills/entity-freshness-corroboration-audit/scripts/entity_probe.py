#!/usr/bin/env python3
"""entity-freshness-corroboration-audit probe: can an assistant tell this brand apart, and trust that its facts are current?

Runs the 12 `ef.*` checks of the shared registry over the sampled pages:
  entity        sameAs anchors, one robots-allowed Wikipedia/Wikidata lookup, plain-text NAP, name consistency
  freshness     visible dates, copyright year, JSON-LD dateModified versus the visible date
  corroboration press/newsroom surface, and the bounded off-site spot-check (an agent step; this script reports it)

Usage:
  entity_probe.py --url https://example.com [--workdir DIR] [--out FILE] [--no-external]
  entity_probe.py --workdir DIR [--out FILE]

External requests: at most one Wikipedia article (or one Wikidata EntityData document) per audit, fetched under the
shared policy with the audit's own user agent and that host's robots.txt obeyed. Wikidata's search API is disallowed
for generic agents by its robots.txt and is never called. `--no-external` or BRAND_AUDIT_EXTERNAL=0 disables the lookup.
Writes `work/entity.json` (what was resolved) and `work/entity_lookup.json` (the lookup result, reused in workdir mode).
Reads `work/offsite_mentions.json` when the agent step has written it.
Standard library only. Never raises; internal errors are reported in the `error` field.
"""
import datetime as _dt
import json
import os
import re
import sys
from urllib.parse import quote, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "audit-orchestrator", "scripts")))

from auditlib import extract as X  # noqa: E402
from auditlib.categories import SEVERITY_OVERRIDES  # noqa: E402
from auditlib.cli import probe_main  # noqa: E402
from auditlib.fetch import Fetcher, WIKIDATA_HOST, WIKIPEDIA_HOST, registrable_domain  # noqa: E402
from auditlib.findings import ProbeOutput, evidence_item  # noqa: E402
from auditlib.render import render_state  # noqa: E402

PROBE = "entity-freshness-corroboration-audit"
ENTITY_REL = "work/entity.json"
LOOKUP_REL = "work/entity_lookup.json"
OFFSITE_REL = "work/offsite_mentions.json"
EXTERNAL_ENV = "BRAND_AUDIT_EXTERNAL"
LOOKUP_TIMEOUT = 8.0
STALE_YEARS = 2
MISMATCH_DAYS = 30

LEGAL_SUFFIX_RE = re.compile(r"\b(ltd|limited|inc|incorporated|llc|llp|plc|gmbh|ag|sa|s\.a\.|bv|b\.v\.|pty|oy|ab|srl|s\.r\.l\.|spa|s\.p\.a\.|corp|corporation|co|company|group|holdings)\b\.?", re.I)
COPYRIGHT_YEAR_RE = re.compile(r"(?:©|\(c\)|copyright)[^\d\n]{0,40}?((?:19|20)\d{2})(?:\s*[-–—]\s*((?:19|20)\d{2}))?", re.I)
PRESS_LINK_RE = re.compile(r"\b(press|newsroom|news\s*room|news|media|blog|announcements|updates|in\s+the\s+(press|news)|stories|insights|journal)\b", re.I)
PRESS_PATH_SEGMENTS = {"press", "news", "newsroom", "media", "blog", "updates", "announcements", "stories", "insights", "journal", "press-releases", "pressroom"}
MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
QID_RE = re.compile(r"/(Q\d+)(?:[/#?.]|$)")
WIKI_TITLE_RE = re.compile(r"<title>(.*?)\s+-\s+Wikipedia</title>", re.S | re.I)
WIKI_QID_RE = re.compile(r'"wgWikibaseItemId"\s*:\s*"(Q\d+)"')
REFS = {
    "sameas": "https://schema.org/sameAs",
    "org": "https://developers.google.com/search/docs/appearance/structured-data/organization",
    "wikidata": "https://www.wikidata.org/wiki/Wikidata:Introduction",
    "dates": "https://developers.google.com/search/docs/appearance/structured-data/article#date-best-practices",
}


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today():
    return _dt.datetime.now(_dt.timezone.utc).date()


def _host(url):
    return (urlsplit(url or "").hostname or "").lower()


def _norm_name(s):
    s = LEGAL_SUFFIX_RE.sub(" ", (s or "").lower())
    return re.sub(r"[^a-z0-9]+", "", s)


def _external_enabled(args):
    if args is not None and getattr(args, "no_external", False):
        return False
    return os.environ.get(EXTERNAL_ENV, "1").strip().lower() not in ("0", "false", "no", "off")


# ---------------------------------------------------------------- dates
def parse_date(s):
    """A date from an ISO string ('2026-09-07', '2026-09-07T14:02:12Z') or a written date ('7 September 2026'). None if not a date."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    m = re.match(r"^((?:19|20)\d{2})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"^(?:(\d{1,2})(?:st|nd|rd|th)?\s+)?([A-Za-z]{3,9})\.?\s+(?:(\d{1,2})(?:st|nd|rd|th)?,?\s+)?((?:19|20)\d{2})$", s)
    if m:
        mon = MONTHS.get(m.group(2)[:3].lower())
        day = int(m.group(1) or m.group(3) or 1)
        if mon:
            try:
                return _dt.date(int(m.group(4)), mon, day)
            except ValueError:
                return None
    return None


def visible_dates(page):
    """[(date, raw, kind)] for a page: <time datetime> values, ISO dates and written dates in the body text."""
    out = []
    for t in page.doc.times:
        d = parse_date(t)
        if d:
            out.append((d, t, "time"))
    text = page.doc.body_text or ""
    for m in X.ISO_DATE_RE.finditer(text):
        d = parse_date(m.group(0))
        if d:
            out.append((d, m.group(0), "text"))
    for m in X.TEXT_DATE_RE.finditer(text):
        d = parse_date(m.group(0))
        if d:
            out.append((d, m.group(0), "text"))
    return out


def copyright_years(page):
    """[(year, excerpt)] from copyright lines in the body text; the later year of a range counts."""
    out = []
    text = page.doc.body_text or ""
    for m in COPYRIGHT_YEAR_RE.finditer(text):
        y = int(m.group(2) or m.group(1))
        out.append((y, text[max(0, m.start() - 10):m.end() + 30].strip()))
    return out


def jsonld_dates(page):
    """[(date, raw, property, type)] from top-level JSON-LD nodes: dateModified, else datePublished."""
    out = []
    for n, _ in X.doc_top_nodes(page.doc):
        for prop in ("dateModified", "datePublished"):
            v = n.get(prop)
            if isinstance(v, str) and parse_date(v):
                out.append((parse_date(v), v, prop, (X.node_types(n) or ["?"])[0]))
                break
    return out


# ---------------------------------------------------------------- entity resolution
def org_nodes(pages, category):
    allow_person = category == "portfolio_personal"
    nodes = []
    for p in X._ordered(pages, ("home", "about")):
        for n, i in X.doc_top_nodes(p.doc):
            if X.is_org_node(n, allow_person=allow_person):
                nodes.append((p, n, i))
    return nodes


def sameas_urls(nodes):
    seen, out = set(), []
    for _, n, _ in nodes:
        for u in X._walk_key(n, "sameAs"):
            if isinstance(u, str) and u.startswith("http") and u not in seen:
                seen.add(u)
                out.append(u)
    return out


def authority_hosts(category):
    hosts = list(X.AUTHORITY_HOSTS)
    if category == "portfolio_personal":
        hosts += list(X.PROFILE_HOSTS)
    return hosts


def wikipedia_title_for(brand):
    t = re.sub(r"\s+", " ", (brand or "").strip())
    if not t:
        return None
    t = t[0].upper() + t[1:]
    return quote(t.replace(" ", "_"), safe="_()-.,'&")


def classify_wikipedia(html, domain):
    """Read a fetched Wikipedia page. Returns dict(title, qid, disambiguation, entries, mentions_domain, no_article)."""
    h = html or ""
    m = WIKI_TITLE_RE.search(h)
    title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else None
    q = WIKI_QID_RE.search(h)
    disamb = ("dmbox-disambig" in h) or ("Category:Disambiguation_pages" in h) or ('"All disambiguation pages"' in h)
    entries = 0
    if disamb:
        i = h.find("mw-parser-output")
        j = h.find('id="catlinks"', i if i >= 0 else 0)
        body = h[i:j] if i >= 0 else h
        entries = len(re.findall(r"<li\b", body))
    return {"title": title, "qid": q.group(1) if q else None, "disambiguation": disamb, "entries": entries,
            "mentions_domain": bool(domain) and (domain.lower() in h.lower()), "no_article": "noarticletext" in h}


def classify_entitydata(data, qid, brand, domain):
    """Read a Wikidata EntityData document. Returns dict(label, aliases, website, label_match, website_match)."""
    ents = (data or {}).get("entities") or {}
    ent = ents.get(qid) or (next(iter(ents.values())) if ents else {})
    label = ((ent.get("labels") or {}).get("en") or {}).get("value")
    aliases = [a.get("value") for a in ((ent.get("aliases") or {}).get("en") or []) if isinstance(a, dict)]
    website = None
    for claim in ((ent.get("claims") or {}).get("P856") or []):
        v = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(v, str):
            website = v
            break
    nb = _norm_name(brand)
    label_match = bool(nb) and any(_norm_name(x) == nb for x in [label] + aliases if x)
    website_match = bool(domain) and bool(website) and registrable_domain(_host(website)) == domain
    return {"label": label, "aliases": aliases[:5], "website": website, "label_match": label_match, "website_match": website_match}


def entity_lookup(ctx, brand, sameas, external, domain):
    """One robots-allowed request that either verifies the site's own sameAs anchor or looks the brand name up on Wikipedia.

    outcome: verified | ambiguous | collision | mismatch | not_found | unavailable | skipped
    """
    res = {"mode": None, "target": None, "outcome": None, "reason": None, "status": None, "title": None, "qid": None,
           "entries": 0, "mentions_domain": None, "label": None, "website": None, "requests_made": 0, "checked_at": _now()}
    saved = os.path.join(ctx.workdir, LOOKUP_REL) if ctx.workdir else None
    if saved and os.path.exists(saved):
        try:
            with open(saved, encoding="utf-8") as f:
                prev = json.load(f)
            if prev.get("outcome") not in (None, "unavailable"):
                prev["reused"] = True
                return prev
        except Exception:  # noqa: BLE001
            pass
    if not external:
        res["outcome"], res["reason"] = "unavailable", "network_disabled"
        return _save_lookup(ctx, res)
    wiki = [u for u in sameas if "wikipedia.org" in _host(u)]
    wd = [u for u in sameas if "wikidata.org" in _host(u) and QID_RE.search(urlsplit(u).path + "/")]
    if wiki:
        res["mode"], res["target"] = "verify_wikipedia", wiki[0]
    elif wd:
        qid = QID_RE.search(urlsplit(wd[0]).path + "/").group(1)
        res["mode"], res["target"], res["qid"] = "verify_wikidata", "https://%s/wiki/Special:EntityData/%s.json" % (WIKIDATA_HOST, qid), qid
    else:
        title = wikipedia_title_for(brand)
        if not title or not re.search(r"[A-Za-z]{2}", brand or ""):
            res["outcome"], res["reason"] = "skipped", "no_brand_name"
            return _save_lookup(ctx, res)
        res["mode"], res["target"] = "discover", "https://%s/wiki/%s" % (WIKIPEDIA_HOST, title)
    fetcher = ctx.fetcher or Fetcher(workdir=ctx.workdir, site=ctx.site)
    before = fetcher.requests_made
    r = fetcher.get(res["target"], purpose="entity_lookup", timeout=LOOKUP_TIMEOUT)
    res["requests_made"] = fetcher.requests_made - before
    res["status"] = r.get("status")
    if r.get("skipped"):
        res["outcome"], res["reason"] = "unavailable", "robots_disallow"
        return _save_lookup(ctx, res)
    if r.get("error"):
        res["outcome"] = "unavailable"
        res["reason"] = "lookup_timeout" if "timeout" in r["error"] else ("network_disabled" if r["error"] == "network_disabled" else "lookup_failed")
        res["error"] = r.get("error_detail") or r["error"]
        return _save_lookup(ctx, res)
    if r.get("status") == 404:
        res["outcome"] = "not_found"
        return _save_lookup(ctx, res)
    if r.get("status") != 200:
        res["outcome"], res["reason"], res["error"] = "unavailable", "lookup_failed", "http %s" % r.get("status")
        return _save_lookup(ctx, res)
    if res["mode"] == "verify_wikidata":
        try:
            info = classify_entitydata(json.loads(r.text or "{}"), res["qid"], brand, domain)
        except Exception as e:  # noqa: BLE001
            res["outcome"], res["reason"], res["error"] = "unavailable", "lookup_failed", "bad json: %s" % e
            return _save_lookup(ctx, res)
        res.update({"label": info["label"], "website": info["website"], "title": info["label"]})
        res["outcome"] = "verified" if (info["label_match"] or info["website_match"]) else "mismatch"
        return _save_lookup(ctx, res)
    info = classify_wikipedia(r.text or "", domain)
    res.update({"title": info["title"], "qid": info["qid"] or res["qid"], "entries": info["entries"], "mentions_domain": info["mentions_domain"]})
    if info["no_article"]:
        res["outcome"] = "not_found"
    elif res["mode"] == "verify_wikipedia":
        res["outcome"] = "mismatch" if info["disambiguation"] else "verified"
    elif info["disambiguation"]:
        res["outcome"] = "ambiguous"
    elif info["mentions_domain"]:
        res["outcome"] = "verified"
    else:
        res["outcome"] = "collision"
    return _save_lookup(ctx, res)


def _save_lookup(ctx, res):
    if ctx.workdir:
        try:
            path = os.path.join(ctx.workdir, LOOKUP_REL)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(res, f, indent=2, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass
    return res


# ---------------------------------------------------------------- checks: entity
def check_sameas(ctx, out, nodes, sameas, lookup, brand):
    if not nodes:
        out.not_evaluated("ef.entity.sameas_missing", reason="dependency_failed")
        out.not_evaluated("ef.entity.sameas_no_authority", reason="dependency_failed")
        return
    types = sorted({(X.node_types(n) or ["?"])[0] for _, n, _ in nodes})
    pages = sorted({p.final_url for p, _, _ in nodes})
    roles = [p.role for p, _, _ in nodes]
    if not sameas:
        items = [evidence_item(p.final_url, "jsonld_excerpt", json.dumps({k: n.get(k) for k in ("@type", "name", "url") if k in n}, ensure_ascii=False)[:200],
                               location="script[type=application/ld+json][%d]" % (i + 1), note="no sameAs property") for p, n, i in nodes[:3]]
        detail = ("Add a sameAs array to the %s node with the brand's authoritative profiles: its Wikidata item and Wikipedia article where they exist, "
                  "the LinkedIn company page, and the national company-register entry. Each URL must point to this brand and nothing else." % types[0])
        if lookup.get("outcome") == "verified" and lookup.get("mode") == "discover":
            items.append(evidence_item("site", "external", "%s (%s)" % (lookup.get("target"), lookup.get("qid") or "no Q-id"),
                                       note="Wikipedia article '%s' mentions %s; a ready-made sameAs target" % (lookup.get("title"), _domain(ctx))))
            detail += " The Wikipedia article '%s' (Wikidata %s) already describes this brand: start with those two URLs." % (lookup.get("title"), lookup.get("qid"))
        out.fail("ef.entity.sameas_missing",
                 title="%s JSON-LD carries no sameAs links to the brand's authoritative profiles" % types[0],
                 evidence="%s node%s on %s ha%s no sameAs property, so nothing in the markup ties '%s' to a Wikidata item, Wikipedia article, or company register." % (
                     "/".join(types), "s" if len(nodes) != 1 else "", ", ".join(sorted(set(roles))), "ve" if len(nodes) != 1 else "s", brand or "the brand"),
                 evidence_items=items,
                 why="sameAs is the one machine-readable statement that says which real-world entity this site is. Without it an assistant matches the brand by name alone, and names collide: the answer may describe a different company, or hedge because it cannot tell.",
                 action="Add sameAs links (Wikidata, Wikipedia, LinkedIn, company register) to the Organization JSON-LD on the home page.",
                 detail=detail, pages=pages, page_roles=roles, references=[REFS["sameas"], REFS["org"]])
        out.not_evaluated("ef.entity.sameas_no_authority", reason="dependency_failed")
        return
    out.check("ef.entity.sameas_missing", "pass", pages=pages)
    hosts = sorted({_host(u) for u in sameas})
    auth = authority_hosts(ctx.category)
    good = [u for u in sameas if any(a in _host(u) for a in auth)]
    if good:
        out.check("ef.entity.sameas_no_authority", "pass", pages=pages)
        return
    out.fail("ef.entity.sameas_no_authority",
             title="sameAs links only to social profiles, none to an authority that fixes the brand's identity",
             evidence="sameAs lists %d URL%s (%s); none points to Wikidata, Wikipedia, LinkedIn, Crunchbase, or a company register." % (
                 len(sameas), "s" if len(sameas) != 1 else "", ", ".join(hosts[:6])),
             evidence_items=[evidence_item(pages[0], "jsonld_excerpt", u, note="sameAs") for u in sameas[:6]],
             why="Social profiles are created by anyone and prove little; a Wikidata item, Wikipedia article, LinkedIn company page, or register entry is what knowledge graphs and assistants use to pin a name to one entity.",
             action="Add at least one authoritative sameAs target (Wikidata item, Wikipedia article, LinkedIn company page, or company-register entry).",
             detail="Keep the social links and add the authoritative ones. If the brand has no Wikidata item, the LinkedIn company page and the official register entry are usually available immediately.",
             pages=pages, page_roles=roles, references=[REFS["sameas"], REFS["wikidata"]])


def check_lookup(ctx, out, lookup, brand, sameas):
    o = lookup.get("outcome")
    dom = _domain(ctx)
    if o == "skipped":
        for cid in ("ef.entity.wikidata_ambiguous", "ef.entity.wikidata_not_found", "ef.entity.wikidata_unavailable"):
            out.not_evaluated(cid, reason=lookup.get("reason") or "no_brand_name")
        return
    if o == "unavailable":
        reason = lookup.get("reason") or "lookup_failed"
        for cid in ("ef.entity.wikidata_ambiguous", "ef.entity.wikidata_not_found"):
            out.not_evaluated(cid, reason="lookup_unavailable")
        out.not_evaluated("ef.entity.wikidata_unavailable", reason=reason, emit_finding=True,
                          title="Entity lookup not performed (%s)" % reason.replace("_", " "),
                          evidence="The one external request this audit makes (%s) did not run: %s. Whether '%s' resolves to a single public entity was not checked." % (
                              lookup.get("target") or "Wikipedia article for the brand name", reason.replace("_", " ") + ((": " + str(lookup.get("error"))) if lookup.get("error") else ""), brand or "the brand"),
                          evidence_items=[evidence_item("site", "external", lookup.get("target") or "-", note="outcome=%s reason=%s" % (o, reason))],
                          why="Without the lookup the audit cannot say whether the brand name collides with other entities that an assistant might describe instead.",
                          action="Re-run with network access (or without --no-external) to complete the entity lookup.",
                          detail="The lookup fetches at most one Wikipedia article or Wikidata EntityData document, with the audit's own user agent, under that host's robots.txt.")
        return
    out.check("ef.entity.wikidata_unavailable", "pass")
    target, title, qid = lookup.get("target"), lookup.get("title"), lookup.get("qid")
    ext = evidence_item("site", "external", target or "-", note="outcome=%s title=%r qid=%s" % (o, title, qid))
    if o == "verified":
        out.check("ef.entity.wikidata_ambiguous", "pass")
        out.check("ef.entity.wikidata_not_found", "pass")
        return
    if o == "not_found":
        verify = lookup.get("mode") != "discover"
        out.check("ef.entity.wikidata_ambiguous", "pass")
        out.fail("ef.entity.wikidata_not_found",
                 title=("sameAs points to a Wikipedia page that does not exist" if verify else "No Wikipedia article (and so no Wikidata item) is found under the brand name"),
                 evidence=("%s returned 404: the sameAs anchor the site publishes is broken." % target if verify else
                           "%s returned 404. The brand name '%s' has no article under that title; a Wikidata item may still exist under another label (low confidence: this is a title lookup, not a search)." % (target, brand)),
                 evidence_items=[ext],
                 why="Knowledge-graph entries are what let assistants say 'X is a company that…' with confidence and disambiguate it from homonyms. A brand with no entry is described from whatever pages happen to rank.",
                 action=("Fix the sameAs URL so it points to the brand's real Wikipedia article or Wikidata item." if verify else
                         "Create or claim a Wikidata item for the brand and link it via sameAs; a Wikipedia article requires independent coverage first."),
                 detail=("Open the URL in a browser, find the correct article, and update the JSON-LD." if verify else
                         "Wikidata accepts items for organisations with a verifiable existence (register entry, official website). Create the item, add official website (P856) and the register identifier, then add its URL to sameAs."),
                 confidence="medium" if verify else "low", references=[REFS["wikidata"]])
        return
    # ambiguous | collision | mismatch
    out.check("ef.entity.wikidata_not_found", "pass")
    if o == "ambiguous":
        ttl = "'%s' is a disambiguation page on Wikipedia and the site does not link its own entity" % (title or brand)
        ev = "%s is a disambiguation page with about %d entries; the site's sameAs (%s) does not point to any of them." % (target, lookup.get("entries") or 0, ", ".join(sameas[:3]) or "none")
        conf = "medium"
    elif o == "collision":
        ttl = "The Wikipedia article '%s' is about a different thing called %s" % ((title or brand)[:40], brand)
        ev = "%s (Wikidata %s) does not mention %s anywhere, so the best-known entity under this name is not this brand, and the site publishes no sameAs to say which one it is." % (target, qid or "unknown", dom or "the site's domain")
        conf = "medium"
    else:
        ttl = "The site's sameAs points to an entity that does not match the brand"
        ev = "%s resolves to '%s' (%s); its label, aliases and official website do not match '%s' or %s." % (target, title or "?", qid or "no Q-id", brand, dom or "the site's domain")
        conf = "medium"
    out.fail("ef.entity.wikidata_ambiguous", title=ttl, evidence=ev, evidence_items=[ext],
             why="This is the mistaken-identity mechanism: when a name maps to several things, an assistant picks the best-documented one. Unless the site itself states which entity it is, answers about the brand may describe someone else.",
             action="Publish sameAs links to the brand's own Wikidata item and Wikipedia article (create the Wikidata item if none exists) so the name resolves to this entity.",
             detail="In the Organization JSON-LD add sameAs with the exact Wikidata item URL for this brand and, if one exists, its Wikipedia article. If the brand has no item yet, create one on Wikidata with the official website (P856) set to %s." % (dom or "the site's domain"),
             confidence=conf, references=[REFS["wikidata"], REFS["sameas"]])


def _domain(ctx):
    return registrable_domain(_host(ctx.site)) if ctx.site else None


def _text_phone(text):
    for m in X.PHONE_TEXT_RE.finditer(text or ""):
        digits = sum(c.isdigit() for c in m.group(0))
        if 9 <= digits <= 15:
            before = text[max(0, m.start() - 30):m.start()]
            if m.group(0).strip().startswith("+") or X.PHONE_CUE_RE.search(before):
                return m.group(0).strip()
    return None


def _text_address(text):
    t = text or ""
    for rx, label in ((X.STREET_RE, "street"), (X.UK_POSTCODE_RE, "uk_postcode"), (X.US_CITY_STATE_ZIP_RE, "us_city_state_zip")):
        m = rx.search(t)
        if m:
            if label == "uk_postcode" and not re.search(r"[A-Za-z]{3,}", t[max(0, m.start() - 40):m.start()]):
                continue
            return t[max(0, m.start() - 30):m.end() + 10].strip(), label
    return None


def check_nap(ctx, out, pages, brand):
    anchor = [p for p in pages if p.role in ("home", "contact", "about")] or pages[:3]
    texts = [(p, p.doc.body_text or "") for p in anchor]
    found = {}
    name = (brand or {}).get("value")
    weak_name = (brand or {}).get("source") == "host"
    if name and not (weak_name and not re.search(r"[A-Za-z]{2}", name)):
        nn = _norm_name(name)
        core = re.sub(r"[^a-z0-9]+", "", (name.split()[0] if name else "").lower())
        for p, t in texts:
            nt = re.sub(r"[^a-z0-9]+", "", t.lower())
            if nn and nn in nt:
                found["name"] = (p, name); break
            if core and len(core) >= 4 and core in nt:
                found["name"] = (p, name.split()[0]); break
        name_evaluated = True
    else:
        name_evaluated = False
    for p, t in texts:
        if "address" not in found:
            a = _text_address(t)
            if a:
                found["address"] = (p, a[0])
        if "phone" not in found:
            ph = _text_phone(t)
            if ph:
                found["phone"] = (p, ph)
        if "email" not in found:
            m = X.EMAIL_RE.search(t)
            if m:
                found["email"] = (p, m.group(0))
    cat = ctx.category
    if cat == "local_business":
        need = {"name": ["name"], "postal address": ["address"], "phone number": ["phone"]}
    elif cat == "portfolio_personal":
        need = {"name": ["name"], "contact (email or phone)": ["email", "phone"]}
    else:
        need = {"name": ["name"], "postal address or phone number": ["address", "phone"]}
    if not name_evaluated:
        need.pop("name", None)
    missing = [label for label, keys in need.items() if not any(k in found for k in keys)]
    roles = ", ".join(p.role for p in anchor)
    items = [evidence_item(p.final_url, "text_excerpt", v[:120], note="%s found" % k) for k, (p, v) in found.items()]
    items.append(evidence_item("site", "computed", "pages_checked=%s; required=%s; missing=%s" % (roles, "|".join(need), ",".join(missing) or "none")))
    if not missing:
        out.check("ef.entity.nap_missing_plain_text", "pass", pages=[p.final_url for p in anchor])
        return
    seen_roles = {p.role for p in anchor}
    out.fail("ef.entity.nap_missing_plain_text",
             confidence="high" if seen_roles & {"contact", "about"} else "medium",
             extra_adjust=None if seen_roles & {"contact", "about"} else ["contact_and_about_not_sampled:confidence_medium"],
             title="%s %s not visible as plain text on the %s page%s" % (" and ".join(m.capitalize() for m in missing), "is" if len(missing) == 1 else "are", roles.replace(", ", "/"), "s" if len(anchor) != 1 else ""),
             evidence="Checked the visible text of %s. Present: %s. Missing: %s. Structured data or images may carry them, but an assistant cross-checking the brand's identity reads the text." % (
                 roles, ", ".join(sorted(found)) or "nothing", ", ".join(missing)),
             evidence_items=items,
             why="Name, address and phone are the three facts every directory, register and knowledge graph holds about a business. When the site itself does not state them as text, the assistant cannot confirm it has the right entity, and inconsistent copies elsewhere win.",
             action="State the organisation name, postal address and phone number as visible text in the site footer or on the contact page.",
             detail="Use the same spelling and format everywhere (footer, contact page, JSON-LD PostalAddress and telephone, Google Business Profile, LinkedIn). A footer line is enough: 'Ledgerly Software Ltd · 12 Harbour Street, Bristol BS1 4QA · +44 117 496 0123'.",
             pages=[p.final_url for p in anchor], page_roles=[p.role for p in anchor], references=[REFS["org"]])


def name_candidates(pages):
    cands = []
    for p in X._ordered(pages, ("home", "about")):
        sn = p.doc.meta("og:site_name", "application-name")
        if sn:
            cands.append((sn.strip(), "meta:og:site_name", p.final_url)); break
    for p in X._ordered(pages, ("home", "about")):
        for n, _ in X.doc_top_nodes(p.doc):
            if X.is_org_node(n, allow_person=True) and isinstance(n.get("name"), str) and n["name"].strip():
                cands.append((n["name"].strip(), "jsonld:%s.name" % (X.node_types(n) or ["?"])[0], p.final_url))
    segs = {}
    for p in pages:
        for seg in re.split(r"\s+[|—–-]\s+|\s*:\s+", p.doc.title or ""):
            seg = seg.strip()
            if 1 <= len(seg.split()) <= 4:
                segs.setdefault(seg, set()).add(p.final_url)
    common = [s for s, urls in sorted(segs.items(), key=lambda x: -len(x[1])) if len(urls) >= 2]
    if common:
        cands.append((common[0], "title:common_segment", None))
    return cands


def check_name_consistency(ctx, out, pages):
    cands = name_candidates(pages)
    distinct = {}
    for val, src, url in cands:
        distinct.setdefault(_norm_name(val), (val, src, url))
    keys = [k for k in distinct if k]
    conflict = any(not (a in b or b in a) for i, a in enumerate(keys) for b in keys[i + 1:])
    if not conflict:
        out.check("ef.entity.name_inconsistent", "pass")
        return
    out.fail("ef.entity.name_inconsistent",
             title="The brand is named differently in the title, og:site_name and JSON-LD",
             evidence="Names seen: %s. Beyond case, punctuation and legal suffixes these do not agree, so a machine sees more than one brand." % "; ".join(
                 "'%s' (%s)" % (v, s) for v, s, _ in (distinct[k] for k in keys)),
             evidence_items=[evidence_item(u or "site", "computed", v, note=s) for v, s, u in (distinct[k] for k in keys)],
             why="Entity resolution starts from the name. Two names on one site look like two brands, or like a brand and a product, and the assistant may cite either.",
             action="Use one canonical brand name in og:site_name, the JSON-LD Organization name and the title suffix.",
             detail="Pick the trading name customers use. Put the legal name in JSON-LD legalName, not name. Update the title template so every page ends with the same brand segment.",
             references=[REFS["org"]])


# ---------------------------------------------------------------- checks: freshness
def check_freshness(ctx, out, pages):
    today = _today()
    per_page = []
    for p in pages:
        vd = visible_dates(p)
        cy = copyright_years(p)
        per_page.append((p, vd, cy, jsonld_dates(p)))
    any_dates = any(vd or cy for _, vd, cy, _ in per_page)
    if any_dates:
        out.check("ef.freshness.no_visible_dates", "pass", pages=[p.final_url for p, vd, cy, _ in per_page if vd or cy])
    else:
        out.fail("ef.freshness.no_visible_dates",
                 title="No visible date anywhere on the sampled pages",
                 evidence="None of the %d sampled pages (%s) shows a date: no <time> element, no written or ISO date, and no copyright year." % (len(pages), ", ".join(p.role for p in pages)),
                 evidence_items=[evidence_item(p.final_url, "computed", "time_elements=%d; text_dates=%d; copyright_year=none" % (len(p.doc.times), 0)) for p in pages[:6]],
                 why="An assistant that fetches at answer time prefers sources it can date. A site with no dates cannot be shown to be current, so a dated copy elsewhere, even a stale one, may be trusted over it.",
                 action="Show a visible 'last updated' date (with <time datetime>) on key pages and a current copyright year in the footer.",
                 detail="Add 'Updated <time datetime=\"YYYY-MM-DD\">…</time>' to the pricing, product and about pages and publication dates to articles, mirrored in JSON-LD dateModified/datePublished. Automate the footer year.",
                 references=[REFS["dates"]])
    stale = [(p, y, ex) for p, _, cy, _ in per_page for y, ex in cy if y <= today.year - STALE_YEARS]
    fresh_years = [y for _, _, cy, _ in per_page for y, _ in cy if y > today.year - STALE_YEARS]
    if stale and not fresh_years:
        pages_s = sorted({p.final_url for p, _, _ in stale})
        out.fail("ef.freshness.stale_copyright_year",
                 title="Footer copyright year is %d, %d years behind" % (max(y for _, y, _ in stale), today.year - max(y for _, y, _ in stale)),
                 evidence="Copyright lines on %s show %s; the current year is %d." % (", ".join(sorted({p.role for p, _, _ in stale})), ", ".join(sorted({str(y) for _, y, _ in stale})), today.year),
                 evidence_items=[evidence_item(p.final_url, "text_excerpt", ex[:120]) for p, y, ex in stale[:4]],
                 why="The copyright year is the cheapest freshness signal on a page and one of the first a reader or a model notices. A year two or more behind reads as an abandoned site, whatever the content says.",
                 action="Make the footer copyright year automatic (current year) in the template.",
                 detail="Most templates support a dynamic year; if not, update it now and add a calendar reminder. A range ('2019–%d') is fine when the later year is current." % today.year,
                 pages=pages_s, page_roles=sorted({p.role for p, _, _ in stale}))
    else:
        out.check("ef.freshness.stale_copyright_year", "pass")
    mismatches = []
    for p, vd, cy, jd in per_page:
        for d, raw, prop, typ in jd:
            if d > today + _dt.timedelta(days=1):
                mismatches.append((p, raw, prop, typ, None, "in the future"))
                continue
            if not vd:
                continue
            nearest = min(vd, key=lambda x: abs((x[0] - d).days))
            gap = abs((nearest[0] - d).days)
            if gap > MISMATCH_DAYS:
                mismatches.append((p, raw, prop, typ, nearest[1], "%d days from the nearest visible date %s" % (gap, nearest[1])))
    if mismatches:
        pages_m = sorted({p.final_url for p, *_ in mismatches})
        out.fail("ef.freshness.date_modified_mismatch",
                 title="JSON-LD dates disagree with the dates shown on the page",
                 evidence="; ".join("%s: %s.%s=%s is %s" % (p.role, typ, prop, raw, why) for p, raw, prop, typ, _, why in mismatches[:4]) + ".",
                 evidence_items=[evidence_item(p.final_url, "jsonld_excerpt", "%s.%s=%s" % (typ, prop, raw), note=why) for p, raw, prop, typ, _, why in mismatches[:6]],
                 why="When the machine-readable date and the visible date disagree, neither can be trusted, and a future or long-past dateModified reads as a template artefact rather than a real update.",
                 action="Make JSON-LD dateModified/datePublished match the dates displayed on the page, generated from the same source.",
                 detail="Emit both from the CMS's real modified timestamp. Never hard-code dates in templates; never set dateModified without a visible 'updated' line to match it.",
                 pages=pages_m, page_roles=sorted({p.role for p, *_ in mismatches}), references=[REFS["dates"]])
    else:
        out.check("ef.freshness.date_modified_mismatch", "pass")


# ---------------------------------------------------------------- checks: corroboration
def press_surface(ctx, pages):
    roles = [p.role for p in ctx.pages]
    if "blog" in roles:
        p = ctx.page("blog")
        return {"kind": "role:blog", "value": p.final_url if p else "/blog", "page": p.final_url if p else None}
    for p in pages:
        for l in p.doc.links:
            if not l.internal or l.href.lower().startswith(("mailto:", "tel:")):
                continue
            segs = [s.lower() for s in urlsplit(l.url).path.split("/") if s]
            if PRESS_LINK_RE.search(l.text or "") or (segs and segs[0] in PRESS_PATH_SEGMENTS):
                return {"kind": "link", "value": "%s -> %s" % ((l.text or "").strip()[:40], l.url), "page": p.final_url}
        if p.doc.feeds:
            return {"kind": "feed", "value": p.doc.feeds[0] if isinstance(p.doc.feeds[0], str) else str(p.doc.feeds[0]), "page": p.final_url}
    return None


def check_press(ctx, out, pages):
    ov = SEVERITY_OVERRIDES.get("ef.corroboration.press_page_missing", {}).get(ctx.category)
    if ov == "not_evaluated":
        out.not_evaluated("ef.corroboration.press_page_missing", reason="not_applicable_for_category")
        return None
    surf = press_surface(ctx, pages)
    if surf:
        out.check("ef.corroboration.press_page_missing", "pass", pages=[surf["page"]] if surf.get("page") else None)
        return surf
    out.fail("ef.corroboration.press_page_missing",
             title="No newsroom, press or blog page for journalists and citers to draw on",
             evidence="No sampled page has the blog/news role and no internal link on the %d sampled pages (%s) is labelled press, news, newsroom, media, blog or updates; no RSS feed is advertised." % (len(pages), ", ".join(p.role for p in pages)),
             evidence_items=[evidence_item(p.final_url, "computed", "press_links=0; feeds=%d" % len(p.doc.feeds)) for p in pages[:6]],
             why="Agreement across the web starts with a source others can cite. A newsroom with dated announcements, a press contact and a media kit is where journalists, directories and models pick up consistent facts; without one, third-party copies drift.",
             action="Add a newsroom or news page with dated announcements, a press contact and a short boilerplate paragraph about the company.",
             detail="Three items are enough to start: a one-paragraph boilerplate (what the company is, where, since when), a press contact email, and a dated list of announcements. Link it from the footer and expose an RSS feed.",
             references=[])
    return None


def offsite_queries(brand, domain, entity):
    b = (brand or {}).get("value") or domain or ""
    qs = ['"%s"' % b, '"%s" %s' % (b, domain or ""), '"%s" reviews' % b, '"%s" site:linkedin.com' % b]
    city = (entity.get("nap") or {}).get("locality")
    if city:
        qs.insert(1, '"%s" %s' % (b, city))
    return [q.strip() for q in qs if q.strip() and q.strip() != '""'][:5]


def check_offsite(ctx, out, brand, domain, entity):
    path = os.path.join(ctx.workdir, OFFSITE_REL) if ctx.workdir else None
    data = None
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:  # noqa: BLE001
            data = {"error": "unreadable: %s" % e}
    queries = offsite_queries(brand, domain, entity)
    entity["suggested_offsite_queries"] = queries
    if data and isinstance(data.get("mentions"), list):
        mentions = [m for m in data["mentions"] if isinstance(m, dict) and m.get("url")]
        kinds = {}
        for m in mentions:
            kinds[m.get("kind") or "other"] = kinds.get(m.get("kind") or "other", 0) + 1
        agree = sum(1 for m in mentions if m.get("agrees_with"))
        out.inconclusive("ef.corroboration.offsite_spotcheck", reason="bounded_spotcheck",
                         title="Off-site spot-check: %d mention%s across %d quer%s" % (len(mentions), "s" if len(mentions) != 1 else "", len(data.get("queries") or []), "ies" if len(data.get("queries") or []) != 1 else "y"),
                         evidence="A bounded search (%s) found %d independent mention%s%s%s. This samples the corroboration surface; it does not measure agreement across the web." % (
                             data.get("tool") or "web search", len(mentions), "s" if len(mentions) != 1 else "",
                             (" by kind: " + ", ".join("%s=%d" % kv for kv in sorted(kinds.items()))) if kinds else "",
                             ("; %d restate a fact from the site" % agree) if agree else ""),
                         evidence_items=[evidence_item("site", "external", m["url"], note="%s%s" % (m.get("kind") or "other", (": " + str(m.get("snippet"))[:120]) if m.get("snippet") else "")) for m in mentions[:6]]
                                        or [evidence_item("site", "computed", "mentions=0; queries=%s" % "; ".join(data.get("queries") or [])[:200])],
                         why="Facts repeated consistently by independent sources are trusted; a claim that exists only on the brand's own site is fragile. The spot-check shows whether any such repetition exists, not how much.",
                         action="Read the mentions listed and correct any that disagree with the site (address, name, what the company does).",
                         detail="Where a directory or profile states an old address or name, update it there. Where nothing exists, the newsroom and profile actions above create the surface.")
        return
    out.not_evaluated("ef.corroboration.offsite_spotcheck", reason="tool_unavailable", emit_finding=True,
                      title="Off-site mention spot-check not performed",
                      evidence="No search-tool result at %s%s. The off-site check is an agent step: it needs a web-search tool, which this script does not have." % (
                          OFFSITE_REL, (" (file present but unreadable: %s)" % data["error"]) if data and data.get("error") else ""),
                      evidence_items=[evidence_item("site", "computed", "suggested_queries=" + " | ".join(queries))],
                      why="Without it the report says nothing about whether independent sources repeat the brand's facts; that is a limitation, not a defect of the site.",
                      action="Run the bounded spot-check described in SKILL.md (at most five searches), write work/offsite_mentions.json, and re-run this probe.",
                      detail="Search the suggested queries with a web-search tool, record up to ten mentions with url, kind (news, directory, review, social, wiki, other) and whether each restates a site fact, then re-run with --workdir.")


# ---------------------------------------------------------------- entity file
def write_entity(ctx, entity):
    if not ctx.workdir:
        return None
    path = os.path.join(ctx.workdir, ENTITY_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entity, f, indent=2, ensure_ascii=False)
    return ENTITY_REL


# ---------------------------------------------------------------- main
def _all_not_evaluated(out, reason):
    out.fill_unreported("ef.", status="not_evaluated")
    for c in out.checks:
        c["reason"] = reason


def run(ctx, args=None):
    out = ProbeOutput(PROBE, ctx.site, ctx.category, [], total_sampled_pages=len(ctx.pages))
    external = _external_enabled(args) and not (ctx.fetcher is not None and getattr(ctx.fetcher, "offline", False))
    domain = _domain(ctx)
    entity = {"site": ctx.site, "domain": domain, "site_category": ctx.category, "extracted_at": _now(), "external_lookups": external}
    if ctx.error:
        out.error = ctx.error
        _all_not_evaluated(out, "context_error")
        return out
    home = ctx.home
    usable, excluded = [], []
    for p in ctx.pages:
        if p.skipped:
            excluded.append((p, p.skipped)); continue
        if p.challenge:
            excluded.append((p, "challenge_page")); continue
        if p.error or (p.status or 0) >= 400:
            excluded.append((p, "network_disabled" if p.error == "network_disabled" else "http_error")); continue
        if not p.ok_html:
            excluded.append((p, "non_html")); continue
        if render_state(p.doc) in ("gate", "shell"):
            excluded.append((p, "no_rendered_content")); continue
        usable.append(p)
    out.pages_examined = [p.final_url for p in usable]
    entity["pages_used"] = [p.final_url for p in usable]
    entity["pages_excluded"] = [{"role": p.role, "url": p.final_url, "reason": r} for p, r in excluded]
    if not usable:
        reasons = [r for _, r in excluded]
        if home is not None and home.skipped == "robots_disallow":
            reason = "robots_disallow"
        elif reasons and all(r == "network_disabled" for r in reasons):
            reason = "network_disabled"
        elif reasons and all(r == "challenge_page" for r in reasons):
            reason = "challenge_page"
        elif any(r == "no_rendered_content" for r in reasons):
            reason = "no_rendered_content"
        elif reasons and all(r == "non_html" for r in reasons):
            reason = "non_html"
        else:
            reason = "no_html_pages"
        brand = {"value": None, "source": None, "page": None}
        lookup = {"outcome": "unavailable", "reason": "network_disabled"} if not external else {"outcome": "skipped", "reason": reason}
        try:
            check_lookup(ctx, out, lookup, None, [])
            check_offsite(ctx, out, brand, domain, entity)
        except Exception as e:  # noqa: BLE001
            out.error = "degraded path: %s: %s" % (type(e).__name__, e)
        out.fill_unreported("ef.", status="not_evaluated")
        for c in out.checks:
            if c["status"] == "not_evaluated" and "reason" not in c:
                c["reason"] = reason
        entity.update({"brand_name": brand, "lookup": lookup})
        try:
            rel = write_entity(ctx, entity)
            if rel:
                out.artifacts["entity"] = rel
        except Exception as e:  # noqa: BLE001
            out.error = ((out.error or "") + " entity file: %s" % e).strip()
        return out
    brand = X.brand_name(usable, ctx.site)
    nodes = org_nodes(usable, ctx.category)
    sameas = sameas_urls(nodes)
    entity.update({"brand_name": brand, "org_node_types": sorted({(X.node_types(n) or ["?"])[0] for _, n, _ in nodes}), "sameas": sameas,
                   "authority_hosts_present": sorted({_host(u) for u in sameas if any(a in _host(u) for a in authority_hosts(ctx.category))})})
    try:
        lookup = entity_lookup(ctx, brand.get("value"), sameas, external, domain)
    except Exception as e:  # noqa: BLE001
        lookup = {"outcome": "unavailable", "reason": "lookup_failed", "error": "%s: %s" % (type(e).__name__, e)}
    entity["lookup"] = lookup
    entity["name_candidates"] = [{"value": v, "source": s, "page": u} for v, s, u in name_candidates(usable)]
    for name, fn, a in (("lookup", check_lookup, (ctx, out, lookup, brand.get("value"), sameas)),
                        ("sameas", check_sameas, (ctx, out, nodes, sameas, lookup, brand.get("value"))),
                        ("nap", check_nap, (ctx, out, usable, brand)),
                        ("name", check_name_consistency, (ctx, out, usable)),
                        ("freshness", check_freshness, (ctx, out, usable)),
                        ("press", check_press, (ctx, out, usable)),
                        ("offsite", check_offsite, (ctx, out, brand, domain, entity))):
        try:
            r = fn(*a)
            if name == "press":
                entity["press_surface"] = r
        except Exception as e:  # noqa: BLE001
            out.error = ((out.error or "") + " %s checks: %s: %s" % (name, type(e).__name__, e)).strip()
    out.fill_unreported("ef.", status="not_evaluated")
    for c in out.checks:
        if c["status"] == "not_evaluated" and "reason" not in c:
            c["reason"] = "dependency_failed"
    try:
        rel = write_entity(ctx, entity)
        if rel:
            out.artifacts["entity"] = rel
        if ctx.workdir and os.path.exists(os.path.join(ctx.workdir, LOOKUP_REL)):
            out.artifacts["entity_lookup"] = LOOKUP_REL
    except Exception as e:  # noqa: BLE001
        out.error = ((out.error or "") + " entity file: %s" % e).strip()
    return out


def _extra_args(ap):
    ap.add_argument("--no-external", action="store_true", help="skip the one Wikipedia/Wikidata request (also BRAND_AUDIT_EXTERNAL=0)")


def main(argv=None):
    return probe_main(PROBE, run, __doc__, argv, extra_args=_extra_args)


if __name__ == "__main__":
    sys.exit(main())
