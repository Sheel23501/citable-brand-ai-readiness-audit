"""Page sampler and site categorizer. Implements fetch_policy.md section 8 and site_categories.md sections 1-3.

    from auditlib.fetch import Fetcher
    from auditlib.sampler import sample_site
    f = Fetcher(workdir="audit-x", site="https://example.com")
    manifest = sample_site(f, "https://example.com")

Takes at most 6 pages: home always, then one per role (about, contact, pricing,
product, blog) found by nav keywords first, then sitemap URL patterns. Saves
each page as snapshots/<role>.html and returns the sample manifest dict.
Never raises.
"""
import datetime as _dt
import json
import os
import re
import zlib
from urllib.parse import urlsplit, urljoin

from .fetch import PROBE_USER_AGENTS, normalize_url, origin_of, registrable_domain
from .htmldoc import Document

MAX_PAGES = 6
ROLE_ORDER = ("about", "contact", "pricing", "product", "blog")

# site_categories.md section 3 (English) + section 2 non-English rows. Keep in sync with the markdown.
ROLE_KEYWORDS = {
    "about": ["about", "about us", "company", "who we are", "our story", "team", "über uns", "ueber uns", "à propos",
              "a propos", "sobre nosotros", "chi siamo", "quiénes somos", "quienes somos"],
    "contact": ["contact", "contact us", "get in touch", "support", "help", "kontakt", "contacto", "contatti"],
    "pricing": ["pricing", "plans", "prices", "rates", "fees", "preise", "prix", "precios", "prezzi", "tarifs"],
    "product": ["products", "product", "services", "solutions", "features", "shop", "menu", "programs", "what we do",
                "produkte", "produits", "productos", "boutique", "tienda", "leistungen"],
    "blog": ["blog", "news", "newsroom", "press", "insights", "articles", "latest", "journal", "aktuelles",
             "actualités", "actualites", "noticias", "presse"],
}
ROLE_SLUGS = {
    "about": ["about", "about-us", "company", "team", "ueber-uns", "uber-uns", "a-propos", "sobre-nosotros", "chi-siamo"],
    "contact": ["contact", "contact-us", "support", "kontakt", "contacto", "contatti"],
    "pricing": ["pricing", "plans", "prices", "preise", "prix", "precios", "prezzi", "tarifs"],
    "product": ["products", "product", "services", "solutions", "features", "collections", "shop", "menu", "programs",
                "produkte", "produits", "productos", "leistungen"],
    "blog": ["blog", "news", "newsroom", "press", "insights", "articles", "journal", "aktuelles", "actualites", "noticias", "presse"],
}
ROLE_SITEMAP_PATTERNS = {
    "about": ["/about", "/company", "/team"],
    "contact": ["/contact", "/support"],
    "pricing": ["/pricing", "/plans"],
    "product": ["/products/", "/services/", "/solutions/", "/collections/", "/menu", "/product", "/services", "/features"],
    "blog": ["/blog", "/news", "/press", "/insights"],
}
CONTEXT_RANK = {"nav": 0, "header": 1, "main": 2, "body": 3, "article": 3, "aside": 4, "form": 4, "footer": 5, "head": 9}

# ------------------------------------------------------------------ categories (site_categories.md section 1-2)
CATEGORY_ORDER = ["ecommerce", "saas_software", "local_business", "professional_services", "publisher_media",
                  "portfolio_personal", "nonprofit_institution", "corporate_enterprise"]
