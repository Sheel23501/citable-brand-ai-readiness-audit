"""Category tables mirrored from ../../references/site_categories.md (sections 1, 4, 5).

The markdown owns the rule; this module is the machine-readable copy the
probes read. Keep them in sync (tests/run_tests.py checks the ids agree).
"""
CATEGORIES = ("ecommerce", "saas_software", "local_business", "professional_services", "publisher_media",
              "portfolio_personal", "nonprofit_institution", "corporate_enterprise", "unknown")

# key pages besides home (section 1)
KEY_PAGES = {
    "ecommerce": ["product", "about", "contact"],
    "saas_software": ["pricing", "product", "about", "contact"],
    "local_business": ["contact", "product", "about"],
    "professional_services": ["product", "about", "contact"],
    "publisher_media": ["blog", "about", "contact"],
    "portfolio_personal": ["about", "contact"],
    "nonprofit_institution": ["about", "product", "contact"],
    "corporate_enterprise": ["about", "product", "blog", "contact"],
    "unknown": ["about", "contact"],
}

# key facts required in plain text (section 1)
KEY_FACTS = {
    "ecommerce": ["what_it_sells", "sample_product_price", "shipping_or_returns", "contact_method"],
    "saas_software": ["what_it_does", "pricing_or_trial", "who_it_is_for", "contact_or_signup_method"],
    "local_business": ["address", "phone", "opening_hours", "services_or_menu"],
    "professional_services": ["services_offered", "who_it_serves", "location_or_service_area", "contact_method"],
    "publisher_media": ["topics_covered", "publisher_identity", "recency_evidence", "contact_method"],
    "portfolio_personal": ["who", "what_they_do", "contact_or_profile_link"],
    "nonprofit_institution": ["mission", "programs_or_services", "location", "how_to_participate"],
    "corporate_enterprise": ["what_company_does", "headquarters", "leadership_or_size", "contact_or_press_method"],
    "unknown": ["what_it_does", "location_or_contact"],
}

# the audience fact used by simulation Q4 (section 6)
AUDIENCE_FACT = {
    "ecommerce": "what_it_sells", "saas_software": "who_it_is_for", "local_business": "services_or_menu",
    "professional_services": "who_it_serves", "publisher_media": "topics_covered", "portfolio_personal": "what_they_do",
    "nonprofit_institution": "programs_or_services", "corporate_enterprise": "what_company_does", "unknown": "what_it_does",
}

# engagement applicability caps (section 4): "yes" | "no" | "low"
_CAP_ROWS = {
    #                                  ecom   saas   local  prof   pub    port   npo    corp   unk
    "en.nav.landmark_missing":        ("yes", "yes", "yes", "yes", "yes", "low", "yes", "yes", "low"),
    "en.nav.breadcrumbs_missing":     ("yes", "low", "no",  "no",  "yes", "no",  "low", "yes", "no"),
    "en.nav.site_search_missing":     ("yes", "low", "no",  "no",  "yes", "no",  "low", "yes", "no"),
    "en.nav.related_links_missing":   ("yes", "low", "no",  "no",  "yes", "no",  "no",  "low", "no"),
    "en.cta.missing":                 ("yes", "yes", "yes", "yes", "low", "low", "yes", "low", "low"),
    "en.trust.signals_missing":       ("yes", "yes", "yes", "yes", "low", "no",  "yes", "low", "low"),
    "en.hero.value_prop_unclear":     ("yes", "yes", "yes", "yes", "low", "yes", "yes", "yes", "yes"),
}
_CAP_ORDER = ("ecommerce", "saas_software", "local_business", "professional_services", "publisher_media",
              "portfolio_personal", "nonprofit_institution", "corporate_enterprise", "unknown")


def engagement_cap(check_id, category):
    row = _CAP_ROWS.get(check_id)
    if row is None:
        return "yes"
    try:
        return row[_CAP_ORDER.index(category)]
    except ValueError:
        return row[-1]


# severity overrides (section 5): check_id -> {category: severity | "not_evaluated"}
SEVERITY_OVERRIDES = {
    "ef.entity.nap_missing_plain_text": {"local_business": "high", "saas_software": "low", "publisher_media": "low", "portfolio_personal": "low"},
    "ef.freshness.no_visible_dates": {"publisher_media": "medium"},
    "ef.corroboration.press_page_missing": {"corporate_enterprise": "medium", "portfolio_personal": "not_evaluated", "local_business": "not_evaluated"},
    "fx.content.faq_absent": {"publisher_media": "not_evaluated", "portfolio_personal": "not_evaluated"},
    "cr.index.sitemap_missing": {"ecommerce": "medium", "publisher_media": "medium"},
}

CTA_VOCAB = {
    "ecommerce": ["shop", "buy", "add to cart", "browse", "order"],
    "saas_software": ["sign up", "start", "try", "get started", "book a demo", "request a demo", "free trial"],
    "local_business": ["book", "call", "directions", "order", "reserve", "visit"],
    "professional_services": ["contact", "talk to us", "get a quote", "schedule", "consultation", "book"],
    "publisher_media": ["subscribe", "read", "sign up", "newsletter"],
    "portfolio_personal": ["contact", "hire", "email", "view work"],
    "nonprofit_institution": ["donate", "apply", "volunteer", "join", "register"],
    "corporate_enterprise": ["contact", "learn more", "explore", "careers"],
    "unknown": ["contact", "get started", "learn more"],
}


