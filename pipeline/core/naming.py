"""Name normalization for search & entity matching.

Normalization is only ever used for searching/matching — original display names
are never mutated (product spec §34). OpenCC provides simplified/traditional
conversion so 亞古獸 / 亚古兽 hit the same entity.
"""
from __future__ import annotations

import re
import unicodedata

from opencc import OpenCC

_t2s = OpenCC("t2s")
_s2t = OpenCC("s2t")

# Punctuation characters removed when building a search key.
_PUNCT_RE = re.compile(r"[\s\-_:/\\()（）\[\]【】.,・·~～'\"`“”‘’]+")
# X-Antibody spellings normalized to a single token.
_XAB_RE = re.compile(r"\b(x[\s\-_]*antibody|xa?b?)\b", re.IGNORECASE)


def to_simplified(text: str) -> str:
    """Convert Chinese text to Simplified Chinese."""
    return _t2s.convert(text)


def to_traditional(text: str) -> str:
    """Convert Chinese text to Traditional Chinese."""
    return _s2t.convert(text)


def normalize_key(text: str) -> str:
    """Build a stable, lossy search/matching key from a name.

    Steps: NFKC (full-width -> half-width, unicode normalize) -> lowercase ->
    X-Antibody canonicalization -> strip punctuation/whitespace.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = _XAB_RE.sub("xantibody", s)
    s = _PUNCT_RE.sub("", s)
    return s.casefold()


def normalize_key_zh(text: str) -> str:
    """Simplified-Chinese search key (both zh forms and t2s-normalized)."""
    return normalize_key(to_simplified(text))


def normalize_key_ja(text: str) -> str:
    """Japanese search key (katakana/hiragana normalization via NFKC)."""
    return normalize_key(text)


def is_chinese(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def is_japanese(text: str) -> bool:
    return any(
        ("぀" <= ch <= "ヿ") or ("ㇰ" <= ch <= "ㇿ") for ch in text
    )


def canonicalize_x_antibody_slug(base: str) -> str:
    """Return the canonical slug for an X-Antibody variant of a base slug."""
    return f"{base}-x-antibody"


def slugify(text: str) -> str:
    """Create a canonical_slug candidate from a name (lossy, ASCII lowercase).

    Note: canonical_slugs are assigned by the merge pipeline from the official
    Japanese romanized name, not by arbitrary slugify of a Chinese name. This
    helper is only for fallback / external-slug normalization.
    """
    s = unicodedata.normalize("NFKD", text)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = _XAB_RE.sub("xantibody", s)
    s = _PUNCT_RE.sub("-", s).strip("-")
    return s.casefold()


# Character-level mapping used for quick CJK detection in search routing.
_KATAKANA_BASE = "ァアィイゥウェエォオ" \
    "カガキギクグケゲコゴサザ" \
    "シジスズセゼソゾタダチヂ" \
    "ッツヅテデトドナニヌネノ" \
    "ハバパヒビピフブプヘベペ" \
    "ホボポマミムメモャヤュユ" \
    "ョヨラリルレロワヰヱヲン" \
    "ヴヵヶ"
