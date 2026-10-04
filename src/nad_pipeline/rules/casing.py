"""Name casing for sources that deliver ALL CAPS, lowercase, or naively title-cased text."""

import re

# Articles and prepositions lowercased inside a name (never as its first word). The list
# follows the JOSM validator rules and TIGER-ROAR, minus "a", which is usually an initial.
LOWER_WORDS = {
    "del", "de", "di", "du", "la", "las", "los", "el",
    "of", "on", "for", "an", "the", "at", "to", "in", "via", "by", "or", "and", "but",
}
ROMAN_NUMERALS = {"II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII", "XIII"}
# Vowel-less words that are abbreviations to title-case, not initialisms to keep in caps.
TITLE_ABBREVIATIONS = {"JR", "SR", "ST", "MT", "FT", "DR", "MR", "MRS", "MS"}

_ORDINAL = re.compile(r"^(\d+)(ST|ND|RD|TH)$")
_NAIVE_MC = re.compile(r"^Mc[a-z]{2,}$")


def _case_word(word: str) -> str:
    upper = word.upper()
    if m := _ORDINAL.match(upper):
        return f"{int(m.group(1))}{m.group(2).lower()}"
    if any(c.isdigit() for c in upper) or len(upper) == 1 or upper in ROMAN_NUMERALS:
        return upper
    if upper.startswith("MC") and len(upper) > 3 and upper.isalpha():
        return "Mc" + upper[2:].capitalize()
    if upper not in TITLE_ABBREVIATIONS and not re.search(r"[AEIOUY]", upper):
        return upper  # initialism such as MLK or JFK
    return upper.capitalize()


ENGLISH_LOWER_WORDS = {"of", "on", "the", "at", "in", "and"}


def smart_title_token(token: str, first: bool = True, keep_upper: frozenset = frozenset(),
                      lower_words=LOWER_WORDS) -> str:
    """Case one space-separated token. Mixed-case tokens are trusted as delivered."""
    if not first and token.lower() in lower_words:
        return token.lower()
    if _ORDINAL.match(token.upper()):
        return _case_word(token)  # also repairs naive title-casing such as 13Th
    if not token.isupper() and not token.islower():
        # Mixed case: only repair naive title-casing of Mc names (Mcdowell -> McDowell).
        return "Mc" + token[2:].capitalize() if _NAIVE_MC.match(token) else token
    if token.upper() in keep_upper:
        return token.upper()
    pieces = re.split(r"([-'/&.])", token)
    out = []
    for i, piece in enumerate(pieces):
        if i % 2 == 1 or not piece:
            out.append(piece)
        elif i >= 2 and pieces[i - 1] == "'" and piece.upper() in ("S", "T"):
            out.append(piece.lower())  # Mary's, Don't
        else:
            out.append(_case_word(piece))
    return "".join(out)


def smart_title(text: str, keep_upper: frozenset = frozenset(), lower_words=LOWER_WORDS) -> str:
    return " ".join(
        smart_title_token(token, i == 0, keep_upper, lower_words)
        for i, token in enumerate(text.split())
    )
