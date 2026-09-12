#!/usr/bin/env python3
"""engagement-audit probe: does a visitor who arrives, often mid-journey from an AI answer, stay and find their way?

Runs the 16 `en.*` checks of the shared registry over the sampled pages:
  first viewport   hero clarity, primary call to action
  orientation      navigation landmark, breadcrumbs, related links, site search, landing-page continuity
  friction         blocking interstitial, missing mobile viewport, page-weight proxy, missing lang
  trust            category trust signals
  reliability      sampled internal-link health (with the 403/429 cluster reclassification), soft and unhelpful 404s

Usage:
  engagement_probe.py --url https://example.com [--workdir DIR] [--out FILE] [--no-network]
  engagement_probe.py --workdir DIR [--out FILE] [--no-network]

Network: besides the sampled pages, at most 15 internal-link GETs and one GET of a deliberately non-existent path
(the 404 probe), under the shared fetch policy and robots.txt. `--offline`, `--no-network` or BRAND_AUDIT_NETWORK=0
skips both: en.links.* and en.errors.* become not_evaluated with reason network_disabled.
Writes `work/engagement.json` (what was sampled and decided). Standard library only. Never raises; internal errors are
reported in the `error` field.
"""
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "audit-orchestrator", "scripts")))

from auditlib import extract as X  # noqa: E402
from auditlib.categories import (CTA_VOCAB, CTA_VOCAB_BY_LANG, CTA_LANGS_SUPPORTED, CTA_UNIVERSAL, CATEGORY_NOUNS, OFFER_VERBS, TRUST_SIGNALS, TRUST_SIGNALS_DEFAULT,  # noqa: E402
                                 engagement_cap, is_key_page, category_label)
from auditlib.cli import probe_main  # noqa: E402
from auditlib.fetch import Fetcher, normalize_url, registrable_domain  # noqa: E402
from auditlib.findings import ProbeOutput, evidence_item, impact_for, priority_for  # noqa: E402
from auditlib.htmldoc import Document, WORD_RE  # noqa: E402
from auditlib.render import render_state  # noqa: E402
from auditlib.sampler import CONTEXT_RANK  # noqa: E402

PROBE = "engagement-audit"
ENGAGEMENT_REL = "work/engagement.json"
NETWORK_ENV = "BRAND_AUDIT_NETWORK"
LINK_SAMPLE_MAX = 15
LINK_TIMEOUT = 10.0
NETWORK_TIME_BUDGET = 40.0          # seconds this probe may spend on its own requests
FIRST_VIEWPORT_FRAC = 0.4           # "first 40% of the body markup"
LEAD_WORDS = 120
H1_MIN_WORDS, H1_MAX_WORDS = 3, 25
INTERSTITIAL_MIN_WORDS = 40
HEAVY_HTML_BYTES = 1024 * 1024
HEAVY_SCRIPT_TAGS = 40
HEAVY_IMAGES = 100
RELATED_MIN_LINKS = 3
LISTING_MIN_LINKS = 6               # a page listing this many internal links in lists is a listing page, not a detail page
BLOCKED_CLUSTER_MIN = 3
TRANSPORT_ERRORS = ("dns_failure", "connect_timeout", "read_timeout", "total_timeout", "connection_refused", "tls_error", "too_many_redirects")
SEARCH_INPUT_NAMES = {"q", "s", "search", "query", "keyword", "keywords", "term"}
STOPWORDS = {"this", "that", "with", "from", "your", "have", "will", "home", "page", "more", "what", "when", "where",
             "which", "their", "there", "they", "them", "then", "than", "into", "over", "also", "just", "only", "some", "such",
             "very", "here", "been", "were", "being", "after", "before", "other", "every", "each", "because", "while", "these",
             "those", "would", "could", "should", "welcome", "official", "site", "website"}
RELATED_HEADING_RE = re.compile(r"\b(related|similar|you\s+may\s+also\s+like|you\s+might\s+also\s+like|recommended|see\s+also|read\s+next|"
                                r"further\s+reading|more\s+(from|like|in)|customers\s+also|people\s+also|popular\s+(posts|products|articles)|"
                                r"you\s+may\s+also\s+need|frequently\s+bought|latest\s+(posts|articles|from))\b", re.I)
TERMS_PRIVACY_RE = re.compile(r"\b(terms|privacy|legal|imprint|impressum)\b", re.I)
RETURNS_RE = re.compile(r"\b(returns?|refunds?|exchanges?|money[\s-]back)\b", re.I)
BADGE_RE = re.compile(r"\b(visa|mastercard|amex|american\s+express|paypal|apple\s+pay|google\s+pay|klarna|stripe|ssl|secure\s+(checkout|payments?)|"
                      r"trustpilot|verified|norton|mcafee|trusted\s+shops|pci[\s-]?dss)\b", re.I)
REVIEW_RE = re.compile(r"\b(\d[\d,]*\s+(reviews?|ratings?)|rated\s+\d|\d(\.\d)?\s*(/|out\s+of)\s*5\b|\d(\.\d)?\s+stars?|trustpilot|google\s+reviews|tripadvisor|yelp)\b", re.I)
TESTIMONIAL_RE = re.compile(r"\b(testimonials?|trusted\s+by|loved\s+by|used\s+by|our\s+customers|customers\s+(say|include)|"
                            r"what\s+(our\s+)?(customers|clients|users)\s+say|clients\s+include|case\s+stud(y|ies)|success\s+stor(y|ies)|as\s+seen\s+in|featured\s+in)\b", re.I)
SECURITY_RE = re.compile(r"\b(security|compliance|soc\s?2|iso\s?27001|gdpr|hipaa|trust\s+cent(er|re)|data\s+protection)\b", re.I)
TEAM_RE = re.compile(r"\b(our\s+team|the\s+team|meet\s+the\s+team|team|our\s+people|people|leadership|founders?|partners|staff|who\s+we\s+are|board|trustees|directors)\b", re.I)
CLIENTS_RE = re.compile(r"\b(clients?|case\s+stud(y|ies)|our\s+work|portfolio|projects|customers|selected\s+work|who\s+we\s+work\s+with)\b", re.I)
CREDENTIALS_RE = re.compile(r"\b(accredit(ed|ation)|certif(ied|icate|ication)|chartered|licen[cs]ed|regulated\s+by|member\s+of|registered\s+with|"
                            r"award(-|\s)winning|iso\s?\d{4,5}|bar\s+association|fellow\s+of)\b", re.I)
REG_NUMBER_RE = re.compile(r"\b(charity|registered|registration|company|organi[sz]ation|ein|tax)\s*(no\.?|number|#|id)?\s*[:#]?\s*[A-Z]{0,3}\d{5,}\b|\b501\s*\(\s*c\s*\)\s*\(?\s*3\s*\)?", re.I)
FINANCIAL_RE = re.compile(r"\b(annual\s+report|financial\s+(statements?|reports?|summary)|impact\s+report|form\s+990|audited\s+accounts|accounts\s+and\s+reports)\b", re.I)
PREMISES_IMG_RE = re.compile(r"\b(shop|store|storefront|office|premises|interior|exterior|restaurant|dining|salon|clinic|team|staff|building|room|kitchen|studio|front)\b", re.I)
REFS = {
    "viewport": "https://developer.mozilla.org/en-US/docs/Web/HTML/Guides/Viewport_meta_element",
    "lang": "https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Global_attributes/lang",
    "breadcrumb": "https://developers.google.com/search/docs/appearance/structured-data/breadcrumb",
    "soft404": "https://developers.google.com/search/docs/crawling-indexing/http-network-errors#soft-404-errors",
    "nav": "https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/nav",
}
_NOUN_RES = {}
_VERB_RE = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(v) for v in OFFER_VERBS), re.I)


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(url):
    try:
        return normalize_url(url).rstrip("/")
    except Exception:  # noqa: BLE001
        return (url or "").rstrip("/")


def _words(s):
    return WORD_RE.findall(s or "")   # the shared tokenizer: whole words in every script, see htmldoc.WORD_RE


def _norm_words(s):
    return " ".join(w.lower() for w in _words(s))


def _noun_re(category):
    if category not in _NOUN_RES:
        nouns = CATEGORY_NOUNS.get(category) or CATEGORY_NOUNS["unknown"]
        _NOUN_RES[category] = re.compile(r"\b(?:%s)(?:s|es|ing|ed)?\b" % "|".join(re.escape(n) for n in nouns), re.I)
    return _NOUN_RES[category]


def _page_lang(doc):
    """The page's declared language as a bare subtag ('de-CH' -> 'de'), or None."""
    raw = (getattr(doc, "lang", None) or "").strip().lower()
    return raw.split("-")[0] if raw else None


