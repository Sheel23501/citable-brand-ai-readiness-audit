# entity-freshness-corroboration-audit: explicit non-findings and limits

Things this skill sees and deliberately does **not** flag. Each is a real
pattern on production sites that a naive checker misreports. Stating them is
part of the detection-accuracy contract: few false positives, and no finding
that tells a business to change a legitimate choice.

| Condition | Why it is not a finding | What the report says instead |
|---|---|---|
| **The brand name is a common word** (Apple, Notion, Mint, Stripe) | Ambiguity is never judged from the name itself. A dictionary-word heuristic misfires on most strong brands and would be a false-positive source of its own. | Nothing from the name alone. The audit checks `sameAs` deterministically and does one lookup; only an observed collision or disambiguation page, with the site publishing no anchor, becomes `ef.entity.wikidata_ambiguous`. |
| **A namesake is more famous** (the Wikipedia article under the name is about something else) and the site publishes a matching `sameAs` | The site has already said which entity it is. | Lookup outcome `verified` through the anchor; nothing. |
| **`sameAs` lists only social profiles** | The property exists and corroborates; social links are worth keeping. | `ef.entity.sameas_no_authority` at low, never medium. The action adds an authoritative target and keeps the social links. |
| **A person's `sameAs` points to LinkedIn, GitHub, Behance, Instagram, …** | For `portfolio_personal` a professional profile is the authority; people rarely have register entries or Wikidata items. | `ef.entity.sameas_no_authority` passes. |
| **No Organization JSON-LD at all** | The missing markup is one defect, owned by the fact-extractability skill; grading its consequences again would double-count it. | `ef.entity.sameas_missing` and `ef.entity.sameas_no_authority` are `not_evaluated` with reason `dependency_failed`; `fx.jsonld.missing` / `fx.jsonld.no_organization` carry the finding (dedupe row 6). |
| **No Wikipedia article under the brand's exact name** (discover mode) | A title lookup is not a search; the article may exist under another title, and most businesses have none. | `ef.entity.wikidata_not_found` at low severity **and** low confidence, worded as "no article under that title". The action is a Wikidata item, never "get a Wikipedia article". |
| **The lookup could not run** (offline, `--no-external`, robots.txt of the lookup host, timeout) | Nothing about the site is proven. | `ef.entity.wikidata_unavailable`, info, saying what was not checked and how to re-run. |
| **Brand name derivable only from the host label** | A guessed name is not evidence that the site fails to state its name. | The name component is dropped from the NAP requirement; only address and phone are graded, and the `computed` item shows the reduced `required=`. |
| **Address and phone present only in JSON-LD** on a non-local site | The identity facts exist for machines; only the visible-text cross-check is weaker. | `ef.entity.nap_missing_plain_text` fires at the category's severity (low for saas, publisher, portfolio; medium otherwise), with the evidence saying structured data may carry them. On local sites the JSON-LD address still satisfies the key-fact check; compose folds the overlap (dedupe row 8). |
| **A software product, publication or personal site without a street address** | Not every entity has a shopfront. | Category override: low. The action asks for a footer line, not a storefront. |
| **Names that differ by case, punctuation, or a legal suffix** ("Ledgerly", "LEDGERLY", "Ledgerly Software Ltd") | The same name to any reader and any machine. | Normalised before comparison; `ef.entity.name_inconsistent` passes. |
| **A brand name and a longer name that contains it** ("Ledgerly" beside "Ledgerly Invoicing") | A product line marketed under the brand is normal. | Substring containment counts as agreement; nothing. |
| **Undated evergreen pages** (about, pricing, contact) when another sampled page shows a date | The check is site-level: any readable date on any sampled page passes it. | `ef.freshness.no_visible_dates` passes. |
| **A copyright year one year behind** | Sites are commonly updated in January; one year is not staleness. | Nothing. The threshold is two full years. |
| **A copyright range** ("2015–2026") | The later year is current. | The later year of a range counts; nothing. |
| **An old copyright year on one page while another page shows a current one** | A single stale template fragment, not an abandoned site. | Nothing. The check fails only when no page shows a current year. |
| **JSON-LD `dateModified` within 30 days of the visible date** | Normal drift between a CMS timestamp and a displayed date. | Nothing. |
| **JSON-LD dates on a page that shows no visible date** | There is nothing to compare against. | Not graded, except a date in the future. |
| **No JSON-LD dates anywhere** | Absence of a recommended property is not a defect here. | Nothing from `ef.freshness.date_modified_mismatch`; the orchestrator may list `dateModified` among proactive recommendations. |
| **A blog instead of a newsroom** | Dated posts are a corroboration surface. | The blog role, any press/news/blog link, or an advertised feed passes `ef.corroboration.press_page_missing`. |
| **A `mailto:press@` link but no press page** | An address is not a surface others can cite. | `ef.corroboration.press_page_missing` still fires at low; the action creates the page. |
| **No press page on a personal site or a walk-in business** | Nobody expects a newsroom from a photographer or a bakery. | `not_evaluated`, reason `not_applicable_for_category`. |
| **Zero off-site mentions in the spot-check** | A handful of searches cannot prove absence. | `ef.corroboration.offsite_spotcheck` reports zero mentions as `inconclusive`, info; never a defect and never counted. |
| **No search tool in the session** | The off-site check is an agent step and cannot run without one. | `ef.corroboration.offsite_spotcheck` `not_evaluated`, reason `tool_unavailable`, with the suggested queries for whoever runs it next. |
| **Pages that are a JavaScript gate or client-rendered shell** | There is no text to grade; one finding should say so. | Excluded with reason `no_rendered_content`; `cr.render.js_gate` / `cr.render.csr_shell` own the finding. |

## What one lookup and six pages cannot know

- **The lookup is a title lookup on English Wikipedia, not a search.** A
  brand whose article sits under another title reads as `not_found` (low
  confidence, low severity). A brand with an article on another language
  edition only is not seen. The Wikidata search API is never called: the
  only Wikidata document the audit may request is the EntityData record for
  a Q-id the site itself published.
- **A `collision` can be a legitimately more famous namesake.** The finding
  reports what an assistant would find under the name and asks the site to
  publish anchors; it does not judge the name.
- **Phone and address recognition is pattern-based.** A bare number without
  `+` or a cue word ("0117 496 0123" on its own line) is not recognised as a
  phone; an address without a street word from the English, German, French,
  Spanish or Italian lists, or without a UK postcode or US ZIP, is not
  recognised. Both must be missed before `ef.entity.nap_missing_plain_text`
  fires on a non-local site, and the evidence names the pages searched so
  the owner can point to the line that has it.
- **Dates are read in ISO and English written forms.** Numeric `07/09/2026`
  and non-English month names are not parsed; this is why
  `ef.freshness.no_visible_dates` is medium confidence.
- **Only sampled pages are read.** Home plus up to five role pages. An
  Organization node, a press link or a dated page outside the sample is
  invisible; every finding lists the pages it applies to.
- **One point in time.** The lookup result is cached for the run; the
  copyright and date checks use the current date at run time.
- **Nothing is inferred from memory.** If the lookup says `not_found`, the
  report says the audit found no article under that title, even if the
  reader believes one exists. The entity file records exactly what was
  fetched and decided.
