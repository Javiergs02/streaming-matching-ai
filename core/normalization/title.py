"""Title normalization for matching preparation.

Converts titles like "Super-Heróis!" and "Super Heróis" into a
common comparable form.

The original titles are never modified — normalization produces
a separate value.
"""

from __future__ import annotations

import functools
import re
import unicodedata

_LATIN_MAX = 0x0300


def _strip_latin_diacritics(text: str) -> str:
    """Remove diacritics from Latin characters only.

    NFD decomposition is applied to the whole string, but combining
    marks are only removed when their base character is Latin (ord <
    0x0300).  Marks following non-Latin base characters — e.g. Katakana
    dakuten (゛) or handakuten (゜) — are preserved.  NFC is applied at
    the end to recompose any surviving decomposed sequences.
    """
    decomposed = unicodedata.normalize("NFD", text)
    result: list[str] = []
    for char in decomposed:
        if unicodedata.combining(char) and result and ord(result[-1]) < _LATIN_MAX:
            continue
        result.append(char)
    return unicodedata.normalize("NFC", "".join(result))


def _replace_punctuation_and_symbols(text: str) -> str:
    """Replace every Unicode punctuation (P*) or symbol (S*) char with a space.

    Replacing — rather than deleting — prevents adjacent words from
    fusing together (e.g. "Super-Heróis" → "super herois", not
    "superherois").
    """
    return "".join(
        c if not (
            unicodedata.category(c).startswith("P")
            or unicodedata.category(c).startswith("S")
        )
        else " "
        for c in text
    )


def _remove_format_characters(text: str) -> str:
    """Remove Unicode format characters (Cf) such as zero-width spaces."""
    return "".join(c for c in text if unicodedata.category(c) != "Cf")


@functools.lru_cache(maxsize=131072)
def normalize_title(title: str) -> str:
    """Normalize a title for comparison purposes.

    Transformations (applied in order):
      1. Strip leading/trailing whitespace
      2. Truncate at the first compilation marker
      3. Lowercase
      4. Remove format characters (zero-width spaces, soft hyphens…)
      5. Remove diacritics from Latin characters only (NFD selective)
      6. Replace punctuation/symbols with spaces (prevents word fusion)
      7. Collapse consecutive whitespace
      8. Strip final whitespace
      
    Args:
        title: The original title string.

    Returns:
        The normalized title, or an empty string if input is empty/whitespace.
    """
    if not title or not isinstance(title, str):
        return ""

    title = title.strip()

    if not title:
        return ""
        
    # BUSINESS RULE: Ignore everything after the first compilation marker
    # Compilations use separators like "/", "|", " & ", " + ", " - " (Fix M7)
    compilation_markers = ["/", "|", " - ", " & ", " + ", " そして", " ＆ "]
    for marker in compilation_markers:
        if marker in title:
            title = title.split(marker, 1)[0].strip()

    title = title.lower()
    title = _remove_format_characters(title)
    title = _strip_latin_diacritics(title)
    title = _replace_punctuation_and_symbols(title)
    title = re.sub(r"\s+", " ", title).strip()

    return title
