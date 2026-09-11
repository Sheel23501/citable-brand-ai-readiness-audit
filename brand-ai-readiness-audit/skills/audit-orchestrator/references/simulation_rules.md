# AI-answer simulation, attribution note and narrative: the rules (shared convention)

The orchestrator agent writes exactly three kinds of text into a report:
the simulated answers, the attribution note, and the narrative. Everything
else is produced by scripts. This file is the whole rulebook for those three.
`validate.py --final` enforces the parts that can be checked mechanically;
the rest is the agent's discipline, and a reader can verify it because every
sentence must trace back to something in the report or the facts file.

Related: `report_schema.md` section 3b (`ai_answer_simulation`,
`narrative_summary`), `site_categories.md` section 6 (the questions),
`coverage_map.md` sections 5 and 7 (what the simulation is and is not),
`../../fact-extractability-audit/references/extracted_facts.md` (the facts
file this simulation may read).

---

## 1. What the simulation is

A demonstration of what an assistant could say about the brand if it had
**only this site's own text** in front of it. Not a prediction of what any
real assistant says today: that is non-deterministic, account-bound and
changes daily, and the audit says so in its limitations. The value of the
simulation is that it is reproducible and checkable: anyone can open
`work/extracted_facts.json`, find each quoted excerpt, and see that nothing
else was used.

`compose.py` pre-fills the block. For every question it has already decided
`answerable` (every mapped fact has `status: present`), `facts_used` (the
present facts) and `missing_facts` (the absent or partial ones), and it has
pointed each unanswerable question at the finding that explains it
(`see_finding`). The agent fills in `answer_from_facts` for answerable
questions, and nothing else on a question.

## 2. The facts-only rule

An answer may contain, as its substance, **only the `value` strings of facts
whose `status` is `present` in `work/extracted_facts.json`**, quoted verbatim.

- Quote, do not paraphrase. Put the excerpt in double quotes. The validator
  requires a verbatim run of at least 20 characters of each fact named in
  `facts_used` to appear in the answer (the whole value when it is shorter);
  an answer that only summarises a fact is rejected.
- A value cut with `…` is quoted as far as it goes. Do not complete the
  sentence from memory or from the page.
- Framing words are allowed and expected: "According to the site, …", "The
  pricing page states …", "It describes itself as …". Framing carries no
  facts. If a sentence would still say something about the brand with the
  quotation removed, it has broken the rule.
- Name the page the fact came from when it helps the reader (`page` on the
  fact entry), by role: "the pricing page", "the contact page".
- One to three sentences. Answer the question asked; do not add facts the
  question did not ask for, even if they are present.
- `facts_used` lists every fact quoted and no fact that is not quoted. Compose
  pre-fills it with the facts the question maps to; remove an entry only if
  the answer ends up not quoting it (and then reconsider, because the
  question needed it).

## 3. The forbidden-knowledge rule

Nothing outside the facts file goes into an answer, in any form:

- **Not the agent's own knowledge.** What the model knows or believes about
  the brand, its industry, its competitors, its reputation, its history. If
  the brand is famous, the temptation is strongest and the rule is the same.
- **Not the page snapshots.** `snapshots/*.html` is the site's own HTML, but
  the simulation reads the facts file, not the pages; that is what makes the
  extraction step auditable. If the page says something the facts file
  missed, that is a finding about extraction, not material for an answer.
- **Not anything fetched.** No search, no fetch, no lookup of any kind while
  writing answers. The off-site spot-check (section 6) happens before
  answers are written and feeds a finding, never an answer.
- **Not inference.** "The site does not mention a free trial, so it probably
  has none" is knowledge the file does not hold. Absence is reported as
  absence: the question is unanswerable, `missing_facts` names what is
  absent, and the answer stays `null`.
- **Not correction.** If a quoted value looks wrong, out of date or odd, it
  is quoted as it is. The audit reports facts as present or absent, never as
  correct or incorrect (`coverage_map.md` section 5).

## 4. Question by question

