# AI-readiness audit: python.org

https://www.python.org · category **nonprofit_institution** (medium confidence) · audited 2026-09-12T14:33:02Z · tool brand-ai-readiness-audit 0.1.0

## Summary

No critical or high findings on the 4 pages read; 3 medium and 5 low. Start with F-001: Postal address or phone number is not visible as plain text on the home/about/contact….

**10 findings** — 0 critical, 0 high, 3 medium, 5 low, 2 informational.

61 checks run: 47 passed, 9 failed, 0 inconclusive, 5 not evaluated.

## What this means

This audit read 4 pages of the site and ran 61 checks against what a non-JavaScript fetcher receives. It raised 3 medium, 5 low. Start with F-001: Postal address or phone number is not visible as plain text on the home/about/contact…. 47 checks passed. 5 checks had no verdict, because the pages that would answer them were not reached or could not be read; those are gaps in this sample, not faults found on the site.

## Quick wins

Low effort, real impact, high enough confidence to act on today.

- **F-001** Postal address or phone number is not visible as plain text on the home/about/contact… — State the organisation name, postal address and phone number as visible text in the site footer or on the contact page.

## Findings

### Medium (3)

#### F-001 Postal address or phone number is not visible as plain text on the home/about/contact…

`ef.entity.nap_missing_plain_text` · severity **medium** · confidence high · effort low · entity · `/`, `/about/`, `/about/help/`

Checked the visible text of home, about, contact. Present: email, name. Missing: postal address or phone number. Structured data or images may carry them, but an assistant cross-checking the brand's identity reads the text.

```
text_excerpt: Python.org  (name found)
text_excerpt: python-announce@python.org  (email found)
computed: pages_checked=home, about, contact; required=name|postal address or phone number; missing=postal address or phone number
```

*Why it matters.* Name, address and phone are the three facts every directory, register and knowledge graph holds about a business. When the site itself does not state them as text, the assistant cannot confirm it has the right entity, and inconsistent copies elsewhere win.

*Do this.* State the organisation name, postal address and phone number as visible text in the site footer or on the contact page. Use the same spelling and format everywhere (footer, contact page, JSON-LD PostalAddress and telephone, Google Business Profile, LinkedIn). A footer line is enough: the registered name, the street address in the country's own postal format, and a phone number in international form (+<country code>).

Priority **medium** · impact medium · effort low · quick win

Reference: https://developers.google.com/search/docs/appearance/structured-data/organization

#### F-002 1 of 4 key facts for a nonprofit or institutional site are not extractable as text

`fx.facts.key_fact_missing` · severity **medium** · confidence medium · effort medium · extract · site-wide

Searched 4 sampled pages (home, about, contact, blog). Found 3 of 4 key facts as plain text or structured data; not found: location (absent).

```
computed: pages_searched=4 (home, about, contact, blog); key_facts=4; found=3; missing=location
text_excerpt: …Foundation The mission of the Python Software Foundation is to promote, protect, and advance the Python programming language, and to support and facilitate the growth of a diverse and international …  (mission found via text)
text_excerpt: Get Started; Download; Docs; Jobs; Upcoming Events  (programs_or_services found via heading)
text_excerpt: Donate  (how_to_participate found via link)
computed: adjustments=single_missing_fact:medium
```

*Why it matters.* An assistant answers from the text it can extract. A fact that is absent, or present only as a hint, is a question the brand cannot be quoted on, so the answer comes from a competitor or from nowhere. The brand is invisible for that question.

*Do this.* Add the missing facts as plain text on the pages a visitor would expect them (location). State the location as text (city and country at minimum). Mirror each fact in the matching JSON-LD property (offers.price, address, telephone, openingHoursSpecification, description, audience) so both text and structured data agree.

Priority **medium** · impact medium · effort medium

Reference: https://developers.google.com/search/docs/appearance/structured-data/sd-policies

#### F-003 Home page heading is 2 words, too short to state what the site offers

`en.hero.value_prop_unclear` · severity **medium** · confidence low · effort medium · engagement · `/`

Home page: <h1> 'Intuitive Interpretation' (2 words); the text below it does name the offer (work).

```
text_excerpt @ h1: Intuitive Interpretation
text_excerpt: Intuitive Interpretation Calculations are simple with Python and expression syntax is straightforward the operators and work as expected parentheses can be used for grouping More about simple math fun  (first 120 words of the first viewport)
computed: signals=h1_too_short:2_words; notes=none; category_noun=none; offer_verb=work
```

*Why it matters.* Most of a visit's attention lands in the first screen. A visitor who cannot tell within a few seconds what the site offers and for whom leaves, and the click an assistant sent is wasted: the bouncing mode.

