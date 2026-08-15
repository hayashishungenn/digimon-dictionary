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

# Template rendering rules for clean_wikitext (P1-2). Each maps a template name
# (lowercased) to a function of the |split args; returning None keeps the raw
# template verbatim and marks the text as "unresolved" (never silently deleted).
# Args are already recursively cleaned before this is called.
_TEMPLATE_RULES: dict[str, object] = {
    # language markers -> readable label
    "jp": lambda a: "Japanese",
    "japanese": lambda a: "Japanese",
    "eng": lambda a: "English",
    "english": lambda a: "English",
    "chi": lambda a: "Chinese",
    "zho": lambda a: "Chinese",
    "kor": lambda a: "Korean",
    "korean": lambda a: "Korean",
    # etymology: keep the origin word(s)
    "ety": lambda a: a[0] if a else "",
    "etyk": lambda a: a[0] if a else "",
    "etyf": lambda a: a[0] if a else "",
    "etyq": lambda a: a[0] if a else "",
    # etymology furigana helpers: render the reading
    "fgu": lambda a: a[0] if a else "",
    "fgm": lambda a: a[0] if a else "",
    "fmk": lambda a: a[0] if a else "",
    "fm": lambda a: a[0] if a else "",
    "fmo": lambda a: a[0] if a else "",
    "fmok": lambda a: a[0] if a else "",
    # etymology quotation / noun-form helpers
    "eq": lambda a: a[0] if a else "",
    "eqk": lambda a: a[0] if a else "",
    "eqo": lambda a: a[0] if a else "",
    "eqok": lambda a: a[0] if a else "",
    "etr": lambda a: a[0] if a else "",
    "nn": lambda a: a[0] if a else "",
    "nnk": lambda a: a[0] if a else "",
    "nno": lambda a: a[0] if a else "",
    "nnok": lambda a: a[0] if a else "",
    # attack references inside profiles: keep the move name
    "at": lambda a: a[0] if a else "",
    "atk": lambda a: a[0] if a else "",
    "at2": lambda a: a[0] if a else "",
    "specialattack": lambda a: a[0] if a else "",
    "ato": lambda a: a[0] if a else "",
    "atok": lambda a: a[0] if a else "",
    # citations / footnotes / decoration -> drop
    "ref": lambda a: "",
    "rfc": lambda a: "",
    "rf": lambda a: "",
    "cite": lambda a: "",
    "citeweb": lambda a: "",
    "citep": lambda a: "",
    "dd": lambda a: "",
    "dd2": lambda a: "",
    "noun": lambda a: "",
    "noun2": lambda a: "",
    "disc": lambda a: "",
    "kanji": lambda a: "",
    "reflist": lambda a: "",
    "note": lambda a: "",
    "notes": lambda a: "",
    "j": lambda a: "",
    "j2": lambda a: "",
    "s2ep": lambda a: "",
    "br": lambda a: "",
    "xab": lambda a: "",
    # grammatical role markers in etymology
    "adj": lambda a: "",
    "verb": lambda a: "",
    "adv": lambda a: "",
    "prep": lambda a: "",
    "pron": lambda a: "",
    "num": lambda a: "",
    "suf": lambda a: "",
    "pref": lambda a: "",
    "comb": lambda a: "",
    "conj": lambda a: "",
    "interj": lambda a: "",
    "dub": lambda a: a[0] if a else "",
    # plain wikilink-as-template
    "w": lambda a: a[1] if len(a) > 1 else (a[0] if a else ""),
    "s": lambda a: "",
    "ruby": lambda a: a[0] if a else "",
    "nihongo": lambda a: a[0] if a else "",
    "efn": lambda a: "",
    "notelist": lambda a: "",
}

# Etymology language markers: "{{HEB}}" -> "Hebrew", "{{GRE|λόγος}}" -> "λόγος".
_ETYM_LANG_NAMES = {
    "heb": "Hebrew", "gre": "Greek", "lat": "Latin", "fra": "French",
    "deu": "German", "ger": "German", "san": "Sanskrit", "ita": "Italian",
    "esp": "Spanish", "spa": "Spanish", "jpn": "Japanese", "ga": "Irish/Gaelic",
    "egy": "Egyptian", "per": "Persian", "nrs": "Old Norse", "hel": "Greek",
    "ara": "Arabic", "fin": "Finnish", "ass": "Assyrian", "etr": "Etruscan",
    "rus": "Russian", "por": "Portuguese", "nld": "Dutch", "swe": "Swedish",
    "dan": "Danish", "nor": "Norwegian", "tur": "Turkish", "hin": "Hindi",
    "may": "Malay", "tha": "Thai", "ukr": "Ukrainian", "pol": "Polish",
    "cze": "Czech", "hun": "Hungarian", "rom": "Romanian", "isl": "Icelandic",
    "zho": "Chinese", "chi": "Chinese", "zh": "Chinese", "kor": "Korean",
    "en": "English", "eng": "English", "jp": "Japanese", "ja": "Japanese",
}
for _code, _label in _ETYM_LANG_NAMES.items():
    _TEMPLATE_RULES[_code] = (lambda label: lambda args: args[0] if (args and args[0]) else label)(_label)


def _match_braces(text: str, start: int) -> tuple[int, int]:
    """From `start` at '{{', return (closing_index_after_}} or -1)."""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        if text.startswith("{{", i):
            depth += 1
            i += 2
        elif text.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                return 0, i
        else:
            i += 1
    return -1, n


