"""Standardized enumerations for the canonical Digimon database.

All source values (Japanese / English / digi-api / Wikimon / Chinese) are mapped
into these internal enumerations during NORMALIZE. The original source value is
always preserved alongside (e.g. ``level_raw``) — mapping is never destructive.
"""
from __future__ import annotations

import re as _re
from enum import StrEnum


class Level(StrEnum):
    """Canonical level stages (Japanese-origin terminology, per product spec)."""

    DIGI_EGG = "digi_egg"  # 数码蛋 / Digitama
    BABY_I = "baby_i"  # 幼年期Ⅰ / Fresh
    BABY_II = "baby_ii"  # 幼年期Ⅱ / In-Training
    CHILD = "child"  # 成长期 / Rookie
    ADULT = "adult"  # 成熟期 / Champion
    PERFECT = "perfect"  # 完全体 / Ultimate
    ULTIMATE = "ultimate"  # 究极体 / Mega
    SUPER_ULTIMATE = "super_ultimate"  # 超究极体 / Super Ultimate (some extended forms)
    ARMOR = "armor"  # 装甲体
    HYBRID = "hybrid"  # 混合体
    UNKNOWN = "unknown"  # 不明

    @property
    def label_zh(self) -> str:
        return LEVEL_LABEL_ZH[self]

    @property
    def label_en(self) -> str:
        return LEVEL_LABEL_EN[self]


LEVEL_LABEL_ZH: dict[Level, str] = {
    Level.DIGI_EGG: "数码蛋",
    Level.BABY_I: "幼年期Ⅰ",
    Level.BABY_II: "幼年期Ⅱ",
    Level.CHILD: "成长期",
    Level.ADULT: "成熟期",
    Level.PERFECT: "完全体",
    Level.ULTIMATE: "究极体",
    Level.SUPER_ULTIMATE: "超究极体",
    Level.ARMOR: "装甲体",
    Level.HYBRID: "混合体",
    Level.UNKNOWN: "不明",
}

LEVEL_LABEL_EN: dict[Level, str] = {
    Level.DIGI_EGG: "Digi-Egg",
    Level.BABY_I: "Baby I (Fresh)",
    Level.BABY_II: "Baby II (In-Training)",
    Level.CHILD: "Child (Rookie)",
    Level.ADULT: "Adult (Champion)",
    Level.PERFECT: "Perfect (Ultimate)",
    Level.ULTIMATE: "Ultimate (Mega)",
    Level.SUPER_ULTIMATE: "Super Ultimate",
    Level.ARMOR: "Armor",
    Level.HYBRID: "Hybrid",
    Level.UNKNOWN: "Unknown",
}

# All source synonyms -> canonical level. Keys are lowercased/trimmed source
# strings as they arrive from digi-api, Wikimon infoboxes, and Chinese sources.
LEVEL_MAP: dict[str, Level] = {
    # Digi-Egg
    "digi-egg": Level.DIGI_EGG,
    "digi egg": Level.DIGI_EGG,
    "digitama": Level.DIGI_EGG,
    "数码蛋": Level.DIGI_EGG,
    "蛋": Level.DIGI_EGG,
    "幼生体": Level.DIGI_EGG,
    # Baby I
    "fresh": Level.BABY_I,
    "baby i": Level.BABY_I,
    "baby": Level.BABY_I,
    "幼年期": Level.BABY_I,
    "幼年期i": Level.BABY_I,
    "幼年期ⅰ": Level.BABY_I,
    "幼年期1": Level.BABY_I,
    "幼年期i期": Level.BABY_I,
    # Baby II
    "in training": Level.BABY_II,
    "in-training": Level.BABY_II,
    "intraining": Level.BABY_II,
    "baby ii": Level.BABY_II,
    "幼年期ⅱ": Level.BABY_II,
    "幼年期ii": Level.BABY_II,
    "幼年期2": Level.BABY_II,
    "幼年期Ⅱ": Level.BABY_II,
    "幼年期ii期": Level.BABY_II,
    # Child / Rookie
    "child": Level.CHILD,
    "rookie": Level.CHILD,
    "成长期": Level.CHILD,
    "成長期": Level.CHILD,
    "成长期i": Level.CHILD,
    # Adult / Champion
    "adult": Level.ADULT,
    "champion": Level.ADULT,
    "成熟期": Level.ADULT,
    "成熟期i": Level.ADULT,
    # Perfect / Ultimate (JP)
    "perfect": Level.PERFECT,
    "完全体": Level.PERFECT,
    # Ultimate / Mega
    "ultimate": Level.ULTIMATE,
    "mega": Level.ULTIMATE,
    "究极体": Level.ULTIMATE,
    "究極体": Level.ULTIMATE,
    "究極體": Level.ULTIMATE,
    # Super Ultimate
    "super ultimate": Level.SUPER_ULTIMATE,
    "超究极体": Level.SUPER_ULTIMATE,
    "超究極体": Level.SUPER_ULTIMATE,
    # Armor
    "armor": Level.ARMOR,
    "armour": Level.ARMOR,
    "装甲体": Level.ARMOR,
    "裝甲體": Level.ARMOR,
    # Hybrid
    "hybrid": Level.HYBRID,
    "fusion": Level.HYBRID,
    "混合体": Level.HYBRID,
    "混合體": Level.HYBRID,
    "鬥士體": Level.HYBRID,
    # Unknown / other
    "unknown": Level.UNKNOWN,
    "不明": Level.UNKNOWN,
    "none": Level.UNKNOWN,
    "n/a": Level.UNKNOWN,
    "": Level.UNKNOWN,
}


