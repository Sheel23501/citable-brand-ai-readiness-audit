# Site categories (shared convention)

The sampler infers one category per site. Probes read it to decide which key
facts are required, which pages count as key pages, which engagement checks
apply, and which severity overrides fire. The orchestrator reads it to pick the
AI-answer simulation questions.

Category ids are stable strings. Do not invent new ones in a probe; add a row
here.

---

## 1. Category table

| id | Meaning | Detection signals | Key pages (besides home) | Key facts (plain-text required) |
|---|---|---|---|---|
| `ecommerce` | Sells goods online with a cart. | JSON-LD `Product`/`Offer`; nav words `cart`, `checkout`, `shop`, `collections`; URL patterns `/products/`, `/collections/`, `/cart`; ≥ 3 currency-formatted prices on home. | `product`, `about`, `contact` | `what_it_sells`, `sample_product_price`, `shipping_or_returns`, `contact_method` |
| `saas_software` | Software product or platform sold as a service. | JSON-LD `SoftwareApplication`/`WebApplication`; nav words `pricing`, `features`, `docs`, `api`, `integrations`, `sign up`, `log in`, `demo`. | `pricing`, `product`, `about`, `contact` | `what_it_does`, `pricing_or_trial`, `who_it_is_for`, `contact_or_signup_method` |
| `local_business` | Serves customers at or from a physical location. | JSON-LD `LocalBusiness` or subtype; address + phone + hours on home; nav words `directions`, `hours`, `book`, `menu`, `locations`, `visit`. | `contact`, `product` (services/menu), `about` | `address`, `phone`, `opening_hours`, `services_or_menu` |
| `professional_services` | Agency, consultancy, law, finance, medical practice without a walk-in emphasis. | JSON-LD `ProfessionalService`/`Organization` with `serviceType`; nav words `services`, `clients`, `case studies`, `our work`, `team`, `expertise`, `practice areas`. | `product` (services), `about`, `contact` | `services_offered`, `who_it_serves`, `location_or_service_area`, `contact_method` |
| `publisher_media` | Publishes articles as the primary product. | JSON-LD `NewsArticle`/`Article`/`BlogPosting` on ≥ 2 sampled pages; bylines and dates on home; nav words `news`, `latest`, `sections`, `opinion`, `subscribe`; RSS link. | `blog`, `about`, `contact` | `topics_covered`, `publisher_identity`, `recency_evidence`, `contact_method` |
| `portfolio_personal` | One person presenting themselves or their work. | JSON-LD `Person`; ≤ 5 internal pages; nav words `work`, `projects`, `about me`, `resume`, `cv`; first-person copy on home. | `about`, `contact` | `who`, `what_they_do`, `contact_or_profile_link` |
| `nonprofit_institution` | NGO, school, university, government body, association. | JSON-LD `NGO`/`EducationalOrganization`/`GovernmentOrganization`; TLD `.org`/`.edu`/`.gov`/`.ac.*`; nav words `donate`, `mission`, `programs`, `admissions`, `volunteer`, `members`. | `about`, `product` (programs), `contact` | `mission`, `programs_or_services`, `location`, `how_to_participate` (donate/apply/join) |
| `corporate_enterprise` | Multi-product company; brand site rather than a storefront. | Nav words `investors`, `careers`, `newsroom`, `press`, `leadership`, `sustainability`; ≥ 2 distinct product/brand sections; JSON-LD `Corporation`/`Organization` with `numberOfEmployees` or `tickerSymbol`. | `about`, `product`, `blog` (newsroom), `contact` | `what_company_does`, `headquarters`, `leadership_or_size`, `contact_or_press_method` |
| `unknown` | Fallback when no category reaches the threshold. | — | `about`, `contact` | `what_it_does`, `location_or_contact` |

Fact ids are stable strings used as keys in `work/extracted_facts.json`.
Every fact has a status: `present`, `partial`, or `absent`. `partial` means a
hint exists but not the fact itself; `fx.facts.key_fact_missing` fires for
required facts that are absent **or** partial, and its evidence says which.

