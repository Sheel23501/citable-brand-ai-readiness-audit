# Session handoff — brand-ai-readiness-audit

Written 2026-09-08 so a fresh session can continue with no prior context.
Read this, then `BUILD_PLAN.md`, then start the first unticked step.

---

## 1. What this is

Adobe University Hackathon 2026, **Round 3 final**. The user (Sheel) is a
finalist. The deliverable is an **Agent Skill Marketplace**: a zip of a
directory holding `marketplace.json`, a `README.md`, and several skill folders,
each a valid `agentskills.io` SKILL.md. Exactly one skill is the **entrypoint**.
Pointed at any website, the entrypoint audits it and emits one report of
findings plus prioritized suggested actions.

The audit covers **two halves**, both required by the handout:

- **Off-site discoverability** — why AI assistants do not find or cite the brand.
- **On-site engagement** — why visitors who arrive do not stay.

Judged on: detection accuracy (few false positives), suggested-action quality,
output design, skill-format and engineering hygiene, marketplace composition
(genuine separation of concerns, not padding), and generalization to unseen
sites. **Judges read the skill source**, not any one report a run produces.

Hard rules from the handout: recommend-only (never modifies a site), no
destructive or authenticated actions, respect robots.txt, portable and
self-contained manifest (no external service to resolve it), zip ≤ 50 MB, audit
runtime < 5 minutes for a typical site.

### Source documents (in the repo root, provided by the user)

- `6a8ffdf33590a_round3-handout-updated.pdf` — **the source of truth.** Its
  appendix concepts **A–F** are the Round-2 background concepts; the report
  floor mirrors its sample schema exactly.
- `Brand-AI-Readiness-Audit-Winning-Strategy.pdf` (Part 1) — the product idea.
- `Part2-Edge-Cases-Hardening-Research.pdf` — edge cases and hardening.
- `Part3-Competitive-Landscape-Positioning.pdf` — market and positioning.

Parts 1–3 are strategy, not gospel: where they disagree with the handout or
with the code, the handout and the code win. Several of their citations are
**unverified** and must be confirmed in Step 20 or removed.

---

## 2. Where things are

```
/Users/sheelgautam/adobe-hackathon/          <- git repo root
  BUILD_PLAN.md                              <- 24 steps, the plan of record
  CONTEXT.md                                 <- this file
  *.pdf, *.html                              <- the handout and strategy docs
  brand-ai-readiness-audit/                  <- the marketplace (this is what gets zipped)
    marketplace.json                          5 skills, 1 entrypoint
    README.md                                 placeholder until Step 21
    LICENSE                                   MIT
    skills/
      audit-orchestrator/     ENTRYPOINT      references/ (7 shared conventions), scripts/auditlib/ (shared code)
      crawl-render-audit/                     16 cr.* checks   — done
      fact-extractability-audit/              12 fx.* checks   — done
      entity-freshness-corroboration-audit/   12 ef.* checks   — done
      engagement-audit/                       16 en.* checks   — probe done, references pending (Step 13)
    tests/
      serve_fixtures.py                       one local HTTP server per fixture, 127.0.0.1:8100+
      run_tests.py                            the whole suite, staged
      fixtures/<name>/                        16 static mini-sites, each with _fixture.json
```

- Git remote: `https://github.com/Sheel23501/potential-winner.git`, branch `main`.
  `gh` is authenticated as Sheel23501. Commits so far: `e25fdfd` initial,
  `4214fa1` Step 11, `aff6ca2` Step 12. Working tree clean, everything pushed.
- Skill validator: `~/.local/bin/agentskills validate <skill-dir>` (not on PATH).
- **macOS has no `timeout` command.** Run the suite plainly; it takes a few minutes.

---

## 3. Current state

| Phase | Steps | State |
|---|---|---|
| 0 Foundations | 1–3 | done: skeleton, 7 shared conventions, fixtures |
| 1 Fetch layer | 4–5 | done: fetch helper + robots, sampler + categorizer |
| 2 Probes | 6–13 | 6–12 done; **Step 13 (engagement references) is next** |
| 3 Orchestrator | 14–17 | not started: compose, validate, run_audit, entrypoint SKILL.md |
| 4 Hardening | 18–20 | not started: test stages, live pass, source verification |
| 5 Packaging | 21–24 | not started: README, demo, sweep, dry-run judging |

