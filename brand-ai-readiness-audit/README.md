# brand-ai-readiness-audit

An Agent Skill Marketplace that audits a website for the problems that hurt
its AI discoverability (being found and cited by AI assistants) and its
on-site engagement (keeping the visitor once they arrive), then emits a single
prioritized, evidence-backed report of findings and suggested actions.

Read-only. It recommends; it never modifies a live site.

## Status

Skeleton plus shared conventions. Scripts and full skill procedures are filled
in step by step. See `BUILD_PLAN.md` in the parent folder for the build order.

## Conventions

All cross-skill rules live in `skills/audit-orchestrator/references/` and are
the single source of truth for every script and SKILL.md:

| File | Governs |
|---|---|
| `report_schema.md` | Probe output, Finding, Evidence, final report (required floor + superset), ordering, Markdown rendering |
| `severity_confidence_rubric.md` | Severity, confidence, effort, adjustment rules, quick wins |
| `check_ids.md` | `check_id` naming rule and the registry of all 58 checks |
| `coverage_map.md` | Handout concepts A–F mapped to seven audit stages, dedupe table, what is not covered |
| `site_categories.md` | Site categories, inference scoring, page roles, key facts, engagement caps, simulation questions |
| `bot_tiers.md` | AI bot user-agent tokens by tier (live-answer / index / training-only) |
| `fetch_policy.md` | GET-only fetch rules, limits, robots.txt semantics, challenge fingerprinting, manifests |

## Layout

```
brand-ai-readiness-audit/
  marketplace.json                          manifest: five skills, one entrypoint
  LICENSE                                   MIT
  README.md
  examples/                                 demo report (added later)
  tests/
    serve_fixtures.py                       one local server per fixture (127.0.0.1:8100..)
    run_tests.py                            test runner; stages added step by step
    fixtures/<name>/                        static mini-sites with _fixture.json expectations
  skills/
    audit-orchestrator/                     ENTRYPOINT
      references/                           shared conventions (see below)
      scripts/auditlib/                     shared stdlib code: fetch.py (policy-enforcing GET), robots.py (RFC 9309 + bot tiers),
                                            htmldoc.py (served-HTML document model), sampler.py (page roles + category),
                                            findings.py (registry + rubric-applying finding builder), categories.py, context.py,
                                            render.py (shared thin-page / gate / shell rule), cli.py (probe_main: common probe CLI),
                                            extract.py (fact detectors, JSON-LD required-property specs)
      scripts/fetch_url.py                  CLI: fetch one URL under the policy, optionally grade robots.txt
      scripts/sample_site.py                CLI: sample home + 5 role pages, infer category, write snapshots/ and sample.json
    crawl-render-audit/
      scripts/crawl_probe.py                probe: robots by bot tier, access, JS gate, CSR shell, sitemap, noindex, canonical
    fact-extractability-audit/
      scripts/facts_probe.py                probe: category-gated key facts, image-only facts, JSON-LD (parse, required props,
                                            organisation node), title/H1/meta/Open Graph, alt text, FAQ; writes work/extracted_facts.json
    entity-freshness-corroboration-audit/
      scripts/entity_probe.py               probe: sameAs anchors, one robots-allowed Wikipedia/Wikidata lookup, plain-text NAP, name
                                            consistency, visible dates vs dateModified, copyright year, newsroom surface, off-site spot-check
                                            report; writes work/entity.json
    engagement-audit/
```

## Tests

```
python3 tests/run_tests.py          # fixtures serve + robots parser + fetch helper (offline-safe)
python3 tests/run_tests.py --live https://example.com/   # add live-site fetches
python3 tests/serve_fixtures.py     # keep the fixtures up for manual probing
```

Fixtures: `clean-site` (false-positive guard), `csr-shell`, `js-gate`,
`bot-blocking-robots`, `blanket-disallow`, `challenge-page`, `malformed-jsonld`,
`image-only-pricing`, `non-html-seed`, `one-page-portfolio`. Each carries the
check ids it is expected to trigger, taken from the registry.

## Validation

```
agentskills validate skills/<skill-name>
```
