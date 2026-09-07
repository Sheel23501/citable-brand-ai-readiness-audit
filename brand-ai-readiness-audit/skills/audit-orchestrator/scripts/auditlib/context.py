"""AuditContext: everything a probe needs, loaded from a workdir (orchestrator mode) or built from a URL.

    ctx = AuditContext.from_workdir("audit-example")     # sample.json + snapshots/ + fetch/robots.txt
    ctx = AuditContext.from_url("https://example.com", workdir="audit-example")  # runs the sampler first
    ctx.site, ctx.category, ctx.pages -> [Page(role, url, fetch, doc)], ctx.robots (Robots), ctx.sitemap (dict)

Never raises: a missing or broken workdir yields a context with `error` set and no pages.
"""
import json
import os

from .fetch import Fetcher
from .htmldoc import Document
from .robots import Robots
from .sampler import sample_site


class Page:
    __slots__ = ("role", "url", "final_url", "source", "fetch", "doc", "summary")

    def __init__(self, entry, doc):
        self.role = entry.get("role")
        self.url = entry.get("url")
        self.final_url = entry.get("final_url") or entry.get("url")
        self.source = entry.get("source")
        self.fetch = entry.get("fetch") or {}
        self.doc = doc
        self.summary = entry.get("summary")

    @property
    def status(self):
        return self.fetch.get("status")

    @property
    def ok_html(self):
        return self.doc is not None

    @property
    def skipped(self):
        return self.fetch.get("skipped")

    @property
    def challenge(self):
        return bool(self.fetch.get("challenge"))

    @property
    def error(self):
        return self.fetch.get("error")

    def __repr__(self):
        return "Page(%s %s status=%s html=%s)" % (self.role, self.final_url, self.status, self.ok_html)


class AuditContext:
    def __init__(self, workdir=None):
        self.workdir = workdir
        self.manifest = {}
        self.site = None
        self.category = "unknown"
        self.category_info = {}
        self.pages = []
        self.robots = Robots(None, state="unreachable")
        self.sitemap = {"state": "missing"}
        self.error = None
        self.fetcher = None

    # ------------------------------------------------------------ constructors
    @classmethod
    def from_workdir(cls, workdir):
        ctx = cls(workdir)
        try:
            with open(os.path.join(workdir, "sample.json"), encoding="utf-8") as f:
                ctx.manifest = json.load(f)
        except Exception as e:  # noqa: BLE001
            ctx.error = "cannot read sample.json: %s" % e
            return ctx
        ctx._load()
        return ctx

    @classmethod
    def from_url(cls, url, workdir, offline=False, category_override=None, obey_robots=True):
        ctx = cls(workdir)
        try:
            os.makedirs(workdir, exist_ok=True)
            ctx.fetcher = Fetcher(workdir=workdir, site=url, offline=offline, obey_robots=obey_robots)
            ctx.manifest = sample_site(ctx.fetcher, url, category_override=category_override, save=True)
        except Exception as e:  # noqa: BLE001
            ctx.error = "sampler failed: %s" % e
            return ctx
        ctx._load()
        return ctx

    # ------------------------------------------------------------ loading
    def _load(self):
        m = self.manifest
        self.site = m.get("site")
        sc = m.get("site_category") or {}
        self.category = sc.get("value") or "unknown"
        self.category_info = sc
        self.sitemap = m.get("sitemap") or {"state": "missing"}
        rob = m.get("robots") or {}
        text = None
        rpath = rob.get("path")
        if rpath and self.workdir:
            try:
                with open(os.path.join(self.workdir, rpath), encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                text = None
        state = rob.get("state") or "unreachable"
        self.robots = Robots(text if state == "ok" else None, state=state, url=rob.get("url"))
        if state == "ok" and text is None:
            # sampler said ok but body is unavailable: treat as unreachable for grading, say so
            self.robots = Robots(None, state="unreachable", url=rob.get("url"))
            self.robots.parse_errors.append("robots body not available in workdir")
        for entry in m.get("pages", []):
            doc = None
            fr = entry.get("fetch") or {}
            bp = fr.get("body_path")
            if fr.get("status") == 200 and fr.get("is_html") and not fr.get("challenge") and bp and self.workdir:
                try:
                    with open(os.path.join(self.workdir, bp), "rb") as f:
                        raw = f.read()
                    doc = Document(raw.decode(fr.get("charset") or "utf-8", "replace"), base_url=fr.get("final_url") or entry.get("url"))
                except Exception:  # noqa: BLE001
                    doc = None
            self.pages.append(Page(entry, doc))

    # ------------------------------------------------------------ helpers
    @property
    def home(self):
        for p in self.pages:
            if p.role == "home":
                return p
        return None

    def page(self, role):
        for p in self.pages:
            if p.role == role:
                return p
        return None

    @property
    def html_pages(self):
        return [p for p in self.pages if p.ok_html]

    @property
    def examined_urls(self):
        return [p.final_url for p in self.pages if p.status is not None or p.skipped]

    def key_roles(self):
        from .categories import key_pages
        return key_pages(self.category)
