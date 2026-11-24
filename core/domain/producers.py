"""
Producer & studio resolution rules for Amuse Animation, external distributions, and UNMATCHED titles.
"""
from __future__ import annotations

import re
from typing import Optional


# Patterns for third-party distributors / external studios: (tuple_of_keywords, producer_name)
EXTERNAL_PRODUCER_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    # Shadow Studio
    (
        ("cool city",),
        "Shadow Studio"
    ),

    # Shout! Factory
    (
        ("jasper", "penguim jasper", "pinguino jasper"),
        "Shout! Factory"
    ),

    # Sunnyside Studios (Groovy The Martian & Superzoo)
    (
        ("groovy", "superzoo"),
        "Sunnyside Studios"
    ),

    # Millimages
    (
        ("molang", "моланг"),
        "Millimages"
    ),
    (
        ("mouk", "mokon suuri maailma", "мук", "ムーク"),
        "Millimages"
    ),
    (
        ("louie", "didou", "mal mir", "luluś", "lulus", "piirrä minulle", "tegn meg", "рисунки тёмы"),
        "Millimages"
    ),
    (
        ("corneil & bernie", "corneil and bernie", "corneil et bernie", "watch my chops"),
        "Millimages"
    ),
    (
        ("mimi cracra",),
        "Millimages"
    ),
    (
        ("saturnin",),
        "Millimages"
    ),
    (
        ("caroline et ses amis",),
        "Millimages"
    ),
    (
        ("mon robot et moi",),
        "Millimages"
    ),
    (
        ("nasreddin", "nasredine", "маджарохае насредин"),
        "Millimages"
    ),
    (
        ("diego & ziggy", "diego et ziggy", "diego y ziggy"),
        "Millimages"
    ),
    (
        ("64 zoo lane", "calle del zoológico 64", "calle del zoologico 64", "calle del zool", "動物園通り64番地"),
        "Millimages"
    ),
    (
        ("kung fu bunny",),
        "Millimages"
    ),
    (
        ("niko", "niko le petit renne", "niko 2"),
        "Millimages"
    ),
    (
        ("piccolo, saxo", "piccolo saxo"),
        "Millimages"
    ),
    (
        ("lascars",),
        "Millimages"
    ),
    (
        ("pirata et capitano", "pirata & capitano", "pirata y capitano", "pirata capitano", "pirata e capitano"),
        "Millimages"
    ),
    (
        ("homiez", "round da way"),
        "Millimages"
    ),
    (
        ("jump around",),
        "Millimages"
    ),
    (
        ("renaissance",),
        "Millimages"
    ),

    # Gulli / Lagardère / M6
    (
        ("gulli", "gu'live", "tiji", "canal j", "elle girl", "mcm la chaîne", "mcm la chaine", "june tv", "tahiti quest", "safari go"),
        "Gulli / Lagardère"
    ),

    # External Partner Studios & Creators
    (
        ("pitchoun", "pitchoun toons"),
        "Pitchoun Médias"
    ),
    (
        ("lévanah", "levanah"),
        "Lévanah Solomon"
    ),
    (
        ("brèves de classe", "breves de classe"),
        "Brèves de Classe"
    ),
    (
        ("rainbow chicks",),
        "Rainbow Chicks"
    ),

    # Toonbox
    (
        ("kit ^n^ kate", "kit n kate", "kit and kate", "kit i kate"),
        "Toonbox"
    ),
]

# Standard catalogue list for dashboard filters
KNOWN_PRODUCERS: list[str] = [
    "Amuse Animation",
    "Millimages",
    "Gulli / Lagardère",
    "Pitchoun Médias",
    "Lévanah Solomon",
    "Sunnyside Studios",
    "Shadow Studio",
    "Shout! Factory",
    "Toonbox",
    "Brèves de Classe",
    "Rainbow Chicks",
    "Sin Asignar"
]