`pricing_or_trial` is `present` with any of: a currency price; a free tier
statement ("free plan", "free forever"); or an explicit sales-led statement
("request a demo", "contact sales", "pricing on request", "talk to sales")
found on the pricing, product or home page, or anywhere when the site has no
pricing page. A "book a demo" link on the contact page does not by itself make
a site sales-led. A free-trial mention alone ("Start free trial") is `partial`
(`kind: trial_only`): it says a trial exists and nothing about cost. Enterprise
and B2B sites that sell through a sales team are a large, normal category and
are never flagged for withholding prices; the fact is recorded with
`kind: sales_led` so the simulation can answer "pricing is available on request".

Two optional facts exist for every category and never produce a finding when
absent: `audience` (who the offer is for, taken from the category's audience
fact where one exists) and `differentiator` (an explicit claim of what sets the
brand apart: "unlike", "the only", "first", "built for"). They exist so the
AI-answer simulation can ask the fit and comparison questions in section 6.
NAP fields (`address`, `phone`) are owned by the entity probe for every
category **except** `local_business`, where they are also key facts; compose
dedupes the overlap (see `coverage_map.md` section 4).

---

## 2. Inference rule (Step 5 implements exactly this)

Score every category from the home page plus the discovered nav:

| Signal | Points | Cap per category |
|---|---|---|
| JSON-LD `@type` match on any sampled page (types and subtypes listed in `CATEGORY_SIGNALS`) | 3 | 3 |
| Generic parent type only (`LocalBusiness`, the schema.org parent of `ProfessionalService`, `Store`, `Restaurant`, …), when no specific type matched | 2 | 2 |
| Nav keyword match (link text or href slug) | 1 each | 4 |
| URL pattern match on discovered internal links | 1 each | 2 |
| TLD hint | 1 | 1 |
| Page-count rule (`portfolio_personal` only: ≤ 5 internal pages) | 2 | 2 |
| Price-count rule (`ecommerce` only: ≥ 3 currency-formatted prices on home) | 2 | 2 |

- A nav keyword counts only on a **menu-length label**: link text of at most four words. A category word inside a headline or a sentence ("Saving the world with Open Data") is not a signal. Links to a sibling subdomain of the site (`docs.example.com` from `www.example.com`) are the site's own navigation and count.
- Newspaper **section names** (`world`, `business`, `politics`, `sport`, `culture`, `opinion` and their German, French and Spanish equivalents) are ordinary words on their own; they score for `publisher_media` only when **two or more distinct** ones appear, as `section:<word>`, within the nav cap.
- Category = highest score. **Tie** → the category whose points rest on stronger evidence: a JSON-LD type beats menu labels, which beat URL patterns, which beat the TLD and the count rules; if still equal, the one with more distinct signals; if still equal, the order of the table above, and that last resort is recorded as `tie:<runner-up>` in `signals` with confidence `low`, because the inference is genuinely uncertain.
- Score < 3 → `unknown`.
- Category confidence: score ≥ 6 `high`; 3–5 `medium`; `unknown` is always `low`; an unresolved tie is `low`.
- The winning signals are recorded as strings like `nav:pricing`, `jsonld:SoftwareApplication`, `url:/products/`, `tld:.org` in `site_category.signals`.
- A user-supplied `--category` flag overrides inference and is recorded with confidence `high` and signal `user_supplied`.

Nav keyword vocabulary is English plus non-English equivalents matched
case-insensitively as whole words in link text (for example `preise`/`prix`/
`precios`/`prezzi` for pricing, `kontakt`/`contacto`/`contatti` for contact,
`über uns`/`à propos`/`sobre nosotros`/`chi siamo` for about, `aktuelles`/
`actualités`/`noticias` for news, `produkte`/`produits`/`productos` for product,
`boutique`/`tienda` for shop). The canonical word lists live in one place,
`skills/audit-orchestrator/scripts/auditlib/sampler.py` (`ROLE_KEYWORDS`,
`ROLE_SLUGS`, `CATEGORY_SIGNALS`), because they are data the code must match
exactly; this file owns the rule and the scoring. Adding a word means adding it
there and, if it is a new language, noting the language here.

