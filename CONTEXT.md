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

- Git remote: `https://github.com/Sheel23501/potential-winner.git`, branch `main`. **Two people commit here**: Sheel's
  sessions and Deepak (deepak23188@iiitd.ac.in). Pull with `--ff-only` before every step; keep commits small.
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
| 4 Hardening | 18–20 | done (Step 20 by Deepak, re-verified 2026-09-09) |
| 5 Packaging | 21–24 | Steps 21–22 done by Deepak. **Step 23 (compliance sweep) is next**, then dry-run judging |

Suite: **3354 checks, 0 failures, GREEN.** It now takes over ten minutes; run it in the background
or with `--stage <name>` while iterating, and plainly once before ticking a step. All five skills pass the validator.

Code size: ~8,100 lines. Largest pieces: `engagement_probe.py` 1044, `compose.py` 800, `validate.py` 335, `run_audit.py` 210, `finalize.py` 130,
`entity_probe.py` 820, `extract.py` 702, `facts_probe.py` 624, `fetch.py` 528,
`htmldoc.py` 522, `run_tests.py` 1640.

Registry: 61 checks — 19 `cr.*` (three edge-access checks added by Deepak), 12 `fx.*`, 12 `ef.*`, 16 `en.*`, 2 `or.*`.

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
| `check_ids.md` | `check_id` naming + the registry of all 61 checks with defaults |
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

## 12. Step 18 — done (test runner)

The stages the plan lists had each landed with the step that built the thing they test,
so Step 18 added the last clause: a **`scripts` stage** that invokes all ten scripts the
way their SKILL.md says, as subprocesses, across an invocation matrix of about ninety rows:
no arguments, `--help`, an unknown flag, a missing workdir, a valid workdir, `--offline`,
an unknown `--category`, a fixture URL, a non-URL string, a refused connection, `--out`.
Every row asserts that no traceback reaches stdout or stderr, and rows with a documented
exit code assert it. Also: every script from a foreign working directory, every probe's
`--help` listing the shared flags, and a probe's stdout being exactly one JSON document.

It caught one real edge — `compose.py --render-only` into a directory that did not exist
could not write the Markdown (a clean exit 1, not a traceback) — now fixed. The runner's
docstring is the stage list in run order; `--stage <name>` runs one.

## 13. Step 19 — done (live generalization pass)

Thirteen sites, one per category plus the plan's edge cases (German, bot-protected,
unreachable, non-HTML seed, bare IP), then python.org and djangoproject.com re-checked.
Every run exit 0, no traceback, longest 41 s. Workdirs are kept under the scratchpad
`live-pass/` (`wd-*` first pass, `v3-*` after the fixes) as inputs for Step 22.

**The method was the plan's: read every finding and ask whether it would survive a
judge who knows the site.** Nine rule defects surfaced; none was fixed by naming a site.
The one worth remembering is `fx.facts.image_only`, which fired four times and was wrong
four times — a photo caption containing "location", a headline containing "plans", an
article image on a corporate blog. The principle that fixed it also fixed category
inference and role discovery: **a label is not a sentence.** A fact word inside prose is
not a signal; only short alt text, a filename token, or a short heading is. The same
principle removed python.org's `nav:world` (an eight-word headline) and heise's "pricing
page" (a news headline containing "plans").

Category inference got three more rules, all in `site_categories.md` section 2 and
`sampler.py`: newspaper section names score only as a cluster of two or more; nav links
to sibling subdomains are the site's own navigation; a generic `LocalBusiness` type scores
2 while a specific one scores 3. And the documented tiebreak: stronger evidence kind, then
breadth, then table order — that last resort recorded as `tie:<runner-up>` with confidence
`low`, because an unresolved tie *is* uncertainty. python.org now resolves to
`nonprofit_institution` by score with no tie; djangoproject.com to `saas_software`.

Entity: `© 2005-now` is the current year; the discover lookup tries the site's shorter
self-name once (Dishoom's long `og:site_name` had produced a false `not_found`; the short
name found the article, which is the 2016 film — a *true* collision, and the finding now
says "Wikipedia's 'Dishoom' is not this brand, and the site links no entity of its own");
an unclassified site's NAP requirement is any contact, not a postal address. Compose: when
no page was readable, the simulation check is `not_evaluated` with reason
`no_readable_pages` — an unread site is unknown, not silent. `category_label()` in
`categories.py` ended "a unknown site".

Two honest non-fixes: paulgraham.com stays `unknown` (image-only navigation with no alt
text gives nothing to score, and its 18 findings are true of the page), and Clearleft's
`wikidata_not_found` stays at low confidence as the registry says.