def _cta_re(category, lang=None):
    """CTA matcher for a category, extended with the page language's vocabulary.

    English is the category table; a non-English page is matched against its own words too,
    because otherwise a German site's "Anmelden" and "Abonnement" read as no call to action.
    Measured: the English-only version called that a missing CTA on spiegel.de.
    """
    vocab = list(CTA_VOCAB.get(category) or CTA_VOCAB["unknown"])
    if lang and lang != "en":
        vocab += CTA_VOCAB_BY_LANG.get(lang, [])
    words = vocab + [v for v in CTA_UNIVERSAL if v not in vocab]   # vocab stays category-first for the messages
    return re.compile(r"\b(?:%s)\b" % "|".join(re.escape(v).replace(r"\ ", r"\s+") for v in words), re.I), vocab


def _network_enabled(ctx, args):
    # --offline must hold in workdir mode too, where ctx.fetcher is None and this probe would otherwise
    # build its own online one; the flag, not the context, is the authority.
    if args is not None and (getattr(args, "no_network", False) or getattr(args, "offline", False)):
        return False
    if os.environ.get(NETWORK_ENV, "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    if ctx.fetcher is not None and getattr(ctx.fetcher, "offline", False):
        return False
    return True


# ---------------------------------------------------------------- pages
def classify_pages(ctx):
    """usable (rendered HTML), html_pages (any served HTML incl. gates/shells), excluded [(page, reason)]."""
    usable, html_pages, excluded = [], [], []
    for p in ctx.pages:
        if p.skipped:
            excluded.append((p, p.skipped)); continue
        if p.challenge:
            excluded.append((p, "challenge_page")); continue
        if p.error or (p.status or 0) >= 400:
            excluded.append((p, "network_disabled" if p.error == "network_disabled" else "http_error")); continue
        if not p.ok_html:
            excluded.append((p, "non_html")); continue
        html_pages.append(p)
        if render_state(p.doc) in ("gate", "shell"):
            excluded.append((p, "no_rendered_content")); continue
        usable.append(p)
    return usable, html_pages, excluded


def dominant_reason(ctx, excluded):
    reasons = [r for _, r in excluded]
    home = ctx.home
    if home is not None and home.skipped == "robots_disallow":
        return "robots_disallow"
    if reasons and all(r == "network_disabled" for r in reasons):
        return "network_disabled"
    if reasons and all(r == "challenge_page" for r in reasons):
        return "challenge_page"
    if any(r == "no_rendered_content" for r in reasons):
        return "no_rendered_content"
    if reasons and all(r == "non_html" for r in reasons):
        return "non_html"
    return "no_html_pages"


def page_reason(page, excluded):
    if page is None:
        return "no_html_pages"
    for p, r in excluded:
        if p is page:
            return r
    return "no_html_pages"


def _cap(out, cid, ctx):
    """Category applicability: None (not applicable, recorded), 'yes', or 'low'."""
    cap = engagement_cap(cid, ctx.category)
    if cap == "no":
        out.not_evaluated(cid, reason="not_applicable_for_category")
        return None
    return cap


def _fail(out, cid, cap, **kw):
    if cap == "low":
        kw["extra_adjust"] = list(kw.get("extra_adjust") or []) + ["category_cap:low"]
    f = out.fail(cid, **kw)
    if cap == "low" and f["severity"] != "low":
        f["severity"] = "low"
        f["suggested_action"]["impact"] = impact_for("low")
        f["suggested_action"]["priority"] = priority_for("low", f["confidence"])
    return f


def _short(url, n=80):
    return url if len(url) <= n else url[:n - 1] + "…"


# ---------------------------------------------------------------- first viewport
def lead_text(doc, h1):
    text = doc.body_text or ""
    if h1:
        i = text.find(h1)
        if i >= 0:
            text = text[i:]
    return " ".join(_words(text)[:LEAD_WORDS])


def check_hero(ctx, out, usable, excluded, work):
    cid = "en.hero.value_prop_unclear"
    cap = _cap(out, cid, ctx)
    if cap is None:
        return
    home = ctx.home
    if home is None or home not in usable:
        out.not_evaluated(cid, reason=page_reason(home, excluded)); return
    doc = home.doc
    signals, notes = [], []     # signals fail the check; notes only explain what was read
    # what a visitor reads, not what the markup hides: a screen-reader-only h1 is not this page's headline
    h1 = next((h for h in doc.visible_h1s if h.strip()), None)   # an <h1> holding only an image has no text a machine can read
    h1_tag = "h1"
    hidden_h1_only = h1 is None and any(h.strip() for h in doc.h1s)
    if hidden_h1_only:
        visible = doc.visible_headings(("h2", "h3"))
        if visible:
            # reading the visible heading instead is a fact about where the text came from, not a defect:
            # putting it in signals made a page whose visible heading is perfectly good fail the check
            h1, h1_tag = visible[0]["text"], visible[0]["tag"]
            notes.append("h1_hidden_from_sight:read_%s_instead" % h1_tag)
        else:
            signals.append("h1_hidden_only")     # nothing a sighted visitor can read announces the page
    n = len(_words(h1)) if h1 else 0
    if h1 is None and not hidden_h1_only:
        signals.append("h1_missing" if not doc.h1s else "h1_empty")
    elif n < H1_MIN_WORDS:
        signals.append("h1_too_short:%d_words" % n)
    elif n > H1_MAX_WORDS:
        signals.append("h1_too_long:%d_words" % n)
    lead = lead_text(doc, h1)
    noun = _noun_re(ctx.category).search(lead)
    verb = _VERB_RE.search(lead)
    if not noun and not verb:
        signals.append("lead_text_no_offer")
    work["hero"] = {"page": home.final_url, "h1": h1, "h1_tag": h1_tag, "h1_words": n, "lead_excerpt": lead[:240],
                    "category_noun": noun.group(0) if noun else None,
                    "offer_verb": verb.group(0) if verb else None, "signals": signals, "notes": notes}
    if not signals:
        out.check(cid, "pass", pages=[home.final_url]); return
    conf = "medium" if len(signals) >= 2 else "low"
    if "h1_missing" in signals or "h1_empty" in signals or "h1_hidden_only" in signals:
        title = {"h1_missing": "Home page has no main heading to say what the site offers",
                 "h1_empty": "Home page's main heading holds no text, only an image",
                 "h1_hidden_only": "Home page's only heading is hidden from sighted visitors"}[
            next(k for k in ("h1_missing", "h1_empty", "h1_hidden_only") if k in signals)]
        first = {"h1_missing": "no <h1>", "h1_empty": "an <h1> with no text (image only)",
                 "h1_hidden_only": "an <h1> a sighted visitor never sees, and no visible heading below it"}[
            next(k for k in ("h1_missing", "h1_empty", "h1_hidden_only") if k in signals)]
    elif any(sig.startswith("h1_too_") for sig in signals):
        title = "Home page heading is %d words, too %s to state what the site offers" % (n, "short" if n < H1_MIN_WORDS else "long")
        first = "<%s> '%s' (%d words)" % (h1_tag, h1[:80], n)
    else:
        # the heading's length is fine; what failed is the text under it
        title = "Home page heading is %d words and the text below it does not say what is offered" % n
        first = "<%s> '%s' (%d words)" % (h1_tag, h1[:80], n)
    lead_note = ("the first %d words from the heading contain no %s noun and no verb of offer" % (LEAD_WORDS, ctx.category.replace("_", " "))
                 if "lead_text_no_offer" in signals else "the text below it does name the offer (%s)" % (noun.group(0) if noun else verb.group(0)))
    _fail(out, cid, cap, title=title,
          evidence="Home page: %s; %s." % (first, lead_note),
          evidence_items=[evidence_item(home.final_url, "text_excerpt", h1 or "(no h1)", location=h1_tag),
                          evidence_item(home.final_url, "text_excerpt", lead[:200], note="first %d words of the first viewport" % LEAD_WORDS),
                          evidence_item(home.final_url, "computed", "signals=%s; notes=%s; category_noun=%s; offer_verb=%s" % (
                              ",".join(signals), ",".join(notes) or "none",
                              noun.group(0) if noun else "none", verb.group(0) if verb else "none"))],
          why="Most of a visit's attention lands in the first screen. A visitor who cannot tell within a few seconds what the site offers and for whom leaves, and the click an assistant sent is wasted: the bouncing mode.",
          action="Rewrite the home page's first viewport as a headline that names the offer and the customer, a one-sentence subhead, and a primary call to action.",
          detail="Use a 5-12 word <h1> that states what the site provides (the product or service noun) for whom, followed by one plain sentence. Check with a stranger: shown only the first screen, can they say what you sell?",
          pages=[home.final_url], page_roles=["home"], confidence=conf)


def cta_hits(doc, rx, vocab, role=None):
    hits = []
    if role == "contact":
        # a contact page's call to action is the contact method itself, wherever it sits on the page: sipgate.de
        # shows its number as a tel: link in the header and was told its contact page asked for nothing
        for l in doc.links:
            scheme = urlsplit(l.url).scheme
            if not l.in_head and scheme in ("tel", "mailto"):
                hits.append((scheme, l.text or l.url))
    for l in doc.links:
        if l.in_head:
            continue
        frac = doc.body_frac(l.mpos)
        # A header or nav link is what a visitor sees first whatever its markup position: iiitd.ac.in's
        # <a>Admission</a> sits at 17.9-42.8% of the markup behind a long utility bar, past the 40% proxy,
        # and was reported as "no call to action" though it is the first thing in the page's own header.
        # FIRST_VIEWPORT_FRAC still governs body links, where markup position is the only proxy available.
        if l.context not in ("header", "nav") and (frac is None or frac > FIRST_VIEWPORT_FRAC):
            continue
        scheme = urlsplit(l.url).scheme
        if rx.search(l.text or ""):
            hits.append(("link", l.text or l.url))
        elif scheme == "mailto" and ("email" in vocab or "contact" in vocab):
            hits.append(("mailto", l.text or l.url))
        elif scheme == "tel" and ("call" in vocab or "contact" in vocab):
            hits.append(("tel", l.text or l.url))
    for b in doc.buttons:
        frac = doc.body_frac(b.get("mpos"))
        if frac is not None and frac <= FIRST_VIEWPORT_FRAC and rx.search(b.get("text") or ""):
            hits.append(("button", b["text"]))
    for f in doc.forms:
        frac = doc.body_frac(f.get("mpos"))
        if frac is None or frac > FIRST_VIEWPORT_FRAC or is_search_form(f):
            continue
        inputs = [i for i in f["inputs"] if i["type"] not in ("hidden", "submit", "button", "search")]
        if any((i.get("name") or "").lower() not in SEARCH_INPUT_NAMES for i in inputs):
            hits.append(("form", f["action"] or "(form)"))
    return hits


def check_cta(ctx, out, usable, work):
    cid = "en.cta.missing"
    cap = _cap(out, cid, ctx)
    if cap is None:
        return
    pages = [p for p in usable if is_key_page(p.role, ctx.category)]
    if not pages:
        out.not_evaluated(cid, reason="no_key_pages_usable"); return
    # Declared page language, if any (the first page that states one). A language outside
    # CTA_LANGS_SUPPORTED has no vocabulary to search for, and searching it with English or
    # the wrong language's words would repeat the bug this guards against: reporting "no call
    # to action" about a page whose buttons are simply in a language we did not check for.
    lang = next((_page_lang(p.doc) for p in pages if _page_lang(p.doc)), None)
    if lang and lang not in CTA_LANGS_SUPPORTED:
        out.not_evaluated(cid, reason="language_not_supported"); return
    rx, vocab = _cta_re(ctx.category, lang=lang)
    failing, items, seen = [], [], []
    for p in pages:
        hits = cta_hits(p.doc, rx, vocab, role=p.role)
        early = [l.text for l in p.doc.links if not l.in_head and p.doc.body_frac(l.mpos) is not None and p.doc.body_frac(l.mpos) <= FIRST_VIEWPORT_FRAC and l.text]
        work.setdefault("cta", {})[p.final_url] = {"role": p.role, "hits": hits[:5], "first_viewport_links": len(early)}
        if hits:
            seen.append(p.final_url)
        else:
            failing.append(p)
            items.append(evidence_item(p.final_url, "computed", "first_viewport_links=%d; matched=0; sample=%s" % (
                len(early), " | ".join(t[:30] for t in early[:6]) or "(none)"), note="%s page" % p.role))
    if not failing:
        out.check(cid, "pass", pages=seen); return
    roles = [p.role for p in failing]
    _fail(out, cid, cap,
          title="No primary call to action in the first viewport of the %s page%s" % ("/".join(roles), "s" if len(roles) != 1 else ""),
          evidence="On %d of %d key pages (%s) no link, button or form in the first %d%% of the page matches the %s vocabulary (%s) and no non-search form appears there." % (
              len(failing), len(pages), ", ".join(roles), int(FIRST_VIEWPORT_FRAC * 100), ctx.category.replace("_", " "), ", ".join(vocab[:5])),
          evidence_items=items[:6],
          why="A visitor who has just arrived needs one obvious next step. With nothing actionable in view, attention has nowhere to go and the visit ends on the first screen.",
          action="Add one primary call to action near the top of the %s page%s that names the next step." % ("/".join(roles[:3]), "s" if len(roles) != 1 else ""),
          detail="One button or prominent link in the header or hero: for this category one of '%s'. Keep it above the first scroll and repeat it at the end of the page." % "', '".join(vocab[:3]),
          pages=[p.final_url for p in failing], page_roles=roles)


# ---------------------------------------------------------------- orientation
def _anchor_page(ctx, usable):
    home = ctx.home
    if home is not None and home in usable:
        return home
    return usable[0] if usable else None


def has_nav_landmark(doc):
    if doc.nav_count > 0:
        return "nav_or_role_navigation"
    hdr = {l.url for l in doc.internal_links if l.context == "header" and l.in_list}
    if len(hdr) >= 3:
        return "header_list_%d_links" % len(hdr)
    return None


def check_landmark(ctx, out, usable, excluded, work):
    cid = "en.nav.landmark_missing"
    if ctx.category == "portfolio_personal" and (ctx.manifest.get("internal_pages_estimate") or 0) <= 3:
        out.not_evaluated(cid, reason="not_applicable_for_category"); return
    cap = _cap(out, cid, ctx)
    if cap is None:
        return
    page = _anchor_page(ctx, usable)
    if page is None:
        out.not_evaluated(cid, reason=dominant_reason(ctx, excluded)); return
    how = has_nav_landmark(page.doc)
    work["navigation"] = {"page": page.final_url, "landmark": how, "nav_count": page.doc.nav_count,
                          "header_list_links": len({l.url for l in page.doc.internal_links if l.context == "header" and l.in_list})}
    if how:
        out.check(cid, "pass", pages=[page.final_url]); return
    total = len({l.url for l in page.doc.internal_links})
    _fail(out, cid, cap,
          title="%s page has no navigation landmark" % page.role.capitalize(),
          evidence="%s page: no <nav> element, no role=navigation, and no list of three or more internal links inside <header> (internal links on the page: %d)." % (page.role.capitalize(), total),
          evidence_items=[evidence_item(page.final_url, "computed", "nav_elements=0; role_navigation=0; header_list_links=%d; internal_links=%d" % (
              work["navigation"]["header_list_links"], total))],
          why="A visitor who lands mid-site orients by the navigation. Without a recognisable menu, the page reads as a dead end and the visit ends there: the bouncing mode.",
          action="Wrap the site's main links in a <nav> element in the page header, present on every page.",
          detail="A <nav aria-label=\"Main\"> containing a list of the top-level pages (product, pricing, about, contact) is enough. Verify by checking that every sampled page contains <nav.",
          pages=[page.final_url], page_roles=[page.role], references=[REFS["nav"]])


# A search box is recognised by what its markup calls it, in any of the audit's languages. Drupal names its box
# search_block_form, WordPress uses s, and many CMSs put the word only in the form id, action or placeholder: a
# name whitelist reported "no site search" on a university site with a working search box in its header.
SEARCH_WORD_RE = re.compile(r"search|suche|recherch|buscar|busca|cerca|ricerca|zoek|pesquis|搜索|検索", re.I)


def is_search_form(f):
    if f.get("role") == "search":
        return True
    if SEARCH_WORD_RE.search(" ".join([f.get("id") or "", f.get("cls") or "", f.get("label") or "",
                                       urlsplit(f.get("action") or "").path])):
        return True
    for i in f["inputs"]:
        if i["type"] == "search" or (i.get("name") or "").lower() in SEARCH_INPUT_NAMES:
            return True
        if SEARCH_WORD_RE.search(" ".join([i.get("name") or "", i.get("id") or "", i.get("placeholder") or "",
                                           i.get("label") or ""])):
            return True
    return False


def has_site_search(doc):
    if doc.search_roles > 0:
        return "role_search"
    if any(is_search_form(f) for f in doc.forms):
        return "search_form"
    return None


def check_search(ctx, out, usable, excluded, work):
    cid = "en.nav.site_search_missing"
    cap = _cap(out, cid, ctx)
    if cap is None:
        return
    page = _anchor_page(ctx, usable)
    if page is None:
        out.not_evaluated(cid, reason=dominant_reason(ctx, excluded)); return
    how = has_site_search(page.doc)
    work["site_search"] = {"page": page.final_url, "found": how}
    if how:
        out.check(cid, "pass", pages=[page.final_url]); return
    _fail(out, cid, cap,
          title="No site search on the %s page" % page.role,
          evidence="%s page: no <input type=search>, no role=search, and no form with a q/s/search/query field." % page.role.capitalize(),
          evidence_items=[evidence_item(page.final_url, "computed", "search_roles=0; search_inputs=0; forms=%d" % len(page.doc.forms))],
          why="On a site with many pages, search is how a visitor with a specific question (the kind an assistant's answer prompts) gets to it without guessing the menu.",
          action="Add a site search field to the header, present on every page.",
          detail="A <form role=\"search\"> with an <input type=\"search\" name=\"q\"> is the recognisable pattern; wire it to your platform's search page.",
          pages=[page.final_url], page_roles=[page.role])


def check_breadcrumbs(ctx, out, usable, work):
    cid = "en.nav.breadcrumbs_missing"
    cap = _cap(out, cid, ctx)
    if cap is None:
        return
    pages = [p for p in usable if p.role != "home"]
    if not pages:
        out.not_evaluated(cid, reason="only_home_sampled"); return
    have, items = [], []
    for p in pages:
        markup = p.doc.breadcrumb_markup
        ld = "BreadcrumbList" in p.doc.jsonld_types
        if markup or ld:
            have.append(p.final_url)
        items.append(evidence_item(p.final_url, "computed", "breadcrumb_markup=%s; BreadcrumbList=%s" % (markup, ld), note="%s page" % p.role))
    work["breadcrumbs"] = {"pages_with": have, "pages_checked": [p.final_url for p in pages]}
    if have:
        out.check(cid, "pass", pages=have); return
    _fail(out, cid, cap,
          title="No breadcrumbs on any of the %d secondary pages sampled" % len(pages),
          evidence="None of the %d non-home pages sampled (%s) has breadcrumb markup (a nav or list named breadcrumb) or BreadcrumbList JSON-LD." % (len(pages), ", ".join(p.role for p in pages)),
          evidence_items=items[:6],
          why="Visitors from an assistant usually land on an inner page. Breadcrumbs tell them where in the site they are and give a one-click way up; without them the inner page is an island.",
          action="Add a breadcrumb trail (with BreadcrumbList JSON-LD) to the template of every page below the home page.",
          detail="A <nav aria-label=\"Breadcrumb\"> list from Home to the current page, mirrored in BreadcrumbList structured data, is enough. Test on the deepest page type first.",
          pages=[p.final_url for p in pages], page_roles=[p.role for p in pages], references=[REFS["breadcrumb"]])


def check_related(ctx, out, usable, work):
    cid = "en.nav.related_links_missing"
    cap = _cap(out, cid, ctx)
    if cap is None:
        return
    candidates = [p for p in usable if p.role in ("product", "blog")]
    if not candidates:
        out.not_evaluated(cid, reason="no_product_or_blog_page"); return
    # onward links may point at a sibling subdomain (blog.example.com from www.example.com): same registrable domain counts
    site_domain = registrable_domain((urlsplit(ctx.site or "").hostname or "").lower())

    def _onward(doc):
        out_links = []
        for l in doc.links:
            if l.in_head or urlsplit(l.url).scheme not in ("http", "https"):
                continue
            if l.internal or (site_domain and registrable_domain((urlsplit(l.url).hostname or "").lower()) == site_domain):
                out_links.append(l)
        return out_links

    # a listing page is itself the onward navigation; only detail pages are graded
    def _listing(doc):
        listed = {l.url for l in _onward(doc) if l.in_list and l.context in ("main", "article", "aside", "body")}
        return doc.article_count >= 2 or len(listed) >= LISTING_MIN_LINKS, len(listed)
    pages = []
    for p in candidates:
        is_listing, listed = _listing(p.doc)
        if is_listing:
            work.setdefault("related_links", {})[p.final_url] = {"role": p.role, "listing": True, "articles": p.doc.article_count, "listed_links": listed}
        else:
            pages.append(p)
    if not pages:
        out.not_evaluated(cid, reason="listing_pages_only"); return
    failing, items, ok = [], [], []
    for p in pages:
        doc = p.doc
        heading = next((h["text"] for h in doc.headings if RELATED_HEADING_RE.search(h["text"] or "")), None)
        own = _norm(p.final_url)
        trailing = {l.url for l in _onward(doc) if l.context in ("main", "article", "aside", "body")
                    and doc.body_frac(l.mpos) is not None and doc.body_frac(l.mpos) >= 0.5 and _norm(l.url) != own}
        work.setdefault("related_links", {})[p.final_url] = {"role": p.role, "related_heading": heading, "trailing_internal_links": len(trailing)}
        if heading or len(trailing) >= RELATED_MIN_LINKS:
            ok.append(p.final_url)
        else:
            failing.append(p)
            items.append(evidence_item(p.final_url, "computed", "related_heading=none; trailing_internal_links=%d" % len(trailing), note="%s page" % p.role))
    if not failing:
        out.check(cid, "pass", pages=ok); return
    _fail(out, cid, cap,
          title="%s page%s offer%s no related links to continue to" % ("/".join(p.role.capitalize() for p in failing), "s" if len(failing) != 1 else "", "" if len(failing) != 1 else "s"),
          evidence="%s: no section headed related/similar/you may also like, and fewer than %d internal links in the second half of the content." % (
              ", ".join("%s page" % p.role for p in failing), RELATED_MIN_LINKS),
          evidence_items=items[:6],
          why="A visitor who finishes a product or article page needs somewhere to go next; a page that ends without related links ends the visit.",
          action="Add a related-items section at the end of %s pages with three or more links to comparable pages." % "/".join(p.role for p in failing),
          detail="Three links under a 'Related' heading, chosen by category or tag, is enough. Keep them inside the main content, not only in the footer.",
          pages=[p.final_url for p in failing], page_roles=[p.role for p in failing])


def _content_words(s):
    return {w.lower() for w in _words(s) if len(w) >= 4 and w.lower() not in STOPWORDS}


def check_continuity(ctx, out, usable, work):
    cid = "en.continuity.h1_title_mismatch"
    cap = _cap(out, cid, ctx)
    if cap is None:
        return
    failing, items, ok, host = [], [], [], (urlsplit(ctx.site or "").hostname or "").lower()
    graded = 0
    for p in usable:
        doc = p.doc
        title = (doc.title or "").strip()
        h1 = next((h for h in doc.h1s if h.strip()), None)
        if not h1 or not title or title.lower() in X.GENERIC_TITLES or title.lower() == host:
            continue  # fx.identity.* owns missing/generic titles and missing or empty h1s (dedupe row 10)
        h1w = _content_words(h1)
        tw = _content_words(title) | _content_words(doc.meta("description") or "")
        shared = sorted(h1w & tw)
        # A title or description that repeats the heading word for word matches whatever its words are; and a
        # heading made only of function words ("What we do", "Get in touch") that is not repeated has nothing
        # to compare, so it is not graded rather than failed. Measured: a corporate "What we do" page under the
        # title "What we do — Meridian Industrial Group" was reported as a mismatch.
        h1n = _norm_words(h1)
        verbatim = bool(h1n) and (h1n in _norm_words(title) or h1n in _norm_words(doc.meta("description") or ""))
        if not h1w and not verbatim:
            work.setdefault("continuity", {})[p.final_url] = {"role": p.role, "h1": h1[:120], "title": title[:120], "shared": [], "graded": False}
            continue
        graded += 1
        work.setdefault("continuity", {})[p.final_url] = {"role": p.role, "h1": h1[:120], "title": title[:120],
                                                            "shared": shared[:5] or (["(heading repeated verbatim)"] if verbatim else [])}
        if shared or verbatim:
            ok.append(p.final_url)
        else:
            failing.append(p)
            items.append(evidence_item(p.final_url, "computed", "h1=%r; title=%r; shared_words=none" % (h1[:60], title[:60]), note="%s page" % p.role))
    if not graded:
        out.not_evaluated(cid, reason="dependency_failed"); return
    if not failing:
        out.check(cid, "pass", pages=ok); return
    _fail(out, cid, cap,
          title="%s page heading does not match its title and description" % "/".join(p.role.capitalize() for p in failing),
          evidence="On %d of %d graded pages (%s) the <h1> shares no content word of four or more letters with the <title> or the meta description." % (
              len(failing), graded, ", ".join(p.role for p in failing)),
          evidence_items=items[:6],
          why="An assistant or a search result shows the title and description; the visitor arrives expecting that. A heading that says something else makes them doubt they are in the right place, and they go back.",
          action="Make the <h1> of the %s page%s restate the promise of its title and description." % ("/".join(p.role for p in failing), "s" if len(failing) != 1 else ""),
          detail="The title, description and h1 should share the same key noun. Rewrite whichever of the three is off-message; usually the h1.",
          pages=[p.final_url for p in failing], page_roles=[p.role for p in failing])


# ---------------------------------------------------------------- friction
def check_interstitial(ctx, out, usable, work):
    cid = "en.interstitial.blocking"
    cap = _cap(out, cid, ctx)
    if cap is None:
        return
    failing, items, ok = [], [], []
    for p in usable:
        doc = p.doc
        h1m = next((h.get("mpos") for h in doc.headings if h["tag"] == "h1"), None)
        hits = []
        for c in doc.overlay_candidates:
            if c.get("hidden") or (c.get("words") or 0) <= INTERSTITIAL_MIN_WORDS:
                continue
            before = (c.get("mpos") is not None and h1m is not None and c["mpos"] < h1m) or (h1m is None and (doc.body_frac(c.get("mpos")) or 1.0) <= FIRST_VIEWPORT_FRAC)
            if before:
                hits.append(c)
        work.setdefault("interstitials", {})[p.final_url] = [{"tag": c["tag"], "id": c["id"], "class": c["class"], "position": c["position"], "words": c["words"]} for c in hits]
        if hits:
            failing.append(p)
            c = hits[0]
            items.append(evidence_item(p.final_url, "html_excerpt", "<%s%s%s style=%r> %d words: %s" % (
                c["tag"], (' id="%s"' % c["id"]) if c["id"] else "", (' class="%s"' % c["class"][:40]) if c["class"] else "", (c["style"] or "")[:60], c["words"], c["text"][:100]),
                note="position:%s; before the <h1>" % (c["position"] or "not inline")))
        else:
            ok.append(p.final_url)
    if not failing:
        out.check(cid, "pass", pages=ok); return
    _fail(out, cid, cap,
          title="%s page opens with a blocking overlay before its content" % "/".join(p.role.capitalize() for p in failing),
          evidence="%s: an element named modal/overlay/popup/cookie in the served HTML, not hidden, with more than %d words, appears before the main heading." % (
              ", ".join("%s page" % p.role for p in failing), INTERSTITIAL_MIN_WORDS),
          evidence_items=items[:6],
          why="A wall of text or a sign-up box that covers the page before the visitor has read a word is the classic snap-judgement bounce, and on mobile it is often the only thing on screen.",
          action="Remove or defer the overlay on the %s page%s so the first screen is the content." % ("/".join(p.role for p in failing), "s" if len(failing) != 1 else ""),
          detail="Show newsletter or promotional dialogs after the visitor has scrolled or after a delay, never in the initial HTML above the heading. A consent notice should be a short bar, not a full-screen wall.",
          pages=[p.final_url for p in failing], page_roles=[p.role for p in failing])


def check_viewport(ctx, out, html_pages, work):
    cid = "en.mobile.viewport_missing"
    cap = _cap(out, cid, ctx)
    if cap is None:
        return
    failing, ok = [], []
    for p in html_pages:
        (ok if p.doc.meta("viewport") else failing).append(p)
    work["viewport"] = {"pages_with": [p.final_url for p in ok], "pages_without": [p.final_url for p in failing]}
    if not failing:
        out.check(cid, "pass", pages=[p.final_url for p in ok]); return
    _fail(out, cid, cap,
          title="No mobile viewport meta tag on %s" % ("any sampled page" if not ok else "the %s page%s" % ("/".join(p.role for p in failing), "s" if len(failing) != 1 else "")),
          evidence="%d of %d HTML pages (%s) have no <meta name=\"viewport\">; mobile browsers render them at desktop width and the visitor must pinch and zoom." % (
              len(failing), len(html_pages), ", ".join(p.role for p in failing)),
          evidence_items=[evidence_item(p.final_url, "computed", "meta_viewport=absent", note="%s page" % p.role) for p in failing[:6]],
          why="Most visits are on phones. Without the viewport tag the page is drawn at desktop width and shrunk to fit, which makes text unreadable at arrival; the visitor leaves before reading anything.",
          action="Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"> to the <head> of every page template.",
          detail="One line in the shared head template. Verify by fetching each page and checking the tag is present, then test on a phone.",
          pages=[p.final_url for p in failing], page_roles=[p.role for p in failing], references=[REFS["viewport"]])


def check_lang(ctx, out, html_pages, excluded, work):
    cid = "en.lang.attribute_missing"
    cap = _cap(out, cid, ctx)
    if cap is None:
        return
    home = ctx.home
    page = home if (home is not None and home in html_pages) else (html_pages[0] if html_pages else None)
    if page is None:
        out.not_evaluated(cid, reason=dominant_reason(ctx, excluded)); return
    work["lang"] = {"page": page.final_url, "lang": page.doc.lang}
    if page.doc.lang:
        out.check(cid, "pass", pages=[page.final_url]); return
    _fail(out, cid, cap,
          title="The <html> element declares no language",
          evidence="%s page: <html> has no lang attribute." % page.role.capitalize(),
          evidence_items=[evidence_item(page.final_url, "computed", "html_lang=absent")],
          why="Screen readers, translation features and some assistants use the declared language to read and render the page; without it text can be voiced or translated wrongly, which reads as a broken page.",
          action="Add lang=\"<language code>\" to the <html> element in the page template.",
          detail="For example <html lang=\"en\"> or <html lang=\"de\">. One change in the shared template.",
          pages=[page.final_url], page_roles=[page.role], references=[REFS["lang"]])


def check_weight(ctx, out, html_pages, work):
    cid = "en.perf.page_weight_heavy"
    cap = _cap(out, cid, ctx)
    if cap is None:
        return
    failing, items, ok = [], [], []
    for p in html_pages:
        doc = p.doc
        reasons = []
        if doc.html_bytes > HEAVY_HTML_BYTES:
            reasons.append("html_bytes=%d>%d" % (doc.html_bytes, HEAVY_HTML_BYTES))
        if doc.script_tags > HEAVY_SCRIPT_TAGS:
            reasons.append("script_tags=%d>%d" % (doc.script_tags, HEAVY_SCRIPT_TAGS))
        if len(doc.images) > HEAVY_IMAGES:
            reasons.append("images=%d>%d" % (len(doc.images), HEAVY_IMAGES))
        work.setdefault("page_weight", {})[p.final_url] = {"role": p.role, "html_bytes": doc.html_bytes, "script_tags": doc.script_tags,
                                                            "external_scripts": len(doc.external_scripts), "stylesheets": len(doc.stylesheets), "images": len(doc.images)}
        if reasons:
            failing.append(p)
            items.append(evidence_item(p.final_url, "computed", "%s; external_scripts=%d; stylesheets=%d" % ("; ".join(reasons), len(doc.external_scripts), len(doc.stylesheets)), note="%s page" % p.role))
        else:
            ok.append(p.final_url)
    if not failing:
        out.check(cid, "pass", pages=ok); return
    _fail(out, cid, cap,
          title="%s page is heavy by the static proxy (markup size, script and image counts)" % "/".join(p.role.capitalize() for p in failing),
          evidence="%s exceed%s a static weight threshold (HTML over %d KB, more than %d script tags, or more than %d images). This is a proxy: no load time was measured." % (
              ", ".join("%s page" % p.role for p in failing), "s" if len(failing) == 1 else "", HEAVY_HTML_BYTES // 1024, HEAVY_SCRIPT_TAGS, HEAVY_IMAGES),
          evidence_items=items[:6],
          why="Each second of delay before the first screen appears loses a measurable share of visitors, and script and image counts are the cheapest predictor of that delay a static audit can see.",
          action="Measure the %s page's load time with a browser performance tool and trim the largest scripts and images." % "/".join(p.role for p in failing),
          detail="Run a Lighthouse or WebPageTest report on the page. Defer non-critical scripts, lazy-load below-the-fold images, and remove unused tags. Re-run this audit to confirm the counts drop.",
          pages=[p.final_url for p in failing], page_roles=[p.role for p in failing], confidence="low")


# ---------------------------------------------------------------- trust
def detect_trust_signals(ctx, pages):
    docs = [p.doc for p in pages]

    def link_match(rx):
        for p in pages:
            for l in p.doc.links:
                if l.in_head:
                    continue
                if rx.search(l.text or "") or rx.search(urlsplit(l.url).path or ""):
                    return {"page": p.final_url, "value": (l.text or l.url)[:80], "source": "link"}
        return None

    def text_match(rx):
        for p in pages:
            t = p.doc.body_text or ""
            m = rx.search(t)
            if m:
                return {"page": p.final_url, "value": t[max(0, m.start() - 30):m.end() + 40].strip()[:120], "source": "text"}
        return None

    def heading_match(rx):
        for p in pages:
            for h in p.doc.headings:
                if rx.search(h["text"] or ""):
                    return {"page": p.final_url, "value": h["text"][:80], "source": "heading"}
        return None

    def image_match(rx):
        for p in pages:
            for im in p.doc.images:
                blob = "%s %s" % (im.get("alt") or "", urlsplit(im.get("src") or "").path.rsplit("/", 1)[-1])
                if rx.search(blob):
                    return {"page": p.final_url, "value": blob.strip()[:80], "source": "image"}
        return None

    def _f(found):
        return {"page": found["page"], "value": (found.get("value") or "")[:120], "source": found.get("source")} if found else None

    quotes = next(({"page": p.final_url, "value": q["text"][:100], "source": "blockquote"} for p in pages for q in p.doc.blockquotes if q["words"] >= 8), None)
    reviews_ld = next(({"page": p.final_url, "value": t, "source": "jsonld"} for p in pages for t in p.doc.jsonld_types if t in ("AggregateRating", "Review")), None)
    pricing_page = ctx.page("pricing")
    pricing_ok = None
    if pricing_page is not None and pricing_page.ok_html and pricing_page.doc.price_mentions:
        pricing_ok = {"page": pricing_page.final_url, "value": pricing_page.doc.price_mentions[0], "source": "pricing_page"}
    people = heading_match(TEAM_RE) or link_match(TEAM_RE) or text_match(X.LEADERSHIP_RE)
    sig = {
        "terms_privacy_links": link_match(TERMS_PRIVACY_RE),
        "returns_policy_link": link_match(RETURNS_RE),
        "payment_or_security_badge": image_match(BADGE_RE) or text_match(BADGE_RE),
        "review_markup_or_count": reviews_ld or text_match(REVIEW_RE),
        "address": _f(X.find_address(pages)),
        "phone": _f(X.find_phone(pages)),
        "opening_hours": _f(X.find_hours(pages)),
        "premises_photos": image_match(PREMISES_IMG_RE),
        "testimonials_or_logos": quotes or heading_match(TESTIMONIAL_RE) or text_match(TESTIMONIAL_RE),
        "security_or_compliance_link": link_match(SECURITY_RE),
        "pricing_transparency": _f(X.find_price(pages)) or pricing_ok,
        "team_named_people": people,
        "named_people": people,
        "clients_or_case_studies": heading_match(CLIENTS_RE) or link_match(CLIENTS_RE),
        "credentials": text_match(CREDENTIALS_RE),
        "registration_number": text_match(REG_NUMBER_RE),
        "financial_report_link": link_match(FINANCIAL_RE) or text_match(FINANCIAL_RE),
        "named_leadership": text_match(X.LEADERSHIP_RE) or heading_match(TEAM_RE),
    }
    return sig


def check_trust(ctx, out, usable, work):
    cid = "en.trust.signals_missing"
    cap = _cap(out, cid, ctx)
    if cap is None:
        return
    pages = [p for p in usable if p.role in ("home", "about", "contact")]
    if not pages:
        out.not_evaluated(cid, reason="no_anchor_pages_usable"); return
    sig = detect_trust_signals(ctx, pages)
    if ctx.category in TRUST_SIGNALS:
        expected = TRUST_SIGNALS[ctx.category]
        present = [s for s in expected if sig.get(s)]
        passed = bool(present)
        rule = "any of %s" % ", ".join(expected)
    else:
        req, any_of = TRUST_SIGNALS_DEFAULT["required"], TRUST_SIGNALS_DEFAULT["any_of"]
        expected = req + any_of
        present = [s for s in expected if sig.get(s)]
        passed = all(sig.get(s) for s in req) and any(sig.get(s) for s in any_of)
        rule = "%s plus any of %s" % (", ".join(req), ", ".join(any_of))
    missing = [s for s in expected if not sig.get(s)]
    work["trust_signals"] = {"category": ctx.category, "rule": rule, "expected": expected, "present": {s: sig[s] for s in present},
                             "missing": missing, "pages_checked": [p.final_url for p in pages]}
    if passed:
        out.check(cid, "pass", pages=[p.final_url for p in pages]); return
    items = [evidence_item(sig[s]["page"], "text_excerpt", sig[s]["value"], note="%s found (%s)" % (s, sig[s]["source"])) for s in present[:3]]
    items.append(evidence_item("site", "computed", "pages_checked=%s; rule=%s; present=%s; missing=%s" % (
        ",".join(p.role for p in pages), rule, ",".join(present) or "none", ",".join(missing))))
    _fail(out, cid, cap,
          title="None of the trust signals expected of %s is visible on the home, about or contact page" % category_label(ctx.category)
          if not present else "Trust signals on the home, about and contact pages fall short of what %s needs" % category_label(ctx.category),
          evidence="Checked %s for %s: found %s." % (", ".join(p.role for p in pages), rule, ", ".join(present) or "none of them"),
          evidence_items=items,
          why="A visitor deciding whether to stay looks for proof that others trust the site: names, addresses, reviews, policies. When the pages they land on show none, the offer reads as unverified and they go back to the assistant.",
          action="Add the missing trust signals to the home, about and contact pages: %s." % ", ".join(s.replace("_", " ") for s in missing[:4]),
          detail="Start with the cheapest: a footer line with the legal name and address, links to terms and privacy, and one or two named customer quotes or logos with permission.",
          pages=[p.final_url for p in pages], page_roles=[p.role for p in pages])


# ---------------------------------------------------------------- reliability (network)
def sample_links(ctx, usable):
    """Up to LINK_SAMPLE_MAX unique internal links: nav first, then header, body, aside, footer; home page first."""
    home = ctx.home
    ordered = ([home] if home is not None and home in usable else []) + [p for p in usable if p is not home]
    cands = []
    for pi, p in enumerate(ordered):
        own = _norm(p.final_url)
        for li, l in enumerate(p.doc.internal_links):
            if urlsplit(l.url).scheme not in ("http", "https"):
                continue
            key = _norm(l.url)
            if not key or key == own:
                continue
            cands.append((CONTEXT_RANK.get(l.context, 3), pi, li, key, l.url, (l.text or "")[:60], l.context, p.final_url))
    cands.sort(key=lambda c: c[:3])
    seen, sample = set(), []
    for rank, pi, li, key, url, text, context, src in cands:
        if key in seen:
            continue
        seen.add(key)
        sample.append({"url": url, "key": key, "text": text, "context": context, "linked_from": src})
        if len(sample) >= LINK_SAMPLE_MAX:
            break
    return sample


def classify_fetch(r):
    """`transport_error` (DNS/TLS/timeout/refused) is deliberately distinct from `broken`: it says the
    audit's own fetcher could not complete the request, not that the site answered with 404/410/5xx.
    check_links retries a transport error once before accepting the verdict, and never counts a transport
    error as a broken link -- a python.org page that returned 200 to a normal request was once reported
    broken because this audit's own connection to it saw a TLS error."""
    if r.get("skipped"):
        return "skipped"
    if r.get("challenge"):
        return "blocked"
    err = r.get("error")
    if err in TRANSPORT_ERRORS:
        return "transport_error"
    if err:
        return "error"
    st = r.get("status")
    if st in (404, 410) or (st or 0) >= 500:
        return "broken"
    if st in (403, 429):
        return "blocked"
    return "ok"


def check_links(ctx, out, fetcher, usable, excluded, work, deadline):
    known = {}
    for p in ctx.pages:
        for u in (p.url, p.final_url):
            if u:
                known[_norm(u)] = p.fetch
    sample = sample_links(ctx, usable)
    if not sample:
        reason = dominant_reason(ctx, excluded) if not usable else "no_internal_links"
        out.not_evaluated("en.links.broken_sampled", reason=reason)
        out.not_evaluated("en.links.blocked_cluster", reason=reason)
        work["link_sample"] = []
        return
    requested = 0
    for s in sample:
        if s["key"] in known:
            r = known[s["key"]]
            s["source"] = "sampled_page"
        elif time.monotonic() > deadline:
            s.update({"source": "not_checked", "verdict": "not_checked", "status": None, "error": "time_budget"})
            continue
        else:
            r = fetcher.get(s["url"], purpose="link_sample", timeout=LINK_TIMEOUT)
            requested += 1
            s["source"] = "request"
        s["status"] = r.get("status")
        s["error"] = r.get("error")
        s["skipped"] = r.get("skipped")
        s["verdict"] = classify_fetch(r)
        # A transport error (DNS/TLS/timeout/refused) says the audit's own request failed to complete, not
        # that the site is broken -- python.org's /downloads/ios/ returned 200 to a normal request after
        # this audit's first attempt saw a tls_error. One retry before the verdict stands.
        if s["verdict"] == "transport_error" and s["source"] == "request" and time.monotonic() <= deadline:
            r = fetcher.get(s["url"], purpose="link_sample_retry", timeout=LINK_TIMEOUT)
            requested += 1
            s["status"], s["error"], s["skipped"] = r.get("status"), r.get("error"), r.get("skipped")
            s["verdict"] = classify_fetch(r)
    blocked = [s for s in sample if s.get("verdict") == "blocked"]
    by_host = {}
    for s in blocked:
        by_host.setdefault((urlsplit(s["url"]).hostname or "").lower(), []).append(s)
    cluster = [s for h, ss in by_host.items() if len(ss) >= BLOCKED_CLUSTER_MIN for s in ss]
    broken = [s for s in sample if s.get("verdict") == "broken"]
    transport = [s for s in sample if s.get("verdict") == "transport_error"]
    counts = {v: sum(1 for s in sample if s.get("verdict") == v) for v in ("ok", "broken", "blocked", "skipped", "error", "transport_error", "not_checked")}
    work["link_sample"] = sample
    work["link_summary"] = {"sampled": len(sample), "requested": requested, "blocked_cluster": len(cluster), **counts}
    summary = "sampled=%d; requested=%d; ok=%d; broken=%d; blocked=%d; transport_error=%d; skipped=%d; not_checked=%d" % (
        len(sample), requested, counts["ok"], counts["broken"], counts["blocked"], counts["transport_error"],
        counts["skipped"], counts["not_checked"] + counts["error"])
    if cluster:
        host = (urlsplit(cluster[0]["url"]).hostname or "").lower()
        out.inconclusive("en.links.blocked_cluster", reason="fetcher_blocked",
                         title="%d sampled internal links answered 403/429 to the audit's fetcher" % len(cluster),
                         evidence="%d of %d sampled internal links on %s returned 403 or 429 (or a bot challenge) to this audit's plain GET; that is a fetcher block, not broken links, and it likely affects AI crawlers too." % (
                             len(cluster), len(sample), host),
                         evidence_items=[evidence_item(s["linked_from"], "http_status", "GET %s -> %s" % (_short(s["url"]), s.get("status") or s.get("error")), note="%s link" % s["context"]) for s in cluster[:6]]
                                        + [evidence_item("site", "computed", summary)],
                         why="Links that reject a low-volume automated reader are not broken for a person, so they are not counted as broken; but assistants fetching at answer time see the same refusal, so the block itself deserves a look.",
                         action="Check the WAF or rate-limit rules for the paths listed and allow verified crawlers and low-volume readers through.",
                         detail="Compare the rules applied to these paths with the ones for the pages that were served normally; vendors publish verified-bot lists that can be allowed without opening the site to abuse.")
    else:
        out.check("en.links.blocked_cluster", "pass")
    if broken:
        out.fail("en.links.broken_sampled",
                 title="%d of %d sampled internal links %s broken" % (len(broken), len(sample), "is" if len(broken) == 1 else "are"),
                 evidence="Of %d internal links sampled (navigation first, then body and footer), %d returned 404/410 or a server error: %s." % (
                     len(sample), len(broken), "; ".join("%s -> %s" % (_short(s["url"], 50), s.get("status") or s.get("error")) for s in broken[:3])),
                 evidence_items=[evidence_item(s["linked_from"], "http_status", "GET %s -> %s" % (_short(s["url"]), s.get("status") or s.get("error")), note="%s link '%s'" % (s["context"], s["text"][:40])) for s in broken[:8]]
                                + [evidence_item("site", "computed", summary)],
                 why="A dead link is the fastest way to lose a visitor who was following the site's own suggestion, and a page the site links to but cannot serve is invisible to assistants as well.",
                 action="Fix or remove the %d broken link%s listed, starting with the ones in the navigation." % (len(broken), "s" if len(broken) != 1 else ""),
                 detail="Point each link at the current page, or redirect the old URL (301) to it. Re-run the audit; the sample is deterministic, so the same links are checked again.",
                 pages=[], page_roles=[])
    elif transport:
        out.inconclusive("en.links.broken_sampled", reason="fetcher_error",
                         title="%d of %d sampled internal links did not answer this audit's fetcher, twice" % (len(transport), len(sample)),
                         evidence="Of %d internal links sampled, %d failed at the transport level (DNS, TLS, timeout or connection refused) on both this audit's attempts, with no 404/410/5xx from the site itself: %s. A transport failure is not evidence the link is broken; it may be this fetcher, this network, or a momentary problem at the origin." % (
                             len(sample), len(transport), "; ".join("%s -> %s" % (_short(s["url"], 50), s.get("error")) for s in transport[:3])),
                         evidence_items=[evidence_item(s["linked_from"], "http_status", "GET %s -> %s" % (_short(s["url"]), s.get("error")), note="%s link '%s'" % (s["context"], s["text"][:40])) for s in transport[:8]]
                                        + [evidence_item("site", "computed", summary)],
                         why="Counting a transport failure as a broken link risks blaming the site for this audit's own connection; a person's browser or a search crawler with a different network path may see the page just fine.",
                         action="Fetch each listed URL yourself (curl -I) to see whether it is actually reachable.",
                         detail="If curl also fails, treat it as broken and fix or remove the link. If curl succeeds, this audit's network path to that host was the problem, not the site.")
    else:
        out.check("en.links.broken_sampled", "pass")


def check_404(ctx, out, fetcher, work):
    site = (ctx.site or "").rstrip("/")
    path = "/brand-ai-readiness-audit-404-probe-" + hashlib.sha1(site.encode("utf-8")).hexdigest()[:10]
    url = site + path
    r = fetcher.get(url, purpose="404_probe", timeout=LINK_TIMEOUT)
    rec = {"url": url, "status": r.get("status"), "final_url": r.get("final_url"), "redirects": len(r.get("redirect_chain") or []),
           "error": r.get("error"), "skipped": r.get("skipped"), "challenge": r.get("challenge"), "is_html": r.get("is_html"), "verdict": None}
    work["probe_404"] = rec
    soft, unhelp = "en.errors.soft_404", "en.errors.unhelpful_404"
    if r.get("skipped"):
        out.not_evaluated(soft, reason="robots_disallow"); out.not_evaluated(unhelp, reason="robots_disallow"); rec["verdict"] = "skipped"; return
    if r.get("challenge"):
        out.not_evaluated(soft, reason="challenge_page"); out.not_evaluated(unhelp, reason="challenge_page"); rec["verdict"] = "challenge"; return
    if r.get("error"):
        reason = "network_disabled" if r["error"] == "network_disabled" else "fetch_error"
        out.not_evaluated(soft, reason=reason); out.not_evaluated(unhelp, reason=reason); rec["verdict"] = "error"; return
    st = r.get("status")
    if st == 200 and r.get("is_html"):
        rec["verdict"] = "soft_404"
        doc = Document(r.text, base_url=r.get("final_url") or url)
        redirected = " after %d redirect%s to %s" % (rec["redirects"], "s" if rec["redirects"] != 1 else "", _short(r.get("final_url") or "", 60)) if rec["redirects"] else ""
        out.fail(soft,
                 title="Missing pages return 200 instead of 404 (soft 404)",
                 evidence="GET %s (a path that cannot exist) returned HTTP 200 with an HTML page titled %r%s." % (_short(path, 70), (doc.title or "")[:60], redirected),
                 evidence_items=[evidence_item(url, "http_status", "GET %s -> 200 %s" % (path, r.get("content_type") or ""), note="final_url=%s" % r.get("final_url")),
                                 evidence_item(url, "html_excerpt", "<title>%s</title>" % (doc.title or ""), location="head > title")],
                 why="A visitor who follows a stale link gets a page that looks like the site but is not what they wanted, with no signal that anything is wrong; crawlers index the same nothing-page under every dead URL, diluting the real pages.",
                 action="Return HTTP 404 (or 410) for paths that do not exist, with a helpful not-found page.",
                 detail="Configure the server or framework's catch-all to send a 404 status with the not-found template rather than serving the home page or redirecting to it. Verify with curl -I on a random path.",
                 pages=[], page_roles=[], references=[REFS["soft404"]])
        out.not_evaluated(unhelp, reason="soft_404")
        return
    if st in (404, 410):
        rec["verdict"] = "real_404"
        out.check(soft, "pass")
        doc = Document(r.text, base_url=url) if r.get("is_html") and r.text else None
        home_link = nav = search = False
        if doc is not None:
            root = _norm(site)
            home_link = any(_norm(l.url) == root for l in doc.internal_links) or any((l.href or "").strip() in ("/", site, site + "/") for l in doc.links)
            nav = bool(has_nav_landmark(doc))
            search = bool(has_site_search(doc))
        rec.update({"home_link": home_link, "nav": nav, "search": search, "title": doc.title if doc else None})
        if home_link or nav or search:
            out.check(unhelp, "pass"); return
        out.fail(unhelp,
                 title="The not-found page offers no way onward",
                 evidence="GET %s returned %d; the page (%s) has no link to the home page, no navigation landmark, and no search field." % (
                     _short(path, 60), st, ("titled %r" % (doc.title or "")[:50]) if doc is not None else "not HTML"),
                 evidence_items=[evidence_item(url, "http_status", "GET %s -> %d" % (path, st)),
                                 evidence_item(url, "computed", "home_link=false; nav_landmark=false; search=false; words=%d" % (doc.word_count if doc else 0))],
                 why="Visitors reach dead URLs from old links and assistant answers. A bare not-found page ends the visit; one with the site's navigation and a search box keeps it going.",
                 action="Give the 404 page the site's header, a link to the home page, and a search field.",
                 detail="Use the normal page template for the not-found route so the navigation and search are present, add a short apology and links to the most visited pages. Keep the 404 status.",
                 pages=[], page_roles=[])
        return
    rec["verdict"] = "unexpected_%s" % st
    out.not_evaluated(soft, reason="unexpected_status")
    out.not_evaluated(unhelp, reason="unexpected_status")


# ---------------------------------------------------------------- output file
def write_work(ctx, work):
    if not ctx.workdir:
        return None
    path = os.path.join(ctx.workdir, ENGAGEMENT_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(work, f, indent=2, ensure_ascii=False, default=str)
    return ENGAGEMENT_REL


def _all_not_evaluated(out, reason):
    out.fill_unreported("en.", status="not_evaluated")
    for c in out.checks:
        if c["status"] == "not_evaluated" and "reason" not in c:
            c["reason"] = reason


# ---------------------------------------------------------------- main
def run(ctx, args=None):
    out = ProbeOutput(PROBE, ctx.site, ctx.category, [], total_sampled_pages=len(ctx.pages))
    network = _network_enabled(ctx, args)
    work = {"site": ctx.site, "site_category": ctx.category, "extracted_at": _now(), "network": network, "requests_made": 0}
    if ctx.error:
        out.error = ctx.error
        _all_not_evaluated(out, "context_error")
        return out
    usable, html_pages, excluded = classify_pages(ctx)
    out.pages_examined = [p.final_url for p in usable]
    work["pages_used"] = [p.final_url for p in usable]
    work["pages_rendered_or_not"] = [p.final_url for p in html_pages]
    work["pages_excluded"] = [{"role": p.role, "url": p.final_url, "reason": r} for p, r in excluded]
    home = ctx.home
    if home is not None and home.skipped == "robots_disallow":
        _all_not_evaluated(out, "robots_disallow")
        try:
            rel = write_work(ctx, work)
            if rel:
                out.artifacts["engagement"] = rel
        except Exception as e:  # noqa: BLE001
            out.error = "engagement file: %s" % e
        return out
    reason = dominant_reason(ctx, excluded) if not usable else None
    content_checks = (("hero", check_hero, (ctx, out, usable, excluded, work)), ("cta", check_cta, (ctx, out, usable, work)),
                      ("landmark", check_landmark, (ctx, out, usable, excluded, work)), ("search", check_search, (ctx, out, usable, excluded, work)),
                      ("breadcrumbs", check_breadcrumbs, (ctx, out, usable, work)), ("related", check_related, (ctx, out, usable, work)),
                      ("trust", check_trust, (ctx, out, usable, work)), ("continuity", check_continuity, (ctx, out, usable, work)),
                      ("interstitial", check_interstitial, (ctx, out, usable, work)))
    content_ids = ("en.hero.value_prop_unclear", "en.cta.missing", "en.nav.landmark_missing", "en.nav.site_search_missing", "en.nav.breadcrumbs_missing",
                   "en.nav.related_links_missing", "en.trust.signals_missing", "en.continuity.h1_title_mismatch", "en.interstitial.blocking")
    if usable:
        for name, fn, a in content_checks:
            try:
                fn(*a)
            except Exception as e:  # noqa: BLE001
                out.error = ((out.error or "") + " %s checks: %s: %s" % (name, type(e).__name__, e)).strip()
    else:
        for cid in content_ids:
            out.not_evaluated(cid, reason=reason)
    head_checks = (("viewport", check_viewport, (ctx, out, html_pages, work)), ("lang", check_lang, (ctx, out, html_pages, excluded, work)),
                   ("weight", check_weight, (ctx, out, html_pages, work)))
    if html_pages:
        for name, fn, a in head_checks:
            try:
                fn(*a)
            except Exception as e:  # noqa: BLE001
                out.error = ((out.error or "") + " %s checks: %s: %s" % (name, type(e).__name__, e)).strip()
    else:
        for cid in ("en.mobile.viewport_missing", "en.lang.attribute_missing", "en.perf.page_weight_heavy"):
            out.not_evaluated(cid, reason=reason)
    network_ids = ("en.links.broken_sampled", "en.links.blocked_cluster", "en.errors.soft_404", "en.errors.unhelpful_404")
    if not network:
        for cid in network_ids:
            out.not_evaluated(cid, reason="network_disabled")
        out.not_evaluated("en.links.broken_sampled", reason="network_disabled", emit_finding=True,
                          title="Link health and 404 behaviour not checked (network disabled)",
                          evidence="The link sample (up to %d internal links) and the 404 probe make live requests; this run had the network switched off, so en.links.* and en.errors.* were not evaluated." % LINK_SAMPLE_MAX,
                          evidence_items=[evidence_item("site", "computed", "network=disabled; link_sample=0; probe_404=not_run")],
                          why="Without them the report says nothing about broken links or soft 404s; that is a limitation of this run, not a finding about the site.",
                          action="Re-run without --offline / --no-network to complete the reliability checks.",
                          detail="The checks spend at most %d requests under the shared fetch policy and robots.txt." % (LINK_SAMPLE_MAX + 1))
    elif not html_pages:
        for cid in network_ids:
            out.not_evaluated(cid, reason=reason)
    else:
        fetcher = ctx.fetcher or Fetcher(workdir=ctx.workdir, site=ctx.site, time_budget=NETWORK_TIME_BUDGET + 20)
        before = fetcher.requests_made
        deadline = time.monotonic() + NETWORK_TIME_BUDGET
        for name, fn, a in (("links", check_links, (ctx, out, fetcher, usable, excluded, work, deadline)), ("errors", check_404, (ctx, out, fetcher, work))):
            try:
                fn(*a)
            except Exception as e:  # noqa: BLE001
                out.error = ((out.error or "") + " %s checks: %s: %s" % (name, type(e).__name__, e)).strip()
        work["requests_made"] = fetcher.requests_made - before
    out.fill_unreported("en.", status="not_evaluated")
    for c in out.checks:
        if c["status"] == "not_evaluated" and "reason" not in c:
            c["reason"] = "dependency_failed"
    try:
        rel = write_work(ctx, work)
        if rel:
            out.artifacts["engagement"] = rel
    except Exception as e:  # noqa: BLE001
        out.error = ((out.error or "") + " engagement file: %s" % e).strip()
    return out


def _extra_args(ap):
    ap.add_argument("--no-network", action="store_true", help="skip the link sample and the 404 probe (also BRAND_AUDIT_NETWORK=0)")


def main(argv=None):
    return probe_main(PROBE, run, __doc__, argv, extra_args=_extra_args)


if __name__ == "__main__":
    sys.exit(main())
