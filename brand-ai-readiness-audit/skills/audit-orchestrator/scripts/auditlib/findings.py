"""Registry loader and finding builder shared by every probe.

Implements report_schema.md sections 1-2 and severity_confidence_rubric.md
section 3 (adjustment order). Probes call:

    reg = Registry()                      # parsed from ../../references/check_ids.md
    out = ProbeOutput("crawl-render-audit", ctx)
    out.check("cr.robots.blanket_disallow", "pass")
    out.fail("cr.render.csr_shell", pages=[...], evidence_items=[...], title=..., why=..., action=..., detail=...)
    out.inconclusive("cr.access.challenge_page", pages=[...], reason="challenge_page", ...)
    out.not_evaluated("cr.index.noindex_on_key_page", reason="robots_disallow")
    print(out.to_json())
"""
import datetime as _dt
import json
import os
import re

from . import __version__
from .categories import SEVERITY_OVERRIDES, is_key_page

REFERENCES_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "references"))
CHECK_IDS_MD = os.path.join(REFERENCES_DIR, "check_ids.md")
SEVERITIES = ("critical", "high", "medium", "low", "info")
CONFIDENCES = ("high", "medium", "low")
EFFORTS = ("low", "medium", "high", "n/a")
STATUSES = ("pass", "fail", "inconclusive", "not_evaluated")
STAGES = ("access", "render", "extract", "entity", "freshness", "corroboration", "engagement")
_ROW = re.compile(r"^\| `([a-z]{2}\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)` \| ([a-z—]+) \| (\w+) \| (\w+) \| (\w+) \| ([\w/]+) \| ([\w-]+) \| (.*?) \|\s*$", re.M)


class Registry:
    """check_id -> defaults, parsed from check_ids.md (the single source of truth)."""

    def __init__(self, path=CHECK_IDS_MD):
        self.rows = {}
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            text = ""
        for cid, stage, sev, mx, conf, effort, scope, desc in _ROW.findall(text):
            self.rows[cid] = {"check_id": cid, "stage": None if stage == "—" else stage, "severity": sev, "max_severity": mx,
                              "confidence": conf, "effort": effort, "scope": scope, "fails_when": desc.strip()}

    def __contains__(self, cid):
        return cid in self.rows

    def __getitem__(self, cid):
        return self.rows[cid]

    def ids(self, prefix=None):
        return [c for c in self.rows if not prefix or c.startswith(prefix)]


def _lower(sev, n=1):
    i = SEVERITIES.index(sev)
    return SEVERITIES[min(i + n, len(SEVERITIES) - 2)]  # never below low via adjustments


def _raise(sev, n=1):
    return SEVERITIES[max(SEVERITIES.index(sev) - n, 0)]


def _cap(sev, mx):
    return sev if SEVERITIES.index(sev) >= SEVERITIES.index(mx) else mx


def adjust_severity(default, max_severity, confidence, check_id, category, page_roles, total_sampled_pages, home_hit=False):
    """severity_confidence_rubric.md section 3, in order. Returns (severity, [adjustment strings])."""
    sev = default
    adj = []
    # 5 (applied first per rubric text): category overrides replace the default
    ov = SEVERITY_OVERRIDES.get(check_id, {}).get(category)
    if ov and ov != "not_evaluated":
        sev = ov
        adj.append("category_override:%s" % ov)
    # 2: page role. Home or key page => default; only non-key pages => one level lower (never below low)
    if page_roles:
        if any(is_key_page(r, category) for r in page_roles):
            if home_hit or "home" in page_roles:
                if max_severity == "critical" and default in ("high", "critical"):
                    sev = "critical"
                    adj.append("home_page:critical")
        else:
            sev = _lower(sev)
            adj.append("non_key_pages:-1")
    # 3: blast radius: same fail on every sampled page (>= 3 pages) => one level higher, up to max
    if page_roles and total_sampled_pages >= 3 and len(set(page_roles)) >= total_sampled_pages:
        raised = _cap(_raise(sev), max_severity)
        if raised != sev:
            sev = raised
            adj.append("blast_radius:+1")
    # 4: confidence cap
    if confidence == "low" and SEVERITIES.index(sev) < SEVERITIES.index("medium"):
        sev = "medium"
        adj.append("confidence_cap:medium")
    if SEVERITIES.index(sev) < SEVERITIES.index(max_severity):
        sev = max_severity
    return sev, adj


