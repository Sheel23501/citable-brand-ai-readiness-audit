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
