# crawl-render-audit: the 16 checks

Implementation: `scripts/crawl_probe.py`. Defaults come from the shared
registry (`../../audit-orchestrator/references/check_ids.md`); this file
explains the rule behind each row, what evidence is captured, and why the
severity and confidence are set as they are. Stages: `access` (handout
concepts A and B: is the crawler let in) and `render` (A and C: can it read
the page without JavaScript).

The audit fetches with its own honest user agent and never impersonates a
listed bot. robots.txt rules for named bots are graded from the file itself and
are authoritative regardless of what our own fetch experienced.

---

## Robots (stage `access`)

### `cr.robots.unreachable` · info · inconclusive
**Rule.** `/robots.txt` returned 5xx, timed out, or was a bot-protection challenge.
**Evidence.** The status or error and the URL.
**Why info.** Nothing can be graded. Most crawlers treat an unreachable robots.txt as "wait", so the site is temporarily invisible to them too, but the audit cannot prove a configuration defect. Every other robots check becomes `not_evaluated` with reason `robots_unreachable`. A 404 is *not* this case: 4xx means "no rules", everything allowed.

### `cr.robots.blanket_disallow` · critical · high
**Rule.** The `User-agent: *` group's longest-match rule for `/` is a Disallow (RFC 9309 evaluation: longest match wins, equal-length Allow wins).
**Evidence.** The matching rule text and the list of bot tiers affected.
**Why critical.** Every crawler that honours robots.txt is told to stay out: live-answer fetchers, index crawlers, and classic search. It is the single most complete way to be invisible, and a one-line fix. The audit itself obeys the rule, fetches nothing else, and marks every page-level check `not_evaluated` with reason `robots_disallow`.

### `cr.robots.live_answer_bot_blocked` · high, critical when all · high
**Rule.** A token in the `live_answer` tier (`bot_tiers.md`) has its **own** group whose longest-match rule for `/` is a Disallow. Tokens blocked only through a blocking `*` group are not counted here; they belong to the blanket finding.
**Evidence.** One `robots_rule` item per token: `User-agent: <token> / <rule>`.
**Why high.** These agents fetch a page while an assistant answers a user. A block here removes the site from answers immediately, even if it is indexed. Critical when every listed live-answer token is blocked: there is no assistant left that can read the site at answer time.

### `cr.robots.index_bot_blocked` · high · high
**Rule.** As above for the `index` tier.
**Evidence.** One `robots_rule` item per token. If Googlebot or Bingbot is among them the evidence notes that classic search is affected too.
**Why high.** Index crawlers decide which pages are in the citable pool. The effect is delayed rather than immediate, hence high rather than critical.

### `cr.robots.training_bot_blocked` · info (policy note) · high
**Rule.** As above for the `training_only` tier.
**Why info.** Blocking training crawlers does not change whether an assistant can fetch or cite the site today. It is a legitimate content-policy decision and is reported as a note with the trade-off stated (future models may know less about the brand from training data), never as a defect. Status is `fail` because the condition is real; severity is `info` because it is not a problem.

