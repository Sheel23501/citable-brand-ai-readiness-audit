# Severity, confidence, effort and quick-win rubric (shared convention)

Every finding's `severity`, `confidence`, and `effort` is chosen by these rules
and only these rules. A probe that needs a value not covered here adds a row to
this file rather than deciding locally. The registry in `check_ids.md` records
each check's default severity and confidence; a probe may only move away from
the default using the adjustment rules in section 3.

---

## 1. Severity

Severity answers: **if this is the only problem, how much of the mechanism is
lost, and on how much of the site?**

| Level | Definition | Typical triggers |
|---|---|---|
| `critical` | The mechanism fails completely for the whole site, or for the home page in a way that nothing downstream can recover from. An assistant gets nothing usable. | `User-agent: *` + `Disallow: /`; every live-answer bot disallowed on `/`; JS gate or client-rendered shell on the home page; home URL returns a non-HTML document; home returns 5xx on retry. |
| `high` | A key page or key fact is unreachable or unextractable, or a whole mechanism fails on a key page. The assistant can find the brand but will answer a core question wrongly or not at all. | A live-answer or index bot disallowed on `/`; noindex on a key page; CSR shell on a non-home key page; a category-required key fact missing in plain text; pricing present only as an image; NAP missing for a local business. |
| `medium` | The mechanism works but the answer will be lower quality, less confident, or less trusted. Facts are recoverable with effort. | Malformed JSON-LD; missing required JSON-LD properties; key page disallowed for a live-answer bot; no `sameAs` on Organization; missing viewport; no identifiable CTA; broken sampled links; unclear hero; soft 404. |
| `low` | Hygiene. Marginal effect on either axis, or affects only secondary pages. | Missing meta description; missing Open Graph; stale copyright year; missing breadcrumbs where expected; missing `lang`; missing sitemap; missing alt text on non-decorative images. |
| `info` | Not a defect. Something the reader should know: an inconclusive check, a not-evaluated check, a policy choice, or an informational observation. Never counted as a problem in the narrative. | Challenge page served to the fetcher; training-only bot blocked; off-site spot-check result; a check skipped because the network was disabled. |

Key page = home, plus any sampled page whose role is in the category's
`key_pages` list in `site_categories.md`. Key fact = an entry in the category's
`key_facts` list.

Hard rules:

- `status` = `inconclusive` or `not_evaluated` ⇒ `severity` = `info`, always.
- Blocking a training-only bot is `info`, never higher. It is a legitimate policy decision (see `bot_tiers.md`).
- A finding may be raised to `critical` only for the home page or for site-level configuration. Nothing page-specific on a non-home page is `critical`.
- Positive observations are not findings. They go in `checks` with `status: pass`.

---

## 2. Confidence

Confidence answers: **how directly does the evidence prove the claim?**

| Level | Definition | Examples |
|---|---|---|
| `high` | Deterministic. A machine reading the same bytes would reach the same conclusion. | An HTTP status code; a robots.txt rule matched per RFC 9309; a JSON parse error; an absent `<meta name="viewport">`; a `noindex` directive; an absent `sameAs` property. |
| `medium` | Heuristic, but at least two independent signals agree (the two-signal rule), or a full deterministic check on a sample rather than the whole site. | CSR shell = low visible-text word count **and** a known framework root with empty container; link health on a 15-link sample; a key fact judged missing by keyword patterns **and** absence of a matching JSON-LD property. |
| `low` | A single heuristic signal, or a proxy for something not directly measured. | Page weight proxy (total referenced asset bytes, not measured load time); "image-only pricing" inferred from an `<img>` whose alt or filename contains price words with no price text nearby; hero clarity by word-count heuristics alone. |

Hard rules:

- Proxy checks are capped at `medium`, and are `low` unless a second signal corroborates.
- Any check that relied on a truncated body (byte cap hit) drops one level.
- Any check whose evidence comes from a page where a challenge fingerprint matched is not `low`; it is `inconclusive` and the finding becomes `info`.

---

## 3. Adjustment rules (the only permitted deviations from registry defaults)

Apply in this order.

1. **Category gating.** If `site_categories.md` marks the check `not_applicable` for the inferred category, the check is `not_evaluated` with reason `not_applicable_for_category` and emits no finding.
2. **Proportion, where a check counts things.** `fx.facts.key_fact_missing` reports `medium` when exactly
   one of the category's key facts is missing and `high` when two or more are. A rule that returns the same
   severity whether one fact or every fact is absent stops carrying information; measured across 38 real
   sites the unscaled rule fired `high` on 47% of them.
