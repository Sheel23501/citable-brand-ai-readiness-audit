#!/usr/bin/env python3
"""fact-extractability-audit probe: can a machine pick out the specific facts someone would ask about?

    python3 facts_probe.py --workdir audit-example            # orchestrator mode: reads sample.json + snapshots
    python3 facts_probe.py --url https://example.com          # standalone: samples the site first
    python3 facts_probe.py --workdir audit-example --out audit-example/probes/fact-extractability-audit.json

Emits the probe output object (report_schema.md section 1) with every `fx.*` check, and writes
<workdir>/work/extracted_facts.json, the file the orchestrator's AI-answer simulation reads.
Standard library only. Never raises; internal errors are reported in the `error` field.
"""
import datetime as _dt
import json
import os
import re
import sys
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "audit-orchestrator", "scripts")))
from auditlib.cli import probe_main  # noqa: E402
from auditlib.categories import KEY_FACTS, AUDIENCE_FACT, SEVERITY_OVERRIDES, category_label  # noqa: E402
from auditlib.findings import ProbeOutput, evidence_item  # noqa: E402
from auditlib.render import render_state  # noqa: E402
from auditlib import extract as X  # noqa: E402

PROBE = "fact-extractability-audit"
FACTS_REL = "work/extracted_facts.json"
GENERIC_TITLES = X.GENERIC_TITLES  # shared with the engagement probe's continuity check
PRESENT, PARTIAL, ABSENT = "present", "partial", "absent"
IMAGE_FACT_WORDS = {
    "pricing": re.compile(r"\b(price|prices|pricing|plans?|rates?|fees?|tariffs?|costs?|packages?)\b", re.I),
    "hours": re.compile(r"\b(hours|opening|open(ing)?\s+times|schedule|timetable)\b", re.I),
    "address": re.compile(r"\b(address|location|directions|find\s+us|where\s+we\s+are|map)\b", re.I),
    "menu": re.compile(r"\b(menu|menus|specials|dishes|wine\s+list)\b", re.I),
    "specs": re.compile(r"\b(specs?|specifications?|datasheet|dimensions|comparison|compare|features?\s+table)\b", re.I),
}
IMAGE_FACT_TO_FACT_IDS = {"pricing": ("pricing_or_trial", "sample_product_price"), "hours": ("opening_hours",), "address": ("address", "location", "location_or_service_area", "headquarters", "location_or_contact"),
                          "menu": ("services_or_menu",), "specs": ()}
# Where each fact is expected to live. An image on a blog post is a photo, whatever its caption says.
IMAGE_FACT_PAGES = {"pricing": ("pricing", "product", "home"), "hours": ("contact", "home", "about", "product"),
                    "address": ("contact", "about", "home"), "menu": ("product", "home"), "specs": ()}
IMAGE_ALT_MAX_WORDS = 5       # a label ("Opening hours", "Price list 2026"), not a caption
IMAGE_HEADING_MAX_WORDS = 4   # a heading that names the fact, not a sentence that happens to contain the word


def image_fact_signals(alt, fname, heading, fact):
    """Which of alt / filename / heading name `fact` as a label. Captions and sentences never count: the words that
    mark a fact ("plans", "location", "hours") are ordinary words inside prose."""
    rx = IMAGE_FACT_WORDS[fact]
    signals = []
    if alt and len(alt.split()) <= IMAGE_ALT_MAX_WORDS and rx.search(alt):
        signals.append("alt")
    if fname and rx.search(fname):
        signals.append("filename")
    if heading and len(heading.split()) <= IMAGE_HEADING_MAX_WORDS and rx.search(heading):
        signals.append("heading")
    return signals
REFS = {
    "jsonld": "https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data",
    "sd_general": "https://developers.google.com/search/docs/appearance/structured-data/sd-policies",
    "og": "https://ogp.me/",
    "title": "https://developers.google.com/search/docs/appearance/title-link",
    "snippet": "https://developers.google.com/search/docs/appearance/snippet",
    "alt": "https://developers.google.com/search/docs/appearance/google-images",
    "faq": "https://schema.org/FAQPage",
    "absorption": "https://arxiv.org/abs/2604.25707",
}


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- fact resolution
def fact_pricing_or_trial(pages):
    has_pricing_page = any(p.role == "pricing" for p in pages)
    f = X.find_price(pages)
    if f:
        return PRESENT, "price", f
    f = X.find_sales_led(pages, roles=("pricing", "product", "home") if has_pricing_page else None)
    if f:
        return PRESENT, "sales_led", f
    f = X.find_free_tier(pages)
    if f:
        return PRESENT, "free_tier", f
    f = X.find_free_trial(pages)
    if f:
        return PARTIAL, "trial_only", f
    return ABSENT, None, None


def _simple(finder, kind):
    def fn(pages):
        f = finder(pages)
        return (PRESENT, kind, f) if f else (ABSENT, None, None)
    return fn


def fact_sample_product_price(pages):
    f = X.find_price(pages, prefer=("product", "pricing", "home"))
    return (PRESENT, "price", f) if f else (ABSENT, None, None)


