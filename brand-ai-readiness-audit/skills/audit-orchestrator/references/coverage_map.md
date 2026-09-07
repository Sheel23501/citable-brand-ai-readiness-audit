# Coverage map: handout concepts A–F, audit stages, dedupe, non-coverage (shared convention)

Why the audit is organised the way it is, which handout concept each check is
evidence for, what overlaps and how compose resolves them, and what the audit
deliberately does not claim. The README's "Limitations and coverage" section
(Step 21) is generated from sections 1, 2 and 5 of this file.

The letters **A–F** in this file are the Round-2 appendix concepts from the
official Round 3 handout ("Appendix — Background Concepts"). They are never
used for anything else. Our own grouping of checks is called a **stage** and
uses words, never letters (section 2).

---

## 1. Handout concepts A–F and what the audit does about each

| Letter | Handout concept (paraphrased) | What it implies for a site audit | Coverage | Stages that supply evidence |
|---|---|---|---|---|
| **A** | **How search visibility works.** A crawler must be let in, must be able to read the page, and must be able to pick out the specific fact. Fail any one and the page does not exist for that system. | Three ordered gates: permission and reachability; text present without a browser; facts stated explicitly. | **Covered.** This is the spine of the discoverability half. | `access`, `render`, `extract` |
| **B** | **How assistants use sources.** Many assistants search and fetch a few pages at answer time; the pages chosen are the ones a machine can easily reach, read, and quote a clear fact from. | Grade robots.txt by bot *tier* (live-answer and index bots matter at answer time; training bots do not). Prefer quotable, self-contained facts (FAQ-shaped, plain sentences, structured data). | **Covered.** `bot_tiers.md` exists because of this concept. | `access` (tiered robots), `extract` (quotable facts, FAQ, JSON-LD), `freshness` (what the page says *at that moment*) |
| **C** | **How machines read a page.** Content assembled after load, or locked in a non-textual form, is invisible to a simple reader. The more explicit and plain the text, the more likely correct extraction. | Detect client-side rendering and JS gates; detect facts that exist only in images or PDFs; check that identity text (title, H1, description) exists in the HTML. | **Covered.** | `render`, `extract` |
| **D** | **Why agreement across the web matters.** Facts repeated consistently across independent sources are trusted; a claim in one place is fragile. Mistaken identity when names collide unless something disambiguates. | Check the disambiguation anchors the site itself controls (`sameAs`, Wikidata link, consistent name and NAP), the corroboration surface it offers (press/newsroom), and, when a search tool exists, a bounded off-site spot-check. | **Partial by design.** We can verify the site's own anchors deterministically; off-site agreement is an agent step with a `not_evaluated` fallback. | `entity`, `corroboration` |
| **E** | **Personalization and prior context.** Assistants weight answers by the user's conversation, preferences, and location, so two people get different brands. | Not observable from the site. The only site-side levers are explicit facts that let an assistant match a user's context: location and service area, language, audience ("who it is for"). | **Out of scope, stated.** We report the site-side levers as facts present/absent under `extract` and `entity`; we never claim to measure personalization. | `extract` (`who_it_is_for`, `location_or_service_area`), `entity` (NAP), `engagement` (`lang`) |
| **F** | **Why machines drop content from emails.** Summaries are built from readable text; substance carried in unreadable form or buried in filler disappears. | Email is outside a website audit. The same mechanism on a web page is "substance not in readable text, or buried": the hero test, image-only facts, and interstitials that push content down. | **Out of scope for email, stated.** The web analogue is covered under `render`, `extract`, and `engagement`. | `engagement` (hero clarity, interstitials), `extract` (image-only facts) |

Round-2 framing used in the narrative summary: **invisible** (A, B, C),
**stale or mistrusted** (B freshness, D), **bouncing** (the engagement half).
Every finding's `why_it_matters` names one of these three words.

## 2. Stages (our grouping) and the check-to-stage map

