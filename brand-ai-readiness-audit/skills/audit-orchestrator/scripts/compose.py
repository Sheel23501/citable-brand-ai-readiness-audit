#!/usr/bin/env python3
"""compose.py: merge the probe outputs in a workdir into one report.json and render report.md.

  compose.py --workdir audit-example                    # writes <workdir>/report.json and report.md
  compose.py --workdir audit-example --render-only      # re-renders report.md from an existing report.json

What it does, in the order the conventions require:

  1. read sample.json, probes/*.json and work/extracted_facts.json  (report_schema.md section 5)
  2. merge every finding, keeping its source skill                   (section 4 rule 1)
  3. apply the 12-row dedupe table with severity inheritance         (coverage_map.md section 4)
  4. sort, assign F-### ids and ranks, count                         (section 4 rules 3-5)
  5. add the derived tags no probe may set                           (coverage_map.md section 7)
  6. build passed_checks, coverage, limitations, proactive_recommendations
  7. pre-fill the AI-answer simulation from the facts file alone     (site_categories.md section 6)
  8. emit or.simulation.question_unanswerable and or.run.probe_error (check_ids.md)
  9. render the Markdown, which contains nothing the JSON does not   (report_schema.md section 6)

`narrative_summary`, each question's `answer_from_facts`, and `attribution_note` are left empty
for the orchestrator agent (Step 17). Standard library only. Never raises: on an internal error it
still writes a valid report whose only finding is `or.run.probe_error`.
"""
import argparse
import collections
import datetime as _dt
import json
import os
import re
import sys
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from auditlib import __version__  # noqa: E402
from auditlib.fetch import language_edition as _language_edition  # noqa: E402
from auditlib.categories import (AUDIENCE_FACT, AUDIENCE_PHRASE, CTA_LANGS_SUPPORTED, FACT_ROLES, KEY_FACTS,  # noqa: E402
                                 SIMULATION_QUESTIONS, category_label, key_pages)
from auditlib.findings import (SEVERITIES, Registry, ProbeOutput, evidence_item,  # noqa: E402
                               impact_for, priority_for, _title)

REFERENCES_DIR = os.path.normpath(os.path.join(HERE, "..", "references"))
COVERAGE_MAP_MD = os.path.join(REFERENCES_DIR, "coverage_map.md")

TOOL_NAME = "brand-ai-readiness-audit"
STAGE_ORDER = ("access", "render", "extract", "entity", "freshness", "corroboration", "engagement")
PROBE_PREFIX = {"crawl-render-audit": "cr.", "fact-extractability-audit": "fx.",
                "entity-freshness-corroboration-audit": "ef.", "engagement-audit": "en."}
PROBE_ORDER = ("crawl-render-audit", "fact-extractability-audit",
               "entity-freshness-corroboration-audit", "engagement-audit")

# coverage_map.md section 7. Derived tags: a probe never sets these, compose always does.
STAGE_CONCEPTS = {"access": ["A", "B"], "render": ["A", "C"], "extract": ["A", "B", "C"], "entity": ["D"],
                  "freshness": ["B", "D"], "corroboration": ["D"], "engagement": []}
STAGE_PIPELINE = {"access": "retrieval", "render": "retrieval", "extract": "ranking", "entity": "ranking",
                  "freshness": "ranking", "corroboration": "ranking", "engagement": "post_click"}
STAGE_MODE = {"access": "invisible", "render": "invisible", "extract": "invisible", "entity": "stale",
              "freshness": "stale", "corroboration": "stale", "engagement": "bouncing"}
CONTENT_EN = ("en.hero.", "en.cta.", "en.trust.", "en.continuity.", "en.nav.related_links_missing")

# Positive titles for `passed_checks`: the pass condition of every registry row, said as a fact about
# the site. check_ids.md owns the rows and names this table; tests assert the two agree exactly.
POSITIVE_TITLES = {
    "cr.robots.unreachable": "robots.txt was fetched and parsed",
    "cr.robots.blanket_disallow": "robots.txt does not blanket-disallow crawlers",
    "cr.robots.live_answer_bot_blocked": "Assistant answer-time bots are allowed to crawl",
    "cr.robots.index_bot_blocked": "Search index bots are allowed to crawl",
    "cr.robots.training_bot_blocked": "Training-only bots are not blocked",
    "cr.robots.key_page_disallowed": "Every sampled key page is crawlable",
    "cr.access.http_error": "Every sampled page returned a successful HTTP status",
    "cr.access.challenge_page": "No page served a bot challenge to the audit fetcher",
    "cr.access.non_html_seed": "The home URL returns an HTML document",
    "cr.access.edge_block": "AI crawlers are served the page, not refused at the edge",
    "cr.access.edge_block_training": "Training-only crawlers are not refused at the edge",
    "cr.access.ua_content_variance": "The page is the same size for every crawler tested",
    "cr.render.js_gate": "No sampled page hides its content behind a JavaScript gate",
    "cr.render.csr_shell": "Sampled pages carry their text in the server response",
    "cr.index.sitemap_missing": "A sitemap is published",
    "cr.index.sitemap_invalid": "The sitemap parses and lists URLs",
    "cr.index.noindex_on_key_page": "No key page is marked noindex",
    "cr.index.canonical_offsite": "No canonical URL points to another domain",
    "cr.index.canonical_mismatch": "Canonical URLs match the pages that declare them",
    "fx.facts.key_fact_missing": "Every key fact for this category is stated in plain text",
    "fx.facts.image_only": "No key fact is locked inside an image",
    "fx.jsonld.missing": "Structured data (JSON-LD) is present",
    "fx.jsonld.malformed": "Every JSON-LD block parses",
    "fx.jsonld.required_props_missing": "JSON-LD nodes carry their identifying properties",
    "fx.jsonld.no_organization": "An Organization or Person node identifies the site",
    "fx.identity.title_missing_or_generic": "Every sampled page has a specific title",
    "fx.identity.h1_missing_or_multiple": "Every sampled page has exactly one main heading",
    "fx.identity.meta_description_missing": "Every sampled page has a meta description",
    "fx.identity.og_missing": "Open Graph title or description is present",
    "fx.media.alt_text_missing": "Content images carry alt text",
    "fx.content.faq_absent": "The site answers questions in an FAQ-shaped section",
    "ef.entity.sameas_missing": "The Organization node links out with sameAs",
    "ef.entity.sameas_no_authority": "sameAs points at an authoritative profile",
    "ef.entity.wikidata_ambiguous": "The brand name resolves to this brand",
    "ef.entity.wikidata_not_found": "The brand name was found in the reference source",
    "ef.entity.wikidata_unavailable": "The entity lookup ran",
    "ef.entity.nap_missing_plain_text": "The name and contact details are visible text",
    "ef.entity.name_inconsistent": "The brand is named consistently across the site",
    "ef.freshness.no_visible_dates": "Pages carry visible dates",
    "ef.freshness.stale_copyright_year": "The copyright year is current",
    "ef.freshness.date_modified_mismatch": "Structured dates agree with the visible dates",
    "ef.corroboration.press_page_missing": "The site offers a press, news or blog surface",
    "ef.corroboration.offsite_spotcheck": "The off-site mention spot-check ran",
    "en.hero.value_prop_unclear": "The home page says what is offered, in the first screen",
    "en.cta.missing": "Every key page offers a clear next step",
    "en.nav.landmark_missing": "The site has a navigation landmark",
    "en.links.broken_sampled": "Every sampled internal link resolves",
    "en.links.blocked_cluster": "No cluster of links blocked the audit fetcher",
    "en.mobile.viewport_missing": "Pages declare a mobile viewport",
    "en.perf.page_weight_heavy": "Page weight is within the proxy thresholds",
    "en.trust.signals_missing": "The trust signals expected for this category are present",
    "en.continuity.h1_title_mismatch": "Headings match the titles visitors arrive on",
    "en.nav.breadcrumbs_missing": "Interior pages show breadcrumbs",
    "en.nav.related_links_missing": "Detail pages link onward to related content",
    "en.nav.site_search_missing": "The site offers a search field",
    "en.interstitial.blocking": "No interstitial covers the content on arrival",
    "en.lang.attribute_missing": "The page declares its language",
    "en.errors.soft_404": "A missing page returns a real 404",
    "en.errors.unhelpful_404": "The 404 page helps a visitor continue",
    "or.simulation.question_unanswerable": "Every simulated question can be answered from the site's own text",
    "or.run.probe_error": "Every probe completed without an internal error",
}


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sev_index(s):
    return SEVERITIES.index(s) if s in SEVERITIES else len(SEVERITIES)


def _host(url):
    h = (urlsplit(url or "").netloc or "").lower()
    return h[4:] if h.startswith("www.") else h


# ---------------------------------------------------------------- loading
def load_workdir(workdir):
    """Read sample.json, probes/*.json and the facts file. Missing pieces are reported, never raised."""
    data = {"workdir": workdir, "sample": {}, "probes": [], "facts": None, "load_errors": []}
    try:
        with open(os.path.join(workdir, "sample.json"), encoding="utf-8") as f:
            data["sample"] = json.load(f)
    except Exception as e:  # noqa: BLE001
        data["load_errors"].append("sample.json unreadable: %s" % e)
    pdir = os.path.join(workdir, "probes")
    names = []
    try:
        names = sorted(n for n in os.listdir(pdir) if n.endswith(".json"))
    except OSError:
        data["load_errors"].append("no probes/ directory in the workdir")
    order = {n + ".json": i for i, n in enumerate(PROBE_ORDER)}
    for name in sorted(names, key=lambda n: (order.get(n, len(order)), n)):
        try:
            with open(os.path.join(pdir, name), encoding="utf-8") as f:
                data["probes"].append(json.load(f))
        except Exception as e:  # noqa: BLE001
            data["load_errors"].append("%s unreadable: %s" % (name, e))
    for probe in data["probes"]:
        rel = (probe.get("artifacts") or {}).get("extracted_facts")
        if rel and data["facts"] is None:
            try:
                with open(os.path.join(workdir, rel), encoding="utf-8") as f:
                    data["facts"] = json.load(f)
            except Exception as e:  # noqa: BLE001
                data["load_errors"].append("%s unreadable: %s" % (rel, e))
    return data


