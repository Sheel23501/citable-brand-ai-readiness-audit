# engagement-audit: the engagement file

The probe writes `work/engagement.json` inside the workdir on every run
(including the degraded paths) and returns its relative path in the probe
output's `artifacts.engagement`. It records what was sampled and decided, so
the orchestrator can count requests, explain a finding, and so a reader can
check any verdict against the served evidence without re-running anything.

## 1. Always present

| Field | Type | Meaning |
|---|---|---|
| `site` | string | The audited site (scheme and host), as in the probe output. |
| `site_category` | string | The category the checks ran under, after any `--category` override. |
| `extracted_at` | string | UTC timestamp, `YYYY-MM-DDTHH:MM:SSZ`. |
| `network` | boolean | Whether the reliability checks were allowed to make requests (`false` under `--offline`, `--no-network`, `BRAND_AUDIT_NETWORK=0`). |
| `requests_made` | integer | Requests this probe made on its own account (link sample plus the 404 probe); 0 when the network was off. The orchestrator adds this to the run total. |
| `pages_used` | list | Final URLs of the usable (rendered) pages, in sample order. |
| `pages_rendered_or_not` | list | Final URLs of every page served as HTML, including gates and shells; the head-level checks ran on these. |
| `pages_excluded` | list | `{role, url, reason}` for each sampled page not graded by the content checks; reasons are `robots_disallow`, `challenge_page`, `http_error`, `network_disabled`, `non_html`, `no_rendered_content`. |

## 2. Per check, when it ran

| Field | Written by | Shape |
|---|---|---|
| `hero` | `en.hero.value_prop_unclear` | `{page, h1, h1_words, lead_excerpt (≤ 240 chars), category_noun, offer_verb, signals[]}` |
| `cta` | `en.cta.missing` | Per key page URL: `{role, hits: [[kind, text], …] (≤ 5; kinds link, button, form, mailto, tel), first_viewport_links}` |
| `navigation` | `en.nav.landmark_missing` | `{page, landmark: "nav_or_role_navigation" \| "header_list_<n>_links" \| null, nav_count, header_list_links}` |
| `site_search` | `en.nav.site_search_missing` | `{page, found: "role_search" \| "search_form" \| null}` |
| `breadcrumbs` | `en.nav.breadcrumbs_missing` | `{pages_with[], pages_checked[]}` |
| `related_links` | `en.nav.related_links_missing` | Per candidate page URL: `{role, related_heading, trailing_internal_links}` for a graded page, or `{role, listing: true, articles, listed_links}` for a listing that was not graded |
| `trust_signals` | `en.trust.signals_missing` | `{category, rule, expected[], present: {signal: {page, value, source}}, missing[], pages_checked[]}` |
| `continuity` | `en.continuity.h1_title_mismatch` | Per graded page URL: `{role, h1, title, shared[] (≤ 5 words)}` |
| `interstitials` | `en.interstitial.blocking` | Per usable page URL: a list (possibly empty) of `{tag, id, class, position, words}` for overlays that fired |
| `viewport` | `en.mobile.viewport_missing` | `{pages_with[], pages_without[]}` |
| `lang` | `en.lang.attribute_missing` | `{page, lang}` |
| `page_weight` | `en.perf.page_weight_heavy` | Per served page URL: `{role, html_bytes, script_tags, external_scripts, stylesheets, images}` |
| `link_sample` | `en.links.*` | The sampled links in order, each `{url, key, text, context, linked_from, source: "sampled_page" \| "request" \| "not_checked", status, error, skipped, verdict: "ok" \| "broken" \| "blocked" \| "skipped" \| "error" \| "not_checked"}`; `[]` when nothing could be sampled |
| `link_summary` | `en.links.*` | `{sampled, requested, blocked_cluster, ok, broken, blocked, skipped, error, not_checked}` |
| `probe_404` | `en.errors.*` | `{url, status, final_url, redirects, error, skipped, challenge, is_html, verdict}` plus, for a real 404, `{home_link, nav, search, title}`. Verdicts: `real_404`, `soft_404`, `skipped`, `challenge`, `error`, `unexpected_<status>` |

A key is absent when its check did not run (category not applicable, no usable
page, network off).

## 3. How the rest of the audit reads it

- The orchestrator adds `requests_made` to the run's request count and reads
  `link_summary` and `probe_404` for the limitations block ("N links sampled").
- The narrative may cite `hero.lead_excerpt`, the `cta` hits and the
  `trust_signals.present` values as the served evidence behind the engagement
  half; it may not add anything the file does not hold.
- Nothing here feeds the AI-answer simulation, which reads
  `work/extracted_facts.json` only.

## 4. Worked example (abridged)

A saas site whose home page has a heading, a header call to action and a
menu, whose sampled links all resolve, and whose missing pages get a real,
helpful 404:

```json
{
  "site": "https://ledgerly.example",
  "site_category": "saas_software",
  "extracted_at": "2026-09-08T09:12:40Z",
  "network": true,
  "requests_made": 5,
  "pages_used": ["https://ledgerly.example/", "https://ledgerly.example/about", "https://ledgerly.example/contact",
                 "https://ledgerly.example/pricing", "https://ledgerly.example/product", "https://ledgerly.example/blog"],
  "pages_excluded": [],
  "hero": {"page": "https://ledgerly.example/", "h1": "Invoicing and expense software built for freelance designers", "h1_words": 8,
           "lead_excerpt": "Invoicing and expense software built for freelance designers Ledgerly helps freelance designers …",
           "category_noun": "software", "offer_verb": "helps", "signals": []},
  "cta": {"https://ledgerly.example/": {"role": "home", "hits": [["link", "Start free trial"]], "first_viewport_links": 8}},
  "navigation": {"page": "https://ledgerly.example/", "landmark": "nav_or_role_navigation", "nav_count": 1, "header_list_links": 0},
  "link_summary": {"sampled": 10, "requested": 4, "blocked_cluster": 0, "ok": 10, "broken": 0, "blocked": 0, "skipped": 0, "error": 0, "not_checked": 0},
  "probe_404": {"url": "https://ledgerly.example/brand-ai-readiness-audit-404-probe-6efcff0a7f", "status": 404, "redirects": 0,
                "is_html": true, "verdict": "real_404", "home_link": true, "nav": true, "search": true, "title": "Page not found — Ledgerly"}
}
```

Every one of the 16 checks passes on this site, and the file shows the
evidence for each pass as plainly as it would for a failure.
