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
      engagement-audit/                       16 en.* checks   — done
    tests/
      serve_fixtures.py                       one local HTTP server per fixture, 127.0.0.1:8100+
      run_tests.py                            the whole suite, staged
      fixtures/<name>/                        16 static mini-sites, each with _fixture.json
```

- Git remote: `https://github.com/Sheel23501/potential-winner.git`, branch `main`.
  `gh` is authenticated as Sheel23501. Commits so far: `e25fdfd` initial,
  `4214fa1` Step 11, `aff6ca2` Step 12, `6bb7ca1` CONTEXT.md, then Step 13. Working tree clean, everything pushed.
- Skill validator: `~/.local/bin/agentskills validate <skill-dir>` (not on PATH).
- **macOS has no `timeout` command.** Run the suite plainly; it takes a few minutes.

---

## 3. Current state

| Phase | Steps | State |
|---|---|---|
| 0 Foundations | 1–3 | done: skeleton, 7 shared conventions, fixtures |
| 1 Fetch layer | 4–5 | done: fetch helper + robots, sampler + categorizer |
| 2 Probes | 6–13 | done |
| 3 Orchestrator | 14–17 | done: compose.py, validate.py, run_audit.py, finalize.py, the entrypoint SKILL.md and simulation_rules.md |
| 4 Hardening | 18–20 | **Step 18 (test runner) is next**, then the live pass, then source verification |
| 5 Packaging | 21–24 | not started: README, demo, sweep, dry-run judging |

Suite: **2513 checks, 0 failures, GREEN.** All five skills pass the validator.

Code size: ~8,100 lines. Largest pieces: `engagement_probe.py` 1044, `compose.py` 800, `validate.py` 335, `run_audit.py` 210, `finalize.py` 130,
`entity_probe.py` 820, `extract.py` 702, `facts_probe.py` 624, `fetch.py` 528,
`htmldoc.py` 522, `run_tests.py` 1520.

Registry: 58 checks — 16 `cr.*`, 12 `fx.*`, 12 `ef.*`, 16 `en.*`, 2 `or.*`.

Reference files written so far:

- `audit-orchestrator/references/`: `report_schema.md`, `severity_confidence_rubric.md`,
  `check_ids.md`, `coverage_map.md`, `site_categories.md`, `simulation_rules.md`, `bot_tiers.md`, `fetch_policy.md`
- `crawl-render-audit/references/`: `checks.md`, `non_findings.md`
- `fact-extractability-audit/references/`: `checks.md`, `extracted_facts.md`, `non_findings.md`
- `entity-freshness-corroboration-audit/references/`: `checks.md`, `non_findings.md`, `entity_file.md`, `offsite_spotcheck.md`
- `engagement-audit/references/`: `checks.md`, `non_findings.md`, `engagement_file.md`

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
- `categories.py` also owns `SIMULATION_QUESTIONS` and `AUDIENCE_PHRASE` (site_categories.md section 6).
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

## 8. Steps 13 and 14 — done

**Step 13** wrote `skills/engagement-audit/SKILL.md` (8-step procedure, the two-tier page
rule, the full reason vocabulary) and `references/checks.md`, `non_findings.md`,
`engagement_file.md`. No code changed.

**Step 14** built `skills/audit-orchestrator/scripts/compose.py` (780 lines), the first
piece of Phase 3. `compose(workdir)` returns the whole report dict and
`render_markdown(report)` renders it; `--render-only` re-renders from an existing
report.json, which is what the orchestrator agent (Step 17) will call after writing the
narrative and the simulation answers.

Notable decisions, each recorded in the plan's done-note:

- **Positive titles.** `passed_checks` needs each check's pass condition said as a fact.
  Those 58 titles live in `compose.py` as `POSITIVE_TITLES`, following the existing rule
  that word lists code must match exactly live in code; `check_ids.md` now says so and the
  suite asserts the two sets are equal.
