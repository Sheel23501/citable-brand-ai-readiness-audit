#!/usr/bin/env python3
"""crawl-render-audit probe: can a non-JavaScript fetcher reach and read this site?

    python3 crawl_probe.py --workdir audit-example            # orchestrator mode: reads sample.json + snapshots
    python3 crawl_probe.py --url https://example.com          # standalone: samples the site first (writes a workdir)
    python3 crawl_probe.py --url https://example.com --workdir out --out out/probes/crawl-render-audit.json

Emits the probe output object (report_schema.md section 1) with every `cr.*`
check from check_ids.md and findings for failures. Standard library only.
Never raises; internal errors are reported in the `error` field.
"""
import argparse
import json
import os
import re
import sys
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "audit-orchestrator", "scripts")))
from auditlib.context import AuditContext  # noqa: E402
from auditlib.findings import ProbeOutput, Registry, evidence_item, validate_probe_output  # noqa: E402
from auditlib.fetch import registrable_domain, normalize_url, PROBE_USER_AGENTS  # noqa: E402
from auditlib.robots import load_bot_tiers, grade_tokens  # noqa: E402
from auditlib.categories import is_key_page  # noqa: E402
from auditlib.render import THIN_WORDS, js_gate_signals, csr_signals  # noqa: E402
from auditlib.cli import probe_main  # noqa: E402

PROBE = "crawl-render-audit"
REFS = {
    "robots": "https://www.rfc-editor.org/rfc/rfc9309",
    "jsseo": "https://developers.google.com/search/docs/crawling-indexing/javascript-seo-basics",
    "sitemaps": "https://www.sitemaps.org/protocol.html",
    "robots_meta": "https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag",
    "canonical": "https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls",
}


def _rule_text(rob, path, token):
    r = rob.matching_rule(path, token)
    return r or "(no matching rule)"


