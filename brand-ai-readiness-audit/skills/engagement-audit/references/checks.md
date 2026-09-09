# engagement-audit: the 16 checks

Implementation: `scripts/engagement_probe.py`, with the served-HTML model in
`../../audit-orchestrator/scripts/auditlib/htmldoc.py` (markup positions,
landmarks, forms, overlays) and the category vocabularies in
`../../audit-orchestrator/scripts/auditlib/categories.py`. Defaults come from
the shared registry (`../../audit-orchestrator/references/check_ids.md`); this
file explains the rule behind each row, what evidence is captured, and why the
severity and confidence are set as they are. Stage: `engagement`, the second
half of the handout's brief: a visitor has already arrived, usually mid-journey
from an assistant's answer, on whatever page the answer linked. Does that page
tell them where they are, what is offered, and what to do next?

The probe reads served HTML only. It does not render, run scripts, or measure
load time. Where a check is therefore a proxy for the thing that matters, the
confidence says so and the wording is a risk flag, not a verdict.

---

## Which pages are graded

Pages are classified as in the other probes, with one difference: two tiers.

- **Usable**: fetched, not a bot-protection challenge, status below 400 with an
  HTML body, and not a JavaScript gate or client-rendered shell under the
  shared thin-page rule (`auditlib/render.py`). Content checks run only here.
- **Served HTML**: every usable page plus gates and shells. Head-level checks
  (viewport, lang, page weight) run here too: a shell page's `<head>` is real,
  and its weight is real.

Every other page is excluded with a reason (`robots_disallow`,
`challenge_page`, `http_error`, `network_disabled`, `non_html`,
`no_rendered_content`) and listed in `work/engagement.json` under
`pages_excluded`. When no page is usable, the content checks are
`not_evaluated` with one dominant reason (`robots_disallow` when the home page
was disallowed, `network_disabled`, `challenge_page`, `no_rendered_content`,
`non_html`, else `no_html_pages`); when no HTML was served at all, so are the
head and network checks.

Home is the anchor page for site-level checks (landmark, search, lang). When
home is not usable the first usable page stands in and the evidence names it.

Twelve check groups run in order, each guarded on its own: hero, cta, landmark,
search, breadcrumbs, related, trust, continuity, interstitial, viewport, lang,
weight, then links and errors (the two that make requests). If a group raises,
`error` names it, its checks become `not_evaluated` with reason
`dependency_failed`, and the rest stand.

## Category applicability

`site_categories.md` section 4 gates seven checks per category: `yes` (runs at
the registry default), `low` (runs, severity capped at `low`, recorded as
`category_cap:low` in the adjustments), or `no` (`not_evaluated`, reason
`not_applicable_for_category`). The table, mirrored in
`categories.py` `_CAP_ROWS`:

| check | ecommerce | saas | local | prof. services | publisher | portfolio | nonprofit | corporate | unknown |
|---|---|---|---|---|---|---|---|---|---|
| `en.nav.landmark_missing` | yes | yes | yes | yes | yes | low (no when ≤ 3 pages) | yes | yes | low |
| `en.nav.breadcrumbs_missing` | yes | low | no | no | yes | no | low | yes | no |
| `en.nav.site_search_missing` | yes | low | no | no | yes | no | low | yes | no |
| `en.nav.related_links_missing` | yes | low | no | no | yes | no | no | low | no |
| `en.cta.missing` | yes | yes | yes | yes | low | low | yes | low | low |
| `en.trust.signals_missing` | yes | yes | yes | yes | low | no | yes | low | low |
| `en.hero.value_prop_unclear` | yes | yes | yes | yes | low | yes | yes | yes | yes |

The other nine checks run at their defaults for every category.

---

## First viewport (stage `engagement`)

### `en.hero.value_prop_unclear` · medium · low, medium with two signals · per-page (home)
**Rule.** Graded on the home page only. Three signals, any one of which fails
the check:

- `h1_missing` / `h1_empty`: no `<h1>`, or the first `<h1>` holds no text (an
  image-only heading has no words a machine, or a screen reader, can use).
