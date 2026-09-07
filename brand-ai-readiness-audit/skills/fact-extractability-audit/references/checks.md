# fact-extractability-audit: the 12 checks

Implementation: `scripts/facts_probe.py`, with the detectors in
`../../audit-orchestrator/scripts/auditlib/extract.py`. Defaults come from the
shared registry (`../../audit-orchestrator/references/check_ids.md`); this file
explains the rule behind each row, what evidence is captured, and why the
severity and confidence are set as they are. Stage: `extract` (handout
concepts A, B and C: once a crawler is in and can read the page, can it pick
out the specific fact a person would ask about?).

The probe reads served HTML only. "Extractable" means present as visible body
text, in the meta description, or in JSON-LD; a fact that only exists in an
image, a PDF, or content assembled by JavaScript is not extractable.

---

## Which pages are graded

A sampled page is **usable** when it was fetched (not skipped by robots.txt),
was not a bot-protection challenge, returned a status below 400 with an HTML
body, and is not a JavaScript gate or client-rendered shell under the shared
thin-page rule (`auditlib/render.py`: fewer than 60 visible words plus a gate
or shell signal, the same rule the crawl-render skill applies). Every other
page is excluded with a reason (`robots_disallow`, `challenge_page`,
`http_error`, `non_html`, `no_rendered_content`) and listed in the facts file
under `pages_excluded`. Nothing on an excluded page is graded; the crawl-render
skill owns those findings (dedupe rows 4 and 5 in `coverage_map.md`).

When the home page is disallowed by robots.txt nothing is fetched and every
check is `not_evaluated` with reason `robots_disallow`. When no page is usable
every check is `not_evaluated` with one dominant reason: `challenge_page` when
every excluded page was challenged, `no_rendered_content` when any page was a
gate or shell, `non_html` when every page was non-HTML, otherwise
`no_html_pages`. The facts file is still written, with `pages_used` empty.

Searchable text for a page is the visible body text, the meta description (or
`og:description`), and the leaf strings of its top-level JSON-LD nodes, capped
at 400,000 characters.

---

## Facts (stage `extract`)

### `fx.facts.key_fact_missing` · high · medium · site
**Rule.** For each key fact of the inferred category (`site_categories.md`
section 1; for example `what_it_does`, `pricing_or_trial`, `who_it_is_for`,
`contact_or_signup_method` for `saas_software`), a resolver runs over the
usable pages in a fixed order of detectors (`extracted_facts.md` section 4)
and returns `present`, `partial`, or `absent`. One finding fires when any
required fact is not `present`.
**Evidence.** A `computed` summary (pages searched, facts required, found,
missing); a `text_excerpt` for each partial fact showing the hint that was
found; a `text_excerpt` for each present fact with the page and the source it
came from, so the reader sees the negative space and not only the gap.
**Why high.** A fact that is absent, or present only as a hint, is a question
the brand cannot be quoted on, so the answer comes from a competitor or from
nowhere: the "invisible" mode. **Why medium confidence.** Regex detectors on a
sample of at most six pages can miss a fact phrased unusually or living on an
unsampled page; the evidence lists the pages searched so the owner can point
to the page that has it. The action names a concrete fix per missing fact and
the JSON-LD property to mirror it in.
**The pricing rule.** `pricing_or_trial` is `present` with a currency amount,
a free-tier statement ("free plan", "free forever"), or an explicit sales-led
statement ("request a demo", "contact sales", "pricing on request") on the
pricing, product or home page, or anywhere when the site has no pricing page.
A free-trial mention alone is `partial` with kind `trial_only`, and the
evidence says so in words: "a free-trial mention but no price, free tier, or
sales-led path". Sales-led sites are never flagged for withholding prices.
**Never fires for** the optional facts `audience` and `differentiator`, or for
`address` and `phone` outside `local_business` (the entity skill owns NAP).