def impact_for(severity):
    return "high" if severity in ("critical", "high") else ("medium" if severity == "medium" else "low")


def priority_for(severity, confidence):
    imp = impact_for(severity)
    if confidence == "low" and imp != "low":
        return {"high": "medium", "medium": "low"}[imp]
    return imp


def evidence_item(page, kind, value, location=None, note=None):
    value = re.sub(r"\s+", " ", str(value)).strip()
    if len(value) > 300:
        value = value[:297] + "…"
    item = {"page": page, "kind": kind, "value": value}
    if location:
        item["location"] = location
    if note:
        item["note"] = note
    return item


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ProbeOutput:
    def __init__(self, probe_name, site, category, pages_examined, registry=None, total_sampled_pages=None):
        self.registry = registry or Registry()
        self.probe = probe_name
        self.site = site
        self.category = category or "unknown"
        self.pages_examined = list(pages_examined)
        self.total_sampled_pages = total_sampled_pages if total_sampled_pages is not None else len(self.pages_examined)
        self.checks = []
        self.findings = []
        self.artifacts = {}
        self.error = None
        self._seen = set()

    # ------------------------------------------------------------ checks
    def check(self, check_id, status, pages=None, reason=None):
        """Record a check's status. One entry per check_id: a later call replaces the earlier entry."""
        assert status in STATUSES, status
        entry = {"check_id": check_id, "status": status}
        if pages:
            entry["pages"] = list(pages)
        if reason:
            entry["reason"] = reason
        for i, c in enumerate(self.checks):
            if c["check_id"] == check_id:
                self.checks[i] = entry
                return entry
        self.checks.append(entry)
        self._seen.add(check_id)
        return entry

    def status_of(self, check_id):
        for c in self.checks:
            if c["check_id"] == check_id:
                return c["status"]
        return None

    def fill_unreported(self, prefix, status="pass"):
        """Every registered check for this probe appears in `checks`; unreported ones default to pass."""
        for cid in self.registry.ids(prefix):
            if cid not in self._seen:
                self.check(cid, status)

    # ------------------------------------------------------------ findings
    def fail(self, check_id, title, evidence, evidence_items, why, action, detail, pages=None, page_roles=None,
             confidence=None, effort=None, references=None, extra_adjust=None):
        row = self.registry[check_id]
        conf = confidence or row["confidence"]
        sev, adj = adjust_severity(row["severity"], row["max_severity"], conf, check_id, self.category,
                                   page_roles or [], self.total_sampled_pages)
        if extra_adjust:
            adj.extend(extra_adjust)
        eff = effort or row["effort"]
        items = list(evidence_items)
        if adj:
            items.append(evidence_item(pages[0] if pages else "site", "computed", "adjustments=" + ",".join(adj)))
        f = {
            "check_id": check_id, "title": title[:90], "status": "fail", "severity": sev, "confidence": conf, "effort": eff,
            "mechanism": row["stage"], "affected_pages": list(pages or []), "evidence": evidence[:300], "evidence_items": items,
            "why_it_matters": why,
            "suggested_action": {"summary": action, "detail": detail, "impact": impact_for(sev), "effort": eff,
                                 "priority": priority_for(sev, conf)},
            "references": list(references or []),
            "dedupe_key": check_id + "|" + ",".join(sorted(pages or [])),
        }
        self.findings.append(f)
        self.check(check_id, "fail", pages=pages)
        return f

    def _info(self, check_id, status, reason, title, evidence, evidence_items, why, action, detail, pages=None):
        row = self.registry[check_id]
        f = {
            "check_id": check_id, "title": title[:90], "status": status, "severity": "info", "confidence": row["confidence"],
            "effort": "n/a", "mechanism": row["stage"], "affected_pages": list(pages or []), "evidence": evidence[:300],
            "evidence_items": list(evidence_items), "why_it_matters": why,
            "suggested_action": {"summary": action, "detail": detail, "impact": "low", "effort": "n/a", "priority": "low"},
            "references": [], "dedupe_key": check_id + "|" + ",".join(sorted(pages or [])), "reason": reason,
        }
        self.findings.append(f)
        self.check(check_id, status, pages=pages, reason=reason)
        return f

    def policy_note(self, check_id, title, evidence, evidence_items, why, action, detail, pages=None):
        """A check that is registered as `info` by default: the condition was found, but it is a policy choice,
        not a defect. status=fail (the condition is real) with severity=info (never counted as a problem)."""
        row = self.registry[check_id]
        assert row["severity"] == "info", "policy_note only for info-registered checks: %s" % check_id
        f = {
            "check_id": check_id, "title": title[:90], "status": "fail", "severity": "info", "confidence": row["confidence"],
            "effort": "n/a", "mechanism": row["stage"], "affected_pages": list(pages or []), "evidence": evidence[:300],
            "evidence_items": list(evidence_items), "why_it_matters": why,
            "suggested_action": {"summary": action, "detail": detail, "impact": "low", "effort": "n/a", "priority": "low"},
            "references": [], "dedupe_key": check_id + "|" + ",".join(sorted(pages or [])),
        }
        self.findings.append(f)
        self.check(check_id, "fail", pages=pages)
        return f

    def inconclusive(self, check_id, reason, title, evidence, evidence_items, why, action, detail, pages=None):
        return self._info(check_id, "inconclusive", reason, title, evidence, evidence_items, why, action, detail, pages)

    def not_evaluated(self, check_id, reason, pages=None, emit_finding=False, **kw):
        """not_evaluated produces a finding only when the reason is worth telling the user (schema section 1)."""
        if emit_finding:
            return self._info(check_id, "not_evaluated", reason, kw["title"], kw["evidence"], kw.get("evidence_items", []),
                              kw["why"], kw["action"], kw["detail"], pages)
        return self.check(check_id, "not_evaluated", pages=pages, reason=reason)

    # ------------------------------------------------------------ output
    def to_dict(self):
        return {"probe": self.probe, "probe_version": __version__, "site": self.site, "run_at": _now(),
                "site_category": self.category, "pages_examined": self.pages_examined, "checks": self.checks,
                "findings": self.findings, "artifacts": self.artifacts, "error": self.error}

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


