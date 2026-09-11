---
name: entity-freshness-corroboration-audit
description: Checks whether a brand's facts are trustworthy and unambiguous to AI assistants. Detects missing entity-disambiguation anchors (Organization sameAs to Wikidata, Wikipedia, LinkedIn, a company register), a brand name that resolves to something else or to a disambiguation page, missing plain-text identity facts (name, address, phone), inconsistent naming, absent or contradictory freshness signals (visible dates, copyright year, JSON-LD dateModified), and a missing press or newsroom corroboration surface. Optionally performs a bounded off-site mention spot-check when a web-search tool is available. Use when diagnosing entity confusion, stale answers, or low trust in AI assistants, or as the trust stage of a brand AI-readiness audit.
license: MIT
compatibility: Requires Python 3.8+ (standard library only). With --url it makes read-only GET requests under the shared fetch policy and respects robots.txt. Makes at most one optional request to en.wikipedia.org or www.wikidata.org (disable with --no-external); degrades gracefully without it. The off-site spot-check needs an agent web-search tool and is skipped with an explicit note if none is available. Imports the shared auditlib from ../audit-orchestrator/scripts; install it with audit-orchestrator.
metadata:
  marketplace: brand-ai-readiness-audit
  concern: trust-identity-freshness
allowed-tools: Bash(python3:*) Read Write WebSearch
---

# Entity, Freshness and Corroboration Audit

## When to use

Use when you need to know whether an assistant can tell this brand apart
from everything else that shares its name, whether the site states the
identity facts a cross-checker reads, and whether its content can be shown to
be current and corroborated. This is the trust stage of the chain: the
crawl-render skill shows whether a crawler is let in and can read the page,
the fact-extractability skill whether the page says anything quotable, and
this skill whether what it says will be believed and attributed to the right
entity. It also writes the entity file that any statement about the brand's
identity must be drawn from.

## Inputs

One of:

- `--url <site>`: a URL or bare domain. The script samples the site itself
  (home plus up to five role pages) and writes a workdir.
- `--workdir <dir>`: a workdir produced by the orchestrator or by
  `audit-orchestrator/scripts/sample_site.py`, containing `sample.json` and
  `snapshots/`. Site pages are not fetched again; the one external lookup is
  made unless `work/entity_lookup.json` already holds a result.

Optional: `--out <file>` to write the JSON to a file, `--category <id>` to
override the inferred site category (this changes the NAP requirement and
which checks apply), `--no-external` (or `BRAND_AUDIT_EXTERNAL=0`) to skip
the one Wikipedia or Wikidata request, `--offline` to prove the degraded path.

## Procedure

1. Run the probe. From the marketplace root:

   ```
   python3 skills/entity-freshness-corroboration-audit/scripts/entity_probe.py --url https://example.com --workdir audit-example
   ```

   or, when the orchestrator has already sampled the site:

   ```
   python3 skills/entity-freshness-corroboration-audit/scripts/entity_probe.py --workdir audit-example --out audit-example/probes/entity-freshness-corroboration-audit.json
   ```

2. Read the `error` field first. `null` means every check group ran
   (`lookup`, `sameas`, `nap`, `name`, `freshness`, `press`, `offsite`). A
   non-null value names the group that failed internally; its checks are
   `not_evaluated` with reason `dependency_failed`, the other groups are still
   valid, and the entity file is still written.

3. Read `site_category` and `pages_examined`. The category decides the NAP
   requirement, the severity overrides, and whether the press check applies
   (`site_categories.md` sections 4 and 5). `pages_examined` lists the usable
   pages; pages excluded because of robots.txt, a bot-protection challenge, an
   HTTP error, a non-HTML response, or a JavaScript gate or client-rendered
   shell are listed in `work/entity.json` under `pages_excluded` with a
   reason. Nothing on them is graded; the crawl-render skill owns those
   findings.