A `stage` is the value of the `mechanism` field on every finding
(`report_schema.md`). Seven values. A stage is `evaluated` in a report when
every non-gated check in its row ran with status `pass` or `fail`; `partial`
when at least one was `inconclusive` or `not_evaluated` for a reason other
than `not_applicable_for_category`; `not_evaluated` when none ran.

| Stage | Question it answers | Handout | Owning skill | Checks |
|---|---|---|---|---|
| `access` | Is a non-browser fetcher permitted and able to obtain an HTML response for the pages that matter? | A, B | crawl-render-audit | `cr.robots.unreachable`, `cr.robots.blanket_disallow`, `cr.robots.live_answer_bot_blocked`, `cr.robots.index_bot_blocked`, `cr.robots.training_bot_blocked`, `cr.robots.key_page_disallowed`, `cr.access.http_error`, `cr.access.challenge_page`, `cr.access.non_html_seed` |
| `render` | Is the substantive text in the response without executing JavaScript, and is the page allowed to be indexed and attributed to the right URL? | A, C | crawl-render-audit | `cr.render.js_gate`, `cr.render.csr_shell`, `cr.index.sitemap_missing`, `cr.index.sitemap_invalid`, `cr.index.noindex_on_key_page`, `cr.index.canonical_offsite`, `cr.index.canonical_mismatch` |
| `extract` | Can a machine pick out the specific facts a person would ask about, from text or structured data rather than images or layout? | A, B, C, (E, F) | fact-extractability-audit | `fx.facts.key_fact_missing`, `fx.facts.image_only`, `fx.jsonld.missing`, `fx.jsonld.malformed`, `fx.jsonld.required_props_missing`, `fx.jsonld.no_organization`, `fx.identity.title_missing_or_generic`, `fx.identity.h1_missing_or_multiple`, `fx.identity.meta_description_missing`, `fx.identity.og_missing`, `fx.media.alt_text_missing`, `fx.content.faq_absent`, `or.simulation.question_unanswerable` |
| `entity` | Can the assistant tell this brand apart from other things with the same name and connect the site to the right entity? | D, (E) | entity-freshness-corroboration-audit | `ef.entity.sameas_missing`, `ef.entity.sameas_no_authority`, `ef.entity.wikidata_ambiguous`, `ef.entity.wikidata_not_found`, `ef.entity.wikidata_unavailable`, `ef.entity.nap_missing_plain_text`, `ef.entity.name_inconsistent` |
| `freshness` | Are there signals that the facts are current, so an assistant fetching at answer time prefers them over stale copies? | B, D | entity-freshness-corroboration-audit | `ef.freshness.no_visible_dates`, `ef.freshness.stale_copyright_year`, `ef.freshness.date_modified_mismatch` |
| `corroboration` | Does the site offer a surface for off-site agreement, and does any exist? | D | entity-freshness-corroboration-audit | `ef.corroboration.press_page_missing`, `ef.corroboration.offsite_spotcheck` |
| `engagement` | When a visitor arrives, often mid-journey from an AI answer onto a deep page, can they orient, understand the offer, trust it, and act? | (F analogue) | engagement-audit | all `en.*` |

`or.run.probe_error` has no stage (`mechanism: null`); it is run metadata.

## 3. Why the probe boundaries sit where they do

- **`access` and `render` share a skill** because both are answered from the same raw fetch and the same robots parse; splitting them would fetch twice.
- **`extract` is alone** because it is the only probe that writes a side artifact (`work/extracted_facts.json`) consumed by the orchestrator's simulation, and its rules are category-heavy.
- **`entity`, `freshness`, `corroboration` share a skill** because all three are about trust rather than access, all read the same Organization JSON-LD, and the corroboration agent step needs the entity name the entity checks resolve.
- **`engagement` is alone** because it is the other half of the problem statement and is graded against category caps rather than crawl mechanics.

This is the separation-of-concerns argument for the rubric's "marketplace
composition" line: four probes, each with a distinct input artifact or output
artifact, none of which could be folded into another without re-fetching or
mixing grading rules.