Internal page count for the `portfolio_personal` rule is
`max(distinct internal links on home, sitemap URL count)`, so a one-page shell
with a seven-URL sitemap does not look like a portfolio. JSON-LD `@type`
matches are taken from every sampled page, not only home, because Organization
and SoftwareApplication markup commonly sits on about and product pages.

---

## 3. Page roles (used by the sampler and every probe)

Role discovery from link text follows the same label rule as category inference: a role keyword counts only in link text of at most four words. A headline that contains "plans" is not the pricing page; a slug match (`/pricing`) is unaffected.

| role | Nav keywords (any language row above) | Sitemap fallback pattern |
|---|---|---|
| `home` | — (the input URL after redirects) | — |
| `about` | about, about us, company, who we are, our story, team | `/about`, `/company`, `/team` |
| `contact` | contact, contact us, get in touch, support, help | `/contact`, `/support` |
| `pricing` | pricing, plans, prices, rates, fees | `/pricing`, `/plans` |
| `product` | products, services, solutions, features, shop, menu, programs, what we do | `/products/`, `/services/`, `/solutions/`, `/collections/`, `/menu` |
| `blog` | blog, news, newsroom, press, insights, articles, latest, journal | `/blog`, `/news`, `/press`, `/insights` |

Sampler takes at most 6 pages: `home` always, then one per role in the order
above, nav first then sitemap. A role with no candidate is recorded as
`missing_role` in the sample manifest (this is not itself a finding; probes use
it, for example the engagement probe's landing-continuity check, or
`ef.corroboration.press_page_missing`).

---

## 4. Engagement applicability caps

`yes` = check runs with default severity. `no` = `not_evaluated` with reason
`not_applicable_for_category`. `low` = runs but severity capped at `low`.

| check | ecommerce | saas | local | prof_services | publisher | portfolio | nonprofit | corporate | unknown |
|---|---|---|---|---|---|---|---|---|---|
| `en.nav.landmark_missing` | yes | yes | yes | yes | yes | low (no if ≤ 3 pages) | yes | yes | low |
| `en.nav.breadcrumbs_missing` | yes | low | no | no | yes | no | low | yes | no |
| `en.nav.site_search_missing` | yes | low | no | no | yes | no | low | yes | no |
| `en.nav.related_links_missing` | yes (product) | low | no | no | yes (blog) | no | no | low | no |
| `en.cta.missing` | yes | yes | yes | yes | low | low | yes | low | low |
| `en.trust.signals_missing` | yes | yes | yes | yes | low | no | yes | low | low |
| `en.hero.value_prop_unclear` | yes | yes | yes | yes | low | yes | yes | yes | yes |
| all other `en.*` | yes | yes | yes | yes | yes | yes | yes | yes | yes |

The word lists below, plus the category nouns and verbs of offer used by
`en.hero.value_prop_unclear`, live in
`skills/audit-orchestrator/scripts/auditlib/categories.py` (`CTA_VOCAB`,
`CATEGORY_NOUNS`, `OFFER_VERBS`, `TRUST_SIGNALS`), which the engagement probe
reads; this file owns the rule, the code owns the lists.

Expected CTA vocabulary per category (used by `en.cta.missing`; a match is a
`<a>` or `<button>` in the first viewport region whose text contains one):

- ecommerce: shop, buy, add to cart, browse, order
- saas_software: sign up, start, try, get started, book a demo, request a demo, free trial
- local_business: book, call, directions, order, reserve, visit
- professional_services: contact, talk to us, get a quote, schedule, consultation, book
- publisher_media: subscribe, read, sign up, newsletter
- portfolio_personal: contact, hire, email, view work
- nonprofit_institution: donate, apply, volunteer, join, register
- corporate_enterprise: contact, learn more, explore, careers
- unknown: contact, get started, learn more

Expected trust signals per category (used by `en.trust.signals_missing`; ≥ 1
present passes):

- ecommerce: returns/refund policy link, payment or security badges, review markup or review count, physical address
- saas_software: customer logos or testimonials, security/compliance page, pricing transparency, terms/privacy links
- local_business: address, phone, hours, review count or rating, photos of premises
- professional_services: team page with named people, client list or case studies, credentials/accreditations, address
- nonprofit_institution: registration/charity number, financial or annual report link, named leadership, address
- others: terms/privacy links plus at least one of address, named people, testimonials

