# Example audit

A real, unedited run of the entrypoint against a live public site, kept here so
the finished shape of a report can be read without running anything.

```bash
python3 skills/audit-orchestrator/scripts/run_audit.py https://www.python.org
python3 skills/audit-orchestrator/scripts/finalize.py --workdir audit-python.org --answers answers.json
```

| File | What it is |
|---|---|
| `python.org-report.md` | The rendered report a non-expert reads |
| `python.org-report.json` | The same report as structured data |
| `python.org-extracted_facts.json` | The facts file the simulation is allowed to quote from — included so every quoted excerpt can be checked |

**Result:** 10 findings (0 critical, 1 high, 2 medium, 5 low, 2 informational)
from 61 checks in **16.7 seconds**. Validated with `validate.py --final`.

## Why this site

`www.python.org` is a large, well-maintained, non-commercial site whose
robots.txt welcomes ordinary crawlers, and it belongs to no one's brand
portfolio. Auditing it is read-only and recommends nothing to anybody: it is
here to show the report's shape, not to grade the Python Software Foundation.
Nothing about it was used to design or tune any check — the fixtures in
`tests/fixtures/` are all synthetic.

## What this example demonstrates

**The causal bridge.** The report does not stop at "2 of 4 key facts are not
extractable" (F-001). The simulation shows what that costs: asked *"What is
Python.org's mission?"*, an assistant with only this site's served HTML has
nothing to answer with. The finding and the consequence sit in the same report.

**Quoting, not paraphrasing.** Every simulated answer quotes the facts file
verbatim, and the facts file ships alongside so the quotes can be verified. The
answer to *"How do I donate, apply, or join?"* quotes a navigation fragment,
because that is genuinely all the extractor found — the report does not tidy it
into something more flattering.

**Confidence separated from severity.** F-002 is `medium` severity at `high`
confidence (a plain-text absence, deterministic). F-003 is `medium` at `low`
confidence (a word-count heuristic). Both are reported; only one is asserted
firmly.

**A clean bill where one is due.** 47 of 61 checks passed and are listed by name
under "What is working", so the report says what is right as well as what is
wrong. There are no `critical` findings, and the report does not manufacture one.

**Recommendations that are not defects.** The proactive section suggests
`/llms.txt` while stating plainly that adoption is unconfirmed by any operator's
documentation and that it is *not graded anywhere in this audit*. An unproven
convention is offered as an option, never scored as a failure.

## Note on the narrative and the simulated answers

Those are the only prose in the report written by the agent rather than by a
script. They are held to `references/simulation_rules.md`: an answer may contain
only verbatim quotations of facts marked `present`, `validate.py --final`
rejects a paraphrase, and every sentence of the narrative must trace to a
finding id, a passed check, a coverage line, or the simulation. The agent is
forbidden from using anything it happens to know about the site — which is why
questions the facts file cannot answer are left unanswered instead of filled in
from memory.
