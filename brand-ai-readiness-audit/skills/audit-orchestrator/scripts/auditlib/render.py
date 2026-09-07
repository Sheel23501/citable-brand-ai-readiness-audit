"""Render-state rule shared by probes: is a served page a JavaScript gate, a client-rendered shell, or readable?

Single definition of the two-signal rule from check_ids.md (cr.render.js_gate / cr.render.csr_shell).
crawl-render-audit turns the states into findings; the other probes use them to decide whether a page
has any server-rendered content worth extracting from.
"""
import re

THIN_WORDS = 60
GATE_TEXT_RE = re.compile(r"(enable|requires?|turn on|activate|needs?)\s+(javascript|js)\b|javascript\s+(is\s+)?(required|disabled|needed)|without\s+javascript", re.I)
FORM_SUBMIT_RE = re.compile(r"forms?\s*(\[\s*0\s*\]|\.\w+|\(\s*0\s*\))?\s*\.submit\s*\(", re.I)


def js_gate_signals(doc):
    sig = []
    if any(re.search(r"javascript|\bjs\b", t, re.I) for t in doc.noscript_texts):
        sig.append("noscript_javascript_notice")
    if GATE_TEXT_RE.search(doc.body_text or ""):
        sig.append("enable_javascript_text")
    onload = doc.body_attrs.get("onload") or ""
    if FORM_SUBMIT_RE.search(onload) or (doc.forms and FORM_SUBMIT_RE.search(doc.inline_scripts_text)):
        sig.append("onload_form_submit")
    return sig


def csr_signals(doc):
    sig = []
    if doc.empty_root_containers:
        sig.append("empty_root_container:%s" % doc.empty_root_containers[0])
    text_bytes = max(len(doc.body_text.encode("utf-8", "replace")), 1)
    if doc.script_bytes > 10 * text_bytes and doc.script_bytes > 2000:
        sig.append("inline_script_bytes_%dx_text" % (doc.script_bytes // text_bytes))
    if len(doc.external_scripts) >= 2 and doc.word_count < 20 and not doc.h1s:
        sig.append("external_bundles_no_heading")
    return sig


def render_state(doc):
    """'ok' (readable, even if short), 'gate' (JavaScript required), or 'shell' (client-rendered container)."""
    if doc is None:
        return "none"
    if doc.word_count >= THIN_WORDS:
        return "ok"
    if js_gate_signals(doc):
        return "gate"
    if csr_signals(doc):
        return "shell"
    return "ok"
