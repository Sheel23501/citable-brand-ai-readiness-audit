# check_id naming rule and registry (shared convention)

A `check_id` is the stable machine name of one check. Fixtures assert on it,
compose dedupes on it, the validator accepts only ids listed here, and the
README's coverage table is generated from this file.

---

## 1. Naming rule

```
<prefix>.<subject>.<condition>
```

- Three segments, lower-case ASCII, `snake_case` inside a segment, dots between segments. Regex: `^[a-z]{2}\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`.
- `prefix` is the owning skill: `cr` crawl-render, `fx` fact-extractability, `ef` entity-freshness-corroboration, `en` engagement, `or` orchestrator-level.
- `subject` is the thing examined (`robots`, `jsonld`, `hero`).
- `condition` names the **failure** as a noun phrase (`blanket_disallow`, `malformed`, `missing`). Never a verb, never the pass condition.
- One check ⇒ one id. A check that fails on several pages emits **one** finding with several `affected_pages`, not several findings. Exception: checks marked `per-page` below emit one finding per page because the evidence and action differ per page.
- Ids are never renamed or reused. A retired id stays in section 3 marked `retired`.
- Adding a check = adding a row here first, then implementing it, then adding a fixture assertion.
- Every row also has a **positive title**: the same condition said as a fact about a site that passed it. Those titles live in `audit-orchestrator/scripts/compose.py` as `POSITIVE_TITLES`, one per row, and are what the report's "What is working" section prints. The test suite asserts the two sets match.

---

## 2. Registry

Columns: stage (`coverage_map.md` section 2), default severity, maximum severity after adjustments, default confidence, effort, per-page or site-level, and the one-line pass condition. Titles in findings are written by the probe but must match the row's meaning.

### crawl-render-audit (`cr.*`)

| check_id | Stage | Sev | Max | Conf | Effort | Scope | Fails when |
|---|---|---|---|---|---|---|---|
| `cr.robots.unreachable` | access | info | info | high | n/a | site | robots.txt 5xx / timeout / challenge (status `inconclusive`). |
| `cr.robots.blanket_disallow` | access | critical | critical | high | low | site | `*` group disallows `/`. |
| `cr.robots.live_answer_bot_blocked` | access | high | critical | high | low | site | Any `live_answer` token disallowed on `/`; critical when all are. |
| `cr.robots.index_bot_blocked` | access | high | high | high | low | site | Any `index` token disallowed on `/`. |
| `cr.robots.training_bot_blocked` | access | info | info | high | n/a | site | Any `training_only` token disallowed on `/` (policy note). |
| `cr.robots.key_page_disallowed` | access | medium | high | high | low | per-page | A `live_answer`/`index` token allowed on `/` but disallowed on a sampled key page. |
| `cr.access.http_error` | access | high | critical | high | medium | per-page | Sampled page final status ≥ 400 or transport error, not a challenge. Critical when home. |
| `cr.access.challenge_page` | access | info | info | high | n/a | per-page | Challenge fingerprint matched (status `inconclusive`). |
| `cr.access.non_html_seed` | access | critical | critical | high | medium | site | Home URL's final response is not HTML. |
| `cr.access.edge_block` | access | high | critical | high | medium | site | A `live_answer` or `index` crawler's published user agent is refused (status ≥ 400 or transport error) while the audit's own user agent is served 200. Critical when every probed citation-tier agent is refused. Only tokens the site's robots.txt allows for the home URL are announced; a disallowed token is the site's stated policy, reported by `cr.robots.*`, and is never probed. When no token could be announced the check is `not_evaluated` (`probe_tokens_disallowed`, or `robots_unreachable`). A transport **timeout** is not a refusal: a citation-tier token that hangs while the audit's own request was served is `inconclusive` (`probe_timeout`) with the curl check, never a fail. |
| `cr.access.edge_block_training` | access | info | info | high | n/a | site | Only `training_only` agents are refused at the edge (policy note, not a defect). |
| `cr.access.ua_content_variance` | access | info | info | low | n/a | site | Every probed agent is served 200, but a response body differs from the baseline by more than half its size. Informational: A/B tests and personalisation cause this too. |
| `cr.render.js_gate` | render | high | critical | high | high | per-page | Visible text < 60 words **and** any of: a `<noscript>` block mentioning JavaScript; body text matching "enable/requires/turn on JavaScript"; a `<body onload>` or inline script that submits a form (`document.forms[0].submit()`, the client-side-only redirect gate). A plain HTTP 3xx chain is never a gate. Critical when home. |
| `cr.render.csr_shell` | render | high | critical | medium | high | per-page | Two-signal rule: visible text < 60 words **and** (an empty framework root container **or** script bytes > 10× text bytes). Critical when home. |
| `cr.index.sitemap_missing` | render | low | medium | high | low | site | No `Sitemap:` in robots and `/sitemap.xml` (and `/sitemap_index.xml`) not 200. |
| `cr.index.sitemap_invalid` | render | medium | medium | high | low | site | Sitemap fetched but not parseable XML or contains zero `<loc>`. |
| `cr.index.noindex_on_key_page` | render | high | high | high | low | per-page | `<meta name="robots">` or `X-Robots-Tag` contains `noindex` on a key page. |
| `cr.index.canonical_offsite` | render | medium | medium | high | low | per-page | `rel=canonical` points to a different registrable domain. |
| `cr.index.canonical_mismatch` | render | low | low | medium | low | per-page | Canonical points to a different path on the same site that is not a trivial normalisation (slash, case, `www`). |