- `h1_too_short` / `h1_too_long`: the first `<h1>` with text has fewer than 3
  or more than 25 words.
- `lead_text_no_offer`: the 120 words of visible body text starting at that
  `<h1>` (from the top of the body when there is none) contain no category noun
  and no verb of offer. Nouns are the category's list in `CATEGORY_NOUNS`
  (`software`, `platform`, `app`, … for saas; `shop`, `store`, `product`, …
  for ecommerce; and so on, with an optional s/es/ing/ed suffix); verbs are the
  shared `OFFER_VERBS` list (`helps`, `build`, `make`, `send`, `track`, `shop`,
  `lets`, `allows`, …). A page that names either has said what it does.

**Evidence.** The `<h1>` text, the lead excerpt (first 120 words), and a
`computed` item `signals=…; category_noun=…; offer_verb=…`.
**Why medium, and why the confidence moves.** Most of a visit's attention lands
in the first screen; a visitor who cannot tell what the site offers leaves,
which wastes the click the assistant sent. This is the bouncing mode's most
common cause. Confidence is `low` with one signal (word counts and word lists
are heuristics) and `medium` with two independent ones, and the rubric's
confidence cap keeps severity at medium either way. Not graded when the home
page is not usable (reason: that page's exclusion reason, for example
`non_html`).

### `en.cta.missing` · medium · medium · per-page (home and key pages)
**Rule.** On the home page and the category's key pages, an element in the
**first 40% of the body markup** (`Document.body_frac`) counts as a call to
action when it is:

- an `<a>` or `<button>` whose text matches the category vocabulary
  (`CTA_VOCAB`: `sign up`, `start`, `try`, `get started`, `book a demo`,
  `request a demo`, `free trial` for saas; `shop`, `buy`, `add to cart`,
  `browse`, `order` for ecommerce; `book`, `call`, `directions`, `order`,
  `reserve`, `visit` for local businesses; `contact`, `talk to us`, `get a
  quote`, `schedule`, `consultation`, `book` for professional services;
  `subscribe`, `read`, `sign up`, `newsletter` for publishers; `contact`,
  `hire`, `email`, `view work` for portfolios; `donate`, `apply`, `volunteer`,
  `join`, `register` for nonprofits; `contact`, `learn more`, `explore`,
  `careers` for corporate; `contact`, `get started`, `learn more` otherwise);
- a `mailto:` link where the vocabulary has `email` or `contact`, or a `tel:`
  link where it has `call` or `contact`;
- a `<form>` that is not a search form (`role=search`, or only search-named
  inputs, never counts) and has at least one real input.

One finding lists every key page with no such element.
**Evidence.** Per failing page: the number of links seen in the first viewport
and a sample of their texts, so the reader can see what was there instead.
**Why medium.** A visitor who has just arrived needs one obvious next step;
with nothing actionable in view, attention has nowhere to go. Medium confidence
because the vocabulary is text-based: an icon button with no label is not seen.

**Language.** The page's declared `lang` (`Document.lang`, e.g. `de-CH` -> `de`)
selects which vocabulary is searched. English is always included; German,
French, Spanish, Italian, Portuguese and Dutch add their own words
(`CTA_VOCAB_BY_LANG` in `auditlib/categories.py`) so a German site's
"Anmelden" or "Abonnement" is recognised as a call to action rather than
missed because it is not in English. Measured: before this, spiegel.de failed
this check purely because its buttons are German.

A declared language outside that set (`CTA_LANGS_SUPPORTED`) has no vocabulary
to search, and the check does not guess: it reports `not_evaluated` with
reason `language_not_supported` rather than asserting "no call to action"
using words the page was never going to contain. No `lang` attribute at all
falls back to the English-only vocabulary, as before -- `en.lang.attribute_missing`
already reports the missing attribute separately.

---

## Orientation (stage `engagement`)