## 4. Overlap and dedupe table (compose applies exactly this, in order)

Two probes can legitimately observe the same root cause from different angles.
Compose keeps the finding closest to the root cause (the earlier stage in the
order `access` → `render` → `extract` → `entity` → `freshness` →
`corroboration` → `engagement`) and folds the rest into `suppressed_findings`
with `merged_into` set, appending a one-line note to the primary's evidence.
Nothing is deleted.

| # | Primary (kept) | Suppressed | Condition | Note appended to primary |
|---|---|---|---|---|
| 1 | `cr.access.challenge_page` on page P | every other per-page finding on P | always | `downstream checks on this page are inconclusive` |
| 2 | `cr.robots.blanket_disallow` | `cr.robots.live_answer_bot_blocked`, `cr.robots.index_bot_blocked`, `cr.robots.training_bot_blocked`, `cr.robots.key_page_disallowed` | always | `affected tiers: live_answer, index, training_only` |
| 3 | `cr.access.non_html_seed` | every per-page finding on home | always | `home is not an HTML document` |
| 4 | `cr.render.js_gate` or `cr.render.csr_shell` on page P | `fx.facts.image_only`, `fx.identity.*`, `fx.media.*`, `en.hero.*`, `en.cta.*`, `en.trust.*`, `en.continuity.*`, `en.interstitial.*`, `en.nav.related_links_missing` on P | same page | `root cause: content is not present in the server response` |
| 5 | `cr.render.js_gate` or `cr.render.csr_shell` on home | `fx.facts.key_fact_missing` | when home is the only sampled page or every sampled page is a shell | `facts cannot be extracted because pages are not rendered server-side` |
| 6 | `fx.jsonld.missing` | `ef.entity.sameas_missing`, `fx.jsonld.no_organization`, `ef.entity.name_inconsistent` (JSON-LD leg only) | no JSON-LD anywhere | `adding Organization JSON-LD with sameAs resolves the folded findings` |
| 7 | `fx.jsonld.malformed` for block K | `fx.jsonld.required_props_missing` for block K | same block | — |
| 8 | `ef.entity.nap_missing_plain_text` | `fx.facts.key_fact_missing` entries for `address`, `phone` (local_business only) | same missing facts | `also a category key fact` |
| 9 | `en.links.blocked_cluster` | `en.links.broken_sampled` entries with status 403/429 | ≥ 3 sampled links 403/429 from one host | `reclassified: fetcher blocked, not broken` |
| 10 | `fx.identity.h1_missing_or_multiple` on P | `en.continuity.h1_title_mismatch`, `en.hero.value_prop_unclear` (H1 leg) on P | H1 absent | `continuity not evaluable without an H1` |
| 11 | `cr.index.sitemap_missing` | `cr.index.sitemap_invalid` | no sitemap found | — |
| 12 | `ef.entity.wikidata_unavailable` | `ef.entity.wikidata_ambiguous`, `ef.entity.wikidata_not_found` | lookup did not run | — |

Rules:

- Suppression never lowers the primary's severity. If a suppressed finding had a **higher** severity than the primary, the primary is raised to match and the evidence note records `severity_inherited_from: <check_id>`.
- Suppressed findings still appear in the Markdown under "Folded into other findings" with one line each, so the reader loses nothing.
- Design-level dedupe (no table row needed): `fx.facts.key_fact_missing` does not evaluate `address`/`phone` except for `local_business` (row 8 covers that case); `en.*` never grades robots or JSON-LD.

## 5. What the audit does not cover (say this in every report's `limitations`)