def fact_contact_or_signup(pages):
    f = X.find_contact(pages)
    if f:
        return PRESENT, "contact", f
    f = X.find_signup(pages)
    return (PRESENT, "signup", f) if f else (ABSENT, None, None)


def fact_contact_or_press(pages):
    f = X.find_contact(pages)
    if f:
        return PRESENT, "contact", f
    f = X.find_press_contact(pages)
    return (PRESENT, "press", f) if f else (ABSENT, None, None)


def fact_contact_or_profile(pages):
    f = X.find_contact(pages)
    if f:
        return PRESENT, "contact", f
    f = X.find_profile_links(pages)
    return (PRESENT, "profile_link", f) if f else (ABSENT, None, None)


def fact_location(pages):
    f = X.find_address(pages)
    if f:
        return PRESENT, "address", f
    f = X.find_location_phrase(pages)
    return (PRESENT, "location_phrase", f) if f else (ABSENT, None, None)


def fact_location_or_contact(pages):
    st, kind, f = fact_location(pages)
    if st == PRESENT:
        return st, kind, f
    f = X.find_contact(pages)
    return (PRESENT, "contact", f) if f else (ABSENT, None, None)


def fact_offer_list(prefer):
    def fn(pages):
        f = X.find_offer_list(pages, prefer=prefer)
        return (PRESENT, "list", f) if f else (ABSENT, None, None)
    return fn


FACT_RESOLVERS = {
    "what_it_does": _simple(X.find_description, "description"),
    "what_company_does": _simple(X.find_description, "description"),
    "pricing_or_trial": fact_pricing_or_trial,
    "sample_product_price": fact_sample_product_price,
    "who_it_is_for": _simple(X.find_audience, "audience"),
    "who_it_serves": _simple(X.find_audience, "audience"),
    "contact_method": _simple(X.find_contact, "contact"),
    "contact_or_signup_method": fact_contact_or_signup,
    "contact_or_press_method": fact_contact_or_press,
    "contact_or_profile_link": fact_contact_or_profile,
    "address": _simple(X.find_address, "address"),
    "phone": _simple(X.find_phone, "phone"),
    "opening_hours": _simple(X.find_hours, "hours"),
    "services_or_menu": fact_offer_list(("product", "home", "contact")),
    "services_offered": fact_offer_list(("product", "home", "about")),
    "programs_or_services": fact_offer_list(("product", "home", "about")),
    "what_it_sells": fact_offer_list(("product", "home")),
    "topics_covered": fact_offer_list(("blog", "home")),
    "shipping_or_returns": _simple(X.find_shipping_returns, "policy"),
    "location_or_service_area": fact_location,
    "location": fact_location,
    "headquarters": fact_location,
    "location_or_contact": fact_location_or_contact,
    "publisher_identity": _simple(X.find_publisher_identity, "identity"),
    "recency_evidence": _simple(X.find_dates, "date"),
    "who": _simple(X.find_person, "person"),
    "what_they_do": _simple(X.find_role_statement, "role"),
    "mission": _simple(X.find_mission, "mission"),
    "how_to_participate": _simple(X.find_participation, "call_to_action"),
    "leadership_or_size": _simple(X.find_leadership_or_size, "leadership"),
    "audience": _simple(X.find_audience, "audience"),
    "differentiator": _simple(X.find_differentiator, "claim"),
}

FACT_ADVICE = {
    "what_it_does": "State in one plain sentence what the brand offers, in the home page's first paragraph and the meta description.",
    "what_company_does": "State in one plain sentence what the company does, on the home page and in the meta description.",
    "pricing_or_trial": "Publish prices as HTML text on the pricing page (or a plain 'pricing on request, contact sales' statement); a free-trial button alone does not tell anyone the cost.",
    "sample_product_price": "Show each product's price as text next to its name, and in Offer JSON-LD.",
    "who_it_is_for": "Name the audience in a sentence ('built for freelance designers and small studios').",
    "who_it_serves": "Name the clients you serve in a sentence on the home or services page.",
    "contact_method": "Put an email address or phone number as text (and a mailto:/tel: link) on the contact page.",
    "contact_or_signup_method": "Put a contact email/phone or a clear sign-up route as text on the home or contact page.",
    "contact_or_press_method": "Put a general or press contact email as text on the contact or newsroom page.",
    "contact_or_profile_link": "Add an email link or links to your professional profiles.",
    "address": "Write the full postal address as text on the contact page and in PostalAddress JSON-LD.",
    "phone": "Write the phone number as text with a tel: link on the contact page.",
    "opening_hours": "List opening hours as text (day ranges and times) and in openingHoursSpecification JSON-LD.",
    "services_or_menu": "List services or menu items as text headings or a list, not only as images or PDFs.",
    "services_offered": "List the services as text headings on a services page.",
    "programs_or_services": "List programs or services as text headings on a programs page.",
    "what_it_sells": "List product categories or products as text with names, and add Product JSON-LD.",
    "topics_covered": "Name the sections or topics you cover as text navigation or headings.",
    "shipping_or_returns": "Add a shipping and returns statement as text and link it from product pages.",
    "location_or_service_area": "State where you are based and the area you serve in a sentence.",
    "location": "State the location as text (city and country at minimum).",
    "headquarters": "State the headquarters location as text on the about page.",
    "location_or_contact": "Add a location line or a contact email/phone as text.",
    "publisher_identity": "Name the publishing organisation as text on the about page and in Organization JSON-LD.",
    "recency_evidence": "Show publication or update dates as visible text with <time datetime> markup.",
    "who": "Put your name as text in the heading and in Person JSON-LD.",
    "what_they_do": "State what you do in one sentence ('I am a freelance illustrator in Lisbon').",
    "mission": "State the mission in one plain sentence on the home and about pages.",
    "how_to_participate": "Add a clear text call to action (donate, apply, volunteer, join) with a link.",
    "leadership_or_size": "Name the leadership or state the company size as text on the about page.",
}


