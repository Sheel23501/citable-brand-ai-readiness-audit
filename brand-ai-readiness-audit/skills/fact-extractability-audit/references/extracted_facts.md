# fact-extractability-audit: the facts file

`work/extracted_facts.json` is written on every run, inside the workdir, and
its relative path is returned in the probe output's `artifacts.extracted_facts`.
It exists for one reason: the orchestrator's AI-answer simulation
(`report_schema.md`, `ai_answer_simulation.basis = "extracted_facts_only"`) may
use **only** the values in this file. Anything the agent knows about the brand,
or could fetch itself, is out of bounds. If a fact is `absent` here, the
simulated answer is "the site does not state it".

The file is written even when no page was usable (`pages_used` is then empty
and `facts` is `{}`), so the orchestrator can always explain why the simulation
had nothing to work with.

## 1. Top-level fields

| Field | Type | Meaning |
|---|---|---|
| `site` | string | The audited site (scheme and host), as in the probe output. |
| `site_category` | string | The category the facts were resolved for (`site_categories.md` section 1), after any `--category` override. |
| `extracted_at` | string | UTC timestamp, `YYYY-MM-DDTHH:MM:SSZ`. |
| `basis` | string | Always `served_html_only`. |
| `brand_name` | object | `{value, page, source}`: the name used as `{brand}` in the simulation questions (section 6). |
| `facts` | object | One entry per fact id (section 2), for the category's required facts plus the two optional facts. |
| `required_fact_ids` | list | The category's key facts, in the order of `site_categories.md`. |
| `pages_used` | list | `{role, url, words, jsonld_types}` for each usable page, in sample order. |
| `pages_excluded` | list | `{role, url, reason}` for each sampled page that was not graded; reasons are `robots_disallow`, `challenge_page`, `http_error`, `non_html`, `no_rendered_content`. |
| `identity` | object | Per role: `{title, h1 (first two), description, og_site_name}`, so the simulation can quote how each page introduces itself. |
| `jsonld_recommendations` | list | Up to 20 `{page, type, missing_recommended}` entries: recommended (not required) properties absent from top-level JSON-LD nodes. Input for the orchestrator's proactive recommendations, never a finding. |
| `note` | string | The contract sentence: values are verbatim excerpts; the simulation may use only these values. |

## 2. A fact entry

```json
"pricing_or_trial": {
  "status": "partial",
  "kind": "trial_only",
  "value": "…About Contact Search Search Start free trial Invoicing and expense software…",
  "page": "https://example.com/",
  "source": "text",
  "required": true
}
```

| Field | Meaning |
|---|---|
| `status` | `present`: the fact itself was found. `partial`: a hint exists but not the fact (today only `pricing_or_trial` can be partial). `absent`: nothing found on the usable pages. |
| `kind` | What was found, from the vocabulary in section 4 (`price`, `sales_led`, `free_tier`, `trial_only`, `description`, `audience`, `contact`, `signup`, `press`, `profile_link`, `address`, `location_phrase`, `phone`, `hours`, `list`, `policy`, `identity`, `date`, `person`, `role`, `mission`, `call_to_action`, `leadership`, `claim`). `null` when absent. |
| `value` | A verbatim excerpt from the served HTML, at most 200 characters, snapped to word boundaries and marked with `…` where cut. Never a paraphrase. |
| `page` | The final URL of the page it was found on. |
| `source` | Where on the page it came from (section 5). |
| `required` | Whether the fact is one of the category's key facts. Only required facts can produce `fx.facts.key_fact_missing`. |
| `note` | Optional. `from <fact id>` when `audience` was aliased (section 3); `resolver_error: …` when a detector raised and the fact was recorded `absent` rather than crashing the probe; `no resolver` should never appear. |

## 3. Which facts are resolved

The required facts are the category's key facts from `site_categories.md`
section 1. Two optional facts are resolved for every category and never
produce a finding:

- `audience`: who the offer is for. Looked up directly first (`AUDIENCE` rule
  below). When absent, it is aliased from the category's audience fact
  (`who_it_is_for`, `who_it_serves`, `topics_covered`, `services_or_menu`,
  `what_it_sells`, `programs_or_services`, `what_they_do`,
  `what_company_does`) with `note: "from <fact id>"`, so the simulation's fit
  question (Q4) can be answered "for whom" rather than yes or no.
- `differentiator`: an explicit claim of what sets the brand apart ("unlike",
  "the only", "the first", "what sets us apart", "why choose"). Feeds the
  comparison question (Q5). Unanswerable Q5 is informational only.

## 4. Detection order per fact

