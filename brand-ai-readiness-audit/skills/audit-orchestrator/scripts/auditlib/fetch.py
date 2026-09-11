"""Shared fetch helper. Implements fetch_policy.md exactly. Standard library only.

    from auditlib.fetch import Fetcher
    f = Fetcher(workdir="audit-example", site="https://example.com")
    r = f.get("https://example.com/", purpose="page", save_as="snapshots/home.html")
    r["status"], r["is_html"], r["challenge"], r.text

Guarantees:
  * GET only. http/https only. Never sends a body or cookies.
  * Never raises. Every failure is a FetchResult with `error` set and `status` None.
  * Obeys robots.txt for the audit's own token and '*' (skipped=robots_disallow).
  * Enforces: connect 10s, read 15s, total 25s, 5 redirects, 2 MiB decoded body,
    one retry on 429, >= 0.5s between requests to one host, 40 requests per audit,
    optional wall-clock deadline.
"""
import datetime as _dt
import http.client
import json
import os
import re
import socket
import ssl
import sys
import time
import zlib
from urllib.parse import urljoin, urlsplit, urlunsplit, quote

from . import robots as _robots
from . import __version__

# ------------------------------------------------------------------ constants (fetch_policy.md section 2-3)
USER_AGENT = ("Mozilla/5.0 (compatible; brand-ai-readiness-audit/%s; read-only audit; "
              "+https://github.com/Sheel23501/potential-winner)" % __version__)
AUDIT_TOKEN = _robots.AUDIT_TOKEN

# Published user-agent strings for the edge-level access check (cr.access.edge_block).
# Sourced from each operator's own documentation; see references/sources.md.
# Tier annotations mirror bot_tiers.md so severity stays consistent with the robots checks.
PROBE_USER_AGENTS = (
    # OpenAI publishes the full strings (developers.openai.com/api/docs/bots, checked 2026-09-09): version 1.4.
    ("OAI-SearchBot", "index",
     "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.4; +https://openai.com/searchbot"),
    # Anthropic documents the token, not a full string (support.claude.com article 8896518, checked 2026-09-09); the
    # surrounding format is the common `compatible;` form. Only the token matters for a robots.txt or WAF rule.
    ("Claude-User", "live_answer",
     "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; Claude-User/1.0; +Claude-User@anthropic.com"),
    ("GPTBot", "training_only",
     "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.4; +https://openai.com/gptbot"),
)

# Accept-Language "*": present, but with no preference. "en" asked multilingual sites for their English edition.
# Omitting the header is worse -- bot protection reads a request with none as a bot: lemonde.fr served a 3 KB stub
# instead of its 270 KB page. A site that still redirects "*" to a language edition (lemonde.fr sends it to /en/)
# is named in the report's limitations rather than second-guessed here.
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
    "Accept-Language": "*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "close",
}
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 15.0
TOTAL_TIMEOUT = 25.0
MAX_REDIRECTS = 5
BYTE_CAP = 2 * 1024 * 1024
RETRY_AFTER_CAP = 10.0
RETRY_AFTER_DEFAULT = 3.0
MIN_DELAY = 0.5
REQUEST_BUDGET = 40
KEPT_HEADERS = ("content-type", "server", "x-robots-tag", "last-modified", "cf-mitigated", "retry-after",
                "location", "content-encoding", "content-length", "x-datadome")
HTML_TYPES = ("text/html", "application/xhtml+xml")
ERRORS = ("connect_timeout", "read_timeout", "total_timeout", "too_many_redirects", "dns_failure",
          "connection_refused", "tls_error", "budget_exhausted", "unsupported_scheme", "time_budget",
          "network_disabled", "host_not_allowed", "unknown")
WIKIDATA_HOST = "www.wikidata.org"
WIKIPEDIA_HOST = "en.wikipedia.org"
EXTERNAL_HOSTS = {WIKIDATA_HOST, WIKIPEDIA_HOST}  # entity probe only; robots.txt of these hosts is obeyed like any other

