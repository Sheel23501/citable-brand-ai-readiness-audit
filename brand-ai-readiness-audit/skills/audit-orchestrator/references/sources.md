# Sources

Every external claim made by this marketplace traces to a source here. A claim
without a source in this file is removed from the code, references and README
rather than softened. Verified 2026-09-08.

---

## 1. AI crawler tiers (`bot_tiers.md` section 2)

Each row of the token list was confirmed against the operator's own public
documentation. Where the operator publishes nothing, the token is not listed.

| Operator | Source |
|---|---|
| OpenAI (`GPTBot`, `OAI-SearchBot`, `ChatGPT-User`) | https://developers.openai.com/api/docs/bots |
| Anthropic (`ClaudeBot`, `Claude-SearchBot`, `Claude-User`) | https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler |
| Perplexity (`PerplexityBot`, `Perplexity-User`) | https://docs.perplexity.ai/guides/bots |
| Google (`Googlebot`, `Google-Extended`) | https://developers.google.com/search/docs/crawling-indexing/google-common-crawlers |
| Apple (`Applebot`, `Applebot-Extended`) | https://support.apple.com/en-us/119829 |
| Meta (`meta-externalagent`, `meta-externalfetcher`) | https://developers.facebook.com/docs/sharing/webmasters/web-crawlers/ |
| DuckDuckGo (`DuckAssistBot`) | https://duckduckgo.com/duckduckgo-help-pages/results/duckassistbot/ |
| DuckDuckGo (`DuckDuckBot`) | https://duckduckgo.com/duckduckgo-help-pages/results/duckduckbot/ |
| Mistral (`MistralAI-User`) | https://docs.mistral.ai/robots |
| Amazon (`Amazonbot`) | https://developer.amazon.com/amazonbot |
| Common Crawl (`CCBot`) | https://commoncrawl.org/ccbot |
| Microsoft (`Bingbot`) | https://www.bing.com/webmasters/help/which-crawlers-does-bing-use-8c184ec0 |

Quotations relied on for tier assignment:

- OpenAI, on `OAI-SearchBot`: sites opted out "will not be shown in ChatGPT
  search answers". This is why `index` is graded above `training_only`.
- Google, on `Google-Extended`: it "does not impact a site's inclusion in Google
  Search nor is it used as a ranking signal in Google Search". This is why
  blocking it is `info`, not a discoverability defect.
- Apple, on `Applebot-Extended`: it "does not crawl webpages"; pages that
  disallow it "can still be included in search results".
- Perplexity, on `PerplexityBot`: "It is not used to crawl content for AI
  foundation models."
- Perplexity, on `Perplexity-User`, and Meta, on `meta-externalfetcher`: both
  operators state these user-triggered agents may ignore robots.txt, so a
  `Disallow` for them is reported as a weaker signal than for an index crawler.

### Tokens deliberately excluded

| Token | Why excluded |
|---|---|
| `anthropic-ai` | Legacy token; absent from Anthropic's current crawler documentation. |
| `Bytespider` | ByteDance publishes no reachable documentation; the UA's own reference link is not resolvable outside China. |
| `cohere-ai` | Cohere publishes no crawler documentation. |
| `YouBot` | You.com publishes no crawler documentation; third-party directories disagree on the exact user-agent string, so a row would risk a false match. |
| `Diffbot` | Documented, but Diffbot's own docs state it does not crawl for generative-AI training. It is a structured-data extraction service, not an answer-engine crawler, so blocking it does not affect AI visibility. |

---

## 2. Protocol and format references

| Claim | Source |
|---|---|
| robots.txt grammar, group merging, longest-match precedence, `$`/`*` semantics | RFC 9309 — https://www.rfc-editor.org/rfc/rfc9309.html |
| Agent Skills format: frontmatter fields, limits, progressive disclosure | https://agentskills.io/specification |
| Structured data required properties | https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data |

---

## 3. Citation, ranking and content-influence research

Findings that shaped severity, confidence and the proactive recommendations
around fact density, structured data and FAQ content.

| Claim | Source |
|---|---|
| Per-technique visibility deltas for quotations, statistics, citing sources, fluency, etc.; keyword stuffing reduces visibility; citing sources helps low-ranked sources far more than top-ranked ones | Aggarwal et al., "GEO: Generative Engine Optimization", KDD 2024 — https://arxiv.org/abs/2311.09735 |
| JSON-LD alone gives a small effect (d=0.18); the same facts *also* stated as visible human-readable text near the structured data gives a large effect (+29.6% accuracy, d=0.60, p<10⁻²¹); the gain is largest where plain HTML previously stated nothing (travel, editorial) and smallest where it already did (e-commerce, ceiling effect) | "Structured Linked Data as a Memory Layer for Agent-Orchestrated Retrieval" — https://arxiv.org/abs/2603.10700 |
| Citation *selection* (getting retrieved) is gated by domain authority and being an official/news/vertical source (79-88% of citations); citation *absorption* (shaping the generated answer once selected) correlates with page length (top-quartile pages average 11.44x the words of bottom-quartile), heading and list density, and content genre — numbers/statistics (+61.55%), definitions (+57.33%) and comparisons (+55.28%) show the largest influence gains, while Q&A-formatted content shows a small negative effect (-5.74%) | "From Citation Selection to Citation Absorption: A Measurement Framework for Generative Engine Optimization Across AI Search Platforms" — https://arxiv.org/abs/2604.25707 |

**Design consequences drawn from these three papers:**
- `fx.jsonld.*` findings stay `medium` at most on their own (schema alone is a
  small effect); the structured-data recommendations push toward materialising
  the same facts as visible text, not toward JSON-LD as a standalone fix.
- `fx.content.faq_absent`'s advice no longer claims Q&A format is "the easiest
  to quote" — the largest independent measurement of citation influence found
  the opposite for that specific format, even though Q&A framing may still aid
  initial retrieval for question-shaped queries. The finding now recommends
  FAQ content for retrieval and clarity while asking that the same facts also
  appear as ordinary prose.
- A new proactive recommendation asks for at least one concrete, stated number
  in the site's own words, reflecting the largest single content-genre effect
  measured (numbers/statistics, +61.55% absorption influence).