def collect_checks(probes, registry):
    """check_id -> {status, reason, pages, source_skill}. Prefixes are disjoint, so no probe can overwrite another."""
    checks = {}
    for probe in probes:
        skill = probe.get("probe") or "unknown"
        for c in probe.get("checks", []):
            cid = c.get("check_id")
            if not cid or cid not in registry:
                continue
            checks[cid] = {"check_id": cid, "status": c.get("status"), "reason": c.get("reason"),
                           "pages": c.get("pages") or [], "source_skill": skill}
    return checks


# ---------------------------------------------------------------- dedupe (coverage_map.md section 4)
RENDER_SUPPRESSES = ("fx.facts.image_only", "fx.identity.", "fx.media.", "en.hero.", "en.cta.",
                     "en.trust.", "en.continuity.", "en.interstitial.", "en.nav.related_links_missing")
ROBOTS_TIER = {"cr.robots.live_answer_bot_blocked": "live_answer", "cr.robots.index_bot_blocked": "index",
               "cr.robots.training_bot_blocked": "training_only", "cr.robots.key_page_disallowed": "key pages"}


def _by_id(findings, *check_ids):
    return [f for f in findings if not f.get("_suppressed") and f["check_id"] in check_ids]


def _pages_of(finding):
    return set(finding.get("affected_pages") or [])


def _computed(finding, needle):
    """The first computed evidence value on this finding containing `needle`, or None."""
    for it in finding.get("evidence_items") or []:
        if it.get("kind") == "computed" and needle in (it.get("value") or ""):
            return it["value"]
    return None


def _locations(finding):
    return {it.get("location") for it in finding.get("evidence_items") or [] if it.get("location")}


def _h1_absent_pages(finding):
    """Pages where fx.identity.h1_missing_or_multiple saw zero h1 (row 10 fires on absence, not duplication)."""
    out = set()
    for it in finding.get("evidence_items") or []:
        if it.get("kind") == "computed" and re.search(r"\bh1_count=0\b", it.get("value") or ""):
            out.add(it.get("page"))
    return out


def _fold(primary, victim, note):
    """Move `victim` under `primary`: record it, append the one-line note, inherit a higher severity."""
    victim["_suppressed"] = True
    victim["_merged_into_key"] = primary["dedupe_key"]
    primary.setdefault("merged_from", []).append(victim["dedupe_key"])
    if note and note not in primary.setdefault("_notes", []):
        primary["_notes"].append(note)
        primary["evidence_items"].append(evidence_item(
            (primary.get("affected_pages") or ["site"])[0], "computed",
            "folded=%s; note=%s" % (victim["check_id"], note)))
        if len(primary["evidence"]) + len(note) + 3 <= 300:
            primary["evidence"] = primary["evidence"].rstrip() + " (" + note + ")"
    # Severity inheritance. An `inconclusive` or `not_evaluated` primary stays `info`: the rubric's hard
    # rule outranks inheritance, and the registry's max severity for those rows is info.
    if primary.get("status") == "fail" and _sev_index(victim["severity"]) < _sev_index(primary["severity"]):
        ceiling = primary.get("_max_severity", "info")
        raised = victim["severity"] if _sev_index(victim["severity"]) >= _sev_index(ceiling) else ceiling
        if _sev_index(raised) < _sev_index(primary["severity"]):
            primary["severity"] = raised
            primary["evidence_items"].append(evidence_item(
                (primary.get("affected_pages") or ["site"])[0], "computed",
                "severity_inherited_from=%s" % victim["check_id"]))
            sa = primary.get("suggested_action") or {}
            sa["impact"] = impact_for(raised)
            sa["priority"] = priority_for(raised, primary.get("confidence", "high"))


def dedupe(findings, sample, category=None):
    """The 12 rows of coverage_map.md section 4, applied in order. Nothing is deleted; folded findings
    are marked and returned separately with `merged_into` filled in once ids exist."""
    home_url = None
    html_urls = set()
    for p in sample.get("pages") or []:
        fr = p.get("fetch") or {}
        url = fr.get("final_url") or p.get("url")
        if p.get("role") == "home":
            home_url = url
        if fr.get("status") == 200 and fr.get("is_html") and not fr.get("challenge"):
            html_urls.add(url)

    # 1. challenge page: every other per-page finding on that page
    for primary in _by_id(findings, "cr.access.challenge_page"):
        pages = _pages_of(primary)
        for f in findings:
            if f is primary or f.get("_suppressed") or f["check_id"] == "cr.access.challenge_page":
                continue
            if _pages_of(f) and _pages_of(f) <= pages:
                _fold(primary, f, "downstream checks on this page are inconclusive")

    # 2. blanket disallow: every tiered robots finding
    for primary in _by_id(findings, "cr.robots.blanket_disallow"):
        tiers = []
        for f in _by_id(findings, *ROBOTS_TIER):
            tiers.append(ROBOTS_TIER[f["check_id"]])
            _fold(primary, f, "affected tiers: " + ", ".join(tiers))

    # 3. non-HTML home: every per-page finding on home
    for primary in _by_id(findings, "cr.access.non_html_seed"):
        for f in findings:
            if f is primary or f.get("_suppressed") or not home_url:
                continue
            if _pages_of(f) and _pages_of(f) <= {home_url}:
                _fold(primary, f, "home is not an HTML document")

    # 4. gate or shell: the content checks on the same page
    gated = set()
    for primary in _by_id(findings, "cr.render.js_gate", "cr.render.csr_shell"):
        pages = _pages_of(primary)
        gated |= pages
        for f in findings:
            if f is primary or f.get("_suppressed"):
                continue
            if not any(f["check_id"].startswith(pre) or f["check_id"] == pre for pre in RENDER_SUPPRESSES):
                continue
            if _pages_of(f) and _pages_of(f) <= pages:
                _fold(primary, f, "root cause: content is not present in the server response")

    # 5. gate or shell on home, and nothing else was rendered: the site-level key-fact finding
    if gated and (html_urls <= gated or len(html_urls) <= 1):
        for primary in _by_id(findings, "cr.render.js_gate", "cr.render.csr_shell"):
            if home_url and home_url not in _pages_of(primary):
                continue
            for f in _by_id(findings, "fx.facts.key_fact_missing"):
                _fold(primary, f, "facts cannot be extracted because pages are not rendered server-side")

    # 6. no JSON-LD anywhere: the findings that adding Organization JSON-LD would resolve
    for primary in _by_id(findings, "fx.jsonld.missing"):
        for f in _by_id(findings, "ef.entity.sameas_missing", "fx.jsonld.no_organization"):
            _fold(primary, f, "adding Organization JSON-LD with sameAs resolves the folded findings")
        for f in _by_id(findings, "ef.entity.name_inconsistent"):
            # only the JSON-LD leg of the name comparison; with no JSON-LD at all there is none, so this
            # clause is a safety net rather than a path the probes can currently reach
            if any("jsonld" in (it.get("note") or "").lower() for it in f.get("evidence_items") or []):
                _fold(primary, f, "adding Organization JSON-LD with sameAs resolves the folded findings")

    # 7. malformed block: the required-property finding for the same block
    for primary in _by_id(findings, "fx.jsonld.malformed"):
        for f in _by_id(findings, "fx.jsonld.required_props_missing"):
            if _pages_of(f) <= _pages_of(primary) and (_locations(f) & _locations(primary)):
                _fold(primary, f, "")

    # 8. NAP for a local business: the key-fact finding when it names only address and phone
    if (category or (sample.get("site_category") or {}).get("value")) == "local_business":
        for primary in _by_id(findings, "ef.entity.nap_missing_plain_text"):
            for f in _by_id(findings, "fx.facts.key_fact_missing"):
                missing = _computed(f, "missing=") or ""
                names = {m.strip() for m in (missing.split("missing=")[-1]).split(";")[0].split(",") if m.strip()}
                if names and names <= {"address", "phone"}:
                    _fold(primary, f, "also a category key fact")

    # 9. blocked cluster: broken-link entries that are only 403/429
    for primary in _by_id(findings, "en.links.blocked_cluster"):
        for f in _by_id(findings, "en.links.broken_sampled"):
            statuses = re.findall(r"->\s*(\d{3})", json.dumps(f.get("evidence_items") or []))
            if statuses and all(s in ("403", "429") for s in statuses):
                _fold(primary, f, "reclassified: fetcher blocked, not broken")

    # 10. no h1 on the page: the engagement checks that need one
    for primary in _by_id(findings, "fx.identity.h1_missing_or_multiple"):
        absent = _h1_absent_pages(primary)
        if not absent:
            continue
        for f in _by_id(findings, "en.continuity.h1_title_mismatch"):
            if _pages_of(f) and _pages_of(f) <= absent:
                _fold(primary, f, "continuity not evaluable without an H1")
        for f in _by_id(findings, "en.hero.value_prop_unclear"):
            signals = _computed(f, "signals=") or ""
            if _pages_of(f) and _pages_of(f) <= absent and ("h1_missing" in signals or "h1_empty" in signals):
                _fold(primary, f, "continuity not evaluable without an H1")

    # 11. no sitemap: the invalid-sitemap finding
    for primary in _by_id(findings, "cr.index.sitemap_missing"):
        for f in _by_id(findings, "cr.index.sitemap_invalid"):
            _fold(primary, f, "")

    # 12. lookup did not run: the lookup verdicts
    for primary in _by_id(findings, "ef.entity.wikidata_unavailable"):
        for f in _by_id(findings, "ef.entity.wikidata_ambiguous", "ef.entity.wikidata_not_found"):
            _fold(primary, f, "")

    kept = [f for f in findings if not f.get("_suppressed")]
    folded = [f for f in findings if f.get("_suppressed")]
    return kept, folded


