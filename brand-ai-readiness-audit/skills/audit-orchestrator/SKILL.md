---
name: audit-orchestrator
description: Entrypoint for the brand AI-readiness audit. Given a website URL or domain, runs the crawl-render, fact-extractability, entity-freshness-corroboration, and engagement audits, composes their findings into one prioritized report (evidence, severity, confidence, suggested actions, proactive recommendations), simulates what an assistant could answer from the site's own text, and emits it as JSON plus Markdown. Use when asked to audit a website for AI discoverability, AI citation readiness, or on-site engagement problems, or to diagnose why a brand is missing or misrepresented in AI assistants.
license: MIT
compatibility: Requires Python 3.8+ (standard library only) and outbound HTTPS access to the audited site. Read-only; performs GET requests only, respects robots.txt, and finishes in under five minutes for a typical site. A web-search tool is optional and used only for the bounded off-site spot-check.
metadata:
  role: entrypoint
  marketplace: brand-ai-readiness-audit
allowed-tools: Bash(python3:*) Read Write WebSearch
---

# Audit Orchestrator (entrypoint)

## When to use

Use this skill when a user asks to audit a website for AI discoverability
and/or on-site engagement and wants one actionable report. It answers two
questions about a site: why AI assistants might not find, quote or credit the
brand, and why visitors who do arrive might not stay. Everything is graded
from what a non-JavaScript fetcher receives; nothing is modified, nothing is
submitted, no assistant is queried.

Do not use it for a single page, a PDF, an app store listing, or a site the
user cannot legitimately audit. It never impersonates a bot or bypasses a
challenge page.

## Inputs

- A URL or bare domain, for example `https://example.com` or `example.com`.
- Optional: `--category <id>` to override the inferred site category
  (`references/site_categories.md` section 1) when the user knows better;
  `--workdir <dir>` to choose where the run is written; `--offline` to re-grade
  an existing workdir without any network access.

## Procedure

Every command runs from the marketplace root. Do not skip a step, do not
reorder steps 3 and 4, and never edit `report.json` by hand: step 7 does that.

1. **Run the audit.**

   ```
   python3 skills/audit-orchestrator/scripts/run_audit.py https://example.com --workdir audit-example
   ```

   This samples the site once (home plus up to five role pages, robots.txt,
   sitemap), runs the four probe skills in stage order as separate processes
   with a 60-second cap each, composes the report, validates it, and prints
   the paths of `report.json` and `report.md`. It exits 0 with a valid report
   even when the site is unreachable or a probe fails: the report then says so
   (`cr.access.http_error`, `or.run.probe_error`). If it exits 1, read the
   `PROBLEM` lines it printed; that is a tool defect, not a site defect, and
   the report it still wrote must not be presented as final.

2. **Read `report.json`** (the `Read` tool, not a script). Before doing
   anything else, check three fields:

   - `run.probes`: every entry should have `error: null`. If not, the
     narrative (step 6) must say the run was incomplete.
   - `summary`: the counts you will quote.
   - `ai_answer_simulation.questions`: which questions are `answerable` and,
     for the rest, which `missing_facts` and which `see_finding` explain them.

3. **Off-site spot-check, only if a web-search tool is available in this
   session.** Follow
   `../entity-freshness-corroboration-audit/references/offsite_spotcheck.md`
   exactly: at most five searches, the queries listed in
   `audit-example/work/entity.json`, at most ten verbatim mentions, written to
   `audit-example/work/offsite_mentions.json`. Then re-run the entity probe
   and recompose:

   ```
   python3 skills/entity-freshness-corroboration-audit/scripts/entity_probe.py --workdir audit-example --out audit-example/probes/entity-freshness-corroboration-audit.json
   python3 skills/audit-orchestrator/scripts/compose.py --workdir audit-example
   ```

   Without a search tool, do nothing: the `not_evaluated` note with reason
   `tool_unavailable` is the correct result and already carries the queries.
   This step comes before step 4 because compose rewrites `report.json`.

4. **Write the simulated answers**, following
   `references/simulation_rules.md` sections 2 to 4 without exception. Open
   `audit-example/work/extracted_facts.json` with `Read`. For each question
   with `answerable: true`, write one to three sentences whose substance is
   only the verbatim `value` strings of the facts in `facts_used`, in double
   quotes, framed by words that carry no facts ("According to the site, …").
   For each question with `answerable: false`, write nothing. Do not use
   anything you know about the brand, anything in the page snapshots, or
   anything fetched: the validator will reject an answer that does not quote
   its facts verbatim, and the reader can check every quotation against the
   facts file.

5. **Write the attribution note** (`references/simulation_rules.md` section
   5): one or two sentences on whether an assistant using these facts would
   have the brand's name in hand, based only on whether the quoted values
   carry the name and on the `ef.entity.*` and `ef.corroboration.*` results in
   the report.

