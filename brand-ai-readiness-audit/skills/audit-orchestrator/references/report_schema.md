# Report schema (shared convention)

Canonical definition of what a probe emits and what the orchestrator emits.
Every probe script, the compose script, the validate script, and every SKILL.md
must conform to this file. Do not define fields anywhere else.

Related conventions: `severity_confidence_rubric.md` (allowed values and how to
pick them), `check_ids.md` (naming and registry), `coverage_map.md` (mechanism
letters and dedupe table), `site_categories.md`, `bot_tiers.md`,
`fetch_policy.md`.

---

## 1. Probe output

Each probe script writes one JSON object to stdout (or to a file when `--out`
is given). It never raises; on internal error it still emits this object with
`error` set and `findings` empty.

```json
{
  "probe": "crawl-render-audit",
  "probe_version": "0.1.0",
  "site": "https://example.com",
  "run_at": "2026-09-07T10:00:00Z",
  "site_category": "saas_software",
  "pages_examined": ["https://example.com/", "https://example.com/pricing"],
  "checks": [
    {"check_id": "cr.robots.blanket_disallow", "status": "pass"},
    {"check_id": "cr.render.csr_shell", "status": "fail", "pages": ["https://example.com/"]},
    {"check_id": "cr.index.sitemap_invalid", "status": "not_evaluated", "reason": "sitemap_missing"}
  ],
  "findings": [ /* Finding objects, section 2 */ ],
  "artifacts": {"extracted_facts": "work/extracted_facts.json"},
  "error": null
}
```

| Field | Type | Required | Rule |
|---|---|---|---|
| `probe` | string | yes | Skill `name` from its SKILL.md frontmatter. |
| `probe_version` | string | yes | Semver. Bump when a check is added or a rule changes. |
| `site` | string | yes | Normalised origin, trailing slash removed, scheme included. |
| `run_at` | string | yes | UTC ISO-8601 with `Z`. |
| `site_category` | string | yes | One of the ids in `site_categories.md`, or `unknown`. |
| `pages_examined` | string[] | yes | Absolute final URLs actually read. |
| `checks` | Check[] | yes | One entry per check the probe knows about, always, including passes. This is what makes the positive report possible. |
| `findings` | Finding[] | yes | Only for checks whose status is `fail`, `inconclusive`, or `not_evaluated`. A `pass` never produces a finding. |
| `artifacts` | object | no | Paths to side files (for example the extracted-facts file). |
| `error` | string or null | yes | Non-null only when the probe hit an internal error. The orchestrator surfaces this in `limitations`. |

### Check

| Field | Type | Required | Rule |
|---|---|---|---|
| `check_id` | string | yes | From the registry in `check_ids.md`. |
| `status` | enum | yes | `pass` / `fail` / `inconclusive` / `not_evaluated`. |
| `pages` | string[] | no | Pages the status applies to. Omit for site-level checks. |
| `reason` | string | when not `pass`/`fail` | Machine-readable snake_case reason, e.g. `challenge_page`, `robots_disallow`, `network_disabled`, `tool_unavailable`, `not_applicable_for_category`, `dependency_failed`, `role_page_not_sampled`, `navigation_not_readable`. |

Status meanings:

