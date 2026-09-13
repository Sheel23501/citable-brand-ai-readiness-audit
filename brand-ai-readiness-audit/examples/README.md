# Example audit

A real, unedited run of the entrypoint against a live public site, kept here so
the finished shape of a report can be read without running anything.

```bash
python3 skills/audit-orchestrator/scripts/run_audit.py https://www.python.org
```

| File | What it is |
|---|---|
| `python.org-report.md` | The rendered report a non-expert reads |
| `python.org-report.json` | The same report as structured data |
| `python.org-extracted_facts.json` | The facts file the simulation is allowed to quote from — included so every quoted excerpt can be checked |

**Result:** 10 findings (0 critical, 0 high, 3 medium, 5 low, 2 informational)
from 61 checks in **16.2 seconds**. Validated with `validate.py --final`, which
passes on the report as the script writes it: the narrative, the attribution note
and every answer are written by `compose.py`, not added by hand afterwards.

## Why this site

`www.python.org` is a large, well-maintained, non-commercial site whose
robots.txt welcomes ordinary crawlers, and it belongs to no one's brand
portfolio. Auditing it is read-only and recommends nothing to anybody: it is
here to show the report's shape, not to grade the Python Software Foundation.
The checks were designed against the synthetic fixtures in `tests/fixtures/`,
but two rules were widened after live runs on this site exposed them: the
mission phrase now matches "The mission of X is to", and a transport failure on
a sampled link is no longer reported as the site's broken link.

## What this example demonstrates

**The causal bridge.** The report does not stop at a list of missing facts. The
simulation shows what each one costs: asked *"What sets Python.org apart from
alternatives?"* and *"What programs does Python.org run, and where?"*, an
assistant holding only this site's served HTML has nothing to answer with, and
the report says so instead of inventing an answer. The finding and the
consequence sit in the same report.

**Quoting, not paraphrasing.** Every simulated answer quotes the facts file
verbatim, and the facts file ships alongside so each quote can be checked. The
mission answer quotes the sentence python.org actually publishes; the
participation answer quotes the single word the extractor found, *"Donate"*,
rather than padding it into a sentence the site never wrote.

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
