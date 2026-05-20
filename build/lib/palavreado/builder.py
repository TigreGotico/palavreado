"""
Builder helpers for constructing palavreado intents programmatically.

:func:`pattern2regex` converts simplematch patterns to regular expressions.
:func:`expand_samples` expands bracket/pipe notation into flat string lists.
:class:`IntentCreator` provides a fluent API for defining intent slots.
"""
import simplematch as sm
from typing import List, Union

from palavreado.bracket_expansion import expand_parentheses


def pattern2regex(pattern: str, case_sensitive: bool = False) -> str:
    """Convert a simplematch *pattern* string to a regular expression string.

    Args:
        pattern: A simplematch pattern, e.g. ``"buy {item}"``.
        case_sensitive: When ``True`` the generated regex will be case-
            sensitive.  Defaults to ``False``.

    Returns:
        The equivalent regular expression string.
    """
    matcher = sm.Matcher(pattern, case_sensitive=case_sensitive)
    return matcher.regex  # -> the generated regex


def expand_samples(samples: Union[str, List[str]]) -> List[str]:
    """Expand bracket/pipe notation in *samples* into a flat list of strings.

    ``"(hello|hi) world"`` becomes ``["hello world", "hi world"]``.

    Args:
        samples: A single pattern string or a list of pattern strings.

    Returns:
        A flat list of all expanded sample strings.
    """
    if isinstance(samples, str):
        samples = [samples]
    expanded = []
    for line in samples:
        expanded += expand_parentheses(line)
    return expanded


class IntentCreator:
    """Fluent builder for palavreado intents.

    Chain :meth:`require`, :meth:`optionally`, :meth:`require_regex`,
    :meth:`optional_regex`, :meth:`require_autoregex`, and
    :meth:`optional_autoregex` calls, then call :meth:`build` (or pass the
    creator directly to :meth:`~palavreado.IntentContainer.add_intent`) to
    produce the intent dict.

    Args:
        name: Unique name for the intent.
    """

    def __init__(self, name: str) -> None:
        """Initialise a new intent builder with the given *name*."""
        self.name = name
        self.required: dict = {}
        self.optional: dict = {}
        self.regexes: dict = {}

    def require(self, keyword_name: str,
                keyword_samples: Union[str, List[str]]) -> "IntentCreator":
        """Add a required keyword slot.

        Args:
            keyword_name: Slot/entity name.
            keyword_samples: One or more sample strings (bracket notation
                supported).

        Returns:
            ``self`` for chaining.
        """
        if keyword_name not in self.required:
            self.required[keyword_name] = []
        keyword_samples = expand_samples(keyword_samples)
        self.required[keyword_name] += keyword_samples
        return self

    def optionally(self, keyword_name: str,
                   keyword_samples: Union[str, List[str]]) -> "IntentCreator":
        """Add an optional keyword slot.

        Args:
            keyword_name: Slot/entity name.
            keyword_samples: One or more sample strings.

        Returns:
            ``self`` for chaining.
        """
        if keyword_name not in self.optional:
            self.optional[keyword_name] = []
        keyword_samples = expand_samples(keyword_samples)
        self.optional[keyword_name] += keyword_samples
        return self

    def require_regex(self, keyword_name: str,
                      keyword_samples: Union[str, List[str]]) -> "IntentCreator":
        """Add a required regex slot (raw regular expression).

        Args:
            keyword_name: Slot/entity name.
            keyword_samples: One or more raw regex strings.

        Returns:
            ``self`` for chaining.
        """
        if keyword_name not in self.required:
            self.required[keyword_name] = []
        if isinstance(keyword_samples, str):
            keyword_samples = [keyword_samples]
        if keyword_name not in self.regexes:
            self.regexes[keyword_name] = []
        self.regexes[keyword_name] += keyword_samples
        return self

    def optional_regex(self, keyword_name: str,
                       keyword_samples: Union[str, List[str]]) -> "IntentCreator":
        """Add an optional regex slot (raw regular expression).

        Args:
            keyword_name: Slot/entity name.
            keyword_samples: One or more raw regex strings.

        Returns:
            ``self`` for chaining.
        """
        if keyword_name not in self.optional:
            self.optional[keyword_name] = []
        if isinstance(keyword_samples, str):
            keyword_samples = [keyword_samples]
        if keyword_name not in self.regexes:
            self.regexes[keyword_name] = []
        self.regexes[keyword_name] += keyword_samples
        return self

    def require_autoregex(self, keyword_name: str,
                          keyword_samples: Union[str, List[str]],
                          case_sensitive: bool = False) -> "IntentCreator":
        """Add a required slot using simplematch autoregex patterns.

        Args:
            keyword_name: Slot/entity name.
            keyword_samples: One or more simplematch pattern strings,
                e.g. ``"buy {item}"``.
            case_sensitive: Whether the generated regex should be
                case-sensitive.

        Returns:
            ``self`` for chaining.
        """
        if keyword_name not in self.required:
            self.required[keyword_name] = []
        keyword_samples = expand_samples(keyword_samples)
        keyword_samples = [pattern2regex(s, case_sensitive)
                           for s in keyword_samples]
        if keyword_name not in self.regexes:
            self.regexes[keyword_name] = []
        self.regexes[keyword_name] += keyword_samples
        return self

    def optional_autoregex(self, keyword_name: str,
                           keyword_samples: Union[str, List[str]],
                           case_sensitive: bool = False) -> "IntentCreator":
        """Add an optional slot using simplematch autoregex patterns.

        Args:
            keyword_name: Slot/entity name.
            keyword_samples: One or more simplematch pattern strings.
            case_sensitive: Whether the generated regex should be
                case-sensitive.

        Returns:
            ``self`` for chaining.
        """
        if keyword_name not in self.optional:
            self.optional[keyword_name] = []
        keyword_samples = expand_samples(keyword_samples)
        keyword_samples = [pattern2regex(s, case_sensitive)
                           for s in keyword_samples]
        if keyword_name not in self.regexes:
            self.regexes[keyword_name] = []
        self.regexes[keyword_name] += keyword_samples
        return self

    def build(self) -> dict:
        """Serialise the intent definition to a plain dict.

        Returns:
            A dict with keys ``intent_name``, ``required``, ``optional``,
            and ``regex``.
        """
        return {
            "intent_name": self.name,
            "required": self.required,
            "optional": self.optional,
            "regex": self.regexes
        }