def resolve_facts(category, pages):
    required = KEY_FACTS.get(category, KEY_FACTS["unknown"])
    facts = {}
    for fid in required + ["audience", "differentiator"]:
        if fid in facts:
            continue
        resolver = FACT_RESOLVERS.get(fid)
        if resolver is None:
            facts[fid] = {"status": ABSENT, "kind": None, "value": None, "page": None, "source": None, "required": fid in required, "note": "no resolver"}
            continue
        try:
            st, kind, f = resolver(pages)
        except Exception as e:  # noqa: BLE001
            st, kind, f = ABSENT, None, None
            facts[fid] = {"status": ABSENT, "kind": None, "value": None, "page": None, "source": None, "required": fid in required, "note": "resolver_error: %s" % e}
            continue
        facts[fid] = {"status": st, "kind": kind, "value": f["value"] if f else None, "page": f["page"] if f else None,
                      "source": f["source"] if f else None, "required": fid in required}
    if "audience" in facts and facts["audience"]["status"] == ABSENT:
        alias = AUDIENCE_FACT.get(category)
        if alias and alias in facts and facts[alias]["status"] == PRESENT:
            facts["audience"] = dict(facts[alias], required=False, note="from %s" % alias)
    return required, facts


PARTIAL_LABELS = {
    "trial_only": "a free-trial mention but no price, free tier, or sales-led path",
}


def _partial_label(kind):
    return PARTIAL_LABELS.get(kind or "", "a %s hint" % (kind or "").replace("_", " "))


# ---------------------------------------------------------------- checks
def check_key_facts(ctx, out, pages, required, facts):
    missing = [(fid, facts[fid]) for fid in required if facts[fid]["status"] != PRESENT]
    if not missing:
        out.check("fx.facts.key_fact_missing", "pass", pages=[p.final_url for p in pages])
        return
    roles = ", ".join(p.role for p in pages)
    parts = []
    for fid, f in missing:
        if f["status"] == PARTIAL:
            parts.append("%s (partial: %s; %r on %s)" % (fid, _partial_label(f["kind"]), (f["value"] or "")[:60], urlsplit(f["page"] or "").path or "/"))
        else:
            parts.append("%s (absent)" % fid)
    items = [evidence_item("site", "computed", "pages_searched=%d (%s); key_facts=%d; found=%d; missing=%s" % (
        len(pages), roles, len(required), len(required) - len(missing), ",".join(fid for fid, _ in missing)))]
    for fid, f in missing:
        if f["status"] == PARTIAL and f["value"]:
            items.append(evidence_item(f["page"] or "site", "text_excerpt", f["value"], note="%s: %s" % (fid, _partial_label(f["kind"]))))
    for fid in required:
        f = facts[fid]
        if f["status"] == PRESENT:
            items.append(evidence_item(f["page"] or "site", "text_excerpt", f["value"] or "", note="%s found via %s" % (fid, f["source"])))
    advice = " ".join(FACT_ADVICE.get(fid, "Add %s as plain text." % fid) for fid, _ in missing[:3])
    out.fail("fx.facts.key_fact_missing",
             title="%d of %d key facts for %s are not extractable as text" % (len(missing), len(required), category_label(ctx.category)),
             evidence="Searched %d sampled pages (%s). Found %d of %d key facts as plain text or structured data; not found: %s." % (
                 len(pages), roles, len(required) - len(missing), len(required), "; ".join(parts)),
             evidence_items=items,
             why="An assistant answers from the text it can extract. A fact that is absent, or present only as a hint, is a question the brand cannot be quoted on, so the answer comes from a competitor or from nowhere. The brand is invisible for that question.",
             action="Add the missing facts as plain text on the pages a visitor would expect them (%s)." % ", ".join(fid.replace("_", " ") for fid, _ in missing[:4]),
             detail=advice + " Mirror each fact in the matching JSON-LD property (offers.price, address, telephone, openingHoursSpecification, description, audience) so both text and structured data agree.",
             references=[REFS["sd_general"]],
             extra_adjust=["single_missing_fact:medium"] if len(missing) == 1 else None)
    # Severity scales with how much of the category's fact set is unavailable. One gap is a gap;
    # two or more is a pattern of facts an assistant cannot quote. Without this the check reported
    # `high` whether one fact was missing or all of them, which flattens the report: measured across
    # 38 real sites it fired `high` on 47% of them, so the severity stopped distinguishing anything.
    if len(missing) == 1 and out.findings[-1]["severity"] == "high":
        out.findings[-1]["severity"] = "medium"
        out.findings[-1]["suggested_action"]["priority"] = "medium"
        out.findings[-1]["suggested_action"]["impact"] = "medium"


