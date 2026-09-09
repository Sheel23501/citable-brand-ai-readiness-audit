# AI bot tiers (shared convention)

Used by the crawl-render probe to grade robots.txt rules and by compose to
word robots findings. The tier, not the vendor, decides severity.

Verification status: every row is confirmed against the operator's public
documentation, with the source URL recorded in `sources.md`. A row that cannot
be confirmed is removed, not kept with a guess. The loader enforces this: rows
whose Status is not `verified` are ignored at runtime.

---

## 1. Tiers

| Tier | Meaning | Effect of a `Disallow: /` for this tier | Default severity |
|---|---|---|---|
| `live_answer` | Fetches a page on demand while answering a user's question, or grounds an answer on the live page. Blocking it removes the site from answers immediately. | The assistant cannot read the site when a user asks about it. | `high`; `critical` if **every** `live_answer` token listed here is blocked, or if `*` is blocked. |
| `index` | Builds a search index that an assistant queries for grounding or citations. Blocking it removes the site from the pool of citable sources. | The site stops appearing as a source in answers over time. | `high`. For `Googlebot` and `Bingbot` the finding also notes that classic web search is affected. |
| `training_only` | Collects text for model training. Blocking it has no effect on whether the site is fetched or cited at answer time. | None on discoverability. A policy choice. | `info`. Title: "Training-only crawler blocked (policy note, not a defect)". |

A user-agent token may appear in two tiers when the operator uses one crawler
for both index and live grounding; the higher tier (`live_answer`) governs.

---

## 2. Token list

Match is case-insensitive on the product token (RFC 9309 §2.2.1) exactly as it
appears in a `User-agent:` line. Substring matching is not used.

Every row below was confirmed against the operator's own public documentation on
2026-09-08; the URLs are in `sources.md`. A token whose operator publishes no
documentation is **not listed**, because we cannot state its purpose or even its
exact spelling with confidence, and a wrong row would produce a false finding.
Removed for that reason: `anthropic-ai` (legacy token, absent from Anthropic's
current crawler docs), `Bytespider` (ByteDance publishes no reachable
documentation), `cohere-ai` and `YouBot` (no vendor documentation; third-party
directories disagree on the exact string), and `Diffbot` (documented, but its
own docs say it does not crawl for generative-AI training, so it is not an
answer-engine crawler and blocking it does not affect AI visibility).

| Token | Operator | Tier | Notes | Status |
|---|---|---|---|---|
| `ChatGPT-User` | OpenAI | `live_answer` | User-initiated fetches from ChatGPT and Custom GPTs. | verified |
| `Claude-User` | Anthropic | `live_answer` | Fetches a page when a Claude user asks about it. | verified |
| `Perplexity-User` | Perplexity | `live_answer` | User-initiated fetches. Perplexity states this agent generally ignores robots.txt, so a Disallow may not stop it. | verified |
| `DuckAssistBot` | DuckDuckGo | `live_answer` | Crawls in real time for DuckAssist AI answers, which cite their sources. | verified |
| `MistralAI-User` | Mistral | `live_answer` | Le Chat user actions. Mistral states it is not used for automatic crawling or training. | verified |
| `meta-externalfetcher` | Meta | `live_answer` | Fetches individual links at a user's request. Meta states it may bypass robots.txt. | verified |
| `OAI-SearchBot` | OpenAI | `index` | Index for ChatGPT search. OpenAI: sites opted out "will not be shown in ChatGPT search answers". | verified |
| `Claude-SearchBot` | Anthropic | `index` | Improves search result quality for Claude users. | verified |
| `PerplexityBot` | Perplexity | `index` | Surfaces and links sites in Perplexity results. Explicitly not used for foundation-model training. | verified |
| `Googlebot` | Google | `index` | Google Search, Discover, Images, Video, News. Blocking removes the site from Google Search. | verified |
| `Bingbot` | Microsoft | `index` | Bing index, which also grounds Copilot. Blocking removes the site from Bing. | verified |
| `Applebot` | Apple | `index` | Spotlight, Siri, Safari suggestions. | verified |
| `DuckDuckBot` | DuckDuckGo | `index` | DuckDuckGo search results. | verified |
| `Amazonbot` | Amazon | `index` | Fetches and indexes page content for Amazon products and services. | verified |
| `GPTBot` | OpenAI | `training_only` | Training for OpenAI foundation models. | verified |
| `ClaudeBot` | Anthropic | `training_only` | Collects content that may contribute to model training. | verified |
| `Google-Extended` | Google | `training_only` | Gemini training and grounding. Google: it "does not impact a site's inclusion in Google Search nor is it used as a ranking signal". | verified |
| `Applebot-Extended` | Apple | `training_only` | Does not crawl; only governs whether Applebot-crawled data trains Apple models. Pages disallowing it still appear in search. | verified |
| `meta-externalagent` | Meta | `training_only` | Training foundation models and indexing content. | verified |
| `CCBot` | Common Crawl | `training_only` | Open web-crawl corpus. Common Crawl does not describe it as a training crawler, but the corpus is widely used for model training, so a block is treated as a training-scope choice. | verified |

Not listed here ⇒ not graded. A `Disallow` for an unlisted token produces no
finding. Do not add tokens outside this file, and do not add a row without a
source URL in `sources.md`.

---

## 3. Grading rules for robots.txt (used by `cr.robots.*`)

Evaluate per RFC 9309 semantics (`fetch_policy.md` section 5): choose the
group whose token matches, otherwise the `*` group; longest-match on path;
`Allow` wins a tie of equal length.

| Situation | check_id | Severity |
|---|---|---|
| `*` group disallows `/` (and no listed token has its own allowing group) | `cr.robots.blanket_disallow` | `critical` |
| A `live_answer` token is disallowed on `/` (its own group, or via `*` when it has no group) | `cr.robots.live_answer_bot_blocked` | `high`; `critical` when all listed `live_answer` tokens are blocked |
| An `index` token is disallowed on `/` | `cr.robots.index_bot_blocked` | `high` |
| A `training_only` token is disallowed on `/` | `cr.robots.training_bot_blocked` | `info` |
| A `live_answer` or `index` token is allowed on `/` but disallowed on a sampled key page | `cr.robots.key_page_disallowed` | `medium` |
| robots.txt returns 4xx | (no finding; treated as allow-all, recorded in evidence of passes) | — |
| robots.txt returns 5xx, times out, or is a challenge page | `cr.robots.unreachable` | `info`, `inconclusive` |

Per-tier findings describe **named** blocks only: a token that is blocked
solely because it falls back to a blocking `*` group has no rule of its own and
is covered by `cr.robots.blanket_disallow`, whose evidence lists the affected
tiers. When both a blanket block and named blocks exist, compose folds the
named findings into the blanket one (dedupe table in `coverage_map.md`).

The audit's own user agent (`fetch_policy.md` section 2) is also subject to
robots.txt. Pages disallowed for it are not fetched; dependent checks become
`not_evaluated` with reason `robots_disallow`.

---

## 4. What this file does not claim

- It does not claim any operator ignores robots.txt.
- It does not claim blocking a `training_only` bot is wrong.
- It sees user-agent-based refusal only at the home URL and only for the three tokens the edge probe announces (`cr.access.edge_block`), and only where the site's robots.txt allows those tokens. The audit never announces a token the site has disallowed, and never uses one to get past a refusal.