# ---------------------------------------------------------------- the absence gate (rubric section 3, rule 6)
# An absence finding is a claim about a *site*, made from a *sample* of it. When the page where the
# missing thing would live was never fetched, "absent from the site" and "absent from the pages I
# read" are different statements, and the audit must not make them in the same voice. The sampler
# records the roles it could not reach in sample.missing_roles; this gate is the only place that
# turns them into verdicts. A two-page sample of a JS-navigated site once produced high-confidence
# "no newsroom" and "key fact missing" findings about pages that were never read.
#
# Presence findings (an image-only h1, malformed JSON-LD on a page that was fully parsed) are
# page-local and cannot be wrong this way. Per-page absence findings (en.cta.missing,
# en.trust.signals_missing) name the pages they graded and claim nothing about the others, so they
# are not gated either. Two rules keep the gate from over-suppressing real findings:
#   * a role the category does not expect is never "unreached": a nonprofit has no pricing page, so
#     not finding one says nothing (site_categories.md section 1, key_pages());
#   * key facts are scoped one fact at a time (FACT_ROLES): "no mission statement on the About page
#     we read" stays a confirmed finding when only the contact page, where the address would live,
#     was missed. The severity is then recomputed from the facts that were actually checked.
#
# Site-level absence checks whose evidence can live only on the listed role pages.
ABSENCE_ROLES = {
    "ef.entity.nap_missing_plain_text": ("contact", "about"),
    "fx.content.faq_absent": ("pricing", "product", "about"),
}
# press_page_missing is decided from the links of every page read, so it needs no blog page to have a
# verdict; it is gated only when the sample is too thin to have shown the site's navigation at all.
NAV_THIN_LINKS = 3    # home exposed this many internal links or fewer to a non-JavaScript fetcher
NAV_THIN_ROLES = 4    # this many of the five roles not found: at most one role page was reached
GATE_REASONS = ("role_page_not_sampled", "navigation_not_readable")


def _resync_action(f):
    """Keep suggested_action in step after a gate lowers severity or confidence.

    report_schema.md requires priority to be the impact of the severity, lowered one level when confidence
    is low. A gate that changes either without recomputing this writes a report the validator rejects.
    """
    act = f.setdefault("suggested_action", {})
    act["impact"] = impact_for(f.get("severity"))
    act["priority"] = priority_for(f.get("severity"), f.get("confidence"))


def _roles_text(roles):
    roles = list(roles)
    if len(roles) == 1:
        return "%s page" % roles[0]
    return "%s and %s pages" % (", ".join(roles[:-1]), roles[-1])


def _role_phrase(roles):
    return _roles_text(roles) + (" was" if len(list(roles)) == 1 else " were")


def _pages_read(sample):
    """Sampled pages that were actually read: fetched 200, HTML, not a challenge page."""
    out = []
    for p in sample.get("pages") or []:
        fetch = p.get("fetch") or {}
        if fetch.get("status") == 200 and fetch.get("is_html") and not fetch.get("challenge"):
            out.append(p)
    return out


def _blind_roles(roles, missing, category):
    """The listed roles the category expects that were not reached. Home is always read."""
    expected = set(key_pages(category))
    return [r for r in roles if r != "home" and r in expected and r in missing]


def _gate_not_evaluated(f, checks, reason):
    """The check has no verdict: drop the finding; coverage and limitations carry the reason."""
    f["_gated"] = reason
    c = checks.get(f["check_id"])
    if c is not None:
        c["status"] = "not_evaluated"
        c["reason"] = reason


def _append_note(evidence, note):
    """Append a gate's note inside the 300-character evidence limit, cutting the original at a sentence end."""
    room = 300 - len(note)
    head = evidence or ""
    if len(head) > room:
        cut = head[:room]
        dot = cut.rfind(". ")
        head = cut[:dot + 1] if dot > room // 2 else cut.rstrip() + "…"
    return (head.rstrip() + note)[:300]


def _gate_sample_scope(f, blind, n_read, note=None):
    """The finding stands as a claim about the pages read: confidence low, severity at most medium."""
    f["confidence"] = "low"
    if f.get("severity") in ("critical", "high"):
        f["severity"] = "medium"
    _resync_action(f)
    f["absence_scope"] = "sample"
    note = note or (" The %s not reached in this sample, so this describes the %d page%s read, not the whole site."
                    % (_role_phrase(blind), n_read, "s" if n_read != 1 else ""))
    f["evidence"] = _append_note(f.get("evidence", ""), note)
    f.setdefault("evidence_items", []).append(
        evidence_item("site", "computed", "absence_scope=sample; roles_not_sampled=%s" % ",".join(blind)))


def _missing_fact_ids(f, category, facts):
    """The key facts the finding reports missing: its own computed evidence first, the facts file as fallback."""
    for it in f.get("evidence_items") or []:
        m = re.search(r"\bmissing=([\w,]+)", it.get("value") or "")
        if m:
            return [x for x in m.group(1).split(",") if x]
    table = facts.get("facts") if isinstance(facts, dict) else None
    if isinstance(table, dict):
        return [fid for fid in KEY_FACTS.get(category, KEY_FACTS["unknown"])
                if (table.get(fid) or {}).get("status", "absent") != "present"]
    return []


def _gate_key_facts(f, checks, sample, category, facts, missing, n_read):
    """One fact at a time: a fact is confirmed missing only when every page it would live on was read."""
    fids = _missing_fact_ids(f, category, facts)
    if not fids:
        return
    unchecked = {}
    for fid in fids:
        blind = _blind_roles(FACT_ROLES.get(fid, ()), missing, category)
        if blind:
            unchecked[fid] = blind
    if not unchecked:
        return
    confirmed = [fid for fid in fids if fid not in unchecked]
    if not confirmed:
        _gate_not_evaluated(f, checks, "role_page_not_sampled")
        return
    total = len(KEY_FACTS.get(category, KEY_FACTS["unknown"]))
    roles_read = [p.get("role") or "?" for p in _pages_read(sample)]
    if len(confirmed) == 1 and f.get("severity") in ("critical", "high"):
        f["severity"] = "medium"      # rubric rule 2 (one fact is medium, two or more high), on the confirmed count
    _resync_action(f)
    f["absence_scope"] = "sample"
    title = ("%d of %d key facts for %s are not extractable as text; %d not checked"
             % (len(confirmed), total, category_label(category), len(unchecked)))
    if len(title) > 90:   # long category labels: keep both counts, drop the label rather than truncate mid-sentence
        title = "%d of %d key facts are not extractable as text; %d not checked (%s unreached)" % (
            len(confirmed), total, len(unchecked), ", ".join(sorted({r for b in unchecked.values() for r in b})))
    f["title"] = _title(title)
    not_checked = "; ".join("%s (%s not reached)" % (fid, _roles_text(b)) for fid, b in unchecked.items())
    evidence = ("Searched %d sampled page%s (%s). Confirmed missing: %s. Not checked: %s."
                % (n_read, "s" if n_read != 1 else "", ", ".join(roles_read), ", ".join(confirmed), not_checked))
    if len(evidence) > 300:
        evidence = ("Searched %d sampled page%s. Confirmed missing: %s. Not checked: %s."
                    % (n_read, "s" if n_read != 1 else "", ", ".join(confirmed), ", ".join(unchecked)))
    f["evidence"] = evidence[:300]
    f.setdefault("evidence_items", []).append(evidence_item(
        "site", "computed", "absence_scope=sample; confirmed_missing=%s; not_checked=%s; roles_not_sampled=%s"
        % (",".join(confirmed), ",".join(unchecked), ",".join(sorted({r for b in unchecked.values() for r in b})))))
    act = f.setdefault("suggested_action", {})
    act["summary"] = ("Add the missing facts as plain text on the pages a visitor would expect them (%s)."
                      % ", ".join(fid.replace("_", " ") for fid in confirmed[:4]))


def _gate_press(f, checks, sample, missing):
    """A link-based absence claim needs a readable navigation; one role page found is not one."""
    links = sample.get("internal_links_seen")
    thin_links = isinstance(links, int) and links <= NAV_THIN_LINKS
    if "blog" in missing and (thin_links or len(missing) >= NAV_THIN_ROLES):
        _gate_not_evaluated(f, checks, "navigation_not_readable")


def apply_absence_gate(findings, checks, sample, category=None, facts=None):
    """Scope every absence claim to what was actually read. Returns the findings that keep a verdict.

    Fully blind (no page that could have carried the thing was read, for a role the category expects):
    the check has no verdict. Its status becomes not_evaluated with the reason, the finding is dropped,
    and coverage plus a limitations line carry it. It is never reported as a defect.
    Partly blind: the finding stands as a claim about the pages read, at low confidence and at most
    medium severity, and its evidence names the pages that were not reached. Key facts are scoped
    one fact at a time (_gate_key_facts); the press check on the navigation being readable (_gate_press).
    """
    missing = set(sample.get("missing_roles") or [])
    if not missing:
        return findings
    category = category or (sample.get("site_category") or {}).get("value") or "unknown"
    n_read = len(_pages_read(sample))
    for f in findings:
        cid = f.get("check_id")
        if f.get("status") != "fail":
            continue
        if cid == "fx.facts.key_fact_missing":
            _gate_key_facts(f, checks, sample, category, facts, missing, n_read)
        elif cid == "ef.corroboration.press_page_missing":
            _gate_press(f, checks, sample, missing)
        elif cid in ABSENCE_ROLES:
            expected = [r for r in ABSENCE_ROLES[cid] if r in key_pages(category)]
            blind = _blind_roles(ABSENCE_ROLES[cid], missing, category)
            if not blind:
                continue
            if len(blind) == len(expected):
                _gate_not_evaluated(f, checks, "role_page_not_sampled")
            else:
                _gate_sample_scope(f, blind, n_read)
    return [f for f in findings if not f.get("_gated")]