### fact-extractability-audit (`fx.*`)

| check_id | Stage | Sev | Max | Conf | Effort | Scope | Fails when |
|---|---|---|---|---|---|---|---|
| `fx.facts.key_fact_missing` | extract | high | high | medium | medium | site | A category key fact (`site_categories.md`) is `absent` or `partial`: found neither as plain text on any usable sampled page nor as a matching JSON-LD property. One finding listing all missing facts with what was found instead. Severity scales with how much of the fact set is unavailable: exactly one missing fact is `medium`, two or more is `high`. `pricing_or_trial` counts as present when the site states a price, a free tier/trial, **or** an explicit sales-led statement ("request a demo", "contact sales", "pricing on request"): a sales-led site is not defective, it has chosen not to publish prices. |
| `fx.facts.image_only` | extract | high | high | low | medium | per-page | A non-decorative image that **labels** a category key fact, on a page where that fact is expected (pricing: pricing/product/home; hours: contact/home/about/product; address: contact/about/home; menu: product/home), while the page text contains no equivalent (no currency amount, hours pattern, or address pattern). A label is a short alt (≤ 5 words), a filename token, or a preceding heading of ≤ 4 words; a caption or a headline that merely contains the word ("location pins on a street map", "Broadcom plans new vSphere") is not a signal, and a blog page is never graded. Confidence medium when two of the three signals agree, else low. |
| `fx.jsonld.missing` | extract | medium | medium | high | medium | site | No `application/ld+json` block on any sampled page. |
| `fx.jsonld.malformed` | extract | medium | medium | high | low | per-page | A `ld+json` block fails `json.loads`. |
| `fx.jsonld.required_props_missing` | extract | medium | medium | high | low | per-page | A **top-level** node (block root, list item, or `@graph` member) of a known type lacks its identifying properties (`auditlib/extract.py` `REQUIRED_PROPS`, documented in the fact-extractability references). Nested nodes are never graded. |
| `fx.jsonld.no_organization` | extract | low | medium | medium | low | site | JSON-LD exists but no `Organization` (or subtype) / `Person` for portfolios appears on home or about. |
| `fx.identity.title_missing_or_generic` | extract | medium | medium | high | low | per-page | `<title>` absent, empty, or in the generic list (`Home`, `Untitled`, `Welcome`, `Index`, domain only). |
| `fx.identity.h1_missing_or_multiple` | extract | low | low | high | low | per-page | Zero or more than one `<h1>`. |
| `fx.identity.meta_description_missing` | extract | low | low | high | low | per-page | No `<meta name="description">` or it is empty. |
| `fx.identity.og_missing` | extract | low | low | high | low | per-page | Neither `og:title` nor `og:description`. |
| `fx.media.alt_text_missing` | extract | low | low | high | medium | per-page | A sampled page has at least 3 content images (not decorative, not under 50px), at least 2 lack alt, and those are over 30% of the page's content images. Alt presence is not fact extractability (see fx.facts.image_only). |
| `fx.content.faq_absent` | extract | low | low | medium | medium | site | No `FAQPage` JSON-LD and no heading matching FAQ/questions patterns on any sampled page. Category-gated. |

### entity-freshness-corroboration-audit (`ef.*`)