3. **Page role.** Home page or key page ⇒ default severity. Non-key sampled page ⇒ one level lower (never below `low`).
3. **Blast radius.** The same `fail` on every sampled page (≥ 3 pages) ⇒ one level higher, up to the check's registered maximum.
4. **Confidence cap.** `confidence: low` ⇒ severity at most `medium`.
5. **Category overrides** listed in `site_categories.md` (for example NAP missing is `high` for `local_business`, `medium` otherwise) replace the default before steps 2–4 run.
6. **Absence scope** (orchestrator only, `compose.apply_absence_gate`). A site-level absence claim is
   scoped to the pages actually read. When no page that could have carried the thing was reached, for a
   role the category expects (`site_categories.md` section 1), the check is `not_evaluated` with reason
   `role_page_not_sampled`, emits no finding, and coverage plus a `limitations` line carry it. When some
   were reached, the finding stands at `confidence: low`, severity at most `medium`, `absence_scope: sample`,
   and its evidence names the pages not reached. `fx.facts.key_fact_missing` is scoped one fact at a time
   (`site_categories.md` section 1b, `categories.py` `FACT_ROLES`): a fact is confirmed missing only when
   every page it would live on was read, and rule 2 is re-applied to the confirmed count.
   `ef.corroboration.press_page_missing` is `not_evaluated` with reason `navigation_not_readable` when the
   sample was too thin to have shown the navigation (three or fewer internal links on home, or at most one
   role page reached). Presence findings and per-page findings are never gated; a role the category does
   not expect is never "unreached".
7. **Language scope** (orchestrator only, `compose.apply_language_gate`). A finding whose verdict rests on
   English phrase lists (`compose.LANG_DEPENDENT`), on a site whose sampled pages are written in a language
   that check has no vocabulary for, stands at `confidence: low`, severity at most `medium`,
   `language_scope: <lang>`, and a `limitations` line names the checks.

A probe records which adjustments fired in a `computed` evidence item, e.g.
`adjustments=blast_radius:+1,confidence_cap:medium`. Rules 6 and 7 run in compose, after the probes,
and record theirs as `absence_scope=sample; ...` and `language_scope` on the finding.

---

## 4. Effort

Effort answers: **what does the site owner have to do?**

| Level | Definition | Examples |
|---|---|---|
| `low` | Configuration or copy change. Hours, no engineering ticket. | Edit robots.txt; add a `<meta>` tag; fix a JSON-LD typo; add `sameAs` URLs; add `lang`; add a visible address line. |
| `medium` | Content or template work. Days. Needs a content owner or front-end developer. | Write an FAQ page; add a pricing table as HTML; add breadcrumbs to a template; publish a press page; replace image-only content with text. |
| `high` | Architectural. Weeks. | Move to server-side or pre-rendering; remove a JavaScript entry gate; change WAF challenge behaviour for verified bots; re-platform. |
| `n/a` | Only for `info` findings. | |

---

## 5. Quick win

A finding is a `quick_win` when **all** hold:

- `severity` ∈ {`critical`, `high`, `medium`}
- `effort` = `low`
- `confidence` ≠ `low`
- `status` = `fail`

Compose lists quick wins in rank order. Nothing else may be labelled a quick win.

**Where to start.** The rule above is strict on purpose, so a report can carry
defects and no quick win: a `medium` at `low` confidence, or a certain `low`,
qualifies for neither. The report still names a first move.
`summary.start_with` is the first quick win when there is one; otherwise the
finding above `info` with the highest `suggested_action.priority` (priority
already folds severity and confidence, so a certain medium outranks a guessed
high), then the lowest `effort`, then the highest `confidence`, then rank. It
is `null` only when nothing is above `info`. `summary.headline` states it in
one sentence, and the Markdown's Quick wins section names it whenever it is
set. Neither loosens the quick-win rule; the validator recomputes `start_with`.

---

## 6. Wording rules that follow from the rubric

- `title` states a fact about the site, not an instruction ("Pricing exists only as an image", not "Add text pricing").
- `why_it_matters` names the mechanism consequence in one plain sentence, optionally a second on the engagement consequence.
- `suggested_action.summary` starts with a verb and names the page or element; `suggested_action.detail` says how and includes a cheap verification step where one exists; `suggested_action.impact` is derived from severity (critical/high → high, medium → medium, low/info → low); `priority` equals impact, lowered one level when confidence is `low`. Neither is ever set by hand.
- `evidence` (the sentence) is generated from `evidence_items` and states counts when sampled; it never asserts more than the items show.
- `info` findings that report `inconclusive` or `not_evaluated` say what was not checked and why, and what the user can do to make it checkable (for example, allow the audit user agent through the WAF, or re-run with network access).
