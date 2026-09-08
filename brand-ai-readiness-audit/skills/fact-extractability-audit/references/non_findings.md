# fact-extractability-audit: explicit non-findings and limits

Things this skill sees and deliberately does **not** flag. Each is a real
pattern on production sites that a naive checker misreports. Stating them is
part of the detection-accuracy contract: few false positives, and no finding
that tells a business to change a legitimate choice.

| Condition | Why it is not a finding | What the report says instead |
|---|---|---|
| **Sales-led pricing** ("request a demo", "contact sales", "pricing on request", "talk to sales") on the pricing, product or home page | Enterprise and B2B sites that sell through a sales team are a large, normal category. Choosing not to publish prices is not a defect; the site still tells a reader how pricing works. | `pricing_or_trial` is `present` with kind `sales_led` in the facts file, so the simulation answers "pricing is available on request". Nothing from `fx.facts.key_fact_missing`. |
| **A "book a demo" link on the contact page alone** | A contact page always has some call to action; it does not make the site sales-led. | Counted only when the site has no pricing page. Otherwise the fact stays `absent` or `partial` and the finding says why. |
| **Free-trial button with no price anywhere** ("Start free trial") | A trial exists, so the hint is recorded, but the trial says nothing about cost. | `partial`, kind `trial_only`, listed inside the single `fx.facts.key_fact_missing` finding with the excerpt; never a second finding. |
| **Price present only in JSON-LD** (`Offer.price` with `priceCurrency`, no visible amount) | Structured data is extractable by definition. | `pricing_or_trial` / `sample_product_price` `present`, source `jsonld:Offer.price`. |
| **Fact present only in the meta description or `og:description`** | Both are served text that indexers and assistants read. | The fact is `present` with source `meta:description` or `meta:og:description`. |
| **An image with pricing, hours or address words on a page whose text also has the fact** (a pricing table plus a hero image called `pricing.png`) | The fact is extractable; the image is illustration. | Nothing. `fx.facts.image_only` requires the text equivalent to be absent. |
| **Images with no fact words in alt, filename or the preceding heading** | There is no signal that the image carries a fact. | Nothing from `fx.facts.image_only`; `fx.media.alt_text_missing` may count them if alt is missing on enough of them. |
| **Specs, datasheet or comparison images** | Feature grids are usually decorative restatements of text elsewhere; the false-positive rate is too high. | Nothing. |
| **Decorative images** (`alt=""`, `role="presentation"`, icons under 50 px) | Correctly marked as decorative; skipping them is the point of the attribute. | Excluded from every image check. |
| **One image without alt on a page with two images** | A pattern needs a pattern's worth of images. | Nothing. `fx.media.alt_text_missing` needs three content images and two missing. |
| **Nested JSON-LD nodes missing properties** (an `Offer` without `price` inside a `Product`, a `publisher` without `url`) | Nested nodes describe a property of their parent; grading them produces the long nagging lists that make structured-data reports unread. | Nothing. Only top-level nodes are graded by `fx.jsonld.required_props_missing`. |
| **JSON-LD types outside the table** (`WebPage`, `SearchAction`, `ContactPoint`, custom types) | No documented identifying-property set to grade against. | Nothing; the types are listed in the facts file under `pages_used[].jsonld_types`. |
| **Recommended properties missing** (`logo`, `sameAs`, `dateModified`, `author`, `image`) | Useful but not identifying; treating them as defects inflates counts. | Written to `jsonld_recommendations` in the facts file for the orchestrator's proactive recommendations. Never a finding here. |
| **Microdata or RDFa instead of JSON-LD** | This audit parses JSON-LD only; the markup may be complete. | `fx.jsonld.missing` still fires (JSON-LD is what current documentation asks for) but at `medium` confidence, with the evidence saying Microdata or RDFa attributes were seen and not parsed. |
| **`og:image`, `og:type`, Twitter cards absent** | Not used for extraction. | Nothing. Only `og:title` and `og:description` are graded. |
| **Title too long, too short, or repeated across pages** | Presentation and search-ranking questions, not extractability. | Nothing. Only missing or generic titles are graded. |
| **Pages that are a JavaScript gate or client-rendered shell** | There is no text to grade; the cause is the rendering, and one finding should say so. | Excluded with reason `no_rendered_content`; `cr.render.js_gate` / `cr.render.csr_shell` own the finding (dedupe rows 4 and 5). |
| **No FAQ on a publisher or portfolio site** | Articles and portfolios are not question-shaped products. | `fx.content.faq_absent` is `not_evaluated`, reason `not_applicable_for_category`. |
| **Questions answered in prose without an FAQ shape** | Legitimate; the FAQ finding is an opportunity, not a defect. | `fx.content.faq_absent` at low severity, medium confidence, worded as an opportunity. |
| **`audience` or `differentiator` absent** | Optional facts that exist only so the simulation can ask the fit and comparison questions. | Recorded as `absent` in the facts file. Never a finding. |
| **Address or phone missing on a non-local site** | NAP is the entity skill's concern for every category except `local_business`. | Nothing from this skill (dedupe row 8 covers the overlap). |
| **A PDF menu, price list or brochure linked from the page** | The link is not followed: a fetcher answering a question does not open PDFs either. | If the page text lacks the fact, it is `absent` and the action says to reproduce it as HTML text. The PDF is not itself a finding. |

## What regex extraction over six pages cannot know

- **Vocabulary is English-first.** Sales-led, free-tier, audience, mission and
  differentiator phrases are matched from English word lists (page-role
  detection in the sampler covers six languages, but fact phrasing does not).
  On a non-English site a fact may be reported `absent` when it is present.
  This is the main reason `fx.facts.key_fact_missing` is `medium` confidence
  and why its evidence lists exactly which pages were searched. The
  orchestrator adds a limitation line whenever the page language is not
  English.
- **Only sampled pages are searched.** Home plus up to five role pages, chosen
  by navigation labels and sitemap patterns. A fact on an unsampled page is
  invisible to this audit; every finding lists the pages it applies to.
- **Prices are recognised by currency symbols and ISO codes** (`$ £ € ¥ ₹`,
  `USD EUR GBP INR CAD AUD JPY CHF`). A price written as "twelve pounds a
  month" or in another currency's plain code is missed.
- **JSON-LD only.** Microdata and RDFa are detected as present but not
  parsed; their content never counts as an extractable fact.
- **Excerpts are verbatim windows**, snapped to word boundaries and marked
  with `…` where cut, at most 200 characters. They prove the fact was found;
  they are not summaries.
- **Nothing is inferred about a fact from its absence in the sample.** The
  facts file records `absent`, the finding says "not extractable from the
  sampled pages", and the simulation answers "the site does not state it".

## Added after the live pass (Step 19)

| What the probe sees | Why it is not a finding |
|---|---|
| A photo whose caption mentions a fact word: "location pins dropping onto a street map", "Thomas Kropf … and colleagues" on a news post | A caption is prose, not a label. `fx.facts.image_only` reads only short alt text (≤ 5 words), filename tokens, and headings of ≤ 4 words, and only on the pages where the fact is expected. |
| A headline that contains "plans" above an article image | Same rule: "Broadcom plans new vSphere Standard" is a sentence. It is neither a pricing heading nor, for the sampler, a pricing page. |
| An "hours" or "address" image on a corporate or SaaS site | Only the category's key facts are graded. A corporate site is not asked for opening hours. |
| A map screenshot with a seven-word caption on a contact page with no text address | The missing address is already `ef.entity.nap_missing_plain_text` and `fx.facts.key_fact_missing`; the image is not a third finding. |