**Known quality item for Step 22:** the `how_to_participate` fact excerpt can be a window
of navigation chrome ("…Donate ≡ Menu Search…"); the detector should prefer the matching
link's text. It is a fact excerpt, not a finding, so it was out of Step 19's scope.

## 14. 2026-09-09 — Deepak's Steps 20–24 work, and the edge-block fix

Deepak pushed three commits (`947b2a2`, `b35db53`, `77144ae`): a new **edge-level access
check** (`cr.access.edge_block` and two info siblings — the sampler announces three
published crawler tokens at the home URL and compares with the baseline, catching a CDN
that 403s crawlers a clean robots.txt permits), `references/sources.md` with every bot-tier
row verified and three research papers, a rewritten README, the demo report in `examples/`,
`CONTRIBUTING.md`, and four false-positive fixes from a 38-site gauntlet (refused sites
reported as unreachable; URL patterns matching the hostname; `key_fact_missing` always
`high`; English-only CTA vocabulary). All three papers were re-fetched on 2026-09-09 and
every figure quoted is in their text.

**The edge check had one real defect**, found by building a site that disallows the three
tokens in robots.txt *and* 403s them at the edge — a site enforcing its own policy
correctly. It was reported as a **critical** `edge_block` on top of the robots findings,
with evidence saying "robots.txt is not the cause" (false), and an action telling the owner
to undo the policy. Also: the probe announced tokens the site had disallowed, and an
unexplained refusal of the auditor fell through to a confident critical.

**The fix, in one commit, all uncommitted work of that day:**

- *Sampler* (`probe_edge_access`): a token is announced only where robots.txt allows it
  for the home URL (RFC 9309, evaluated for the announced token); disallowed tokens are
  recorded under `edge_access.policy` with the matched rule; nothing probed → `reason`.
- *Fetcher* (`get_as`): the same rule enforced where the request is made — a disallowed
  token is never sent, `skipped=robots_disallow_for_token`, whoever calls.
- *Crawl probe*: `edge_block` grades probed tokens only; nothing probed → `not_evaluated`
  (`probe_tokens_disallowed` / `robots_unreachable`), no finding. A refusal of the auditor
  that no probe can explain is `inconclusive` (`crawler_access_unknown` /
  `crawler_access_mixed`), never critical; only "every robots-allowed token refused too"
  stays a critical fail, with each probe in the evidence sentence.
- *Documents*: `bot_tiers.md` §4 no longer promises the audit "never impersonates a listed
  token"; `fetch_policy.md`, `check_ids.md`, `coverage_map.md` (a design-level-dedupe
  bullet: one token is a policy finding or a behaviour finding, never both), the
  crawl-render `checks.md` and `non_findings.md`, and the README Safety section all agree.
  A hygiene test asserts the retired sentence appears nowhere.
- *Fixtures*: `edge-enforces-policy`, `edge-blocked-mixed`, `edge-refuses-auditor`, plus a
  test that each probe token's tier matches `bot_tiers.md`. `edge-blocked-bots` (the real
  defect) stays critical.
- *Step F*: probe strings on OpenAI's documented 1.4; Anthropic documents only the
  `Claude-User` token, said so in `sources.md`; `OAI-AdsBot` excluded with a reason; the
  JSON-LD paper's sentence tightened to its own definition of an enhanced entity page.

**Live proof**, ten sites the same day: nytimes (all three tokens policy → no edge finding,
robots findings only), bbc (per-token: two policy, one probed and served), redcross (robots
allows, edge refuses all → critical, correct), khanacademy (client-rendered shell →
critical, correct). Batch workdirs under the scratchpad `batch10/`.

**Two calibration candidates from that batch, not yet acted on:**
`ef.entity.nap_missing_plain_text` fired on 7 of 10 sites at `medium` for corporate and
SaaS sites that simply do not print a postal address (true, but arguably `low` there); and
`en.cta.missing` graded *About* pages (stripe, notion at `medium`) — an About page without a
sign-up button is what About pages look like. Both are rubric-and-registry changes with a
fixture each. Also still open: `cr.access.non_html_seed` reports `pass` when the home page
returned 403 (it never saw HTML) — should be `not_evaluated`.

## 15. 2026-09-10 — where things stand, and what to do next (read this first)

Everything above is history. This section is the current state.

