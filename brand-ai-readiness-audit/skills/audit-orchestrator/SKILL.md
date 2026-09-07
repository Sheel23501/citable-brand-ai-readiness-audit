---
name: audit-orchestrator
description: Entrypoint for the brand AI-readiness audit. Given a website URL or domain, runs the crawl-render, fact-extractability, entity-freshness-corroboration, and engagement audits, composes their findings into one prioritized report (evidence, severity, confidence, suggested actions, proactive recommendations), and emits it as JSON plus Markdown. Use when asked to audit a website for AI discoverability, AI citation readiness, or on-site engagement problems, or to diagnose why a brand is missing or misrepresented in AI assistants.
license: MIT
compatibility: Requires Python 3.8+ (standard library only) and outbound HTTPS access to the audited site. Read-only; performs GET requests only.
metadata:
  role: entrypoint
  marketplace: brand-ai-readiness-audit
allowed-tools: Bash(python3:*) Read Write
---

# Audit Orchestrator (entrypoint)

## When to use

Use this skill when a user asks to audit a website for AI discoverability
and/or on-site engagement, and wants a single actionable report.

## Inputs

- A URL or bare domain (for example `https://example.com` or `example.com`).

## Procedure

To be written in Step 17. The procedure will: run the audit script, perform
the AI-answer simulation strictly from extracted facts, write the narrative
summary, validate the report, and emit it.

## Output

A single audit report (`report.json` plus `report.md` rendered from it) as
defined in `references/report_schema.md` section 3: the required floor (`site`,
`audited_at`, counts-by-severity `summary`, `findings` with `id`, `title`,
`severity`, `evidence`, `suggested_action` with `summary` and `priority`, in the exact shapes of the handout sample) plus the superset fields (category,
sampled pages, quick wins, passed checks, coverage, proactive recommendations,
AI-answer simulation, narrative, limitations).

## Shared conventions

Every skill in this marketplace follows the files in `references/`. Later
build steps point here instead of inventing rules:

| File | Governs |
|---|---|
| `references/report_schema.md` | Probe output, Finding, Evidence, final report floor and superset, ordering, run layout, Markdown rendering |
| `references/severity_confidence_rubric.md` | Severity, confidence, effort, adjustment order, quick-win rule, wording |
| `references/check_ids.md` | check_id naming rule and the registry of every check with defaults |
| `references/coverage_map.md` | Map from the handout's Round-2 concepts A–F to our seven audit stages, check-to-stage map, dedupe table, explicit non-coverage |
| `references/site_categories.md` | Category ids, inference scoring, page roles, key facts, engagement caps, severity overrides, simulation questions |
| `references/bot_tiers.md` | AI bot tokens by tier and robots.txt grading |
| `references/fetch_policy.md` | GET-only rules, identity, limits, robots semantics, challenge fingerprints, FetchResult and sample manifest |