class Attribute(StrEnum):
    VACCINE = "vaccine"
    VIRUS = "virus"
    DATA = "data"
    FREE = "free"
    VARIABLE = "variable"
    UNKNOWN = "unknown"

    @property
    def label_zh(self) -> str:
        return ATTRIBUTE_LABEL_ZH[self]

    @property
    def label_en(self) -> str:
        return ATTRIBUTE_LABEL_EN[self]


ATTRIBUTE_LABEL_ZH: dict[Attribute, str] = {
    Attribute.VACCINE: "疫苗种",
    Attribute.VIRUS: "病毒种",
    Attribute.DATA: "资料种",
    Attribute.FREE: "自由种",
    Attribute.VARIABLE: "可变种",
    Attribute.UNKNOWN: "不明",
}

ATTRIBUTE_LABEL_EN: dict[Attribute, str] = {
    Attribute.VACCINE: "Vaccine",
    Attribute.VIRUS: "Virus",
    Attribute.DATA: "Data",
    Attribute.FREE: "Free",
    Attribute.VARIABLE: "Variable",
    Attribute.UNKNOWN: "Unknown",
}

ATTRIBUTE_MAP: dict[str, Attribute] = {
    "vaccine": Attribute.VACCINE,
    "ワクチン種": Attribute.VACCINE,
    "疫苗种": Attribute.VACCINE,
    "疫苗種": Attribute.VACCINE,
    "疫苗": Attribute.VACCINE,
    "vaccine type": Attribute.VACCINE,
    "virus": Attribute.VIRUS,
    "ウィルス種": Attribute.VIRUS,
    "ウイルス種": Attribute.VIRUS,
    "病毒种": Attribute.VIRUS,
    "病毒種": Attribute.VIRUS,
    "病毒": Attribute.VIRUS,
    "virus type": Attribute.VIRUS,
    "data": Attribute.DATA,
    "データ種": Attribute.DATA,
    "资料种": Attribute.DATA,
    "資料種": Attribute.DATA,
    "资料": Attribute.DATA,
    "資料": Attribute.DATA,
    "data type": Attribute.DATA,
    "free": Attribute.FREE,
    "フリー種": Attribute.FREE,
    "自由种": Attribute.FREE,
    "自由種": Attribute.FREE,
    "free type": Attribute.FREE,
    "variable": Attribute.VARIABLE,
    "バリアブル種": Attribute.VARIABLE,
    "可变种": Attribute.VARIABLE,
    "可變種": Attribute.VARIABLE,
    "variable type": Attribute.VARIABLE,
    "unknown": Attribute.UNKNOWN,
    "no attribute": Attribute.UNKNOWN,
    "not applicable": Attribute.UNKNOWN,
    "no data": Attribute.UNKNOWN,
    "无属性": Attribute.UNKNOWN,
    "無屬性": Attribute.UNKNOWN,
    "不明": Attribute.UNKNOWN,
    "": Attribute.UNKNOWN,
}