### `en.nav.landmark_missing` · low, up to medium · high · site
**Rule.** On the anchor page: no `<nav>` element, no `role="navigation"`, and
no list (`<ul>`/`<ol>`) inside `<header>` holding three or more distinct
internal links. For `portfolio_personal` sites with at most 3 internal pages
(`internal_pages_estimate` from the sample manifest) the check is
`not_evaluated`: a one-pager needs no menu.
**Evidence.** `nav_elements=0; role_navigation=0; header_list_links=n;
internal_links=n`.
**Why low, high confidence.** Deterministic. A visitor landing mid-site orients
by the menu; without a recognisable one the page reads as a dead end. Low
because most templates ship one, and the fix is wrapping existing links.

### `en.nav.breadcrumbs_missing` · low · high · site
**Rule.** No non-home usable page has breadcrumb markup (a `nav`, `ol`, `ul` or
`div` whose class, id or `aria-label` contains "breadcrumb") or `BreadcrumbList`
JSON-LD. Passes when any one has. `not_evaluated` (`only_home_sampled`) when
only the home page was usable.
**Evidence.** Per page: `breadcrumb_markup=…; BreadcrumbList=…`.
**Why low.** Visitors from an assistant land on inner pages; breadcrumbs say
where in the site they are and give a one-click way up. Low because navigation
and search cover most of the same need. Gated: not expected on local, service,
portfolio or unknown sites.

### `en.nav.related_links_missing` · low · medium · per-page (product and blog)
**Rule.** On the product and blog role pages that are **detail pages**: no
heading matching related / similar / recommended / you may also like / see also
/ read next / further reading / more from, and fewer than 3 same-site links
(same registrable domain, so `blog.example.com` counts from `www.example.com`;
context main, article, aside or body, never nav, header or footer) in the
second half of the body markup. **Listing pages are not graded**: two or more
`<article>` elements, or six or more same-site links inside lists in the
content, mean the page is itself the onward navigation (`listing_pages_only`
when every candidate is a listing; `no_product_or_blog_page` when neither role
was usable).
**Evidence.** Per page: `related_heading=none; trailing_internal_links=n`.
**Why low, medium confidence.** A page that ends without somewhere to go ends
the visit. Medium confidence because "the second half of the markup" is a
proxy for "after the content", and a related section can be built by script.

### `en.nav.site_search_missing` · low · high · site
**Rule.** On the anchor page: no `role="search"`, no `<input type="search">`,
and no form with an input named `q`, `s`, `search`, `query`, `keyword`,
`keywords` or `term`.
**Why low, high confidence.** Deterministic. Search is how a visitor with a
specific question reaches the answer without guessing the menu; low because it
matters on large sites (hence gated to ecommerce, publisher, corporate).

### `en.continuity.h1_title_mismatch` · low · medium · per-page
**Rule.** On every usable page that has an `<h1>` with text and a `<title>`
that is neither missing nor generic (`GENERIC_TITLES`: home, welcome, untitled,
index, …; `fx.identity.*` owns those cases, dedupe row 10): the `<h1>` shares
no content word (four or more letters, not a stopword) with the `<title>` or
the meta description. `not_evaluated` (`dependency_failed`) when no page could
be graded.
**Evidence.** Per failing page: `h1=…; title=…; shared_words=none`.
**Why low, medium confidence.** The assistant or search result shows the title
and description; a heading that says something else makes the visitor doubt
they are in the right place. Medium confidence because word overlap is a proxy
for meaning: a synonym reads as a mismatch.

---

## Friction (stage `engagement`)

### `en.interstitial.blocking` · medium · medium · per-page
**Rule.** An element whose class or id contains modal, overlay, popup,
interstitial, cookie, consent, lightbox or newsletter-popup, that is **not
hidden in the initial HTML** (no `hidden` attribute, no `aria-hidden="true"`,
no inline `display:none` or `visibility:hidden`), holds **more than 40 words**
of text, and appears **before the `<h1>`** (or in the first 40% of the body
when there is no `<h1>`).
**Evidence.** An `html_excerpt` of the opening tag with its inline style, the
word count, and the first 100 characters of its text; the note says whether
`position:fixed`/`absolute` was declared inline.
**Why medium, medium confidence.** A wall of text or a sign-up box that covers
the page before the visitor has read a word is the classic snap-judgement
bounce, and on a phone it is often the only thing on screen. Medium confidence
because the served HTML cannot show the stylesheet: an element named "modal"
may be positioned off-screen by CSS, so the finding is worded as what the
markup shows. A short cookie bar (40 words or fewer) never fires.