# Checks whose verdict rests on matching English phrases. The value is the set of languages whose
# vocabulary the code actually carries; anything outside it is a guess, not a reading. Address, phone,
# email, dates and structured data are language-neutral and are deliberately absent from this table.
LANG_DEPENDENT = {
    "fx.facts.key_fact_missing": frozenset(["en"]),
    "fx.content.faq_absent": frozenset(["en"]),
    "ef.corroboration.press_page_missing": frozenset(["en"]),
    "en.hero.value_prop_unclear": frozenset(["en"]),
    "en.trust.signals_missing": frozenset(["en"]),
    "en.cta.missing": CTA_LANGS_SUPPORTED,
}


def sample_language(sample):
    """The language the sampled pages are actually written in, as a bare subtag, or None if unclear.

    The declared lang attribute is the stated answer and the word counts are the observed one. Real sites
    get this wrong often enough to matter -- a page can keep its template's lang attribute while its words are in another language
    -- so where the text disagrees with the attribute, the text wins: it is what an assistant reading the
    page would see. Majority across sampled pages, so one stray consent page cannot flip a site.
    """
    declared, detected = [], []
    for pg in sample.get("pages") or []:
        summary = pg.get("summary") or {}
        raw = (summary.get("lang") or "").strip().lower()
        if raw:
            declared.append(raw.split("-")[0])
        if summary.get("lang_detected"):
            detected.append(summary["lang_detected"])
    for votes in (detected, declared):
        if votes:
            return collections.Counter(votes).most_common(1)[0][0]
    return None


# Visitor-facing checks whose evidence lives in the page chrome: the header (navigation, search, the call to action)
# and the footer (terms, privacy, address, copyright year, the way on from a 404). When the served HTML leaves both
# for a script to fill in, these read an empty frame, not the page a visitor sees.
CHROME_DEPENDENT = ("en.nav.landmark_missing", "en.nav.site_search_missing", "en.nav.breadcrumbs_missing",
                    "en.nav.related_links_missing", "en.cta.missing", "en.trust.signals_missing",
                    "en.errors.unhelpful_404", "ef.freshness.no_visible_dates")


def apply_render_gate(findings, checks, sample):
    """Withdraw chrome-dependent failures when the home page's header or footer is served empty and filled by script.

    The signal is structural, not a guess: a <header> or <footer> that arrives with no link and almost no text, no
    <nav> anywhere in the served HTML, and at least one external script. adobe.com was told it had no navigation,
    no search and no privacy link because its header and footer are assembled in the browser. The checks get no
    verdict (reason chrome_rendered_by_javascript) and the limitations say what a non-JavaScript reader misses.
    Returns the withdrawn check ids.
    """
    home = next((p for p in sample.get("pages") or [] if p.get("role") == "home"), None)
    summ = (home or {}).get("summary") or {}
    if not (summ.get("empty_chrome") and not summ.get("nav_count") and (summ.get("external_scripts") or 0) > 0):
        return []
    gated = []
    for f in findings:
        if f.get("check_id") in CHROME_DEPENDENT and f.get("status") == "fail":
            _gate_not_evaluated(f, checks, "chrome_rendered_by_javascript")
            gated.append(f["check_id"])
    findings[:] = [f for f in findings if not f.get("_gated")]
    return gated


def apply_language_gate(findings, checks, sample):
    """Scope English-vocabulary claims to the language the audit can actually read. Mutates in place.

    A page that says lang="de" and whose buttons read "Jetzt spenden" has a call to action. Searching it
    with an English word list and reporting "no call to action" is not a weak finding, it is a false one.
    Where no vocabulary exists for the declared language the finding survives as a low-confidence signal
    with the reason stated, rather than being asserted at full strength or dropped silently.

    Returns the language that was gated on, or None.
    """
    lang = sample_language(sample)
    if not lang or lang == "en":
        return None
    gated = []
    for f in findings:
        supported = LANG_DEPENDENT.get(f.get("check_id"))
        if supported is None or f.get("status") != "fail" or lang in supported:
            continue
        f["confidence"] = "low"
        if f.get("severity") in ("critical", "high"):
            f["severity"] = "medium"
        _resync_action(f)
        f["language_scope"] = lang
        note = (" Pages declare lang=\"%s\"; the phrases this check searches for are English, so the site may "
                "state this in its own language where the audit did not look." % lang)
        f["evidence"] = _append_note(f.get("evidence", ""), note)
        gated.append(f["check_id"])
    return lang


# ---------------------------------------------------------------- ordering and tags
def sort_findings(findings):
    """report_schema.md section 4 rule 3, stable."""
    return sorted(findings, key=lambda f: (_sev_index(f.get("severity", "info")),
                                           ("high", "medium", "low").index(f.get("confidence", "low"))
                                           if f.get("confidence") in ("high", "medium", "low") else 3,
                                           -len(f.get("affected_pages") or []),
                                           f.get("check_id", "")))


def add_derived_tags(f):
    """coverage_map.md section 7. Probes never set these."""
    cid = f["check_id"]
    stage = f.get("mechanism")
    f["round2_mode"] = STAGE_MODE.get(stage)
    f["handout_concepts"] = list(STAGE_CONCEPTS.get(stage, []))
    f["pipeline_stage"] = STAGE_PIPELINE.get(stage)
    if cid.startswith("or.simulation."):
        f["handout_concepts"] = ["B"]
        f["pipeline_stage"] = "selection"
        f["round2_mode"] = "invisible"
    elif cid.startswith("or.run."):
        f["handout_concepts"] = []
        f["pipeline_stage"] = None
        f["round2_mode"] = None
    technical = cid.startswith(("cr.", "or.run.")) or (
        cid.startswith("en.") and not any(cid.startswith(p) or cid == p for p in CONTENT_EN))
    f["opportunity_type"] = "technical" if technical else "content"
    return f


def is_quick_win(f):
    """severity_confidence_rubric.md section 5."""
    return (f.get("severity") in ("critical", "high", "medium") and f.get("effort") == "low"
            and f.get("confidence") != "low" and f.get("status") == "fail")


def start_with(findings, quick_wins):
    """report_schema.md section 3b: the one finding to act on first, or None when nothing is above info.

    The first quick win when there is one. Otherwise the finding above `info` with the highest
    suggested_action.priority (priority already folds severity and confidence: a certain medium outranks a
    guessed high), then the lowest effort, then the highest confidence, then rank. The quick-win rule stays
    strict; this is what the report says when that rule leaves the reader with defects and no first move.
    """
    if quick_wins:
        return quick_wins[0]
    prio = {"high": 0, "medium": 1, "low": 2}
    effort = {"low": 0, "medium": 1, "high": 2}
    conf = {"high": 0, "medium": 1, "low": 2}
    cands = [f for f in findings if f.get("severity") != "info" and f.get("status") == "fail"]
    if not cands:
        return None
    best = min(cands, key=lambda f: (prio.get((f.get("suggested_action") or {}).get("priority"), 3),
                                     effort.get(f.get("effort"), 3), conf.get(f.get("confidence"), 3),
                                     f.get("rank") or 0))
    return best.get("id")


def build_headline(findings, pages_sampled, checks, probe_errors, start_id):
    """One deterministic sentence for the reader who opens nothing else: what, on how much, where to begin."""
    n_read = len([p for p in pages_sampled if p.get("status") == 200 and not p.get("challenge")])
    pages = "%d page%s read" % (n_read, "" if n_read == 1 else "s")
    counts = collections.Counter(f.get("severity") for f in findings)

    def phrase(*levels):
        return " and ".join("%d %s" % (counts[l], l) for l in levels if counts[l])

    if counts["critical"] or counts["high"]:
        n = counts["critical"] + counts["high"]
        head = "%s finding%s on the %s." % (phrase("critical", "high"), "" if n == 1 else "s", pages)
    elif counts["medium"] or counts["low"]:
        head = "No critical or high findings on the %s; %s." % (pages, phrase("medium", "low"))
    else:
        head = "No defects on the %s." % pages
    by_id = {f.get("id"): f for f in findings}
    if start_id in by_id:
        head += " Start with %s: %s." % (start_id, (by_id[start_id].get("title") or "").rstrip("."))
    gated = [cid for cid, c in checks.items() if c.get("reason") in GATE_REASONS]
    if gated:
        head += (" %d check%s had no verdict because parts of the site were not reached; see Coverage and limitations."
                 % (len(gated), "" if len(gated) == 1 else "s"))
    if probe_errors:
        head = "The run was incomplete: %d probe%s did not finish. %s" % (
            len(probe_errors), "" if len(probe_errors) == 1 else "s", head)
    return head


# ---------------------------------------------------------------- AI-answer simulation
def _fact(facts, fid):
    return ((facts or {}).get("facts") or {}).get(fid) or {}