- `pass` — the check ran on real evidence and found no problem.
- `fail` — the check ran and found the condition. Produces a finding with a real severity, except for checks registered as `info` by default (policy notes such as a training-only bot block): those keep status `fail` because the condition is real, but severity `info` because it is not a defect.
- `inconclusive` — the check ran but the evidence cannot be trusted (challenge page, truncated body). Produces an `info` finding that says so.
- `not_evaluated` — the check did not run (network off, tool unavailable, category makes it not applicable, an upstream condition made it meaningless). Produces an `info` finding only when nothing else in the report explains the gap (`network_disabled`, `tool_unavailable`). Reasons that another probe already explains produce no finding: `robots_disallow` and `challenge_page` (crawl-render carries the finding), `no_rendered_content` (the page is a JS gate or CSR shell, again crawl-render's finding), `non_html`, `not_applicable_for_category`, `dependency_failed`. Nor do the two reasons the orchestrator's absence gate assigns (`severity_confidence_rubric.md` rule 6): `role_page_not_sampled` (no page that could have carried the thing was reached) and `navigation_not_readable` (the sample was too thin to show the site's navigation); a `limitations` line explains them. The `checks` list still carries every one of them with its reason, and compose lists them under coverage.

---

## 2. Finding

```json
{
  "check_id": "cr.render.csr_shell",
  "title": "Home page is a client-rendered shell with no server-rendered text",
  "status": "fail",
  "severity": "critical",
  "confidence": "medium",
  "effort": "high",
  "mechanism": "render",
  "affected_pages": ["https://example.com/"],
  "evidence": "Home page HTML contains 14 words of visible text and an empty <div id=\"root\"> loaded by 612 KB of scripts.",
  "evidence_items": [
    {"page": "https://example.com/", "kind": "computed", "value": "visible_text_words=14; script_bytes=612340; root_div_empty=true"},
    {"page": "https://example.com/", "kind": "html_excerpt", "value": "<div id=\"root\"></div><script src=\"/static/js/main.9f2c.js\"></script>"}
  ],
  "why_it_matters": "Assistants that do not execute JavaScript receive an empty page, so nothing on it can be quoted or cited. The brand is invisible.",
  "suggested_action": {
    "summary": "Server-render or pre-render the home page so its heading, value proposition, and navigation are in the initial HTML.",
    "detail": "Use the framework's SSR or static export for the home, about, pricing, and contact routes first. Keep the same URLs. Verify with `curl -s https://example.com/ | grep -c \"<h1\"` returning 1.",
    "priority": "high",
    "effort": "high"
  },
  "references": ["https://developers.google.com/search/docs/crawling-indexing/javascript-seo-basics"],
  "dedupe_key": "cr.render.csr_shell|https://example.com/"
}
```

| Field | Type | Required | Rule |
|---|---|---|---|
| `check_id` | string | yes | Registry id. |
| `title` | string | yes | ≤ 90 chars. States the problem as a fact about this site. No verbs of instruction. Name the page role when page-specific ("Pricing page…"). |
| `status` | enum | yes | `fail` / `inconclusive` / `not_evaluated` (never `pass`). |
| `severity` | enum | yes | `critical` / `high` / `medium` / `low` / `info`. Pick per `severity_confidence_rubric.md`. `inconclusive` and `not_evaluated` are always `info`. |
| `confidence` | enum | yes | `high` / `medium` / `low`. Pick per the rubric. |
| `effort` | enum | yes | `low` / `medium` / `high` / `n/a`. Rubric section 4. `n/a` only for `info`. Mirrored into `suggested_action.effort`. |
| `mechanism` | enum | yes | The stage from `coverage_map.md` section 2: `access` / `render` / `extract` / `entity` / `freshness` / `corroboration` / `engagement`. (The handout's concept letters A–F are never used here; the coverage map relates stages to them.) |
| `affected_pages` | string[] | yes | Absolute final URLs. Empty array only for site-level findings (robots, sitemap, Wikidata). |
| `evidence` | string | yes | One sentence, ≤ 300 chars, that a non-expert can read: what was observed, where, and the count when sampled ("Crawled 5 pages; 0/5 contain JSON-LD."). This is the handout's required `evidence` field and is generated from `evidence_items`, never written independently of them. |
| `evidence_items` | Evidence[] | yes | At least one item. The verbatim proof behind the sentence. |
| `why_it_matters` | string | yes | 1–2 sentences tying the finding to the mechanism, using one of the Round-2 words: invisible, stale, or bouncing. Plain language. |
| `suggested_action` | object | yes | The handout's required field, as an object. `summary` (string, one sentence, starts with a verb, names the page or element), `detail` (string, 1–3 sentences: how to do it and how to verify), `impact` (`high` / `medium` / `low`, derived from severity: critical or high → `high`, medium → `medium`, low or info → `low`), `effort` (same enum as the finding's `effort`), `priority` (`high` / `medium` / `low`: equals `impact`, lowered one level when `confidence` is `low`, so a certain medium outranks a guessed high). Impact, effort and priority together are what let a non-expert triage without reading every finding. |
| `references` | string[] | no | Absolute URLs to primary sources only (vendor docs, RFCs, schema.org). Anything here must survive Step 20 source verification. |
| `dedupe_key` | string | yes | `check_id` + `|` + sorted affected pages joined by `,` (empty when site-level). Used by compose. |

### Evidence

| Field | Type | Required | Rule |
|---|---|---|---|
| `page` | string | yes | Absolute URL the evidence came from, or `robots.txt` / `sitemap` / `external:<host>` for non-page sources. |
| `kind` | enum | yes | `http_status`, `http_header`, `robots_rule`, `html_excerpt`, `jsonld_excerpt`, `text_excerpt`, `computed`, `external`. |
| `value` | string | yes | ≤ 300 chars, whitespace-collapsed. Excerpts are truncated with `…`. Computed values are `key=value; key=value`. |
| `location` | string | no | Where in the document: a tag path like `head > script[type=application/ld+json][2]`, or `line 41`. |
| `note` | string | no | One sentence of interpretation only when the value alone is not self-explanatory. |

Evidence rules:

- Quote what the fetcher actually received. Never paraphrase into the `value` field.
- Never include content that was not publicly served by the site or the named external source.
- For sampled checks, state the sample: `sampled=15; failed=3` in a `computed` item.

---

## 3. Final report (orchestrator output)

Two files: `report.json` and `report.md`. The Markdown is rendered from the
JSON and contains nothing the JSON does not.

### 3a. Required floor

These are the handout's minimum required shape ("a floor, not a ceiling") plus
its exact field names and value shapes. They must always be present and
non-empty (except `findings`, which may be an empty array for a clean site).
The validate script rejects any report missing them.

| Field | Type | Rule |
|---|---|---|
| `site` | string | Registrable host as in the handout sample (`example.com`). The full origin goes in `site_url`. |
| `audited_at` | string | UTC ISO-8601 `Z`. |
| `summary` | object | `total_findings`, `critical`, `high`, `medium`, `low`, `info` — integers; `total_findings` equals the sum and equals `findings.length`. Field names mirror the handout sample exactly (`total_findings`, not `total`). |
| `findings` | Finding[] | Each with at least `id`, `title`, `severity`, `evidence` (non-empty string), `suggested_action` (object with non-empty `summary` and `priority`). These are the five per-finding fields the handout requires, in the shapes its sample shows. |
| `findings[].id` | string | `F-001`, `F-002`, … zero-padded to 3, assigned after sorting (section 4). Unique. |

### 3b. Superset (what compose actually writes)

```json
{
  "site": "example.com",
  "site_url": "https://www.example.com",
  "audited_at": "2026-09-07T10:00:00Z",
  "tool": {"name": "brand-ai-readiness-audit", "version": "0.1.0"},
  "input_url": "example.com",
  "site_category": {"value": "saas_software", "confidence": "medium", "signals": ["nav:pricing", "nav:docs", "jsonld:SoftwareApplication"]},
  "pages_sampled": [
    {"role": "home", "url": "https://example.com/", "status": 200, "snapshot": "snapshots/home.html", "challenge": false}
  ],
  "summary": {"total_findings": 7, "critical": 0, "high": 1, "medium": 2, "low": 3, "info": 1,
              "checks_run": 40, "checks_passed": 31, "checks_failed": 6, "checks_inconclusive": 1, "checks_not_evaluated": 2,
              "headline": "1 high finding on the 6 pages read. Start with F-002: Pricing exists only as an image.",
              "start_with": "F-002"},
  "findings": [ /* Finding + id, source_skill, quick_win, rank */ ],
  "quick_wins": ["F-002", "F-004"],
  "passed_checks": [{"check_id": "cr.robots.blanket_disallow", "title": "robots.txt does not blanket-disallow crawlers", "source_skill": "crawl-render-audit"}],
  "coverage": {
    "handout_concepts": {"A": "covered", "B": "covered", "C": "covered", "D": "partial", "E": "out_of_scope", "F": "out_of_scope"},
    "stages": {"access": "evaluated", "render": "evaluated", "extract": "evaluated", "entity": "partial", "freshness": "evaluated", "corroboration": "partial", "engagement": "evaluated"},
    "not_evaluated": [{"check_id": "ef.corroboration.offsite_spotcheck", "reason": "tool_unavailable"}]
  },
  "proactive_recommendations": [
    {"title": "Publish a FAQ page answering the five questions buyers ask", "rationale": "…", "mechanism": "extract", "effort": "medium", "priority": "medium"}
  ],
  "ai_answer_simulation": {
    "basis": "extracted_facts_only",
    "facts_file": "work/extracted_facts.json",
    "questions": [
      {"question": "What does Example do?", "answerable": true, "answer_from_facts": "…", "facts_used": ["what_it_does"], "missing_facts": []},
      {"question": "How much does Example cost?", "answerable": false, "answer_from_facts": null, "facts_used": [], "missing_facts": ["pricing"]}
    ]
  },
  "narrative_summary": "Three to six sentences written by the orchestrator agent.",
  "limitations": ["This report reflects a single point-in-time fetch of 6 sampled pages; personalised or A/B-tested pages may differ between runs.", "Off-site mention spot-check skipped: no search tool available."],
  "suppressed_findings": [ /* Findings folded by the dedupe table, kept for transparency */ ],
  "run": {"wall_clock_seconds": 94.2, "requests_made": 23, "probe_errors": []}
}
```

Extra fields on each final Finding, added by compose:

| Field | Type | Rule |
|---|---|---|
| `id` | string | `F-###`. |
| `rank` | integer | 1-based position after sorting. |
| `source_skill` | string | Probe `name`. |
| `quick_win` | boolean | Rubric section 5. |
| `round2_mode` | enum | `invisible` / `stale` / `bouncing`, derived from the stage: access, render, extract → `invisible`; entity, freshness, corroboration → `stale`; engagement → `bouncing`. Used to group the narrative. |
| `handout_concepts` | string[] | The Round-2 appendix letters this finding is evidence for, primary first, from `coverage_map.md` section 2 (for example `["A","B"]`). Engagement findings carry `[]`. |
| `pipeline_stage` | enum | Citation-failure stage, derived from the stage (`coverage_map.md` section 7): access, render → `retrieval`; extract, entity, freshness, corroboration → `ranking`; `or.simulation.*` → `selection`; engagement → `post_click`. |
| `opportunity_type` | enum | `technical` or `content`, Adobe's own split for detected issues (`coverage_map.md` section 7). |
| `merged_from` | string[] | `dedupe_key`s folded into this finding, if any. |
| `absence_scope` | enum | Optional. `sample` when the orchestrator's absence gate (rubric rule 6) scoped a site-level absence claim to the pages read: confidence is `low`, severity at most `medium`, and the evidence names the pages not reached. Absent on every other finding. |
| `language_scope` | string | Optional. The bare language subtag when the language gate (rubric rule 7) scoped an English-phrase-list check on a non-English site. Absent otherwise. |

