---
name: engagement-audit
description: Checks whether a visitor who arrives at a website, often mid-journey from an AI answer, can orient, understand the offer, and continue. Detects a missing or unclear first-viewport value proposition, no identifiable primary call to action, missing navigation landmarks, broken sampled links, missing mobile viewport, heavy page weight (proxy), missing trust signals, weak landing-page continuity (H1 versus title and description), missing breadcrumbs, related links, or site search, blocking interstitials, missing lang attribute, and soft 404 behaviour. Use when diagnosing why visitors bounce, or as the on-site engagement stage of a brand AI-readiness audit.
license: MIT
compatibility: Requires Python 3.8+ (standard library only). Operates on fetched HTML; sampled link-health checks make a bounded number of GET requests.
metadata:
  marketplace: brand-ai-readiness-audit
  concern: on-site-engagement
allowed-tools: Bash(python3:*) Read
---

# Engagement Audit

## When to use

Use when you need to know whether a human visitor who has already arrived
will stay, understand, and find their way.

## Inputs

- A URL, or a folder of page snapshots plus the inferred site category.

## Procedure

To be written in Step 13.

## Output

The probe output object defined in the shared conventions
(`../audit-orchestrator/references/report_schema.md`, section 1): a `checks`
list with every check's status, plus `findings` for failures only. Check ids,
default severities and pass conditions are the `en.*` rows of
`../audit-orchestrator/references/check_ids.md`. Severity and confidence follow
`../audit-orchestrator/references/severity_confidence_rubric.md`; category
gating follows `../audit-orchestrator/references/site_categories.md`; all
network access follows `../audit-orchestrator/references/fetch_policy.md`.