def build_simulation(facts, category, site_host, facts_rel):
    """Deterministic pre-fill: questions from site_categories.md section 6, `answerable` and
    `missing_facts` computed from the facts file alone. The agent writes `answer_from_facts`."""
    brand = ((facts or {}).get("brand_name") or {}).get("value") or site_host or "this site"
    audience = AUDIENCE_PHRASE.get(category, AUDIENCE_PHRASE["unknown"])
    rows = list(SIMULATION_QUESTIONS.get(category) or SIMULATION_QUESTIONS["unknown"])
    rows = rows + [("Is {brand} a good fit for %s?" % audience, [AUDIENCE_FACT.get(category, "what_it_does")], False),
                   ("What sets {brand} apart from alternatives?", ["differentiator"], True)]
    questions = []
    for i, (template, fact_ids, informational) in enumerate(rows, start=1):
        present, missing = [], []
        for fid in fact_ids:
            (present if _fact(facts, fid).get("status") == "present" else missing).append(fid)
        q = {"id": "q%d" % i, "question": template.format(brand=brand), "answerable": not missing,
             "answer_from_facts": None, "facts_used": present, "missing_facts": missing}
        if informational:
            q["informational"] = True
        questions.append(q)
    sim = {"basis": "extracted_facts_only", "facts_file": facts_rel, "brand": brand,
           "questions": questions, "attribution_note": None}
    if facts is None:
        sim["note"] = "No extracted-facts file was available, so no question could be answered."
    return sim


# ---------------------------------------------------------------- proactive recommendations
def _seen_jsonld_types(facts, sample):
    types = set()
    for p in (facts or {}).get("pages_used") or []:
        types |= set(p.get("jsonld_types") or [])
    for p in sample.get("pages") or []:
        types |= set(((p.get("summary") or {}).get("jsonld_types")) or [])
    return types


def build_recommendations(category, facts, checks, findings, sample):
    """Opportunities, not restated findings: every candidate is dropped when a check it relates to
    already produced a finding. Chosen by category and by what actually passed."""
    failed = {f["check_id"] for f in findings if f.get("severity") != "info"}
    status = {cid: c["status"] for cid, c in checks.items()}
    types = _seen_jsonld_types(facts, sample)
    facts_map = (facts or {}).get("facts") or {}
    has_jsonld = status.get("fx.jsonld.missing") == "pass"
    out = []

    def rec(title, rationale, mechanism, effort, priority, blocked_by=()):
        if any(cid in failed for cid in blocked_by):
            return
        out.append({"title": title, "rationale": rationale, "mechanism": mechanism,
                    "effort": effort, "priority": priority})

    if status.get("fx.content.faq_absent") == "pass" and "FAQPage" not in types:
        rec("Mark the existing questions up as FAQPage structured data",
            "The site already answers questions in prose. FAQPage JSON-LD makes each question and answer a "
            "self-contained pair a machine can quote without guessing where the answer ends.",
            "extract", "low", "medium", ("fx.jsonld.missing", "fx.jsonld.malformed"))
    if facts_map and _fact(facts, "differentiator").get("status") != "present":
        rec("State in one sentence what sets this brand apart",
            "Assistants fan a query out into comparison questions. Nothing on the sampled pages claims a "
            "difference, so a comparison answer has nothing of this site's own wording to quote. This is an "
            "opportunity, not a defect: it is never reported as a finding.",
            "extract", "low", "medium")
    diff_fact = _fact(facts, "differentiator")
    diff_val = diff_fact.get("value") or ""
    if diff_fact.get("status") == "present" and not re.search(r"\d", diff_val):
        rec("State at least one concrete number in the site's own words",
            "Of the content genres measured for how much they shape a generated answer once a page is already "
            "cited, numbers and statistics carry the largest independent effect (+61.55%), ahead of definitions "
            "and comparisons. The site's own stated differentiator has no number in it, so there is nothing "
            "concrete here for an assistant to quote back.",
            "extract", "low", "medium")
    audience_fact = AUDIENCE_FACT.get(category, "what_it_does")
    if facts_map and _fact(facts, "audience").get("status") != "present":
        rec("Name the audience explicitly on the home page",
            "An explicit \"built for …\" line is what lets an assistant match this brand to the person asking, "
            "and it is the only site-side lever for the personalisation concept the audit cannot measure.",
            "extract", "low", "medium", ("fx.facts.key_fact_missing",) if audience_fact else ())
    recs = ((facts or {}).get("jsonld_recommendations") or [])[:3]
    if has_jsonld and recs:
        detail = "; ".join("%s: %s" % (r.get("type"), ", ".join((r.get("missing_recommended") or [])[:4])) for r in recs)
        rec("Add the recommended properties to the existing structured data",
            "The structured data present is valid but thin. Missing recommended properties (%s) are the ones "
            "assistants use to distinguish one entity from another." % detail,
            "extract", "low", "medium", ("fx.jsonld.missing", "fx.jsonld.malformed", "fx.jsonld.required_props_missing"))
    if category == "ecommerce" and has_jsonld and "Product" not in types:
        rec("Add Product and Offer structured data to product pages",
            "Price and availability stated only in the page layout have to be inferred. As Offer properties they "
            "are unambiguous, which is what a shopping question needs.",
            "extract", "medium", "medium", ("fx.jsonld.missing",))
    if category == "local_business":
        if has_jsonld and not (types & {"LocalBusiness", "Restaurant", "Store", "ProfessionalService"}):
            rec("Add LocalBusiness structured data with address, telephone and opening hours",
                "A local answer depends on machine-readable location and hours. Visible text is a good start; the "
                "structured version removes the parsing guess.",
                "entity", "low", "high", ("fx.jsonld.missing", "ef.entity.nap_missing_plain_text"))
        if _fact(facts, "opening_hours").get("status") == "present" and \
                "jsonld" not in (_fact(facts, "opening_hours").get("source") or ""):
            rec("Repeat the opening hours as openingHoursSpecification",
                "The hours are on the page as text. Restating them in structured data is the difference between an "
                "assistant reading them correctly and it declining to answer \"are they open now?\".",
                "entity", "low", "medium", ("fx.jsonld.missing",))
    if category in ("publisher_media", "corporate_enterprise") and status.get("ef.freshness.no_visible_dates") == "pass" \
            and not (types & {"Article", "BlogPosting", "NewsArticle"}):
        rec("Publish article dates and bylines as Article structured data",
            "Visible dates already tell a reader the page is current. Article JSON-LD with datePublished, "
            "dateModified and an author tells an assistant the same thing at answer time.",
            "freshness", "medium", "medium", ("fx.jsonld.missing",))
    if category == "saas_software" and _fact(facts, "pricing_or_trial").get("kind") == "sales_led":
        rec("Publish an indicative price or price range alongside the sales-led pricing",
            "Choosing not to publish prices is legitimate and is never reported as a defect here. A stated range "
            "still gives a cost question something to quote instead of a competitor's number.",
            "extract", "medium", "medium", ("fx.facts.key_fact_missing",))
    if status.get("ef.corroboration.press_page_missing") == "pass":
        rec("Publish datable milestones on the news surface others can cite",
            "The site already has a place to publish. Dated, factual announcements are what other sites quote, and "
            "repeated facts across independent sources are what make an entity trusted.",
            "corroboration", "medium", "low", ("ef.corroboration.press_page_missing",))
    if status.get("ef.entity.sameas_missing") == "pass" and status.get("ef.entity.sameas_no_authority") == "pass":
        rec("Keep the sameAs list current as new authoritative profiles appear",
            "The identity anchors already point somewhere authoritative. They are only useful while they resolve, so "
            "they are worth reviewing when a profile moves.",
            "entity", "low", "low")
    if category in ("publisher_media", "ecommerce", "saas_software", "corporate_enterprise"):
        rec("Make every deep page self-contained",
            "A visitor arriving from an AI answer lands on an interior page, not the home page. One line near the "
            "top saying what the site is, and a link to the parent section, keeps that visitor oriented.",
            "engagement", "medium", "medium", ("en.continuity.h1_title_mismatch", "en.nav.breadcrumbs_missing"))
    rec("Consider publishing a plain-text summary of the site at /llms.txt",
        "Not a confirmed ranking or citation signal for any major search or answer engine, so it is not graded "
        "anywhere in this audit. Early academic evidence on structured, agent-navigable pages suggests explicit "
        "machine-readable summaries can help agentic systems that autonomously fetch and follow links, distinct "
        "from ranking. It costs one file, and the exercise of writing it usually exposes facts the site never "
        "states plainly.",
        "extract", "low", "low")
    rank = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda r: (rank.get(r["priority"], 3), r["title"]))
    return out[:8]


# ---------------------------------------------------------------- coverage and limitations
LETTER_STAGES = {"A": ("access", "render", "extract"), "B": ("access", "extract", "freshness"),
                 "C": ("render", "extract"), "D": ("entity", "freshness", "corroboration")}
LETTER_BASE = {"A": "covered", "B": "covered", "C": "covered", "D": "partial",
               "E": "out_of_scope", "F": "out_of_scope"}


def build_coverage(checks, registry, sample):
    """coverage_map.md section 2 (stage status), section 1 (letters) and section 6 (the statement)."""
    stages = {}
    for stage in STAGE_ORDER:
        ran = degraded = seen = False
        for cid, c in checks.items():
            if cid not in registry or registry[cid]["stage"] != stage:
                continue
            seen = True
            if c["status"] in ("pass", "fail"):
                ran = True
            elif c.get("reason") != "not_applicable_for_category":
                degraded = True
        stages[stage] = "not_evaluated" if not (seen and ran) else ("partial" if degraded else "evaluated")
    concepts = {}
    for letter, base in LETTER_BASE.items():
        st = [stages[s] for s in LETTER_STAGES.get(letter, ())]
        if not st:
            concepts[letter] = base
        elif all(s == "not_evaluated" for s in st):
            concepts[letter] = "not_evaluated"
        elif any(s != "evaluated" for s in st):
            concepts[letter] = "partial"
        else:
            concepts[letter] = base
    not_evaluated, not_applicable = [], []
    for cid in sorted(checks):
        c = checks[cid]
        if c["status"] in ("not_evaluated", "inconclusive"):
            (not_applicable if c.get("reason") == "not_applicable_for_category" else not_evaluated).append(
                {"check_id": cid, "reason": c.get("reason") or c["status"]})
    return {"handout_concepts": concepts, "stages": stages, "not_evaluated": not_evaluated,
            "not_applicable_for_category": not_applicable,
            "statement": coverage_statement(concepts, stages, not_evaluated, sample)}