CATEGORY_SIGNALS = {
    "ecommerce": {
        "jsonld": ["Product", "Offer", "AggregateOffer", "OnlineStore"],
        "nav": ["cart", "checkout", "shop", "collections", "basket", "boutique", "tienda", "warenkorb", "panier"],
        "url": ["/products/", "/collections/", "/cart", "/checkout", "/shop/"],
        "tld": [],
    },
    "saas_software": {
        "jsonld": ["SoftwareApplication", "WebApplication", "MobileApplication", "SoftwareSourceCode"],
        "nav": ["pricing", "features", "docs", "documentation", "api", "integrations", "sign up", "signup", "log in",
                "login", "demo", "free trial", "trial", "start free", "developers", "changelog"],
        "url": ["/pricing", "/docs", "/api", "/integrations", "/signup", "/login", "/features"],
        "tld": ["io", "app", "dev"],
    },
    "local_business": {
        # LocalBusiness is the schema.org parent of ProfessionalService, Store, Restaurant, ...: a site that declares only
        # the parent has said "a business with premises", not which kind, so it scores as generic (2), not specific (3)
        "jsonld_generic": ["LocalBusiness"],
        "jsonld": ["Restaurant", "Store", "Dentist", "Physician", "MedicalClinic", "Hotel", "LodgingBusiness",
                   "FoodEstablishment", "CafeOrCoffeeShop", "Bakery", "BarOrPub", "AutoRepair", "HairSalon", "BeautySalon",
                   "HealthAndBeautyBusiness", "HomeAndConstructionBusiness", "Plumber", "Electrician", "RealEstateAgent",
                   "SportsActivityLocation", "ExerciseGym", "AutomotiveBusiness", "ChildCare", "DryCleaningOrLaundry",
                   "EmergencyService", "EntertainmentBusiness", "FinancialService", "GovernmentOffice", "LegalService",
                   "Library", "MedicalBusiness", "ShoppingCenter", "TravelAgency", "VeterinaryCare"],
        "nav": ["directions", "hours", "opening hours", "book", "book now", "reservations", "menu", "locations", "visit",
                "find us", "öffnungszeiten", "horaires", "horario", "orari"],
        "url": ["/menu", "/locations", "/hours", "/book", "/reservations", "/directions"],
        "tld": [],
    },
    "professional_services": {
        "jsonld": ["ProfessionalService", "Attorney", "AccountingService", "Consultant", "LegalService", "InsuranceAgency",
                   "EmploymentAgency", "Notary", "AdvertisingAgency", "MarketingAgency", "DesignAgency"],
        "nav": ["services", "clients", "case studies", "our work", "work", "expertise", "practice areas", "team",
                "leistungen", "referenzen", "servicios", "servizi"],
        "url": ["/services/", "/case-studies", "/clients", "/our-work", "/expertise", "/practice-areas"],
        "tld": [],
    },
    "publisher_media": {
        "jsonld": ["NewsArticle", "Article", "BlogPosting", "NewsMediaOrganization", "Periodical", "ReportageNewsArticle"],
        "nav": ["news", "latest", "sections", "subscribe", "newsletter", "aktuelles", "actualités", "noticias"],
        # section names: any one of these is an ordinary word; two or more together are a newspaper's masthead
        "nav_cluster": {"members": ["world", "business", "politics", "sport", "sports", "culture", "opinion",
                                    "wirtschaft", "politik", "monde", "économie", "mundo", "economía"], "min": 2},
        "url": ["/news/", "/article/", "/articles/", "/opinion/", "/section/", "/category/", "/tag/"],
        "tld": ["news", "media"],
    },
    "portfolio_personal": {
        "jsonld": ["Person"],
        "nav": ["work", "projects", "about me", "resume", "cv", "portfolio", "hire me", "my work"],
        "url": ["/projects/", "/work/", "/portfolio", "/resume", "/cv"],
        "tld": ["me"],
    },
    "nonprofit_institution": {
        "jsonld": ["NGO", "EducationalOrganization", "GovernmentOrganization", "CollegeOrUniversity", "School",
                   "HighSchool", "ElementarySchool", "Preschool", "FundingAgency", "Church", "PlaceOfWorship", "GovernmentService"],
        "nav": ["donate", "mission", "programs", "admissions", "volunteer", "members", "membership", "get involved",
                "our impact", "students", "faculty", "spenden", "faire un don", "donar"],
        "url": ["/donate", "/mission", "/programs", "/admissions", "/volunteer", "/get-involved"],
        "tld": ["org", "edu", "gov", "ac", "int"],
    },
    "corporate_enterprise": {
        "jsonld": ["Corporation"],
        "nav": ["investors", "investor relations", "careers", "newsroom", "press", "leadership", "sustainability",
                "governance", "esg", "our brands", "businesses", "karriere", "investisseurs", "inversores"],
        "url": ["/investors", "/careers", "/newsroom", "/leadership", "/sustainability", "/brands/"],
        "tld": [],
    },
}
SCORE_CAPS = {"jsonld": 3, "jsonld_generic": 2, "nav": 4, "url": 2, "tld": 1}
THRESHOLD = 3
NAV_LABEL_MAX_WORDS = 4   # a nav keyword must be a menu label; a category word inside a headline is not a signal
# tiebreak order of evidence: a self-declared JSON-LD type beats menu labels, which beat URL patterns, which beat
# the TLD and the count rules
_SIGNAL_RANK = {"jsonld": 3, "nav": 2, "section": 2, "url": 1, "tld": 0, "pages": 0, "prices": 0}


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_text(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _slug_parts(url):
    path = urlsplit(url).path.lower().strip("/")
    return [p for p in path.split("/") if p]


def _keyword_hit(text, keywords, max_words=None):
    """Whole-phrase match: keyword equals the text, or appears as a whole word/phrase inside short link text.
    `max_words` limits the match to menu-length labels: a category word inside a headline is not a signal."""
    t = _norm_text(text)
    if not t or len(t) > 60:
        return None
    if max_words and len(t.split()) > max_words:
        return None
    for k in keywords:
        if t == k or re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", t):
            return k
    return None


# ------------------------------------------------------------------ sitemap
def _parse_sitemap(body):
    """Return (kind, locs) where kind is 'urlset' | 'sitemapindex' | None."""
    if not body:
        return None, []
    if body[:2] == b"\x1f\x8b":
        try:
            body = zlib.decompress(body, 16 + zlib.MAX_WBITS)
        except zlib.error:
            return None, []
    try:
        text = body.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None, []
    head = text[:2000].lower()
    kind = "sitemapindex" if "<sitemapindex" in head else ("urlset" if "<urlset" in head else None)
    if kind is None:
        # plain-text sitemap: one URL per line
        lines = [l.strip() for l in text.splitlines() if l.strip().startswith("http")]
        return ("urlset", lines) if lines and "<" not in text[:200] else (None, [])
    locs = [re.sub(r"\s+", "", m) for m in re.findall(r"<loc>\s*(.*?)\s*</loc>", text, re.S | re.I)]
    locs = [l.replace("&amp;", "&") for l in locs]
    return kind, locs


def discover_sitemap(fetcher, origin, robots):
    """Follow fetch_policy: robots Sitemap lines first, else /sitemap.xml then /sitemap_index.xml. <= 2 requests."""
    candidates = list(robots.sitemaps) if robots.state == "ok" and robots.sitemaps else []
    candidates = [c for c in candidates if urlsplit(c).scheme in ("http", "https")]
    if not candidates:
        candidates = [origin + "/sitemap.xml", origin + "/sitemap_index.xml"]
    result = {"state": "missing", "url": None, "url_count": 0, "urls": [], "path": None, "from_robots": bool(robots.sitemaps)}
    budget = 2
    tried = []
    for cand in candidates:
        if budget <= 0:
            break
        r = fetcher.get(cand, purpose="sitemap", save_as="fetch/sitemap.xml")
        budget -= 1
        tried.append(cand)
        if r.get("skipped"):
            result.update(state="missing", url=cand, skipped=r["skipped"])
            continue
        if r.get("challenge"):
            result.update(state="challenge", url=cand)
            break
        if r.get("error") or (r.get("status") or 0) >= 500:
            result.update(state="unreachable", url=cand, error=r.get("error"))
            continue
        if r.get("status") != 200:
            continue
        kind, locs = _parse_sitemap(r.body)
        if kind is None:
            result.update(state="invalid", url=cand, path=r.get("body_path"))
            continue
        if kind == "sitemapindex":
            result.update(state="ok", url=cand, path=r.get("body_path"), index_children=len(locs))
            if locs and budget > 0:
                child = fetcher.get(locs[0], purpose="sitemap", save_as="fetch/sitemap_child.xml")
                budget -= 1
                tried.append(locs[0])
                if child.get("status") == 200 and not child.get("challenge"):
                    k2, locs2 = _parse_sitemap(child.body)
                    if k2 == "urlset":
                        result.update(urls=locs2, url_count=len(locs2), child_url=locs[0])
                    else:
                        result.update(state="invalid", child_url=locs[0])
            break
        result.update(state="ok", url=cand, urls=locs, url_count=len(locs), path=r.get("body_path"))
        break
    result["tried"] = tried
    return result


# ------------------------------------------------------------------ role discovery
def find_role_candidates(doc, sitemap_urls, home_url):
    """For each role: ordered candidate URLs [(url, source)], nav links first (by context rank), then sitemap patterns."""
    home_norm = normalize_url(home_url).rstrip("/")
    out = {r: [] for r in ROLE_ORDER}
    seen = {r: set() for r in ROLE_ORDER}
    scored = []
    for l in doc.internal_links:
        if l.url.rstrip("/") == home_norm:
            continue
        parts = _slug_parts(l.url)
        for role in ROLE_ORDER:
            k = _keyword_hit(l.text, ROLE_KEYWORDS[role], max_words=NAV_LABEL_MAX_WORDS)  # a label, not a headline
            slug_hit = None
            if parts:
                for s in ROLE_SLUGS[role]:
                    if parts[0] == s or (len(parts) > 1 and parts[-1] == s):
                        slug_hit = s
                        break
            if k or slug_hit:
                rank = CONTEXT_RANK.get(l.context, 3)
                # both text and slug agreeing is the strongest signal
                strength = (0 if (k and slug_hit) else 1, rank, len(parts))
                scored.append((role, strength, l.url, "nav", k or slug_hit))
    scored.sort(key=lambda x: (x[0], x[1]))
    for role, _, url, src, kw in scored:
        key = url.rstrip("/")
        if key not in seen[role]:
            seen[role].add(key)
            out[role].append({"url": url, "source": src, "matched": kw})
    for role in ROLE_ORDER:
        for pat in ROLE_SITEMAP_PATTERNS[role]:
            for u in sitemap_urls:
                p = urlsplit(u).path.lower()
                hit = (p.rstrip("/") == pat.rstrip("/")) if not pat.endswith("/") else p.startswith(pat)
                if hit and u.rstrip("/") != home_norm and u.rstrip("/") not in seen[role]:
                    seen[role].add(u.rstrip("/"))
                    out[role].append({"url": u, "source": "sitemap", "matched": pat})
    return out


# ------------------------------------------------------------------ categorizer
def categorize(pages, docs, sitemap_urls, home_url, internal_pages_estimate, override=None):
    """site_categories.md section 2. `docs` is {role: Document} for HTML pages fetched."""
    if override:
        return {"value": override, "confidence": "high", "signals": ["user_supplied"], "scores": {}}
    home = docs.get("home")
    host = (urlsplit(home_url).hostname or "").lower()
    tld_parts = host.split(".")
    tlds = set()
    if len(tld_parts) >= 2:
        tlds.add(tld_parts[-1])
        tlds.add(tld_parts[-2])  # second-level like ac in ac.uk, edu in edu.au
    nav_texts = []
    link_urls = []
    if home is not None:
        # a nav link to a sibling subdomain (docs.example.com from www.example.com) is the site's own navigation
        site_domain = registrable_domain(host)
        for l in home.links:
            link_host = (urlsplit(l.url).hostname or "").lower()
            if l.url.startswith(("http://", "https://")) and registrable_domain(link_host) == site_domain:
                nav_texts.append((_norm_text(l.text), l.url))
                link_urls.append(l.url.lower())
    link_urls += [u.lower() for u in sitemap_urls[:200]]
    jsonld_types = []
    for role, d in docs.items():
        for t in d.jsonld_types:
            if t not in jsonld_types:
                jsonld_types.append(t)
    scores, signals = {}, {}
    for cat in CATEGORY_ORDER:
        sig = CATEGORY_SIGNALS[cat]
        sc, why = 0, []
        j = [t for t in jsonld_types if t in sig["jsonld"]]
        g = [t for t in jsonld_types if t in sig.get("jsonld_generic", ())]
        if j:
            sc += SCORE_CAPS["jsonld"]
            why.append("jsonld:" + j[0])
        elif g:
            sc += SCORE_CAPS["jsonld_generic"]
            why.append("jsonld:%s(generic)" % g[0])
        n = 0
        seen_kw = set()
        for text, url in nav_texts:
            k = _keyword_hit(text, sig["nav"], max_words=NAV_LABEL_MAX_WORDS)
            if k and k not in seen_kw:
                seen_kw.add(k)
                n += 1
                why.append("nav:" + k)
                if n >= SCORE_CAPS["nav"]:
                    break
        cluster = sig.get("nav_cluster")
        if cluster and n < SCORE_CAPS["nav"]:
            members = set()
            for text, url in nav_texts:
                k = _keyword_hit(text, cluster["members"], max_words=NAV_LABEL_MAX_WORDS)
                if k:
                    members.add(k)
            if len(members) >= cluster["min"]:
                for k in sorted(members)[:SCORE_CAPS["nav"] - n]:
                    why.append("section:" + k)
                n = min(SCORE_CAPS["nav"], n + len(members))
        sc += n
        u = 0
        seen_pat = set()
        for pat in sig["url"]:
            if pat in seen_pat:
                continue
            if any(pat in url for url in link_urls):
                seen_pat.add(pat)
                u += 1
                why.append("url:" + pat)
                if u >= SCORE_CAPS["url"]:
                    break
        sc += u
        if any(t in sig["tld"] for t in tlds):
            sc += 1
            why.append("tld:." + next(t for t in sig["tld"] if t in tlds))
        if cat == "portfolio_personal" and internal_pages_estimate <= 5 and home is not None:
            sc += 2
            why.append("pages:<=5")
        if cat == "ecommerce" and home is not None and len(home.price_mentions) >= 3:
            sc += 2
            why.append("prices:%d" % len(home.price_mentions))
        scores[cat] = sc
        signals[cat] = why
    # Tie rule (site_categories.md section 2): equal scores are separated by the strength of the evidence behind
    # them, then by breadth; only then by table order, and that last resort is recorded and lowers confidence.
    strength = {c: (scores[c], max([_SIGNAL_RANK.get(w.split(":")[0], 0) for w in signals[c]] or [0]), len(signals[c]))
                for c in CATEGORY_ORDER}
    ranked = sorted(CATEGORY_ORDER, key=lambda c: (strength[c], -CATEGORY_ORDER.index(c)), reverse=True)
    best = ranked[0]
    if scores[best] < THRESHOLD:
        return {"value": "unknown", "confidence": "low", "signals": signals.get(best, [])[:3], "scores": scores}
    conf = "high" if scores[best] >= 6 else "medium"
    why = list(signals[best])
    runner = ranked[1]
    if strength[runner] == strength[best]:
        why.append("tie:" + runner)
        conf = "low"
    return {"value": best, "confidence": conf, "signals": why, "scores": scores}


# ------------------------------------------------------------------ main entry
def sample_site(fetcher, url, category_override=None, save=True):
    """Fetch home + up to 5 role pages, categorize, return the sample manifest (fetch_policy.md section 8)."""
    manifest = {"site": None, "input_url": url, "sampled_at": _now(), "site_category": None,
                "robots": None, "sitemap": None, "edge_access": None, "pages": [], "missing_roles": [], "internal_links_seen": 0,
                "internal_pages_estimate": 0, "requests_made": 0, "notes": []}
    try:
        return _sample(fetcher, url, category_override, save, manifest)
    except Exception as e:  # noqa: BLE001
        manifest["notes"].append("sampler_error: %s: %s" % (type(e).__name__, e))
        manifest["requests_made"] = fetcher.requests_made
        if manifest["site_category"] is None:
            manifest["site_category"] = {"value": "unknown", "confidence": "low", "signals": [], "scores": {}}
        return manifest


def _page_entry(role, url, source, r, doc=None):
    e = {"role": role, "url": url, "final_url": r.get("final_url"), "source": source, "fetch": dict(r)}
    if doc is not None:
        e["summary"] = doc.summary()
    return e



def probe_edge_access(fetcher, url, home_r):
    """Ask what robots.txt cannot answer: does the origin actually serve a declared AI crawler?

    robots.txt states a site's policy. A CDN or WAF can refuse an AI crawler regardless of
    that policy, and inspecting robots.txt alone cannot see it. We request the same URL
    announcing each crawler's published token and compare the response with the baseline
    fetch made under our own user agent.

    Read-only GETs under the same budget, delay and robots rules as every other request.
    We announce a token to observe the origin's response; never to get around a refusal.
    Returns None when there is no usable baseline to compare against.
    """
    if not home_r.ok or home_r.get("challenge") or (home_r.get("status") or 0) != 200:
        return None
    baseline_bytes = home_r.get("bytes") or 0
    out = {"url": home_r.get("final_url") or url,
           "baseline": {"user_agent": "audit", "status": home_r.get("status"), "bytes": baseline_bytes},
           "agents": []}
    for token, tier, ua in PROBE_USER_AGENTS:
        r = fetcher.get_as(out["url"], ua, purpose="ua_probe")
        out["agents"].append({"token": token, "tier": tier, "status": r.get("status"),
                              "bytes": r.get("bytes") or 0, "error": r.get("error"),
                              "challenge": bool(r.get("challenge"))})
    return out

def _sample(fetcher, url, category_override, save, manifest):
    url = normalize_url(url)
    fetcher.set_site(url)
    home_r = fetcher.get(url, purpose="page", save_as="snapshots/home.html" if save else None)
    site_origin = origin_of(home_r.get("final_url") or url)
    manifest["site"] = site_origin
    if home_r.get("cross_domain"):
        manifest["notes"].append("home redirected across domains to %s" % home_r["final_url"])
    robots = fetcher.robots(site_origin)
    manifest["robots"] = {"state": robots.state, "url": robots.url, "sitemaps": list(robots.sitemaps),
                          "path": getattr(getattr(robots, "fetch", None), "get", lambda k, d=None: d)("body_path"),
                          "parse_errors": robots.parse_errors}
    docs = {}
    home_doc = None
    if home_r.ok and home_r.get("is_html") and not home_r.get("challenge"):
        home_doc = Document(home_r.text, base_url=home_r["final_url"])
        docs["home"] = home_doc
    manifest["pages"].append(_page_entry("home", url, "input", home_r, home_doc))
    manifest["edge_access"] = probe_edge_access(fetcher, url, home_r)

    # sitemap (bounded to 2 requests)
    sm = discover_sitemap(fetcher, site_origin, robots)
    manifest["sitemap"] = {k: v for k, v in sm.items() if k != "urls"}
    site_rd = registrable_domain(urlsplit(site_origin).hostname)
    sitemap_urls = [u for u in sm.get("urls", []) if registrable_domain(urlsplit(u).hostname) == site_rd]

    # role candidates
    if home_doc is not None:
        cands = find_role_candidates(home_doc, sitemap_urls, home_r["final_url"])
        manifest["internal_links_seen"] = len(home_doc.internal_urls())
    else:
        cands = find_role_candidates(Document("", base_url=site_origin), sitemap_urls, url)
    manifest["internal_pages_estimate"] = max(manifest["internal_links_seen"], len(sitemap_urls))

    taken = {(home_r.get("final_url") or url).rstrip("/")}
    for role in ROLE_ORDER:
        if len(manifest["pages"]) >= MAX_PAGES:
            manifest["missing_roles"].append(role)
            continue
        chosen = None
        for c in cands[role]:
            if c["url"].rstrip("/") not in taken:
                chosen = c
                break
        if not chosen:
            manifest["missing_roles"].append(role)
            continue
        taken.add(chosen["url"].rstrip("/"))
        r = fetcher.get(chosen["url"], purpose="page", save_as=("snapshots/%s.html" % role) if save else None)
        if r.get("final_url"):
            taken.add(r["final_url"].rstrip("/"))
        doc = None
        if r.ok and r.get("is_html") and not r.get("challenge"):
            doc = Document(r.text, base_url=r["final_url"])
            docs[role] = doc
        entry = _page_entry(role, chosen["url"], chosen["source"], r, doc)
        entry["matched"] = chosen.get("matched")
        manifest["pages"].append(entry)

    manifest["site_category"] = categorize(manifest["pages"], docs, sitemap_urls, site_origin,
                                           manifest["internal_pages_estimate"], override=category_override)
    manifest["requests_made"] = fetcher.requests_made
    if save and fetcher.workdir:
        path = os.path.join(fetcher.workdir, "sample.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        manifest["path"] = "sample.json"
        fetcher.save_manifest()
    return manifest