def check_image_only(ctx, out, pages, facts):
    required = set(KEY_FACTS.get(ctx.category, KEY_FACTS["unknown"]))
    hits_by_page = []
    for p in pages:
        d = p.doc
        text = p_text = X.page_text(p)
        page_hits = []
        for img in d.images:
            if (img.get("role") == "presentation") or (img.get("alt") == ""):
                continue
            w, h = img.get("width"), img.get("height")
            if (w is not None and w < 50) or (h is not None and h < 50):
                continue
            alt = img.get("alt") or ""
            fname = os.path.basename(urlsplit(img.get("src") or "").path)
            heading = ""
            for hd in d.headings:
                if hd["pos"] <= img.get("pos", 0):
                    heading = hd["text"] or ""
            for fact in IMAGE_FACT_WORDS:
                # only the category's key facts, only on the pages where that fact is expected, only from labels
                if not any(f in required for f in IMAGE_FACT_TO_FACT_IDS[fact]) or p.role not in IMAGE_FACT_PAGES[fact]:
                    continue
                signals = image_fact_signals(alt, fname, heading, fact)
                if not signals:
                    continue
                if fact == "pricing" and X.PRICE_RE.search(p_text):
                    continue
                if fact == "hours" and X.HOURS_RE.search(text):
                    continue
                if fact == "address" and (X.STREET_RE.search(text) or X.UK_POSTCODE_RE.search(text) or X.US_CITY_STATE_ZIP_RE.search(text)):
                    continue
                if fact == "menu" and len([hd for hd in d.headings if hd["tag"] in ("h2", "h3")]) >= 6:
                    continue
                if fact == "specs":
                    continue  # never a finding: feature grids are usually decorative restatements of text
                page_hits.append({"fact": fact, "src": img.get("src"), "alt": alt, "filename": fname, "heading": heading, "signals": signals,
                                  "key_fact": True})
                break
        if page_hits:
            hits_by_page.append((p, page_hits))
    if not hits_by_page:
        out.check("fx.facts.image_only", "pass", pages=[p.final_url for p in pages])
        return
    for p, hits in hits_by_page:
        strong = any(len(h["signals"]) >= 2 for h in hits)
        kinds = sorted({h["fact"] for h in hits})
        f = out.fail("fx.facts.image_only",
                     title="%s exist%s only as an image on the %s page" % (" and ".join(k.capitalize() for k in kinds), "s" if len(kinds) == 1 else "", p.role),
                     evidence="%d image%s on %s signal %s (%s) and the page text contains no %s. A fetcher cannot read text inside an image." % (
                         len(hits), "s" if len(hits) != 1 else "", urlsplit(p.final_url).path or "/", "/".join(kinds),
                         "; ".join("alt=%r file=%s" % (h["alt"][:40], h["filename"]) for h in hits[:3]),
                         "currency amount" if "pricing" in kinds else " or ".join(kinds)),
                     evidence_items=[evidence_item(p.final_url, "html_excerpt", '<img src="%s" alt="%s">' % (h["src"], h["alt"]), note="signals=%s heading=%r" % (",".join(h["signals"]), h["heading"][:40])) for h in hits[:4]] +
                                    [evidence_item(p.final_url, "computed", "visible_words=%d; price_text_found=%s" % (p.doc.word_count, bool(X.PRICE_RE.search(X.page_text(p)))))],
                     why="Assistants and crawlers extract facts from text and structured data, not from pixels. The %s a visitor sees %s not exist for them, so the brand cannot be quoted on it. Invisible." % (
                         " and ".join(kinds), "do" if len(kinds) > 1 else "does"),
                     action="Reproduce the %s as HTML text on this page (a table or list), keeping the image if you like." % " and ".join(kinds),
                     detail="Add the same information as a text table or list directly under the image, and add the matching JSON-LD (Offer.price and priceCurrency for prices, openingHoursSpecification for hours, PostalAddress for addresses). Verify by searching the page source for the numbers.",
                     pages=[p.final_url], page_roles=[p.role], confidence="medium" if strong else "low")