6. **Write the narrative** (`references/simulation_rules.md` section 7):
   three to six sentences, grouped invisible → stale → bouncing, naming the
   worst finding of each group by id, stating how many simulation questions
   were answerable, and closing with what to do first (the `quick_wins` ids
   when there are any, otherwise `summary.start_with`). Every sentence must trace to a finding id, a passed
   check, a coverage line or the simulation. If any probe did not finish, the
   first sentence says the run was incomplete.

7. **Finalize.** Put steps 4 to 6 in one small file and let the script merge,
   re-render and validate:

   ```
   cat > audit-example/answers.json <<'EOF'
   {
     "answers": {
       "q1": {"answer_from_facts": "According to the site, \"…\""},
       "q3": {"answer_from_facts": "The contact page lists \"…\""}
     },
     "attribution_note": "…",
     "narrative_summary": "…"
   }
   EOF
   python3 skills/audit-orchestrator/scripts/finalize.py --workdir audit-example --answers audit-example/answers.json
   ```

   `finalize.py` writes the answers onto the matching questions, sets the
   note and the narrative, renders `report.md` from the JSON, and runs
   `validate.py --final`. Exit 0 means the report is final. On exit 1 read
   the `PROBLEM` lines, fix the answers file (a rejected answer almost always
   paraphrased instead of quoting, or named a fact it did not quote), and run
   it again. Do not present a report that has not passed.

8. **Emit both files.** Hand the user `audit-example/report.md` as the
   deliverable and `audit-example/report.json` as its machine-readable twin,
   with the one-line summary the validator printed. Point out the
   `limitations` section: the report is a point-in-time read of served HTML
   and says so.

## Output

`report.json` and `report.md`, the Markdown rendered from the JSON and
containing nothing the JSON does not (`references/report_schema.md` section
3). The floor is the handout's required shape: `site`, `audited_at`, a
`summary` of counts by severity, and `findings` each with `id`, `title`,
`severity`, `evidence` and a `suggested_action` with `summary` and `priority`.
On top of it: the site category and sampled pages, `quick_wins` plus a
one-sentence `summary.headline` and `summary.start_with` naming where to
begin, every `passed_checks` entry with a positive title, `coverage` of the handout's
concepts A–F and of the seven audit stages, `proactive_recommendations` that
never restate a finding, the `ai_answer_simulation` with its facts-only
basis, the `narrative_summary`, `limitations` that always open with the
point-in-time statement, `suppressed_findings` kept for transparency, and the
`run` record with per-probe timings.

A clean site produces a report with zero defects, a list of what was verified,
and recommendations framed as opportunities. That is a valid and useful
result, not a failure of the tool.

## Scripts

| Script | Role |
|---|---|
| `skills/audit-orchestrator/scripts/run_audit.py` | The whole pipeline as one command: sample, four probes, compose, validate. |
| `skills/audit-orchestrator/scripts/compose.py` | Merge probe outputs into the report: dedupe, order, tag, pre-fill the simulation, render Markdown (`--render-only` re-renders from JSON). |
| `skills/audit-orchestrator/scripts/validate.py` | The handout floor, then the superset; `--final` for the report the agent hands over. |
| `skills/audit-orchestrator/scripts/finalize.py` | Merge the agent's answers file into the report, re-render, validate `--final`. |
| `skills/audit-orchestrator/scripts/sample_site.py`, `fetch_url.py` | Utilities: sample a site into a workdir, fetch one URL under the policy. |
| `skills/audit-orchestrator/scripts/auditlib/` | Shared code every probe imports: fetcher, robots parser, document model, sampler, registry, category tables. |

## Shared conventions

Every skill in this marketplace follows the files in `references/`; nothing
in a probe or a SKILL.md invents a rule that belongs here.

| File | Governs |
|---|---|
| `references/report_schema.md` | Probe output, Finding, Evidence, final report floor and superset, ordering, run layout, Markdown rendering |
| `references/severity_confidence_rubric.md` | Severity, confidence, effort, adjustment order, quick-win rule, wording |
| `references/sources.md` | Every external claim this marketplace makes, with the URL it was verified against; the AI bot tier rows and the tokens deliberately excluded |
| `references/check_ids.md` | check_id naming rule and the registry of every check with defaults; positive titles for passed checks |
| `references/coverage_map.md` | Map from the handout's Round-2 concepts A–F to our seven audit stages, check-to-stage map, dedupe table, derived tags, explicit non-coverage |
| `references/site_categories.md` | Category ids, inference scoring, page roles, key facts, engagement caps, severity overrides, simulation questions |
| `references/simulation_rules.md` | The facts-only rule, the forbidden-knowledge rule, question-by-question wording, the attribution note, the narrative |
| `references/bot_tiers.md` | AI bot tokens by tier and robots.txt grading |
| `references/fetch_policy.md` | GET-only rules, identity, limits, robots semantics, challenge fingerprints, FetchResult and sample manifest |
