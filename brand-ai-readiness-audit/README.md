# brand-ai-readiness-audit

An Agent Skill Marketplace that audits any website for the problems that keep it
out of AI assistants' answers, and the problems that lose the visitor who does
arrive. It emits one prioritised, evidence-backed report of findings and
suggested actions.

**Read-only. It recommends; it never modifies a live site.** Every request is a
plain GET, robots.txt is obeyed, and the whole run is bounded to 40 requests and
five minutes.

```bash
python3 skills/audit-orchestrator/scripts/run_audit.py https://example.com
# -> audit-example.com/report.json  and  report.md
```

---

## The two halves

The brief names two failure modes, and they are not the same problem. This
marketplace keeps them separate all the way through, using the industry's own
distinction:

| | **Agentic traffic** | **Referral traffic** |
|---|---|---|
| Who arrives | An AI crawler fetching the page | A human who clicked a citation |
| Failure looks like | The brand is absent from, or misrepresented in, the answer | The visitor lands, is disoriented, and leaves |
| Covered by | `crawl-render-audit`, `fact-extractability-audit`, `entity-freshness-corroboration-audit` | `engagement-audit` |

An audit that only does the first half explains why nobody arrives. It cannot
explain why the people who do arrive leave again.

## Where this sits

Tools in this space split cleanly, and both sides leave the same gap:

- **Outside-in** platforms watch what assistants say about a brand — prompt
  panels, share-of-voice, CDN log analysis. They tell you *whether* you are
  cited. They need you to be a customer, and they cannot tell you which line of
  your HTML caused it.
- **Inside-out** checkers read your site — robots.txt, schema presence, a
  sitemap — and hand back a letter grade. They run on any URL, but they stop at
  "no schema found" and never connect that to a consequence.

Neither closes the loop. This marketplace does: it reads only what a
non-JavaScript fetcher can actually see, reasons from the published mechanics of
how generative engines retrieve, rank, select and attribute sources, then
demonstrates the consequence by attempting to answer real buyer questions using
**strictly** the evidence it extracted — so the report says not just that a fact
is missing, but which question that missing fact costs you.

And where it is guessing, it says so.

---

## Quick start

```bash
# Audit a site end to end (writes report.json + report.md into a workdir)
python3 skills/audit-orchestrator/scripts/run_audit.py https://example.com

# Re-run the probes over an existing sample without touching the network
python3 skills/audit-orchestrator/scripts/run_audit.py --workdir audit-example.com --offline

# Any probe on its own, against a live URL or a saved sample. Every probe imports the shared auditlib from
# skills/audit-orchestrator/scripts, so keep that folder alongside it.
python3 skills/crawl-render-audit/scripts/crawl_probe.py --url https://example.com
python3 skills/engagement-audit/scripts/engagement_probe.py --workdir audit-example.com
```

Python 3.8+. **No dependencies** — standard library only, no API keys, no
external service.

Every skill folder is independently *valid* — each carries its own spec-compliant
`SKILL.md`, its own checks and its own `references/` — and each probe runs on its
own against a live URL or a saved sample. They are not independently
*distributable*: the four sub-skills import the shared fetch/parse/severity
library from `skills/audit-orchestrator/scripts/auditlib`, and read the shared
schema and rubric from the orchestrator's `references/`. That is deliberate — one
fetch policy, one severity rubric and one report schema, rather than four drifting
copies — but it means a sub-skill folder lifted out of the marketplace on its own
will not run.

A finished report from a real run is in [`examples/`](examples/) — 10 findings
from 61 checks in 16.7 seconds, including the facts file so every quoted
excerpt in the simulation can be checked.

---

## The five skills

| Skill | Concern | Checks |
|---|---|---|
| **`audit-orchestrator`** *(entrypoint)* | Samples the site once, runs the four probes, merges and dedupes their findings, applies the severity rubric, ranks quick wins, and writes the report | 2 |
| `crawl-render-audit` | Can a non-JavaScript fetcher reach and read the site? robots.txt by bot tier, **edge-level crawler access**, JS gates, client-rendered shells, sitemap, noindex, canonical | 19 |
| `fact-extractability-audit` | Can a machine pick out the specific facts? Plain-text key facts, image-only facts, JSON-LD validity and required properties, page self-identification | 12 |
| `entity-freshness-corroboration-audit` | Is the brand identifiable and trusted? Disambiguation anchors, plain-text identity facts, freshness signals, off-site corroboration surface | 12 |
| `engagement-audit` | Does the visitor stay? First-viewport clarity, calls to action, orientation, context retention, mobile readiness, link health | 16 |