Suite: **1420 checks, 0 failures, GREEN.** All five skills pass the validator.

Code size: ~7,300 lines. Largest pieces: `engagement_probe.py` 1044,
`entity_probe.py` 820, `extract.py` 702, `facts_probe.py` 624, `fetch.py` 528,
`htmldoc.py` 522, `run_tests.py` 928.

Registry: 58 checks — 16 `cr.*`, 12 `fx.*`, 12 `ef.*`, 16 `en.*`, 2 `or.*`.

Reference files written so far:

- `audit-orchestrator/references/`: `report_schema.md`, `severity_confidence_rubric.md`,
  `check_ids.md`, `coverage_map.md`, `site_categories.md`, `bot_tiers.md`, `fetch_policy.md`
- `crawl-render-audit/references/`: `checks.md`, `non_findings.md`
- `fact-extractability-audit/references/`: `checks.md`, `extracted_facts.md`, `non_findings.md`
- `entity-freshness-corroboration-audit/references/`: `checks.md`, `non_findings.md`, `entity_file.md`, `offsite_spotcheck.md`
- `engagement-audit/references/`: **empty — this is Step 13.**

---

## 4. Architecture you must not re-invent

### Shared conventions own every rule

`skills/audit-orchestrator/references/` is the single source of truth. Nothing
in a probe or a SKILL.md may invent a rule that belongs in one of these:

| File | Governs |
|---|---|
| `report_schema.md` | Probe output, Finding, Evidence, final report floor + superset, ordering, run layout, Markdown rendering |
| `severity_confidence_rubric.md` | Severity, confidence, effort, the 5 adjustment rules in order, quick-win rule |
| `check_ids.md` | `check_id` naming + the registry of all 58 checks with defaults |
| `coverage_map.md` | Handout A–F ↔ our 7 stages, the 12-row dedupe table, derived tags, non-coverage |
| `site_categories.md` | 9 categories, inference scoring, page roles, key facts, engagement caps, severity overrides, the 5 simulation questions |
| `bot_tiers.md` | AI bot tokens by tier (live_answer / index / training_only) |
| `fetch_policy.md` | GET-only rules, identity, limits, robots semantics, challenge fingerprints |

Word lists that code must match exactly live in code, and the markdown says so:
`auditlib/sampler.py` (`ROLE_KEYWORDS`, `ROLE_SLUGS`, `CATEGORY_SIGNALS`) and
`auditlib/categories.py` (`CTA_VOCAB`, `CATEGORY_NOUNS`, `OFFER_VERBS`,
`TRUST_SIGNALS`, caps, severity overrides).

### The seven stages (our grouping; A–F are the handout's, never reused)

`access` → `render` → `extract` → `entity` → `freshness` → `corroboration` → `engagement`

Dedupe keeps the finding closest to the root cause, in that order.

### Shared code (`skills/audit-orchestrator/scripts/auditlib/`)

- `fetch.py` — `Fetcher`. GET only, never raises, obeys robots.txt for our own
  token, 40-request budget, 2 MiB cap, one 429 retry, 0.5 s politeness delay,
  challenge fingerprinting. `EXTERNAL_HOSTS` allows only Wikipedia/Wikidata.
- `robots.py` — RFC 9309 parser, bot-tier grading.
- `htmldoc.py` — `Document`: the served-HTML model. Extended in Step 12 with
  `body_frac(mpos)` (position within body markup), `Link.mpos` / `Link.in_list`,
  overlay candidates with text/words/hidden/position, `stylesheets`,
  `script_tags`, `article_count`, `blockquotes`.
- `sampler.py` — home + up to 5 role pages (about, contact, pricing, product,
  blog) via nav then sitemap; category inference by scoring.