### `cr.robots.key_page_disallowed` · medium, up to high · high
**Rule.** A `live_answer` or `index` token is allowed on `/` but its longest-match rule for a sampled **key page** path (home plus the category's key pages, `site_categories.md`) is a Disallow.
**Evidence.** The matching rule per token and path.
**Why medium.** The assistant can reach the brand but not the page that holds the answer to a core question (pricing, contact, product). It answers from what it can read or from someone else's copy.

## Access (stage `access`)

### `cr.access.http_error` · high, critical when home · high
**Rule.** A sampled page's final response (after up to 5 redirects and one 429 retry) has status ≥ 400 or a transport error (`dns_failure`, `tls_error`, `connect_timeout`, `read_timeout`, `connection_refused`), and is **not** a fingerprinted challenge page.
**Evidence.** Status or error code per page, with the raw error detail when present.
**Why.** A page that errors for a plain fetcher does not exist for an assistant. When it is the home page the title becomes "Site is unreachable" and the severity is critical: this is the top-level never-crash path, the report still exists and says exactly what happened.

### `cr.access.challenge_page` · info · inconclusive
**Rule.** The fetch layer matched a bot-protection fingerprint (`fetch_policy.md` section 6: Cloudflare, Akamai, Imperva, DataDome, HUMAN, AWS WAF, Vercel, generic CAPTCHA) on a sampled page.
**Evidence.** Status and vendor per page.
**Why info and not a defect.** A challenge page has no content, so the audit cannot check the page, but it also cannot know whether real assistants are challenged. The finding says what was not checked and how to allow the audit through. When every fetched page is challenged, the render and index checks are marked `inconclusive` with reason `challenge_page`. This is the most common false-positive trap for JS-gate and CSR heuristics, which is why fingerprinting runs first.

### `cr.access.non_html_seed` · critical · high
**Rule.** The home URL returned 200 with a Content-Type that is not HTML (after sniffing when the header is missing).
**Evidence.** The content-type header and byte count.
**Why critical.** The entry point is where every crawler starts; a PDF or file there offers no navigation, no structured data, and no quotable HTML text. The sampler may still find HTML pages via the sitemap and those are audited, but the front door is the finding.

### `cr.access.edge_block` · high, critical when every citation-tier agent is refused · high

**Rule.** The sampler requests the home URL once per published crawler token
(`OAI-SearchBot` / index, `Claude-User` / live_answer, `GPTBot` /
training_only) and compares each response with the baseline fetch made under
the audit's own user agent. A token is announced **only where the site's
robots.txt allows it for that URL**, evaluated for the announced token under
RFC 9309; a token the site has disallowed is recorded as policy and never
sent. The check fails when the baseline is 200 but a probed `live_answer` or
`index` agent gets a transport error or a status ≥ 400. Critical when every
citation-tier agent probed is refused.

**Evidence.** The baseline status and byte count, then one row per refused
agent with its token, tier, status and the robots.txt rule that allowed it,
and one row per token not probed because the site's policy disallows it.

**Why it matters.** robots.txt states a site's *policy*; this states the
origin's *behaviour*. A CDN or WAF can refuse an AI crawler no matter what
robots.txt permits, and a site can therefore pass every `cr.robots.*` check
while being completely unreachable to the crawlers that fetch pages for AI
answers. This check is the only one in the marketplace that can see that,
because it is the only one that asks the server rather than reading a file.

**Why the requests are safe.** Three read-only GETs of one URL, under the same
budget, politeness delay and robots rules as every other request
(`fetch_policy.md` section 3). We announce a crawler's published token to
observe how the origin responds; we never use one to get around a refusal. A
refusal is recorded as evidence and the probe stops.

**Not a finding when.** The baseline itself is missing, challenged or non-200
(there is nothing to compare against, so the check is `not_evaluated`); the
run had no network; every token the audit could announce is disallowed by the
site's own robots.txt (`not_evaluated`, reason `probe_tokens_disallowed`: the
edge is enforcing the published policy, which `cr.robots.*` already reports);
or robots.txt could not be read (`robots_unreachable`), so no permission could
be decided.

**When the audit itself is refused.** If the home URL answers 401, 403 or 429 to
the audit's own user agent, `cr.access.http_error` uses the same probes to tell
two cases apart. Every robots-allowed token refused the same way: a fail,
critical on the home page, with each probe in the evidence. Every probed token
served: `inconclusive` (`audit_user_agent_refused`), no action for AI
visibility. Nothing probeable (all tokens are the site's policy, or robots.txt
unreadable) or mixed answers: `inconclusive` (`crawler_access_unknown` /
`crawler_access_mixed`), never a fail, because a refusal the audit cannot
explain is not knowledge of a defect.

### `cr.access.edge_block_training` · info · high

**Rule.** Only `training_only` agents are refused at the edge, and no
citation-tier agent is. Reported as a policy note, never as a defect.

**Evidence.** The refused training agents and the baseline status.

**Why info.** Blocking a training crawler keeps content out of future model
training. It does not stop the site being fetched or cited when a user asks
about it today. This mirrors `cr.robots.training_bot_blocked`: the same
decision is graded the same way whether it is made in robots.txt or at the
edge.

### `cr.access.ua_content_variance` · info · low

**Rule.** Every probed agent is served 200, but at least one response body
differs from the baseline by more than half its size.

**Evidence.** The baseline byte count and each differing agent's byte count.