AMUSE_KEYWORDS: tuple[str, ...] = (
    # Car City & vehicle franchise
    "car city", "bilköping", "bilkã¶ping", "autopolis", "orasul masinilor", "автомобильном городе", "малыши", "ð¼ð°ð»ñ‹ñˆð¸",
    "tom ", "tom'", "toms", "tom's", "tomun", "tom'un", "tomovo", "tomova", "odtahov", "toma", "тома",
    "recker", "レッカー車のトム", "トム", "tom die tou", "sanggar lukis tom",
    "spalatoria auto a lui tom", "малярная мастерская", "малярная", "ñ‚ð¾ð¼", "ð¼ð°ð»ñ ", "ð¼ð°ð»ñ ñ€ð½ð°ñ ", "βαφείο", "ï„î¿ î²î±ï†îµî¯î¿",
    "carl super truck", "super truck", "super camion", "super caminhão", "super camión", "superlastbilen",
    "carl si truk", "carl de supertruck", "carl il super truck", "σούπερ φορτηγό", "îšî±ï",
    "troy the train", "tåget troy", "troy le train", "troy o trem", "troy der zug", "troy",
    "ted el tren", "ted o trem", "ted poci", "ted il treno", "trenul ted", "ted le train", "τρόυ", "î¤ï", "トレインと一緒に学ぼう",
    "car patrol", "super pattuglia", "カーパトロール", "περιπολία", "î— î",
    "construction squad", "byggänget", "byggã¤nget", "echipa de constructii", "ekipa budowla", "construçao", "construção",
    "建設チーム", "inşaat ekibi", "inşaat", "nşaat ekibi", "ekibi", "înåÿaat", "ä°nåÿaat", "thi công", "cã´ng", "î¤î¿",
    "bebes en auto", "babies in car city", "go go babies", "piccoli a car city",
    "amber l'ambulance", "amber, a ambulância", "amber the ambulance", "amber",
    "ethan la volqueta", "ethan le camion", "ethan wywrotka", "ethan the dump truck", "ethan", "игорь", "игорем", "самосвалом игорем", "грузовичком игорем", "учимся вместе с игорем",
    "tiny town", "tiny trucks", "tiny cars", "ciudad mini", "mini cidade", "winzige stadt", "minik kamyonlar", "маленькими грузовичками", "грузовичками", "ñƒñ‡ð¸ð¼",
    "truck games", "monster trucks",
    # Learning TV & Dinosaurs
    "dino the dinosaur", "dino dem dinosaurier", "dino il dinosauro", "恐竜のダイノ", "dino",
    "jeppy", "learn tv", "lucas el camioncito",
    # Fairy tales, music & other Amuse IPs
    "increditales", "märchen für kinder", "fairy tales for kids", "adorável demais para assustar", "おとぎ話",
    "the supers", "shark academy", "sharkies", "shark city",
    "aladdin", "アラジン",
    "birdie",
    "animacars", "アニマカーズ",
    "lily's lovely songs", "lily's songs", "lilys lovely songs", "lilys songs",
    "plum the super witch", "robofuse", "miliki", "spooky songs", "monster town", "jonny toolbox", "jonny & friends",
    # Additional Amuse network franchises & series
    "cam & sam", "cam and sam", "baby shark", "sharky family", "bebé tiburón", "bebe tiburon", "baby sharky",
    "kidsflix", "kids flix", "one zeez", "onezeez", "los one zeez", "pete the ghost",
    "coloring pages", "super kids learning", "tiny world", "incredible tales", "fairy tales"
)


def resolve_producer(
    title: Optional[str] = "",
    series_name: Optional[str] = "",
    ip_name: Optional[str] = "",
    platform: Optional[str] = None
) -> str:
    """
    Determines the producer / studio based on title, series_name, IP name, and platform.

    Returns:
        - Producer name for known third-party studios (e.g. "Millimages", "Sunnyside Studios", "Shadow Studio")
        - "Amuse Animation" for proprietary IPs, matched catalog titles, Amuse international series, and Amuse CMS channels
        - "Sin Asignar" for unclassified UNMATCHED records from external distributions
    """
    s_title = (str(title) if title is not None else "").lower()
    s_series = (str(series_name) if series_name is not None else "").lower()
    s_ip = (str(ip_name) if ip_name is not None else "").strip().upper()
    s_plat = (str(platform) if platform is not None else "").strip().lower()

    combined_text = f"{s_series} {s_title}"

    # 1. Match external third-party patterns
    for patterns, producer in EXTERNAL_PRODUCER_PATTERNS:
        for p in patterns:
            if p in combined_text:
                return producer

    # 2. Check if it's already an identified Amuse IP in Broadkast
    if s_ip and s_ip not in ("UNMATCHED", "UNKNOWN", "UNKNOWN IP", "NAN", "NONE", ""):
        return "Amuse Animation"

    # 3. Check for known Amuse series keywords
    if any(ak in combined_text for ak in AMUSE_KEYWORDS):
        return "Amuse Animation"

    # 4. For YouTube: all managed channels belong to the Amuse Animation CMS network
    if s_plat == "youtube":
        return "Amuse Animation"

    # 5. Fallback for unclassified UNMATCHED records
    if s_ip in ("UNMATCHED", "UNKNOWN", "UNKNOWN IP", ""):
        return "Sin Asignar"

    return "Amuse Animation"