**Repo:** `main`, clean, pushed. **All 24 steps of `BUILD_PLAN.md` are ticked** (Step 24's
submission itself is the user's action). Suite: 3,349 checks green
(`cd brand-ai-readiness-audit && python3 tests/run_tests.py`, >10 min; use `--stage <name>`
while iterating). 61 checks, 21 fixtures, five skills all pass the validator.

**Two people commit:** Sheel's sessions and Deepak (deepak23188@iiitd.ac.in). Always
`git pull --ff-only origin main` before starting anything.

**To audit any site:**
```
cd brand-ai-readiness-audit
python3 skills/audit-orchestrator/scripts/run_audit.py https://example.com/ --workdir audit-example
```
Read `audit-example/report.md`. `--category <id>` overrides inference, `--offline` re-grades a
saved workdir, `--verbose` shows each probe. `audit-*` directories are git-ignored.

**Live results so far** (all exit 0, no tracebacks, longest 83 s): Step 19's 13 sites; Deepak's
38; a 10-site batch on 2026-09-09 (72 defect findings, 0 judged false, ~10 arguable on
severity); iiitd.ac.in on 2026-09-10 (12 findings: 4 medium, 6 low, 2 info; category
nonprofit_institution; simulation answered 4 of 5 questions, the unanswerable one — "what
programs, and where" — matched the key-fact finding exactly).

**Steps 23–24 done on 2026-09-10.** Zip built with `git archive --format=zip -o
brand-ai-readiness-audit.zip HEAD:brand-ai-readiness-audit` (516 KB; rebuild after any commit),
unzipped cold, validator green from the copy, stdlib/GET-only/one-entrypoint/robots all proven.
The dry run on adobe.com and thehawksmoor.com found two defects, both fixed by rule with tests:
a hung crawler probe (`read_timeout`) is now `inconclusive probe_timeout`, never a critical
refusal; and every first-viewport rule measures from the first *visible* content
(`Document.content_mpos`, ignoring `noscript`/`svg`/`template`), not from `<body>` — a page with
200 KB of inline SVG before its first link had its four "Book a table" buttons reported as no CTA.

**An LLM-council session on 2026-09-10** (five advisors + peer review) reached these
conclusions, which are the plan from here:

1. **Do NOT do the 500-site corpus run.** Judges never see that number; it costs a day.
2. **Do Step 24 before Step 23.** Give Deepak the zip cold, a clean machine, three sites
   Sheel never ran — **adobe.com, a bare React SPA, a local business** — one hour. He lists
   every finding he cannot verify in 60 seconds and every place the README confused him.
   That list is the real Step 23. Adobe.com has never been run; do it first.
3. **The two severity calibrations are not optional** (the council's one real clash, resolved
   4–1): `ef.entity.nap_missing_plain_text` at `medium` on corporate/SaaS sites that simply do
   not print an address → `low` (or accept email as the contact fact); `en.cta.missing` grading
   About and Contact pages → info-level non-finding on those roles. Each is a registry +
   rubric change with a fixture. iiitd.ac.in's F-001 is a live example of the second.
4. **Make what is already built visible.** Reviewers flagged robots/GET-only compliance, the
   5-minute wall, and marketplace composition as "unaddressed" — all three are built and
   tested; the README must *say so in one line each* (request manifest per run; 300 s budget
   with partial reports; validator on all five skills, composition argument in
   `coverage_map.md` §3).
5. **Put the no-JS thesis on page one of the README as the point** ("we show what a
   non-JavaScript fetcher sees, because that is what AI crawlers see"), not as a limitation.
6. **Explain the simulation's verbatim-only rule in the report itself**, or it reads as
   weak next to teams that fake richer answers.
7. **Move the false-positive history inside the zip** (it lives in BUILD_PLAN.md/CONTEXT.md,
   outside): expand `CONTRIBUTING.md`'s known traps or add a short mistakes log — nine
   defects in Step 19, four in Deepak's pass, the edge-block fix.
8. **Consider sorting findings by verifiability**, not only severity — the first finding a
   judge reads decides the score. This changes `report_schema.md` §4; decide, don't drift.
9. Tag a ~90-second smoke subset of the suite; run the full suite once before zipping.
10. Also open, smaller: `cr.access.non_html_seed` reports `pass` when the home page returned
    403 (should be `not_evaluated`); check the zip for stray workdirs and its size.

**Decisions the council judged right, keep them:** stdlib-only; no headless browser (fix the
framing, not the bet); the large suite (it caught 13 real defects); "fix rules, never sites";
the verbatim-only simulation with its validator; the zero-findings clean-site report as a
product feature.

**Order for the next session:** pull → run adobe.com and read the first finding as a judge
would → the two calibrations (with fixtures) → README items 4–7 → Deepak's cold run → fix
his list → full suite → zip → Step 23 checklist against the zip → Step 24 → submit.
