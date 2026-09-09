# crawl-render-audit: explicit non-findings and limits

Things this skill sees and deliberately does **not** flag. Each is a real
pattern on production sites that a naive checker misreports. Stating them
is part of the detection-accuracy contract: few false positives.

| Condition | Why it is not a finding | What the report says instead |
|---|---|---|
| **HTTP 3xx redirect chain** (geo, locale, `http`→`https`, apex→`www`), up to 5 hops | Server-side redirects are followed by every crawler; only a script-driven redirect is a gate. | Nothing. The final URL is recorded in the sample manifest. A cross-domain redirect is noted in the manifest, not graded. |
| **Bot-protection challenge page** served to the audit | The audit cannot know whether assistants are challenged too; a thin challenge body looks like a shell but is not one. | `cr.access.challenge_page`, info, inconclusive, with instructions to allow the audit user agent. Render and index checks on those pages are `inconclusive`, never `fail`. |
| **Plain 403 or 429 without a challenge fingerprint** | Could be a user-agent allowlist or rate limit aimed at unknown clients, not at assistants. | `cr.access.http_error` at page level, with the raw status as evidence and a note to check server logs. Not escalated to a claim about AI bots; robots.txt is the authority for that. |
| **robots.txt returns 404** | Per RFC 9309 a missing file means no restrictions. | All robots checks `pass`. |
| **Training-only bots blocked** (GPTBot, ClaudeBot, CCBot, Google-Extended, Applebot-Extended, Bytespider, …) | A content-policy choice with no effect on answer-time fetching or indexing. | `cr.robots.training_bot_blocked`, info policy note with the trade-off stated. |
| **Unlisted bot tokens blocked** | Not graded; we do not guess at tiers for tokens outside `bot_tiers.md`. | Nothing. |
| **`noindex` on non-key pages** (search results, thank-you pages, tag archives) | Normal hygiene. | Nothing. Only key pages for the inferred category are graded. |
| **Canonical differing only by `www.`, case, or trailing slash** | Trivial normalisation, not a mismatch. | Nothing. |
| **Thin page with real text structure** (a short landing page with an `<h1>` and a paragraph) | Under 60 words alone is not a shell; a signal from markup is required as well. | Nothing from this skill. Content thinness is the fact-extractability and engagement skills' domain. |
| **Heavy external bundles on a page with real text** | Script weight without thinness is a performance question, not a rendering gate. | Nothing here; the engagement skill's page-weight proxy may note it at low confidence. |
| **`llms.txt` absent** | No operator documentation confirms assistants consume it. | Nothing. The orchestrator may list it as an optional proactive idea. |
| **Site returns different HTML to different user agents** (cloaking) | Undetectable with one honest user agent, by design. | Stated as a limitation in every report. |

## What a non-rendering fetcher cannot know

- Whether content appears after JavaScript runs. The audit reads the served
  HTML only; that is the point, because assistant fetchers do the same. The
  CSR-shell finding is therefore a risk flag at medium confidence, and its
  action includes the one-line `curl` check that settles it.
- Whether a specific assistant was blocked yesterday or will be tomorrow.
  robots.txt is read once, at audit time.
- Whether a WAF challenge is shown to verified AI crawlers. Vendors maintain
  verified-bot lists; the finding points the owner there.
- Anything on pages that were not sampled. The sample is home plus up to
  five role pages; every finding lists the pages it applies to.

## A crawler user agent that is served normally

Announcing `OAI-SearchBot`, `Claude-User` or `GPTBot` and receiving the same
200 the audit's own user agent received is not a finding, and neither is a
small difference in byte count: pages carry timestamps, CSRF tokens and
rotating banners. `cr.access.ua_content_variance` only speaks when a body
differs from the baseline by more than half its size, and even then it reports
an observation at `info` rather than a defect, because A/B tests and
personalisation produce exactly the same signal.

## A training-only crawler refused at the edge

Refusing `GPTBot` while serving `OAI-SearchBot` and `Claude-User` is a policy
choice about model training, not a discoverability defect: the site can still
be fetched and cited when someone asks about it. It is reported as `info` by
`cr.access.edge_block_training`, exactly as the equivalent robots.txt rule is.

## A site whose edge enforces its own robots.txt

A robots.txt that disallows `OAI-SearchBot`, and a CDN that returns 403 to
`OAI-SearchBot`, are one decision stated twice. robots.txt is advisory; the
edge is the only place it is enforced, so a site doing both is doing the
right thing. The policy is reported once, by `cr.robots.*`, at the severity
its tier deserves. `cr.access.edge_block` never announces a token the site
has disallowed, so it cannot report the enforcement as a second finding, and
it cannot tell the owner to add a WAF allow rule for a crawler they chose to
refuse. It speaks only when robots.txt allows a crawler and the edge refuses
it anyway: policy and behaviour disagreeing.