*Do this.* Rewrite the home page's first viewport as a headline that names the offer and the customer, a one-sentence subhead, and a primary call to action. Use a 5-12 word <h1> that states what the site provides (the product or service noun) for whom, followed by one plain sentence. Check with a stranger: shown only the first screen, can they say what you sell?

Priority **low** · impact medium · effort medium

### Low (5)

#### F-004 2 pages have multiple <h1> elements

`fx.identity.h1_missing_or_multiple` · severity **low** · confidence high · effort low · extract · `/`, `/about/help/`

home: 5 h1; contact: 10 h1.

```
computed: h1_count=5
computed: h1_count=10
```

*Why it matters.* The single main heading is how a machine decides what the page is about. Zero headings leave it guessing; several compete.

*Do this.* Use exactly one <h1> per page that states the page's subject. Demote extra h1s to h2, or add an h1 above the main content. Check the template rather than individual pages.

Priority **low** · impact low · effort low

#### F-005 No XML sitemap is advertised or found at the standard paths

`cr.index.sitemap_missing` · severity **low** · confidence high · effort low · render · site-wide

robots.txt has no Sitemap line and https://www.python.org/sitemap.xml, https://www.python.org/sitemap_index.xml did not return a sitemap.

```
http_status: tried=https://www.python.org/sitemap.xml;https://www.python.org/sitemap_index.xml; robots_sitemap_lines=0
```

*Why it matters.* Crawlers can still follow links, but a sitemap is how they learn about pages that are not linked prominently and when pages changed. Without it, deep pages are found late or not at all.

*Do this.* Publish /sitemap.xml listing the public pages with lastmod dates, and reference it from robots.txt. Most CMSs and frameworks generate one. Add 'Sitemap: https://<host>/sitemap.xml' to robots.txt. Verify the file returns 200 and parses.

Priority **low** · impact low · effort low

Reference: https://www.sitemaps.org/protocol.html

#### F-006 Home/Blog page heading does not match its title and description

`en.continuity.h1_title_mismatch` · severity **low** · confidence medium · effort low · engagement · `/`, `/blogs/`

On 2 of 4 graded pages (home, blog) the <h1> shares no content word of four or more letters with the <title> or the meta description.

```
computed: h1='Intuitive Interpretation'; title='Welcome to Python.org'; shared_words=none  (home page)
computed: h1='The 2026 PSF Board Election is Open!'; title='Our Blogs | Python.org'; shared_words=none  (blog page)
```

*Why it matters.* An assistant or a search result shows the title and description; the visitor arrives expecting that. A heading that says something else makes them doubt they are in the right place, and they go back.

*Do this.* Make the <h1> of the home/blog pages restate the promise of its title and description. The title, description and h1 should share the same key noun. Rewrite whichever of the three is off-message; usually the h1.

Priority **low** · impact low · effort low

#### F-007 JSON-LD is present but no Organization node describes the site owner

`fx.jsonld.no_organization` · severity **low** · confidence medium · effort low · extract · `/`, `/about/`

Structured data types found: SearchAction, WebSite; none on the home or about page identifies the organisation behind the site.

```
computed: jsonld_types=WebSite,SearchAction
computed: jsonld_types=WebSite,SearchAction
```

*Why it matters.* Without an Organization node there is no machine-readable statement of who the brand is, so page-level markup floats unattached to an entity.

*Do this.* Add an Organization JSON-LD node (name, url, logo, sameAs) to the home page. One block in the home page <head> is enough; reference it from other nodes via publisher or provider.

Priority **low** · impact low · effort low

Reference: https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data

#### F-008 No FAQ-shaped content or FAQPage markup on the sampled pages

`fx.content.faq_absent` · severity **low** · confidence low · effort medium · extract · site-wide

None of the 4 sampled pages has a FAQ heading, three or more question headings, or FAQPage JSON-LD. The product page was not reached in this sample, so this describes the 4 pages read, not the whole site.

```
computed: faq_heading=false; question_headings=0; FAQPage=false
computed: faq_heading=false; question_headings=0; FAQPage=false
computed: faq_heading=false; question_headings=9; FAQPage=false
computed: faq_heading=false; question_headings=0; FAQPage=false
computed: absence_scope=sample; roles_not_sampled=product
```

*Why it matters.* A page shaped as question and answer can help it match a question-shaped query, but a 23,745-citation measurement study across 602 prompts found Q&A-formatted content has lower influence on the generated answer once selected (-5.74%) than content built around concrete numbers, comparisons, or plain definitions (+41% to +62%). This is an opportunity, not a defect: add FAQ content for retrieval and clarity, and keep stating the same facts as ordinary prose too, not only as isolated Q&A pairs.

*Do this.* Add a short FAQ (five real questions customers ask, answered in one or two sentences each) on the pricing or product page, with FAQPage JSON-LD, and state the same facts once more in the page's main prose. Use the questions your support inbox actually receives. Put each question in a heading and the answer directly under it, then mirror them in FAQPage mainEntity. A stray Q&A pair is not a substitute for the fact being stated plainly elsewhere on the page.