| Not covered | Handout | Why | What we do instead |
|---|---|---|---|
| Whether a specific assistant actually cites or misrepresents the brand today | B | Would require querying live assistants, whose answers are non-deterministic, account-bound, and change daily. | Simulate strictly from the extracted-facts file (`or.simulation.*`) and state that it is a simulation. |
| Inclusion in any model's training data | B | Not observable from outside. | Grade training-only bot blocks as `info` policy notes. |
| Off-site agreement at scale: how many independent sources repeat each fact | D | Requires third-party indices; out of scope for a read-only site audit. | Check the site's own anchors and corroboration surface; bounded spot-check when a search tool exists. |
| Personalization: what a particular user sees | E | Depends on the user, not the site. | Report the site-side levers (location, language, audience facts) as present/absent. |
| Email summarization behaviour | F | Not a website property. | Cover the web analogue: substance in readable text, not buried. |
| User-agent-based cloaking or bot-specific WAF rules | A | The audit uses one honest user agent and never impersonates a listed bot. | Report challenge pages as `inconclusive` and tell the owner how to verify with the vendor's tools. |
| Rendering with a headless browser | C | Deliberate: the point is to see what a non-JavaScript fetcher sees. | Two-signal CSR detection; recommend verifying with `curl`. |
| `llms.txt` and similar proposed conventions | B | Adoption by assistants is not confirmed by operator documentation. | Not graded. Mentioned in proactive recommendations only as optional. |
| Search ranking, domain authority, backlink volume | D | Third-party data. | Not claimed. |
| Accessibility conformance (WCAG) | — | Separate discipline. | Only `alt` and `lang` where they also serve extraction. |
| Real performance (Core Web Vitals) | — | Needs a browser. | Page-weight proxy at `low` confidence. |
| Content quality, accuracy, or brand voice | — | Judgement, not audit. | Facts are reported as present/absent, never as correct/incorrect. |
| Pages beyond the ≤ 6 sampled | A | Bounded, polite crawl. | Sample by role; state the sample in every finding's evidence. |

## 6. Coverage statement template (compose fills it)

> Handout concepts covered: A, B, C fully; D partially (Wikidata lookup
> unavailable; off-site spot-check skipped: no search tool); E and F out of
> scope for a site audit, site-side levers reported. Stages evaluated: access,
> render, extract, freshness, engagement; partial: entity, corroboration. Pages
> sampled: 5 of 6 roles (no pricing page found). Requests made: 23. This audit
> reads what a non-JavaScript fetcher receives; it does not query live
> assistants or execute scripts.

## 7. Derived tags on every finding (compose adds them; probes never set them)

| Stage | `handout_concepts` | `pipeline_stage` | `round2_mode` |
|---|---|---|---|
| `access` | A, B | `retrieval` | invisible |
| `render` | A, C | `retrieval` | invisible |
| `extract` | A, B, C | `ranking` | invisible |
| `entity` | D | `ranking` | stale |
| `freshness` | B, D | `ranking` | stale |
| `corroboration` | D | `ranking` | stale |
| `engagement` | (none) | `post_click` | bouncing |
| `or.simulation.*` | B | `selection` | invisible |

`pipeline_stage` follows the four-stage citation-failure taxonomy (retrieval →
ranking → selection → attribution): a source is never fetched, or fetched but
ranked too low to reach generation, or available but not chosen, or used but
not credited. Severity ceilings already follow this dependency chain (an
access failure makes every later stage moot). `attribution` is not assigned to
any check: mention-without-citation happens inside generation and is observed
only by the AI-answer simulation, which records it in
`ai_answer_simulation.attribution_note` rather than as a finding. `post_click`
is our label for the engagement half, which sits after the citation pipeline.
The taxonomy's source is cited in the README only after Step 20 verifies it.

`opportunity_type` uses the content/technical split:

| `technical` | `content` |
|---|---|
| all `cr.*`; `en.mobile.*`, `en.perf.*`, `en.links.*`, `en.errors.*`, `en.lang.*`, `en.interstitial.*`, `en.nav.landmark_missing`, `en.nav.breadcrumbs_missing`, `en.nav.site_search_missing`; `or.run.*` | all `fx.*`; all `ef.*`; `en.hero.*`, `en.cta.*`, `en.trust.*`, `en.continuity.*`, `en.nav.related_links_missing`; `or.simulation.*` |
