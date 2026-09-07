# Adobe University Hackathon 2026 — Round 3 Build Plan

Marketplace: brand-ai-readiness-audit
Rule: one step at a time, verify "Done when" before moving on. No coding until told to start.

## Phase 0: Foundations

- [x] **Step 1. Project skeleton and manifest.** (done 2026-09-07) Marketplace root, marketplace.json with 5 skills and 1 entrypoint, 5 minimal SKILL.md files with valid frontmatter, empty scripts/ and references/ folders, MIT license, placeholder README.
  Done when: skills-ref validator passes on all five skills.

- [x] **Step 2. Shared conventions document.** (done 2026-09-07; 7 files in skills/audit-orchestrator/references/, fetch_policy.md added) Reference files: probe finding schema, severity + confidence rubric, bot tier list (live-answer / index / training-only), site category definitions, mechanism coverage map A–F, check_id naming rule.
  Done when: every later step points to one of these instead of inventing rules.

- [x] **Step 3. Test fixtures.** (done 2026-09-07; 9 fixtures in tests/fixtures/, blanket-disallow added; tests/serve_fixtures.py + tests/run_tests.py, 179 checks green) Static HTML: clean site, CSR shell, JS gate, bot-blocking robots, malformed JSON-LD, image-only pricing, non-HTML seed, minimal one-page portfolio. Local server script + test runner stub.
  Done when: fixtures serve locally.

## Phase 1: Fetch layer

- [x] **Step 4. Shared fetch helper.** (done 2026-09-07; skills/audit-orchestrator/scripts/auditlib/{fetch,robots}.py + fetch_url.py CLI; challenge-page fixture added; 280 tests green incl. example.com + python.org live) GET only, timeouts, redirect cap, byte cap, one retry on 429, content-type check, challenge-page fingerprinting, robots.txt parsing with bot tiers. Never raises.
  Done when: runs on every fixture and two live sites with no traceback.

- [x] **Step 5. Page sampler and site categorizer.** (done 2026-09-07; auditlib/htmldoc.py + auditlib/sampler.py + sample_site.py CLI; all 10 fixtures categorised correctly; 515 tests green; note for Step 19: python.org ties publisher_media/nonprofit at 4-4) Up to 6 pages by role (home, about, contact, pricing, product/service, blog/news) via nav keywords then sitemap. Infers category. Saves snapshots.
  Done when: correct sample manifest and category on every fixture.

## Phase 2: Probes (one at a time)

- [x] **Step 6. Crawl-render probe.** (done 2026-09-07; skills/crawl-render-audit/scripts/crawl_probe.py + auditlib/{findings,categories,context}.py; all 10 fixtures match their contracts; 605 tests green) robots by bot tier, blanket disallow, JS gate (incl. onload-form-submit gate; plain 3xx is never a gate), CSR shell (two-signal rule), sitemap, noindex, canonical, challenge inconclusive note.
  Done when: each fixture triggers exactly its expected findings; clean fixture triggers none.
- [x] **Step 7. Crawl-render SKILL.md + references.** (done 2026-09-07; SKILL.md with 6-step procedure; references/checks.md covers all 16 cr.* checks with rule/evidence/rationale; references/non_findings.md lists 12 explicit non-findings; hygiene test enforces references cover every registered id)

- [x] **Step 8. Fact-extractability probe.** (done 2026-09-07; skills/fact-extractability-audit/scripts/facts_probe.py + auditlib/{extract,render,cli}.py; all 12 fx.* checks; 11 fixtures match their contracts incl. new bare-metadata which covers the 7 previously unexercised fail paths; work/extracted_facts.json readable on fixtures and live (python.org, plausible.io); 780 tests green) Category-gated key facts (sales-led 'request a demo' satisfies pricing_or_trial; optional audience + differentiator facts), image-only fact proxies, JSON-LD parse + required props, malformed JSON-LD as own finding, title/H1/meta, Open Graph, alt text, FAQ-shaped content. Writes extracted-facts file.
  Done when: fixtures pass and facts file is readable.
- [x] **Step 9. Fact-extractability SKILL.md + references.** (done 2026-09-07; SKILL.md with 8-step procedure incl. the facts-file-only rule for the simulation; references/checks.md covers all 12 fx.* checks with rule/evidence/rationale and the REQUIRED_PROPS table; references/extracted_facts.md defines the facts file field by field with detection order per fact and the source vocabulary; references/non_findings.md lists 23 explicit non-findings and the limits of regex extraction; fx.jsonld.missing now notes Microdata/RDFa at medium confidence; 785 tests green)