Priority **low** · impact low · effort medium

Reference: https://schema.org/FAQPage, https://arxiv.org/abs/2604.25707

### Informational (2)

#### F-009 Off-site mention spot-check not performed

`ef.corroboration.offsite_spotcheck` · severity **info** · confidence high · effort n/a · corroboration · site-wide

No search-tool result at work/offsite_mentions.json. The off-site check is an agent step: it needs a web-search tool, which this script does not have.

```
computed: suggested_queries="Python.org" | "Python.org" python.org | "Python.org" reviews | "Python.org" site:linkedin.com
```

*Why it matters.* Without it the report says nothing about whether independent sources repeat the brand's facts; that is a limitation, not a defect of the site.

*Do this.* Run the bounded spot-check described in SKILL.md (at most five searches), write work/offsite_mentions.json, and re-run this probe. Search the suggested queries with a web-search tool, record up to ten mentions with url, kind (news, directory, review, social, wiki, other) and whether each restates a site fact, then re-run with --workdir.

Priority **low** · impact low · effort n/a

#### F-010 1 of the questions a buyer would ask cannot be answered from this site's text

`or.simulation.question_unanswerable` · severity **info** · confidence high · effort n/a · extract · site-wide

Simulated from work/extracted_facts.json only: 1 of 4 questions unanswerable; facts absent: location.

```
computed: question=What programs does Python.org run, and where?; missing_facts=location
```

*Why it matters.* An assistant answering at fetch time has only what the pages say. Where the site is silent it either declines to answer or uses someone else's page, and the brand is invisible for that question.

*Do this.* State each missing fact in plain sentence text on the page a visitor would look for it. The specific defect is already reported by the fact-extractability findings; this is the reader-facing consequence. Re-run the audit afterwards: the simulation is deterministic.

Priority **low** · impact low · effort n/a

## What is working

47 checks passed. These are the parts an assistant will not trip over.

**access**

- No page served a bot challenge to the audit fetcher (`cr.access.challenge_page`)
- AI crawlers are served the page, not refused at the edge (`cr.access.edge_block`)
- Training-only crawlers are not refused at the edge (`cr.access.edge_block_training`)
- Every sampled page returned a successful HTTP status (`cr.access.http_error`)
- The home URL returns an HTML document (`cr.access.non_html_seed`)
- The page is the same size for every crawler tested (`cr.access.ua_content_variance`)
- robots.txt does not blanket-disallow crawlers (`cr.robots.blanket_disallow`)
- Search index bots are allowed to crawl (`cr.robots.index_bot_blocked`)
- Every sampled key page is crawlable (`cr.robots.key_page_disallowed`)
- Assistant answer-time bots are allowed to crawl (`cr.robots.live_answer_bot_blocked`)
- Training-only bots are not blocked (`cr.robots.training_bot_blocked`)
- robots.txt was fetched and parsed (`cr.robots.unreachable`)

**render**

- Canonical URLs match the pages that declare them (`cr.index.canonical_mismatch`)
- No canonical URL points to another domain (`cr.index.canonical_offsite`)
- No key page is marked noindex (`cr.index.noindex_on_key_page`)
- Sampled pages carry their text in the server response (`cr.render.csr_shell`)
- No sampled page hides its content behind a JavaScript gate (`cr.render.js_gate`)

**extract**

- No key fact is locked inside an image (`fx.facts.image_only`)
- Every sampled page has a meta description (`fx.identity.meta_description_missing`)
- Open Graph title or description is present (`fx.identity.og_missing`)
- Every sampled page has a specific title (`fx.identity.title_missing_or_generic`)
- Every JSON-LD block parses (`fx.jsonld.malformed`)
- Structured data (JSON-LD) is present (`fx.jsonld.missing`)
- JSON-LD nodes carry their identifying properties (`fx.jsonld.required_props_missing`)
- Content images carry alt text (`fx.media.alt_text_missing`)

**entity**

- The brand is named consistently across the site (`ef.entity.name_inconsistent`)
- The brand name resolves to this brand (`ef.entity.wikidata_ambiguous`)
- The brand name was found in the reference source (`ef.entity.wikidata_not_found`)
- The entity lookup ran (`ef.entity.wikidata_unavailable`)

**freshness**

- Structured dates agree with the visible dates (`ef.freshness.date_modified_mismatch`)
- Pages carry visible dates (`ef.freshness.no_visible_dates`)
- The copyright year is current (`ef.freshness.stale_copyright_year`)

**corroboration**

- The site offers a press, news or blog surface (`ef.corroboration.press_page_missing`)

**engagement**