def parse_level(value: str | None) -> Level:
    """Map a raw source level string to the canonical Level enum.

    Lookup is via the case-insensitive LEVEL_MAP; on miss we return UNKNOWN
    (never raise, never invent). Preserve the raw value alongside via the
    caller (`level_raw`).
    """
    if value is None:
        return Level.UNKNOWN
    raw = value.strip()
    direct = LEVEL_MAP.get(raw.lower(), Level.UNKNOWN)
    if direct is not Level.UNKNOWN:
        return direct
    # compact fallback: handles unicode/variant spellings the exact map misses,
    # e.g. "In-TrainingⅠ" -> Baby I, "完全体 (XW)" -> Perfect (Xros Wars tag).
    return _LEVEL_COMPACT.get(_compact_level(raw), Level.UNKNOWN)


# Unicode roman numerals (Baby I/II) → ASCII before compact matching.
_LEVEL_ROMAN = str.maketrans({"Ⅰ": "i", "ⅰ": "i", "Ⅱ": "ii", "ⅱ": "ii"})


def _compact_level(value: str) -> str:
    s = value.strip().lower().translate(_LEVEL_ROMAN)
    s = _re.sub(r"[（(]\s*xw\s*[）)]", "", s)  # strip Xros Wars annotation
    return _re.sub(r"[\s\-_.,·]+", "", s)


# Compact fallback map: every LEVEL_MAP key in compact form + explicit extras
# that only appear as variant spellings in real source data.
_LEVEL_COMPACT: dict[str, Level] = {_compact_level(k): v for k, v in LEVEL_MAP.items()}
_LEVEL_COMPACT.update(
    {
        "intrainingi": Level.BABY_I,
        "intrainingii": Level.BABY_II,
    }
)


def parse_attribute(value: str | None) -> Attribute:
    if value is None:
        return Attribute.UNKNOWN
    return ATTRIBUTE_MAP.get(value.strip().lower(), Attribute.UNKNOWN)


class EvolutionType(StrEnum):
    NORMAL = "normal"
    JOGRESS = "jogress"
    DNA = "dna"
    ARMOR = "armor"
    SPIRIT = "spirit"
    SLIDE = "slide"
    MODE_CHANGE = "mode_change"
    X_EVOLUTION = "x_evolution"
    BURST = "burst"
    FUSION = "fusion"
    DEATH = "death"
    SPECIAL = "special"
    GAME_SPECIFIC = "game_specific"
    UNKNOWN = "unknown"


class RelationType(StrEnum):
    VARIANT = "variant"
    X_ANTIBODY = "x_antibody"
    MODE_CHANGE = "mode_change"
    BLACK_VARIANT = "black_variant"
    SAME_SPECIES = "same_species"
    FUSION_COMPONENT = "fusion_component"
    COUNTERPART = "counterpart"
    RELATED = "related"


class SkillType(StrEnum):
    SPECIAL_MOVE = "special_move"
    SIGNATURE_MOVE = "signature_move"
    ATTACK = "attack"
    ABILITY = "ability"
    OTHER = "other"


class AliasType(StrEnum):
    OFFICIAL = "official"
    DUB = "dub"
    ROMANIZATION = "romanization"
    OLD_TRANSLATION = "old_translation"
    FAN_TRANSLATION = "fan_translation"
    GAME_TRANSLATION = "game_translation"
    ANIME_TRANSLATION = "anime_translation"
    ALTERNATIVE_SPELLING = "alternative_spelling"


class ImageType(StrEnum):
    MAIN_IMAGE = "main_image"
    THUMBNAIL = "thumbnail"
    OFFICIAL_ART = "official_art"
    REFERENCE_ART = "reference_art"
    SPRITE = "sprite"
    CARD_ART = "card_art"
    ANIME_ART = "anime_art"
    GAME_MODEL = "game_model"


class AppearanceMedium(StrEnum):
    VPET = "vpet"
    GAME = "game"
    ANIME = "anime"
    MANGA = "manga"
    CARD = "card"
    NOVEL = "novel"
    WEB = "web"
    OTHER = "other"


class NameStatus(StrEnum):
    OFFICIAL = "official"
    OFFICIAL_GAME = "official_game"
    OFFICIAL_ANIME = "official_anime"
    COMMUNITY = "community"
    TRANSLITERATION = "transliteration"
    UNVERIFIED = "unverified"


class DataSource(StrEnum):
    """Canonical source identifiers used across provenance records."""

    DAPI = "dapi"  # digi-api.com
    WIKIMON = "wikimon"  # wikimon.net
    OFFICIAL = "official"  # digimon.net reference book
    DIGIMONS_NET = "digimons_net"  # digimons.net
    DIGIDB = "digidb"  # digidb.io
    MANUAL = "manual"
    GENERATED = "generated"
    UNKNOWN = "unknown"