**Why info and low confidence.** Serving a crawler materially different HTML
means the rest of this report may not describe what the crawler actually
reads. But A/B tests, personalisation, cookie state and compression all
produce the same signal from a single byte-count comparison, so the check
reports the observation and explicitly declines to call it a defect.

## Render (stage `render`)

Both render checks require the page to be **thin**: fewer than 60 visible
words after stripping script, style, noscript and template content. A page
with real text is never a gate or a shell, whatever else it contains.

### `cr.render.js_gate` · high, critical when home · high
**Rule.** Thin page **and** at least one of:
1. a `<noscript>` block that mentions JavaScript ("You need to enable JavaScript to run this app");
2. body text matching *enable / requires / turn on JavaScript*, *JavaScript is required / disabled*;
3. a `<body onload>` handler or inline script that submits a form (`document.forms[0].submit()`), the client-side-only redirect gate seen on production sites with no `<noscript>` fallback.
**Evidence.** Word count and the matched signals per page, plus the gate text.
**Why high confidence.** Each signal is an explicit statement in the served HTML that scripts are needed; there is no inference. Critical on the home page because a fetcher that does not execute JavaScript never gets past hop one. A plain HTTP 3xx chain is never a gate (see `non_findings.md`).

### `cr.render.csr_shell` · high, critical when home · medium
**Rule (two signals).** Thin page, not a JS gate, **and** at least one of:
1. an empty framework root container (`#root`, `#app`, `#__next`, `#__nuxt`, `#___gatsby`, `#app-root`, `#svelte`, `#q-app`, and empty `.app`/`.root` divs);
2. inline script bytes more than 10× the visible text bytes (and above 2 KB);
3. two or more external script bundles with under 20 words and no `<h1>`.
**Evidence.** Word count, script bytes, external script count, and the signals per page.
**Why medium, not high, confidence.** The audit did not render the page. A server-rendered page from a framework outside the fingerprint list could, in theory, be thin for a legitimate reason. Two signals on a page, or the same signature on several pages, keep confidence at medium; a single signal on a single page drops to low and the severity cap then holds it at medium. The action tells the owner exactly how to verify with `curl`.

## Index (stage `render`)

### `cr.index.sitemap_missing` · low (medium for ecommerce, publisher) · high
**Rule.** No `Sitemap:` line in robots.txt and neither `/sitemap.xml` nor `/sitemap_index.xml` returned 200 (two requests at most).
**Why low.** Crawlers still follow links; a sitemap mainly helps deep pages and change discovery. For catalogue and news sites, where deep pages are the product, the category override raises it to medium. If robots blocked the audit, this is `not_evaluated`; if the sitemap URL errored or was challenged, `inconclusive`.

### `cr.index.sitemap_invalid` · medium · high
**Rule.** A sitemap URL returned 200 but is not a parseable `urlset` or `sitemapindex` with at least one `<loc>` (gzip and plain-text sitemaps are accepted).
**Why medium.** An unparseable sitemap is ignored and signals poor maintenance. `not_evaluated` when there is no sitemap at all.

### `cr.index.noindex_on_key_page` · high · high
**Rule.** A key page's `<meta name="robots">` (or `googlebot`/`bingbot` variant) or `X-Robots-Tag` header contains `noindex`.
**Why high.** An explicit instruction to every indexer to drop the page. Non-key pages are not graded: noindex on a search-results or thank-you page is normal.

### `cr.index.canonical_offsite` · medium · high
**Rule.** `rel=canonical` on a sampled page points to a different registrable domain.
**Why medium.** The page tells indexers the authoritative copy lives elsewhere, so citations flow to that domain. Usually a copied theme or a leaked staging host.

### `cr.index.canonical_mismatch` · low · medium
**Rule.** `rel=canonical` points to the same domain but a different path, after normalising `www.`, case, and trailing slash.
**Why low and medium confidence.** Sometimes intentional (paginated or filtered views consolidating to a parent). The finding lists the pairs so the owner can decide.

---

## Adjustments the probe records

Every finding's `evidence_items` ends with a `computed` item
`adjustments=...` when the rubric changed the default: `home_page:critical`,
`non_key_pages:-1`, `blast_radius:+1`, `confidence_cap:medium`,
`category_override:<sev>`, `all_live_answer_blocked:critical`,
`home_unreachable:critical`. A reader can always see why a severity differs
from the registry default.