def validate_probe_output(d, registry=None):
    """Return a list of problems (empty = valid) against report_schema.md section 1-2."""
    reg = registry or Registry()
    problems = []
    for k in ("probe", "probe_version", "site", "run_at", "site_category", "pages_examined", "checks", "findings", "error"):
        if k not in d:
            problems.append("missing top-level %s" % k)
    for c in d.get("checks", []):
        if c.get("check_id") not in reg:
            problems.append("unknown check_id %s" % c.get("check_id"))
        if c.get("status") not in STATUSES:
            problems.append("bad status %s" % c.get("status"))
        if c.get("status") in ("inconclusive", "not_evaluated") and not c.get("reason"):
            problems.append("%s: %s without reason" % (c.get("check_id"), c.get("status")))
    for f in d.get("findings", []):
        cid = f.get("check_id")
        for k in ("title", "status", "severity", "confidence", "effort", "mechanism", "affected_pages", "evidence",
                  "evidence_items", "why_it_matters", "suggested_action", "dedupe_key"):
            if k not in f:
                problems.append("%s: finding missing %s" % (cid, k))
        if f.get("status") == "pass":
            problems.append("%s: finding with status pass" % cid)
        if f.get("status") in ("inconclusive", "not_evaluated") and f.get("severity") != "info":
            problems.append("%s: %s must be info" % (cid, f.get("status")))
        if f.get("severity") not in SEVERITIES or f.get("confidence") not in CONFIDENCES or f.get("effort") not in EFFORTS:
            problems.append("%s: bad enum" % cid)
        if not f.get("evidence_items"):
            problems.append("%s: no evidence items" % cid)
        if len(f.get("title", "")) > 90 or not f.get("evidence"):
            problems.append("%s: title length or empty evidence" % cid)
        sa = f.get("suggested_action") or {}
        for k in ("summary", "detail", "impact", "effort", "priority"):
            if not sa.get(k):
                problems.append("%s: suggested_action missing %s" % (cid, k))
        if cid in reg:
            row = reg[cid]
            if f.get("status") == "fail" and SEVERITIES.index(f["severity"]) < SEVERITIES.index(row["max_severity"]):
                problems.append("%s: severity %s exceeds max %s" % (cid, f["severity"], row["max_severity"]))
            if f.get("confidence") == "low" and f.get("severity") in ("critical", "high"):
                problems.append("%s: low confidence with severity %s" % (cid, f["severity"]))
    return problems