def coverage_statement(concepts, stages, not_evaluated, sample):
    """coverage_map.md section 6, filled from what actually happened."""
    full = [l for l in "ABCD" if concepts.get(l) == "covered"]
    part = [l for l in "ABCD" if concepts.get(l) == "partial"]
    none = [l for l in "ABCD" if concepts.get(l) == "not_evaluated"]
    reasons = "; ".join("%s: %s" % (e["check_id"].split(".")[-1], e["reason"]) for e in not_evaluated[:3])
    bits = []
    if full:
        bits.append("%s fully" % ", ".join(full))
    if part:
        bits.append("%s partially%s" % (", ".join(part), " (%s)" % reasons if reasons else ""))
    if none:
        bits.append("%s not evaluated" % ", ".join(none))
    ev = [s for s in STAGE_ORDER if stages.get(s) == "evaluated"]
    pa = [s for s in STAGE_ORDER if stages.get(s) == "partial"]
    ne = [s for s in STAGE_ORDER if stages.get(s) == "not_evaluated"]
    pages = sample.get("pages") or []
    missing = sample.get("missing_roles") or []
    out = ["Handout concepts covered: %s; E and F out of scope for a site audit, site-side levers reported."
           % ("; ".join(bits) or "none")]
    out.append("Stages evaluated: %s%s%s." % (", ".join(ev) or "none",
                                              "; partial: " + ", ".join(pa) if pa else "",
                                              "; not evaluated: " + ", ".join(ne) if ne else ""))
    out.append("Pages sampled: %d (%s)%s." % (len(pages), ", ".join(p.get("role") or "?" for p in pages) or "none",
                                              "; no page found for: " + ", ".join(missing) if missing else ""))
    out.append("Requests made: %s." % sample.get("requests_made", "unknown"))
    out.append("This audit reads what a non-JavaScript fetcher receives; it does not query live assistants "
               "or execute scripts.")
    return " ".join(out)


def non_coverage_lines():
    """The 'Not covered' column of coverage_map.md section 5, read from the file so the two cannot drift."""
    lines = []
    try:
        text = open(COVERAGE_MAP_MD, encoding="utf-8").read()
    except OSError:
        return lines
    section = text.split("\n## 5.")[-1].split("\n## 6.")[0]
    for row in re.findall(r"^\|(.+)\|\s*$", section, re.M):
        cells = [c.strip() for c in row.split("|")]
        if len(cells) < 4 or cells[0].startswith("---") or cells[0] == "Not covered":
            continue
        lines.append("Not covered: %s. %s" % (cells[0], cells[3]))
    return lines


def language_edition(page):
    """The language edition a redirect sent the home URL to ("en" for lemonde.fr -> /en/), or None."""
    if not page:
        return None
    return _language_edition(page.get("url"), page.get("final_url"))


def build_limitations(sample, probes, checks, gated_lang=None, category=None, chrome_gated=None):
    """report_schema.md section 3b: the boilerplate that applies, then section 5 non-coverage."""
    pages = sample.get("pages") or []
    out = ["This report reflects a single point-in-time fetch of %d sampled page%s; personalised or A/B-tested "
           "pages may differ between runs." % (len(pages), "" if len(pages) == 1 else "s")]
    roles = [p.get("role") for p in pages]
    if roles and set(roles) <= {"home"}:
        out.append("No content pages beyond the home page were discoverable, so every finding below is based on "
                   "the home page alone.")
    edition = language_edition(next((p for p in pages if p.get("role") == "home"), None))
    if edition:
        home = next(p for p in pages if p.get("role") == "home")
        out.append("The home URL redirected to %s, the site's '%s' language edition, although the audit asked for no "
                   "particular language. Every finding describes that edition, which may not be the one most of the "
                   "site's own audience reads." % (home.get("final_url"), edition))
    if chrome_gated:
        out.append("The home page's header and footer are empty in the HTML served without JavaScript and are filled in "
                   "by scripts, so %d visitor-facing check%s had no verdict (%s): a person with a browser sees what the "
                   "scripts add. An assistant or crawler that does not run JavaScript sees none of it."
                   % (len(chrome_gated), "" if len(chrome_gated) == 1 else "s", ", ".join(chrome_gated)))
    category = category or (sample.get("site_category") or {}).get("value") or "unknown"
    by_role = sorted(cid for cid, c in checks.items() if c.get("reason") == "role_page_not_sampled")
    if by_role:
        unreached = [r for r in (sample.get("missing_roles") or []) if r in key_pages(category)]
        out.append("Not checked, because the %s not reached from the home page's links or the sitemap: %s. "
                   "These are not findings that the site lacks them; a run that reaches those pages will grade them."
                   % (_role_phrase(unreached or sample.get("missing_roles") or ["role"]), ", ".join(by_role)))
    by_nav = sorted(cid for cid, c in checks.items() if c.get("reason") == "navigation_not_readable")
    if by_nav:
        found = 5 - len(sample.get("missing_roles") or [])
        out.append("The home page exposed %s internal link%s and led to %d of 5 role pages for a non-JavaScript "
                   "fetcher, so the site's navigation could not be read and %s has no verdict."
                   % (sample.get("internal_links_seen", "few"), "" if sample.get("internal_links_seen") == 1 else "s",
                      max(found, 0), ", ".join(by_nav)))
    rate_limited = [p for p in pages if (p.get("fetch") or {}).get("status") == 429]
    if rate_limited:
        out.append("%d page%s skipped: rate limited (429)." % (len(rate_limited), "" if len(rate_limited) == 1 else "s"))
    challenged = [p for p in pages if (p.get("fetch") or {}).get("challenge")]
    if challenged:
        out.append("Challenge page served on %d page%s: those checks are inconclusive." % (
            len(challenged), "" if len(challenged) == 1 else "s"))
    for cid in ("ef.entity.wikidata_unavailable", "ef.corroboration.offsite_spotcheck"):
        c = checks.get(cid)
        if c and c["status"] in ("not_evaluated", "inconclusive") and c.get("reason") != "bounded_spotcheck":
            label = "Entity lookup" if cid.startswith("ef.entity") else "Off-site mention spot-check"
            out.append("%s skipped: %s." % (label, (c.get("reason") or "unknown").replace("_", " ")))
    for probe in probes:
        if probe.get("error"):
            out.append("%s reported an internal error and its checks may be incomplete: %s"
                       % (probe.get("probe"), probe["error"]))
    if gated_lang:
        covered = sorted(c for c, langs in LANG_DEPENDENT.items() if gated_lang in langs)
        out.append("The sampled pages declare lang=\"%s\". Address, phone, email, dates and structured data are read "
                   "the same way in any language, but the phrase lists behind %s are English%s. Findings from those "
                   "checks are reported at low confidence: the site may state the thing in its own words where this "
                   "audit did not look."
                   % (gated_lang, ", ".join(sorted(set(LANG_DEPENDENT) - set(covered))),
                      " (the call-to-action check does cover %s)" % gated_lang if covered else ""))
    out.append("This audit reads served HTML only and does not execute JavaScript or query live assistants.")
    out.extend(non_coverage_lines())
    return out


# ---------------------------------------------------------------- orchestrator-level findings
def orchestrator_findings(site, category, pages_examined, simulation, probes, load_errors, registry, facts=None):
    """or.simulation.question_unanswerable and or.run.probe_error, built through the shared builder."""
    out = ProbeOutput("audit-orchestrator", site, category, pages_examined, registry=registry)
    unanswerable = [q for q in simulation["questions"] if not q["answerable"] and not q.get("informational")]
    readable = bool((facts or {}).get("pages_used"))
    if unanswerable and not readable:
        # nothing was read, so nothing about the site's text can be concluded: not_evaluated, and say why
        reasons = sorted({e.get("reason") for e in (facts or {}).get("pages_excluded") or [] if e.get("reason")})
        reason = "no_readable_pages" if facts is not None else "facts_file_missing"
        out.not_evaluated(
            "or.simulation.question_unanswerable", reason=reason, emit_finding=True,
            title="No question could be simulated: no sampled page was readable",
            evidence="The simulation reads only the extracted-facts file, and no page reached it (%s), so whether the site "
                     "states these facts is unknown, not absent." % (", ".join(reasons) if reasons else reason),
            evidence_items=[evidence_item("site", "computed", "pages_used=0; excluded=%s" % (",".join(reasons) or "none"))],
            why="An unanswerable question here says nothing about the site's content: the audit could not read it. The "
                "access findings above are the reason, and the fix.",
            action="Resolve the access finding first, then re-run the audit so the facts file has pages to read.",
            detail="For a challenge page, allow the audit's user agent through; for an unreachable site, check the URL.")
    elif unanswerable:
        missing = sorted({m for q in unanswerable for m in q["missing_facts"]})
        out.policy_note(
            "or.simulation.question_unanswerable",
            title="%d of the questions a buyer would ask cannot be answered from this site's text"
                  % len(unanswerable),
            evidence="Simulated from %s only: %d of %d questions unanswerable; facts absent: %s."
                     % (simulation["facts_file"] or "the extracted-facts file", len(unanswerable),
                        len([q for q in simulation["questions"] if not q.get("informational")]), ", ".join(missing)),
            evidence_items=[evidence_item("site", "computed", "question=%s; missing_facts=%s"
                                          % (q["question"], ",".join(q["missing_facts"]) or "none"))
                            for q in unanswerable],
            why="An assistant answering at fetch time has only what the pages say. Where the site is silent it "
                "either declines to answer or uses someone else's page, and the brand is invisible for that question.",
            action="State each missing fact in plain sentence text on the page a visitor would look for it.",
            detail="The specific defect is already reported by the fact-extractability findings; this is the "
                   "reader-facing consequence. Re-run the audit afterwards: the simulation is deterministic.")
    else:
        out.check("or.simulation.question_unanswerable", "pass")
    broken = [p.get("probe") or "unknown" for p in probes if p.get("error")] + list(load_errors)
    if broken:
        out.policy_note(
            "or.run.probe_error",
            title="%d probe%s did not complete cleanly" % (len(broken), "" if len(broken) == 1 else "s"),
            evidence="Incomplete: %s. The affected checks are missing from this report rather than passing."
                     % "; ".join(str(b)[:80] for b in broken),
            evidence_items=[evidence_item("site", "computed", str(b)[:280]) for b in broken],
            why="A check that did not run is not a check that passed. This note exists so an incomplete run is "
                "never read as a clean one.",
            action="Re-run the audit; if the same probe fails again, run it alone with --workdir to see its error.",
            detail="Every probe is guarded, so one failure does not stop the others. The coverage section lists "
                   "which checks have no verdict.")
    else:
        out.check("or.run.probe_error", "pass")
    return out


