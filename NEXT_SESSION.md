# Handoff: what this is, how to work on it, what to fix next

Written 2026-09-12, after the session that took the submission from 6.6 to 8.2.
Read this first, then `CONTEXT.md` (long-form background) and
`brand-ai-readiness-audit/CONTRIBUTING.md` (test loop and traps).

---

## 1. What the project is

**Adobe University Hackathon 2026, Round 3 final.** Deliverable: an **Agent Skill
Marketplace** — a zip holding `marketplace.json`, `README.md` and five
agentskills.io skill folders, exactly one of which is the entrypoint. Pointed at
any website it audits two halves and emits one report plus prioritised actions:

- **Off-site discoverability** — why AI assistants do not find or cite the brand.
- **On-site engagement** — why visitors who arrive do not stay.

Judged on six criteria: detection accuracy (few false positives),
suggested-action quality, output design, skill-format and engineering hygiene,
marketplace composition (genuine separation of concerns), and generalization to
unseen sites. **Judges read the skill source, not one report.**

Hard rules: recommend-only, no destructive or authenticated actions, respect
robots.txt, portable self-contained manifest, zip <= 50 MB, runtime < 5 minutes.

**Layout:** `brand-ai-readiness-audit/` is the marketplace root.
`skills/audit-orchestrator/` is the entrypoint and holds the shared library
(`scripts/auditlib/`), the check registry
(`references/check_ids.md`, 61 checks) and `scripts/compose.py`, which merges
probe output into the report. The other four skills are probes:
`crawl-render-audit` (`cr.*`), `fact-extractability-audit` (`fx.*`),
`entity-freshness-corroboration-audit` (`ef.*`), `engagement-audit` (`en.*`).

## 2. Where it stands

- **Commit `3a933b7`**, pushed to `origin/main`, working tree clean.
- **Zip** `brand-ai-readiness-audit.zip` is byte-identical to that commit
  (279 files, 0.73 MB). It is gitignored on purpose; rebuild with
  `git archive --format=zip -o brand-ai-readiness-audit.zip HEAD brand-ai-readiness-audit`.
- **Tests: 4,752 assertions, 0 failures, 29 fixture sites.**
- **Score 8.2/10** from a three-judge panel (product 8.3, engineer 8.5, rubric
  auditor 8.0). Best: hygiene 9.0, composition 9.0. Worst: detection accuracy
  7.7, generalization 7.7.

## 3. How to work on it

**The test loop** (from `CONTRIBUTING.md`, all of it earned the hard way):

```bash
python3 tests/run_tests.py --stage manifest --stage extract --stage htmldoc --stage robots   # ~2s, use constantly
python3 tests/run_tests.py --stage probe_en --stage compose --stage validate                 # minutes, the stage you touched
python3 tests/run_tests.py                                                                   # ~12 min, before every push
```

**Traps that cost this session hours:**

1. **Never edit files while the suite runs.** Later stages re-read from disk and
   spawn subprocesses; a mid-run edit produces dozens of fake failures
   (`AttributeError: module has no attribute ...`).
2. **Read the `EXIT=` line the runner writes, not the shell's status.** Piping
   through `tail` reports `tail`'s success.
3. **Run on an idle machine.** Timing assertions fail under load: one fixture
   measured 77.9s busy and 7.0s idle. A `TimeoutExpired` with a *negative*
   timeout means the machine slept mid-run — rerun, do not debug.
4. **Behaviour changes break tests that encode the old behaviour.** That is
   correct and expected; update the assertion to the new contract rather than
   softening the code.
