# entity-freshness-corroboration-audit: the 12 checks

Implementation: `scripts/entity_probe.py`, with the shared detectors in
`../../audit-orchestrator/scripts/auditlib/extract.py` (JSON-LD walking, brand
name, phone, address and date patterns). Defaults come from the shared
registry (`../../audit-orchestrator/references/check_ids.md`); this file
explains the rule behind each row, what evidence is captured, and why the
severity and confidence are set as they are. Stages: `entity` (handout
concept D: mistaken identity, and whether anything ties the site to one
real-world entity), `freshness` (B and D: what the page says at answer time,
and whether it can be shown to be current), `corroboration` (D: whether
independent sources can and do repeat the brand's facts).

The probe reads served HTML plus, at most, **one** external document: a
Wikipedia article or a Wikidata EntityData record, fetched with the audit's
own user agent under that host's robots.txt. It never searches. The off-site
spot-check is an agent step described in `offsite_spotcheck.md`; this script
only reads its result.

---

## Which pages are graded

A sampled page is **usable** under the same rule as the fact-extractability
skill: it was fetched (not skipped by robots.txt), was not a bot-protection
challenge, returned a status below 400 with an HTML body, and is not a
JavaScript gate or client-rendered shell under the shared thin-page rule
(`auditlib/render.py`). Every other page is excluded with a reason
(`robots_disallow`, `challenge_page`, `http_error`, `network_disabled`,
`non_html`, `no_rendered_content`) and listed in `work/entity.json` under
`pages_excluded`. Nothing on an excluded page is graded; the crawl-render
skill owns those findings.

When no page is usable, every check is `not_evaluated` with one dominant
reason (`robots_disallow` when the home page was disallowed, `network_disabled`
when every fetch was refused offline, `challenge_page` when every page was
challenged, `no_rendered_content` when any page was a gate or shell,
`non_html` when every page was non-HTML, otherwise `no_html_pages`). The
entity lookup is recorded as `skipped` with that reason, the off-site note is
still emitted, and `work/entity.json` is still written with `pages_used`
empty.

Seven check groups run in order: lookup, sameAs, NAP, name, freshness, press,
off-site. Each is guarded on its own: if one raises, `error` names it, its
checks become `not_evaluated` with reason `dependency_failed`, and the other
groups stand.

---

## Entity (stage `entity`)

### `ef.entity.sameas_missing` · medium · high · site
**Rule.** Organisation nodes are collected from the top-level JSON-LD nodes
(block root, list items, `@graph` members) of every usable page, home and
about first: any node whose `@type` is `Organization` or a subtype (every
`LocalBusiness` type, `Corporation`, `NGO`, `EducationalOrganization`,
`GovernmentOrganization`, …), plus `Person` for `portfolio_personal`. When
there are none, this check and `ef.entity.sameas_no_authority` are
`not_evaluated` with reason `dependency_failed` and produce no finding: the
fact-extractability skill already reports the missing markup
(`fx.jsonld.missing`, `fx.jsonld.no_organization`; dedupe row 6 in
`coverage_map.md`). Fires when no organisation node carries a `sameAs`
property, at any depth inside the node, holding at least one `http` URL.
**Evidence.** A `jsonld_excerpt` per node (up to three) with its `@type`,
`name` and `url` and the block position `script[type=application/ld+json][n]`.
When the entity lookup ran in discover mode and verified a Wikipedia article
about this brand, an `external` item names that article and its Q-id as a
ready-made target and the action's detail says to start with those two URLs.
**Why medium, high confidence.** Deterministic: the property is absent. `sameAs`
is the one machine-readable statement of which real-world entity this site
is; without it an assistant matches the brand by name alone, and names
collide. Not high, because the name may still resolve cleanly (the lookup
checks that); not low, because the fix is a one-line property with an
outsized effect on disambiguation.

### `ef.entity.sameas_no_authority` · low · high · site
**Rule.** `sameAs` is present but no URL's host contains an authority marker:
`wikidata.org`, `wikipedia.org`, `linkedin.com`, `crunchbase.com`,
`companieshouse`, `company-information.service.gov.uk`, `opencorporates.com`,
`sec.gov`, `dnb.com`, `bloomberg.com`, `glassdoor.com`, `g2.com`,
`trustpilot.com` (`auditlib/extract.py` `AUTHORITY_HOSTS`). For
`portfolio_personal` a professional-profile host also counts
(`PROFILE_HOSTS`: `linkedin.com`, `github.com`, `behance.net`,
`dribbble.com`, `instagram.com`, `twitter.com`, `x.com`, `facebook.com`,
`youtube.com`, `tiktok.com`, `vimeo.com`, `medium.com`, `substack.com`,
`mastodon`, `bsky.app`, `threads.net`, `pinterest.com`): a person's identity
is anchored by their profiles. `not_evaluated` (`dependency_failed`) when
`sameAs` is missing altogether.
**Evidence.** One `jsonld_excerpt` per `sameAs` URL (up to six); the sentence
lists the hosts.
**Why low.** The property exists and does part of its job. Social profiles
corroborate, but anyone can create one, so they do not pin a name to one
entity the way a company-register entry, a LinkedIn company page or a
Wikidata item does. The action keeps the social links and adds one
authoritative target.

### The entity lookup

One request decides the three `wikidata_*` checks. The mode depends on what
the site itself publishes:

| Mode | When | Request |
|---|---|---|
| `verify_wikipedia` | `sameAs` contains a `wikipedia.org` URL | That URL. |
| `verify_wikidata` | Otherwise, `sameAs` contains a `wikidata.org` URL with a Q-id | `https://www.wikidata.org/wiki/Special:EntityData/<Q-id>.json`. |
| `discover` | No such anchor | `https://en.wikipedia.org/wiki/<Title>`, where Title is the brand name with its first letter upper-cased and spaces as underscores (`plausible analytics` → `Plausible_analytics`). A title lookup, not a search. |

The brand name is resolved by the shared `brand_name` detector (JSON-LD
Organization or Person `name` on home or about, then `og:site_name` or
`application-name`, then a title segment repeated on at least two pages,
then the host label). When it has fewer than two letters the lookup is
`skipped` with reason `no_brand_name`.

The request uses the audit's own user agent, an 8-second timeout, that
host's robots.txt (fetched and obeyed like any other), and the shared request
budget (one content request plus that robots.txt). The result is saved to
`work/entity_lookup.json` and reused on every later `--workdir` run, so the
off-site re-run makes no external request. `--no-external` or
`BRAND_AUDIT_EXTERNAL=0` switches it off. The Wikidata search API is never
called: the only Wikidata document the audit may request is the EntityData
record for a Q-id the site itself published.

| Outcome | How it is decided | `wikidata_ambiguous` | `wikidata_not_found` | `wikidata_unavailable` |
|---|---|---|---|---|
| `verified` | discover: the page is an article (not a disambiguation page) and the site's registrable domain appears in it. verify_wikipedia: the target is an article. verify_wikidata: the item's English label or an alias equals the brand name (case, punctuation and legal suffixes ignored), or its official website (P856) is on the site's domain. | pass | pass | pass |
| `ambiguous` | discover: the page is a disambiguation page (`dmbox-disambig`, the disambiguation category). | **fail**, medium | pass | pass |
| `collision` | discover: an article, but the site's domain appears nowhere in it. | **fail**, medium | pass | pass |
| `mismatch` | verify_wikipedia: the site's own anchor is a disambiguation page. verify_wikidata: neither label, alias nor website matches. | **fail**, medium | pass | pass |
| `not_found` | HTTP 404, or Wikipedia's no-article marker. | pass | **fail**, low (discover) or medium (verifying an anchor) | pass |
| `unavailable` | `network_disabled` (`--offline`, `--no-external`), `robots_disallow` (the lookup host's robots.txt disallows the path for the audit's agent), `lookup_timeout`, `lookup_failed` (transport error, non-200, unparseable JSON). | `not_evaluated`, `lookup_unavailable` | `not_evaluated`, `lookup_unavailable` | `not_evaluated` with the reason, **plus an info finding** |
| `skipped` | `no_brand_name`, or no usable page (that reason). | `not_evaluated`, reason | `not_evaluated`, reason | `not_evaluated`, reason, no finding |

### `ef.entity.wikidata_ambiguous` · medium · medium · site
**Rule.** Lookup outcome `ambiguous`, `collision` or `mismatch`. Never raised
when the site's own `sameAs` resolves to a matching entity, whatever else
shares the name.
**Evidence.** One `external` item with the URL fetched, the outcome, the page
title and the Q-id. The sentence states the case: a disambiguation page with
about *n* entries and no matching `sameAs`; an article about something else
that never mentions the domain; or the label and website the anchor resolved
to.
**Why medium, medium confidence.** This is the mistaken-identity mechanism of
handout concept D observed directly: the best-documented entity under this
name is not this brand, and the site does not say which entity it is. Medium
confidence because one title lookup on one Wikipedia samples the name space
rather than measuring it, and a `collision` may simply be a more famous
namesake. The action never asks the brand to change its name; it asks the
site to publish the anchors that let the name resolve.

### `ef.entity.wikidata_not_found` · low · low, medium when verifying an anchor · site
**Rule.** Lookup outcome `not_found`.
**Evidence.** The URL and the 404.
**Why low.** Absence of an article under one exact title proves little: the
article may exist under another title, and most businesses have none.
Knowledge-graph entries are still what let an assistant describe a brand
with confidence, so the finding stays, at low confidence, with a Wikidata
action (Wikidata accepts organisations with a verifiable existence; a
Wikipedia article needs independent coverage first and is never the
suggested fix). When the site's own `sameAs` points at a page that does not
exist, the finding is a broken anchor at medium confidence and the action is
to fix the URL.

### `ef.entity.wikidata_unavailable` · info · not_evaluated · site
**Rule.** Lookup outcome `unavailable`. An info finding names the reason and
the request that did not run; the two dependent checks are `not_evaluated`
with reason `lookup_unavailable`.
**Why info.** Nothing about the site is proven either way. The note says what
was not checked and how to make it checkable (re-run with network access, or
without `--no-external`).

### `ef.entity.nap_missing_plain_text` · medium; high for local, low for saas, publisher, portfolio · high · site
**Rule.** The visible body text of the home, contact and about pages among
the usable pages (the first three usable pages when none of those roles was
usable) is searched for:

- **name**: the resolved brand name, compared after lowercasing, stripping
  legal suffixes (Ltd, Inc, LLC, GmbH, …) and non-alphanumerics; the first
  word of the name also counts when it has at least four characters. The name
  component is graded only when the site itself states a name (JSON-LD,
  `og:site_name`, a repeated title segment); a name guessed from the host
  label is not evidence, so it is dropped from the requirement and the
  `computed` item shows `required=` without it.
- **postal address**: a street pattern (a number, up to three capitalised
  words, and a street word in English, German, French, Spanish or Italian), a
  UK postcode preceded within 40 characters by a word, or a US city, state
  and ZIP.
- **phone**: 9–15 digits in phone layout that either start with `+` or follow
  a cue word within 30 characters (phone, tel, telephone, call, mobile, cell,
  whatsapp, fax, ph).
- **email**: an address pattern.

Required per category: `local_business` name, postal address and phone;
`portfolio_personal` name and a contact (email or phone); every other
category name and (postal address or phone). Text inside JSON-LD or images
does not count: this check is about what a reader cross-checking the brand
sees.
**Evidence.** A `text_excerpt` per component found (with the page it was on),
a `computed` item `pages_checked=…; required=…; missing=…`, and the
adjustments. Confidence is high when the contact or about page was among the
pages checked, medium otherwise (recorded as
`contact_and_about_not_sampled:confidence_medium`).
**Why, and why by category.** Name, address and phone are the triple every
directory, register and knowledge graph holds about a business; when the
site does not state them as text, an assistant cannot confirm it has the
right entity, and inconsistent copies elsewhere win. High for a walk-in
business, where the address is the product; low where the entity is a
software product, a publication or a person; medium otherwise. A JSON-LD
address still satisfies the fact-extractability skill's key-fact check on
local sites; compose folds that overlap (dedupe row 8).

### `ef.entity.name_inconsistent` · low · medium · site
**Rule.** Name candidates: `og:site_name` or `application-name` (the first
found, home then about); the `name` of every top-level Organization-family or
`Person` node on the usable pages (home and about first); and the title
segment (split on `|`, `—`, `–`, `-`, `:`) of one to four words shared by at
least two pages. Candidates are normalised as above. The check fails when two
distinct normalised names exist and neither contains the other:
"Ledgerly" and "Ledgerly Software Ltd" agree; "Ledgerly" and "LedgerPro
Software" do not.
**Evidence.** A `computed` item per distinct name with its source.
**Why low, medium confidence.** Entity resolution starts from the name: two
names on one site look like two brands, or a brand and a product, and the
assistant may cite either. Low because the fix is a naming decision, and
medium confidence because the title heuristic can pick up a product line
that the site legitimately markets under its own name.

---

## Freshness (stage `freshness`)

### `ef.freshness.no_visible_dates` · low; medium for publishers · medium · site
**Rule.** No usable page shows a date the audit can read: a `<time datetime>`
value that parses as a full date, an ISO date (`YYYY-MM-DD`) or a written
date (`7 September 2026`, `Sep 7, 2026`) in the body text, or a copyright
line with a year.
**Evidence.** A `computed` item per page: `time_elements`, `text_dates`,
`copyright_year`.
**Why low, medium confidence.** An assistant that fetches at answer time
prefers sources it can date; a site with no dates cannot be shown to be
current, so a dated copy elsewhere may be trusted over it. Medium confidence
because dates can be shown in formats the parser does not read (numeric
`07/09/2026`, non-English month names), so the finding is worded as "no date
the audit could read". Medium severity for `publisher_media`, where recency is
the product.

### `ef.freshness.stale_copyright_year` · low · high · site
**Rule.** At least one copyright line (`©`, `(c)` or "copyright" followed
within 40 characters by a year; the later year of a range counts) shows a
year at least two years behind the current year, and no page shows a
copyright year newer than that threshold.
**Evidence.** The copyright excerpt per page (up to four); the sentence names
the year and the current year.
**Why low, high confidence.** Deterministic and cheap. The footer year is the
first freshness signal a reader or a model notices; two or more years behind
reads as an abandoned site whatever the content says. Low because it says
nothing about the content itself, and it is a template fix.

### `ef.freshness.date_modified_mismatch` · low · medium · per-page
**Rule.** For each usable page, the `dateModified` (else `datePublished`) of
each top-level JSON-LD node is compared with the page's visible dates. Fails
when a JSON-LD date is more than one day in the future, or, when the page
shows visible dates, more than 30 days from the nearest one. A page with
JSON-LD dates and no visible date is not compared (only the future test
applies); a page with no JSON-LD dates is not graded.
**Evidence.** A `jsonld_excerpt` per mismatch: `<Type>.<property>=<value>`
with the gap and the nearest visible date, or "in the future".
**Why low, medium confidence.** When the machine-readable date and the
visible date disagree, neither can be trusted, and a future or long-past
`dateModified` reads as a template artefact rather than a real update. Medium
confidence because a page may legitimately show an older publication date
beside a newer modification stamp; the 30-day window absorbs most such cases.
Non-key pages take the page-role adjustment (already low, so unchanged).

---

## Corroboration (stage `corroboration`)

### `ef.corroboration.press_page_missing` · low; medium for corporate; not evaluated for portfolio and local · medium · site
**Rule.** Passes when any of these holds: the sampler found a page with the
blog/news role; an internal link (not `mailto:` or `tel:`) on a usable page
has text matching press, newsroom, news, media, blog, announcements, updates,
"in the press", "in the news", stories, insights or journal, or a first path
segment among `press`, `news`, `newsroom`, `media`, `blog`, `updates`,
`announcements`, `stories`, `insights`, `journal`, `press-releases`,
`pressroom`; or a page advertises an RSS or Atom feed. Otherwise fails.
`not_evaluated` with reason `not_applicable_for_category` for
`portfolio_personal` and `local_business`.
**Evidence.** A `computed` item per page: `press_links=0; feeds=n`.
**Why low, medium confidence.** Agreement across the web starts with a source
others can cite: a newsroom with dated announcements, a press contact and a
boilerplate paragraph is where journalists, directories and models pick up
consistent facts. Low because many good sites do without one; medium for
`corporate_enterprise`, where it is expected; medium confidence because the
surface may live under a label the pattern does not match. The action is
three items: a boilerplate paragraph, a press contact, a dated list.

### `ef.corroboration.offsite_spotcheck` · info · inconclusive or not_evaluated · site
**Rule.** This script does not search. It reads `work/offsite_mentions.json`,
written by the agent step in `offsite_spotcheck.md`. When the file is present
with a `mentions` list the check is `inconclusive` with reason
`bounded_spotcheck`: the title carries the mention and query counts, the
evidence tallies mentions by kind (`news`, `directory`, `review`, `social`,
`wiki`, `other`), says how many restate a fact from the site, and lists up to
six URLs. When the file is absent, or has no `mentions` list, the check is
`not_evaluated` with reason `tool_unavailable` and the evidence carries the
suggested queries (also written to `work/entity.json` as
`suggested_offsite_queries`).
**Why info.** At most five searches sample the corroboration surface; they
never measure agreement across the web, so the result is neither a defect nor
a pass, and it never affects the severity counts. Zero mentions is reported
as zero mentions, not as a finding against the site.

---

## Adjustments the probe records

Every finding's `evidence_items` ends with a `computed` item
`adjustments=...` when the rubric changed the default:
`category_override:<sev>`, `non_key_pages:-1`, `blast_radius:+1`,
`confidence_cap:medium`, `contact_and_about_not_sampled:confidence_medium`.
A reader can always see why a severity differs from the registry default.