`summary.headline` is one deterministic sentence for the reader who opens
nothing else: how many findings at which severities on how many pages were
read, which finding to start with, whether any checks had no verdict because
parts of the site were not reached, and, first of all, whether the run was
incomplete. `summary.start_with` is the id of the finding to act on first:
the first quick win when there is one, otherwise the finding above `info`
with the highest `suggested_action.priority` (priority already folds severity
and confidence), then the lowest `effort`, then the highest `confidence`,
then rank; `null` when nothing is above `info`. Both are computed by compose
and never written by the agent; the validator recomputes `start_with` and
rejects a report whose value differs (`severity_confidence_rubric.md`
section 5, "Where to start").

`limitations` always begins with the boilerplate lines that apply (compose adds
them, the agent never removes them): the single point-in-time fetch statement
with the page count; "no content pages beyond the home page were discoverable"
when only home was sampled; "Not checked, because the … pages were not reached
…: <check ids>" when the absence gate withdrew a check (`role_page_not_sampled`);
"The home page exposed N internal links and led to K of 5 role pages …" when it
withdrew the press check (`navigation_not_readable`); "N pages skipped: rate
limited (429)" when any sampled page ended in 429; "challenge page served on N
pages: those checks are inconclusive" when any page was challenged; the language
line when the language gate fired; "this audit reads served HTML only and does
not execute JavaScript or query live assistants" always.

