# engagement-audit: explicit non-findings and limits

Things this skill sees and deliberately does **not** flag. Each is a real
pattern on production sites that a naive checker misreports. Stating them is
part of the detection-accuracy contract: few false positives, and no finding
that tells a business to change a legitimate design choice.

| Condition | Why it is not a finding | What the report says instead |
|---|---|---|
| **A deliberately minimal one-page site** (a portfolio, a campaign page) with no menu | An intentional design, not disorientation. | `en.nav.landmark_missing` is `not_evaluated` for a `portfolio_personal` site with at most 3 internal pages; capped at `low` for portfolios and unknown sites otherwise. Breadcrumbs, search and related links are not applicable to portfolios at all. |
| **A search form in the first viewport** | Searching is not the visitor's next step in the journey; it is a tool. | Never counts as a call to action. `en.cta.missing` looks for the category's action vocabulary, a `mailto:`/`tel:` link, or a real (non-search) form. |
| **A call to action below the first 40% of the page** | It exists, and a scrolling visitor finds it; the finding is about the first screen. | Nothing when any key page has one in the first viewport region. The evidence lists what was in the first viewport of the pages that do not. |
| **A listing page** (a shop category, a blog index, a newsroom) without a "related" section | The list is the onward navigation. | Pages with two or more `<article>` elements, or six or more same-site links inside lists in the content, are not graded by `en.nav.related_links_missing` (`listing_pages_only` when every candidate is one). |
| **Onward links that go to a sibling subdomain** (`blog.example.com` from `www.example.com`) | The same site to a visitor. | Same-registrable-domain links count for `en.nav.related_links_missing`. The link sample stays same-host, because the fetch policy allows only the audited host. |
| **Breadcrumbs absent on a local business, a service firm, a portfolio, or an unknown-category site** | Small sites with a flat structure do not need them. | `not_evaluated`, reason `not_applicable_for_category`. |
| **Site search absent on a small site** | Search pays off with many pages; a ten-page site is navigated by its menu. | Gated: expected only on ecommerce, publisher and corporate sites; `low` for saas and nonprofit; not applicable elsewhere. |
| **A short cookie or consent bar** | A one-line notice does not cover the content. | `en.interstitial.blocking` needs more than 40 words inside the element. |
| **A newsletter or promotional dialog hidden in the initial HTML** (`hidden`, `aria-hidden="true"`, inline `display:none`) and revealed later by script | It is not on screen when the page arrives; timing after that is the site's choice. | Not a finding. Only overlays visible in the served HTML before the heading fire. |
| **An overlay named "modal" that appears after the `<h1>`** | The visitor has read the heading first; the design decision is theirs. | Nothing. Only overlays positioned before the `<h1>` (or in the first 40% of the body when there is none) are graded. |
| **A heading that is short because the brand name is the heading** ("Acme") | The lead text below it may still name the offer. | One signal only (word count); `low` confidence; and if the lead text names a category noun or an offer verb the finding says the text does name the offer. Never above medium severity. |
| **A page whose title is missing or generic** ("Home") and whose `<h1>` therefore matches nothing | The title is the defect, and `fx.identity.title_missing_or_generic` already reports it. | `en.continuity.h1_title_mismatch` skips the page (dedupe row 10). |
| **An image-only `<h1>`** (a logo wrapped in a heading) | There is no text to compare or to read the offer from. | Treated as a heading with no text: `h1_empty` for the hero check, skipped by the continuity check. |
| **Heavy pages by count alone** (a gallery with 120 lazy-loaded thumbnails, a page with many deferred analytics tags) | The static proxy cannot tell render-blocking assets from deferred or lazy ones. | `en.perf.page_weight_heavy` is `low` severity at `low` confidence, `priority` low, and the action is to measure load time with a real tool before changing anything. |
| **Links that answer 403 or 429 to the audit** | A user-agent allowlist or rate limit aimed at unknown clients, not a broken link. | Never counted as broken. Three or more from one host become `en.links.blocked_cluster`, an `inconclusive` info note that also tells the owner assistants may be refused the same way. |
| **A link robots.txt disallows for the audit** | Not fetched, so not judged. | Listed as `skipped` in the summary; not broken. |
| **An internal link the sampler already fetched** (nav links to the sampled pages) | Its status is already known. | Reused without a request, so the 15-request budget goes to links not yet seen. |
| **A 404 page reached by a redirect to the home page** | The visitor sees the home page with a 200, which is a soft 404 in every crawler's book. | `en.errors.soft_404` fires, and the evidence names the redirect. |
| **A 410 for the probe path** | "Gone" is a real not-found status. | `en.errors.soft_404` passes; the 410 page is graded for helpfulness like a 404 page. |
| **A site that answers 200 for missing pages** and therefore has no 404 page | There is nothing to grade for helpfulness; the soft 404 is the finding. | `en.errors.unhelpful_404` is `not_evaluated` with reason `soft_404`. |
| **Missing viewport or lang on a page that was excluded** (challenged, non-HTML, disallowed) | Nothing was served to read. | `not_evaluated` with the exclusion reason. Gates and shells are graded: their `<head>` is real. |
| **Testimonials, badges or policies that exist on a page outside home, about and contact** | The trust check reads the pages a visitor lands on first. | The finding names the pages checked; the action is to surface the signals there. |
| **Pages that are a JavaScript gate or client-rendered shell** | There is no content to grade; one finding should say so. | Content checks are `not_evaluated` with reason `no_rendered_content`; `cr.render.js_gate` / `cr.render.csr_shell` own the finding (dedupe row 4). Head-level and 404 checks still run. |

## What a non-rendering audit cannot know

- **Icon-only calls to action.** The CTA vocabulary is text: a button that is
  an icon with no label is not seen. This is why `en.cta.missing` is `medium`
  confidence, never high, and its evidence lists the link texts that were in
  the first viewport so the owner can point to the button that was missed.
- **Calls to action in a language we have no vocabulary for.** English,
  German, French, Spanish, Italian, Portuguese and Dutch are covered
  (`CTA_LANGS_SUPPORTED` in `auditlib/categories.py`), selected by the page's
  declared `lang`. A declared language outside that set makes `en.cta.missing`
  `not_evaluated` with reason `language_not_supported` instead of asserting
  absence with the wrong words -- visible in the report's check statuses, not
  as a separate limitation line. A page with **no** `lang` attribute at all
  falls back to English only, and `en.lang.attribute_missing` reports the
  missing attribute as its own, separate finding.
- **Where things are on screen.** "First 40% of the body markup" and "before
  the `<h1>`" are markup positions, not pixels. Fixed headers, CSS reordering
  and grid layouts can put an element elsewhere than its position in the
  source suggests. This is why the CTA and interstitial checks are `medium`
  confidence, never high.
- **Load time.** Never measured; the weight proxy is a count.
- **Whether an overlay is really on top.** Inline `position:fixed` is recorded
  when present; a stylesheet is never read.
- **Trust signals expressed without the words.** Every trust detector is a word
  list; a testimonial with no quote mark and no heading, or a badge drawn in
  CSS, is missed. The finding always says which pages and signals were
  searched.
- **Only sampled pages and sampled links.** Home plus up to five role pages,
  and at most 15 links from them. A broken link elsewhere is not seen; the
  sample is deterministic so a re-run checks the same links, and every finding
  lists the pages it applies to.
- **One point in time.** Personalised or A/B-tested pages may show a different
  first viewport on the next fetch; the orchestrator's limitations say so.
