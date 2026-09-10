"""
Bracket/parenthesis expansion and text normalisation for palavreado.

Converts patterns like ``"(hello|hi) world"`` into a list of all possible
expansions: ``["hello world", "hi world"]``.  Square brackets denote optional
sections: ``"hey [world]"`` → ``["hey world", "hey"]``.

Also provides :func:`normalize_utterance`, :func:`normalize_example`, and
:func:`lemmatize` so that training data and queries match robustly across
apostrophe and plural variants.
"""
import re
import warnings
from typing import List

from ovos_spec_tools import expand
from ovos_utils.log import deprecated

from palavreado.version import VERSION_MAJOR

_REMOVAL = f"{VERSION_MAJOR + 1}.0.0"


@deprecated(
    "palavreado.bracket_expansion.expand_parentheses is deprecated; "
    "use ovos_spec_tools.expand instead.",
    _REMOVAL,
)
def expand_parentheses(sent: str) -> List[str]:
    """Deprecated shim — delegates to :func:`ovos_spec_tools.expand`.

    Kept for backwards compatibility. New code should import ``expand``
    from ``ovos_spec_tools`` directly.
    """
    warnings.warn(
        "palavreado.bracket_expansion.expand_parentheses is deprecated; "
        "use ovos_spec_tools.expand instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return sorted(expand(sent))


def clean_braces(example: str) -> str:
    """Normalize ``{{entity}}`` double braces to ``{entity}``."""
    clean = example.replace('{{', '{').replace('}}', '}')
    return clean


def translate_padatious(example: str) -> str:
    """Translate Padatious ``:0`` wildcard syntax to ``{word0:word}`` placeholder form."""
    if ':0' not in example:
        return example
    tokens = example.split()
    i = 0
    for idx, token in enumerate(tokens):
        if token == ":0":
            tokens[idx] = '{' + f'word{i}:word' + '}'
            i += 1
    return " ".join(tokens)


def normalize_whitespace(text: str) -> str:
    """Collapse multiple consecutive whitespace characters into a single space and strip."""
    return re.sub(r'\s+', ' ', text).strip()


def drop_apostrophes(text: str) -> str:
    """Replace apostrophes and common apostrophe-like unicode variants with a space.

    Using a space rather than empty string preserves word boundaries so that
    ``"it's"`` → ``"it s"`` and both sides of a match reduce the same way.
    """
    apostrophe_variants = [
        "'",           # U+0027 ASCII apostrophe
        "’",      # U+2019 RIGHT SINGLE QUOTATION MARK
        "‘",      # U+2018 LEFT SINGLE QUOTATION MARK
        "ʼ",      # U+02BC MODIFIER LETTER APOSTROPHE
        "ʹ",      # U+02B9 MODIFIER LETTER PRIME
        "`",           # U+0060 GRAVE ACCENT (backtick)
        "´",      # U+00B4 ACUTE ACCENT
        "＇",      # U+FF07 FULLWIDTH APOSTROPHE
    ]
    for variant in apostrophe_variants:
        text = text.replace(variant, " ")
    return text


def _space_entities(text: str) -> str:
    """
    Ensure a space exists on both sides of every {entity} placeholder.
    Handles agglutinative suffixes like {keyword}ren so the suffix becomes
    a separate token and the capture group is not contaminated.
    """
    return re.sub(r'(\{[^}]+\})', r' \1 ', text)


def normalize_utterance(text: str) -> str:
    """Normalize a plain utterance (inference query) for consistent matching.

    Does NOT touch entity placeholder syntax.
    """
    text = drop_apostrophes(text)
    text = normalize_whitespace(text)
    return text


def normalize_example(example: str) -> str:
    text = clean_braces(translate_padatious(example))
    text = drop_apostrophes(text)
    text = normalize_whitespace(text)
    return text


# ── lightweight lemmatizer ───────────────────────────────────────────────────

_APOS_RE = re.compile(r"[\u0027\u2019\u2018\u02BC\u02B9\u0060\u00B4\uFF07]")


def lemmatize(word: str) -> str:
    """Canonical stem of *word* for matching only — never used in output.

    Language-agnostic: strips apostrophes (replaced with space) and removes a
    trailing ``"s"`` (not ``"ss"``) so plural/singular variants match.
    ``"lights"`` → ``"light"``;  ``"what s"`` tokens → ``"what"`` + ``""``.
    """
    word = _APOS_RE.sub(" ", word).strip().lower()
    if len(word) > 2 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word