- `context.py` — `AuditContext.from_url()` / `.from_workdir()`, `Page` objects.
- `findings.py` — `Registry` (parses `check_ids.md`), `ProbeOutput` with
  `.check/.fail/.inconclusive/.not_evaluated/.policy_note/.fill_unreported`,
  `adjust_severity`, `validate_probe_output`.
- `render.py` — the shared thin-page rule: `render_state(doc)` → ok/gate/shell.
- `cli.py` — `probe_main`: the common `--url` / `--workdir` / `--out` /
  `--offline` / `--category` CLI that never emits a traceback.
- `extract.py` — fact detectors, JSON-LD helpers, `GENERIC_TITLES`,
  `AUTHORITY_HOSTS`, `PROFILE_HOSTS`, address/phone/date patterns.
- `categories.py` — the category tables and the engagement vocabularies.

### Every probe follows the same shape

`run(ctx, args=None)` → `ProbeOutput`. Reads a workdir (or samples from a URL),
classifies pages into usable / excluded with a reason, runs guarded check
groups (one `try/except` each so one failure cannot take down the run), calls
`fill_unreported(prefix)` so **every registered check appears with a status**,
and writes a side file under `work/`. Never raises.

---

## 5. Invariants that make this submission good — do not break them

1. **Never crash on an unseen site.** Every script's `main()` is guarded and
   always emits valid JSON. Every probe guards each check group. This is worth
   more than any extra check.
2. **Every registered check always appears in `checks`**, including passes.
   That is what makes a positive report on a clean site possible.
3. **`pass` never produces a finding.** `inconclusive` and `not_evaluated` are
   always `severity: info` and carry a machine-readable `reason`.
4. **Never overclaim.** Confidence tiers are real: deterministic = high, two
   independent signals = medium, one heuristic or a proxy = low. A `low`
   confidence caps severity at medium.
5. **Explicit non-findings.** Each skill's `non_findings.md` lists what it sees
   and deliberately does not flag, and why. This is a deliverable, not hedging.
6. **The clean-site fixture must produce zero findings** from every probe. It is
   the false-positive guard.
7. **Category gating.** A check that does not apply to a category is
   `not_evaluated` with reason `not_applicable_for_category`, never a finding.
8. **Sub-skills never assign final IDs.** The orchestrator owns ids, dedupe and
   counts.
9. **The AI-answer simulation may read only `work/extracted_facts.json`.**
   Never the agent's own knowledge, never a fetch of its own.
10. **Stdlib only.** No pip installs anywhere, ever. It is both a rule and the
    positioning ("runs on any URL with nothing installed").
11. **No unverified citation** may appear in any file until Step 20 confirms it.

---

## 6. What happened in this session

### Step 11 — entity-freshness-corroboration SKILL.md + references (commit 4214fa1)