- **Simulation tables.** `SIMULATION_QUESTIONS` and `AUDIENCE_PHRASE` were added to
  `categories.py` mirroring `site_categories.md` section 6; the suite checks every question's
  fact ids appear both in that section and in the category's key facts. Q4's `{audience}`
  placeholder is a per-category phrase ("a team like mine"), so the question reads the way a
  person asks it while the answer still comes from the audience fact.
- **Severity inheritance has a limit.** A folded finding can raise its primary, but only up to
  that check's registered maximum, and never when the primary's own status is `inconclusive`
  or `not_evaluated` (the rubric's hard rule that those are always `info` outranks it).
  `coverage_map.md` section 4 now states this, and the same rules paragraph now says rows 8
  and 9 fold a finding only when every entry it reports is covered by the primary.
- **Limitations are read from the reference.** The section-5 non-coverage lines are parsed out
  of `coverage_map.md` at run time rather than copied, so the two cannot drift.
- **No dedupe row fires on any fixture**, because the probes already gate themselves (a
  challenged page yields no downstream findings at all). That is the design working, but it
  means the table needed its own proof: the compose stage has 12 synthetic dedupe cases, one
  per row, plus the negative cases (a different JSON-LD block, two h1s rather than none, a
  real 404 inside a blocked cluster, a hero that fails on its lead text).
- `findings.py` now snaps titles longer than 90 characters to a word boundary instead of
  cutting mid-word.

Clean-site composes to a report with **zero defects**, 54 passing checks, six proactive
recommendations and every simulation question answerable except the comparison one, which is
informational by rule.

## 9. Step 15 — done (validate.py)

`skills/audit-orchestrator/scripts/validate.py`. `validate_report(report, facts=None,
final=False)` returns `(problems, warnings)`; the CLI takes `--workdir` or `--report`,
finds the facts file from the report's own `ai_answer_simulation.facts_file`, and exits
0/1. Problems are prefixed `floor:` (the handout's required shape, never relaxed) or
`superset:` (our conventions), so the two tiers stay distinguishable in output.

The one rule that goes beyond the plan text: an answer must carry a **verbatim
20-character run** of every fact it lists in `facts_used` (`quotes_fact`). That is how
"the simulation may use only the facts file" becomes checkable rather than a promise.
`--final` additionally requires a narrative and an answer for every answerable question;
sentence count (3–6) and an empty `attribution_note` are warnings, not failures, so the
agent is never blocked by a counting heuristic.

Two small fixes made while proving it: compose now writes `site: "unknown"` (never an empty
string) when a workdir has no sample, so even the run-error fallback passes the floor; and
`site_url` may be empty only in that case.

## 10. Step 16 — done (run_audit.py)

`run_audit.py <url> [--workdir DIR] [--category C] [--offline] [--no-network]
[--time-budget S]` is the one command: sample once, run the four probes in stage order,
compose, validate non-final, write `report.json` and `report.md`, print the paths.
`--workdir` with no URL re-grades an existing sample without fetching anything.

**Each probe runs as its own subprocess.** That is the only way a 60-second per-probe
limit is actually enforceable, and it means a probe that crashes, hangs, exits non-zero
or merely prints a traceback cannot take the run down: it is replaced by a stub output
carrying the reason, and `or.run.probe_error` names it in the report. The 300-second
wall clock is split — 55 % to the sampler through the Fetcher's existing `time_budget`
(`AuditContext.from_url` gained a `time_budget` argument), then `min(60, remaining - 5)`
per probe, with anything under 8 seconds left skipped rather than started and killed.

**Two real bugs surfaced by running the whole thing as a command**, both fixed:

- `--offline` was ignored in **workdir mode**. The engagement and entity probes decided
  whether to use the network by looking at `ctx.fetcher.offline`, but in workdir mode
  `ctx.fetcher` is None, so they built their own online fetcher and went to the network.
  Replaying a saved workdir with `--offline` therefore counted every unreachable link as a
  broken one: a false positive of exactly the kind the audit is judged on. The flag, not the
  context, is now the authority in both probes.
- `--category` was passed to every probe but the report still printed the *inferred*
  category, so a report could be graded as one category and labelled another. `compose()`
  now takes `category_override` and states it with confidence `high` and the signal
  `override:command_line`.

Live timings after the fixes: example.com 4.3 s, python.org 13.3 s, gutenberg.org 21.4 s,
three different inferred categories, no traceback anywhere.

### Carried to Step 19 (live generalization)

- **python.org ties `publisher_media` / `nonprofit_institution` 4-4** and resolves by table
  order. Needs a documented tiebreak rule, not a special case.
- **djangoproject.com infers `unknown` with low confidence.** A large, obvious software
  project falling through to `unknown` is a scoring gap worth a rule.
- The engagement probe is the slow one on live sites (7-14 s of the total), because of the
  15-link sample. That is within budget but it is where any future speed work belongs.

## 11. Step 17 — done (orchestrator SKILL.md, simulation_rules.md, finalize.py)

Phase 3 is complete. `skills/audit-orchestrator/SKILL.md` is now the procedure a fresh
agent follows, in eight numbered steps: run `run_audit.py`; read `report.json`; the
off-site spot-check if a search tool exists (and only then); the simulated answers; the
attribution note; the narrative; `finalize.py`; emit both files. `allowed-tools` gained
`WebSearch` for the spot-check.

**`references/simulation_rules.md`** is the rulebook for the only three pieces of text
the agent writes. Its two central rules: an answer's substance may be only the verbatim
`value` strings of `present` facts, in quotation marks, framed by words that carry no
facts (the validator demands a 20-character verbatim run of every fact named); and
nothing outside the facts file goes in — not the model's knowledge, not the page
snapshots, not anything fetched, not inference from absence, not correction of an odd
value. Q4 is answered "for whom", never yes/no; Q5 is informational. The attribution note
is the one place mention-without-citation is recorded. The narrative is 3–6 sentences,
grouped invisible → stale → bouncing, every sentence traceable to an id, a passed check,
a coverage line or the simulation, and it must open by saying so if the run was incomplete.

**Ordering constraint that the SKILL.md enforces:** the spot-check re-runs the entity
probe and compose, and compose rewrites `report.json`. So the spot-check is step 3 and
the agent's text is written last, by `finalize.py`, which never recomposes.

**One addition beyond the plan text:** `scripts/finalize.py`. The agent writes a small
`answers.json` (answers keyed by question id, `attribution_note`, `narrative_summary`)
and the script merges it, re-renders `report.md`, and runs `validate.py --final`. The
alternative was an agent hand-editing a 2,000-line JSON with `Write`, which is where a
report would get corrupted. It refuses an answer on an unanswerable question and reports
the validator's problems so the agent can fix the file and re-run.

Also: compose now fills `see_finding` on every unanswerable category question (the
`fx.facts.key_fact_missing` id, else the `or.simulation.question_unanswerable` id) and
the validator checks it names a real finding.

**Verification.** Walked the procedure by hand on python.org: answers written from the
facts file alone, `finalize.py` exit 0, `validate.py --final` zero problems, the narrative
and quotations render. The orchestrator is now held to the same reference/script hygiene
tests as the four probes. The literal "fresh agent session given only the SKILL.md" test
belongs to Step 24's dry run.

## 12. Next step — Step 18 (test runner)

Read the plan's Step 18 text first. Most of what it lists already exists: stages
`probe_en`, `compose`, `validate` and `run_audit` were added as each step landed, and the
`run_audit` stage already asserts no traceback in the CLI's output. What is left is the
plan's last clause: **a traceback grep over every script's stdout/stderr**, meaning every
script in `skills/*/scripts/` invoked the way its SKILL.md says (including the wrong-usage
paths: no arguments, a bad flag, a missing workdir), never emitting a Python traceback.
Add that as a stage, keep everything green, and update the runner's docstring stage list.
Do not re-implement stages that exist; extend them where the plan text asks for something
they do not yet check.