The split follows the causal chain, not convenience: a crawler must be **let in**
before it can **read**, must read before it can **extract a fact**, and the fact
must be **corroborated** before it is trusted. Engagement is deliberately
separate — it begins after the click and shares almost no logic with the rest.

## How the entrypoint composes them

```
run_audit.py <url>
      |
      v
  sample once ......... home + up to 5 role pages, robots.txt, sitemap,
      |                 site-category inference, edge-access probe
      |                 -> sample.json + snapshots/   (one fetch, shared by all)
      v
  four probes ......... each its own process, own timeout, own JSON
      |                 crawl-render -> fact-extractability
      |                              -> entity-freshness -> engagement
      v
  compose ............. merge, apply the dedupe table, assign F-00N ids,
      |                 normalise severity/confidence, rank quick wins,
      |                 pre-fill the simulation questions
      v
  validate ............ the brief's required floor + our superset
      |
      v
  report.json + report.md
```

Two properties this buys, both load-bearing:

- **One fetch, four probes.** The sampler fetches each page once and every probe
  reads the same snapshots, so a four-skill audit costs about the same number of
  HTTP requests as a one-skill audit. That is politeness, not just speed.
- **Replay parity.** Every page the checks grade is fetched once, by the sampler,
  and recorded; `--workdir` mode then reproduces `--url` mode exactly, and the
  test suite asserts that for every fixture. Two probes make their own requests
  and record them the same way: the engagement probe's link sample and 404
  check, and the entity probe's single optional Wikipedia or Wikidata lookup.
  A check that fetched a *graded page* at grade time would break parity.

---

## What the report contains

Every field the brief requires, plus a superset. Required floor: `site`,
`audited_at`, a counts-by-severity `summary`, and per finding `id`, `title`,
`severity`, `evidence`, `suggested_action`.

Each finding also carries:

| Field | Why |
|---|---|
| `round2_mode` | `invisible`, `stale` or `bouncing` — the brief's own three failure modes, so the two halves are never blurred |
| `pipeline_stage` | Where it breaks the citation pipeline: `retrieval`, `ranking`, `selection`, `attribution`, `post_click` |
| `handout_concepts` | Which of the brief's concepts A–F the finding traces to |
| `opportunity_type` | `content` or `technical` — which team fixes it |
| `mechanism` | The stage that produced it: access, render, extract, entity, freshness, corroboration, engagement |
| `confidence` | `high` / `medium` / `low`. **A heuristic is never reported as a certainty** |
| `why_it_matters` | Why this costs the brand an answer, in plain words |
| `suggested_action.impact` / `.effort` | Feeds `quick_wins`: high impact, low effort, ranked first |
| `evidence_items` | The exact bytes the claim rests on — a status code, a robots rule, an HTML excerpt |
| `quick_win` / `rank` | Ordering, so the reader knows what to do first |

On the shipped example these come out as `round2_mode`: 6 invisible, 2 stale,
2 bouncing — both halves present in one report.

Plus `passed_checks` (what is working, said as a fact), `coverage`,
`limitations`, `ai_answer_simulation`, and `run` telemetry.

### The AI-answer simulation

The agent attempts a handful of realistic buyer questions using **only** the
facts the crawl actually extracted, and is forbidden from filling gaps from its
own knowledge. Where it cannot answer, the report says so and names the finding
responsible. `validate.py` enforces this mechanically: the basis is pinned to
`extracted_facts_only`, and a paraphrase or an unsupported answer is rejected.

It is a demonstration, not a prediction. What a real assistant says today is
non-deterministic and account-bound; the report says so in its limitations. The
value is that it is reproducible: anyone can open `work/extracted_facts.json`
and check every quoted excerpt.

---

## Design principles

**Severity is earned, not asserted.** A `critical` means the mechanism fails
completely for the whole site. Blocking a *training-only* crawler is `info`, not
a defect — it is a legitimate policy choice that does not stop the site being
cited today. Tools that grade every `GPTBot` block as critical are wrong, and
that distinction comes straight from the operators' own documentation.

**Confidence is separate from severity.** A robots.txt rule matched per RFC 9309
is `high` confidence. A page-weight proxy is `low`, and says it is a proxy. Two
independent signals are required before a heuristic reaches `medium`.