def check_jsonld(ctx, out, pages):
    blocks = [(p, b, i) for p in pages for i, b in enumerate(p.doc.jsonld)]
    if not blocks:
        micro = [p for p in pages if getattr(p.doc, "microdata_hint", False)]
        evidence = "0 of %d sampled pages (%s) contain a script[type=application/ld+json] block." % (len(pages), ", ".join(p.role for p in pages))
        items = [evidence_item(p.final_url, "computed", "jsonld_blocks=0") for p in pages[:6]]
        if micro:
            evidence += " Microdata or RDFa attributes (itemtype/typeof/vocab) are present on %d page%s; this audit does not parse them." % (len(micro), "s" if len(micro) != 1 else "")
            items.append(evidence_item(micro[0].final_url, "computed", "microdata_or_rdfa=present on %s" % ", ".join(p.role for p in micro[:6]), note="not parsed; validate separately"))
        out.fail("fx.jsonld.missing",
                 title="No JSON-LD structured data on any of the %d sampled pages" % len(pages),
                 evidence=evidence,
                 evidence_items=items,
                 confidence="medium" if micro else "high",
                 why="Structured data is the one place a brand states its identity, offers and contact details in a form every machine parses the same way. Without it, assistants reconstruct the brand from prose and are more likely to confuse it with something else. Supporting, not sufficient: the plain-text facts still matter most.",
                 action="Add an Organization (or Person) JSON-LD block to the home page with name, url, logo, sameAs and contact details, then type-specific blocks on product, pricing and article pages.",
                 detail="Start with one block in the home page <head>: @type Organization, name, url, logo, sameAs (Wikidata, Wikipedia, LinkedIn), address, telephone. Then Product/SoftwareApplication with offers on product pages and FAQPage where questions are answered. Validate with the Schema Markup Validator.",
                 references=[REFS["jsonld"]])
        for cid in ("fx.jsonld.malformed", "fx.jsonld.required_props_missing", "fx.jsonld.no_organization"):
            out.not_evaluated(cid, reason="dependency_failed")
        return
    out.check("fx.jsonld.missing", "pass", pages=[p.final_url for p in pages])
    bad = [(p, b, i) for p, b, i in blocks if b["error"]]
    if bad:
        pages_bad = sorted({p.final_url for p, _, _ in bad})
        out.fail("fx.jsonld.malformed",
                 title="%d JSON-LD block%s fail%s to parse on %s" % (len(bad), "s" if len(bad) != 1 else "", "" if len(bad) != 1 else "s", ", ".join(sorted({p.role for p, _, _ in bad}))),
                 evidence="%s. A block that does not parse is silently ignored by every consumer; it is worse than no block because it looks done." % "; ".join(
                     "%s block %d: %s" % (p.role, i + 1, b["error"].split(":")[0]) for p, b, i in bad[:4]),
                 evidence_items=[evidence_item(p.final_url, "jsonld_excerpt", b["raw"][-160:] if len(b["raw"]) > 160 else b["raw"], location="script[type=application/ld+json][%d]" % (i + 1), note=b["error"]) for p, b, i in bad[:4]],
                 why="Validators and crawlers drop unparseable JSON, so whatever this block was meant to say about the brand is not said. The failure is invisible in a browser, so it persists.",
                 action="Fix the JSON syntax in the listed block%s (the parser error names the position)." % ("s" if len(bad) != 1 else ""),
                 detail="Common causes: a trailing comma before a closing brace, unescaped quotes in text, or template output injecting HTML. Paste the block into a JSON validator, fix, and re-check with the Schema Markup Validator.",
                 pages=pages_bad, page_roles=[p.role for p, _, _ in bad], references=[REFS["jsonld"]])
    else:
        out.check("fx.jsonld.malformed", "pass")
    incomplete = []
    for p in pages:
        for n, i in X.doc_top_nodes(p.doc):
            spec_type, missing, unmet = X.missing_required(n)
            if spec_type and (missing or unmet):
                incomplete.append((p, i, spec_type, X.node_types(n), missing, unmet))
    if incomplete:
        desc = "; ".join("%s on %s lacks %s" % (types[0], p.role, ", ".join(missing + ["|".join(g) for g in unmet])) for p, i, st, types, missing, unmet in incomplete[:4])
        out.fail("fx.jsonld.required_props_missing",
                 title="%d JSON-LD node%s lack%s required properties" % (len(incomplete), "s" if len(incomplete) != 1 else "", "" if len(incomplete) != 1 else "s"),
                 evidence=desc + ".",
                 evidence_items=[evidence_item(p.final_url, "jsonld_excerpt", json.dumps({k: v for k, v in list(_node_preview(p, i, types).items())[:6]}, ensure_ascii=False)[:280],
                                               location="script[type=application/ld+json][%d]" % (i + 1), note="missing: %s" % ", ".join(missing + ["|".join(g) for g in unmet])) for p, i, st, types, missing, unmet in incomplete[:4]],
                 why="A node without its identifying properties tells a machine that something exists but not what it is called or what it offers, so it cannot be matched to the brand or quoted.",
                 action="Add the missing properties to each listed node.",
                 detail="For each node add: %s. Validate with the Schema Markup Validator and Google's Rich Results Test." % "; ".join(
                     "%s → %s" % (st, ", ".join(missing + [" or ".join(g) for g in unmet])) for p, i, st, types, missing, unmet in incomplete[:4]),
                 pages=sorted({p.final_url for p, *_ in incomplete}), page_roles=[p.role for p, *_ in incomplete], references=[REFS["jsonld"]])
    else:
        out.check("fx.jsonld.required_props_missing", "pass")
    anchor_pages = [p for p in pages if p.role in ("home", "about")] or pages[:1]
    allow_person = ctx.category == "portfolio_personal"
    has_org = any(X.is_org_node(n, allow_person=allow_person) for p in anchor_pages for n, _ in X.doc_top_nodes(p.doc))
    if has_org:
        out.check("fx.jsonld.no_organization", "pass")
    else:
        types_seen = sorted({t for p in pages for t in p.doc.jsonld_types})
        out.fail("fx.jsonld.no_organization",
                 title="JSON-LD is present but no %s node describes the site owner" % ("Organization or Person" if allow_person else "Organization"),
                 evidence="Structured data types found: %s; none on the home or about page identifies the organisation behind the site." % (", ".join(types_seen[:8]) or "none"),
                 evidence_items=[evidence_item(p.final_url, "computed", "jsonld_types=%s" % ",".join(p.doc.jsonld_types)) for p in anchor_pages],
                 why="Without an Organization node there is no machine-readable statement of who the brand is, so page-level markup floats unattached to an entity.",
                 action="Add an Organization JSON-LD node (name, url, logo, sameAs) to the home page.",
                 detail="One block in the home page <head> is enough; reference it from other nodes via publisher or provider.",
                 pages=[p.final_url for p in anchor_pages], page_roles=[p.role for p in anchor_pages], references=[REFS["jsonld"]])