| Question | Rule |
|---|---|
| Q1–Q3 (category questions) | Quote the mapped facts. When two facts are mapped and both are present, quote both, each in its own quotation. |
| Q4 (fit: "Is {brand} a good fit for …?") | Never answer yes or no. Answer **for whom**, quoting the audience fact: "The site says it is built for \"freelance designers and small studios\"; whether that fits depends on the reader." |
| Q5 (comparison: "What sets {brand} apart …?") | Informational only. Answerable only when `differentiator` is present; then quote it. When absent it stays unanswered and is never a finding; the proactive recommendations already suggest stating a differentiator. |
| Any question with `answerable: false` | Leave `answer_from_facts` as `null`. Do not write "not stated" as the answer; the null and `missing_facts` say that, and the Markdown renders it. `see_finding` already points at the finding that explains the gap. |
| A fact with `status: partial` | Counts as missing (compose has already put it in `missing_facts`). Do not quote a partial hint as if it answered the question. |

## 5. The attribution note

`ai_answer_simulation.attribution_note`: one or two sentences on whether an
assistant that used these facts would have a reason to **name this brand**
as the source. This is the one place the report speaks to
mention-without-citation, which happens inside generation and cannot be
observed from the site (`coverage_map.md` section 7).

Base it only on what is in the report and the facts file:

- Do the quoted values themselves carry the brand name (`brand_name.value`
  appears inside the `what_it_does` or equivalent value)? A fact that reads
  "Ledgerly helps freelance designers …" travels with its name; "We help
  freelance designers …" does not.
- Is the name anchored (`ef.entity.*` checks passed: consistent name,
  `sameAs`, a resolved entity) or not (those findings exist)?
- Is there a corroboration surface (`ef.corroboration.*`)?

Say which of those hold, in plain words, and stop. Do not predict citation
rates. Example: "Three of the four quoted facts carry the name Ledgerly
inside the text itself, and the Organization node is anchored with sameAs,
so an assistant quoting these lines has the name in hand; the missing press
surface (F-006) means there is little else on the web to credit."

When no question was answerable, say so: "No fact could be quoted, so there
is nothing an assistant could attribute."

## 6. Ordering with the off-site spot-check

The spot-check (`../../entity-freshness-corroboration-audit/references/offsite_spotcheck.md`)
re-runs the entity probe and then compose, and compose **rewrites
`report.json`**. Run it before writing any answer. Answers, the attribution
note and the narrative are the last things written, and `finalize.py` writes
them without recomposing.

## 7. The narrative

`narrative_summary`: three to six sentences, for a reader who will not open
the findings. It is the only free prose in the report, and it is held to
the same standard as everything else: **every sentence traces to a finding
id, a passed check, a coverage line or the simulation.**

Structure, in this order, skipping a group that has nothing in it:

1. **Invisible** (findings with `round2_mode: invisible`: access, render,
   extract). Can an assistant reach, read and extract? Name the worst
   finding by id.
2. **Stale or mistrusted** (`round2_mode: stale`: entity, freshness,
   corroboration). Can it tell which brand this is, and is there reason to
   trust and prefer these pages? Include what the simulation showed: how many
   questions were answerable, and which were not.
3. **Bouncing** (`round2_mode: bouncing`: engagement). Once a visitor
   arrives, do they stay? Name the worst finding by id.
4. **One closing sentence** on what to do first: the quick wins by id if
   there are any, otherwise `summary.start_with` (compose has already chosen
   it by rule; do not pick a different finding).

Rules:

- Use the three Round-2 words (invisible, stale, bouncing) so the reader can
  map the narrative to the handout's framing.
- Counts come from `summary`; ids from `findings`; nothing is invented. Do
  not mention a check, a page or a fact that the report does not contain.
- A clean site gets a positive narrative that says what was verified
  (`passed_checks` count, the stages evaluated) and names the recommendations
  as opportunities, not problems.
- If `or.run.probe_error` is present, say the run was incomplete and which
  checks have no verdict, in the first sentence. An incomplete run must never
  read as a clean one.
- No advice that is not in a `suggested_action`; no severity words beyond
  those in the findings; no promises ("this will make the brand visible").
- Plain language. A non-expert should understand every sentence without the
  glossary.

## 8. What the validator checks, and what it cannot

`validate.py --final` rejects: a non-empty answer on an unanswerable
question; a `facts_used` entry that is not present in the facts file; an
answer that contains no verbatim run of a fact it names; an answerable
question left unanswered; an empty narrative; a `see_finding` that names no
finding. It warns on a narrative outside three to six sentences and an empty
attribution note.

It cannot check that framing words carry no facts, that the narrative
traces to the report, or that nothing was fetched. Those are the agent's
discipline, and they are why the answers quote rather than summarise: a
reader who opens the facts file can verify every claim in under a minute.