| check_id | Stage | Sev | Max | Conf | Effort | Scope | Fails when |
|---|---|---|---|---|---|---|---|
| `ef.entity.sameas_missing` | entity | medium | medium | high | low | site | Organization/Person JSON-LD present but no `sameAs`. |
| `ef.entity.sameas_no_authority` | entity | low | low | high | low | site | `sameAs` present but none points to Wikidata, Wikipedia, LinkedIn, Crunchbase, a national company register, or a review/data authority (`auditlib/extract.py` `AUTHORITY_HOSTS`). For `portfolio_personal` a professional profile host (LinkedIn, GitHub, Behance, Dribbble, Instagram, …) also counts. |
| `ef.entity.wikidata_ambiguous` | entity | medium | medium | medium | medium | site | The one entity lookup (a robots-allowed Wikipedia article fetch for the brand name, or a verification of the site's own Wikipedia/Wikidata `sameAs` target) shows the name does not resolve to this brand: the article is a disambiguation page, or is about something else (it never mentions the site's domain), or the `sameAs` target's label and official website do not match the brand. Not raised when the site's `sameAs` already points at a matching entity. |
| `ef.entity.wikidata_not_found` | entity | low | low | low | high | site | The lookup target returns 404: no Wikipedia article under the brand name **nor under the shorter name the site also uses for itself** (a title segment beside a longer `og:site_name`; at most one extra title, so at most two requests), low confidence because this is a title lookup, not a search; or a `sameAs` anchor that points to a page that does not exist (medium confidence). |
| `ef.entity.wikidata_unavailable` | entity | info | info | high | n/a | site | The lookup did not run: network disabled, `--no-external`, robots.txt of the lookup host disallows the path, timeout, or an HTTP error (status `not_evaluated`; the info finding names the reason). Wikidata's search API is disallowed for generic agents by its robots.txt and is never called. |
| `ef.entity.nap_missing_plain_text` | entity | medium | high | high | low | site | The organisation name and its locator facts are not visible text on the home, contact or about page. Required: `local_business` name + postal address + phone; `portfolio_personal` name + a contact (email or phone); `unknown` name + any contact (address, phone or email), because the audit does not demand a postal address of a site it cannot classify; every other category name + (postal address or phone). Text inside JSON-LD or images does not count. The name component is skipped when the brand name could only be derived from the host. Category overrides apply. |
| `ef.entity.name_inconsistent` | entity | low | low | medium | low | site | Brand name differs across `<title>` site-name part, `og:site_name`, and JSON-LD `name` beyond case/punctuation. |
| `ef.freshness.no_visible_dates` | freshness | low | medium | medium | low | site | No visible date on any sampled page (blog dates, "updated" lines, copyright year). |
| `ef.freshness.stale_copyright_year` | freshness | low | low | high | low | site | Footer copyright year ≤ current year − 2. In a range the later year counts, and an open range (`2005–now`, `–present`) counts as the current year. |
| `ef.freshness.date_modified_mismatch` | freshness | low | low | medium | low | per-page | JSON-LD `dateModified`/`datePublished` differs from the visible date on the same page by > 30 days, or `dateModified` is in the future. |
| `ef.corroboration.press_page_missing` | corroboration | low | medium | medium | medium | site | No sampled page has the `blog` role, no internal link on a usable page has text matching press/news/newsroom/media/blog/updates/announcements/stories/insights/journal (or a first path segment among those), and no RSS/Atom feed is advertised. `mailto:` links never count. Category overrides apply. |
| `ef.corroboration.offsite_spotcheck` | corroboration | info | info | high | n/a | site | Agent step. When `work/offsite_mentions.json` exists the probe reports the count and kind of mentions as an `inconclusive` info finding (reason `bounded_spotcheck`); otherwise `not_evaluated` with reason `tool_unavailable` and the suggested queries. Never affects counts. |

### engagement-audit (`en.*`)