### `en.mobile.viewport_missing` · high · high · per-page (every served page)
**Rule.** A served HTML page has no `<meta name="viewport">`. Graded on gates
and shells too: their `<head>` is real.
**Evidence.** `meta_viewport=absent` per page.
**Why high, high confidence.** Deterministic, and the effect is total: without
the tag mobile browsers draw the page at desktop width and shrink it, so the
text is unreadable on arrival for the majority of visits. Blast radius raises
nothing further (high is the registered maximum).

### `en.perf.page_weight_heavy` · low · low · per-page (every served page)
**Rule.** A served page's HTML exceeds 1 MiB, or it declares more than 40
`<script>` elements (JSON-LD excluded), or more than 100 `<img>` elements.
**Evidence.** The threshold exceeded plus `external_scripts=n; stylesheets=n`.
**Why low, low confidence.** No load time was measured: this is a static proxy
for it. Each second of delay before the first screen loses a measurable share
of visitors, and script and image counts are the cheapest predictor of that a
static audit can see; but lazy-loaded embeds and deferred scripts inflate the
count without blocking render. Confidence is `low`, so priority is `low`, and
the action is to measure with a real performance tool.

### `en.lang.attribute_missing` · low · high · site
**Rule.** The anchor served page's `<html>` has no `lang` attribute.
**Why low, high confidence.** Deterministic. Screen readers, translation
features and some assistants use the declared language; without it text can be
voiced or translated wrongly. Low because the effect is on a minority of
visits, and the fix is one attribute.

---

## Trust (stage `engagement`)

### `en.trust.signals_missing` · medium · medium · site
**Rule.** On the usable home, about and contact pages, the category's expected
signals (`TRUST_SIGNALS`) are searched; at least one present passes. For
categories without a list, `terms_privacy_links` is required **and** at least
one of `address`, `named_people`, `testimonials_or_logos`.

| Category | Any one of |
|---|---|
| ecommerce | returns/refund policy link; payment or security badge; review markup or count; postal address |
| saas_software | testimonials or customer logos; security or compliance link; pricing transparency; terms and privacy links |
| local_business | postal address; phone; opening hours; review markup or count; photos of the premises |
| professional_services | team page with named people; clients or case studies; credentials or accreditations; postal address |
| nonprofit_institution | registration or charity number; financial or annual report link; named leadership; postal address |
| others | terms/privacy links **plus** any of address, named people, testimonials |

Detectors (English word lists): links whose text or path match terms/privacy/
legal/imprint; returns/refunds/exchanges; security/compliance/SOC 2/ISO 27001/
GDPR; team/people/leadership/founders; clients/case studies/our work. Text
matching review counts ("38 reviews", "4.6 out of 5", Trustpilot), payment
badges (Visa, PayPal, secure checkout), credentials (accredited, chartered,
licensed, member of), registration numbers ("company number 00000000",
"501(c)(3)"), financial reports. Images whose alt or filename match badge or
premises words. A `<blockquote>` of eight or more words, or a heading or text
matching "trusted by", "our customers", "testimonials", "case studies". The
shared address, phone, hours and price detectors from `extract.py`; pricing
transparency also passes when the sampled pricing page shows a currency amount.
**Evidence.** A `text_excerpt` for each signal found and a `computed` item
`pages_checked=…; rule=…; present=…; missing=…`.
**Why medium, medium confidence.** A visitor deciding whether to stay looks for
proof that others trust the site; when the landing pages show none, the offer
reads as unverified. Medium confidence because every detector is a word list:
a testimonial without a quote mark or a heading word is not seen, so the
finding names exactly what was searched. Gated off for portfolios; capped low
for publishers, corporate and unknown sites.

---

## Reliability (stage `engagement`, the two checks that make requests)