`ai_answer_simulation.basis` must be exactly `extracted_facts_only`. The
orchestrator agent may not use anything it knows or fetched itself; if a
question cannot be answered from the facts file, `answerable` is `false` and
`missing_facts` names what is absent. See the orchestrator SKILL.md (Step 17).

---

## 4. Ordering, IDs and counting

1. Drop nothing: every finding from every probe enters compose.
2. Apply the dedupe table in `coverage_map.md` section 4. Folded findings move to `suppressed_findings` with `merged_into` set.
3. Sort by: severity (critical → info), then confidence (high → low), then `affected_pages.length` desc, then `check_id` asc. Sorting is stable.
4. Assign `id` and `rank` in that order.
5. `summary` counts only what remains in `findings`. Suppressed findings are not counted. `summary.total_findings` = `findings.length`.
6. `quick_wins` is the ordered list of ids where `quick_win` is true.

---

## 5. File names and locations (run layout)

```
<workdir>/
  fetch/               raw fetch results and manifest.json (fetch_policy.md section 7), robots.txt, sitemap.xml
  snapshots/           <role>.html, one per sampled page
  sample.json          sample manifest (fetch_policy.md section 8)
  probes/              <probe-name>.json, one per probe
  work/extracted_facts.json
  report.json
  report.md
```

`<workdir>` defaults to `./audit-<host>-<YYYYMMDD-HHMMSS>/`.

---

## 6. Markdown rendering rules

- Title line: `# AI-readiness audit: <site>` then category, date, and the counts line.
- Section order: Summary (the `headline` sentence, then the counts) → Narrative → Quick wins → Findings (grouped by severity, each with evidence as a code block) → What is working (passed checks) → AI answer simulation → Proactive recommendations → Coverage and limitations.
- The Quick wins section is present whenever `summary.start_with` is set. It lists the quick wins in rank order or, when none qualifies, says so and names `start_with` with its action, effort and confidence, so a report with defects always tells the reader where to begin. It is absent only when nothing is above `info`.
- Every finding shows: id, title, severity, confidence, effort, affected pages, the evidence sentence, the evidence items as a code block, why it matters, suggested action summary, detail, priority.
- No content appears in the Markdown that is absent from the JSON.
