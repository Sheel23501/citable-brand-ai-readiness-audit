# AI bot tiers (shared convention)

Used by the crawl-render probe to grade robots.txt rules and by compose to
word robots findings. The tier, not the vendor, decides severity.

Verification status: every row must be confirmed against the operator's public
documentation in Step 20 and the source URL recorded in the `sources.md` file
produced there. Until then rows are marked `unverified`. A row that cannot be
confirmed is removed, not kept with a guess.

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

| Token | Operator | Tier | Notes | Status |
|---|---|---|---|---|
| `ChatGPT-User` | OpenAI | `live_answer` | User-initiated fetches from ChatGPT. | unverified |
| `OAI-SearchBot` | OpenAI | `index` | Index for ChatGPT search features. | unverified |
| `GPTBot` | OpenAI | `training_only` | | unverified |
| `Claude-User` | Anthropic | `live_answer` | User-initiated fetches from Claude. | unverified |
| `Claude-SearchBot` | Anthropic | `index` | | unverified |
| `ClaudeBot` | Anthropic | `training_only` | | unverified |
| `anthropic-ai` | Anthropic | `training_only` | Legacy token still seen in robots files. | unverified |
| `Perplexity-User` | Perplexity | `live_answer` | User-initiated fetches. | unverified |
| `PerplexityBot` | Perplexity | `index` | | unverified |
| `Googlebot` | Google | `index` | Also powers AI Overviews / AI Mode grounding. Blocking removes the site from Google Search. | unverified |
| `Google-Extended` | Google | `training_only` | Controls Gemini training and Gemini-app grounding, not classic Search or AI Overviews. | unverified |
| `Bingbot` | Microsoft | `index` | Also grounds Copilot. Blocking removes the site from Bing. | unverified |
| `Applebot` | Apple | `index` | Siri, Spotlight, Safari suggestions, Apple Intelligence. | unverified |
| `Applebot-Extended` | Apple | `training_only` | | unverified |
| `DuckAssistBot` | DuckDuckGo | `live_answer` | | unverified |
| `DuckDuckBot` | DuckDuckGo | `index` | | unverified |
| `Amazonbot` | Amazon | `index` | Alexa answers. | unverified |
| `MistralAI-User` | Mistral | `live_answer` | | unverified |
| `meta-externalfetcher` | Meta | `live_answer` | User-initiated fetches. | unverified |
| `meta-externalagent` | Meta | `training_only` | | unverified |
| `YouBot` | You.com | `index` | | unverified |
| `CCBot` | Common Crawl | `training_only` | Corpus used by many trainers. | unverified |
| `Bytespider` | ByteDance | `training_only` | | unverified |
| `cohere-ai` | Cohere | `training_only` | | unverified |
| `Diffbot` | Diffbot | `training_only` | Knowledge-graph extraction. | unverified |

Not listed here ⇒ not graded. A `Disallow` for an unlisted token produces no
finding. Do not add tokens outside this file.

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
- It does not detect user-agent-based cloaking: the audit fetches only with its own honest user agent and never impersonates a listed token.
