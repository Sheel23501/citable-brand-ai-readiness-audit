---
name: crawl-render-audit
description: Checks whether a non-JavaScript-executing fetcher (the kind used by most AI assistants) can reach and read a website. Detects robots.txt blocks on named AI bots by tier, blanket disallows, JavaScript-required entry gates, client-rendered shells with no server-rendered text, missing or broken sitemaps, noindex directives, and misdirected canonicals. Use when diagnosing why AI crawlers or assistants cannot access or read a site, or as the reachability stage of a brand AI-readiness audit.
license: MIT
compatibility: Requires Python 3.8+ (standard library only) and outbound HTTPS access. Read-only GET requests only. Respects robots.txt.
metadata:
  marketplace: brand-ai-readiness-audit
  concern: reachability-and-readability
allowed-tools: Bash(python3:*) Read
---

# Crawl and Render Audit

## When to use

Use when you need to know whether a crawler is let in and can read the page
without executing JavaScript. This is the first gate in the chain: if it
fails, nothing downstream (facts, entity, freshness, engagement) can be
recovered, so run it first and read it first.

## Inputs

One of:

- `--url <site>`: a URL or bare domain. The script samples the site itself
  (home plus up to five role pages) and writes a workdir.
- `--workdir <dir>`: a workdir produced by the orchestrator or by
  `audit-orchestrator/scripts/sample_site.py`, containing `sample.json`,
  `snapshots/`, and `fetch/robots.txt`. Nothing is fetched again.

Optional: `--out <file>` to write the JSON to a file, `--category <id>` to
override the inferred site category, `--offline` to prove the degraded path.

## Procedure

1. Run the probe. From the marketplace root:

   ```
   python3 skills/crawl-render-audit/scripts/crawl_probe.py --url https://example.com --workdir audit-example
   ```

   or, when the orchestrator has already sampled the site:

   ```
   python3 skills/crawl-render-audit/scripts/crawl_probe.py --workdir audit-example --out audit-example/probes/crawl-render-audit.json
   ```

2. Read the `error` field first. `null` means every check ran. A non-null
   value names the check group that failed internally; the other groups are
   still valid.

3. Read `checks`. Every one of the 16 `cr.*` checks appears with a status.
   `pass` needs no action. `not_evaluated` and `inconclusive` carry a `reason`
   (`robots_disallow`, `challenge_page`, `no_html_pages`, `robots_unreachable`,
   `sitemap_missing`, `network_disabled`) and mean the audit could not see,
   not that the site is fine.

4. Read `findings` in order. Each has `severity`, `confidence`, `evidence`
   (one sentence), `evidence_items` (the verbatim proof), `why_it_matters`,
   and a `suggested_action` with `summary`, `detail`, `impact`, `effort`,
   `priority`. Do not restate a finding without its evidence.

5. Apply the interpretation rules in `references/checks.md` when explaining
   a finding, and the non-findings in `references/non_findings.md` before
   adding anything the script did not flag. Never add a finding the script
   did not produce; if you believe one is missing, report the gap as a
   limitation.

6. Hand the JSON to the orchestrator unchanged. It owns IDs, dedupe, and
   counts. When used standalone, present the findings grouped by severity
   with their evidence and actions, then list the non-pass checks with
   their reasons.

## Output

The probe output object defined in the shared conventions
(`../audit-orchestrator/references/report_schema.md`, section 1): a `checks`
list with every check's status, plus `findings` for failures only. Check ids,
default severities and pass conditions are the `cr.*` rows of
`../audit-orchestrator/references/check_ids.md`. Severity and confidence follow
`../audit-orchestrator/references/severity_confidence_rubric.md`; category
gating follows `../audit-orchestrator/references/site_categories.md`; all
network access follows `../audit-orchestrator/references/fetch_policy.md`.

## References

- `references/checks.md`: what each of the 16 checks detects, the exact rule,
  the evidence it records, and why the severity and confidence are what they are.
- `references/non_findings.md`: conditions this skill deliberately does not
  flag, and the limits of what a non-rendering fetcher can know.
