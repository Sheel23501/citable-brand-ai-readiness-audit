---
name: entity-freshness-corroboration-audit
description: Checks whether a brand's facts are trustworthy and unambiguous to AI assistants. Detects missing entity-disambiguation anchors (Organization sameAs to Wikidata, Wikipedia, official profiles), missing plain-text identity facts (name, address, phone), absent or cosmetic freshness signals (visible last-updated dates versus dateModified), and a missing press or newsroom corroboration surface. Optionally performs a bounded off-site mention spot-check when a search tool is available. Use when diagnosing entity confusion, stale answers, or low trust in AI assistants, or as the trust stage of a brand AI-readiness audit.
license: MIT
compatibility: Requires Python 3.8+ (standard library only). Optional outbound HTTPS to the Wikidata public API; degrades gracefully without it. Off-site search step requires an agent web-search tool and is skipped with an explicit note if unavailable.
metadata:
  marketplace: brand-ai-readiness-audit
  concern: trust-identity-freshness
allowed-tools: Bash(python3:*) Read WebSearch
---

# Entity, Freshness and Corroboration Audit

## When to use

Use when you need to know whether an assistant can tell this brand apart from
others with the same name, and whether its facts look current and corroborated.

## Inputs

- A URL, or a folder of page snapshots plus the inferred site category.

## Procedure

To be written in Step 11.

## Output

The probe output object defined in the shared conventions
(`../audit-orchestrator/references/report_schema.md`, section 1): a `checks`
list with every check's status, plus `findings` for failures only. Check ids,
default severities and pass conditions are the `ef.*` rows of
`../audit-orchestrator/references/check_ids.md`. Severity and confidence follow
`../audit-orchestrator/references/severity_confidence_rubric.md`; category
gating follows `../audit-orchestrator/references/site_categories.md`; all
network access follows `../audit-orchestrator/references/fetch_policy.md`.

The off-site spot-check (`ef.corroboration.offsite_spotcheck`) is `info` and
never affects counts; without a search tool it is `not_evaluated`.