- [x] **Step 10. Entity-freshness-corroboration probe.** (done 2026-09-07; skills/entity-freshness-corroboration-audit/scripts/entity_probe.py, all 12 ef.* checks; entity lookup is one robots-allowed Wikipedia article or Wikidata EntityData fetch (Wikidata's search API is robots-disallowed for generic agents and is never called), verified live on plausible.io, python.org, adobe.com; off-site spot-check reads work/offsite_mentions.json written by the agent step, else tool_unavailable note; two new fixtures weak-entity + undated-entity cover the 8 fail paths; --offline degrades to 12 not_evaluated with reasons and no error; 1050 tests green) sameAs, Wikidata lookup with timeout + fallback, NAP plain text, visible dates vs dateModified, press/newsroom page. Search spot-check = agent step with not-evaluated fallback.
  Done when: degrades cleanly with network disabled.
- [ ] **Step 11. Entity-freshness-corroboration SKILL.md + references.**

- [ ] **Step 12. Engagement probe.** Hero clarity, CTA (structural signals), nav landmark (category cap), link health with 403-cluster reclassification, viewport meta, page weight proxy, trust signals, landing continuity, breadcrumbs, related links, site search, interstitials, lang attribute, 404 behaviour.
  Done when: check count at parity with discoverability; fixtures pass.
- [ ] **Step 13. Engagement SKILL.md + references.**

## Phase 3: Orchestrator

- [ ] **Step 14. Compose script.** Merge, IDs, dedupe via overlap table, counts, sort, quick wins, derived tags (handout_concepts, pipeline_stage, opportunity_type, impact/priority), limitations boilerplate (point-in-time, sampling, rate-limited, challenged), proactive recommendations by category + gaps, Markdown rendered from same JSON.
  Done when: clean fixture yields positive report; broken fixtures yield correct counts.
- [ ] **Step 15. Validate script.** Required floor + superset fields.
  Done when: rejects broken reports, accepts good ones.
- [ ] **Step 16. Run-audit script.** Fetch once, sample, 4 probes on snapshots, compose, validate, write JSON + MD, wall-clock budget, top-level guard.
  Done when: completes on fixtures and 3 live sites under 5 minutes.
- [ ] **Step 17. Orchestrator SKILL.md.** Run script, AI-answer simulation from facts file only (5 questions per category: what, category-specific, how to proceed, fit, comparison; attribution_note), narrative summary, re-validate, emit. References: schema, rubric, simulation rules, coverage map.
  Done when: fresh agent session following only SKILL.md produces a valid report.

## Phase 4: Hardening and proof

- [ ] **Step 18. Test runner.** All probes on all fixtures, run-audit on each, validate all, no tracebacks.
  Done when: green.
- [ ] **Step 19. Live generalization pass.** 8–10 unseen sites across categories incl. non-English, bot-protected, unreachable. Fix rules, not sites.
  Done when: every finding is defensible.
- [ ] **Step 20. Source verification.** Open every citation and Adobe fact. Keep only confirmed, with URLs. Must verify before use: bot_tiers.md rows (vendor docs); arXiv 2603.09296 (citation-failure taxonomy); arXiv 2605.14021 (AI Overviews study); Ahrefs 2026 schema/citation study; Princeton/IIT Delhi GEO study KDD 2024; NNG 57% above-the-fold; Adobe Analytics AI-referred traffic +1,324% retail / +2,215% travel; Gary Illyes on llms.txt (Jul 2025); bot-block prevalence stats (GPTBot 5.5% / 25% top-1000 / 41% B2B); RFC 9309; Google JS SEO basics. Anything unconfirmed is removed, not softened.
  Done when: sources file has no unverified entries.

## Phase 5: Packaging

- [ ] **Step 21. README.** What it does (agentic vs referral traffic framing; inside-out vs outside-in positioning statement), skill table, composition, how to run, schema, limitations + coverage map, sources (verified only), prior-art section (free checkers, monitors, enterprise GEO, claude-seo) and how this differs, field-research note.
  Done when: a stranger can run it from the README alone.
- [ ] **Step 22. Demo report.** Neutral site, JSON + Markdown in examples/.
- [ ] **Step 23. Final compliance sweep.** Validator, manifest, zip size, no third-party imports, no non-GET requests, robots respected, runtime confirmed. Zip the root.
- [ ] **Step 24. Dry-run judging.** Read the zip against each rubric line. Fix weak spots. Submit.