def _node_preview(page, block_index, types):
    try:
        for n, i in X.doc_top_nodes(page.doc):
            if i == block_index and X.node_types(n) == types:
                return {k: (v if isinstance(v, (str, int, float)) else "…") for k, v in n.items()}
    except Exception:  # noqa: BLE001
        pass
    return {}


def check_identity(ctx, out, pages):
    host = (urlsplit(ctx.site or "").hostname or "").lower()
    bad_title, bad_h1, no_desc, no_og = [], [], [], []
    for p in pages:
        d = p.doc
        t = (d.title or "").strip()
        tl = t.lower().rstrip(".!")
        if not t or tl in GENERIC_TITLES or tl in (host, host[4:] if host.startswith("www.") else host) or len(t) < 3:
            bad_title.append((p, t))
        if len(d.h1s) != 1:
            bad_h1.append((p, len(d.h1s)))
        if not (d.meta("description") or "").strip():
            no_desc.append(p)
        if not d.meta("og:title") and not d.meta("og:description"):
            no_og.append(p)
    urls = lambda lst: [x[0].final_url if isinstance(x, tuple) else x.final_url for x in lst]
    roles = lambda lst: [x[0].role if isinstance(x, tuple) else x.role for x in lst]
    if bad_title:
        out.fail("fx.identity.title_missing_or_generic",
                 title="%d page%s ha%s a missing or generic <title>" % (len(bad_title), "s" if len(bad_title) != 1 else "", "ve" if len(bad_title) != 1 else "s"),
                 evidence="; ".join("%s: %s" % (p.role, repr(t) if t else "no <title>") for p, t in bad_title[:5]) + ".",
                 evidence_items=[evidence_item(p.final_url, "html_excerpt", "<title>%s</title>" % t if t else "(no title element)") for p, t in bad_title[:6]],
                 why="The title is the first thing an indexer and an assistant use to say what a page is. 'Home' or an empty title makes the page anonymous in any list of sources.",
                 action="Give each page a title that names the brand and the page's subject.",
                 detail="Pattern: '<Page subject> — <Brand>' (50 to 60 characters). Set it in the template or CMS per page; verify by viewing source.",
                 pages=urls(bad_title), page_roles=roles(bad_title), references=[REFS["title"]])
    else:
        out.check("fx.identity.title_missing_or_generic", "pass")
    if bad_h1:
        out.fail("fx.identity.h1_missing_or_multiple",
                 title="%d page%s ha%s %s" % (len(bad_h1), "s" if len(bad_h1) != 1 else "", "ve" if len(bad_h1) != 1 else "s",
                                             "no <h1>" if all(n == 0 for _, n in bad_h1) else ("multiple <h1> elements" if all(n > 1 for _, n in bad_h1) else "zero or multiple <h1> elements")),
                 evidence="; ".join("%s: %d h1" % (p.role, n) for p, n in bad_h1[:6]) + ".",
                 evidence_items=[evidence_item(p.final_url, "computed", "h1_count=%d" % n) for p, n in bad_h1[:6]],
                 why="The single main heading is how a machine decides what the page is about. Zero headings leave it guessing; several compete.",
                 action="Use exactly one <h1> per page that states the page's subject.",
                 detail="Demote extra h1s to h2, or add an h1 above the main content. Check the template rather than individual pages.",
                 pages=urls(bad_h1), page_roles=roles(bad_h1))
    else:
        out.check("fx.identity.h1_missing_or_multiple", "pass")
    if no_desc:
        out.fail("fx.identity.meta_description_missing",
                 title="%d page%s ha%s no meta description" % (len(no_desc), "s" if len(no_desc) != 1 else "", "ve" if len(no_desc) != 1 else "s"),
                 evidence="No <meta name=\"description\"> on %s." % ", ".join(p.role for p in no_desc[:6]),
                 evidence_items=[evidence_item(p.final_url, "computed", "meta_description=absent") for p in no_desc[:6]],
                 why="The description is a ready-made one-sentence summary that indexers and some assistants quote directly. Without it they improvise one from whatever text comes first.",
                 action="Add a one-sentence meta description to each listed page.",
                 detail="One factual sentence (up to 160 characters) that says what the page offers and for whom. Set per page in the CMS.",
                 pages=urls(no_desc), page_roles=roles(no_desc), references=[REFS["snippet"]])
    else:
        out.check("fx.identity.meta_description_missing", "pass")
    if no_og:
        out.fail("fx.identity.og_missing",
                 title="%d page%s ha%s no Open Graph title or description" % (len(no_og), "s" if len(no_og) != 1 else "", "ve" if len(no_og) != 1 else "s"),
                 evidence="Neither og:title nor og:description on %s." % ", ".join(p.role for p in no_og[:6]),
                 evidence_items=[evidence_item(p.final_url, "computed", "og:title=absent; og:description=absent") for p in no_og[:6]],
                 why="Open Graph tags are the second self-description a page carries; link previews and some fetchers read them when the title is ambiguous.",
                 action="Add og:title, og:description and og:site_name to each page.",
                 detail="Mirror the title and meta description; set og:site_name to the brand name. Most CMS SEO plugins do this in one setting.",
                 pages=urls(no_og), page_roles=roles(no_og), references=[REFS["og"]])
    else:
        out.check("fx.identity.og_missing", "pass")


