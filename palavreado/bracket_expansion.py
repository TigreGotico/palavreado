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
from typing import Dict, List

from ovos_utils.bracket_expansion import expand_template, expand_slots


def expand_parentheses(sent: str) -> List[str]:
    """Expand a template string with ``(a|b)`` alternatives and ``[optional]`` syntax
    into all possible combinations.

    Delegates to :func:`ovos_utils.bracket_expansion.expand_template` so that
    OVOS template semantics stay consistent across plugins.  Internal whitespace
    introduced by an empty ``[optional]`` branch is collapsed so a single
    space separates tokens.

    Args:
        sent: A pattern string containing ``(a|b)`` alternations and/or
            ``[optional]`` sections.

    Returns:
        A flat list of all expanded sentence strings, sorted for determinism.

    Examples:
        >>> expand_parentheses("Will it (rain|pour) [today]?")
        ["Will it pour?", "Will it pour today?", "Will it rain?", "Will it rain today?"]
    """
    expansions = expand_template(sent)
    cleaned = {re.sub(r" +", " ", e).strip() for e in expansions}
    return sorted(cleaned)


def expand_template_slots(template: str,
                          slots: Dict[str, List[str]]) -> List[str]:
    """Expand ``(a|b)``/``[opt]`` template and substitute ``{slot}`` placeholders.

    Thin wrapper around :func:`ovos_utils.bracket_expansion.expand_slots`
    that additionally collapses double whitespace from empty optional
    branches.
    """
    expansions = expand_slots(template, slots)
    cleaned = {re.sub(r" +", " ", e).strip() for e in expansions}
    return sorted(cleaned)


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
