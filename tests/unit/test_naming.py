"""Unit tests for core name normalization (simplified/traditional, X-Antibody)."""
from __future__ import annotations

from pipeline.core import naming


def test_normalize_key_basic():
    assert naming.normalize_key("Agumon") == "agumon"
    assert naming.normalize_key("Agumon 2006") == "agumon2006"
    assert naming.normalize_key("アグモン") == "アグモン"
    assert naming.normalize_key("Ａｇｕｍｏｎ") == "agumon"  # full-width


def test_x_antibody_normalization():
    for variant in ("Agumon X", "Agumon X-Antibody", "Agumon (X-Antibody)"):
        assert naming.normalize_key(variant) == "agumonxantibody"
    assert naming.normalize_key("Agumon (X-Antibody)") == "agumonxantibody"


def test_traditional_to_simplified():
    assert naming.to_simplified("亞古獸") == "亚古兽"
    assert naming.to_simplified("奧米加獸") == "奥米加兽"


def test_normalize_key_zh():
    # Both forms collapse to the same key.
    assert naming.normalize_key_zh("亞古獸") == naming.normalize_key_zh("亚古兽")


def test_traditional_roundtrip():
    assert naming.to_traditional("亚古兽") == "亞古獸"


def test_slugify_fallback():
    assert naming.slugify("Agumon (2006)") == "agumon-2006"
    assert naming.slugify("Omegamon X-Antibody") == "omegamon-xantibody"


def test_cjk_detection():
    assert naming.is_chinese("亚古兽")
    assert naming.is_japanese("アグモン")
    assert not naming.is_chinese("Agumon")
    assert not naming.is_japanese("Agumon")