def _norm_path(url):
    s = urlsplit(url)
    host = (s.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (s.path or "/").lower().rstrip("/") or "/"
    return host, path


# ---------------------------------------------------------------- robots checks
def check_robots(ctx, out):
    rob = ctx.robots
    tiers = load_bot_tiers()
    if rob.state == "unreachable":
        out.inconclusive("cr.robots.unreachable", reason="robots_unreachable",
                         title="robots.txt could not be read, so crawler permissions are unknown",
                         evidence="robots.txt fetch did not return a readable file (%s)." % ("; ".join(rob.parse_errors) or "5xx, timeout or challenge"),
                         evidence_items=[evidence_item("robots.txt", "http_status", rob.url or "robots.txt", note="5xx, timeout or challenge page")],
                         why="Without robots.txt the audit cannot tell which assistants are allowed in; most crawlers treat an unreachable robots.txt as a temporary stop.",
                         action="Make /robots.txt return 200 with a plain-text body (or 404 if you have no rules).",
                         detail="Check the origin server and any WAF for /robots.txt. Verify with curl -I /robots.txt that the status is 200 or 404, not 5xx or a challenge.")
        for cid in ("cr.robots.blanket_disallow", "cr.robots.live_answer_bot_blocked", "cr.robots.index_bot_blocked",
                    "cr.robots.training_bot_blocked", "cr.robots.key_page_disallowed"):
            out.not_evaluated(cid, reason="robots_unreachable")
        return
    out.check("cr.robots.unreachable", "pass")
    if rob.state == "missing":
        for cid in ("cr.robots.blanket_disallow", "cr.robots.live_answer_bot_blocked", "cr.robots.index_bot_blocked",
                    "cr.robots.training_bot_blocked", "cr.robots.key_page_disallowed"):
            out.check(cid, "pass")
        return
    key_paths = []
    for p in ctx.pages:
        if p.role != "home" and is_key_page(p.role, ctx.category):
            key_paths.append(urlsplit(p.final_url).path or "/")
    grades = grade_tokens(rob, tiers, key_paths=key_paths)
    star_blocked = not rob.is_allowed("/", "some-unlisted-crawler")
    if star_blocked:
        affected = sorted({g["tier"] for g in grades if not g["root_allowed"]})
        out.fail("cr.robots.blanket_disallow",
                 title="robots.txt disallows the whole site for every crawler",
                 evidence="robots.txt: the '*' group disallows '/' (rule: %s); %d of %d known AI bots are blocked as a result." % (
                     _rule_text(rob, "/", "*"), sum(1 for g in grades if not g["root_allowed"]), len(grades)),
                 evidence_items=[evidence_item("robots.txt", "robots_rule", "User-agent: * / " + _rule_text(rob, "/", "*")),
                                 evidence_item("robots.txt", "computed", "affected_tiers=%s" % ",".join(affected))],
                 why="Every crawler that honours robots.txt, including the ones assistants use to fetch and index pages, is told to stay out. The brand is invisible to them by instruction.",
                 action="Replace 'Disallow: /' under 'User-agent: *' with rules that only exclude private paths.",
                 detail="Edit robots.txt so the '*' group allows '/' and disallows only paths like /account or /cart. Re-fetch /robots.txt and confirm with a robots tester that '/' is allowed.",
                 references=[REFS["robots"]])
    else:
        out.check("cr.robots.blanket_disallow", "pass")
    # per-tier findings describe NAMED blocks only: a token blocked solely through the '*' group has no rule of
    # its own and is already covered by cr.robots.blanket_disallow (bot_tiers.md section 3)
    by_tier = {"live_answer": [], "index": [], "training_only": []}
    for g in grades:
        if not g["root_allowed"] and g["has_own_group"]:
            by_tier[g["tier"]].append(g)
    live_total = sum(1 for g in grades if g["tier"] == "live_answer")
    if by_tier["live_answer"]:
        toks = [g["token"] for g in by_tier["live_answer"]]
        all_blocked = len(toks) == live_total
        out.fail("cr.robots.live_answer_bot_blocked",
                 title="%s assistant fetcher%s disallowed site-wide in robots.txt" % (
                     "All %d" % live_total if all_blocked else str(len(toks)), "s are" if len(toks) != 1 else " is"),
                 evidence="robots.txt disallows '/' for %s (%s). These bots fetch pages at answer time; blocking them removes the site from answers immediately." % (
                     ", ".join(toks), "; ".join("%s: %s" % (g["token"], g["root_rule"]) for g in by_tier["live_answer"][:4])),
                 evidence_items=[evidence_item("robots.txt", "robots_rule", "User-agent: %s / %s" % (g["token"], g["root_rule"])) for g in by_tier["live_answer"]],
                 why="These user agents are the ones assistants use to read a page while answering a user's question. A block here means the assistant cannot quote the site even when it wants to. The brand is invisible at answer time.",
                 action="Allow %s on '/' in robots.txt, or scope their Disallow to genuinely private paths." % ", ".join(toks),
                 detail="For each listed token, remove 'Disallow: /' from its group or add 'Allow: /' with narrower Disallow lines. Blocking training-only bots (GPTBot, ClaudeBot, CCBot) is a separate decision and can stay.",
                 extra_adjust=["all_live_answer_blocked:critical"] if all_blocked else None,
                 references=[REFS["robots"]])
        if all_blocked:
            out.findings[-1]["severity"] = "critical"
            out.findings[-1]["suggested_action"]["impact"] = "high"
    else:
        out.check("cr.robots.live_answer_bot_blocked", "pass")
    if by_tier["index"]:
        toks = [g["token"] for g in by_tier["index"]]
        search_note = " Googlebot/Bingbot also power classic web search, so search visibility is affected too." if any(t.lower() in ("googlebot", "bingbot") for t in toks) else ""
        out.fail("cr.robots.index_bot_blocked",
                 title="%d AI search-index crawler%s disallowed site-wide in robots.txt" % (len(toks), "s" if len(toks) != 1 else ""),
                 evidence="robots.txt disallows '/' for %s. These crawlers build the indexes assistants cite from.%s" % (", ".join(toks), search_note),
                 evidence_items=[evidence_item("robots.txt", "robots_rule", "User-agent: %s / %s" % (g["token"], g["root_rule"])) for g in by_tier["index"]],
                 why="Index crawlers decide which pages are in the pool an assistant can cite. Blocked here, the site drops out of that pool over time and becomes invisible in answers.",
                 action="Allow %s on '/' in robots.txt." % ", ".join(toks),
                 detail="Remove 'Disallow: /' from each listed group. If some paths must stay private, disallow only those paths. Re-fetch robots.txt to confirm.",
                 references=[REFS["robots"]])
    else:
        out.check("cr.robots.index_bot_blocked", "pass")
    if by_tier["training_only"]:
        toks = [g["token"] for g in by_tier["training_only"]]
        out.policy_note("cr.robots.training_bot_blocked",
                         title="Training-only crawlers blocked (policy note, not a defect)",
                         evidence="robots.txt disallows '/' for %s. These collect text for model training and do not fetch pages at answer time." % ", ".join(toks),
                         evidence_items=[evidence_item("robots.txt", "robots_rule", "User-agent: %s / %s" % (g["token"], g["root_rule"])) for g in by_tier["training_only"]],
                         why="Blocking training crawlers is a legitimate choice about how your content is used. It does not affect whether assistants can fetch or cite the site today; it may reduce what future models know about the brand from training data.",
                         action="No change required. Keep this block if it reflects your content policy.",
                         detail="If you want future models to know the brand from training data, allow these tokens; if not, leave the block. Either way, keep the live-answer and index bots allowed.")
    else:
        out.check("cr.robots.training_bot_blocked", "pass")
    # key pages disallowed for tokens that are otherwise allowed
    hits = [(g, p) for g in grades if g["root_allowed"] and g["tier"] in ("live_answer", "index") for p in g["disallowed_key_paths"]]
    if hits:
        pages = sorted({p.final_url for g, path in hits for p in ctx.pages if (urlsplit(p.final_url).path or "/") == path})
        roles = [p.role for p in ctx.pages if p.final_url in pages]
        out.fail("cr.robots.key_page_disallowed",
                 title="Key page%s disallowed for assistant crawlers that may otherwise crawl the site" % ("s" if len(pages) != 1 else ""),
                 evidence="%s allowed on '/' but disallowed on %s." % (", ".join(sorted({g["token"] for g, _ in hits})), ", ".join(sorted({path for _, path in hits}))),
                 evidence_items=[evidence_item("robots.txt", "robots_rule", "User-agent: %s / %s" % (g["token"], _rule_text(ctx.robots, path, g["token"].lower())), note=path) for g, path in hits[:8]],
                 why="An assistant can reach the home page but not the page that holds the answer (pricing, contact, product). It answers from whatever it can read, or from someone else's copy.",
                 action="Allow the listed key pages for the listed crawlers in robots.txt.",
                 detail="Remove or narrow the Disallow lines that match these paths in the named groups. Confirm with a robots tester for each token.",
                 pages=pages, page_roles=roles, references=[REFS["robots"]])
    else:
        out.check("cr.robots.key_page_disallowed", "pass")


# ---------------------------------------------------------------- access checks
def check_access(ctx, out):
    home = ctx.home
    challenged, errored, ok_pages = [], [], []
    for p in ctx.pages:
        if p.skipped:
            continue
        if p.challenge:
            challenged.append(p)
        elif p.error or (p.status or 0) >= 400:
            errored.append(p)
        else:
            ok_pages.append(p)
    if challenged:
        vendors = sorted({p.fetch.get("challenge_vendor") or "unknown" for p in challenged})
        out.inconclusive("cr.access.challenge_page", reason="challenge_page",
                         title="Bot-protection challenge served on %d sampled page%s; those checks are inconclusive" % (len(challenged), "s" if len(challenged) != 1 else ""),
                         evidence="%s challenge page (HTTP %s) returned for %s instead of content. The audit cannot tell whether assistants are challenged too." % (
                             "/".join(vendors), "/".join(sorted({str(p.status) for p in challenged})), ", ".join(p.role for p in challenged)),
                         evidence_items=[evidence_item(p.final_url, "http_status", "%s challenge=%s" % (p.status, p.fetch.get("challenge_vendor"))) for p in challenged[:6]],
                         why="A challenge page has no content to read, so nothing on these pages could be checked. Real assistants may or may not be challenged; robots.txt rules above are still authoritative.",
                         action="Allow verified AI crawlers and this audit's user agent through the bot-protection layer, then re-run.",
                         detail="In the WAF (Cloudflare, Akamai, etc.) add an allow rule for the crawler user agents you want to serve, or use the vendor's verified-bot list. Re-run the audit from an allowed network to see the full report.",
                         pages=[p.final_url for p in challenged])
    else:
        out.check("cr.access.challenge_page", "pass")
    if errored:
        home_err = any(p.role == "home" for p in errored)
        pages = [p.final_url for p in errored]
        desc = "; ".join("%s: %s" % (p.role, p.error or ("HTTP %s" % p.status)) for p in errored)
        # A refusal is not an outage. 401/403/429 to this auditor usually means the origin
        # declines automated clients while serving browsers perfectly well; calling that
        # "unreachable" would be a confident, critical, false statement about a live site.
        # The edge probe (which now runs on refusal baselines) decides which case this is.
        refused_home = home_err and (home.status or 0) in (401, 403, 429)
        ea = ctx.edge_access or {}
        probed = ea.get("agents") or []
        policy = ea.get("policy") or []
        crawlers_refused = [a for a in probed if (a.get("status") or 0) >= 400 or a.get("error")]
        probe_items = ([evidence_item(ea.get("url") or home.final_url, "http_status", "%s -> %s" % (a["token"], a.get("error") or a.get("status")),
                                      note="user-agent probe; robots.txt %s" % (a.get("robots_rule") or "has no rule for this path (allowed)")) for a in probed] +
                       [evidence_item(ea.get("url") or home.final_url, "robots_rule", "%s not probed: %s" % (a["token"], a.get("rule") or "disallowed"),
                                      note="the site's own policy; reported by cr.robots.*") for a in policy])
        if refused_home and probed and len(crawlers_refused) == len(probed):
            title = "The site refuses automated clients: this auditor and every AI crawler tested got HTTP %s" % home.status
            desc += "; crawler probes (each allowed by robots.txt): " + "; ".join(
                "%s -> %s" % (a["token"], a.get("error") or a.get("status")) for a in probed)
        elif refused_home and probed and not crawlers_refused:
            out.inconclusive("cr.access.http_error", reason="audit_user_agent_refused",
                             title="This auditor was refused (HTTP %s) but AI crawlers were served" % home.status,
                             evidence="GET %s returned HTTP %s to the audit user agent, while %s each received HTTP 200. The refusal applies to this tool, not to the crawlers that matter." % (
                                 ea.get("url"), home.status, ", ".join(a["token"] for a in probed)),
                             evidence_items=[evidence_item(ea.get("url"), "http_status", "audit user agent -> %s" % home.status)] +
                                 [evidence_item(ea.get("url"), "http_status", "%s -> %s" % (a["token"], a.get("status")), note="user-agent probe") for a in probed],
                             why="The pages could not be read by this audit, so checks needing page content have no verdict. The crawlers assistants use were served normally, so this is not evidence of a discoverability problem.",
                             action="No action needed for AI visibility. To audit the site fully, allow this tool's user agent through the bot-protection layer and re-run.",
                             detail="The audit sends one identifying user agent and obeys robots.txt. Allowing it in the WAF for the duration of an audit gives the full report.",
                             pages=pages)
            return ok_pages
        elif refused_home:
            # No probe could settle whether crawlers are served (every token was the site's own policy, robots.txt was
            # unreadable, or the probes disagreed). That is not knowledge of a defect, so it is never a critical finding.
            if not probed:
                why_unknown = {"probe_tokens_disallowed": "every crawler token the audit could test is disallowed by the site's own robots.txt, so none was announced",
                               "robots_unreachable": "robots.txt could not be read, so no crawler token could be announced"}.get(
                    ea.get("reason"), "no crawler token could be announced")
                reason = "crawler_access_unknown"
            else:
                why_unknown = "the crawlers tested were answered differently (%s)" % "; ".join(
                    "%s -> %s" % (a["token"], a.get("error") or a.get("status")) for a in probed)
                reason = "crawler_access_mixed"
            out.inconclusive("cr.access.http_error", reason=reason,
                             title="This auditor was refused (HTTP %s); whether AI crawlers are served could not be established" % home.status,
                             evidence="GET %s returned HTTP %s to the audit user agent, and %s. The refusal may apply only to this tool." % (
                                 home.final_url, home.status, why_unknown),
                             evidence_items=[evidence_item(home.final_url, "http_status", "audit user agent -> %s" % home.status)] + probe_items,
                             why="The pages could not be read by this audit, so checks needing page content have no verdict. Nothing here shows that the crawlers assistants use are refused; it shows only that this audit was.",
                             action="Allow this tool's user agent through the bot-protection layer and re-run to get the full report.",
                             detail="The audit sends one identifying user agent and obeys robots.txt for itself and for every crawler token it announces. Where the site's robots.txt disallows those tokens, their access is the site's stated policy and is reported under cr.robots.*.",
                             pages=pages)
            return ok_pages
        elif home_err:
            title = "Site is unreachable: the home page could not be fetched (%s)" % (home.error or "HTTP %s" % home.status)
        else:
            title = "%d sampled page%s return%s an error to a plain fetcher" % (len(errored), "s" if len(errored) != 1 else "", "" if len(errored) != 1 else "s")
        out.fail("cr.access.http_error", title=title[:90],
                 evidence="Plain GET of %s. %s" % (", ".join(p.role for p in errored), desc),
                 evidence_items=[evidence_item(p.final_url, "http_status", str(p.status) if p.status else "error=%s" % p.error, note=p.fetch.get("error_detail")) for p in errored[:6]]
                                + (probe_items if refused_home else []),
                 why=("Every AI crawler tested was refused the same way, so the pages an assistant would read are unavailable to it, whatever robots.txt permits and however well the site serves browsers."
                      if refused_home else
                      "A page that answers with an error to a plain fetcher does not exist for an assistant. If this is the home page, the whole brand is invisible."),
                 action=("Allow the published AI crawler user agents through the CDN or WAF, then re-run." if refused_home else
                         "Make %s return HTTP 200 to a plain GET from a non-browser client." % ("the home page" if home_err else "these pages")),
                 detail="Check server logs for the audit user agent. Common causes: user-agent allowlists, geo blocks, expired TLS certificates, DNS misconfiguration. Verify with curl -I from a machine outside your network.",
                 pages=pages, page_roles=[p.role for p in errored],
                 extra_adjust=["home_unreachable:critical"] if home_err else None)
        if home_err:
            out.findings[-1]["severity"] = "critical"
            out.findings[-1]["suggested_action"]["impact"] = "high"
    else:
        out.check("cr.access.http_error", "pass")
    if home and home.status == 200 and not home.challenge and not home.fetch.get("is_html"):
        out.fail("cr.access.non_html_seed",
                 title="The home URL serves a %s document, not an HTML page" % (home.fetch.get("content_type") or "non-HTML"),
                 evidence="GET %s returned Content-Type %s (%d bytes). Crawlers expect an HTML entry page with links; a %s cannot be navigated or quoted the same way." % (
                     home.final_url, home.fetch.get("content_type"), home.fetch.get("bytes", 0), home.fetch.get("content_type")),
                 evidence_items=[evidence_item(home.final_url, "http_header", "content-type: %s" % home.fetch.get("content_type")),
                                 evidence_item(home.final_url, "computed", "bytes=%d; is_html=false" % home.fetch.get("bytes", 0))],
                 why="The entry point is the one URL every assistant and crawler starts from. A PDF or file there means no navigation, no structured data, and no quotable text at the front door: the brand is invisible.",
                 action="Serve an HTML home page at %s and link to the document from it." % home.final_url,
                 detail="Put the brochure or file behind a link on a real HTML home page with a heading, a sentence about what the brand does, and navigation. Verify with curl -I that the root returns text/html.",
                 pages=[home.final_url], page_roles=["home"])
    else:
        out.check("cr.access.non_html_seed", "pass")
    return ok_pages



# ---------------------------------------------------------------- edge-level access checks
EDGE_IDS = ("cr.access.edge_block", "cr.access.edge_block_training", "cr.access.ua_content_variance")


def check_edge_access(ctx, out):
    """Does the origin actually serve a declared AI crawler, or does a CDN/WAF refuse it?

    robots.txt states policy; this reads behaviour. A site can allow every AI crawler in
    robots.txt and still return 403 to them at the edge, which robots.txt inspection alone
    cannot see. The sampler does the requests (so a workdir replay reproduces this exactly);
    this function only grades what it recorded.
    """
    ea = ctx.edge_access
    if not ea or not ea.get("agents"):
        # Nothing was probed. Either there was no response to compare against, or every token the audit could
        # announce is disallowed by the site's own robots.txt (its policy, already reported by cr.robots.*), or
        # robots.txt could not be read so no token could be announced. None of these is a verdict on the edge.
        reason = (ea or {}).get("reason") or ("no_baseline" if not ea else "network_disabled")
        for cid in EDGE_IDS:
            out.not_evaluated(cid, reason=reason)
        return
    # This check compares a *served* baseline against the crawler probes. When our own fetch was
    # refused too there is no "served to us but not to them" to report: the blanket refusal is
    # already stated by cr.access.http_error, and claiming the site was served here would
    # contradict it. The probe data is still recorded; it is simply not this check's evidence.
    if ((ea.get("baseline") or {}).get("status") or 0) != 200:
        for cid in EDGE_IDS:
            out.not_evaluated(cid, reason="no_200_baseline")
        return
    base_bytes = (ea.get("baseline") or {}).get("bytes") or 0
    refused, served = [], []
    for a in ea["agents"]:
        st = a.get("status") or 0
        if a.get("error") or st >= 400:
            refused.append(a)
        else:
            served.append(a)

    cite = [a for a in refused if a["tier"] in ("live_answer", "index")]
    train = [a for a in refused if a["tier"] == "training_only"]
    probed_cite = [a for a in ea["agents"] if a["tier"] in ("live_answer", "index")]

    policy = ea.get("policy") or []

    def _desc(a):
        return "%s (%s): %s" % (a["token"], a["tier"], a.get("error") or "HTTP %s" % a.get("status"))

    def _rule(a):
        return a.get("robots_rule") or "no rule for this path (allowed by absence)"

    policy_items = [evidence_item(ea["url"], "robots_rule", "%s not probed: %s" % (a["token"], a.get("rule") or "disallowed"),
                                  note="the site's own policy; reported by cr.robots.*") for a in policy]
    if cite:
        every = len(cite) == len(probed_cite) and probed_cite
        out.fail("cr.access.edge_block",
                 title="The site is served to this audit but refused to %s" % (
                     "every AI crawler tested" if every else "%d AI crawler%s" % (len(cite), "" if len(cite) == 1 else "s")),
                 evidence="GET %s returned HTTP %s (%d bytes) to the audit's own user agent, but %s. robots.txt allows these agents at this URL, so the refusal is the origin's or its CDN's, answering by user agent." % (
                     ea["url"], (ea.get("baseline") or {}).get("status"), base_bytes, "; ".join(_desc(a) for a in cite)),
                 evidence_items=[evidence_item(ea["url"], "http_status", "audit user agent -> %s (%d bytes)" % (
                     (ea.get("baseline") or {}).get("status"), base_bytes))] +
                     [evidence_item(ea["url"], "http_status", _desc(a), note="user-agent probe; robots.txt: %s" % _rule(a)) for a in cite] +
                     policy_items,
                 why="These are the crawlers that fetch and index pages for AI answers. A page they cannot retrieve cannot be quoted or cited, no matter what robots.txt permits. Because the block is at the network edge, it is invisible to every audit that only reads robots.txt.",
                 action="Allow the published AI crawler user agents through the CDN or WAF, then re-run this check.",
                 detail="In Cloudflare, Akamai, Fastly or your WAF, find the bot-management or firewall rule matching these user agents and add an allow rule (most vendors ship a verified-bot list). Confirm with: curl -A '%s' -I %s and check for HTTP 200." % (
                     next((ua for t, _tier, ua in PROBE_USER_AGENTS if t == cite[0]["token"]), cite[0]["token"]), ea["url"]),
                 references=[REFS["robots"]],
                 extra_adjust=["edge_block_all_citation_tiers:critical"] if every else None)
        if every:
            out.findings[-1]["severity"] = "critical"
            out.findings[-1]["suggested_action"]["impact"] = "high"
    else:
        out.check("cr.access.edge_block", "pass")

    if train and not cite:
        out.policy_note("cr.access.edge_block_training",
                        title="Training-only crawlers are refused at the edge (policy note, not a defect)",
                        evidence="%s refused while the audit's own user agent received HTTP %s. No live-answer or index crawler was refused." % (
                            "; ".join(_desc(a) for a in train), (ea.get("baseline") or {}).get("status")),
                        evidence_items=[evidence_item(ea["url"], "http_status", _desc(a), note="user-agent probe; robots.txt: %s" % _rule(a)) for a in train] + policy_items,
                        why="Blocking training crawlers keeps content out of future model training. It does not stop the site being fetched or cited when someone asks about it today, so it is recorded as a choice rather than a problem.",
                        action="No action needed unless you intended these crawlers to have access.",
                        detail="If the block was not deliberate, check the CDN or WAF bot rules for these user agents.")
    else:
        out.check("cr.access.edge_block_training", "pass")

    varied = [a for a in served if base_bytes and abs((a.get("bytes") or 0) - base_bytes) > base_bytes * 0.5]
    if varied and not cite:
        out.inconclusive("cr.access.ua_content_variance", reason="content_varies_by_user_agent",
                         title="The home page body size differs by user agent",
                         evidence="Baseline %d bytes; %s. The audit cannot tell whether this is deliberate, an A/B test, or personalisation." % (
                             base_bytes, "; ".join("%s: %d bytes" % (a["token"], a.get("bytes") or 0) for a in varied)),
                         evidence_items=[evidence_item(ea["url"], "computed", "%s=%d bytes vs baseline %d" % (
                             a["token"], a.get("bytes") or 0, base_bytes)) for a in varied],
                         why="Serving materially different content to a crawler than to other clients means what an assistant reads is not what the audit measured, so the rest of this report may not describe what the crawler sees.",
                         action="Confirm the difference is intentional; if it is not, serve the same HTML to all user agents.",
                         detail="Compare the two responses directly: curl -A '<crawler UA>' URL against curl -A '<browser UA>' URL and diff them.")
    else:
        out.check("cr.access.ua_content_variance", "pass")

# ---------------------------------------------------------------- render checks
def check_render(ctx, out):
    gates, shells = [], []
    for p in ctx.html_pages:
        d = p.doc
        if d.word_count >= THIN_WORDS:
            continue
        g = js_gate_signals(d)
        if g:
            gates.append((p, g))
            continue
        c = csr_signals(d)
        if c:
            shells.append((p, c))
    if gates:
        pages = [p.final_url for p, _ in gates]
        home_hit = any(p.role == "home" for p, _ in gates)
        out.fail("cr.render.js_gate",
                 title="%s require%s JavaScript before any content is served" % (
                     "The home page" if home_hit and len(gates) == 1 else ("Every sampled page" if len(gates) == len(ctx.html_pages) and len(gates) > 1 else "%d sampled page%s" % (len(gates), "s" if len(gates) != 1 else "")),
                     "s" if (home_hit and len(gates) == 1) or (len(gates) == len(ctx.html_pages) and len(gates) > 1) else ""),
                 evidence="%d page%s serve%s under %d words of text plus a JavaScript gate (%s). A fetcher that does not run scripts never gets past this door." % (
                     len(gates), "s" if len(gates) != 1 else "", "" if len(gates) != 1 else "s", THIN_WORDS, "; ".join(sorted({s for _, sig in gates for s in sig}))),
                 evidence_items=[evidence_item(p.final_url, "computed", "visible_words=%d; signals=%s" % (p.doc.word_count, ",".join(sig))) for p, sig in gates[:6]] +
                                [evidence_item(gates[0][0].final_url, "text_excerpt", (gates[0][0].doc.noscript_texts[0] if gates[0][0].doc.noscript_texts else gates[0][0].doc.body_text)[:200])],
                 why="Assistant fetchers do not execute JavaScript. A page whose only server-side content is 'enable JavaScript' or a script-driven redirect has zero readable text for them. The brand is invisible from the first hop.",
                 action="Serve real HTML on %s: heading, a sentence about the brand, and navigation links, with any redirect done server-side (HTTP 3xx)." % ("the home page" if home_hit else "these pages"),
                 detail="Replace the onload form submit or meta refresh with a server-side 301/302 to the right locale or app URL, and make sure the destination returns readable HTML without scripts. Verify with curl that the response contains the main heading.",
                 pages=pages, page_roles=[p.role for p, _ in gates], references=[REFS["jsseo"]])
        if home_hit:
            out.findings[-1]["severity"] = "critical"
            out.findings[-1]["suggested_action"]["impact"] = "high"
    else:
        out.check("cr.render.js_gate", "pass" if ctx.html_pages else "not_evaluated", reason=None if ctx.html_pages else "no_html_pages")
    if shells:
        pages = [p.final_url for p, _ in shells]
        home_hit = any(p.role == "home" for p, _ in shells)
        two_signal = any(len(sig) >= 2 for _, sig in shells)
        out.fail("cr.render.csr_shell",
                 title="%s %s a client-rendered shell with no server-rendered text" % (
                     "The home page" if home_hit and len(shells) == 1 else ("Every sampled page" if len(shells) == len(ctx.html_pages) and len(shells) > 1 else "%d sampled page%s" % (len(shells), "s" if len(shells) != 1 else "")),
                     "is" if (home_hit and len(shells) == 1) or (len(shells) == len(ctx.html_pages) and len(shells) > 1) else "are"),
                 evidence="%d page%s serve%s under %d words of visible text together with a framework root container or script-heavy body (%s). The content exists only after JavaScript runs." % (
                     len(shells), "s" if len(shells) != 1 else "", "" if len(shells) != 1 else "s", THIN_WORDS, "; ".join(sorted({s.split(":")[0] for _, sig in shells for s in sig}))),
                 evidence_items=[evidence_item(p.final_url, "computed", "visible_words=%d; script_bytes=%d; external_scripts=%d; signals=%s" % (
                     p.doc.word_count, p.doc.script_bytes, len(p.doc.external_scripts), ",".join(sig))) for p, sig in shells[:6]],
                 why="A fetcher that does not execute JavaScript receives an empty container. Nothing on these pages can be read, quoted, or cited, so the brand is invisible even though humans see a full site.",
                 action="Server-render or pre-render %s so headings, body text, and navigation are in the initial HTML." % ("the home page and key pages" if home_hit else "these pages"),
                 detail="Use the framework's SSR or static-export mode (Next.js, Nuxt, SvelteKit, Astro all support it) for home, about, pricing, product and contact routes first. Verify with curl -s URL | grep '<h1' that the heading is present without scripts. This audit did not render the page, so confidence is medium.",
                 pages=pages, page_roles=[p.role for p, _ in shells], confidence="medium" if two_signal or len(shells) > 1 else "low",
                 references=[REFS["jsseo"]])
        if home_hit and out.findings[-1]["confidence"] != "low":
            out.findings[-1]["severity"] = "critical"
            out.findings[-1]["suggested_action"]["impact"] = "high"
    else:
        out.check("cr.render.csr_shell", "pass" if ctx.html_pages else "not_evaluated", reason=None if ctx.html_pages else "no_html_pages")


# ---------------------------------------------------------------- index checks
def check_index(ctx, out):
    sm = ctx.sitemap or {}
    state = sm.get("state")
    if ctx.home and ctx.home.skipped == "robots_disallow":
        out.not_evaluated("cr.index.sitemap_missing", reason="robots_disallow")
        out.not_evaluated("cr.index.sitemap_invalid", reason="robots_disallow")
    elif state == "missing":
        out.fail("cr.index.sitemap_missing",
                 title="No XML sitemap is advertised or found at the standard paths",
                 evidence="robots.txt has no Sitemap line and %s did not return a sitemap." % ", ".join(sm.get("tried") or ["/sitemap.xml", "/sitemap_index.xml"]),
                 evidence_items=[evidence_item("sitemap", "http_status", "tried=%s; robots_sitemap_lines=%d" % (";".join(sm.get("tried") or []), len(ctx.robots.sitemaps)))],
                 why="Crawlers can still follow links, but a sitemap is how they learn about pages that are not linked prominently and when pages changed. Without it, deep pages are found late or not at all.",
                 action="Publish /sitemap.xml listing the public pages with lastmod dates, and reference it from robots.txt.",
                 detail="Most CMSs and frameworks generate one. Add 'Sitemap: https://<host>/sitemap.xml' to robots.txt. Verify the file returns 200 and parses.",
                 references=[REFS["sitemaps"]])
        out.check("cr.index.sitemap_invalid", "not_evaluated", reason="sitemap_missing")
    elif state == "invalid":
        out.check("cr.index.sitemap_missing", "pass")
        out.fail("cr.index.sitemap_invalid",
                 title="The sitemap exists but is not valid XML or lists no URLs",
                 evidence="%s returned 200 but could not be parsed as a urlset or sitemapindex with <loc> entries." % sm.get("url"),
                 evidence_items=[evidence_item(sm.get("url") or "sitemap", "computed", "state=invalid; url_count=%s" % sm.get("url_count", 0))],
                 why="A sitemap that does not parse is ignored, so crawlers gain nothing from it and may treat the site as less maintained.",
                 action="Fix the sitemap so it is well-formed XML with at least one <loc>.",
                 detail="Validate it with an XML parser or the Sitemaps protocol validator. Common causes: HTML error page served at the sitemap URL, gzip without the .gz extension, or an empty urlset.",
                 references=[REFS["sitemaps"]])
    elif state in ("unreachable", "challenge"):
        out.inconclusive("cr.index.sitemap_missing", reason="sitemap_" + state,
                         title="The sitemap could not be fetched, so sitemap checks are inconclusive",
                         evidence="%s answered with %s." % (sm.get("url"), sm.get("error") or state),
                         evidence_items=[evidence_item(sm.get("url") or "sitemap", "http_status", state)],
                         why="The audit cannot tell whether a sitemap exists.", action="Make the sitemap URL return 200 to a plain fetcher.",
                         detail="Check the server and WAF for the sitemap path, then re-run.")
        out.check("cr.index.sitemap_invalid", "not_evaluated", reason="sitemap_" + state)
    else:
        out.check("cr.index.sitemap_missing", "pass")
        out.check("cr.index.sitemap_invalid", "pass")
    # noindex on key pages
    noindex = []
    for p in ctx.html_pages:
        if not is_key_page(p.role, ctx.category):
            continue
        meta = p.doc.robots_meta
        hdr = (p.fetch.get("headers") or {}).get("x-robots-tag") or ""
        if "noindex" in meta or "noindex" in hdr.lower():
            noindex.append((p, meta, hdr))
    if noindex:
        out.fail("cr.index.noindex_on_key_page",
                 title="%d key page%s carr%s a noindex directive" % (len(noindex), "s" if len(noindex) != 1 else "", "y" if len(noindex) != 1 else "ies"),
                 evidence="noindex found on %s (%s)." % (", ".join(p.role for p, _, _ in noindex), "; ".join(("meta robots: " + m) if m else ("X-Robots-Tag: " + h) for _, m, h in noindex)),
                 evidence_items=[evidence_item(p.final_url, "html_excerpt" if m else "http_header", m or h) for p, m, h in noindex],
                 why="noindex tells every indexer to drop the page. An assistant grounding on a search index will never see it, however good the content is.",
                 action="Remove the noindex directive from these pages.",
                 detail="Delete the <meta name=\"robots\" content=\"noindex\"> tag or the X-Robots-Tag header on the listed URLs. Check CMS visibility settings and staging flags that leak to production.",
                 pages=[p.final_url for p, _, _ in noindex], page_roles=[p.role for p, _, _ in noindex], references=[REFS["robots_meta"]])
    else:
        out.check("cr.index.noindex_on_key_page", "pass" if ctx.html_pages else "not_evaluated", reason=None if ctx.html_pages else "no_html_pages")
    # canonicals
    offsite, mismatch = [], []
    site_rd = registrable_domain(urlsplit(ctx.site or "").hostname or "")
    for p in ctx.html_pages:
        c = p.doc.canonical
        if not c:
            continue
        ch = urlsplit(c).hostname or ""
        if registrable_domain(ch) != site_rd:
            offsite.append((p, c))
            continue
        if _norm_path(c) != _norm_path(p.final_url):
            mismatch.append((p, c))
    if offsite:
        out.fail("cr.index.canonical_offsite",
                 title="Canonical tag points to a different domain on %d sampled page%s" % (len(offsite), "s" if len(offsite) != 1 else ""),
                 evidence="%s" % "; ".join("%s → %s" % (p.role, c) for p, c in offsite[:4]),
                 evidence_items=[evidence_item(p.final_url, "html_excerpt", '<link rel="canonical" href="%s">' % c) for p, c in offsite],
                 why="The canonical says 'the real copy of this page lives elsewhere'. Indexers credit that other domain, so citations go to it instead of to the brand's own site.",
                 action="Point rel=canonical on these pages to their own URL on this domain.",
                 detail="Check the template or CMS setting that emits the canonical; a copied theme or a staging domain is the usual cause. Verify with curl that each page's canonical matches its own URL.",
                 pages=[p.final_url for p, _ in offsite], page_roles=[p.role for p, _ in offsite], references=[REFS["canonical"]])
    else:
        out.check("cr.index.canonical_offsite", "pass" if ctx.html_pages else "not_evaluated", reason=None if ctx.html_pages else "no_html_pages")
    if mismatch:
        out.fail("cr.index.canonical_mismatch",
                 title="Canonical tag points to a different page on %d sampled page%s" % (len(mismatch), "s" if len(mismatch) != 1 else ""),
                 evidence="%s" % "; ".join("%s → %s" % (p.role, c) for p, c in mismatch[:4]),
                 evidence_items=[evidence_item(p.final_url, "html_excerpt", '<link rel="canonical" href="%s">' % c) for p, c in mismatch],
                 why="Indexers may consolidate this page into the canonical target and drop this URL, so the content here is never cited under its own address.",
                 action="Make each page's canonical point to itself unless it is a true duplicate.",
                 detail="Review the canonical logic in the template; paginated, filtered and localised pages are the usual source of mistakes.",
                 pages=[p.final_url for p, _ in mismatch], page_roles=[p.role for p, _ in mismatch], references=[REFS["canonical"]])
    else:
        out.check("cr.index.canonical_mismatch", "pass" if ctx.html_pages else "not_evaluated", reason=None if ctx.html_pages else "no_html_pages")


# ---------------------------------------------------------------- main
def run(ctx):
    out = ProbeOutput(PROBE, ctx.site, ctx.category, ctx.examined_urls, total_sampled_pages=len(ctx.pages))
    if ctx.error:
        out.error = ctx.error
        out.fill_unreported("cr.", status="not_evaluated")
        for c in out.checks:
            c.setdefault("reason", "context_error")
        return out
    try:
        check_robots(ctx, out)
    except Exception as e:  # noqa: BLE001
        out.error = "robots checks: %s: %s" % (type(e).__name__, e)
    home = ctx.home
    if home and home.skipped == "robots_disallow":
        # the audit obeys robots.txt: nothing beyond robots.txt was fetched, so every page-level check is not evaluated
        for cid in out.registry.ids("cr."):
            if cid not in out._seen:
                out.not_evaluated(cid, reason="robots_disallow")
        return out
    try:
        check_access(ctx, out)
    except Exception as e:  # noqa: BLE001
        out.error = (out.error or "") + " access checks: %s: %s" % (type(e).__name__, e)
    try:
        check_edge_access(ctx, out)
    except Exception as e:  # noqa: BLE001
        out.error = (out.error or "") + " edge access checks: %s: %s" % (type(e).__name__, e)
    try:
        check_render(ctx, out)
    except Exception as e:  # noqa: BLE001
        out.error = (out.error or "") + " render checks: %s: %s" % (type(e).__name__, e)
    try:
        check_index(ctx, out)
    except Exception as e:  # noqa: BLE001
        out.error = (out.error or "") + " index checks: %s: %s" % (type(e).__name__, e)
    # challenged pages: every other per-page check on them is inconclusive (dedupe row 1 handles findings)
    challenged = [p.final_url for p in ctx.pages if p.challenge]
    fetched = [p for p in ctx.pages if not p.skipped]
    if challenged and len(challenged) == len(fetched):
        for c in out.checks:
            if c["check_id"] in ("cr.render.js_gate", "cr.render.csr_shell", "cr.index.noindex_on_key_page",
                                 "cr.index.canonical_offsite", "cr.index.canonical_mismatch") and c["status"] in ("pass", "not_evaluated"):
                c["status"] = "inconclusive"
                c["reason"] = "challenge_page"
                c.pop("pages", None)
    out.fill_unreported("cr.", status="not_evaluated")
    for c in out.checks:
        if c["status"] == "not_evaluated" and "reason" not in c:
            c["reason"] = "dependency_failed"
    return out


def main(argv=None):
    return probe_main(PROBE, run, __doc__, argv)


if __name__ == "__main__":
    sys.exit(main())
