# entity-freshness-corroboration-audit: the entity files

The probe writes two side files inside the workdir and returns their relative
paths in the probe output's `artifacts` (`entity`, `entity_lookup`). They are
the only permitted basis for any statement in the report about the brand's
identity: what the site says its name is, which anchors it publishes, and
what the one external lookup found. Nothing the agent knows or remembers
about the brand may be substituted for them.

Both are written on every run, including the degraded path (no usable page,
offline). `work/entity.json` then has `pages_used` empty and the lookup
recorded as `skipped` or `unavailable`.

## 1. `work/entity.json`

| Field | Type | Meaning |
|---|---|---|
| `site` | string | The audited site (scheme and host), as in the probe output. |
| `domain` | string | The site's registrable domain, used for the lookup's domain-mention test and the suggested queries. |
| `site_category` | string | The category the checks ran under, after any `--category` override. |
| `extracted_at` | string | UTC timestamp, `YYYY-MM-DDTHH:MM:SSZ`. |
| `external_lookups` | boolean | Whether the one external request was permitted on this run (`false` under `--offline`, `--no-external`, `BRAND_AUDIT_EXTERNAL=0`). |
| `pages_used` | list | Final URLs of the usable pages, in sample order. |
| `pages_excluded` | list | `{role, url, reason}` for each sampled page that was not graded; reasons are `robots_disallow`, `challenge_page`, `http_error`, `network_disabled`, `non_html`, `no_rendered_content`. |
| `brand_name` | object | `{value, page, source}`: the name the checks used. `source` is `jsonld:<Type>.name`, `meta:og:site_name`, `title:common_segment`, or `host` (a guess from the host label; the NAP name component is then not graded). |
| `org_node_types` | list | The `@type` of each top-level Organization-family or Person node found (first type of each node). |
| `sameas` | list | Every `http` URL found under `sameAs` in those nodes, in document order, de-duplicated. |
| `authority_hosts_present` | list | The hosts among `sameas` that count as authorities for this category (`checks.md`, `ef.entity.sameas_no_authority`). |
| `lookup` | object | The lookup record (section 2). |
| `name_candidates` | list | `{value, source, page}` for every name the consistency check compared. |
| `press_surface` | object or null | What satisfied the press check: `{kind: "role:blog" \| "link" \| "feed", value, page}`, or `null` when nothing did (or the check was not applicable). |
| `suggested_offsite_queries` | list | At most five search strings for the agent step (`offsite_spotcheck.md`): the quoted brand name; the name with the locality when one was found; the name with the domain; the name with "reviews"; the name with `site:linkedin.com`. |

Absent on the degraded path: `org_node_types`, `sameas`,
`authority_hosts_present`, `name_candidates`, `press_surface`.

## 2. `work/entity_lookup.json` (the `lookup` record)

| Field | Meaning |
|---|---|
| `mode` | `verify_wikipedia`, `verify_wikidata`, `discover`, or `null` when nothing was requested. |
| `target` | The URL requested, or `null`. |
| `outcome` | `verified`, `ambiguous`, `collision`, `mismatch`, `not_found`, `unavailable`, `skipped` (`checks.md`, the outcome table). |
| `reason` | For `unavailable`: `network_disabled`, `robots_disallow`, `lookup_timeout`, `lookup_failed`. For `skipped`: `no_brand_name` or the no-usable-page reason. Otherwise `null`. |
| `status` | HTTP status of the request, or `null`. |
| `title` | The Wikipedia article title, or the Wikidata item's English label. |
| `qid` | The Wikidata Q-id, from the article's page data or the anchor. |
| `entries` | For a disambiguation page, the number of list entries it holds. |
| `mentions_domain` | discover mode: whether the site's domain appears in the article. |
| `label`, `website` | verify_wikidata mode: the item's English label and official website (P856). |
| `requests_made` | HTTP requests spent on the lookup (the content request plus that host's robots.txt when it had to be fetched). |
| `checked_at` | UTC timestamp. |
| `error` | Present when the request failed: the fetch error, the HTTP status, or the JSON parse message. |
| `reused` | `true` when this run reused the saved record instead of requesting again. Set only on the copy under `lookup` in `work/entity.json`; the saved `work/entity_lookup.json` is left as first written. |

Reuse rule: a `--workdir` run reuses the saved record whenever its outcome is
anything other than `unavailable`, so the off-site re-run and the
orchestrator's composition never spend a second external request. Delete the
file to force a fresh lookup.

## 3. How the rest of the audit reads them

- The orchestrator's narrative may state the brand's name, its published
  anchors and the lookup outcome only as recorded here, and quotes `source`
  and `target` when it does.
- The off-site spot-check (`offsite_spotcheck.md`) takes its queries from
  `suggested_offsite_queries` and its comparison facts from
  `work/extracted_facts.json`; it does not read anything else about the brand.
- The AI-answer simulation never reads these files: it is restricted to
  `work/extracted_facts.json` (`report_schema.md`,
  `ai_answer_simulation.basis`).

## 4. Worked example

For a `saas_software` site whose Organization node links Wikidata, Wikipedia,
LinkedIn and Companies House, audited with the lookup switched off:

```json
{
  "site": "https://ledgerly.example",
  "domain": "ledgerly.example",
  "site_category": "saas_software",
  "extracted_at": "2026-09-07T18:24:55Z",
  "external_lookups": false,
  "pages_used": ["https://ledgerly.example/", "https://ledgerly.example/about", "https://ledgerly.example/contact",
                 "https://ledgerly.example/pricing", "https://ledgerly.example/product", "https://ledgerly.example/blog"],
  "pages_excluded": [],
  "brand_name": {"value": "Ledgerly", "page": "https://ledgerly.example/", "source": "jsonld:Organization.name"},
  "org_node_types": ["Organization"],
  "sameas": ["https://www.wikidata.org/wiki/Q000000001", "https://en.wikipedia.org/wiki/Ledgerly_(software)",
             "https://www.linkedin.com/company/ledgerly-example",
             "https://find-and-update.company-information.service.gov.uk/company/00000000"],
  "authority_hosts_present": ["en.wikipedia.org", "find-and-update.company-information.service.gov.uk", "www.linkedin.com", "www.wikidata.org"],
  "lookup": {"mode": null, "target": null, "outcome": "unavailable", "reason": "network_disabled", "status": null,
             "title": null, "qid": null, "entries": 0, "mentions_domain": null, "label": null, "website": null,
             "requests_made": 0, "checked_at": "2026-09-07T18:24:55Z"},
  "name_candidates": [{"value": "Ledgerly", "source": "meta:og:site_name", "page": "https://ledgerly.example/"},
                      {"value": "Ledgerly", "source": "jsonld:Organization.name", "page": "https://ledgerly.example/"}],
  "press_surface": {"kind": "role:blog", "value": "https://ledgerly.example/blog", "page": "https://ledgerly.example/blog"},
  "suggested_offsite_queries": ["\"Ledgerly\"", "\"Ledgerly\" ledgerly.example", "\"Ledgerly\" reviews", "\"Ledgerly\" site:linkedin.com"]
}
```

With the lookup enabled, `mode` would be `verify_wikipedia`, `target` the
article URL, and `outcome` `verified` (an article, not a disambiguation
page): all three `wikidata_*` checks pass and no external request is made on
any later `--workdir` run.