- Every key page offers a clear next step (`en.cta.missing`)
- A missing page returns a real 404 (`en.errors.soft_404`)
- The 404 page helps a visitor continue (`en.errors.unhelpful_404`)
- No interstitial covers the content on arrival (`en.interstitial.blocking`)
- The page declares its language (`en.lang.attribute_missing`)
- No cluster of links blocked the audit fetcher (`en.links.blocked_cluster`)
- Every sampled internal link resolves (`en.links.broken_sampled`)
- Pages declare a mobile viewport (`en.mobile.viewport_missing`)
- Interior pages show breadcrumbs (`en.nav.breadcrumbs_missing`)
- The site has a navigation landmark (`en.nav.landmark_missing`)
- The site offers a search field (`en.nav.site_search_missing`)
- Page weight is within the proxy thresholds (`en.perf.page_weight_heavy`)
- The trust signals expected for this category are present (`en.trust.signals_missing`)

**run**

- Every probe completed without an internal error (`or.run.probe_error`)

## AI answer simulation

What an assistant could answer using **only** the facts this site states in its own served HTML (`work/extracted_facts.json`). Nothing else was consulted.

**What is Python.org's mission?**

According to the site, "…Foundation The mission of the Python Software Foundation is to promote, protect, and advance the Python programming language, and to support and facilitate the growth of a diverse and international …".

**What programs does Python.org run, and where?**

_Not answerable from the site's text. Absent: location._

**How do I donate, apply, or join?**

According to the site, "Donate".

**Is Python.org a good fit for a supporter like me?**

According to the site, "Get Started; Download; Docs; Jobs; Upcoming Events".

**What sets Python.org apart from alternatives?**

_Not answerable from the site's text. Absent: differentiator._ Informational only.

Every answer above quotes this site's own text, exactly as the facts file records it; nothing was added from anywhere else. A question left unanswered means the fact is not on the pages read.

## Proactive recommendations

Opportunities, not defects: none of these is a restatement of a finding above.

- **Add the recommended properties to the existing structured data** (extract, low effort, priority medium) — The structured data present is valid but thin. Missing recommended properties (WebSite: name, publisher; WebSite: name, publisher; WebSite: name, publisher) are the ones assistants use to distinguish one entity from another.
- **State in one sentence what sets this brand apart** (extract, low effort, priority medium) — Assistants fan a query out into comparison questions. Nothing on the sampled pages claims a difference, so a comparison answer has nothing of this site's own wording to quote. This is an opportunity, not a defect: it is never reported as a finding.
- **Consider publishing a plain-text summary of the site at /llms.txt** (extract, low effort, priority low) — Not a confirmed ranking or citation signal for any major search or answer engine, so it is not graded anywhere in this audit. Early academic evidence on structured, agent-navigable pages suggests explicit machine-readable summaries can help agentic systems that autonomously fetch and follow links, distinct from ranking. It costs one file, and the exercise of writing it usually exposes facts the site never states plainly.
- **Publish datable milestones on the news surface others can cite** (corroboration, medium effort, priority low) — The site already has a place to publish. Dated, factual announcements are what other sites quote, and repeated facts across independent sources are what make an entity trusted.

## Coverage and limitations

Handout concepts covered: B fully; A, C, D partially (sitemap_invalid: sitemap_missing; offsite_spotcheck: tool_unavailable; sameas_missing: dependency_failed); E and F out of scope for a site audit, site-side levers reported. Stages evaluated: access, extract, freshness, engagement; partial: render, entity, corroboration. Pages sampled: 4 (home, about, contact, blog); no page found for: pricing, product. Requests made: 10. This audit reads what a non-JavaScript fetcher receives; it does not query live assistants or execute scripts.

Checks with no verdict: `cr.index.sitemap_invalid` (sitemap_missing), `ef.corroboration.offsite_spotcheck` (tool_unavailable), `ef.entity.sameas_missing` (dependency_failed), `ef.entity.sameas_no_authority` (dependency_failed)

Not applicable to a nonprofit or institutional site: `en.nav.related_links_missing`

- This report reflects a single point-in-time fetch of 4 sampled pages; personalised or A/B-tested pages may differ between runs.
- Off-site mention spot-check skipped: tool unavailable.
- This audit reads served HTML only and does not execute JavaScript or query live assistants.
- Outside this audit's scope: Whether a specific assistant actually cites or misrepresents the brand today; Inclusion in any model's training data; Off-site agreement at scale: how many independent sources repeat each fact; Personalization: what a particular user sees; Email summarization behaviour; Cloaking beyond the home URL and the three tokens probed; Rendering with a headless browser; `llms.txt` and similar proposed conventions; Search ranking, domain authority, backlink volume; Accessibility conformance (WCAG); Real performance (Core Web Vitals); Content quality, accuracy, or brand voice; Pages beyond the ≤ 6 sampled. Each is explained in report.json under limitations.
