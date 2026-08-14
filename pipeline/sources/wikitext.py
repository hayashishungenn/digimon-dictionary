"""Minimal MediaWiki wikitext helpers for parsing Wikimon infobox templates.

Handles nested {{...}} braces, |key=value param splitting, and stripping wiki
markup ([[links]], <ref> tags, '''bold''', HTML comments).
"""
from __future__ import annotations

import re

_REF_RE = re.compile(r"<ref[^>]*>.*?</ref>", re.S)
_REF_SELF_RE = re.compile(r"<ref[^>/]*/>")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_LINK_RE = re.compile(r"\[\[([^\]|]*)(?:\|([^\]]*))?\]\]")
_TEMPLATE_INLINE_RE = re.compile(r"\{\{[^}]+\}\}")
_BOLD_RE = re.compile(r"'{2,}")
_TAGS_RE = re.compile(r"<[^>]+>")


def strip_markup(text: str) -> str:
    """Remove wikitext markup, returning plain text (lossy but safe)."""
    s = text
    s = _COMMENT_RE.sub("", s)
    s = _REF_RE.sub("", s)
    s = _REF_SELF_RE.sub("", s)
    s = _LINK_RE.sub(lambda m: m.group(2) or m.group(1), s)
    s = _BOLD_RE.sub("", s)
    s = _TAGS_RE.sub("", s)
    s = s.replace("{{!}}", "|")
    return s.strip()


def strip_markup_keep_templates(text: str) -> str:
    """Remove refs/comments/links but keep templates for later {{AT}} parsing."""
    s = _COMMENT_RE.sub("", text)
    s = _REF_RE.sub("", s)
    s = _REF_SELF_RE.sub("", s)
    s = _LINK_RE.sub(lambda m: m.group(2) or m.group(1), s)
    s = _BOLD_RE.sub("", s)
    return s


def extract_template(text: str, name: str) -> tuple[list[tuple[str, str]], int] | None:
    """Find `{{name` (case-insensitive) and return (params, end_index).

    Params are (key, value) pairs split at the top nesting level. Returns None
    if the template is not found. Handles nested braces.
    """
    start = text.lower().find("{{" + name.lower())
    if start < 0:
        return None
    # advance past the template name (and optional whitespace after)
    depth = 0
    i = start
    while i < len(text):
        if text.startswith("{{", i):
            depth += 1
            i += 2
            continue
        if text.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                break
            continue
        i += 1
    body = text[start:i]
    params = split_params(body, name)
    return params, i


def split_params(body: str, name: str | None = None) -> list[tuple[str, str]]:
    """Split a template body into |key=value pairs at top level.

    Nested {{...}} and [[...]] are protected so their '|' and '=' don't split.
    """
    # protect nested constructs
    protected: list[str] = []
    def _protect(m: re.Match) -> str:
        protected.append(m.group(0))
        return f"\x00{len(protected) - 1}\x00"

    body = re.sub(r"\{\{[^{}]*\}\}", _protect, body)
    body = re.sub(r"\[\[[^\[\]]*\]\]", _protect, body)

    parts = body.split("|")
    params: list[tuple[str, str]] = []
    for part in parts[1:]:  # first part is the template name
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()
        else:
            k, v = part, ""
        # un-protect
        v = _unprotect(v, protected)
        k = _unprotect(k, protected)
        params.append((k, v))
    return params


def _unprotect(value: str, protected: list[str]) -> str:
    def _restore(m: re.Match) -> str:
        idx = int(m.group(1))
        return protected[idx] if idx < len(protected) else ""

    return re.sub(r"\x00(\d+)\x00", _restore, value)


def parse_ol_field(value: str) -> dict[str, str]:
    """Parse the Wikimon `ol` (other languages) field.

    e.g. "{{CHI}} 亞古獸{{DD|a}}<br>{{ZHO}} 亚古兽{{DD|a}}<br>{{KOR}} 아구몬{{DD|a}}"
    Returns {zh_tw?, zh_cn?, ko, ...}.
    """
    out: dict[str, str] = {}
    for seg in re.split(r"<br\s*/?>", value):
        seg = seg.strip()
        if not seg:
            continue
        lang_match = re.match(r"\{\{\s*([A-Za-z]+)\s*\}\}", seg)
        if not lang_match:
            continue
        lang = lang_match.group(1).upper()
        rest = _LINK_RE.sub(lambda m: m.group(2) or m.group(1), seg)
        rest = re.sub(r"\{\{[^}]+\}\}", "", rest)
        # drop italic gloss annotations like — ''Agumon'' or （''Agumon''）
        rest = re.sub(r"'{2,}[^']*'{2,}", "", rest)
        rest = re.sub(r"[—–].*$", "", rest)  # em/en-dash + anything after
        rest = re.sub(r"[（）()].*$", "", rest)  # CJK/latin parens + after
        rest = rest.strip().strip("—–-").strip()
        if not rest:
            continue
        if lang == "CHI":
            out["zh_tw"] = rest  # CHI = Traditional Chinese
        elif lang == "ZHO":
            out["zh_cn"] = rest  # ZHO = Simplified Chinese
        elif lang == "KOR":
            out["ko"] = rest
        else:
            out[lang.lower()] = rest
    return out


def extract_wiki_section(text: str, heading: str) -> list[str]:
    """Return the bullet lines (`* ...`) of a `==Heading==` section."""
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        if line.strip().startswith("==") and line.strip().endswith("=="):
            title = line.strip().strip("=").strip()
            if title.lower() == heading.lower():
                in_section = True
                continue
            if in_section:
                break
        if in_section and line.strip().startswith("*"):
            out.append(line.strip())
    return out
