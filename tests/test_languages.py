import pytest
from core.domain.languages import detect_title_language

GEO_TO_LANG = {
    "ES": "es",
    "MX": "es",
    "AR": "es",
    "CO": "es",
    "US": "en",
    "GB": "en",
    "DE": "de",
    "FR": "fr",
    "IT": "it",
    "JP": "ja",
    "BR": "pt",
    "PT": "pt",
}

def test_detect_user_cases():
    # User examples of English titles consumed in Spanish territories
    assert detect_title_language("BEACH Day at the Playground", "MX", GEO_TO_LANG) == "en"
    assert detect_title_language("Baby Ben is Pranking all Around", "MX", GEO_TO_LANG) == "en"
    assert detect_title_language("Decorate a CHRISTMAS TREE", "ES", GEO_TO_LANG) == "en"
    assert detect_title_language("SING Christmas Carols", "MX", GEO_TO_LANG) == "en"
    assert detect_title_language("Cook a Get-Well Soup", "ES", GEO_TO_LANG) == "en"
    assert detect_title_language("Road Rescue!", "MX", GEO_TO_LANG) == "en"
    assert detect_title_language("Musical Hoops", "ES", GEO_TO_LANG) == "en"

    # User examples of Spanish localized titles
    assert detect_title_language(
        "Mezclando Pizza de Caramelos / El Castillo Inflable / Bebe Jaremy es un Tramposo", 
        "MX", GEO_TO_LANG
    ) == "es"
    assert detect_title_language(
        "【Nuevo episodio!】¡Únete a la Batalle de Baile! / El fuego en la escuela / Un concurso de reciclaje de basura", 
        "ES", GEO_TO_LANG
    ) == "es"
    assert detect_title_language(
        "Bebe Jerry y Bebe Katie se disgustan / Bebe Ben bromea con todo su Alrededor / Bebe Pickle la camino", 
        "ES", GEO_TO_LANG
    ) == "es"

def test_detect_other_major_languages():
    # German
    assert detect_title_language("Feuer in der Nachbarschaft / Versteckspiele", "DE", GEO_TO_LANG) == "de"
    # Japanese
    assert detect_title_language("ズータスティック・アニマルズ/フライング・キャップ", "JP", GEO_TO_LANG) == "ja"
    # Portuguese
    assert detect_title_language("Combatendo o Fogo / O Resgate do Wheelephant", "BR", GEO_TO_LANG) == "pt"
    # French
    assert detect_title_language("Recyclage à la plage", "FR", GEO_TO_LANG) == "fr"
    # Italian
    assert detect_title_language("Cattivi venditori / Confusione alla Fiera / Il Cappello Magico", "IT", GEO_TO_LANG) == "it"

def test_detect_fallback():
    # Ambiguous or empty titles fall back to territory language
    assert detect_title_language("", "DE", GEO_TO_LANG) == "de"
    assert detect_title_language("Unknown Title", "ES", GEO_TO_LANG) == "es"
    assert detect_title_language(None, "JP", GEO_TO_LANG) == "ja"
    assert detect_title_language(None, None, None) == "en"