def check_alt_text(ctx, out, pages):
    bad = []
    for p in pages:
        imgs = [i for i in p.doc.images if i.get("role") != "presentation" and i.get("alt") != ""
                and not ((i.get("width") is not None and i["width"] < 50) or (i.get("height") is not None and i["height"] < 50))]
        if len(imgs) < 3:
            continue  # too few content images to judge a pattern
        missing = [i for i in imgs if i.get("alt") is None]
        if len(missing) >= 2 and len(missing) / len(imgs) > 0.30:
            bad.append((p, len(missing), len(imgs)))
    if bad:
        out.fail("fx.media.alt_text_missing",
                 title="Over 30%% of content images lack alt text on %d page%s" % (len(bad), "s" if len(bad) != 1 else ""),
                 evidence="; ".join("%s: %d of %d images without alt" % (p.role, m, n) for p, m, n in bad[:6]) + ".",
                 evidence_items=[evidence_item(p.final_url, "computed", "images=%d; missing_alt=%d" % (n, m)) for p, m, n in bad[:6]],
                 why="Alt text is the only text a non-visual reader gets from an image. When product shots, charts or infographics carry facts, missing alt text removes them from what can be extracted.",
                 action="Add descriptive alt text to content images (and alt=\"\" to purely decorative ones).",
                 detail="Describe what the image shows and any text or numbers in it. Decorative images should carry an empty alt so they are skipped, not counted.",
                 pages=[p.final_url for p, _, _ in bad], page_roles=[p.role for p, _, _ in bad], references=[REFS["alt"]])
    else:
        out.check("fx.media.alt_text_missing", "pass")


def check_faq(ctx, out, pages):
    ov = SEVERITY_OVERRIDES.get("fx.content.faq_absent", {}).get(ctx.category)
    if ov == "not_evaluated":
        out.not_evaluated("fx.content.faq_absent", reason="not_applicable_for_category")
        return
    f = X.find_faq(pages)
    if f:
        out.check("fx.content.faq_absent", "pass", pages=[f["page"]])
        return
    out.fail("fx.content.faq_absent",
             title="No FAQ-shaped content or FAQPage markup on the sampled pages",
             evidence="None of the %d sampled pages has a FAQ heading, three or more question headings, or FAQPage JSON-LD." % len(pages),
             evidence_items=[evidence_item(p.final_url, "computed", "faq_heading=false; question_headings=%d; FAQPage=false" % len([h for h in p.doc.headings if (h["text"] or "").endswith("?")])) for p in pages[:6]],
             why="A page shaped as question and answer can help it match a question-shaped query, but a 23,745-citation measurement study across 602 prompts found Q&A-formatted content has lower influence on the generated answer once selected (-5.74%) than content built around concrete numbers, comparisons, or plain definitions (+41% to +62%). This is an opportunity, not a defect: add FAQ content for retrieval and clarity, and keep stating the same facts as ordinary prose too, not only as isolated Q&A pairs.",
             action="Add a short FAQ (five real questions customers ask, answered in one or two sentences each) on the pricing or product page, with FAQPage JSON-LD, and state the same facts once more in the page's main prose.",
             detail="Use the questions your support inbox actually receives. Put each question in a heading and the answer directly under it, then mirror them in FAQPage mainEntity. A stray Q&A pair is not a substitute for the fact being stated plainly elsewhere on the page.",
             references=[REFS["faq"], REFS["absorption"]])


