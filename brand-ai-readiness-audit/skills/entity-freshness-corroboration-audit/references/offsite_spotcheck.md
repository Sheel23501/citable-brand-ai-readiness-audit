# entity-freshness-corroboration-audit: the off-site spot-check (agent step)

Handout concept D says a fact is trusted when many independent places say
the same thing. A crawl of the brand's own site cannot see that. This is the
one step in the marketplace an agent performs with a web-search tool: a small,
bounded sample of what independent sources say, recorded so the probe can
report it. It is informational by design. It never changes a severity, never
counts as a finding, and never claims to measure agreement across the web.

## 1. When to run it

Run it only when **all** of these hold:

1. The probe has run once on this workdir, so `work/entity.json` exists with
   `suggested_offsite_queries`.
2. `ef.corroboration.offsite_spotcheck` is `not_evaluated` with reason
   `tool_unavailable`.
3. A web-search tool is available in the session.

Without a search tool, do nothing: the `not_evaluated` note is the correct
result, and it already carries the queries for whoever runs it next. Never
write `work/offsite_mentions.json` from memory.

## 2. Procedure

1. Read `work/entity.json`: `brand_name.value`, `domain`, and
   `suggested_offsite_queries`. If `work/extracted_facts.json` exists, read
   the facts with `status: present` (their `value` strings) and, from
   `work/entity.json`, the name; these are the only facts a mention can be
   said to agree or disagree with.
2. Run the suggested queries **in order, at most five, and no others**.
   Each query is one search-tool call. Stop after the last suggested query.
3. From every result, keep at most **ten** mentions in total:
   - skip results whose host is the audited domain or a subdomain of it
     (they are not independent);
   - skip results whose URL is already recorded;
   - classify `kind`: `news` (an article on a news or trade outlet),
     `directory` (a company register, business directory, app marketplace,
     maps listing, data provider), `review` (a review platform), `social` (a
     profile or post on a social or professional network), `wiki` (Wikipedia,
     Wikidata, another wiki), `other`.
4. For each mention record what the tool returned and nothing more: the
   result's `url` and `title` verbatim, its `snippet` verbatim (at most 200
   characters, cut with `…`, never rewritten), and the `query` that surfaced
   it. Then compare the snippet with the facts from step 1: list under
   `agrees_with` the fact ids whose value the snippet restates consistently
   (name, address, phone, `what_it_does`, …), and under `disagrees_with` any
   it contradicts, with the value seen. Both are `[]` when the snippet says
   nothing checkable. Do not open the result pages: the fetch policy does not
   allow those hosts, and a snippet is the evidence.
5. Write `work/offsite_mentions.json` in the shape below. When every search
   returned nothing usable, write it with `mentions: []`: the probe reports
   zero mentions honestly, as `inconclusive`.
6. Re-run the probe on the same workdir. Nothing is fetched again and the
   entity lookup is reused from `work/entity_lookup.json`:

   ```
   python3 skills/entity-freshness-corroboration-audit/scripts/entity_probe.py --workdir <workdir> --out <workdir>/probes/entity-freshness-corroboration-audit.json
   ```

   The check is now `inconclusive` with reason `bounded_spotcheck`, and its
   info finding lists the mentions by kind.

## 3. Rules

- **Only what the tool returned in this session.** Every mention must come
  from one of the recorded queries. A URL, title or snippet the agent
  remembers, infers or composes is not a mention.
- **Bounded.** At most five searches and ten mentions, whatever the brand's
  size. The point is a sample the reader can check, not coverage.
- **Verbatim.** Titles and snippets are copied, never summarised. Truncate
  with `…` when needed.
- **Independent means off-domain.** Profiles the brand created (its LinkedIn
  page, its app-store listing) still count, classified as `social` or
  `directory`; the reader can see what kind of corroboration exists.
- **Informational.** The probe renders the result as `info`,
  `inconclusive`. Nothing here raises, lowers or creates a graded finding.
  Disagreements go into the finding's action text ("correct the listing at
  …") and the orchestrator's narrative, not into the counts.

## 4. `work/offsite_mentions.json`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `tool` | string | yes | The search tool used, as the session names it (for example `WebSearch`). Appears in the finding's evidence. |
| `searched_at` | string | yes | UTC timestamp, `YYYY-MM-DDTHH:MM:SSZ`. |
| `brand` | string | yes | `brand_name.value` from `work/entity.json`. |
| `domain` | string | yes | `domain` from `work/entity.json`. |
| `queries` | string[] | yes | The exact query strings run, in order, at most five. The finding's title counts them. |
| `mentions` | Mention[] | yes | At most ten. May be empty. A file without this list is ignored by the probe (`tool_unavailable`). |

A `Mention`:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `url` | string | yes | The result URL verbatim. Mentions without a `url` are ignored. |
| `title` | string | no | The result title verbatim, at most 120 characters. |
| `snippet` | string | no | The result snippet verbatim, at most 200 characters. Shown in the evidence. |
| `kind` | enum | yes | `news`, `directory`, `review`, `social`, `wiki`, `other`. Tallied in the evidence. |
| `query` | string | yes | The query from `queries` that surfaced it. |
| `agrees_with` | string[] | yes | Fact ids (or `name`, `address`, `phone`) the snippet restates consistently. `[]` when none. The probe counts mentions with a non-empty list as restating a site fact. |
| `disagrees_with` | object[] | no | `{fact, seen}` for each fact the snippet contradicts, with the value seen. Used by the action text and the narrative, not by the counts. |

Example, for a brand whose site states its Bristol address and what it does:

```json
{
  "tool": "WebSearch",
  "searched_at": "2026-09-07T18:40:12Z",
  "brand": "Ledgerly",
  "domain": "ledgerly.example",
  "queries": ["\"Ledgerly\"", "\"Ledgerly\" Bristol", "\"Ledgerly\" ledgerly.example", "\"Ledgerly\" reviews", "\"Ledgerly\" site:linkedin.com"],
  "mentions": [
    {"url": "https://find-and-update.company-information.service.gov.uk/company/00000000", "title": "LEDGERLY SOFTWARE LTD - Overview", "snippet": "LEDGERLY SOFTWARE LTD. Registered office address 12 Harbour Street, Bristol, BS1 4QA. Company status Active.",
     "kind": "directory", "query": "\"Ledgerly\" Bristol", "agrees_with": ["name", "address"]},
    {"url": "https://www.g2.com/products/ledgerly/reviews", "title": "Ledgerly Reviews 2026", "snippet": "Ledgerly is invoicing and expense software for freelance designers. 4.6 out of 5 stars from 38 reviews.",
     "kind": "review", "query": "\"Ledgerly\" reviews", "agrees_with": ["what_it_does"]},
    {"url": "https://www.linkedin.com/company/ledgerly-example", "title": "Ledgerly | LinkedIn", "snippet": "Ledgerly · Software Development · Bath, England · 11-50 employees",
     "kind": "social", "query": "\"Ledgerly\" site:linkedin.com", "agrees_with": ["name"], "disagrees_with": [{"fact": "address", "seen": "Bath, England"}]}
  ]
}
```

The probe would report: "Off-site spot-check: 3 mentions across 5 queries",
by kind `directory=1, review=1, social=1`, three restating a site fact, and
the orchestrator's narrative would note the LinkedIn locality that disagrees
with the site.
