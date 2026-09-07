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
