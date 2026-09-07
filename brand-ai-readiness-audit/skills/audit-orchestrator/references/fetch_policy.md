# Fetch policy (shared convention)

Every network request made by any script in this marketplace goes through the
shared fetch helper and obeys this file. No script opens a socket by itself.
Standard library only (`urllib`, `http.client`, `ssl`, `socket`, `gzip`,
`zlib`).

---

## 1. Methods and scope

- **GET only.** No HEAD, POST, PUT, OPTIONS. Never send a body. Never send cookies from one request to another.
- Only `http` and `https` schemes. Anything else is recorded as `unsupported_scheme` and not fetched.
- Only hosts that are: the audited host, a host reached by redirect from it, hosts of sampled links (engagement link health, capped), `en.wikipedia.org` and `www.wikidata.org` (entity probe: at most one content request to one of them per audit, optional). Nothing else.

## 2. Identity

```
User-Agent: Mozilla/5.0 (compatible; brand-ai-readiness-audit/0.1; read-only audit; +https://github.com/brand-ai-readiness-audit)
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5
Accept-Language: en,*;q=0.5
Accept-Encoding: gzip, deflate
```

The audit never impersonates a browser beyond the compatibility prefix, and
never uses the token of any bot listed in `bot_tiers.md`. The `+URL` is
replaced with the real repository URL in Step 21.

## 3. Limits

