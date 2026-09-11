"""Lightweight HTML document model built on html.parser. Standard library only.

    from auditlib.htmldoc import Document
    doc = Document(html_text, base_url="https://example.com/")
    doc.title, doc.meta("description"), doc.links, doc.jsonld, doc.visible_text, ...

Extracts what the sampler and probes need from the *served* HTML. It never
executes scripts or fetches sub-resources; that is the point of the audit.
Never raises on malformed HTML (html.parser is tolerant; we guard the rest).
"""
import collections
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urldefrag


# Function words are the cheapest reliable language signal: they are short, extremely frequent, and mostly
# distinct between these languages. This is not a general language identifier -- it only has to answer
# "is this page written in a language whose vocabulary the audit carries", and it only votes when the
# margin is decisive, so an English page quoting a French sentence does not flip.
STOPWORDS = {
    "en": ("the", "and", "for", "with", "you", "your", "our", "that", "this", "from", "are", "have", "more", "about"),
    "de": ("und", "der", "die", "das", "mit", "für", "fuer", "sie", "ist", "auf", "den", "von", "nicht", "wir", "auch"),
    "fr": ("les", "des", "une", "pour", "avec", "vous", "nous", "que", "qui", "dans", "sur", "est", "pas", "plus", "sont"),
    "es": ("los", "las", "una", "para", "con", "que", "por", "más", "mas", "como", "pero", "sus", "este", "son"),
    "it": ("gli", "che", "per", "con", "una", "non", "sono", "come", "anche", "nel", "alla", "dei", "delle", "questo"),
    "pt": ("dos", "das", "uma", "para", "com", "que", "por", "mais", "como", "sua", "seu", "não", "nao", "são"),
    "nl": ("het", "een", "van", "met", "voor", "zijn", "niet", "ook", "maar", "deze", "onze", "wordt", "aan", "bij"),
}
_LANG_WORD_RE = re.compile(r"[a-zà-ÿA-ZÀ-Ý]{2,}")  # own name: _WORD_RE below is the word counter


def language_from_text(text, min_words=120, margin=1.6):
    """The language the words themselves suggest, or None when nothing wins clearly.

    Real sites mislabel pages: a template's lang attribute can survive onto pages written in another language. A gate that trusts the
    attribute alone is inert exactly where it is needed, so the attribute is corroborated against this.
    Returns None on short text or a close call -- an uncertain guess is worse than no guess here, because
    the caller uses it to decide whether a finding may be asserted at full strength.
    """
    words = [w.lower() for w in _LANG_WORD_RE.findall(text or "")]
    if len(words) < min_words:
        return None
    counts = collections.Counter(words)
    scores = {lang: sum(counts[w] for w in ws) for lang, ws in STOPWORDS.items()}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top, second = ranked[0], ranked[1]
    if top[1] < 8:
        return None
    if second[1] and top[1] < second[1] * margin:
        return None
    return top[0]

_SKIP_TEXT = {"script", "style", "noscript", "template", "svg", "head"}
_BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer", "nav",
          "main", "aside", "tr", "td", "th", "br", "ul", "ol", "table", "blockquote", "figure", "figcaption", "dd", "dt"}
_INLINE = {"b", "i", "em", "strong", "span", "u", "sup", "sub", "small", "mark", "abbr", "code", "s", "del", "ins", "q", "cite",
           "dfn", "var", "kbd", "samp", "bdi", "bdo", "font", "wbr"}
_CONTEXT_TAGS = ("nav", "header", "footer", "main", "aside", "article", "form")
_HEAD_TAGS = {"html", "head", "meta", "link", "title", "script", "style", "base", "noscript", "template"}
_ROOT_IDS = ("root", "app", "__next", "__nuxt", "___gatsby", "app-root", "svelte", "q-app", "main-app", "react-root", "ember-app")
_WORD_RE = re.compile(r"\w+", re.U)
_TAGS_RE_STR = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
PRICE_RE = re.compile(r"(?:(?<![\w.])[$£€¥₹]\s?\d[\d,]*(?:\.\d+)?)|(?:\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP|INR|CAD|AUD|JPY|CHF)\b)")