### `fx.facts.image_only` · high, medium when not a key fact · low, medium with two signals · per-page
**Rule.** A content image (not `role=presentation`, not `alt=""`, not under
50 px in a declared dimension) whose `alt`, filename, or nearest preceding
heading contains fact words for **pricing** (price, prices, pricing, plan(s),
rate(s), fee(s), tariff(s), cost(s), package(s)), **hours** (hours, opening,
opening times, schedule, timetable), **address** (address, location,
directions, find us, where we are, map) or **menu** (menu, specials, dishes,
wine list), on a page whose text has no equivalent: no currency amount for
pricing, no hours pattern for hours, no street, UK postcode or US
city-state-zip pattern for address, fewer than six h2/h3 headings for menu.
"specs" words (specifications, datasheet, comparison, features table) never
produce a finding: feature grids are usually decorative. One finding per page.
**Evidence.** An `html_excerpt` per image (up to four) with the signals that
matched and the heading above it, plus a `computed` item with the page's
visible word count and whether any price text was found.
**Why a proxy.** The audit did not read the pixels. With one signal the
confidence is `low` (rubric: a single heuristic signal) and the rubric's
confidence cap holds the severity at medium. When two of the three signals
agree (alt and filename both say "pricing") confidence is `medium` and the
severity stands. Severity is high when the fact is one of the category's key
facts, otherwise medium, recorded as `adjustments=non_key_fact:medium`. The
action is to reproduce the same information as an HTML table or list under
the image, keeping the image.

## Structured data (stage `extract`)

### `fx.jsonld.missing` · medium · high · site
**Rule.** No `<script type="application/ld+json">` block on any usable page.
The three dependent checks (`fx.jsonld.malformed`,
`fx.jsonld.required_props_missing`, `fx.jsonld.no_organization`) become
`not_evaluated` with reason `dependency_failed` and produce no finding.
**Evidence.** A `computed` item per page: `jsonld_blocks=0`. When Microdata or
RDFa attributes (`itemtype`, `typeof`, `vocab`) are present on any page the
evidence says so, confidence drops to `medium`, and an evidence item asks the
owner to validate that markup separately: this audit parses JSON-LD only.
**Why medium.** Structured data is the one place a brand states its identity,
offers and contact details in a form every machine parses the same way, and
it is what current documentation from assistants and search engines asks for.
It is supporting, not sufficient: the plain-text facts still matter most, so
this is not high. The action starts with one Organization block on the home
page and grows from there.

### `fx.jsonld.malformed` · medium · high · per-page
**Rule.** A block fails `json.loads`.
**Evidence.** A `jsonld_excerpt` of the block's last 160 characters (where
trailing-comma and truncation errors live) with the parser's message and the
block's position `script[type=application/ld+json][n]`.
**Why medium, high confidence.** Deterministic. Validators and crawlers drop
unparseable JSON silently, so whatever the block was meant to say is not said;
the failure is invisible in a browser, so it persists. A malformed block is
not also graded for required properties (dedupe row 7).

### `fx.jsonld.required_props_missing` · medium · high · per-page
**Rule.** A **top-level** node (the block root, each item of a top-level
list, each `@graph` member) of a known type lacks a required property, or
satisfies none of an any-of group. Type resolution: an exact entry in the
table below first, then any LocalBusiness subtype maps to `LocalBusiness`,
then any Organization subtype maps to `Organization`; other types are not
graded. Nested nodes (an `Offer` inside a `Product`, a `publisher` inside an
`Article`) are never graded: they describe a property of their parent, and
grading them produces the long lists of nagging that make structured-data
reports unread.

| Type | Required | Any one of |
|---|---|---|
| `Organization` (and subtypes) | `name`, `url` | — |
| `LocalBusiness` (and subtypes) | `name`, `address` | — |
| `Person` | `name` | — |
| `SoftwareApplication`, `WebApplication`, `MobileApplication` | `name` | `offers`, `aggregateRating`, `review` |
| `Product` | `name` | `offers`, `aggregateRating`, `review` |
| `Service` | `name` | — |
| `Article`, `NewsArticle`, `BlogPosting`, `TechArticle` | `headline` | — |
| `FAQPage` | `mainEntity` | — |
| `BreadcrumbList`, `ItemList` | `itemListElement` | — |
| `Event` | `name`, `startDate`, `location` | — |
| `JobPosting` | `title`, `description`, `datePosted`, `hiringOrganization`, `jobLocation` | — |
| `Recipe` | `name`, `image` | — |
| `VideoObject` | `name`, `thumbnailUrl`, `uploadDate` | — |
| `Review` | `itemReviewed` | `reviewRating`, `reviewBody` |
| `WebSite` | `url` | — |
| `Course` | `name`, `description` | — |
| `Book` | `name` | — |

The lists follow the identifying properties in schema.org and the search
engines' structured-data documentation, trimmed to what a machine needs to
name and match the thing. Recommended properties (`logo`, `sameAs`,
`dateModified`, …) are never a finding; they are written to the facts file
under `jsonld_recommendations` for the orchestrator's proactive section.
**Evidence.** A `jsonld_excerpt` per node (up to four) showing its first six
scalar properties, the block position, and the missing properties.
**Why medium.** A node without its identifying properties tells a machine that
something exists but not what it is called or what it offers, so it cannot be
matched to the brand or quoted.