# public suffixes with a second level, for the registrable-domain heuristic
_SECOND_LEVEL = {"co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "net.uk", "com.au", "net.au", "org.au", "edu.au",
                 "co.nz", "org.nz", "co.jp", "ne.jp", "or.jp", "co.in", "net.in", "org.in", "ac.in", "com.br",
                 "com.mx", "com.sg", "com.hk", "co.za", "com.tr", "com.ar", "com.cn", "com.tw", "co.kr", "co.id",
                 "com.my", "com.ph", "com.vn", "com.pk", "com.ng", "com.eg", "com.sa", "co.il", "com.pl", "com.ua"}

# ------------------------------------------------------------------ challenge fingerprints (fetch_policy.md section 6)
_CHALLENGE = [
    ("cloudflare", {"cf-mitigated": "challenge"}, ("__cf_chl_", "challenge-platform", "<title>just a moment...</title>")),
    ("cloudflare", {"server": "cloudflare", "_status": 403}, ("attention required",)),
    ("akamai", {"server": "akamaighost"}, ("access denied", "reference #")),
    ("imperva", {}, ("_incapsula_resource", "incapsula incident id")),
    ("datadome", {"x-datadome": ""}, ()),
    ("datadome", {}, ("datadome", "captcha")),
    ("human", {}, ("_pxhd", "px-captcha", "perimeterx")),
    ("aws_waf", {}, ("awswaf", "aws-waf-token")),
    ("vercel", {}, ("vercel security checkpoint",)),
    ("generic_captcha", {}, ("recaptcha", "hcaptcha")),
]
_ALL_BODY_REQUIRED = {"akamai", "datadome"}  # vendors whose body tokens must ALL match (they are generic words)
_TAG_RE = re.compile(rb"<(script|style|noscript|template)\b.*?</\1\s*>", re.S | re.I)
_TAGS_RE = re.compile(rb"<[^>]+>")
_WORD_RE = re.compile(r"\w+", re.U)


def visible_word_count(body):
    """Rough count of words a reader would see: strips script/style/noscript/template and all tags."""
    if not body:
        return 0
    txt = _TAGS_RE.sub(b" ", _TAG_RE.sub(b" ", body))
    try:
        s = txt.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return 0
    return len(_WORD_RE.findall(s))


def detect_challenge(status, headers, body):
    """Return vendor string or None per fetch_policy.md section 6."""
    lower_body = (body[:200000] if body else b"").decode("utf-8", "replace").lower()
    words = None
    for vendor, hdrs, toks in _CHALLENGE:
        ok = True
        for k, v in hdrs.items():
            if k == "_status":
                ok = ok and status == v
            else:
                hv = headers.get(k)
                if hv is None or (v and v.lower() not in hv.lower()):
                    ok = False
        if not ok:
            continue
        if toks:
            hits = [t for t in toks if t in lower_body]
            if vendor in _ALL_BODY_REQUIRED:
                if len(hits) != len(toks):
                    continue
            elif not hits:
                continue
        elif not hdrs:
            continue
        # fingerprint matched; apply the status rule
        if status in (403, 429, 503):
            return vendor
        if status == 200 or vendor == "generic_captcha":
            if words is None:
                words = visible_word_count(body)
            if words < 60:
                return vendor
    return None


# ------------------------------------------------------------------ helpers
def registrable_domain(host):
    host = (host or "").lower().rstrip(".")
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    if ".".join(parts[-2:]) in _SECOND_LEVEL and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def normalize_url(url):
    """Add scheme if missing, lower-case host, drop fragment, keep path/query."""
    url = (url or "").strip()
    if not url:
        return url
    if "://" not in url:
        url = "https://" + url
    s = urlsplit(url)
    host = (s.hostname or "").lower()
    netloc = host
    if s.port and not ((s.scheme == "http" and s.port == 80) or (s.scheme == "https" and s.port == 443)):
        netloc = "%s:%d" % (host, s.port)
    path = s.path or "/"
    # re-quote anything unsafe but keep already-encoded sequences and reserved chars
    path = quote(path, safe="/%:@!$&'()*+,;=-._~")
    return urlunsplit((s.scheme.lower(), netloc, path, s.query, ""))


