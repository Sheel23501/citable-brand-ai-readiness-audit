# Working on this marketplace

Read this before adding or changing a check. The codebase enforces its own
conventions through tests, which is good, but it means a change made in one
place and not the other five fails in ways that do not obviously point at what
you missed.

---

## Fast test loop

The full suite is ~10 minutes. **Do not run it on every edit.** Run the stage
you touched.

Stages split sharply by whether they need the fixture farm (18 local HTTP
servers). Measured on a laptop:

| Stage | Needs servers | Time |
|---|---|---|
| `manifest` `robots` `extract` `htmldoc` | no | **~0.5s** |
| `serve` `variants` `sample` `probe_*` `compose` `validate` `run_audit` `scripts` | yes | minutes |

So the tight loop is the offline stages — use them constantly. The
server-backed ones are worth running once you think you are done with a change,
not after every keystroke.

```bash
python3 tests/run_tests.py --stage manifest      # ~0.5s: registry/doc bookkeeping
python3 tests/run_tests.py --stage robots        # ~0.5s: RFC 9309 parsing
python3 tests/run_tests.py --stage probe_cr      # minutes: one probe, every fixture
python3 tests/run_tests.py                       # everything, before you commit
```

Stages: `manifest serve variants robots fetch htmldoc extract sample probe_cr
probe_fx probe_ef probe_en compose validate run_audit scripts live`

Which stage matters for what you changed:

| You changed | Run |
|---|---|
| A probe's checks | `--stage probe_cr` (or `_fx` / `_ef` / `_en`) |
| `check_ids.md`, `compose.py` | `--stage manifest --stage compose` |
| `auditlib/fetch.py` or `robots.py` | `--stage fetch --stage robots --stage sample` |
| A fixture | `--stage serve` then the relevant probe stage |
| Report schema or validator | `--stage validate --stage run_audit` |

`tests/serve_fixtures.py` keeps the fixture sites up on ports 8100+ so you can
probe them by hand.

**Never check the exit code through a pipe.** `run_tests.py | tail` returns
`tail`'s status, not the runner's, so a failing suite looks like it passed.

---

## Adding a check

A check id lives in **six** places. The tests enforce five of them.

1. **`skills/audit-orchestrator/references/check_ids.md`** — one registry row:
   `| check_id | stage | severity | max | confidence | effort | scope | fails when |`.
   This file is the single source of truth; the code parses it at runtime.
2. **`skills/<skill>/references/checks.md`** — a documentation block: the rule,
   the evidence, and why the severity is what it is.
   *Enforced by:* "references document every `<prefix>.` check".
3. **`skills/audit-orchestrator/scripts/compose.py`** → `POSITIVE_TITLES` — the
   pass condition said as a fact about a site ("robots.txt does not
   blanket-disallow crawlers"). Printed under "What is working".
   *Enforced by:* "every registry check has a positive title".
4. **`skills/<skill>/references/non_findings.md`** — if the check has a
   near-miss that must *not* fire, write it down. Nothing enforces this, and it
   is where false positives are prevented.
5. **`skills/audit-orchestrator/references/fetch_policy.md`** — only if the
   check costs HTTP requests. Add a line item to the budget table.
   *Enforced by:* the per-fixture sampling budget assertion, which fails on
   **every** fixture at once if you skip it.
6. **`tests/fixtures/<name>/`** — a fixture that triggers it, with the check id
   listed in `_fixture.json` under `expected.fail` / `expected.info`, plus the
   ids that must still `pass`. A check with no fixture is untested.

Then emit it from the probe via `ProbeOutput`: `out.fail(...)`,
`out.policy_note(...)` (for `info`-severity policy observations),
`out.inconclusive(...)`, or `out.check(cid, "pass")`. Never build a finding dict
by hand — the severity rubric is applied inside `ProbeOutput`.

Run `--stage manifest` first — it is half a second and catches items 1, 2 and 3
(the registry/documentation/positive-title bookkeeping), which is where most
mistakes are. Then run the relevant `probe_*` and `compose` stages, which take
minutes because they start the fixture servers.

---

## Invariants you must not break

**Replay parity.** `--workdir` mode must reproduce `--url` mode exactly, and a
test asserts it per fixture. This is why **all network access happens in the
sampler**, never in a probe's check. If your check needs a request, add it to
`auditlib/sampler.py` and record the result in `sample.json`; the probe then
grades what was recorded. A check that fetches at grade time will fail parity.

**Never crash.** Every probe emits valid JSON on every input — DNS failure, 403,
a PDF at the home URL, an empty site. The `scripts` stage runs every script with
deliberate wrong usage and asserts no traceback anywhere. The guarantee lives in
`auditlib/cli.py:probe_main`; keep individual checks inside their own try/except
so one bad page cannot take down a run.

**Standard library only.** No third-party imports anywhere in `skills/`. This is
a submission requirement, not a preference.

**GET only.** No POST/PUT/DELETE/PATCH. The audit recommends; it never changes a
site.

**Severity discipline.** Read `references/severity_confidence_rubric.md` before
choosing a severity. Two rules that are easy to get wrong:
- A `training_only` bot block is `info`, never a defect. It is a legitimate
  policy choice that does not stop the site being cited today.
- `inconclusive` or `not_evaluated` ⇒ severity `info`, always.

**Confidence is not severity.** A heuristic never reports as certain. Proxies
are capped at `medium` and are `low` unless a second signal corroborates.

**Sources.** Nothing in a SKILL.md or reference may cite a claim that is not in
`references/sources.md` with the URL it was verified against. `load_bot_tiers()`
hard-gates on `Status == verified`, so an unconfirmed bot-tier row is inert at
runtime rather than quietly driving a severity.

---

## Traps that have already bitten

**Anchor any `audit-*` exclusion pattern to the root.** A bare `audit-*` glob
matches `skills/audit-orchestrator/` — the entrypoint. This has silently dropped
the entrypoint from both a `.gitignore` and a packaging script. Always write
`/audit-*/` or match the full relative path, and after building an archive,
*list the skills inside it* and cross-check against `marketplace.json`.

**Fixtures must stay byte-exact.** `.gitattributes` pins `tests/fixtures/**` to
`-text` because some assertions match exact bytes (`b"User-agent: *\nDisallow: /"`).
Without it, Git's `autocrlf` rewrites them to CRLF on Windows checkout and those
tests fail for a reason that has nothing to do with your change.

**Always pass `encoding="utf-8"` to `open()`.** On Windows the default is
cp1252, which raises `UnicodeDecodeError` on any smart quote in captured page
text. And use a `with` block: `json.load(open(...))` leaks the handle, which
makes `TemporaryDirectory` cleanup fail with `WinError 32`.

**Derive counts, never hardcode them.** A test that asserts `checks_run == 61`
goes stale the moment someone adds a check. Use `len(Registry().rows)`.

---

## Before you commit

```bash
python3 tests/run_tests.py            # must end GREEN
```

Run artifacts (`audit-<host>/`, `__pycache__`) are gitignored. If you see them
in `git status`, something is wrong with the ignore rules — do not commit them.