**Non-findings are documented too.** Each skill ships a
`references/non_findings.md` saying what it deliberately does not flag and why —
a plain 301 redirect, a crawler served normally, an enterprise site with no
public pricing. Most false positives come from checks that never learned to stay
quiet.

**It never crashes.** Every probe emits valid JSON on every input — DNS failure,
403, a PDF at the home URL, an empty site. A traceback is never the only output.

---

## What it does not cover

Stated plainly, because a report that overclaims is worse than one that admits
its edges. Full table in `skills/audit-orchestrator/references/coverage_map.md`
section 5; every report repeats it in `limitations`.

- **Whether a specific assistant cites the brand today.** That needs live
  querying, which is non-deterministic and account-bound. We simulate from
  extracted facts and label it a simulation.
- **Presence in training data.** Not observable from outside.
- **Rendering with a headless browser.** Deliberate: the point is to see what a
  non-JavaScript fetcher sees. CSR detection uses two independent signals.
- **Cloaking beyond the home URL and three crawler tokens.** The edge-access
  check compares the home URL across three published tokens; it cannot see rules
  that vary by IP, geography or cookie state.
- **Core Web Vitals, WCAG conformance, backlinks, ranking, content quality.**
  Out of scope; a page-weight proxy stands in for performance at `low`
  confidence.
- **Pages beyond the ≤6 sampled.** Every finding's evidence states its sample.

---

## Prior art, and how this differs

This is a crowded space and pretending otherwise would be dishonest.

| Category | Examples | What they do | What they miss |
|---|---|---|---|
| Enterprise GEO platforms | Adobe LLM Optimizer / Brand Visibility, Profound, Scrunch | Prompt monitoring at scale, CDN log analysis, auto-deploy | Require onboarding and log access; cannot be pointed at an arbitrary site |
| Mid-market monitors | Peec, Otterly, AthenaHQ | Track mentions and sentiment over time | Purely outside-in: whether you are cited, never why the page failed |
| Free readiness checkers | AI Agent Readiness Checker, Siftly, aicrawltest | robots.txt + schema + sitemap, graded A–F | One-shot checklists; no severity reasoning, no confidence, no engagement half |
| Agent-skill SEO packages | `claude-seo` (25 sub-skills, 18 sub-agents) | Broad SEO with GEO appended | Depend on paid third-party APIs; breadth over separation of concerns |

**The individual checks here are not novel** — free tools have tested AI-bot
rules in robots.txt for years. Four things are:

1. **Edge-level crawler access.** Every other tool answers "can AI crawlers reach
   this site?" by *parsing robots.txt* — a statement of policy. A CDN can refuse
   those crawlers regardless. `cr.access.edge_block` requests the home URL
   announcing each published crawler token and compares the response with the
   baseline, so a site that passes every robots.txt check while returning 403 to
   real crawlers is caught. This is the outside-in equivalent of what enterprise
   platforms achieve with CDN logs — three requests, no privileged access.
2. **The engagement half**, which the commercial GEO market largely ignores.
3. **The causal bridge.** Not "no schema found" but "this question is
   unanswerable, because this fact exists only inside an image."
4. **Refusing to overclaim.** Confidence tiers, documented non-findings, and
   severity that distinguishes a deliberate training opt-out from a real defect.

**Dependencies:** none. The manifest resolves with nothing but Python's standard
library, which is also what the brief's self-containment rule asks for.

---

## Field research

The checks are calibrated against real sites, not invented. During development
the probes were run against live production sites across several categories,
which is where several design decisions came from — including the discovery that
a major nonprofit serves its full home page to a normal client and returns 403 to
declared AI crawlers, while its robots.txt contains no AI rules at all. That
single observation is why `cr.access.edge_block` exists.

Two findings shaped calibration in particular:

- A homepage's text-to-markup ratio is a poor CSR signal on its own; marketing
  homepages are nav-heavy by nature. Detection requires a low absolute word count
  **and** a structural signal.
- Blocking `GPTBot` while allowing `OAI-SearchBot` and `ChatGPT-User` is common
  and deliberate. Grading it as critical would be a false positive on every site
  that made that choice on purpose.

No site studied is used as a test case; all fixtures are synthetic.

---

## Sources

Every external claim traces to
`skills/audit-orchestrator/references/sources.md`, which records the URL each was
verified against. The AI crawler tier table is built entirely from operator
documentation — OpenAI, Anthropic, Google, Apple, Microsoft, Perplexity, Meta,
DuckDuckGo, Mistral, Amazon, Common Crawl. **Five tokens were removed** for
having no operator documentation at all, rather than kept with a guess: a wrong
tier row would produce a wrong severity. `load_bot_tiers()` enforces this — a row
not marked `verified` is inert at runtime.