def origin_of(url):
    s = urlsplit(url)
    return "%s://%s" % (s.scheme, s.netloc)


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _charset_from(ctype, body):
    m = re.search(r"charset=([\w\-]+)", ctype or "", re.I)
    if m:
        return m.group(1).lower()
    head = body[:2048]
    m = re.search(rb'<meta[^>]+charset=["\']?([\w\-]+)', head, re.I)
    if m:
        return m.group(1).decode("ascii", "replace").lower()
    return "utf-8"


def _decompress(body, encoding):
    enc = (encoding or "").lower()
    if not body or enc in ("", "identity"):
        return body
    try:
        if "gzip" in enc:
            return zlib.decompress(body, 16 + zlib.MAX_WBITS)
        if "deflate" in enc:
            try:
                return zlib.decompress(body)
            except zlib.error:
                return zlib.decompress(body, -zlib.MAX_WBITS)
    except zlib.error:
        return body
    return body


class FetchResult(dict):
    """dict per fetch_policy.md section 7, plus in-memory `.body` (bytes) and `.text` (str)."""

    body = b""

    @property
    def text(self):
        if not self.body:
            return ""
        try:
            return self.body.decode(self.get("charset") or "utf-8", "replace")
        except LookupError:
            return self.body.decode("utf-8", "replace")

    @property
    def ok(self):
        return self.get("status") == 200 and not self.get("error") and not self.get("skipped")