Wrote the SKILL.md (9-step procedure) and four reference files: `checks.md`
(all 12 checks plus the entity lookup's 3 modes and 7 outcomes), `non_findings.md`
(25 non-findings), `entity_file.md` (both side files field by field),
`offsite_spotcheck.md` (the agent step: at most 5 searches, 10 verbatim
mentions, and the exact shape of `work/offsite_mentions.json`).

Two code changes made so the docs were truthful, not describing a discrepancy:

- `check_nap` now **skips the name component when the brand name was only
  guessed from the host label**. The registry always said this; the code graded
  it anyway, which would have produced guess-based findings on live sites.
  Pinned by three new tests.
- The `ef.corroboration.press_page_missing` registry row now states the actual
  link-text, path-segment and feed rules the code applies.

The off-site cap is **five searches, not three**. The plan text said three; the
probe already generates up to five suggested queries and its own finding text
says five. Matched the code rather than introduce a third number.

Also extended the test runner's hygiene stage to cross-check `references/*.md`
against each SKILL.md in both directions (no unnamed files, no dangling paths).

### Step 12 — engagement probe + fixtures (commit aff6ca2)

Built `engagement_probe.py` with all 16 `en.*` checks, three new fixtures, and
extended the document model.

**Document model additions** (`htmldoc.py`): markup positions via
`body_frac(mpos)`, `Link.in_list`, overlay candidates with word counts and
hidden/position flags, `stylesheets`, `script_tags`, `article_count`,
`blockquotes`. These exist because the engagement checks reason about *where in
the page* something is ("first 40% of the body markup", "before the `<h1>`").

**Fixtures added**: `weak-engagement` (soft-404 catch-all, dead link, fixed
newsletter overlay, vague two-word hero, no nav/CTA/viewport/lang/trust),
`weak-ecommerce` (one-product shop: no breadcrumbs, no search, product page
without related links, bare 404, 41 script tags), `blocked-links` (three plain
403 footer links must become a cluster note, never counted broken). The fixture
server gained a `*` catch-all route so a deliberate soft-404 site can be served,
and `serve_expectations` so a fixture can declare it deliberately answers 200
for unknown paths or has a 404 page with no home link.

**Three rules tightened after a live check on python.org**, all recorded in the
registry:

- **Listing pages are not graded for related links.** Two or more `<article>`
  elements, or six or more in-list content links, means the page *is* the
  onward navigation.
- **An image-only `<h1>` counts as having no text.**
- **Onward links may be on a sibling subdomain** (same registrable domain).

Also extended `OFFER_VERBS` with common phrasing ("lets you", "allows",
"works with"), and added a hygiene test asserting every `en.*` id is exercised
as a failure by some fixture.

**Live smoke**: example.com (2 s) and python.org (11 s, 15 link requests), both
with no error.

### Known issue carried forward

**python.org ties `publisher_media` / `nonprofit_institution` at 4-4** in
category scoring and resolves to `publisher_media` by table order. Step 19 must
resolve this with a **documented tiebreak rule, not a special case**.

---

## 7. Working rules (the user's, and they matter)

- **One BUILD_PLAN.md step at a time.** Do only that step. Verify its
  "Done when" clause. Tick the checkbox with a dated note saying what was
  actually built. Then stop and report.
- **The suite must be green before a step is ticked**:
  `cd brand-ai-readiness-audit && python3 tests/run_tests.py`
- **Every probe fail path needs a fixture.** A hidden crash in an unexercised
  path only surfaced on a live site once already.
- **Commit after every step** with the step number in the message, then push.
- Prefer fixing a rule over special-casing a site.
- If the code and a reference disagree, fix whichever is wrong and say so; do
  not paper over it.

---

## 8. Next step — Step 13 (engagement SKILL.md + references)

Same shape as Steps 9 and 11. Read `engagement_probe.py` in full first so the
docs describe what the code actually does.

Deliverables:

- `skills/engagement-audit/SKILL.md` — replace the placeholder Procedure with a
  numbered one (run probe, read `error`, read `site_category`/`pages_examined`,
  read `checks` with the reason vocabulary, read `findings`, open
  `work/engagement.json`, apply the references, hand JSON to the orchestrator
  unchanged). Note the `--no-network` / `--offline` behaviour and that the probe
  spends at most 15 link requests plus one 404 probe.
- `references/checks.md` — all 16 `en.*` checks: rule, evidence, why the
  severity and confidence are what they are. Include the category caps table and
  the CTA / trust-signal vocabularies by category.
- `references/non_findings.md` — a one-page site is not disoriented; icon-only
  or non-English CTAs are a stated limit; page weight is a proxy, not a timing
  test; lazy-loaded embeds; a 403 cluster is not broken links; a listing page
  needs no related links; a search form never counts as a call to action.
- Possibly `references/engagement_file.md` documenting `work/engagement.json`
  (mirroring `entity_file.md`), since the probe writes it and the hygiene test
  will want SKILL.md to name every reference file.

"Done when": the validator passes on the skill, the hygiene stage is green
(it cross-checks references against SKILL.md in both directions and requires
every `en.*` id to appear in some reference file), and the full suite is green.

After Step 13 the remaining large piece is Phase 3 (Steps 14–17): the compose,
validate and run-audit scripts plus the entrypoint SKILL.md.