| check_id | Stage | Sev | Max | Conf | Effort | Scope | Fails when |
|---|---|---|---|---|---|---|---|
| `en.hero.value_prop_unclear` | engagement | medium | medium | low | medium | per-page | Home: no `<h1>` (or one with no text, image only), or the `<h1>` has < 3 or > 25 words, or the 120 words of visible body text starting at the `<h1>` (from the top when there is none) contain no category noun and no verb of offer (`auditlib/categories.py` `CATEGORY_NOUNS`, `OFFER_VERBS`). Two signals ⇒ medium confidence. |
| `en.cta.missing` | engagement | medium | medium | medium | low | per-page | On home and the category's key pages: no `<a>`/`<button>` whose text matches the category CTA vocabulary within the first 40% of the content markup (measured from the first visible content, not from `<body>`), and no non-search `<form>` there. `mailto:`/`tel:` links count where the vocabulary has email, contact or call. |
| `en.nav.landmark_missing` | engagement | low | medium | high | low | site | No `<nav>`, `role=navigation`, or a `<ul>` of ≥ 3 internal links inside `<header>`. Category cap. |
| `en.links.broken_sampled` | engagement | medium | medium | high | low | site | Of ≤ 15 sampled internal links (nav first, then header, body, footer; already-sampled pages reuse their status), ≥ 1 returns 404/410, a 5xx, or a transport error. 403/429 are never broken (see the cluster row). Evidence lists each. |
| `en.links.blocked_cluster` | engagement | info | info | high | n/a | site | ≥ 3 sampled links return 403/429 (or a bot challenge) from the same host: reclassified as fetcher-blocked (status `inconclusive`, reason `fetcher_blocked`), not broken. |
| `en.mobile.viewport_missing` | engagement | high | high | high | low | per-page | No `<meta name="viewport">`. Deterministic and breaks rendering for the majority-mobile segment, hence high. |
| `en.perf.page_weight_heavy` | engagement | low | low | low | medium | per-page | HTML bytes + declared `<script src>`/`<link rel=stylesheet>`/`<img>` count proxy exceeds thresholds (HTML > 1 MiB, or > 40 script tags, or > 100 images). Proxy: never above `low` confidence. |
| `en.trust.signals_missing` | engagement | medium | medium | medium | medium | site | None of the category's expected trust signals present on home, about, or contact. |
| `en.continuity.h1_title_mismatch` | engagement | low | low | medium | low | per-page | The `<h1>` shares no content word (≥ 4 letters, non-stopword) with the `<title>` or the meta description. Pages with no `<h1>` or a missing/generic title are skipped (`fx.identity.*` owns those). |
| `en.nav.breadcrumbs_missing` | engagement | low | low | high | low | site | No `BreadcrumbList` JSON-LD and no `nav[aria-label*=breadcrumb]`/`.breadcrumb` on non-home sampled pages. Category cap. |
| `en.nav.related_links_missing` | engagement | low | low | medium | medium | per-page | On product/blog detail pages, no heading matching related/similar/recommended/you may also like/read next, and < 3 same-site links (same registrable domain, so sibling subdomains count; outside nav, header and footer) in the second half of the body markup. Listing pages (two or more `<article>` elements, or six or more internal links inside lists in the content) are not graded: the list is the onward navigation. Category cap. |
| `en.nav.site_search_missing` | engagement | low | low | high | medium | site | No `<input type=search>`, `role=search`, or `<form>` with a `q`/`s`/`search` field on home. Category cap. |
| `en.interstitial.blocking` | engagement | medium | medium | medium | low | per-page | An element with a modal/overlay/popup/interstitial/cookie/consent/lightbox class or id, not hidden in the initial HTML (`hidden`, `aria-hidden`, inline `display:none`), holding > 40 words of text, that appears before the `<h1>` (or in the first 40% of the body when there is no `<h1>`). Inline `position:fixed/absolute` is recorded as evidence. |
| `en.lang.attribute_missing` | engagement | low | low | high | low | site | `<html>` has no `lang`. |
| `en.errors.soft_404` | engagement | medium | medium | high | medium | site | A request for a random non-existent path returns 200 with an HTML body. |
| `en.errors.unhelpful_404` | engagement | low | low | medium | low | site | The 404 page (status 404/410) lacks all of: a home link, a nav landmark, a search field. `not_evaluated` with reason `soft_404` when the site answers 200 for missing pages. |

### orchestrator (`or.*`)

| check_id | Stage | Sev | Max | Conf | Effort | Scope | Fails when |
|---|---|---|---|---|---|---|---|
| `or.simulation.question_unanswerable` | extract | info | info | high | n/a | site | A category simulation question cannot be answered from the extracted-facts file. One finding listing the questions. Informational; the real defect is already a `fx.*` finding. When no sampled page was readable at all the check is `not_evaluated` with reason `no_readable_pages` (or `facts_file_missing`) and its note says so: an unread site is unknown, not silent. |
| `or.run.probe_error` | — | info | info | high | n/a | site | A probe returned `error` non-null. Lists which. |

---

## 3. Retired ids

None yet.

---

## 4. Counts (kept in sync by hand when rows change)

| Skill | Checks |
|---|---|
| crawl-render-audit | 16 |
| fact-extractability-audit | 12 |
| entity-freshness-corroboration-audit | 12 |
| engagement-audit | 16 |
| orchestrator | 2 |

Discoverability (cr + fx + ef) = 40, engagement = 16. Step 12's parity target
means engagement must cover every heading in its SKILL.md description with at
least one row here, not that the raw counts must match.