# ------------------------------------------------------------------ the fetcher
class Fetcher:
    def __init__(self, workdir=None, site=None, offline=False, obey_robots=True, budget=REQUEST_BUDGET,
                 min_delay=MIN_DELAY, time_budget=None, user_agent=None, verbose=False):
        self.workdir = workdir
        self.offline = offline
        self.obey_robots = obey_robots
        self.budget = budget
        self.min_delay = min_delay
        self.deadline = (time.monotonic() + time_budget) if time_budget else None
        self.headers = dict(DEFAULT_HEADERS)
        if user_agent:
            self.headers["User-Agent"] = user_agent
        self.verbose = verbose
        self.results = []            # every FetchResult in order
        self.requests_made = 0       # every HTTP request including redirect hops and retries
        self.by_purpose = {}
        self._last_hit = {}          # host -> monotonic time
        self._robots = {}            # origin -> Robots
        self.allowed_hosts = set(EXTERNAL_HOSTS)
        self.site = None
        if site:
            self.set_site(site)

    # ------------------------------------------------------------ site / hosts
    def set_site(self, url):
        url = normalize_url(url)
        self.site = origin_of(url)
        self.allow_host(urlsplit(url).hostname)
        return self.site

    def allow_host(self, host):
        if host:
            self.allowed_hosts.add(host.lower())

    def host_allowed(self, host):
        h = (host or "").lower()
        if h in self.allowed_hosts:
            return True
        # Every Wikipedia language edition, and nothing else, once Wikipedia is allowed at all: a site's sameAs to
        # de.wikipedia.org is as authoritative as one to en., and refusing it reported "lookup unavailable" for
        # a German company that had done exactly what the audit recommends.
        labels = h.split(".")
        return (WIKIPEDIA_HOST in self.allowed_hosts and len(labels) == 3 and labels[1:] == ["wikipedia", "org"]
                and 2 <= len(labels[0]) <= 12 and labels[0].replace("-", "").isalpha())

    # ------------------------------------------------------------ robots
    def robots(self, origin=None):
        """Fetch (once per origin) and parse robots.txt. Returns Robots with state ok/missing/unreachable."""
        origin = origin or self.site
        if origin in self._robots:
            return self._robots[origin]
        url = origin.rstrip("/") + "/robots.txt"
        r = self._get(url, purpose="robots", check_robots=False, save_as="fetch/robots.txt")
        if r.get("error") or r.get("challenge") or (r.get("status") or 0) >= 500:
            rob = _robots.Robots(None, state="unreachable", url=url)
        elif r.get("status") == 200:
            rob = _robots.Robots(r.text if r.get("is_text") else "", state="ok", url=url)
        else:
            rob = _robots.Robots(None, state="missing", url=url)
        rob.fetch = r
        self._robots[origin] = rob
        return rob

    def allowed_by_robots(self, url):
        """True unless robots.txt (state ok) disallows the URL for our token or '*'."""
        if not self.obey_robots:
            return True, None
        rob = self.robots(origin_of(url))
        if rob.state != "ok":
            return True, None
        if rob.is_allowed(url, AUDIT_TOKEN):
            return True, None
        return False, rob.matching_rule(url, AUDIT_TOKEN)

    # ------------------------------------------------------------ public get
    def get(self, url, purpose="page", save_as=None, timeout=None):
        """GET `url` under the policy. Never raises. `timeout` caps the total time for this one URL (default TOTAL_TIMEOUT)."""
        try:
            return self._get(url, purpose=purpose, save_as=save_as, check_robots=True, timeout=timeout)
        except Exception as e:  # noqa: BLE001  -- the never-raise guarantee
            r = self._result(url)
            r["error"] = "unknown"
            r["error_detail"] = "%s: %s" % (type(e).__name__, e)
            self._record(r, purpose)
            return r

    def get_as(self, url, user_agent, purpose="ua_probe", timeout=None, token=None):
        """GET `url` announcing a different User-Agent, then restore the default.

        Used only by the edge-level access check (`cr.access.edge_block`), which
        asks a question robots.txt cannot answer: does the server actually serve
        this page to a declared AI crawler, or does a CDN/WAF refuse it?

        The announced token is held to the site's robots.txt as if it were the
        real crawler: a token robots.txt disallows for this URL is never sent.
        The call returns a skipped result (`skipped=robots_disallow_for_token`,
        with the matched rule) and makes no request, whoever the caller is.
        `token` names the crawler; when omitted it is inferred from the
        published strings in PROBE_USER_AGENTS, and an agent that cannot be
        named is not sent at all (`skipped=unknown_token`). When robots.txt
        could not be read, no permission can be decided and the request is
        skipped as `robots_unreachable`.

        Still a plain GET under the same budget and politeness delay as every
        other request. We announce a crawler's published token to observe how
        the origin responds; we never use it to get around a refusal.
        """
        url = normalize_url(url)
        if token is None:
            token = next((t for t, _tier, ua in PROBE_USER_AGENTS if ua == user_agent or t.lower() in (user_agent or "").lower()), None)
        r = self._result(url)
        r["announced_token"] = token
        if not token:
            r["skipped"] = "unknown_token"
            self._record(r, purpose); return r
        if not self.offline:
            rob = self.robots(origin_of(url))
            if rob.state not in ("ok", "missing"):
                r["skipped"] = "robots_unreachable"
                self._record(r, purpose); return r
            if not rob.is_allowed(url, token):
                r["skipped"] = "robots_disallow_for_token"
                r["skipped_rule"] = rob.matching_rule(url, token)
                self._record(r, purpose); return r
        previous = self.headers.get("User-Agent")
        self.headers["User-Agent"] = user_agent
        try:
            r = self.get(url, purpose=purpose, timeout=timeout)
            r["announced_token"] = token
            return r
        finally:
            if previous is None:
                self.headers.pop("User-Agent", None)
            else:
                self.headers["User-Agent"] = previous

    # ------------------------------------------------------------ internals
    def _result(self, url):
        r = FetchResult(url=url, final_url=url, redirect_chain=[], cross_domain=False, status=None, headers={},
                        content_type=None, charset=None, is_html=False, is_text=False, bytes=0, truncated=False,
                        elapsed_ms=0, challenge=False, challenge_vendor=None, blocked=False, skipped=None,
                        error=None, fetched_at=_now(), body_path=None)
        r.body = b""
        return r

    def _record(self, r, purpose):
        self.results.append(r)
        self.by_purpose[purpose] = self.by_purpose.get(purpose, 0) + 1
        if self.verbose:
            sys.stderr.write("[fetch] %-7s %s -> %s %s%s\n" % (purpose, r["url"], r.get("status"), r.get("error") or "",
                                                              " skipped=" + r["skipped"] if r.get("skipped") else ""))

    def _get(self, url, purpose, save_as=None, check_robots=True, timeout=None):
        total = min(TOTAL_TIMEOUT, timeout) if timeout else TOTAL_TIMEOUT
        url = normalize_url(url)
        r = self._result(url)
        s = urlsplit(url)
        if s.scheme not in ("http", "https"):
            r["error"] = "unsupported_scheme"
            self._record(r, purpose); return r
        if self.offline:
            r["error"] = "network_disabled"
            self._record(r, purpose); return r
        if self.site is None:
            self.set_site(url)
        if not self.host_allowed(s.hostname):
            r["error"] = "host_not_allowed"
            self._record(r, purpose); return r
        if check_robots:
            ok, rule = self.allowed_by_robots(url)
            if not ok:
                r["skipped"] = "robots_disallow"
                r["skipped_rule"] = rule
                self._record(r, purpose); return r
        start = time.monotonic()
        current = url
        retried = False
        hops = 0
        while True:
            if self.deadline and time.monotonic() > self.deadline:
                r["error"] = "time_budget"; break
            if self.requests_made >= self.budget:
                r["error"] = "budget_exhausted"; break
            remaining = total - (time.monotonic() - start)
            if remaining <= 0:
                r["error"] = "total_timeout"; break
            status, headers, body, err, truncated = self._one_request(current, remaining)
            self.requests_made += 1
            if err:
                r["error"] = err; break
            r["status"] = status
            r["headers"] = headers
            r["final_url"] = current
            if status in (301, 302, 303, 307, 308) and headers.get("location"):
                hops += 1
                if hops > MAX_REDIRECTS:
                    r["error"] = "too_many_redirects"; break
                r["redirect_chain"].append(current)
                nxt = normalize_url(urljoin(current, headers["location"]))
                ns = urlsplit(nxt)
                if ns.scheme not in ("http", "https"):
                    r["error"] = "unsupported_scheme"; break
                if registrable_domain(ns.hostname) != registrable_domain(urlsplit(url).hostname):
                    r["cross_domain"] = True
                self.allow_host(ns.hostname)  # a host reached by redirect from the site is allowed
                current = nxt
                continue
            if status == 429 and not retried:
                retried = True
                wait = RETRY_AFTER_DEFAULT
                ra = headers.get("retry-after")
                if ra and ra.strip().isdigit():
                    wait = min(float(ra.strip()), RETRY_AFTER_CAP)
                wait = min(wait, max(0.0, total - (time.monotonic() - start)))
                time.sleep(wait)
                continue
            # final response
            r["truncated"] = truncated
            r.body = body
            r["bytes"] = len(body)
            ctype_full = headers.get("content-type") or ""
            ctype = ctype_full.split(";")[0].strip().lower()
            if not ctype:
                sniff = body.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
                ctype = "text/html" if sniff == b"<" else "application/octet-stream"
                r["content_type_sniffed"] = True
            r["content_type"] = ctype
            r["is_html"] = ctype in HTML_TYPES
            r["is_text"] = r["is_html"] or ctype.startswith("text/") or ctype in ("application/xml", "application/json",
                                                                                 "application/ld+json", "application/rss+xml")
            r["charset"] = _charset_from(ctype_full, body) if r["is_text"] else None
            vendor = detect_challenge(status, headers, body)
            if vendor:
                r["challenge"], r["challenge_vendor"] = True, vendor
            elif status in (403, 429):
                r["blocked"] = True
            break
        r["elapsed_ms"] = int((time.monotonic() - start) * 1000)
        if save_as and r.body and not r.get("error") and (r.get("status") == 200 or not save_as.startswith("fetch/robots")):
            r["body_path"] = self._save(save_as, r.body)
        self._record(r, purpose)
        return r

    def _one_request(self, url, remaining):
        """Single HTTP GET. Returns (status, headers_subset, body, error, truncated)."""
        s = urlsplit(url)
        host = s.hostname
        port = s.port or (443 if s.scheme == "https" else 80)
        self._politeness(host)
        connect_to = min(CONNECT_TIMEOUT, remaining)
        try:
            if s.scheme == "https":
                ctx = ssl.create_default_context()
                conn = http.client.HTTPSConnection(host, port, timeout=connect_to, context=ctx)
            else:
                conn = http.client.HTTPConnection(host, port, timeout=connect_to)
            path = s.path or "/"
            if s.query:
                path += "?" + s.query
            hdrs = dict(self.headers)
            hdrs["Host"] = s.netloc
            try:
                conn.connect()
            except socket.timeout:
                return None, {}, b"", "connect_timeout", False
            except ssl.SSLError:
                return None, {}, b"", "tls_error", False
            except socket.gaierror:
                return None, {}, b"", "dns_failure", False
            except ConnectionRefusedError:
                return None, {}, b"", "connection_refused", False
            except OSError as e:
                if isinstance(e, ssl.SSLError):
                    return None, {}, b"", "tls_error", False
                return None, {}, b"", "connection_refused" if getattr(e, "errno", None) in (61, 111) else "unknown", False
            conn.sock.settimeout(min(READ_TIMEOUT, remaining))
            conn.request("GET", path, headers=hdrs)
            resp = conn.getresponse()
            headers = {}
            for k, v in resp.getheaders():
                kl = k.lower()
                if kl in KEPT_HEADERS:
                    headers[kl] = v if kl not in headers else headers[kl] + ", " + v
            # stream the body with a decoded-byte cap and the total deadline
            enc = (headers.get("content-encoding") or "").lower()
            decomp = None
            if "gzip" in enc:
                decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
            elif "deflate" in enc:
                decomp = zlib.decompressobj()
            chunks, total, truncated = [], 0, False
            t0 = time.monotonic()
            while True:
                if time.monotonic() - t0 > remaining:
                    conn.close()
                    return None, {}, b"", "total_timeout", False
                try:
                    chunk = resp.read(65536)
                except socket.timeout:
                    conn.close()
                    return None, {}, b"", "read_timeout", False
                if not chunk:
                    break
                if decomp is not None:
                    try:
                        chunk = decomp.decompress(chunk)
                    except zlib.error:
                        # not really compressed: fall back to raw bytes from here on
                        decomp = None
                chunks.append(chunk)
                total += len(chunk)
                if total >= BYTE_CAP:
                    truncated = True
                    break
            conn.close()
            body = b"".join(chunks)
            if truncated:
                body = body[:BYTE_CAP]
            return resp.status, headers, body, None, truncated
        except socket.timeout:
            return None, {}, b"", "read_timeout", False
        except ssl.SSLError:
            return None, {}, b"", "tls_error", False
        except socket.gaierror:
            return None, {}, b"", "dns_failure", False
        except ConnectionRefusedError:
            return None, {}, b"", "connection_refused", False
        except (http.client.HTTPException, OSError, ValueError) as e:
            return None, {}, b"", "unknown", False

    def _politeness(self, host):
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.min_delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    def _save(self, rel, body):
        if not self.workdir:
            return None
        path = os.path.join(self.workdir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(body)
        return rel

    # ------------------------------------------------------------ manifest
    def manifest(self):
        return {
            "site": self.site,
            "user_agent": self.headers["User-Agent"],
            "requests_made": self.requests_made,
            "by_purpose": dict(self.by_purpose),
            "budget": self.budget,
            "offline": self.offline,
            "robots": {o: rob.to_dict() for o, rob in self._robots.items()},
            "fetches": [dict(r) for r in self.results],
        }

    def save_manifest(self, rel="fetch/manifest.json"):
        if not self.workdir:
            return None
        path = os.path.join(self.workdir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.manifest(), f, indent=2, ensure_ascii=False)
        return rel