4. Read `checks`. Every one of the 12 `ef.*` checks appears with a status.
   `pass` needs no action. `not_evaluated` and `inconclusive` carry a
   `reason` and mean the audit could not see, not that the site is fine:
   - page reasons: `robots_disallow`, `challenge_page`, `no_rendered_content`,
     `non_html`, `no_html_pages`, `network_disabled`;
   - lookup reasons: `lookup_unavailable` (the two dependent checks),
     `network_disabled`, `robots_disallow`, `lookup_timeout`,
     `lookup_failed`, `no_brand_name`;
   - structural: `dependency_failed`, `not_applicable_for_category`,
     `context_error`;
   - spot-check: `tool_unavailable` (not run), `bounded_spotcheck`
     (run; `inconclusive` by design).

5. Read `findings` in order. Each has `severity`, `confidence`, `evidence`
   (one or two sentences), `evidence_items` (the verbatim proof, including
   the URL of the one external document when the lookup ran),
   `why_it_matters`, and a `suggested_action` with `summary`, `detail`,
   `impact`, `effort`, `priority`. Two `info` notes are normal on a run
   without network access or without a search tool
   (`ef.entity.wikidata_unavailable`, `ef.corroboration.offsite_spotcheck`):
   they say what was not checked and are not defects. Do not restate a
   finding without its evidence.

6. Open `work/entity.json` (path in `artifacts.entity`) and, when present,
   `work/entity_lookup.json` (`artifacts.entity_lookup`). They are the only
   permitted basis for any statement about the brand's identity: the name
   the site states and where it came from, the `sameAs` anchors it
   publishes, and what the lookup fetched and decided. Never fill a gap from
   memory: if the lookup says `not_found`, the report says no article was
   found under that title, even if you believe one exists.
   `references/entity_file.md` defines every field.

7. Off-site spot-check (agent step). If `ef.corroboration.offsite_spotcheck`
   is `not_evaluated` with reason `tool_unavailable` **and** a web-search tool
   is available, follow `references/offsite_spotcheck.md`: run the
   `suggested_offsite_queries` from `work/entity.json` (at most five
   searches), record at most ten mentions exactly as the tool returned them,
   write `work/offsite_mentions.json`, and re-run step 1 in `--workdir` mode.
   Nothing is fetched again and the lookup is reused. Without a search tool,
   leave the note as it is and do not write the file.

8. Apply the interpretation rules in `references/checks.md` when explaining
   a finding, and the non-findings in `references/non_findings.md` before
   adding anything the script did not flag. Never add a finding the script
   did not produce; if you believe one is missing, report the gap as a
   limitation.

9. Hand the JSON to the orchestrator unchanged. It owns IDs, dedupe, and
   counts. When used standalone, present the findings grouped by severity
   with their evidence and actions, then the identity table (brand name and
   its source, `sameAs` targets, lookup mode and outcome), then the off-site
   mentions if any, then the non-pass checks with their reasons.

## Output

The probe output object defined in the shared conventions
(`../audit-orchestrator/references/report_schema.md`, section 1): a `checks`
list with every check's status, plus `findings` for failures only. Check ids,
default severities and pass conditions are the `ef.*` rows of
`../audit-orchestrator/references/check_ids.md`. Severity and confidence follow
`../audit-orchestrator/references/severity_confidence_rubric.md`; category
gating and overrides follow `../audit-orchestrator/references/site_categories.md`;
all network access, including the one external lookup, follows
`../audit-orchestrator/references/fetch_policy.md`.

Also writes `work/entity.json` and `work/entity_lookup.json` (paths in
`artifacts`), and reads `work/offsite_mentions.json` when the agent step has
written it. The off-site spot-check (`ef.corroboration.offsite_spotcheck`) is
`info` and never affects counts; without a search tool it is `not_evaluated`.

## References

- `references/checks.md`: what each of the 12 checks detects, the exact rule,
  the entity lookup's modes and outcomes, the evidence recorded, and why the
  severity and confidence are what they are.
- `references/non_findings.md`: conditions this skill deliberately does not
  flag (a common-word brand name, social-only `sameAs`, a one-year-old
  copyright, …), and the limits of one lookup over six pages.
- `references/entity_file.md`: `work/entity.json` and
  `work/entity_lookup.json`, field by field, with the reuse rule.
- `references/offsite_spotcheck.md`: the agent step, its bounds (five
  searches, ten mentions, verbatim only), and the exact shape of
  `work/offsite_mentions.json`.