5. **Push only when the suite is green** (the user's standing rule). Commit
   locally as often as useful.

**Verify a fix on the real site, not only fixtures:**

```bash
python3 skills/audit-orchestrator/scripts/run_audit.py --url https://www.iiitd.ac.in/ --workdir /tmp/run
python3 skills/audit-orchestrator/scripts/validate.py --workdir /tmp/run --final
```

`www.iiitd.ac.in` resolves to a private address on the user's campus network, so
that one needs `BRAND_AUDIT_ALLOW_PRIVATE=1` — the SSRF guard working, not a bug.

## 4. What to fix, in order

All four were named by two or three independent judges. Est. gain to ~9.0.

### 4.1 The answer simulation quotes navigation menus as answers
**Worst defect. 4 of 6 live reports show it.** python.org answers "How do I
donate, apply, or join?" with `"…The Python Network Donate ≡ Menu Search This
Site GO A A Smaller Larger Reset…"`, and marks the question **answerable**. Same
on iiitd, lemonde, sipgate.
**Cause:** the fact extractor captures a window of nav chrome as a fact value,
and `compose.answer_from_facts` quotes whatever the fact holds.
**Fix:** require a fact excerpt to be sentence-shaped before a question may be
`answerable` — a verb, a minimum run without list separators (`|`, `≡`, `;`), and
not drawn from a `nav`/`header` context. Otherwise mark it unanswerable with
`missing_facts`, which the report already renders honestly.
**Files:** `skills/audit-orchestrator/scripts/compose.py` (`answer_from_facts`,
`build_simulation`), `skills/audit-orchestrator/scripts/auditlib/extract.py`
(the `how_to_participate` / `programs_or_services` detectors).

### 4.2 A transport failure is reported as the site's broken link
python.org F-002: "1 of 15 sampled internal links is broken:
`https://www.python.org/downloads/ios/` -> tls_error". That URL returns **200**.
**Cause:** `skills/engagement-audit/scripts/engagement_probe.py:59` lumps
`tls_error`, `read_timeout`, `connect_timeout`, `dns_failure` in with 404/410,
with no retry.
**Fix:** retry once, then classify transport errors as `inconclusive` with reason
`fetcher_error`, or fold them into the existing `blocked_cluster` info finding.
The crawl probe already does exactly this for `cr.access.edge_block` — copy that
rule so the same signal is not `inconclusive` in one probe and a confident defect
in another.

### 4.3 The call-to-action window misses the main navigation
iiitd F-001 says "no call to action" while `<a>Admission</a>` sits at 17.9–42.8%
of the markup (measurements differ by page) and `admission` is already in
`CTA_VOCAB["nonprofit_institution"]`. The **vocabulary** was fixed; the
**position proxy** was not.
**Fix:** treat a link whose `context` is `header` or `nav` as first-viewport
whatever its markup position, in `cta_hits`
(`skills/engagement-audit/scripts/engagement_probe.py`). `FIRST_VIEWPORT_FRAC`
stays for body links.

### 4.4 Language-gated checks still fail non-English sites
`compose.py` (`apply_language_gate`, `LANG_DEPENDENT`) lowers confidence and adds
a caveat but keeps the `fail`. So elpais and lemonde fail
`en.trust.signals_missing` on English-only "terms/privacy" strings, though their
footers say *Aviso legal* and *Mentions légales*.
**Fix:** make every `LANG_DEPENDENT` check `not_evaluated` with reason
`language_not_supported` when the page language's vocabulary is not carried —
`en.cta.missing` already behaves this way
(`engagement_probe.py`, `check_cta`). Better still, add the legal-page vocabulary
per language (Impressum, Mentions légales, Aviso legal, Informativa privacy).

### 4.5 Smaller, if time allows
- **`examples/` is stale** (Sep 8, pre-absence-gate) and contains a retired fake
  address, "Ledgerly Software Ltd · 12 Harbour Street, Bristol", in a report
  about a US foundation. Regenerate with current code.
- **Evidence counts disagree with evidence items**: sipgate F-001 says "5 JSON-LD
  nodes" and lists 4 (capped at `[:4]` in `facts_probe.py`). Say "showing 4 of 5".
- **JS-nav sites collapse to 2 pages** (adobe.com). When the home page's nav is
  script-rendered, drive role discovery from the sitemap and footer links.
- **`ef.entity.nap_missing_plain_text` and `fx.facts.key_fact_missing`** report
  the same missing address twice on python.org; add the pair to the dedupe table
  in `coverage_map.md`.

## 5. What is already fixed — do not redo

Absence gate, language gate, render gate (JS-built chrome), sitemap ordering,
multilingual phone/address grammars, Wikipedia language editions, SSRF guard,
nested JSON-LD organisations (`extract.find_org_node`), hidden headings
(`htmldoc.visible_h1s`), and reports that finish in the script — `validate.py
--final` returns 0 problems on all six live reports, where it used to fail every
one with 3.
