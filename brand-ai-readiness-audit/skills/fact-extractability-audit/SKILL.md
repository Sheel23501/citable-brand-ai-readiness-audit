---
name: fact-extractability-audit
description: Checks whether the specific facts an AI assistant would quote (what the brand does, price, contact, hours, specs) exist as plain, extractable text on the page rather than only in images, PDFs, or client-side rendering. Also validates JSON-LD structured data (parseable, required properties present), page self-identification (title, H1, meta description, Open Graph), image alt text, and FAQ-shaped content. Use when diagnosing why an assistant cannot quote a fact about a brand, or as the fact-extraction stage of a brand AI-readiness audit.
license: MIT
compatibility: Requires Python 3.8+ (standard library only). With --url it makes read-only GET requests under the shared fetch policy and respects robots.txt; with --workdir it reads existing snapshots and needs no network.
metadata:
  marketplace: brand-ai-readiness-audit
  concern: fact-extractability
allowed-tools: Bash(python3:*) Read
---

# Fact Extractability Audit

## When to use

Use when you need to know whether a machine can pick out the specific facts
someone would ask about (what the brand does, what it costs, who it is for,
how to reach it, where it is, when it is open) from the text a crawler
actually receives. This is the third gate in the chain: the crawl-render
skill shows whether a crawler is let in and can read the page; this skill
asks whether the page then says anything quotable. It also writes the facts
file that the orchestrator's AI-answer simulation is restricted to, so run it
before any statement about "what an assistant would say".

## Inputs

One of:

- `--url <site>`: a URL or bare domain. The script samples the site itself
  (home plus up to five role pages) and writes a workdir.
- `--workdir <dir>`: a workdir produced by the orchestrator or by
  `audit-orchestrator/scripts/sample_site.py`, containing `sample.json` and
  `snapshots/`. Nothing is fetched again.

Optional: `--out <file>` to write the JSON to a file, `--category <id>` to
override the inferred site category (this changes which facts are required),
`--offline` to prove the degraded path.

## Procedure

1. Run the probe. From the marketplace root:

   ```
   python3 skills/fact-extractability-audit/scripts/facts_probe.py --url https://example.com --workdir audit-example
   ```

   or, when the orchestrator has already sampled the site:

   ```
   python3 skills/fact-extractability-audit/scripts/facts_probe.py --workdir audit-example --out audit-example/probes/fact-extractability-audit.json
   ```

2. Read the `error` field first. `null` means every check group ran. A
   non-null value names the group that failed internally (`facts`,
   `key_facts`, `image_only`, `jsonld`, `identity`, `alt`, `faq`); the other
   groups are still valid, and the facts file is still written unless the
   failed group is `facts`.

3. Read `site_category` and `pages_examined`. The category decides which
   facts are required (`site_categories.md` section 1) and whether the FAQ
   check applies. `pages_examined` lists the usable pages. Pages excluded
   because of robots.txt, a bot-protection challenge, an HTTP error, a
   non-HTML response, or a JavaScript gate or client-rendered shell are
   listed in the facts file under `pages_excluded` with a reason; nothing on
   them is graded, and the crawl-render skill owns those findings.

4. Read `checks`. Every one of the 12 `fx.*` checks appears with a status.
   `pass` needs no action. `not_evaluated` carries a `reason`
   (`robots_disallow`, `challenge_page`, `no_rendered_content`, `non_html`,
   `no_html_pages`, `not_applicable_for_category`, `dependency_failed`,
   `context_error`) and means the audit could not see, not that the site is
   fine.

5. Read `findings` in order. Each has `severity`, `confidence`, `evidence`
   (one or two sentences), `evidence_items` (the verbatim proof with page and
   location), `why_it_matters`, and a `suggested_action` with `summary`,
   `detail`, `impact`, `effort`, `priority`. `fx.facts.key_fact_missing` is
   one finding for the whole site: its evidence names every missing fact, what
   partial hint was found instead, and where each present fact came from. Do
   not restate a finding without its evidence.

6. Open `work/extracted_facts.json` (path in `artifacts.extracted_facts`).
   It is the only permitted basis for any statement about what the site says:
   one entry per fact with `status`, verbatim `value`, `page`, and `source`.
   Never fill a gap from memory or from a fetch of your own. If a fact is
   `absent` there, the correct answer is "the site does not state it".
   `references/extracted_facts.md` defines every field.

7. Apply the interpretation rules in `references/checks.md` when explaining
   a finding, and the non-findings in `references/non_findings.md` before
   adding anything the script did not flag. Never add a finding the script
   did not produce; if you believe one is missing, report the gap as a
   limitation.

8. Hand the JSON to the orchestrator unchanged. It owns IDs, dedupe, and
   counts. When used standalone, present the findings grouped by severity
   with their evidence and actions, then the facts table (fact, status,
   value, page), then the non-pass checks with their reasons.

## Output

The probe output object defined in the shared conventions
(`../audit-orchestrator/references/report_schema.md`, section 1): a `checks`
list with every check's status, plus `findings` for failures only. Check ids,
default severities and pass conditions are the `fx.*` rows of
`../audit-orchestrator/references/check_ids.md`. Severity and confidence follow
`../audit-orchestrator/references/severity_confidence_rubric.md`; category
gating follows `../audit-orchestrator/references/site_categories.md`; all
network access follows `../audit-orchestrator/references/fetch_policy.md`.

Also writes `work/extracted_facts.json`, keyed by the fact ids in
`site_categories.md`, for the orchestrator's AI-answer simulation. Its path
is returned in `artifacts.extracted_facts`.

## References

- `references/checks.md`: what each of the 12 checks detects, the exact rule,
  the evidence it records, and why the severity and confidence are what they are.
- `references/extracted_facts.md`: the facts file, field by field: fact ids
  per category, statuses, detection order per fact, the pricing rule, and
  the source vocabulary.
- `references/non_findings.md`: conditions this skill deliberately does not
  flag, and the limits of regex extraction over a six-page sample.