---

## 5. Severity overrides by category

Applied per `severity_confidence_rubric.md` section 3 step 5.

| check | Default | Override |
|---|---|---|
| `ef.entity.nap_missing_plain_text` | `medium` | `high` for `local_business`; `low` for `saas_software`, `publisher_media`, `portfolio_personal` |
| `ef.freshness.no_visible_dates` | `low` | `medium` for `publisher_media` |
| `ef.corroboration.press_page_missing` | `low` | `medium` for `corporate_enterprise`; `not_evaluated` for `portfolio_personal`, `local_business` |
| `fx.content.faq_absent` | `low` | `not_evaluated` for `publisher_media`, `portfolio_personal` |
| `fx.facts.image_only` | `high` | `medium` when the fact is not in the category's key-fact list |
| `cr.index.sitemap_missing` | `low` | `medium` for `ecommerce`, `publisher_media` |

---

## 6. AI-answer simulation question templates (Step 17 uses exactly these)

`{brand}` = the organisation name from extracted facts (or the host if absent).
Each question maps to fact ids; a question is `answerable` only when every
listed fact is present in `work/extracted_facts.json`.

Every category also asks two further questions, mirroring how generative
engines fan a query out into angled sub-questions:

- **Q4 (fit):** "Is {brand} a good fit for {audience}?" → the category's audience fact (`who_it_is_for`, `who_it_serves`, `topics_covered`, `services_or_menu`, `what_it_sells`, `programs_or_services`, `what_they_do`, or `what_company_does`), answered as "for whom" rather than yes/no.
- The `{audience}` placeholder is filled from the `AUDIENCE_PHRASE` table in
  `auditlib/categories.py` ("a team like mine", "someone in the area", …), so the question reads the way a
  person asks it; the answer still comes from the audience fact above. The question templates themselves are
  mirrored in the same module as `SIMULATION_QUESTIONS`.
- **Q5 (comparison):** "What sets {brand} apart from alternatives?" → optional fact `differentiator`. Unanswerable Q5 is recorded as informational only and never becomes a finding.

| Category | Q1 (what) | Q2 (category-specific) | Q3 (how to proceed) |
|---|---|---|---|
| `ecommerce` | What does {brand} sell? → `what_it_sells` | How much does a typical product cost, and what is the shipping or return policy? → `sample_product_price`, `shipping_or_returns` | How do I contact {brand}? → `contact_method` |
| `saas_software` | What does {brand} do and who is it for? → `what_it_does`, `who_it_is_for` | How much does {brand} cost, and is there a free trial? → `pricing_or_trial` | How do I get started or contact sales? → `contact_or_signup_method` |
| `local_business` | What does {brand} offer? → `services_or_menu` | Where is {brand} and when is it open? → `address`, `opening_hours` | How do I reach {brand}? → `phone` |
| `professional_services` | What services does {brand} provide? → `services_offered` | Who does {brand} work with, and where? → `who_it_serves`, `location_or_service_area` | How do I contact {brand}? → `contact_method` |
| `publisher_media` | What does {brand} cover? → `topics_covered` | Who publishes {brand}, and is it current? → `publisher_identity`, `recency_evidence` | How do I contact {brand}? → `contact_method` |
| `portfolio_personal` | Who is {brand} and what do they do? → `who`, `what_they_do` | — | How do I contact them? → `contact_or_profile_link` |
| `nonprofit_institution` | What is {brand}'s mission? → `mission` | What programs does {brand} run, and where? → `programs_or_services`, `location` | How do I donate, apply, or join? → `how_to_participate` |
| `corporate_enterprise` | What does {brand} do? → `what_company_does` | Where is {brand} headquartered and who leads it? → `headquarters`, `leadership_or_size` | How do I contact {brand} or its press office? → `contact_or_press_method` |
| `unknown` | What does {brand} do? → `what_it_does` | — | How do I contact {brand}? → `location_or_contact` |