Both run only when the network is on (`--offline`, `--no-network` and
`BRAND_AUDIT_NETWORK=0` switch it off: every reliability check is then
`not_evaluated` with reason `network_disabled`, and one info note on
`en.links.broken_sampled` says so) and at least one page was served as HTML.
They share the audit's fetcher (in `--workdir` mode a fresh one, same policy),
spend at most 15 link requests plus one 404 probe, and stop sampling after 40
seconds of their own time (`not_checked`, reason `time_budget`).

### `en.links.broken_sampled` · medium · high · site
**Rule.** Up to 15 unique internal links are sampled from the usable pages,
home first, ordered by context (nav, then header, main and body, aside,
footer). Links to pages the sampler already fetched reuse that status without a
request. Each other link is fetched with a 10-second cap. A link is **broken**
when it returns 404 or 410, a 5xx, or a transport error (DNS failure, timeout,
connection refused, TLS error, too many redirects). Links robots.txt disallows
are `skipped`, never broken. 403 and 429 (and bot challenges) are `blocked`,
never broken (next row). Fails when at least one link is broken;
`not_evaluated` (`no_internal_links`) when the usable pages link nowhere.
**Evidence.** One `http_status` item per broken link (`GET url -> status`,
with the page and context it was found in) and a `computed` summary
`sampled=; requested=; ok=; broken=; blocked=; skipped=; not_checked=`.
**Why medium, high confidence.** Deterministic on the sample. A dead link is
the fastest way to lose a visitor who followed the site's own suggestion, and a
page the site links to but cannot serve is invisible to assistants too. The
sample is deterministic, so a re-run checks the same links.

### `en.links.blocked_cluster` · info · inconclusive · site
**Rule.** Three or more sampled links return 403 or 429 (or a fingerprinted
challenge) from the same host. They are reclassified as a fetcher block
(`inconclusive`, reason `fetcher_blocked`) and excluded from the broken count.
Fewer than three blocked links are listed in the summary and not counted
either way.
**Why info.** Links that reject a low-volume automated reader are not broken
for a person, so they must not be counted as broken; but assistants fetching
at answer time see the same refusal, so the block itself is worth a note.
This is the near-miss from the hardening research turned into a correct
diagnosis of a different problem.

### `en.errors.soft_404` · medium · high · site
**Rule.** One GET of a path that cannot exist
(`/brand-ai-readiness-audit-404-probe-<10 hex chars of the site's hash>`, the
same path on every run) returns HTTP 200 with an HTML body, after following
redirects. A redirect to the home page counts (the evidence says so).
`not_evaluated` when robots.txt disallows the path (`robots_disallow`), the
response is a challenge (`challenge_page`), the fetch fails (`fetch_error`) or
the status is something else (`unexpected_status`).
**Evidence.** `GET path -> 200 content-type`, the final URL, and the page's
`<title>`.
**Why medium, high confidence.** Deterministic. A visitor who follows a stale
link gets a page that looks like the site but is not what they wanted, with no
signal that anything is wrong; crawlers index the same nothing-page under every
dead URL, diluting the real pages.

### `en.errors.unhelpful_404` · low · medium · site
**Rule.** The probe path returns 404 or 410 and the page has none of: a link to
the home page, a navigation landmark (as `en.nav.landmark_missing` defines
it), a search field. A non-HTML or empty 404 body fails too. `not_evaluated`
with reason `soft_404` when the site answers 200 (there is no 404 page to
grade).
**Evidence.** `GET path -> 404` and `home_link=false; nav_landmark=false;
search=false; words=n`.
**Why low, medium confidence.** Visitors reach dead URLs from old links and
assistant answers; a bare not-found page ends the visit, one with the site's
navigation keeps it going. Medium confidence because the three signals are
structural: a 404 page with a prominent "back" button labelled in another
language would be missed.

---

## Adjustments the probe records

Every finding's `evidence_items` ends with a `computed` item
`adjustments=...` when the rubric changed the default: `non_key_pages:-1`,
`blast_radius:+1`, `confidence_cap:medium`, `category_cap:low`. A reader can
always see why a severity differs from the registry default.