class Link:
    __slots__ = ("href", "url", "text", "context", "rel", "internal", "in_head", "mpos", "in_list")

    def __init__(self, href, url, text, context, rel, internal, in_head=False, mpos=None, in_list=False):
        self.href, self.url, self.text, self.context, self.rel, self.internal, self.in_head = href, url, text, context, rel, internal, in_head
        self.mpos = mpos          # fraction of the served markup at which the <a> starts (0..1), None if unknown
        self.in_list = in_list    # inside a <ul>/<ol>

    def to_dict(self):
        return {"href": self.href, "url": self.url, "text": self.text, "context": self.context, "internal": self.internal}

    def __repr__(self):
        return "Link(%r, %r, %s)" % (self.url, self.text, self.context)


class _Parser(HTMLParser):
    def __init__(self, doc):
        super().__init__(convert_charrefs=True)
        self.doc = doc
        self.stack = []
        self.ctx = []            # nav/header/footer/main... currently open
        self.skip_depth = 0      # inside script/style/etc
        self.cur_link = None     # [attrs, text_parts]
        self.cur_heading = None  # [tag, text_parts]
        self.cur_script = None   # [attrs, text_parts]
        self.cur_title = None
        self.in_body = False
        self.text_parts = []
        self.body_text_parts = []
        self.div_stack = []      # (id, has_content_flag_index)
        self.chrome_open = []    # (tag, links_at_open, body_parts_at_open) for open <header>/<footer>
        self.list_depth = 0      # open <ul>/<ol>
        self.open_overlays = []  # [candidate_index, stack_len_after_push, body_parts_start]
        self.cur_quote = None    # [text_parts, mpos] inside <blockquote>
        self._line_starts = [0]
        self._len = 1

    # -- helpers
    def _ctx(self):
        return self.ctx[-1] if self.ctx else ("body" if self.in_body else "head")

    def _mpos(self):
        """Fraction of the served markup (0..1) at the current tag; None if the parser cannot say."""
        try:
            line, off = self.getpos()
            return min(1.0, max(0.0, (self._line_starts[line - 1] + off) / float(self._len)))
        except Exception:  # noqa: BLE001
            return None

    def _close_overlays(self, end_mpos):
        d = self.doc
        keep = []
        for idx, stack_len, start in self.open_overlays:
            if len(self.stack) < stack_len:
                text = "".join(self.body_text_parts[start:])
                c = d.overlay_candidates[idx]
                c["words"] = len(_WORD_RE.findall(text))
                c["text"] = _clean(text)[:160]
                c["end_mpos"] = end_mpos
            else:
                keep.append([idx, stack_len, start])
        self.open_overlays = keep

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        d = self.doc
        mpos = self._mpos()
        if not self.in_body and tag not in _HEAD_TAGS:
            self.in_body = True  # pages that omit <body> (or fragments) still get body semantics
            if d.body_mpos is None:
                d.body_mpos = mpos
        if tag == "html":
            d.lang = (a.get("lang") or "").strip() or None
        elif tag == "body":
            self.in_body = True
            d.body_attrs = {k.lower(): (v or "") for k, v in attrs}
            if d.body_mpos is None:
                d.body_mpos = mpos
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or a.get("http-equiv") or "").strip().lower()
            if key and "content" in a:
                d.metas.setdefault(key, (a.get("content") or "").strip())
            if key == "refresh":
                d.meta_refresh = (a.get("content") or "").strip()
            if a.get("charset"):
                d.charset = a["charset"].lower()
        elif tag == "link":
            rel = (a.get("rel") or "").lower().split()
            href = a.get("href")
            if href and "canonical" in rel:
                d.canonical = d._abs(href)
            if href and "alternate" in rel and "rss" in (a.get("type") or "").lower() + "|" + "".join(rel):
                d.feeds.append(d._abs(href))
            if href and "alternate" in rel and a.get("hreflang"):
                d.hreflangs.append(a.get("hreflang"))
            if href and "stylesheet" in rel:
                d.stylesheets.append(d._abs(href))
        elif tag == "title" and not d.title_seen:
            self.cur_title = []
        elif tag == "noscript":
            self.cur_noscript = []
        elif tag == "script":
            t = (a.get("type") or "").lower().strip()
            self.cur_script = [a, []]
            if a.get("src"):
                d.external_scripts.append(d._abs(a["src"]))
            if t != "application/ld+json":
                d.script_tags += 1
        elif tag == "a":
            self.cur_link = [a, [], mpos]
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.cur_heading = [tag, [], mpos]
        elif tag in ("ul", "ol"):
            self.list_depth += 1
        elif tag == "blockquote":
            self.cur_quote = [[], mpos]
        elif tag == "article":
            d.article_count += 1
        elif tag == "img":
            d.images.append({"src": d._abs(a.get("src") or a.get("data-src") or ""), "alt": a.get("alt"),
                             "width": _int(a.get("width")), "height": _int(a.get("height")),
                             "role": (a.get("role") or "").lower(), "context": self._ctx(),
                             "loading": a.get("loading"), "pos": len(self.body_text_parts), "mpos": mpos})
            # an image anchors the content only where a visitor would see it: not a tracking pixel in <noscript>,
            # not an icon inside an inline <svg> or <template>
            if d.content_mpos is None and mpos is not None and getattr(self, "cur_noscript", None) is None \
                    and not any(t in _SKIP_TEXT for t in self.stack):
                d.content_mpos = mpos
        elif tag == "form":
            d.forms.append({"action": d._abs(a.get("action") or ""), "role": (a.get("role") or "").lower(),
                            "id": a.get("id") or "", "cls": a.get("class") or "", "label": a.get("aria-label") or "",
                            "method": (a.get("method") or "get").lower(), "inputs": [], "context": self._ctx(), "mpos": mpos})
        elif tag == "input" and d.forms:
            d.forms[-1]["inputs"].append({"type": (a.get("type") or "text").lower(), "name": a.get("name"), "id": a.get("id"),
                                          "placeholder": a.get("placeholder") or "", "label": a.get("aria-label") or ""})
        elif tag == "button" or (tag == "input" and (a.get("type") or "").lower() in ("submit", "button")):
            d.buttons.append({"text": (a.get("value") or "").strip(), "context": self._ctx(), "pos": len(self.body_text_parts), "mpos": mpos})
            if tag == "button":
                self.cur_button = [a, []]
        elif tag == "time":
            if a.get("datetime"):
                d.times.append(a["datetime"].strip())
        elif tag == "div":
            self.div_stack.append([a.get("id") or "", a.get("class") or "", False])
        if tag == "iframe":
            d.iframes.append(d._abs(a.get("src") or ""))
        # attribute-based landmarks
        role = (a.get("role") or "").lower()
        if tag == "nav" or role == "navigation":
            d.nav_count += 1
        if role == "search":
            d.search_roles += 1
        if tag in ("header", "footer"):
            self.chrome_open.append((tag, len(d.links), len(self.body_text_parts)))
        if tag in ("nav", "header", "footer", "main", "aside", "article", "form"):
            self.ctx.append(tag)
            self.stack.append((tag, True))
        else:
            self.stack.append((tag, False))
        if tag in _SKIP_TEXT:
            self.skip_depth += 1
        cls = (a.get("class") or "").lower()
        ident = (a.get("id") or "").lower()
        if tag in ("nav", "ol", "ul", "div") and ("breadcrumb" in cls or "breadcrumb" in ident or "breadcrumb" in (a.get("aria-label") or "").lower()):
            d.breadcrumb_markup = True
        if any(k in cls or k in ident for k in ("modal", "overlay", "popup", "interstitial", "cookie", "consent", "lightbox", "newsletter-popup")):
            style = (a.get("style") or "").lower()
            hidden = ("hidden" in a) or (a.get("aria-hidden") or "").strip().lower() == "true" or bool(re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", style))
            pm = re.search(r"position\s*:\s*(fixed|absolute|sticky)", style)
            d.overlay_candidates.append({"tag": tag, "id": ident, "class": cls, "pos": len(self.body_text_parts), "style": a.get("style") or "",
                                         "mpos": mpos, "hidden": hidden, "position": pm.group(1) if pm else None, "words": 0, "text": "", "end_mpos": None})
            # the element closes when the stack drops below its depth (the push above already happened)
            self.open_overlays.append([len(d.overlay_candidates) - 1, len(self.stack), len(self.body_text_parts)])
        if "itemtype" in a or "typeof" in a or "vocab" in a:
            d.microdata_hint = True  # Microdata / RDFa present; not parsed, only noted
        if tag in _BLOCK:
            self.text_parts.append("\n")
            if self.in_body:
                self.body_text_parts.append("\n")
        elif tag not in _INLINE:
            self.text_parts.append(" ")
            if self.in_body:
                self.body_text_parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in ("img", "meta", "link", "br", "input", "hr", "source", "track", "wbr", "area", "base", "col", "embed", "param"):
            self.handle_endtag(tag)
        elif tag in _SKIP_TEXT:
            self.skip_depth -= 1

    def handle_endtag(self, tag):
        d = self.doc
        if tag in ("header", "footer") and self.chrome_open:
            # served with no link and almost no text: the page's header or footer is filled in by a script
            for i in range(len(self.chrome_open) - 1, -1, -1):
                if self.chrome_open[i][0] == tag:
                    _, n_links, n_parts = self.chrome_open.pop(i)
                    if len(d.links) == n_links and len(" ".join(self.body_text_parts[n_parts:]).strip()) < 40:
                        d.empty_chrome.append(tag)
                    break
        if tag == "head":
            self.in_body = True
        # pop stack to the matching tag (tolerate bad nesting)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for t, is_ctx in self.stack[i:]:
                    if is_ctx and self.ctx:
                        self.ctx.pop()
                    if t in _SKIP_TEXT and self.skip_depth > 0:
                        self.skip_depth -= 1
                del self.stack[i:]
                break
        if self.open_overlays:
            self._close_overlays(self._mpos())
        if tag in ("ul", "ol"):
            self.list_depth = max(0, self.list_depth - 1)
        if tag == "blockquote" and self.cur_quote is not None:
            parts, qm = self.cur_quote
            qt = _clean(" ".join(parts))
            d.blockquotes.append({"text": qt[:300], "words": len(_WORD_RE.findall(qt)), "mpos": qm})
            self.cur_quote = None
        if tag == "title" and self.cur_title is not None:
            d.title = _clean(" ".join(self.cur_title)) or None
            d.title_seen = True
            self.cur_title = None
        elif tag == "script" and self.cur_script is not None:
            a, parts = self.cur_script
            raw = "".join(parts)
            d.script_bytes += len(raw.encode("utf-8", "replace"))
            t = (a.get("type") or "").lower().strip()
            if t == "application/ld+json":
                d.jsonld_raw.append(raw.strip())
            elif t in ("", "text/javascript", "application/javascript", "module") and len(d.inline_scripts_text) < 200000:
                d.inline_scripts_text += raw[:200000 - len(d.inline_scripts_text)]
            self.cur_script = None
        elif tag == "noscript" and getattr(self, "cur_noscript", None) is not None:
            d.noscript_texts.append(_clean(" ".join(self.cur_noscript)))
            self.cur_noscript = None
        elif tag == "a" and self.cur_link is not None:
            a, parts, lm = self.cur_link
            href = (a.get("href") or "").strip()
            text = _clean(" ".join(parts))
            if not text:
                text = _clean(a.get("aria-label") or a.get("title") or "")
            if href:
                url = d._abs(href)
                scheme = urlsplit(url).scheme
                internal = d._is_internal(url) if scheme in ("http", "https") else False
                d.links.append(Link(href, url, text, self._ctx(), (a.get("rel") or "").lower(), internal, not self.in_body,
                                    mpos=lm, in_list=self.list_depth > 0))
            self.cur_link = None
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self.cur_heading is not None:
            t, parts, hm = self.cur_heading
            d.headings.append({"tag": t, "text": _clean(" ".join(parts)), "context": self._ctx(), "pos": len(self.body_text_parts), "mpos": hm})
            if d.content_mpos is None and hm is not None:
                d.content_mpos = hm
            self.cur_heading = None
        elif tag == "button" and getattr(self, "cur_button", None):
            a, parts = self.cur_button
            if d.buttons and not d.buttons[-1]["text"]:
                d.buttons[-1]["text"] = _clean(" ".join(parts))
            self.cur_button = None
        elif tag == "div" and self.div_stack:
            ident, cls, had_content = self.div_stack.pop()
            if not had_content and ident.lower() in _ROOT_IDS:
                d.empty_root_containers.append(ident)
            elif not had_content and cls and any(c in cls.lower().split() for c in ("app", "root")):
                d.empty_root_containers.append("." + cls.split()[0])
        if tag in _BLOCK:
            self.text_parts.append("\n")
            if self.in_body:
                self.body_text_parts.append("\n")
        elif tag not in _INLINE:
            self.text_parts.append(" ")
            if self.in_body:
                self.body_text_parts.append(" ")

    def handle_data(self, data):
        if self.cur_script is not None:
            self.cur_script[1].append(data)
            return
        if getattr(self, "cur_noscript", None) is not None:
            # html.parser hands noscript content through as data when scripting is off; keep raw text sans tags
            self.cur_noscript.append(_TAGS_RE_STR.sub(" ", data))
        if self.cur_title is not None:
            self.cur_title.append(data)
        if self.skip_depth:
            return
        if not data.strip():
            return
        if self.cur_link is not None:
            self.cur_link[1].append(data)
        if self.cur_heading is not None:
            self.cur_heading[1].append(data)
        if self.cur_quote is not None:
            self.cur_quote[0].append(data)
        if getattr(self, "cur_button", None):
            self.cur_button[1].append(data)
        for entry in self.div_stack:
            entry[2] = True
        self.text_parts.append(data)
        if self.in_body:
            self.body_text_parts.append(data)
            if data.strip() and self.doc.content_mpos is None:
                self.doc.content_mpos = self._mpos()


def _int(v):
    try:
        return int(str(v).strip().rstrip("px")) if v not in (None, "") else None
    except ValueError:
        return None


def _clean(s):
    return _WS_RE.sub(" ", s or "").strip()


class Document:
    def __init__(self, html, base_url=None):
        self.base_url = base_url or ""
        self._host = (urlsplit(self.base_url).hostname or "").lower()
        self.title = None
        self.title_seen = False
        self.lang = None
        self.charset = None
        self.canonical = None
        self.metas = {}
        self.links = []
        self.images = []
        self.headings = []
        self.jsonld_raw = []
        self.external_scripts = []
        self.script_bytes = 0
        self.forms = []
        self.buttons = []
        self.times = []
        self.feeds = []
        self.hreflangs = []
        self.iframes = []
        self.nav_count = 0
        self.search_roles = 0
        self.breadcrumb_markup = False
        self.microdata_hint = False
        self.overlay_candidates = []
        self.empty_root_containers = []
        self.empty_chrome = []
        self.body_mpos = None        # markup fraction where <body> (or the first body-level tag) starts
        self.content_mpos = None     # markup fraction of the first visible content (text, heading, image): the viewport starts here
        self.stylesheets = []
        self.script_tags = 0         # <script> elements other than ld+json
        self.article_count = 0       # <article> elements (two or more = a listing page)
        self.blockquotes = []
        self.body_attrs = {}
        self.meta_refresh = None
        self.noscript_texts = []
        self.inline_scripts_text = ""
        self.html_bytes = len(html.encode("utf-8", "replace")) if isinstance(html, str) else len(html)
        self.parse_error = None
        p = _Parser(self)
        text = html if isinstance(html, str) else html.decode("utf-8", "replace")
        p._len = max(len(text), 1)
        p._line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
        try:
            p.feed(text)
            p.close()
        except Exception as e:  # noqa: BLE001
            self.parse_error = "%s: %s" % (type(e).__name__, e)
        if p.open_overlays:  # unclosed overlays end with the document
            p.stack = []
            p._close_overlays(1.0)
        self._text = _WS_RE.sub(" ", "".join(p.text_parts).replace("\n", " \n ")).strip()
        self._body_text = _WS_RE.sub(" ", "".join(p.body_text_parts).replace("\n", " \n ")).strip()
        self._jsonld = None

    # -- positions
    def body_frac(self, mpos):
        """Position within the content markup as a fraction 0..1 (None when unknown). 0.4 = the first 40% of the content.

        Anchored on the first visible content, not on <body>: a page may open with hundreds of kilobytes of inline
        SVG, style or script before its first word (measured: a restaurant home whose first link sat at 60% of the
        body markup), and "the first 40% of the body" would then hold nothing a visitor sees."""
        if mpos is None:
            return None
        start = self.content_mpos if self.content_mpos is not None else (self.body_mpos or 0.0)
        span = max(1.0 - start, 1e-9)
        return max(0.0, min(1.0, (mpos - start) / span))

    # -- url helpers
    def _abs(self, href):
        try:
            return urldefrag(urljoin(self.base_url, href.strip()))[0]
        except Exception:  # noqa: BLE001
            return href

    def _is_internal(self, url):
        h = (urlsplit(url).hostname or "").lower()
        if not h or not self._host:
            return False
        return h == self._host or h.lstrip("www.") == self._host.lstrip("www.") and h.replace("www.", "", 1) == self._host.replace("www.", "", 1)

    # -- content
    @property
    def visible_text(self):
        return self._text

    @property
    def body_text(self):
        return self._body_text or self._text

    @property
    def word_count(self):
        return len(_WORD_RE.findall(self.body_text))

    @property
    def robots_meta(self):
        """Lower-cased content of <meta name=robots> plus any bot-specific robots metas (googlebot, bingbot)."""
        vals = [v for k, v in self.metas.items() if k in ("robots", "googlebot", "bingbot")]
        return ", ".join(v.lower() for v in vals if v)

    def meta(self, *keys):
        for k in keys:
            v = self.metas.get(k.lower())
            if v:
                return v
        return None

    @property
    def h1s(self):
        return [h["text"] for h in self.headings if h["tag"] == "h1"]

    @property
    def jsonld(self):
        """List of {"raw", "data", "error", "types"} for every ld+json block."""
        if self._jsonld is None:
            out = []
            for raw in self.jsonld_raw:
                entry = {"raw": raw, "data": None, "error": None, "types": []}
                try:
                    entry["data"] = json.loads(raw)
                    entry["types"] = jsonld_types(entry["data"])
                except Exception as e:  # noqa: BLE001
                    entry["error"] = "%s: %s" % (type(e).__name__, e)
                out.append(entry)
            self._jsonld = out
        return self._jsonld

    @property
    def jsonld_types(self):
        s = []
        for b in self.jsonld:
            for t in b["types"]:
                if t not in s:
                    s.append(t)
        return s

    def jsonld_nodes(self, *types):
        """Flatten all parsed JSON-LD nodes (following @graph and nested objects) optionally filtered by @type."""
        want = set(types)
        out = []
        for b in self.jsonld:
            if b["data"] is None:
                continue
            for node in _walk_nodes(b["data"]):
                t = node.get("@type")
                ts = t if isinstance(t, list) else ([t] if t else [])
                if not want or any(x in want for x in ts):
                    out.append(node)
        return out

    @property
    def internal_links(self):
        return [l for l in self.links if l.internal and not l.in_head]

    def internal_urls(self):
        seen, out = set(), []
        for l in self.internal_links:
            u = l.url.rstrip("/") or l.url
            if u not in seen:
                seen.add(u)
                out.append(l.url)
        return out

    @property
    def price_mentions(self):
        return PRICE_RE.findall(self.body_text)

    def summary(self):
        return {"title": self.title, "lang": self.lang, "canonical": self.canonical, "h1s": self.h1s,
                "lang_detected": language_from_text(self.body_text),
                "description": self.meta("description"), "word_count": self.word_count, "links": len(self.links),
                "internal_links": len(self.internal_links), "images": len(self.images), "jsonld_types": self.jsonld_types,
                "jsonld_blocks": len(self.jsonld_raw), "script_bytes": self.script_bytes,
                "external_scripts": len(self.external_scripts), "empty_root_containers": self.empty_root_containers,
                "empty_chrome": self.empty_chrome,
                "nav_count": self.nav_count, "forms": len(self.forms), "prices": len(self.price_mentions),
                "noscript_blocks": len(self.noscript_texts), "meta_refresh": self.meta_refresh,
                "body_onload": bool(self.body_attrs.get("onload"))}


def jsonld_types(data):
    out = []
    for node in _walk_nodes(data):
        t = node.get("@type")
        for x in (t if isinstance(t, list) else [t]):
            if isinstance(x, str) and x not in out:
                out.append(x)
    return out


def _walk_nodes(data):
    if isinstance(data, dict):
        yield data
        for k, v in data.items():
            if k.startswith("@") and k != "@graph":
                continue
            for n in _walk_nodes(v):
                yield n
    elif isinstance(data, list):
        for item in data:
            for n in _walk_nodes(item):
                yield n
