---
name: engagement-audit
description: Checks whether a visitor who arrives at a website, often mid-journey from an AI answer, can orient, understand the offer, and continue. Detects a missing or unclear first-viewport value proposition, no identifiable primary call to action, missing navigation landmarks, broken sampled links, missing mobile viewport, heavy page weight (a static proxy), missing trust signals, weak landing-page continuity (H1 versus title and description), missing breadcrumbs, related links, or site search, blocking interstitials, missing lang attribute, and soft or unhelpful 404 behaviour. Use when diagnosing why visitors bounce, or as the on-site engagement stage of a brand AI-readiness audit.
license: MIT
compatibility: Requires Python 3.8+ (standard library only). With --url it makes read-only GET requests under the shared fetch policy and respects robots.txt. Beyond the sampled pages it spends at most 15 internal-link requests and one request for a deliberately non-existent path; --no-network or --offline skips both. Reads served HTML only; never renders or measures load time.
metadata:
  marketplace: brand-ai-readiness-audit
  concern: on-site-engagement
allowed-tools: Bash(python3:*) Read
---

# Engagement Audit

## When to use

Use when you need to know whether a human visitor who has already arrived,
usually on an inner page an assistant's answer linked to, will stay: can they
tell where they are and what is offered, is there something to do next, and
does the page get in the way. This is the second half of the brief and shares
almost no logic with the discoverability skills: a page can be perfectly
readable to a crawler and still lose every visitor in the first screen. Run it
after the crawl-render skill, which decides which pages have any content at all.

## Inputs

One of:

- `--url <site>`: a URL or bare domain. The script samples the site itself
  (home plus up to five role pages) and writes a workdir.
- `--workdir <dir>`: a workdir produced by the orchestrator or by
  `audit-orchestrator/scripts/sample_site.py`, containing `sample.json` and
  `snapshots/`. Site pages are not fetched again; only the link sample and the
  404 probe make requests.

Optional: `--out <file>` to write the JSON to a file, `--category <id>` to
override the inferred site category (this changes which checks apply, the
call-to-action vocabulary and the expected trust signals), `--no-network` (or
`BRAND_AUDIT_NETWORK=0`) to skip the link sample and the 404 probe, `--offline`
to prove the degraded path.

## Procedure

1. Run the probe. From the marketplace root:

   ```
   python3 skills/engagement-audit/scripts/engagement_probe.py --url https://example.com --workdir audit-example
   ```

   or, when the orchestrator has already sampled the site:

   ```
   python3 skills/engagement-audit/scripts/engagement_probe.py --workdir audit-example --out audit-example/probes/engagement-audit.json
   ```

2. Read the `error` field first. `null` means every check group ran (`hero`,
   `cta`, `landmark`, `search`, `breadcrumbs`, `related`, `trust`,
   `continuity`, `interstitial`, `viewport`, `lang`, `weight`, `links`,
   `errors`). A non-null value names the group that failed internally; its
   checks are `not_evaluated` with reason `dependency_failed`, the other groups
   are still valid, and the engagement file is still written.

3. Read `site_category` and `pages_examined`. The category decides which
   checks apply, which are capped at low, the call-to-action vocabulary and the
   expected trust signals (`references/checks.md`, "Category applicability").
   `pages_examined` lists the usable pages. Pages excluded because of
   robots.txt, a bot-protection challenge, an HTTP error, a non-HTML response,
   or a JavaScript gate or client-rendered shell are listed in
   `work/engagement.json` under `pages_excluded` with a reason; the crawl-render
   skill owns those findings. Head-level checks (viewport, lang, page weight)
   still run on gates and shells, because their `<head>` is real.

4. Read `checks`. Every one of the 16 `en.*` checks appears with a status.
   `pass` needs no action. `not_evaluated` and `inconclusive` carry a
   `reason` and mean the audit could not see, not that the site is fine:
   - page reasons: `robots_disallow`, `challenge_page`, `no_rendered_content`,
     `non_html`, `http_error`, `no_html_pages`, `network_disabled`;
   - scope reasons: `not_applicable_for_category`, `no_key_pages_usable`,
     `only_home_sampled`, `no_product_or_blog_page`, `listing_pages_only`,
     `no_anchor_pages_usable`, `no_internal_links`;
   - probe reasons: `soft_404` (no 404 page exists to grade),
     `fetch_error`, `unexpected_status`, `fetcher_blocked` (the
     `inconclusive` cluster note), `dependency_failed`, `context_error`.

5. Read `findings` in order. Each has `severity`, `confidence`, `evidence`
   (one or two sentences), `evidence_items` (the verbatim proof: the heading
   and lead text seen, the link texts in the first viewport, the overlay's
   opening tag, each broken link's status, the 404 probe's response),
   `why_it_matters`, and a `suggested_action` with `summary`, `detail`,
   `impact`, `effort`, `priority`. Read `confidence` before `severity`: the
   first-viewport, interstitial and page-weight checks are proxies on served
   markup and say so. A single info note on `en.links.broken_sampled` is normal
   on a run without network access. Do not restate a finding without its
   evidence.

6. Open `work/engagement.json` (path in `artifacts.engagement`). It holds what
   every check saw: the lead text, the call-to-action hits per page, the trust
   signals found and missing, every sampled link with its status, and the 404
   probe's response. Any statement about the visitor's experience of the site
   must come from it. `references/engagement_file.md` defines every field.

7. Apply the interpretation rules in `references/checks.md` when explaining a
   finding, and the non-findings in `references/non_findings.md` before adding
   anything the script did not flag: a one-page site is not disoriented, a
   search form is not a call to action, a listing page needs no related links,
   a 403 cluster is not broken links, page weight is a count and not a timing.
   Never add a finding the script did not produce; if you believe one is
   missing (an icon-only button, a non-English label), report the gap as a
   limitation.

8. Hand the JSON to the orchestrator unchanged. It owns IDs, dedupe, and
   counts (dedupe rows 4, 9 and 10 in `coverage_map.md` fold engagement
   findings under their root causes). When used standalone, present the
   findings grouped by severity with their evidence and actions, then the link
   sample and 404 probe result, then the non-pass checks with their reasons.

## Output

The probe output object defined in the shared conventions
(`../audit-orchestrator/references/report_schema.md`, section 1): a `checks`
list with every check's status, plus `findings` for failures only. Check ids,
default severities and pass conditions are the `en.*` rows of
`../audit-orchestrator/references/check_ids.md`. Severity and confidence follow
`../audit-orchestrator/references/severity_confidence_rubric.md`; category
gating and caps follow `../audit-orchestrator/references/site_categories.md`
section 4; all network access, including the link sample and the 404 probe,
follows `../audit-orchestrator/references/fetch_policy.md`.

Also writes `work/engagement.json` (path in `artifacts.engagement`).
`en.links.blocked_cluster` is `info` and never affects counts; the reliability
checks are `not_evaluated` with reason `network_disabled` when the network is
off.

## References

- `references/checks.md`: what each of the 16 checks detects, the exact rule,
  the category applicability table, the call-to-action and trust-signal
  vocabularies, the evidence recorded, and why the severity and confidence are
  what they are.
- `references/non_findings.md`: conditions this skill deliberately does not
  flag (a one-page site, a search form, a listing page, a 403 cluster, a
  hidden dialog, …), and what a non-rendering, English-first audit cannot know.
- `references/engagement_file.md`: `work/engagement.json` field by field, with
  a worked example.