# ---------------------------------------------------------------- compose
def compose(workdir, wall_clock=None, input_url=None, category_override=None):
    registry = Registry()
    data = load_workdir(workdir)
    sample, probes, facts = data["sample"], data["probes"], data["facts"]
    site_url = sample.get("site") or input_url or ""
    # an explicit override is what the probes were told to grade against, so it is what the report states
    category = category_override or (sample.get("site_category") or {}).get("value") or "unknown"
    pages = sample.get("pages") or []
    pages_examined = [(p.get("fetch") or {}).get("final_url") or p.get("url") for p in pages]

    findings = []
    for probe in probes:
        for f in probe.get("findings", []):
            f = json.loads(json.dumps(f))
            f["source_skill"] = probe.get("probe") or "unknown"
            f["_max_severity"] = registry[f["check_id"]]["max_severity"] if f.get("check_id") in registry else "info"
            findings.append(f)

    facts_rel = None
    for probe in probes:
        facts_rel = (probe.get("artifacts") or {}).get("extracted_facts") or facts_rel
    simulation = build_simulation(facts, category, _host(site_url), facts_rel or "work/extracted_facts.json")

    orch = orchestrator_findings(site_url, category, pages_examined, simulation, probes, data["load_errors"], registry, facts=facts)
    for f in orch.findings:
        f = json.loads(json.dumps(f))
        f["source_skill"] = "audit-orchestrator"
        f["_max_severity"] = "info"
        findings.append(f)

    checks = collect_checks(probes, registry)
    for c in orch.checks:
        checks[c["check_id"]] = {"check_id": c["check_id"], "status": c["status"], "reason": c.get("reason"),
                                 "pages": c.get("pages") or [], "source_skill": "audit-orchestrator"}
    # scope absence claims to what was actually read, before ordering assigns ids and ranks
    findings = apply_absence_gate(findings, checks, sample, category, facts)
    gated_lang = apply_language_gate(findings, checks, sample)
    chrome_gated = apply_render_gate(findings, checks, sample)

    kept, folded = dedupe(findings, sample, category)
    kept = sort_findings(kept)
    for i, f in enumerate(kept, start=1):
        f["id"] = "F-%03d" % i
        f["rank"] = i
        add_derived_tags(f)
        f["quick_win"] = is_quick_win(f)
    # an unanswerable question points at the finding that explains it, so the agent never looks up an id
    explain = next((f["id"] for f in kept if f["check_id"] == "fx.facts.key_fact_missing"), None) or \
        next((f["id"] for f in kept if f["check_id"] == "or.simulation.question_unanswerable"), None)
    for q in simulation["questions"]:
        if not q["answerable"] and not q.get("informational") and explain:
            q["see_finding"] = explain
    by_key = {f["dedupe_key"]: f for f in kept}
    for f in folded:
        add_derived_tags(f)
        primary = by_key.get(f.get("_merged_into_key"))
        f["merged_into"] = primary["id"] if primary else None
    for f in kept + folded:
        for k in ("_suppressed", "_merged_into_key", "_notes", "_max_severity"):
            f.pop(k, None)

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in kept:
        counts[f.get("severity", "info")] = counts.get(f.get("severity", "info"), 0) + 1
    status_counts = {s: sum(1 for c in checks.values() if c["status"] == s)
                     for s in ("pass", "fail", "inconclusive", "not_evaluated")}
    passed = [{"check_id": cid, "title": POSITIVE_TITLES.get(cid, registry[cid]["fails_when"][:80] if cid in registry else cid),
               "source_skill": checks[cid]["source_skill"], "stage": registry[cid]["stage"] if cid in registry else None}
              for cid in sorted(checks) if checks[cid]["status"] == "pass"]

    pages_sampled = [{"role": p.get("role"), "url": (p.get("fetch") or {}).get("final_url") or p.get("url"),
                      "status": (p.get("fetch") or {}).get("status"),
                      "snapshot": (p.get("fetch") or {}).get("body_path"),
                      "challenge": bool((p.get("fetch") or {}).get("challenge"))} for p in pages]
    probe_errors = ([{"probe": p.get("probe"), "error": p["error"]} for p in probes if p.get("error")]
                    + [{"probe": None, "error": e} for e in data["load_errors"]])
    quick_wins = [f["id"] for f in kept if f["quick_win"]]
    start = start_with(kept, quick_wins)

    report = {
        "site": _host(site_url) or site_url or "unknown",
        "site_url": site_url,
        "audited_at": _now(),
        "tool": {"name": TOOL_NAME, "version": __version__},
        "input_url": input_url or sample.get("input_url") or site_url,
        "site_category": {"value": category,
                          "confidence": "high" if category_override else (sample.get("site_category") or {}).get("confidence", "low"),
                          "signals": ["override:command_line"] if category_override
                                     else (sample.get("site_category") or {}).get("signals", [])},
        "pages_sampled": pages_sampled,
        "summary": dict({"total_findings": len(kept)}, **counts, **{
            "checks_run": len(checks), "checks_passed": status_counts["pass"], "checks_failed": status_counts["fail"],
            "checks_inconclusive": status_counts["inconclusive"], "checks_not_evaluated": status_counts["not_evaluated"],
            "headline": build_headline(kept, pages_sampled, checks, probe_errors, start), "start_with": start}),
        "findings": kept,
        "quick_wins": quick_wins,
        "passed_checks": passed,
        "coverage": build_coverage(checks, registry, sample),
        "proactive_recommendations": build_recommendations(category, facts, checks, kept, sample),
        "ai_answer_simulation": simulation,
        "narrative_summary": "",
        "limitations": build_limitations(sample, probes, checks, gated_lang, category, chrome_gated),
        "suppressed_findings": folded,
        "run": {"wall_clock_seconds": wall_clock, "requests_made": sample.get("requests_made"),
                "probe_errors": probe_errors},
    }
    return report


# ---------------------------------------------------------------- Markdown (report_schema.md section 6)
SEVERITY_LABEL = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low", "info": "Informational"}


def _fmt_pages(f, site_url):
    urls = f.get("affected_pages") or []
    if not urls:
        return "site-wide"
    short = [u[len(site_url):] or "/" if site_url and u.startswith(site_url) else u for u in urls[:4]]
    return ", ".join("`%s`" % s for s in short) + ("" if len(urls) <= 4 else " and %d more" % (len(urls) - 4))