| Limit | Value | On breach |
|---|---|---|
| Connect timeout | 10 s | `error=connect_timeout` |
| Read timeout | 15 s | `error=read_timeout` |
| Total per request (including redirects) | 25 s | `error=total_timeout` |
| Redirects | 5 | `error=too_many_redirects`; last `Location` recorded |
| Response body | 2 MiB (2,097,152 bytes) | Stop reading; `truncated=true`; dependent checks drop one confidence level |
| Retry | once, only on HTTP 429, after `Retry-After` seconds capped at 10 s (default 3 s when the header is absent) | Second 429 recorded as final |
| Politeness delay | ≥ 0.5 s between requests to the same host | — |
| Requests per audit | ≤ 40 total. Budget: robots 1, sitemap ≤ 2, pages ≤ 6, 404 probe 1, link sample ≤ 15, entity lookup ≤ 2 (one host's robots.txt + one article or EntityData document), other ≤ 13 | Further requests are refused with `error=budget_exhausted` |
| Wall clock per audit | 300 s (Step 16 orchestrator); each probe ≤ 60 s | Probe returns what it has, `error=time_budget` |

Cross-host redirects are followed within the cap and recorded (`final_url`,
`redirect_chain`). A redirect to a different registrable domain sets
`cross_domain=true`, and the sampler treats the final host as the audited
host.

## 4. Content handling

- **HTML detection.** `Content-Type` starting with `text/html` or `application/xhtml+xml` ⇒ `is_html=true`. Missing header ⇒ sniff: first non-whitespace bytes after an optional BOM start with `<` ⇒ HTML. Anything else ⇒ `is_html=false`, `content_type` recorded.
- **Encoding.** `charset` from the header, else `<meta charset>` or `http-equiv` within the first 2 KiB, else UTF-8. Decode with `errors="replace"`.
- **Decompression.** gzip and deflate per `Content-Encoding`. Byte cap applies to the decoded body.
- **Never execute** scripts, load subresources, or render. This is the point: the audit sees what a non-JavaScript fetcher sees.

## 5. robots.txt

Fetched once from `<scheme>://<host>/robots.txt` and parsed per RFC 9309:

- Groups start at one or more `User-agent:` lines; rules are `Allow:` and `Disallow:`; `Sitemap:` lines are global.
- Token match is case-insensitive on the whole product token. The audit's own token is `brand-ai-readiness-audit`.
- If no group matches a token, the `*` group applies. If no `*` group exists, everything is allowed.
- Path matching: longest match wins; equal-length `Allow` beats `Disallow`; `*` matches any sequence; `$` anchors the end. An empty `Disallow:` allows everything.
- robots.txt 4xx ⇒ allow all. 5xx, timeout, or challenge page ⇒ `robots_state=unreachable`: robots-based checks become `inconclusive`; page fetching proceeds (bounded, read-only).
- **The audit obeys robots.txt for its own token and `*`.** A disallowed URL is not fetched; the fetch result has `skipped=robots_disallow`. Dependent checks become `not_evaluated` with that reason.

## 6. Challenge and block fingerprinting

A response is a **challenge page** when either:

- status ∈ {403, 429, 503} **and** at least one fingerprint below matches, or
- status = 200 **and** at least one fingerprint matches **and** visible text is < 60 words.

| Vendor | Fingerprints (any) |
|---|---|
| Cloudflare | header `cf-mitigated: challenge`; body contains `__cf_chl_`, `challenge-platform`, or `<title>Just a moment...</title>`; header `server: cloudflare` with status 403 and body containing `Attention Required` |
| Akamai | body contains `Access Denied` and `Reference #` with header `server: AkamaiGHost` |
| Imperva / Incapsula | body contains `_Incapsula_Resource` or `Incapsula incident ID` |
| DataDome | header `x-datadome` or body contains `datadome` with `captcha` |
| HUMAN / PerimeterX | body contains `_pxhd`, `px-captcha`, or `perimeterx` |
| AWS WAF | body contains `awswaf` or `aws-waf-token` |
| Vercel | body contains `Vercel Security Checkpoint` |
| Generic CAPTCHA | body contains `recaptcha` or `hcaptcha` **and** visible text < 60 words |

Effect: `challenge=true` on the fetch result; `cr.access.challenge_page` emits
an `info` finding with status `inconclusive`; every page-level check on that
URL is `inconclusive`. The finding's action tells the owner how to allow the
audit user agent or re-run from an allowed network. A challenge is **never**
reported as a site defect: the audit cannot know whether real assistants are
also challenged.

A plain 403 or 429 without fingerprint is `blocked=true`, not a challenge;
`cr.access.http_error` grades it (see `check_ids.md`).

## 7. FetchResult record

Every fetch returns this object, serialised into `fetch/manifest.json`:

```json
{
  "url": "https://example.com/pricing",
  "final_url": "https://www.example.com/pricing/",
  "redirect_chain": ["https://example.com/pricing"],
  "cross_domain": false,
  "status": 200,
  "headers": {"content-type": "text/html; charset=utf-8", "server": "nginx", "x-robots-tag": null, "last-modified": null, "cf-mitigated": null},
  "content_type": "text/html",
  "charset": "utf-8",
  "is_html": true,
  "bytes": 48213,
  "truncated": false,
  "elapsed_ms": 412,
  "challenge": false,
  "challenge_vendor": null,
  "blocked": false,
  "skipped": null,
  "error": null,
  "fetched_at": "2026-09-07T10:00:01Z",
  "body_path": "snapshots/pricing.html"
}
```

`headers` keeps only the lower-cased subset listed above plus `retry-after`,
`location`, `content-encoding`, `content-length`. `error` is one of
`connect_timeout`, `read_timeout`, `total_timeout`, `too_many_redirects`,
`dns_failure`, `connection_refused`, `tls_error`, `budget_exhausted`,
`unsupported_scheme`, `time_budget`, `network_disabled`, `host_not_allowed`, `unknown`. `skipped` is `robots_disallow`
or `budget_exhausted` or null. The helper never raises; every failure is a
record with `error` set and `status` null.

## 8. Sample manifest (sampler output, consumed by every probe)

```json
{
  "site": "https://www.example.com",
  "input_url": "example.com",
  "sampled_at": "2026-09-07T10:00:05Z",
  "site_category": {"value": "saas_software", "confidence": "medium", "signals": ["nav:pricing", "jsonld:SoftwareApplication", "nav:docs"]},
  "robots": {"state": "ok", "path": "fetch/robots.txt", "sitemaps": ["https://www.example.com/sitemap.xml"]},
  "sitemap": {"state": "ok", "url_count": 143, "path": "fetch/sitemap.xml"},
  "pages": [
    {"role": "home", "url": "https://www.example.com/", "source": "input", "fetch": { /* FetchResult */ }},
    {"role": "pricing", "url": "https://www.example.com/pricing/", "source": "nav", "fetch": { /* FetchResult */ }}
  ],
  "missing_roles": ["blog"],
  "internal_links_seen": 87,
  "requests_made": 9
}
```

`source` ∈ {`input`, `nav`, `sitemap`}. `robots.state` and `sitemap.state` ∈
{`ok`, `missing`, `unreachable`, `invalid`, `challenge`}. Each page entry also
carries `final_url`, a `summary` of the parsed document when it was HTML, and
`matched` (the keyword or pattern that selected it). The manifest additionally
records `internal_pages_estimate`, `notes`, and `site_category.scores`.
Implementation: `auditlib/sampler.py` (`sample_site`), CLI `sample_site.py`;
written to `<workdir>/sample.json`.

## 8a. Implementation

`skills/audit-orchestrator/scripts/auditlib/fetch.py` (class `Fetcher`) and
`auditlib/robots.py` implement this file. Probe scripts import them by
relative path; nothing else opens a socket. `fetch_url.py` next to them is the
manual CLI. `host_not_allowed` is returned for any host that is not the
audited host, a host reached by redirect from it, `en.wikipedia.org`, or
`www.wikidata.org` (section 1).

The entity lookup obeys the lookup host's robots.txt exactly as it obeys the
audited site's. Wikidata's `/w/api.php` search endpoint and Wikipedia's
`/w/index.php?search=` and `/api/rest_v1/` paths are disallowed for generic
agents by those files, so the audit never calls them. It fetches only paths
those files allow: a Wikipedia article (`/wiki/<Title>`) or a Wikidata
EntityData document (`/wiki/Special:EntityData/<Q-id>.json`), one per audit,
with an 8-second cap, identified by the audit user agent.

## 9. Offline mode

`--offline` (or an unreachable network) makes every fetch return
`error=network_disabled` instantly. Probes given snapshots still run all
snapshot-based checks; network-only checks become `not_evaluated` with reason
`network_disabled`. This is how Step 10's "degrades cleanly with network
disabled" and Step 18's test runner are verified.
