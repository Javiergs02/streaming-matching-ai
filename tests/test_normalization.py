"""Unit tests for title normalization."""

import pytest
from core.normalization.title import normalize_title


def test_normalize_title_basic():
    assert normalize_title("Hello World!") == "hello world"


def test_normalize_title_diacritics():
    # Spanish accents and diacritics
    assert normalize_title("Super-Héroes!") == "super heroes"
    assert normalize_title("Canción del ABC") == "cancion del abc"
    assert normalize_title("Groovy el Marciano") == "groovy el marciano"


def test_normalize_title_compilation_markers():
    # Compilation markers truncate title at first marker ('/', '|', ' - ', '&', ' + ', etc.)
    assert normalize_title("Miliky & Friends") == "miliky"
    assert normalize_title("Episode 1 / Episode 2 / Episode 3") == "episode 1"
    assert normalize_title("Car City - Tom the Tow Truck") == "car city"
    assert normalize_title("Song A + Song B") == "song a"


def test_normalize_title_casing_and_whitespace():
    assert normalize_title("   MULTIPLE    SPACES   ") == "multiple spaces"
    assert normalize_title("") == ""
    assert normalize_title("   ") == ""

