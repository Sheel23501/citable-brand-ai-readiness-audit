"""robots.txt parsing and evaluation per RFC 9309, plus bot-tier lookup.

Implements fetch_policy.md section 5 and bot_tiers.md sections 2-3.
Pure functions; no network. Never raises on malformed input.
"""
import os
import re
from urllib.parse import unquote, urlsplit

REFERENCES_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "references"))
BOT_TIERS_MD = os.path.join(REFERENCES_DIR, "bot_tiers.md")
TIERS = ("live_answer", "index", "training_only")
AUDIT_TOKEN = "brand-ai-readiness-audit"


class Rule:
    __slots__ = ("allow", "pattern", "_regex")

    def __init__(self, allow, pattern):
        self.allow = allow
        self.pattern = pattern
        self._regex = _compile(pattern)

    def matches(self, path):
        return self._regex.match(path) is not None

    def __repr__(self):
        return "%s: %s" % ("Allow" if self.allow else "Disallow", self.pattern)


def _compile(pattern):
    """RFC 9309 pattern -> regex. '*' matches any sequence, '$' anchors the end."""
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    parts = [re.escape(_norm(p)) for p in pattern.split("*")]
    body = ".*".join(parts)
    return re.compile("^" + body + ("$" if anchored else ""), re.S)


def _norm(path):
    """Percent-decode for comparison, but keep reserved characters that change meaning."""
    try:
        return unquote(path, errors="strict") if "%" in path else path
    except Exception:  # noqa: BLE001
        return path


class Group:
    __slots__ = ("agents", "rules")

    def __init__(self):
        self.agents = set()
        self.rules = []


class Robots:
    """Parsed robots.txt.

    state: 'ok' | 'missing' (4xx => allow all) | 'unreachable' (5xx/timeout/challenge => inconclusive)
    """

    def __init__(self, text=None, state="ok", url=None):
        self.state = state
        self.url = url
        self.groups = []
        self.sitemaps = []
        self.raw = text or ""
        self.line_count = 0
        self.parse_errors = []
        if text:
            self._parse(text)

    # ----------------------------------------------------------- parsing
    def _parse(self, text):
        group = None
        last_was_agent = False
        for raw in text.splitlines():
            self.line_count += 1
            line = raw.split("#", 1)[0].strip().lstrip("\ufeff").strip()  # RFC 9309: a leading UTF-8 BOM is ignored
            if not line:
                continue  # RFC 9309: blank lines are ignored, they do not end a group
            if ":" not in line:
                self.parse_errors.append("line %d: no colon" % self.line_count)
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if key == "user-agent":
                if group is None or not last_was_agent:
                    group = Group()
                    self.groups.append(group)
                group.agents.add(value.lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if key == "sitemap":
                if value:
                    self.sitemaps.append(value)
                continue
            if key in ("allow", "disallow"):
                if group is None:
                    self.parse_errors.append("line %d: rule before any user-agent" % self.line_count)
                    continue
                if key == "disallow" and value == "":
                    continue  # empty Disallow allows everything: no-op rule
                if key == "allow" and value == "":
                    continue
                if not value.startswith("/") and not value.startswith("*"):
                    value = "/" + value
                group.rules.append(Rule(key == "allow", value))
                continue
            # crawl-delay, host, clean-param and unknown keys are ignored per RFC 9309 section 2.2.4

    # ----------------------------------------------------------- lookup
    def group_for(self, token):
        """The group that governs `token` (case-insensitive exact product-token match), else the '*' group, else None."""
        t = (token or "").lower()
        for g in self.groups:
            if t in g.agents:
                return g
        for g in self.groups:
            if "*" in g.agents:
                return g
        return None

    def has_specific_group(self, token):
        t = (token or "").lower()
        return any(t in g.agents for g in self.groups)

    def is_allowed(self, url_or_path, token):
        """RFC 9309 evaluation: longest match wins; equal length => Allow wins. No group => allowed."""
        if self.state == "missing":
            return True
        path = _path_of(url_or_path)
        g = self.group_for(token)
        if g is None:
            return True
        best = None
        best_len = -1
        for r in g.rules:
            if r.matches(path):
                plen = len(r.pattern.rstrip("$"))
                if plen > best_len or (plen == best_len and r.allow and best is not None and not best.allow):
                    best, best_len = r, plen
        return True if best is None else best.allow

    def matching_rule(self, url_or_path, token):
        """The winning rule text for evidence, or None."""
        path = _path_of(url_or_path)
        g = self.group_for(token)
        if g is None:
            return None
        best, best_len = None, -1
        for r in g.rules:
            if r.matches(path):
                plen = len(r.pattern.rstrip("$"))
                if plen > best_len or (plen == best_len and r.allow):
                    best, best_len = r, plen
        return repr(best) if best else None

    def root_disallowed(self, token):
        return not self.is_allowed("/", token)

    def to_dict(self):
        return {
            "state": self.state,
            "url": self.url,
            "groups": [{"agents": sorted(g.agents), "rules": [repr(r) for r in g.rules]} for g in self.groups],
            "sitemaps": list(self.sitemaps),
            "parse_errors": list(self.parse_errors),
        }


def _path_of(url_or_path):
    if url_or_path.startswith("/") or url_or_path == "":
        p = url_or_path or "/"
    else:
        s = urlsplit(url_or_path)
        p = s.path or "/"
        if s.query:
            p += "?" + s.query
    return _norm(p)


# ----------------------------------------------------------- bot tiers
# Token | Operator | Tier | Notes | Status -- only rows whose Status is exactly "verified" are loaded,
# so an unconfirmed row in the markdown can never reach a finding (sources.md).
_TIER_ROW = re.compile(r"^\| `([^`]+)` \| ([^|]+?) \| `(live_answer|index|training_only)` \|([^|]*)\|\s*([A-Za-z]+)\s*\|", re.M)


def load_bot_tiers(path=BOT_TIERS_MD):
    """Parse bot_tiers.md section 2 -> {token_lower: {"token": str, "operator": str, "tier": str}}.

    The markdown is the single source of truth. Returns {} (never raises) if the file is missing.
    """
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}
    tiers = {}
    for token, operator, tier, _notes, status in _TIER_ROW.findall(text):
        if status.strip().lower() != "verified":
            continue  # unverified rows are inert: see sources.md
        tiers[token.lower()] = {"token": token, "operator": operator.strip(), "tier": tier}
    return tiers


def grade_tokens(robots, tiers, key_paths=()):
    """For every known token: is '/' allowed, does it have its own group, which key paths are disallowed.

    Returns a list of dicts sorted by tier then token. Pure; Step 6 turns this into findings.
    """
    out = []
    for tok_l, info in tiers.items():
        row = {
            "token": info["token"],
            "operator": info["operator"],
            "tier": info["tier"],
            "has_own_group": robots.has_specific_group(tok_l),
            "root_allowed": robots.is_allowed("/", tok_l),
            "root_rule": robots.matching_rule("/", tok_l),
            "disallowed_key_paths": [p for p in key_paths if not robots.is_allowed(p, tok_l)],
        }
        out.append(row)
    order = {t: i for i, t in enumerate(TIERS)}
    out.sort(key=lambda r: (order.get(r["tier"], 9), r["token"].lower()))
    return out