# ---------------------------------------------------------------- facts file
def write_facts(ctx, pages, excluded, required, facts, brand, recommendations):
    doc = {
        "site": ctx.site, "site_category": ctx.category, "extracted_at": _now(), "basis": "served_html_only",
        "brand_name": brand,
        "facts": facts,
        "required_fact_ids": required,
        "pages_used": [{"role": p.role, "url": p.final_url, "words": p.doc.word_count, "jsonld_types": p.doc.jsonld_types} for p in pages],
        "pages_excluded": [{"role": p.role, "url": p.final_url, "reason": r} for p, r in excluded],
        "identity": {p.role: {"title": p.doc.title, "h1": p.doc.h1s[:2], "description": p.doc.meta("description"), "og_site_name": p.doc.meta("og:site_name")} for p in pages},
        "jsonld_recommendations": recommendations,
        "note": "Values are verbatim excerpts from the served HTML. status: present | partial | absent. The AI-answer simulation may use only these values.",
    }
    if ctx.workdir:
        path = os.path.join(ctx.workdir, FACTS_REL)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        return FACTS_REL, doc
    return None, doc


def jsonld_recommendations(pages):
    recs = []
    for p in pages:
        for n, i in X.doc_top_nodes(p.doc):
            spec_type, missing = X.missing_recommended(n)
            if spec_type and missing:
                recs.append({"page": p.final_url, "type": spec_type, "missing_recommended": missing})
    return recs[:20]


# ---------------------------------------------------------------- main
def run(ctx):
    out = ProbeOutput(PROBE, ctx.site, ctx.category, [], total_sampled_pages=len(ctx.pages))
    if ctx.error:
        out.error = ctx.error
        out.fill_unreported("fx.", status="not_evaluated")
        for c in out.checks:
            c.setdefault("reason", "context_error")
        return out
    home = ctx.home
    if home and home.skipped == "robots_disallow":
        out.fill_unreported("fx.", status="not_evaluated")
        for c in out.checks:
            c["reason"] = "robots_disallow"
        return out
    usable, excluded = [], []
    for p in ctx.pages:
        if p.skipped:
            excluded.append((p, p.skipped)); continue
        if p.challenge:
            excluded.append((p, "challenge_page")); continue
        if p.error or (p.status or 0) >= 400:
            excluded.append((p, "http_error")); continue
        if not p.ok_html:
            excluded.append((p, "non_html")); continue
        state = render_state(p.doc)
        if state in ("gate", "shell"):
            excluded.append((p, "no_rendered_content")); continue
        usable.append(p)
    out.pages_examined = [p.final_url for p in usable]
    required = KEY_FACTS.get(ctx.category, KEY_FACTS["unknown"])
    facts, brand, recs = {}, {"value": None, "source": None, "page": None}, []
    try:
        if usable:
            required, facts = resolve_facts(ctx.category, usable)
            brand = X.brand_name(usable, ctx.site)
            recs = jsonld_recommendations(usable)
        rel, _ = write_facts(ctx, usable, excluded, required, facts, brand, recs)
        if rel:
            out.artifacts["extracted_facts"] = rel
    except Exception as e:  # noqa: BLE001
        out.error = "facts: %s: %s" % (type(e).__name__, e)
    if not usable:
        reasons = [r for _, r in excluded]
        reason = "challenge_page" if reasons and all(r == "challenge_page" for r in reasons) else (
            "no_rendered_content" if any(r == "no_rendered_content" for r in reasons) else ("non_html" if reasons and all(r == "non_html" for r in reasons) else "no_html_pages"))
        out.fill_unreported("fx.", status="not_evaluated")
        for c in out.checks:
            c["reason"] = reason
        return out
    for name, fn, args in (("key_facts", check_key_facts, (ctx, out, usable, required, facts)), ("image_only", check_image_only, (ctx, out, usable, facts)),
                           ("jsonld", check_jsonld, (ctx, out, usable)), ("identity", check_identity, (ctx, out, usable)),
                           ("alt", check_alt_text, (ctx, out, usable)), ("faq", check_faq, (ctx, out, usable))):
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001
            out.error = ((out.error or "") + " %s checks: %s: %s" % (name, type(e).__name__, e)).strip()
    out.fill_unreported("fx.", status="not_evaluated")
    for c in out.checks:
        if c["status"] == "not_evaluated" and "reason" not in c:
            c["reason"] = "dependency_failed"
    return out


def main(argv=None):
    return probe_main(PROBE, run, __doc__, argv)


if __name__ == "__main__":
    sys.exit(main())