Detectors run in the order listed and stop at the first hit. "pages" means
the usable pages, tried in the preference order shown (remaining pages follow
in sample order). All text matching is case-insensitive; the phrase lists are
English-first (see `non_findings.md`, limits).

| Fact id | Categories | Detection order | `kind` |
|---|---|---|---|
| `what_it_does`, `what_company_does` | saas, corporate, unknown | meta description of at least 40 characters (home, about, product) → `og:description` or a top-level JSON-LD `description` of at least 40 characters → the first `h1` of at least three words plus the paragraph that follows it (at least 12 words) | `description` |
| `pricing_or_trial` | saas | currency amount in text or `Offer.price`/`lowPrice` in JSON-LD (pricing, product, home first) → sales-led phrase on the pricing, product or home page (anywhere if the site has no pricing page), in text or link text → free-tier phrase anywhere → free-trial phrase anywhere (**partial**) | `price`, `sales_led`, `free_tier`, `trial_only` |
| `sample_product_price` | ecommerce | currency amount in text or `Offer.price` (product, pricing, home first) | `price` |
| `who_it_is_for`, `who_it_serves`, `audience` | saas, professional; optional everywhere | JSON-LD `audience` (`audienceType` or `name`) → "built / designed / made / tailored / perfect / ideal / trusted / used / loved for|by … <audience noun>" in text (home, about, product first) | `audience` |
| `contact_method` | ecommerce, professional, publisher | `mailto:` link or e-mail address in text (contact, home first) → phone: JSON-LD `telephone`, or a 9–15 digit number that starts with `+` or follows a phone cue word → a form on the contact page with an email or message field | `contact` |
| `contact_or_signup_method` | saas | as `contact_method` → sign-up phrase in text, link or button text ("sign up", "get started", "create account", "start free", …) | `contact`, `signup` |
| `contact_or_press_method` | corporate | as `contact_method` → press e-mail (press@, media@, pr@) → press or newsroom phrase in text, headings or links | `contact`, `press` |
| `contact_or_profile_link` | portfolio | as `contact_method` → JSON-LD `sameAs` URLs → a link to a profile host (LinkedIn, GitHub, Instagram, Behance, Dribbble, X/Twitter, Facebook, …) | `contact`, `profile_link` |
| `address` | local | JSON-LD `PostalAddress` with a street, or locality plus postcode → street pattern, UK postcode (with a word before it), or US city-state-zip in body text (contact, about, home first) | `address` |
| `phone` | local | JSON-LD `telephone` → phone number in text as above | `phone` |
| `opening_hours` | local | JSON-LD `openingHoursSpecification` or `openingHours` → day-and-time pattern in body text (contact, home, product first) | `hours` |
| `services_or_menu` | local | three or more named top-level `Product`/`Service`/`Menu`/`MenuItem`/`ItemList`/`Offer`/`Course`/`Event` nodes or `itemListElement` names (not breadcrumbs) → three or more non-generic h2/h3 headings of at most eight words → three or more 2–10 word links in the main content (product, home, contact first) | `list` |
| `services_offered`, `programs_or_services` | professional, nonprofit | as above (product, home, about first) | `list` |
| `what_it_sells` | ecommerce | as above (product, home first) | `list` |
| `topics_covered` | publisher | as above (blog, home first) | `list` |
| `shipping_or_returns` | ecommerce | shipping / delivery / returns phrase in text, headings or links (product, home, contact first) | `policy` |
| `location_or_service_area`, `location`, `headquarters` | professional, nonprofit, corporate | full address as `address` → JSON-LD locality/region/country or `areaServed` → "based in / located in / serving …" phrase in body text (about, home, contact first) | `address`, `location_phrase` |
| `location_or_contact` | unknown | as `location` → as `contact_method` | `address`, `location_phrase`, `contact` |
| `publisher_identity` | publisher | top-level Organization-family node `name` on home or about → `og:site_name` or `application-name` → the name in a copyright line | `identity` |
| `recency_evidence` | publisher | first `<time datetime>` → JSON-LD `datePublished` / `dateModified` → ISO or written date in body text | `date` |
| `who` | portfolio | JSON-LD `Person.name` → a 2–4 word capitalised `h1`, or a name at the start of the `h1` → the first segment of the title when it looks like a name | `person` |
| `what_they_do` | portfolio | JSON-LD `Person.jobTitle` → "I am a / we are a …" statement → the second title segment → a first `h1` of at least four words | `role` |
| `mission` | nonprofit | mission phrase ("our mission", "we exist to", "dedicated to", …) in text (about, home first) → `description` of an NGO / educational / government / Organization node | `mission` |
| `how_to_participate` | nonprofit | donate / apply / enrol / volunteer / join phrase in text, headings, links or buttons (home, product, about first) | `call_to_action` |
| `leadership_or_size` | corporate | JSON-LD `numberOfEmployees` / `founder` → a leadership title (CEO, chief … officer, founder, …) or a head-count phrase in body text (about, home first) | `leadership` |
| `differentiator` | optional everywhere | differentiator phrase in text (home, about, product first) | `claim` |