### `fx.jsonld.no_organization` · low · medium · site
**Rule.** JSON-LD exists, but no top-level node on the home or about page (or
the first usable page when neither was sampled) is an `Organization`, one of
its subtypes (including every LocalBusiness type, `NGO`, `Corporation`,
`EducationalOrganization`, …), or, for `portfolio_personal` only, a `Person`.
A `publisher` nested inside an `Article` or `WebSite` does not count: it
describes that page's publisher, not a standalone statement of who owns the
site.
**Evidence.** The set of types found across all pages and a `computed` item per
anchor page with its types.
**Why low, medium confidence.** Page-level markup floats unattached to an
entity, which matters for disambiguation more than for extraction; the entity
skill grades the consequences (`sameAs`, name consistency). Medium confidence
because the Organization node may live on a page that was not sampled.

## Identity (stage `extract`)

### `fx.identity.title_missing_or_generic` · medium · high · per-page
**Rule.** `<title>` is absent or empty, shorter than three characters, equal to
the host name, or in the generic list: home, home page, homepage, untitled,
untitled document, welcome, index, new page, default, page, site, website,
document.
**Evidence.** An `html_excerpt` with the title element per page.
**Why medium.** The title is the first thing an indexer and an assistant use
to say what a page is; "Home" makes the page anonymous in any list of sources.
Length, duplication across pages and keyword quality are not graded.

### `fx.identity.h1_missing_or_multiple` · low · high · per-page
**Rule.** The page has zero or more than one `<h1>`.
**Evidence.** A `computed` item `h1_count=n` per page; the title says whether
the pattern is "no h1", "multiple h1" or mixed.
**Why low.** A single main heading is how a machine decides what the page is
about; zero leaves it guessing and several compete. Low because modern
extractors cope, and because HTML5 sectioning legitimately produces more than
one `h1` on some templates. The continuity check in the engagement skill
depends on this one (dedupe row 10).

### `fx.identity.meta_description_missing` · low · high · per-page
**Rule.** No `<meta name="description">`, or its content is empty.
**Why low.** A ready-made one-sentence summary that indexers and some
assistants quote directly; without it they improvise from whatever text comes
first. The description is also the first place `what_it_does` is looked for.

### `fx.identity.og_missing` · low · high · per-page
**Rule.** Neither `og:title` nor `og:description` is present. Other Open Graph
properties (`og:image`, `og:type`) and Twitter cards are not graded.
**Why low.** A second self-description that link previews and some fetchers
read when the title is ambiguous. Cheap to add, small effect.

## Media (stage `extract`)

### `fx.media.alt_text_missing` · low · high · per-page
**Rule.** A usable page has at least three content images (not
`role=presentation`, not `alt=""`, not under 50 px in a declared dimension),
at least two of them have no `alt` attribute, and those are more than 30% of
the page's content images.
**Evidence.** `images=n; missing_alt=m` per page.
**Why low, and why the thresholds.** Alt text is the only text a non-visual
reader gets from an image, so when product shots, charts or infographics carry
facts, missing alt removes them from what can be extracted. It is low because
most images do not carry facts; the thresholds exist so that one untagged
image on a two-image page is not a finding. Alt presence is not fact
extractability: an image with `alt="Pricing plans"` still hides the prices,
which is `fx.facts.image_only`'s job.

## Content (stage `extract`)

### `fx.content.faq_absent` · low · medium · site
**Rule.** No usable page has a top-level `FAQPage` JSON-LD node, a heading
matching FAQ words (faq, frequently asked, common questions, questions and
answers, Q&A, got questions, your questions), or three or more h2–h4 headings
ending in a question mark. `not_evaluated` with reason
`not_applicable_for_category` for `publisher_media` and `portfolio_personal`
(`site_categories.md` section 5).
**Evidence.** A `computed` item per page with the three signals.
**Why low, medium confidence.** An opportunity rather than a defect:
assistants answer questions, and content already shaped as question and
answer is the easiest to quote verbatim. Medium confidence because a site can
answer its customers' questions in prose without any FAQ shape; the finding
says what would make that content easier to quote.

---

## Adjustments the probe records

Every finding's `evidence_items` ends with a `computed` item
`adjustments=...` when the rubric changed the default: `non_key_pages:-1`,
`blast_radius:+1`, `confidence_cap:medium`, `category_override:<sev>`,
`non_key_fact:medium`. A reader can always see why a severity differs from
the registry default.
