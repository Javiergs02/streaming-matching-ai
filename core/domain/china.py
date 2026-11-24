"""Domain constants, exchange rates, and Broadkast mappings for Chinese platforms."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

# Annual average CNY (RMB) per 1 USD (Federal Reserve G.5A / IRS historical averages)
RMB_PER_USD_BY_YEAR: dict[int, float] = {
    2017: 6.73,
    2018: 6.62,
    2019: 6.91,
    2020: 6.90,
    2021: 6.45,
    2022: 6.73,
    2023: 7.08,
    2024: 7.19,
    2025: 7.19,
    2026: 7.19,
}

DEFAULT_RMB_PER_USD: float = 7.19

# Exact 1:1 mapping from Tencent SVOD workbook tab codes to Broadkast projects & series
TENCENT_SVOD_SERIES_MAP: dict[str, dict[str, str]] = {
    "SHK": {
        "project_code": "SHK",
        "ip_name": "SHARK_ACADEMY",
        "series_code": "SHK",
        "series_name": "SHARK_ACADEMY",
        "title": "Shark Academy (Tencent SVOD)",
        "monetization_model": "SVOD",
    },
    "INC": {
        "project_code": "INC",
        "ip_name": "INCREDITALES",
        "series_code": "INC",
        "series_name": "INCREDITALES_SKETCHES",
        "title": "Increditales Sketches (Tencent SVOD)",
        "monetization_model": "SVOD",
    },
    "ACAT": {
        "project_code": "AC",
        "ip_name": "ANIMACARS",
        "series_code": "ACAT",
        "series_name": "ANIMA_TOWN",
        "title": "AnimaTown (Tencent SVOD)",
        "monetization_model": "SVOD",
    },
    "CC2BABIES": {
        "project_code": "CC2",
        "ip_name": "CARCITY_SUPER",
        "series_code": "CC2BABIES",
        "series_name": "BABY_TRUCKS",
        "title": "Baby Trucks (Tencent SVOD)",
        "monetization_model": "SVOD",
    },
    "CC2TOM": {
        "project_code": "CC2",
        "ip_name": "CARCITY_SUPER",
        "series_code": "CC2TOM",
        "series_name": "INVENTOM",
        "title": "InvenTom (Tencent SVOD)",
        "monetization_model": "SVOD",
    },
    "CC2RF": {
        "project_code": "CC2",
        "ip_name": "CARCITY_SUPER",
        "series_code": "CC2RF",
        "series_name": "ROBOFUSE",
        "title": "Robofuse (Tencent SVOD)",
        "monetization_model": "SVOD",
    },
    "SPSH": {
        "project_code": "SP",
        "ip_name": "SUPERS",
        "series_code": "SPSH",
        "series_name": "SUPER_HEROS",
        "title": "Super Heroes (Tencent SVOD)",
        "monetization_model": "SVOD",
    },
}

TENCENT_AVOD_META: dict[str, str] = {
    "project_code": "CHANNEL_LEVEL",
    "ip_name": "CHANNEL_LEVEL",
    "series_code": "TENCENT_AVOD",
    "series_name": "Tencent Video AVOD (Channel Level)",
    "title": "Tencent Video AVOD (Channel Level)",
    "monetization_model": "AVOD",
}


def get_rmb_per_usd_rate(year: int) -> float:
    """Returns the annual average RMB per 1 USD exchange rate for the given calendar year."""
    try:
        from core.domain.exchange_rates import get_cny_rate
        return get_cny_rate(year)
    except Exception:
        if year in RMB_PER_USD_BY_YEAR:
            return RMB_PER_USD_BY_YEAR[year]
        if year < min(RMB_PER_USD_BY_YEAR):
            return RMB_PER_USD_BY_YEAR[min(RMB_PER_USD_BY_YEAR)]
        return DEFAULT_RMB_PER_USD


def convert_cny_to_usd(amount_cny: float, date_or_year: str | int | date | datetime) -> tuple[float, float]:
    """Converts an amount in CNY/RMB to USD using the configured exchange rates.

    Returns (amount_usd, rate_rmb_per_usd).
    """
    try:
        from core.domain.exchange_rates import convert_cny_to_usd as fx_convert_cny
        return fx_convert_cny(amount_cny, date_or_year)
    except Exception:
        if isinstance(date_or_year, (datetime, date)):
            year = date_or_year.year
        elif isinstance(date_or_year, int):
            year = date_or_year
        else:
            m = re.match(r"^(\d{4})", str(date_or_year).strip())
            year = int(m.group(1)) if m else 2025

        rate = get_rmb_per_usd_rate(year)
        usd = float(amount_cny) / rate if rate else 0.0
        return usd, rate


def parse_cny_amount(val: Any) -> float:
    """Parses currency cells like '￥0.23', '¥1,234.50', or numeric values into float."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s in ("-", "n/a", "N/A", "None", "nan"):
        return 0.0
    s = s.replace("￥", "").replace("¥", "").replace(",", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def normalize_excel_date(val: Any) -> Optional[str]:
    """Normalizes Excel dates into 'YYYY-MM-DD', repairing two-digit year typos (e.g. 0022 -> 2022)."""
    if val is None:
        return None
    if isinstance(val, datetime):
        y = val.year + 2000 if val.year < 100 else val.year
        return f"{y:04d}-{val.month:02d}-{val.day:02d}"
    if isinstance(val, date):
        y = val.year + 2000 if val.year < 100 else val.year
        return f"{y:04d}-{val.month:02d}-{val.day:02d}"

    s = str(val).strip()
    if not s:
        return None
    m = re.match(r"^(\d{2,4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m2 = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m2:
        return f"{int(m2.group(1)):04d}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}"
    return None


def get_tencent_series_metadata(video_id_or_code: str) -> dict[str, str]:
    """Resolves Broadkast IP/Series metadata for a Tencent video_id or tab code."""
    raw = str(video_id_or_code or "").strip()
    if raw == "TENCENT_AVOD_CHANNEL" or raw.startswith("TENCENT_AVOD"):
        return dict(TENCENT_AVOD_META)
    code = raw.removeprefix("TENCENT_SVOD_")
    if code in TENCENT_SVOD_SERIES_MAP:
        return dict(TENCENT_SVOD_SERIES_MAP[code])
    return {
        "project_code": "UNMATCHED",
        "ip_name": "CHANNEL_LEVEL",
        "series_code": code or "TENCENT",
        "series_name": raw or "Tencent Video",
        "title": raw or "Tencent Video",
        "monetization_model": "SVOD" if "SVOD" in raw else "AVOD",
    }


def _yku_entry(video_id: str, project_code: str, ip_name: str, series_code: str, series_name: str, title: str, subplatform: str) -> dict[str, str]:
    return {
        "video_id": video_id,
        "project_code": project_code,
        "ip_name": ip_name,
        "series_code": series_code,
        "series_name": series_name,
        "title": title,
        "subplatform": subplatform,
    }


YOUKU_DAYU_META: dict[str, dict[str, str]] = {
    "CC": _yku_entry("YOUKU_DAYU_CC", "CC", "CARCITY", "CC_DAYU", "CARCITY_DAYU_CHANNEL", "Car City (Youku DaYu)", "DaYu Platform"),
    "LTV": _yku_entry("YOUKU_DAYU_LTV", "LT", "LEARN_TV", "LT_DAYU", "LEARN_TV_DAYU_CHANNEL", "Learn TV (Youku DaYu)", "DaYu Platform"),
}

_YOUKU_OP_ENTRIES: list[tuple[list[str], dict[str, str]]] = [
    (["迷你卡车乐园"], _yku_entry("YOUKU_OP_TT", "TW", "TINY_WORLD", "TT", "TINY_TOWN", "Tiny Town (Youku Open)", "Open Platform")),
    (["汽车城之汤姆的油漆店"], _yku_entry("YOUKU_OP_TPS", "CC", "CARCITY", "TPS", "TOM_PAINT_SHOP", "Tom's Paint Shop (Youku Open)", "Open Platform")),
    (["汽车城之牛牛贺岁专辑"], _yku_entry("YOUKU_OP_NEWYEAR", "CC", "CARCITY", "NEWYEAR", "CARCITY_THEMATIC_NEW_YEAR", "Car City New Year Special (Youku Open)", "Open Platform")),
    (["和恐龙戴诺学习"], _yku_entry("YOUKU_OP_DINO", "LT", "LEARN_TV", "DINO", "DINO_THE_DINOSAUR", "Dino the Dinosaur (Youku Open)", "Open Platform")),
    (["和翻斗车伊森学习"], _yku_entry("YOUKU_OP_ETHAN", "LT", "LEARN_TV", "ETHAN", "ETHAN_THE_DUMP_TRUCK", "Ethan the Dump Truck (Youku Open)", "Open Platform")),
    (["和迷你卡车学习"], _yku_entry("YOUKU_OP_TINY", "TW", "TINY_WORLD", "TINY", "TINY_TRUCKS", "Tiny Trucks (Youku Open)", "Open Platform")),
    (["和火车泰德学习"], _yku_entry("YOUKU_OP_TED", "LT", "LEARN_TV", "TED", "TED_THE_TRAIN", "Ted the Train (Youku Open)", "Open Platform")),
    (["汽车城之超级变形卡车"], _yku_entry("YOUKU_OP_CARL", "CC", "CARCITY", "CARL", "SUPER_TRUCK", "Super Truck (Youku Open)", "Open Platform")),
    (["汽车城之拖车汤姆"], _yku_entry("YOUKU_OP_TOM", "CC", "CARCITY", "TOM", "TOM_THE_TOW_TRUCK", "Tom the Tow Truck (Youku Open)", "Open Platform")),
    (["汽车城之建筑队"], _yku_entry("YOUKU_OP_CS", "CC", "CARCITY", "CS", "CONSTRUCTION_SQUAD", "Construction Squad (Youku Open)", "Open Platform")),
    (["大脚卡车镇"], _yku_entry("YOUKU_OP_MT", "CC", "CARCITY", "MT", "MONSTER_TOWN", "Monster Town (Youku Open)", "Open Platform")),
    (["汽车之城警车和消防车", "汽车城之警车和消防车"], _yku_entry("YOUKU_OP_CP", "CC", "CARCITY", "CP", "CAR_PATROL", "Car Patrol (Youku Open)", "Open Platform")),
    (["汽车城之火车特洛伊"], _yku_entry("YOUKU_OP_TROY", "CC", "CARCITY", "TROY", "TROY_THE_TRAIN", "Troy the Train (Youku Open)", "Open Platform")),
    (["动物汽车岛之乔尼特工队第二季", "动物汽车岛之乔尼特工队 第二季"], _yku_entry("YOUKU_OP_ACDL", "AC", "ANIMACARS", "ACDL", "ANIMACARS_DAILY_LIFE", "AnimaCars Daily Life (Youku Open)", "Open Platform")),
    (["动物汽车岛之乔尼特工队"], _yku_entry("YOUKU_OP_ACDSC", "AC", "ANIMACARS", "ACDSC", "ANIMACARS_DISCOVERY", "AnimaCars Discovery (Youku Open)", "Open Platform")),
    (["萌宝儿歌", "One ZeeZ 萌宝儿歌"], _yku_entry("YOUKU_OP_OZ", "OZ", "ONE_ZEES", "OZ", "ONE_ZEES_S1", "One Zees (Youku Open)", "Open Platform")),
    (["大脚卡车镇第二季", "大脚卡车镇 第二季"], _yku_entry("YOUKU_OP_MTS2", "CC", "CARCITY", "MT", "MONSTER_TOWN", "Monster Town S2 (Youku Open)", "Open Platform")),
    (["汽车城之魔法卡车城"], _yku_entry("YOUKU_OP_MCC", "CC", "CARCITY", "MCC", "CARCITY_MAGIC_CAR_CITY", "Magic Car City (Youku Open)", "Open Platform")),
    (["超级小特工学院 第二季", "超级小特工学院第二季"], _yku_entry("YOUKU_OP_SPSH_S2", "SP", "SUPERS", "SPSH", "SUPER_HEROS", "Super Heroes S2 (Youku Open)", "Open Platform")),
    (["超级小特工学院 第一季", "超级小特工学院第一季"], _yku_entry("YOUKU_OP_SPSH_S1", "SP", "SUPERS", "SPSH", "SUPER_HEROS", "Super Heroes S1 (Youku Open)", "Open Platform")),
    (["动物汽车岛之小英雄联盟 第二季", "动物汽车岛之小英雄联盟第二季"], _yku_entry("YOUKU_OP_ACAT_S2", "AC", "ANIMACARS", "ACAT", "ANIMA_TOWN", "AnimaTown S2 (Youku Open)", "Open Platform")),
    (["动物汽车岛之小英雄联盟 第一季", "动物汽车岛之小英雄联盟第一季"], _yku_entry("YOUKU_OP_ACAT_S1", "AC", "ANIMACARS", "ACAT", "ANIMA_TOWN", "AnimaTown S1 (Youku Open)", "Open Platform")),
    (["Miliki超级宝贝米利奇 英文版", "Miliki超级宝贝米利奇英文版"], _yku_entry("YOUKU_OP_MLK_EN", "MLK", "MILIKI", "MLK", "MILIKI_SONGS_S1", "Miliki Songs EN (Youku Open)", "Open Platform")),
    (["超级宝贝米利奇"], _yku_entry("YOUKU_OP_MLK_ZH", "MLK", "MILIKI", "MLK", "MILIKI_SONGS_S1", "Miliki Songs ZH (Youku Open)", "Open Platform")),
]


def _norm_zh_key(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip()).lower()


YOUKU_ALBUM_TITLE_MAP: dict[str, dict[str, str]] = {
    _norm_zh_key(alias): entry
    for aliases, entry in _YOUKU_OP_ENTRIES
    for alias in aliases
}

YOUKU_SERIES_BY_VIDEO_ID: dict[str, dict[str, str]] = {
    **{entry["video_id"]: entry for entry in YOUKU_DAYU_META.values()},
    **{entry["video_id"]: entry for _, entry in _YOUKU_OP_ENTRIES},
}


def get_youku_series_metadata(identifier: str) -> dict[str, str]:
    """Resolves Broadkast IP/Series metadata for a Youku video_id, channel code, or Chinese album title."""
    raw = str(identifier or "").strip()
    if raw in YOUKU_DAYU_META:
        return dict(YOUKU_DAYU_META[raw])
    if raw in YOUKU_SERIES_BY_VIDEO_ID:
        return dict(YOUKU_SERIES_BY_VIDEO_ID[raw])
    norm = _norm_zh_key(raw)
    if norm in YOUKU_ALBUM_TITLE_MAP:
        return dict(YOUKU_ALBUM_TITLE_MAP[norm])
    subplat = "DaYu Platform" if "DAYU" in raw.upper() else "Open Platform"
    return {
        "video_id": raw or "YOUKU_UNKNOWN",
        "project_code": "UNMATCHED",
        "ip_name": "CHANNEL_LEVEL",
        "series_code": "YOUKU",
        "series_name": raw or "Youku Video",
        "title": raw or "Youku Video",
        "subplatform": subplat,
    }


def _iqiyi_entry(
    video_id: str,
    project_code: str,
    ip_name: str,
    series_code: str,
    series_name: str,
    title: str,
    channel_name: str,
) -> dict[str, str]:
    return {
        "video_id": video_id,
        "project_code": project_code,
        "ip_name": ip_name,
        "series_code": series_code,
        "series_name": series_name,
        "title": title,
        "channel_name": channel_name,
    }


IQIYI_CHANNEL_META: dict[str, dict[str, str]] = {
    "2463347304": _iqiyi_entry(
        "IQIYI_CC_CHANNEL",
        "CC",
        "CARCITY",
        "CC_IQIYI",
        "CARCITY_IQIYI_CHANNEL",
        "Amuse CC Channel (iQIYI)",
        "Amuse CC (2463347304)",
    ),
    "2484062153": _iqiyi_entry(
        "IQIYI_LTV_CHANNEL",
        "CHANNEL_LEVEL",
        "CHANNEL_LEVEL",
        "LTV_IQIYI",
        "IQIYI_LTV_CHANNEL",
        "Amuse LTV / France Channel (iQIYI)",
        "Amuse LTV / France (2484062153)",
    ),
    "4318775981759616": _iqiyi_entry(
        "IQIYI_SHANGHAI_CHANNEL",
        "CHANNEL_LEVEL",
        "CHANNEL_LEVEL",
        "SHANGHAI_IQIYI",
        "IQIYI_SHANGHAI_CHANNEL",
        "Amuse Shanghai Channel (iQIYI)",
        "Amuse Shanghai (4318775981759616)",
    ),
}

_IQIYI_SERIES_ENTRIES: list[tuple[list[str], dict[str, str]]] = [
    # One Zees
    (["One ZeeZ 萌宝儿歌", "OneZeeZ 萌宝儿歌", "OneZeez", "萌宝儿歌"], _iqiyi_entry("IQIYI_SERIES_OZ", "OZ", "ONE_ZEES", "OZ", "ONE_ZEES_S1", "One Zees (iQIYI)", "Amuse CC (2463347304)")),
    # AnimaCars
    (["动物汽车岛之乔尼特工队"], _iqiyi_entry("IQIYI_SERIES_ACDSC", "AC", "ANIMACARS", "ACDSC", "ANIMACARS_DISCOVERY", "AnimaCars Discovery (iQIYI)", "Amuse CC (2463347304)")),
    (["动物汽车岛之乔尼特工队 第2季", "动物汽车岛之乔尼特工队第2季"], _iqiyi_entry("IQIYI_SERIES_ACDL", "AC", "ANIMACARS", "ACDL", "ANIMACARS_DAILY_LIFE", "AnimaCars Daily Life S2 (iQIYI)", "Amuse CC (2463347304)")),
    # Learn TV (Dino, Ethan, Ted)
    (["和恐龙戴诺学习"], _iqiyi_entry("IQIYI_SERIES_DINO_S1", "LT", "LEARN_TV", "DINO", "DINO_THE_DINOSAUR", "Dino the Dinosaur S1 (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["和恐龙戴诺学习 第2季", "和恐龙戴诺学习第2季"], _iqiyi_entry("IQIYI_SERIES_DINO_S2", "LT", "LEARN_TV", "DINO", "DINO_THE_DINOSAUR", "Dino the Dinosaur S2 (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["和恐龙戴诺学习 第3季", "和恐龙戴诺学习第3季"], _iqiyi_entry("IQIYI_SERIES_DINO_S3", "LT", "LEARN_TV", "DINO", "DINO_THE_DINOSAUR", "Dino the Dinosaur S3 (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["和恐龙戴诺学习 第4季", "和恐龙戴诺学习第4季"], _iqiyi_entry("IQIYI_SERIES_DINO_S4", "LT", "LEARN_TV", "DINO", "DINO_THE_DINOSAUR", "Dino the Dinosaur S4 (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["恐龙戴诺之趣味学常识"], _iqiyi_entry("IQIYI_SERIES_DINO_LUDIQUE", "LT", "LEARN_TV", "DINO", "DINO_SVOD_FUN_KNOWLEDGE", "Dino: Fun Knowledge (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["恐龙戴诺儿童英语", "恐龙戴诺儿童启蒙英语"], _iqiyi_entry("IQIYI_SERIES_DINO_ENGLISH", "LT", "LEARN_TV", "DINO", "DINO_SVOD_ENGLISH", "Dino: Kids English (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["恐龙戴诺之语言认知能力培养", "恐龙戴诺之语言能力培养"], _iqiyi_entry("IQIYI_SERIES_DINO_COGNITION", "LT", "LEARN_TV", "DINO", "DINO_SVOD_COGNITION", "Dino: Communication Skills (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["和翻斗车伊森学习"], _iqiyi_entry("IQIYI_SERIES_ETHAN_S1", "LT", "LEARN_TV", "ETHAN", "ETHAN_THE_DUMP_TRUCK", "Ethan the Dump Truck S1 (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["和翻斗车伊森学习 第2季", "和翻斗车伊森学习第2季"], _iqiyi_entry("IQIYI_SERIES_ETHAN_S2", "LT", "LEARN_TV", "ETHAN", "ETHAN_THE_DUMP_TRUCK", "Ethan the Dump Truck S2 (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["和翻斗车伊森学习 第3季", "和翻斗车伊森学习第3季"], _iqiyi_entry("IQIYI_SERIES_ETHAN_S3", "LT", "LEARN_TV", "ETHAN", "ETHAN_THE_DUMP_TRUCK", "Ethan the Dump Truck S3 (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["和火车泰德学习"], _iqiyi_entry("IQIYI_SERIES_TED", "LT", "LEARN_TV", "TED", "TED_THE_TRAIN", "Ted the Train (iQIYI)", "Amuse LTV / France (2484062153)")),
    # Tiny World
    (["和迷你卡车学习"], _iqiyi_entry("IQIYI_SERIES_TINY_S1", "TW", "TINY_WORLD", "TINY", "TINY_TRUCKS", "Tiny Trucks S1 (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["和迷你卡车学习 第2季", "和迷你卡车学习第2季"], _iqiyi_entry("IQIYI_SERIES_TINY_S2", "TW", "TINY_WORLD", "TINY", "TINY_TRUCKS", "Tiny Trucks S2 (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["和迷你卡车学习 第3季", "和迷你卡车学习第3季"], _iqiyi_entry("IQIYI_SERIES_TINY_S3", "TW", "TINY_WORLD", "TINY", "TINY_TRUCKS", "Tiny Trucks S3 (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["迷你卡车乐园"], _iqiyi_entry("IQIYI_SERIES_TT", "TW", "TINY_WORLD", "TT", "TINY_TOWN", "Tiny Town (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["迷你卡车之科学藏宝箱"], _iqiyi_entry("IQIYI_SERIES_TINY_SCIENCE", "TW", "TINY_WORLD", "TINY", "TINY_SVOD_SCIENCE_BOX", "Tiny Trucks: Science Treasure Box (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["迷你卡车之空间创造篇"], _iqiyi_entry("IQIYI_SERIES_TINY_SPACE", "TW", "TINY_WORLD", "TINY", "TINY_SVOD_SPACE_CREATIVITY", "Tiny Trucks: Space Creativity (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["迷你卡车之趣味学常识"], _iqiyi_entry("IQIYI_SERIES_TINY_KNOWLEDGE", "TW", "TINY_WORLD", "TINY", "TINY_SVOD_FUN_KNOWLEDGE", "Tiny Trucks: Fun Knowledge (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["迷你卡车之趣味想象力篇"], _iqiyi_entry("IQIYI_SERIES_TINY_IMAGINATION", "TW", "TINY_WORLD", "TINY", "TINY_SVOD_IMAGINATION", "Tiny Trucks: Imagination (iQIYI)", "Amuse LTV / France (2484062153)")),
    # Car City Core Series
    (["大脚卡车镇"], _iqiyi_entry("IQIYI_SERIES_MT", "CC", "CARCITY", "MT", "MONSTER_TOWN", "Monster Town (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之救护车安柏"], _iqiyi_entry("IQIYI_SERIES_AA", "CC", "CARCITY", "AA", "AMBER_THE_AMBULANCE", "Amber the Ambulance (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之建筑队"], _iqiyi_entry("IQIYI_SERIES_CS", "CC", "CARCITY", "CS", "CONSTRUCTION_SQUAD", "Construction Squad (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之拖车汤姆"], _iqiyi_entry("IQIYI_SERIES_TOM_S1", "CC", "CARCITY", "TOM", "TOM_THE_TOW_TRUCK", "Tom the Tow Truck S1 (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之拖车汤姆 第2季", "汽车城之拖车汤姆第2季"], _iqiyi_entry("IQIYI_SERIES_TOM_S2", "CC", "CARCITY", "TOM", "TOM_THE_TOW_TRUCK", "Tom the Tow Truck S2 (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之拖车汤姆 第3季", "汽车城之拖车汤姆第3季"], _iqiyi_entry("IQIYI_SERIES_TOM_S3", "CC", "CARCITY", "TOM", "TOM_THE_TOW_TRUCK", "Tom the Tow Truck S3 (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之汤姆的油漆店"], _iqiyi_entry("IQIYI_SERIES_TPS_S1", "CC", "CARCITY", "TPS", "TOM_PAINT_SHOP", "Tom's Paint Shop S1 (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之汤姆的油漆店 第2季", "汽车城之汤姆的油漆店第2季"], _iqiyi_entry("IQIYI_SERIES_TPS_S2", "CC", "CARCITY", "TPS", "TOM_PAINT_SHOP", "Tom's Paint Shop S2 (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之汤姆的洗车店"], _iqiyi_entry("IQIYI_SERIES_TCW", "CC", "CARCITY", "TCW", "TOMS_CAR_WASH", "Tom's Car Wash (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之汽车宝贝们"], _iqiyi_entry("IQIYI_SERIES_BB", "CC", "CARCITY", "BB", "BABIES_IN_CARCITY", "Babies in Car City (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之火车特洛伊"], _iqiyi_entry("IQIYI_SERIES_TROY_S1", "CC", "CARCITY", "TROY", "TROY_THE_TRAIN", "Troy the Train S1 (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之火车特洛伊 第2季", "汽车城之火车特洛伊第2季"], _iqiyi_entry("IQIYI_SERIES_TROY_S2", "CC", "CARCITY", "TROY", "TROY_THE_TRAIN", "Troy the Train S2 (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之火车特洛伊 第3季", "汽车城之火车特洛伊第3季"], _iqiyi_entry("IQIYI_SERIES_TROY_S3", "CC", "CARCITY", "TROY", "TROY_THE_TRAIN", "Troy the Train S3 (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之警车和消防车", "汽车城警车和消防车"], _iqiyi_entry("IQIYI_SERIES_CP_S1", "CC", "CARCITY", "CP", "CAR_PATROL", "Car Patrol S1 (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之警车和消防车 第2季", "汽车城之警车和消防车第2季"], _iqiyi_entry("IQIYI_SERIES_CP_S2", "CC", "CARCITY", "CP", "CAR_PATROL", "Car Patrol S2 (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之警车和消防车 第3季", "汽车城之警车和消防车第3季"], _iqiyi_entry("IQIYI_SERIES_CP_S3", "CC", "CARCITY", "CP", "CAR_PATROL", "Car Patrol S3 (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城警车和消防车 第4季", "汽车城警车和消防车第4季", "汽车城之警车和消防车 第4季"], _iqiyi_entry("IQIYI_SERIES_CP_S4", "CC", "CARCITY", "CP", "CAR_PATROL", "Car Patrol S4 (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之警车和消防车 英文版", "汽车城之警车和消防车+英文版", "汽车城之警车和消防车_英文版", "汽车城之警车和消防车 英文"], _iqiyi_entry("IQIYI_SERIES_CP_EN", "CC", "CARCITY", "CP", "CAR_PATROL", "Car Patrol English (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之超级变形卡车"], _iqiyi_entry("IQIYI_SERIES_CARL_S1", "CC", "CARCITY", "CARL", "SUPER_TRUCK", "Super Truck S1 (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之超级变形卡车 第2季", "汽车城之超级变形卡车第2季"], _iqiyi_entry("IQIYI_SERIES_CARL_S2", "CC", "CARCITY", "CARL", "SUPER_TRUCK", "Super Truck S2 (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之超级变形卡车 第3季", "汽车城之超级变形卡车第3季"], _iqiyi_entry("IQIYI_SERIES_CARL_S3", "CC", "CARCITY", "CARL", "SUPER_TRUCK", "Super Truck S3 (iQIYI)", "Amuse CC (2463347304)")),
    # Car City Thematic & SVOD Playlists
    (["汽车城之世界杯足球特辑"], _iqiyi_entry("IQIYI_SERIES_CC_WORLDCUP", "CC", "CARCITY", "CC_WORLDCUP", "CARCITY_THEMATIC_WORLD_CUP", "Car City: World Cup Soccer (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之圣诞冬日特辑"], _iqiyi_entry("IQIYI_SERIES_CC_CHRISTMAS", "CC", "CARCITY", "CC_XMAS", "CARCITY_THEMATIC_CHRISTMAS", "Car City: Christmas Winter (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之新春快乐", "汽车城牛牛贺岁专辑"], _iqiyi_entry("IQIYI_SERIES_CC_NEWYEAR", "CC", "CARCITY", "CC_CNY", "CARCITY_THEMATIC_NEW_YEAR", "Car City: Chinese New Year (iQIYI)", "Amuse CC (2463347304)")),
    (["汽车城之世界环游篇"], _iqiyi_entry("IQIYI_SERIES_CC_WORLDTOUR", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_WORLD_TOUR", "Car City: World Tour (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之交通安全篇"], _iqiyi_entry("IQIYI_SERIES_CC_SAFETY", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_TRAFFIC_SAFETY", "Car City: Traffic Safety (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之创造力培养"], _iqiyi_entry("IQIYI_SERIES_CC_CREATIVITY", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_CREATIVITY", "Car City: Creativity Development (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之友爱互助篇"], _iqiyi_entry("IQIYI_SERIES_CC_FRIENDSHIP", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_FRIENDSHIP", "Car City: Friendship & Solidarity (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之奥运特别篇"], _iqiyi_entry("IQIYI_SERIES_CC_OLYMPIC", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_OLYMPIC", "Car City: Olympic Special (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之好习惯养成篇"], _iqiyi_entry("IQIYI_SERIES_CC_HABITS", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_GOOD_HABITS", "Car City: Good Habits (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之工程探索篇"], _iqiyi_entry("IQIYI_SERIES_CC_CONSTRUCTION", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_CONSTRUCTION", "Car City: Construction Exploration (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之探索冒险篇"], _iqiyi_entry("IQIYI_SERIES_CC_ADVENTURE", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_ADVENTURE", "Car City: Adventure & Exploration (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之最美四季特别篇"], _iqiyi_entry("IQIYI_SERIES_CC_SEASONS", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_FOUR_SEASONS", "Car City: Four Seasons Special (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之最酷变形"], _iqiyi_entry("IQIYI_SERIES_CC_TRANSFORM", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_TRANSFORMATIONS", "Car City: Coolest Transformations (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之最酷美食"], _iqiyi_entry("IQIYI_SERIES_CC_FOODIES", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_FOODIES", "Car City: Coolest Foodies (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之最酷艺术家"], _iqiyi_entry("IQIYI_SERIES_CC_ARTIST", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_ARTIST", "Car City: Coolest Artist (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之最酷超级英雄"], _iqiyi_entry("IQIYI_SERIES_CC_SUPERHERO", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_SUPER_HERO", "Car City: Coolest Super Hero (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之环游世界过新年"], _iqiyi_entry("IQIYI_SERIES_CC_NY_TOUR", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_NEW_YEAR_TOUR", "Car City: New Year Over the World (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之神奇小医生"], _iqiyi_entry("IQIYI_SERIES_CC_DOCTOR", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_LITTLE_DOCTOR", "Car City: Magic Little Doctor (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之神秘大侦探"], _iqiyi_entry("IQIYI_SERIES_CC_DETECTIVE", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_DETECTIVE", "Car City: Mysterious Detective (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之精彩营救篇", "超级汽车城之精彩营救篇"], _iqiyi_entry("IQIYI_SERIES_CC_RESCUE", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_RESCUE", "Car City: Rescue (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之自我保护篇"], _iqiyi_entry("IQIYI_SERIES_CC_SELFPROT", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_SELF_PROTECTION", "Car City: Self Protection (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之节日嘉年华"], _iqiyi_entry("IQIYI_SERIES_CC_CARNIVAL", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_CARNIVAL", "Car City: Carnival Festival (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之节日庆祝篇"], _iqiyi_entry("IQIYI_SERIES_CC_FESTIVAL", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_FESTIVAL", "Car City: Festival Celebration (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之超级竞速"], _iqiyi_entry("IQIYI_SERIES_CC_FASTFURIOUS", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_FAST_FURIOUS", "Car City: Fast and Furious (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城之趣味世界民俗"], _iqiyi_entry("IQIYI_SERIES_CC_FOLKLORE", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_FOLKLORE", "Car City: Fun World Folklore (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["汽车城系列"], _iqiyi_entry("IQIYI_SERIES_CC_SERIES", "CC", "CARCITY", "CC_SVOD", "CARCITY_SERIES", "Car City Series (iQIYI)", "Amuse LTV / France (2484062153)")),
    (["超级汽车城之英雄卡车"], _iqiyi_entry("IQIYI_SERIES_CC_HEROTRUCK", "CC", "CARCITY", "CC_HERO", "CARCITY_HERO_TRUCK", "Super Car City: Hero Truck (iQIYI)", "Amuse CC (2463347304)")),
    (["超级汽车城之解决问题的能力"], _iqiyi_entry("IQIYI_SERIES_CC_PROBLEMSOLV", "CC", "CARCITY", "CC_SVOD", "CARCITY_SVOD_PROBLEM_SOLVING", "Car City Super: Problem Solving (iQIYI)", "Amuse LTV / France (2484062153)")),
]


def _norm_iqiyi_key(text: str) -> str:
    return re.sub(r"[\s\u3000_+]+", "", str(text or "").strip()).lower()


IQIYI_ALBUM_TITLE_MAP: dict[str, dict[str, str]] = {
    _norm_iqiyi_key(alias): entry
    for aliases, entry in _IQIYI_SERIES_ENTRIES
    for alias in aliases
}

IQIYI_SERIES_BY_VIDEO_ID: dict[str, dict[str, str]] = {
    **{entry["video_id"]: entry for entry in IQIYI_CHANNEL_META.values()},
    **{entry["video_id"]: entry for _, entry in _IQIYI_SERIES_ENTRIES},
}


def get_iqiyi_series_metadata(identifier: str, channel_hint: str = "") -> dict[str, str]:
    """Resolves Broadkast IP/Series metadata for an iQIYI video_id, channel id, or Chinese album title."""
    raw = str(identifier or "").strip()
    if raw in IQIYI_CHANNEL_META:
        return dict(IQIYI_CHANNEL_META[raw])
    if raw in IQIYI_SERIES_BY_VIDEO_ID:
        return dict(IQIYI_SERIES_BY_VIDEO_ID[raw])
    norm = _norm_iqiyi_key(raw)
    if norm in IQIYI_ALBUM_TITLE_MAP:
        return dict(IQIYI_ALBUM_TITLE_MAP[norm])
    ch = channel_hint or "Unknown iQIYI Channel"
    return {
        "video_id": raw or "IQIYI_UNKNOWN",
        "project_code": "UNMATCHED",
        "ip_name": "CHANNEL_LEVEL",
        "series_code": "IQIYI",
        "series_name": raw or "iQIYI Series",
        "title": raw or "iQIYI Series",
        "channel_name": ch,
    }