def render_markdown(report):
    site_url = report.get("site_url") or ""
    s = report.get("summary") or {}
    L = ["# AI-readiness audit: %s" % report.get("site", "")]
    L.append("")
    L.append("%s · category **%s** (%s confidence) · audited %s · tool %s %s"
             % (site_url, (report.get("site_category") or {}).get("value", "unknown"),
                (report.get("site_category") or {}).get("confidence", "low"), report.get("audited_at", ""),
                (report.get("tool") or {}).get("name", ""), (report.get("tool") or {}).get("version", "")))
    L.append("")
    L.append("## Summary")
    L.append("")
    if s.get("headline"):
        L.append(s["headline"])
        L.append("")
    L.append("**%d finding%s** — %d critical, %d high, %d medium, %d low, %d informational."
             % (s.get("total_findings", 0), "" if s.get("total_findings") == 1 else "s", s.get("critical", 0),
                s.get("high", 0), s.get("medium", 0), s.get("low", 0), s.get("info", 0)))
    L.append("")
    L.append("%d checks run: %d passed, %d failed, %d inconclusive, %d not evaluated."
             % (s.get("checks_run", 0), s.get("checks_passed", 0), s.get("checks_failed", 0),
                s.get("checks_inconclusive", 0), s.get("checks_not_evaluated", 0)))
    if report.get("narrative_summary"):
        L += ["", "## What this means", "", report["narrative_summary"]]
    start = s.get("start_with")
    first = next((f for f in report.get("findings") or [] if f.get("id") == start), None) if start else None
    if report.get("quick_wins"):
        L += ["", "## Quick wins", "", "Low effort, real impact, high enough confidence to act on today.", ""]
        for f in report["findings"]:
            if f["id"] in report["quick_wins"]:
                L.append("- **%s** %s — %s" % (f["id"], f["title"], f["suggested_action"]["summary"]))
    elif first is not None:
        # defects but no qualifying quick win: the section still tells the reader where to begin, never vanishes
        L += ["", "## Quick wins", "",
              "None qualify: a quick win needs medium-or-higher severity, low effort and at least medium confidence "
              "(severity_confidence_rubric.md section 5), and no finding here meets all three. Start instead with "
              "**%s** %s — %s (%s effort, %s confidence)."
              % (first["id"], first["title"], ((first.get("suggested_action") or {}).get("summary") or "").rstrip("."),
                 first.get("effort"), first.get("confidence"))]
    if report.get("findings"):
        L += ["", "## Findings", ""]
        for sev in SEVERITIES:
            group = [f for f in report["findings"] if f.get("severity") == sev]
            if not group:
                continue
            L += ["### %s (%d)" % (SEVERITY_LABEL[sev], len(group)), ""]
            for f in group:
                L.append("#### %s %s" % (f["id"], f["title"]))
                L.append("")
                L.append("`%s` · severity **%s** · confidence %s · effort %s · %s · %s"
                         % (f["check_id"], f["severity"], f.get("confidence"), f.get("effort"),
                            f.get("mechanism") or "run", _fmt_pages(f, site_url)))
                L.append("")
                L.append(f.get("evidence", ""))
                L.append("")
                L.append("```")
                for it in (f.get("evidence_items") or [])[:6]:
                    L.append("%s%s: %s%s" % (it.get("kind", ""),
                                             " @ %s" % it["location"] if it.get("location") else "",
                                             it.get("value", ""), "  (%s)" % it["note"] if it.get("note") else ""))
                L.append("```")
                L.append("")
                L.append("*Why it matters.* %s" % f.get("why_it_matters", ""))
                L.append("")
                sa = f.get("suggested_action") or {}
                L.append("*Do this.* %s %s" % (sa.get("summary", ""), sa.get("detail", "")))
                L.append("")
                L.append("Priority **%s** · impact %s · effort %s%s"
                         % (sa.get("priority"), sa.get("impact"), sa.get("effort"),
                            " · quick win" if f.get("quick_win") else ""))
                if f.get("references"):
                    L.append("")
                    L.append("Reference: " + ", ".join(f["references"]))
                L.append("")
    if report.get("suppressed_findings"):
        L += ["## Folded into other findings", "",
              "Kept for transparency: each was observed, and each shares a root cause with the finding named.", ""]
        for f in report["suppressed_findings"]:
            L.append("- `%s` — folded into **%s**%s" % (f["check_id"], f.get("merged_into") or "—",
                                                        " (%s)" % f["title"] if f.get("title") else ""))
        L.append("")
    if report.get("passed_checks"):
        L += ["## What is working", "", "%d checks passed. These are the parts an assistant will not trip over."
              % len(report["passed_checks"]), ""]
        for stage in list(STAGE_ORDER) + [None]:
            group = [c for c in report["passed_checks"] if c.get("stage") == stage]
            if not group:
                continue
            L.append("**%s**" % (stage or "run"))
            L.append("")
            for c in group:
                L.append("- %s (`%s`)" % (c["title"], c["check_id"]))
            L.append("")
    sim = report.get("ai_answer_simulation") or {}
    if sim.get("questions"):
        L += ["## AI answer simulation", "",
              "What an assistant could answer using **only** the facts this site states in its own served HTML "
              "(`%s`). Nothing else was consulted." % sim.get("facts_file", ""), ""]
        for q in sim["questions"]:
            L.append("**%s**" % q["question"])
            L.append("")
            if q.get("answerable"):
                L.append(q.get("answer_from_facts") or "_Answerable from: %s._" % ", ".join(q.get("facts_used") or []))
            else:
                L.append("_Not answerable from the site's text. Absent: %s._%s"
                         % (", ".join(q.get("missing_facts") or []),
                            " Informational only." if q.get("informational") else ""))
            L.append("")
        if sim.get("attribution_note"):
            L += [sim["attribution_note"], ""]
        if sim.get("note"):
            L += ["_%s_" % sim["note"], ""]
    if report.get("proactive_recommendations"):
        L += ["## Proactive recommendations", "",
              "Opportunities, not defects: none of these is a restatement of a finding above.", ""]
        for r in report["proactive_recommendations"]:
            L.append("- **%s** (%s, %s effort, priority %s) — %s"
                     % (r["title"], r["mechanism"], r["effort"], r["priority"], r["rationale"]))
        L.append("")
    cov = report.get("coverage") or {}
    L += ["## Coverage and limitations", ""]
    if cov.get("statement"):
        L += [cov["statement"], ""]
    if cov.get("not_evaluated"):
        L.append("Checks with no verdict: " + ", ".join("`%s` (%s)" % (e["check_id"], e["reason"])
                                                        for e in cov["not_evaluated"]))
        L.append("")
    if cov.get("not_applicable_for_category"):
        L.append("Not applicable to %s: " % category_label((report.get("site_category") or {}).get("value", "unknown"))
                 + ", ".join("`%s`" % e["check_id"] for e in cov["not_applicable_for_category"]))
        L.append("")
    limits = report.get("limitations") or []
    for line in limits:
        if not line.startswith("Not covered: "):
            L.append("- %s" % line)
    gaps = [line[len("Not covered: "):].split(". ")[0].rstrip(".") for line in limits if line.startswith("Not covered: ")]
    if gaps:
        # one line in the report; the reason for each gap stays in report.json under limitations
        L.append("- Outside this audit's scope: %s. Each is explained in report.json under limitations." % "; ".join(gaps))
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description="Merge probe outputs into report.json and report.md.")
    ap.add_argument("--workdir", required=True, help="workdir holding sample.json and probes/*.json")
    ap.add_argument("--out", help="report JSON path (default <workdir>/report.json)")
    ap.add_argument("--md", help="report Markdown path (default <workdir>/report.md)")
    ap.add_argument("--render-only", action="store_true", help="re-render the Markdown from an existing report.json")
    ap.add_argument("--wall-clock-seconds", type=float, default=None)
    ap.add_argument("--input-url", help="the URL the user asked for, when it differs from the sampled origin")
    ap.add_argument("--category", help="state (and grade against) this category instead of the inferred one")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    out_path = args.out or os.path.join(args.workdir, "report.json")
    md_path = args.md or os.path.join(args.workdir, "report.md")
    try:
        if args.render_only:
            with open(out_path, encoding="utf-8") as f:
                report = json.load(f)
        else:
            report = compose(args.workdir, wall_clock=args.wall_clock_seconds, input_url=args.input_url,
                             category_override=args.category)
    except Exception as e:  # noqa: BLE001  -- the never-crash guarantee
        report = _fallback_report(args.workdir, "%s: %s" % (type(e).__name__, e))
    try:
        if not args.render_only:
            os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
        os.makedirs(os.path.dirname(os.path.abspath(md_path)) or ".", exist_ok=True)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(render_markdown(report))
    except OSError as e:
        print("could not write the report: %s" % e, file=sys.stderr)
        return 1
    if not args.quiet:
        print("%s (%d findings, %d suppressed)" % (out_path, len(report.get("findings") or []),
                                                   len(report.get("suppressed_findings") or [])))
        print(md_path)
    return 0


def _fallback_report(workdir, error, site_url=None, title=None, action=None):
    """A valid report whose only finding is the run error: an incomplete run is never read as a clean one.
    run_audit.py passes its own title when the site itself could not be reached."""
    reg = Registry()
    out = ProbeOutput("audit-orchestrator", site_url or workdir, "unknown", [], registry=reg)
    out.policy_note("or.run.probe_error", title=title or "The audit could not be composed",
                    evidence=("%s: %s" % ("the audit did not complete" if title else "compose failed", error))[:300],
                    evidence_items=[evidence_item("site", "computed", error[:280])],
                    why="Nothing about the site can be concluded from this run: the report is empty because the "
                        "tool failed, not because the site is clean.",
                    action=action or "Re-run the audit and check that the workdir holds sample.json and probes/*.json.",
                    detail="Each probe can also be run alone with --workdir to see its own error.")
    f = add_derived_tags(out.findings[0])
    f.update({"id": "F-001", "rank": 1, "source_skill": "audit-orchestrator", "quick_win": False})
    return {"site": _host(site_url or "") or "unknown", "site_url": site_url or "",
            "audited_at": _now(), "tool": {"name": TOOL_NAME, "version": __version__},
            "input_url": site_url or workdir, "site_category": {"value": "unknown", "confidence": "low", "signals": []},
            "pages_sampled": [],
            "summary": {"total_findings": 1, "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 1,
                        "checks_run": 1, "checks_passed": 0, "checks_failed": 1, "checks_inconclusive": 0,
                        "checks_not_evaluated": 0,
                        "headline": "The run was incomplete: 1 probe did not finish. Nothing was evaluated: %s." % str(error)[:160].rstrip("."),
                        "start_with": None},
            "findings": [f], "quick_wins": [], "passed_checks": [],
            "coverage": {"handout_concepts": {l: "not_evaluated" for l in "ABCD"},
                         "stages": {s: "not_evaluated" for s in STAGE_ORDER},
                         "not_evaluated": [], "not_applicable_for_category": [],
                         "statement": "The audit did not complete; nothing was evaluated."},
            "proactive_recommendations": [], "narrative_summary": "",
            "ai_answer_simulation": {"basis": "extracted_facts_only", "facts_file": None, "brand": "",
                                     "questions": [], "attribution_note": None,
                                     "note": "The run failed before any fact could be extracted."},
            "limitations": ["The audit did not complete: %s" % error], "suppressed_findings": [],
            "run": {"wall_clock_seconds": None, "requests_made": None,
                    "probe_errors": [{"probe": None, "error": error}]}}


if __name__ == "__main__":
    raise SystemExit(main())