def _split_template_args(args_raw: str) -> list[str]:
    """Split template args on '|' at the top nesting level."""
    out: list[str] = []
    cur: list[str] = []
    depth = 0
    i = 0
    while i < len(args_raw):
        if args_raw.startswith("{{", i):
            depth += 1
            cur.append("{{")
            i += 2
        elif args_raw.startswith("[[", i):
            depth += 1
            cur.append("[[")
            i += 2
        elif args_raw.startswith("}}", i) or args_raw.startswith("]]", i):
            depth = max(0, depth - 1)
            cur.append(args_raw[i : i + 2])
            i += 2
        elif args_raw[i] == "|" and depth == 0:
            out.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(args_raw[i])
            i += 1
    if cur or not out:
        out.append("".join(cur))
    return out


def _process_wikitext(text: str, depth: int = 0) -> tuple[str, bool]:
    """Recursively clean wikitext: links, refs, tags, comments, templates.

    Returns ``(cleaned, has_unresolved)``. Unparseable templates are kept
    verbatim and flagged so the caller can mark the field for human review —
    never silently dropped (P1-2)."""
    if depth > 12:
        return text, False  # safety stop
    out: list[str] = []
    unresolved = False
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("{{", i):
            _status, j = _match_braces(text, i)
            if _status < 0:  # unbalanced — leave as-is
                out.append(text[i])
                i += 1
                continue
            body = text[i:j]
            inner = body[2:-2]
            name, _, args_raw = inner.partition("|")
            name = name.strip().lower()
            args: list[str] = []
            for a in _split_template_args(args_raw):
                cleaned_arg, arg_unresolved = _process_wikitext(a, depth + 1)
                args.append(cleaned_arg.strip())
                unresolved = unresolved or arg_unresolved  # propagate nested residue
            rule = _TEMPLATE_RULES.get(name)
            if rule is None:
                unresolved = True
                out.append(body)
            else:
                out.append(rule(args) if callable(rule) else "")
            i = j
            continue
        if text.startswith("[[", i):
            end = text.find("]]", i)
            if end == -1:
                end = n
            inner = text[i + 2 : end]
            if inner.lower().startswith(("file:", "image:", "category:")):
                out.append("")  # embedded media / category links -> drop
            else:
                target, _, label = inner.partition("|")
                out.append(label or target)
            i = end + 2
            continue
        if text[i] == "<":
            end = text.find(">", i)
            if end == -1:
                out.append(text[i])
                i += 1
                continue
            tag = text[i + 1 : end].strip().split()[0].lower().lstrip("/")
            if tag == "ref":
                close = text.find("</ref>", end)
                if close != -1:
                    end = close + 6
                out.append("")
                i = end
                continue
            if tag in ("br", "nowiki", "noinclude", "includeonly", "small", "big", "sup", "sub"):
                out.append(" " if tag == "br" else "")
                i = end + 1
                continue
            if tag in ("gallery", "table", "div", "span", "center", "blockquote"):
                out.append("")
                i = end + 1
                continue
            # unknown tag: drop the tag itself, keep content
            out.append("")
            i = end + 1
            continue
        if text[i] == "[" and text[i : i + 2] != "[[":  # stray single bracket
            out.append(text[i])
            i += 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out).strip(), unresolved


def clean_wikitext(text: str) -> tuple[str, bool]:
    """Clean user-visible wikitext into plain text (P1-2).

    Resolves [[links]], drops <ref>/HTML/File/media markup and known noise
    templates, and renders etymology/attack/language templates to readable text.
    Unknown templates are kept verbatim and flagged (``has_unresolved``) so the
    caller can queue them for human review rather than silently deleting.
    """
    s = _COMMENT_RE.sub("", text)
    s = _BOLD_RE.sub("", s)
    return _process_wikitext(s)


def strip_markup(text: str) -> str:
    """Remove wikitext markup, returning plain text (lossy but safe)."""
    cleaned, _unresolved = clean_wikitext(text)
    return cleaned


def strip_residual_markup(text: str) -> str:
    """Drop any templates/links that survived cleaning (P1-2).

    Used as a final safety net for fields already flagged ``unresolved``: the
    original text is preserved in the review queue, while the user-visible
    value is guaranteed to contain no raw ``{{...}}``/``[[...]]`` markup.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("{{", i):
            _status, j = _match_braces(text, i)
            i = j if _status >= 0 else i + 2
            continue
        if text.startswith("[[", i):
            end = text.find("]]", i)
            i = (end + 2) if end != -1 else i + 2
            continue
        out.append(text[i])
        i += 1
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


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
    """Split a template body into |key=value pairs at the top nesting level.

    Nested {{...}} and [[...]] are tracked by depth so their internal '|' and
    '=' never split the surrounding template (P1-2 — previously only *flat*
    templates were protected, so nested values like ``{{ETY|{{FGU|x}}n}}``
    were truncated at the inner pipe)."""
    inner = body
    if inner.startswith("{{"):
        inner = inner[2:]
    if inner.endswith("}}"):
        inner = inner[:-2]
    parts = _split_template_args(inner)
    params: list[tuple[str, str]] = []
    for part in parts[1:]:  # parts[0] is the template name
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()
        else:
            k, v = part, ""
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