`brand_name` is resolved in this order: top-level Organization-family or
`Person` node `name` on home or about → `og:site_name` / `application-name`
on home → a title segment (split on `|`, `—`, `–`, `-`, `:`) of one to four
words that repeats on at least two pages → the registrable host's first label,
capitalised.

## 5. Source vocabulary

| `source` | Meaning |
|---|---|
| `text` | Visible body text (plus meta description and JSON-LD leaf strings for phrase searches). |
| `text:street`, `text:uk_postcode`, `text:us_city_state_zip` | Which address pattern matched. |
| `text:copyright`, `text:press_email` | Copyright line; press e-mail address. |
| `meta:description`, `meta:og:description`, `meta:og:site_name` | The named meta tag. |
| `jsonld:<Type>.<property>` | A property of a top-level node of that type (`jsonld:Organization.name`, `jsonld:Person.jobTitle`, `jsonld:Offer.price`). |
| `jsonld:<property>` | A property found by walking a top-level node (`jsonld:telephone`, `jsonld:PostalAddress`, `jsonld:address`, `jsonld:openingHours`, `jsonld:audience`, `jsonld:sameAs`, `jsonld:description`, `jsonld:datePublished`, `jsonld:dateModified`, `jsonld:areaServed`, `jsonld:numberOfEmployees`, `jsonld:founder`). |
| `jsonld` | A list assembled from several node names. |
| `link:mailto`, `link:profile`, `link` | A `mailto:` link's address; a link to a profile host; matching link text. |
| `button` | Matching button text. |
| `heading`, `heading:h1`, `heading:questions`, `heading+text` | A heading; the first `h1`; three or more question headings; an `h1` with its following paragraph. |
| `title`, `title:common_segment` | The page title; a title segment repeated across pages. |
| `form` | A contact form (value gives the field count). |
| `html:time` | A `<time datetime>` value. |
| `host` | Derived from the host name (brand name fallback only). |

## 6. How the simulation reads it

`site_categories.md` section 6 maps each category's five questions to fact
ids. A question is `answerable` only when every listed fact is `present`;
`partial` counts as missing, and the simulated answer must quote `value` and
name `page`. For `pricing_or_trial` with kind `sales_led`, the answer is
"pricing is available on request"; with kind `trial_only` the question is not
answerable and `missing_facts` lists `pricing_or_trial`. `{brand}` is
`brand_name.value`.

## 7. Worked example

For a `saas_software` site with plain-text pricing and a mailto link:

```json
{
  "site": "https://ledgerly.example",
  "site_category": "saas_software",
  "basis": "served_html_only",
  "brand_name": {"value": "Ledgerly", "page": "https://ledgerly.example/", "source": "jsonld:Organization.name"},
  "required_fact_ids": ["what_it_does", "pricing_or_trial", "who_it_is_for", "contact_or_signup_method"],
  "facts": {
    "what_it_does": {"status": "present", "kind": "description", "value": "Ledgerly helps freelance designers and small studios send invoices, track expenses, and get paid faster.", "page": "https://ledgerly.example/", "source": "meta:description", "required": true},
    "pricing_or_trial": {"status": "present", "kind": "price", "value": "…Plan Price Includes Free £0 per month Up to 3 clients, unlimited…", "page": "https://ledgerly.example/pricing", "source": "text", "required": true},
    "who_it_is_for": {"status": "present", "kind": "audience", "value": "…expense software built for freelance designers Ledgerly helps freelance…", "page": "https://ledgerly.example/", "source": "text", "required": true},
    "contact_or_signup_method": {"status": "present", "kind": "contact", "value": "hello@ledgerly.example", "page": "https://ledgerly.example/contact", "source": "link:mailto", "required": true},
    "audience": {"status": "present", "kind": "audience", "value": "…expense software built for freelance designers Ledgerly helps freelance…", "page": "https://ledgerly.example/", "source": "text", "required": false},
    "differentiator": {"status": "absent", "kind": null, "value": null, "page": null, "source": null, "required": false}
  }
}
```

Every one of the five simulation questions for this category is answerable
from the file except Q5 (no differentiator claim), which is recorded as
informational.