def key_pages(category):
    return ["home"] + KEY_PAGES.get(category, KEY_PAGES["unknown"])


def is_key_page(role, category):
    return role in key_pages(category)


# ---------------------------------------------------------------- engagement vocabularies (site_categories.md section 4)
# The markdown owns the rule ("category noun", "verb of offer", "expected trust signals"); this module owns the word
# lists so the engagement probe and the documentation cannot drift. Nouns match with an optional s/es/ing/ed suffix.

OFFER_VERBS = (
    "help", "helps", "build", "builds", "make", "makes", "create", "creates", "get", "send", "sends", "track", "tracks",
    "manage", "manages", "find", "book", "order", "design", "designs", "deliver", "delivers", "grow", "save", "learn",
    "discover", "shop", "buy", "start", "sell", "sells", "provide", "provides", "offer", "offers", "serve", "serves",
    "run", "runs", "plan", "automate", "automates", "simplify", "simplifies", "connect", "connects", "protect", "protects",
    "teach", "teaches", "support", "supports", "draw", "draws", "write", "writes", "photograph", "publish", "publishes",
    "cover", "covers", "bring", "brings", "turn", "turns", "power", "powers", "ship", "ships", "craft", "crafts",
    "handcraft", "bake", "bakes", "cook", "cooks", "repair", "repairs", "fix", "fixes", "treat", "treats", "train",
    "trains", "hire", "explore", "browse", "compare", "donate", "volunteer", "join", "apply", "subscribe", "read",
    "let", "lets", "allow", "allows", "enable", "enables", "give", "gives", "integrate", "integrates", "work", "works",
)

CATEGORY_NOUNS = {
    "ecommerce": ["shop", "store", "product", "collection", "range", "gear", "goods", "apparel", "furniture", "jewellery", "jewelry",
                  "clothing", "shoes", "bag", "beauty", "skincare", "accessory", "accessories", "homeware", "desk", "order", "delivery",
                  "handmade", "sale", "brand", "boutique", "catalogue", "catalog"],
    "saas_software": ["software", "platform", "app", "application", "tool", "api", "service", "solution", "analytics", "dashboard",
                      "automation", "workflow", "saas", "cloud", "data", "integration", "invoicing", "billing", "crm", "suite", "product",
                      "system", "engine", "infrastructure", "security", "monitoring", "hosting", "database"],
    "local_business": ["restaurant", "cafe", "café", "bar", "bakery", "salon", "barber", "clinic", "dentist", "gym", "studio", "hotel",
                       "shop", "store", "garage", "pharmacy", "florist", "spa", "kitchen", "menu", "booking", "appointment", "visit",
                       "location", "hour", "table", "class", "treatment", "service"],
    "professional_services": ["service", "consulting", "consultancy", "agency", "firm", "law", "legal", "accounting", "accountant",
                              "advisory", "adviser", "advisor", "architect", "engineering", "design", "marketing", "client", "expertise",
                              "practice", "advice", "solicitor", "attorney", "partner", "project", "strategy", "audit"],
    "publisher_media": ["news", "magazine", "journal", "story", "stories", "article", "coverage", "reporting", "analysis", "podcast",
                        "newsletter", "editorial", "feature", "opinion", "guide", "review", "issue", "edition", "journalism"],
    "portfolio_personal": ["designer", "illustrator", "developer", "photographer", "writer", "artist", "engineer", "consultant",
                           "freelance", "portfolio", "work", "project", "illustration", "photography", "commission", "book", "cover",
                           "brand", "film", "music", "author", "maker"],
    "nonprofit_institution": ["mission", "community", "charity", "nonprofit", "non-profit", "foundation", "university", "school",
                              "college", "student", "program", "programme", "research", "education", "support", "donation", "volunteer",
                              "member", "cause", "campaign", "grant", "fund", "course", "faculty"],
    "corporate_enterprise": ["company", "group", "solution", "industry", "industries", "customer", "product", "global", "enterprise",
                             "innovation", "technology", "energy", "manufacturing", "service", "business", "brand", "market",
                             "operation", "leader", "partner"],
    "unknown": ["service", "product", "software", "shop", "store", "company", "business", "platform", "app", "studio", "agency",
                "restaurant", "school", "community", "project", "work", "solution", "tool", "brand", "team", "help", "guide"],
}

# expected trust signals (site_categories.md section 4). At least one present passes for a listed category; every other
# category needs terms/privacy links plus at least one of address, named people, testimonials.
TRUST_SIGNALS = {
    "ecommerce": ["returns_policy_link", "payment_or_security_badge", "review_markup_or_count", "address"],
    "saas_software": ["testimonials_or_logos", "security_or_compliance_link", "pricing_transparency", "terms_privacy_links"],
    "local_business": ["address", "phone", "opening_hours", "review_markup_or_count", "premises_photos"],
    "professional_services": ["team_named_people", "clients_or_case_studies", "credentials", "address"],
    "nonprofit_institution": ["registration_number", "financial_report_link", "named_leadership", "address"],
}
TRUST_SIGNALS_DEFAULT = {"required": ["terms_privacy_links"], "any_of": ["address", "named_people", "testimonials_or_logos"]}