## Safety

- Read-only: GET only, no authenticated areas, no site-altering actions.
- robots.txt obeyed for every fetch beyond robots.txt itself, per RFC 9309.
- Bounded: ≤40 requests per audit, ≥0.5s between requests to the same host, ≤6
  pages sampled, 300s wall clock.
- The edge-access check announces published crawler tokens to observe how the
  origin responds, and only where the site's robots.txt allows that token,
  evaluated for the announced token exactly as for our own. A token the site
  has disallowed is never sent. It never uses one to get around a refusal: a
  403 is recorded as evidence and the probe stops.

## Layout

```
marketplace.json          manifest: five skills, exactly one entrypoint
README.md  LICENSE
examples/                 a real, unedited run against a live public site
skills/
  audit-orchestrator/     ENTRYPOINT - SKILL.md, references/ (shared conventions),
                          scripts/ (auditlib + run_audit, compose, validate, finalize)
  crawl-render-audit/     fact-extractability-audit/
  entity-freshness-corroboration-audit/     engagement-audit/
tests/
  run_tests.py            4752 assertions across 29 synthetic fixture sites
  serve_fixtures.py       one local server per fixture
  fixtures/<name>/        static mini-sites + the check ids each must trigger
```

Shared conventions live in `skills/audit-orchestrator/references/` and are the
single source of truth for every script and every SKILL.md:

| File | Governs |
|---|---|
| `report_schema.md` | Probe output, Finding, Evidence, report floor and superset, ordering, Markdown rendering |
| `severity_confidence_rubric.md` | Severity, confidence, effort, adjustment order, quick-win rule |
| `check_ids.md` | Naming rule and the registry of all 61 checks with their defaults |
| `coverage_map.md` | Concepts A–F mapped to stages, the dedupe table, what is not covered |
| `site_categories.md` | Categories, page roles, key facts, engagement caps, simulation questions |
| `bot_tiers.md` | AI bot tokens by tier: live-answer, index, training-only |
| `fetch_policy.md` | GET-only rules, budgets, robots semantics, challenge fingerprinting |
| `sources.md` | Every external claim and the URL it was verified against |
| `simulation_rules.md` | The rulebook for the agent-written simulation, attribution note and narrative |

## Tests

```bash
python3 tests/run_tests.py                      # offline-safe: fixtures, probes, compose, validate, end to end
python3 tests/run_tests.py --live https://example.com   # add real-site fetches
python3 tests/serve_fixtures.py                 # keep fixtures up for manual probing
```

Fixtures include five **false-positive guards**, one well-built site per
category, each of which must produce zero defects: `clean-site` (SaaS, en),
`clean-restaurant-fr` (a Paris bistro, **French** throughout),
`clean-consultancy` (New York professional services), `clean-publisher` (a
Nova Scotia news site) and `clean-corporate` (a Sydney industrial group). Two
non-English fixtures pin the language rules: `german-site` and
`hindi-nonprofit` (Devanagari; the checks whose phrase lists are English are
gated to low confidence there, never asserted). Alongside them: `csr-shell`,
`js-gate`, `challenge-page`, `bot-blocking-robots`, `blanket-disallow`,
`edge-blocked-bots`, `edge-blocked-training-only`, `malformed-jsonld`,
`image-only-pricing`, `non-html-seed`, `one-page-portfolio`, `blocked-links`,
`js-nav-thin-sample` and `unsampled-contact-nonprofit` (the absence gate),
three `weak-*` sites, and three edge-policy cases (`edge-enforces-policy`,
`edge-blocked-mixed`, `edge-refuses-auditor`) that pin the rule that a site
enforcing its own robots.txt at the edge is never reported as a defect.
Each declares the check ids it must trigger, taken from the registry, and the
checks that must record no verdict on it and why. `CONTRIBUTING.md` has the
full category and language matrix.

## Working on this

`CONTRIBUTING.md` covers what a new contributor needs: the fast per-stage test
loop, the six places a check id must be registered, the invariants that must not
break (replay parity, never-crash, stdlib-only, severity discipline), and the
traps that have already cost time.

## Validation

```bash
agentskills validate skills/<skill-name>
```

## Licence

MIT. See `LICENSE`.
