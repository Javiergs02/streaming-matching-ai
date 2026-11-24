"""
Language detection and resolution rules for multi-platform catalog and performance events.
"""
from __future__ import annotations

import re
from typing import Optional, Dict


# Common multilingual stopword and keyword patterns
ES_WORDS = re.compile(
    r"\b(el|la|los|las|un|una|unos|unas|del|al|en|de|con|por|para|y|o|pero|más|bebé|bebe|bebes|bebés|"
    r"día|dia|patio|recreo|escuela|fuego|camino|camión|camion|rescate|amigos|navidad|árbol|arbol|"
    r"galletas|carreras|ciudad|baile|batalla|concurso|tramposo|bromea|mezclando|castillo|inflable|"
    r"perro|pata|pistas|aprende|números|colores|canción|cancion|fiesta|aventura|abuela|abuelo|"
    r"jugando|nuevo|episodio|temporada|parte|capítulo|capitulo)\b",
    re.IGNORECASE
)

PT_WORDS = re.compile(
    r"\b(o|a|os|as|um|uma|do|da|dos|das|no|na|nos|nas|em|com|para|de|e|não|nao|bebê|bebe|bebês|bebes|"
    r"caminhão|caminhao|resgate|amigos|natal|árvore|arvore|fogo|corrida|cidade|construção|construcao|"
    r"tesouro|caça|caca|está|esta|fica|onde|brincando|desaparecimento|rainha|neve|coberta|polícia|"
    r"policia|bombeiro|pequenos|novo|episódio|episodio|temporada)\b",
    re.IGNORECASE
)

DE_WORDS = re.compile(
    r"\b(der|die|das|dem|den|des|ein|eine|einer|einem|einen|und|oder|in|im|von|vom|mit|zu|zum|zur|"
    r"auf|für|nicht|ist|sind|stadt|zug|lkw|bagger|feuer|rettung|freunde|weihnachten|spiel|spiele|"
    r"nachbarschaft|versteckspiele|schnee|abenteuer|große|kleine|neue|folge|staffel)\b",
    re.IGNORECASE
)

FR_WORDS = re.compile(
    r"\b(le|la|les|un|une|des|du|de|au|aux|en|dans|avec|pour|par|sur|et|ou|est|sont|pas|qui|que|"
    r"ville|train|camion|pompier|sauvetage|amis|noël|noel|fête|fete|course|plage|recyclage|neige|"
    r"glace|fait|avec|petit|petite|nouveau|nouvel|saison|épisode|episode)\b",
    re.IGNORECASE
)

IT_WORDS = re.compile(
    r"\b(il|lo|la|i|gli|le|un|uno|una|del|dello|della|dei|degli|delle|nel|nello|nella|nei|negli|nelle|"
    r"al|allo|alla|ai|agli|alle|in|con|su|per|tra|fra|e|ed|non|che|squadra|camion|treno|città|citta|"
    r"salvataggio|amici|natale|corsa|cattivi|venditori|fiera|cappello|magico|piccoli|nuovo|episodio|stagione)\b",
    re.IGNORECASE
)

EN_WORDS = re.compile(
    r"\b(the|a|an|and|or|of|in|on|at|to|for|with|by|from|is|are|was|were|day|beach|playground|"
    r"baby|babies|truck|trucks|car|cars|train|city|rescue|fire|patrol|squad|friends|christmas|"
    r"tree|presents|song|songs|sing|soup|learn|numbers|colors|battle|prank|pranking|candy|pizza|"
    r"falling|out|adventure|monster|game|games|super|little|big|road|hoops|get|well|cook|"
    r"decorate|new|episode|part|season|hide|seek|lost|puppy|show|potty|police|race)\b",
    re.IGNORECASE
)


def detect_title_language(
    title: Optional[str] = "",
    territory: Optional[str] = None,
    geo_to_lang: Optional[Dict[str, str]] = None
) -> str:
    """
    Infers the language code ('en', 'es', 'de', 'fr', 'ja', etc.) based on title text.
    Falls back to the territory's predominant language or 'en' if the title is ambiguous or neutral.

    Args:
        title: Title of the video, episode, or compilation.
        territory: Country code of consumption/marketplace (e.g. 'US', 'ES', 'DE').
        geo_to_lang: Optional dictionary mapping country codes to language codes.

    Returns:
        Two-letter ISO 639-1 language code.
    """
    if not title or not isinstance(title, str) or title.strip() in ("", "-", "Unknown Title", "Unknown Episode"):
        if geo_to_lang and territory:
            return geo_to_lang.get(str(territory).upper(), "en")
        return "en"

    clean_title = title.strip()
    t_lower = clean_title.lower()

    # 1. Non-Latin writing systems (unambiguous)
    # Japanese (Hiragana, Katakana, Kanji)
    if re.search(r"[\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff]", clean_title):
        return "ja"
    # Cyrillic (Russian, Ukrainian, etc.)
    if re.search(r"[\u0400-\u04ff]", clean_title):
        return "ru"
    # Korean Hangul
    if re.search(r"[\uac00-\ud7af]", clean_title):
        return "ko"
    # Arabic
    if re.search(r"[\u0600-\u06ff]", clean_title):
        return "ar"

    # 2. Distinctive diacritics and accents
    es_score = len(re.findall(r"[áíóúñ¿¡]", t_lower)) * 3
    pt_score = len(re.findall(r"[ãõçê]", t_lower)) * 3
    de_score = len(re.findall(r"[äöüß]", t_lower)) * 3
    fr_score = len(re.findall(r"[èëàùôœæ]", t_lower)) * 3
    it_score = 0

    # 3. Stopwords and frequent vocabulary scoring
    es_score += len(ES_WORDS.findall(t_lower)) * 2
    pt_score += len(PT_WORDS.findall(t_lower)) * 2
    de_score += len(DE_WORDS.findall(t_lower)) * 2
    fr_score += len(FR_WORDS.findall(t_lower)) * 2
    it_score += len(IT_WORDS.findall(t_lower)) * 2
    en_score = len(EN_WORDS.findall(t_lower)) * 2

    scores = {
        "es": es_score,
        "pt": pt_score,
        "de": de_score,
        "fr": fr_score,
        "it": it_score,
        "en": en_score
    }

    best_lang, best_score = max(scores.items(), key=lambda x: x[1])
    if best_score >= 2:
        return best_lang

    # 4. Fallback if inconclusive or short neutral name (e.g. "Tom", "Carl")
    if geo_to_lang and territory:
        return geo_to_lang.get(str(territory).upper(), "en")

    return "en"
