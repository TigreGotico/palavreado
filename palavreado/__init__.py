"""
palavreado — dead-simple keyword-based intent parser for OVOS voice assistants.

Provides :class:`IntentContainer` for registering and matching intents built
with :class:`~palavreado.builder.IntentCreator`.
"""
import re
import logging
from typing import Dict, Iterator, List, Optional, Union

from palavreado.bracket_expansion import expand_parentheses
from palavreado.builder import IntentCreator
from quebra_frases.chunks import chunk
from quebra_frases import word_tokenize, get_exclusive_tokens, flatten

LOG = logging.getLogger('palavreado')


def get_utterance_remainder(utterance: str,
                            samples: List[str],
                            as_string: bool = True) -> Union[str, List[str]]:
    """Return the portion of *utterance* not covered by any sample token.

    Args:
        utterance: The full utterance string.
        samples: Keyword/entity samples that were matched.
        as_string: When ``True`` (default) return a single space-joined
            string; otherwise return a list of token strings.

    Returns:
        Remainder as a string or list of strings depending on *as_string*.
    """
    chunks = flatten([word_tokenize(s) for s in samples])
    words = [t for t in word_tokenize(utterance) if t not in chunks]
    if as_string:
        return " ".join(words)
    return words


class IntentContainer:
    """Container that holds registered intents and performs keyword matching.

    Intents are registered via :meth:`add_intent` (accepting either an
    :class:`~palavreado.builder.IntentCreator` or the dict produced by
    ``IntentCreator.build()``) and matched against utterances with
    :meth:`calc_intent` / :meth:`calc_intents`.
    """

    def __init__(self) -> None:
        """Initialise an empty container with no registered intents."""
        self.intents: Dict[str, dict] = {}

    # build with IntentCreator
    def add_intent(self, intent: Union[IntentCreator, dict]) -> None:
        """Register a new intent.

        Args:
            intent: An :class:`~palavreado.builder.IntentCreator` instance or
                the raw dict produced by ``IntentCreator.build()``.

        Raises:
            RuntimeError: If an intent with the same name has already been
                registered.  Remove it first with :meth:`remove_intent`.
        """
        if isinstance(intent, IntentCreator):
            intent = intent.build()
        if intent["intent_name"] in self.intents:
            raise RuntimeError(f"Intent '{intent['intent_name']}' is already registered. "
                               "Remove it first before re-adding.")
        self.intents[intent["intent_name"]] = intent

    def remove_intent(self, name: Union[str, IntentCreator, dict]) -> None:
        """Unregister an intent by name, creator object, or built dict.

        Silently does nothing when the intent is not found.

        Args:
            name: The intent name string, an :class:`~palavreado.builder.IntentCreator`,
                or a dict with an ``"intent_name"`` or ``"name"`` key.
        """
        if isinstance(name, IntentCreator):
            name = name.build()
        if isinstance(name, dict):
            name = name.get("intent_name") or name.get("name")
        if name in self.intents:
            del self.intents[name]

    # intent api
    def calc_intents(self, query: str) -> Iterator[dict]:
        """Yield scored match results for every intent that matches *query*.

        Only intents with a confidence > 0 are yielded.  Each result is a
        dict with keys ``name``, ``conf``, ``keywords``, ``utterance``, and
        ``utterance_remainder``.

        Args:
            query: The utterance to match against all registered intents.

        Yields:
            Match result dicts ordered by registration, not by confidence.
            Use :meth:`calc_intent` to obtain the single best match.
        """

        def _match(kw_samples):
            # HACK around chunk function limitations
            plurals = [w for w in kw_samples if
                       w.endswith("s")]
            kw_samples = [w for w in kw_samples
                          if not w.endswith("s") and
                          w + "s" not in query]
            chunked = chunk(query, kw_samples)
            chunked2 = chunk(query, plurals)
            return [c for c in chunked if c in kw_samples] + \
                   [c for c in chunked2 if c in plurals]

        for intent_name, intent in self.intents.items():
            if not len(intent["required"]):
                continue
            remainder = query
            conf = 0.0
            partial_conf = 1.0 / len(intent["required"])
            partial_opt_conf = 0.15 / (len(intent["optional"]) + 0.0001)
            matches = {}

            # match regex keywords
            for kw, kw_samples in intent["regex"].items():
                if not kw_samples:
                    continue
                kw_samples = sorted(kw_samples, key=len, reverse=True)
                for rx in kw_samples:
                    flags = re.IGNORECASE
                    regex_compiled = re.compile(rx, flags=flags)
                    match = regex_compiled.match(query)
                    if match:
                        result = match.groupdict()

                        remainder = get_utterance_remainder(remainder,
                                                            [kw] + list(
                                                                result.values()))

                        for k, v in result.items():
                            if k not in matches:
                                matches[k] = []
                            matches[k].append(v)
                            if k not in intent["required"] and \
                                    k not in intent["optional"]:
                                conf += partial_opt_conf * 0.2
                        break
                    else:
                        kws = re.findall(rx, query)
                        if kws:
                            matches[kw] = kws
                            remainder = get_utterance_remainder(remainder,
                                                                kws)
                            break

                if kw in intent["required"] and kw in matches:
                    conf += (partial_conf * 0.9) / len(matches)
                elif kw in intent["optional"] and kw in matches:
                    conf += (partial_opt_conf * 0.9) / len(matches)

            # match required keywords
            for kw, kw_samples in intent["required"].items():
                if not kw_samples:
                    continue
                if query in kw_samples:
                    matches[kw] = [query]
                    conf += partial_conf
                    remainder = ""
                else:
                    kws = _match(kw_samples)
                    if kws:
                        matches[kw] = kws
                        conf += partial_conf
                        remainder = get_utterance_remainder(remainder, kws)
                        if remainder in kws:
                            remainder = ""

            # match optional keywords
            if intent["optional"]:
                for kw, kw_samples in intent["optional"].items():
                    if not kw_samples:
                        continue
                    if query in kw_samples:
                        matches[kw] = [query]
                        conf += partial_opt_conf
                        remainder = ""
                    else:
                        kws = _match(kw_samples)
                        if kws:
                            matches[kw] = kws
                            conf += partial_opt_conf
                            remainder = get_utterance_remainder(remainder,
                                                                kws)
                            if remainder in kws:
                                remainder = ""

            # weight down based on length of utterance remainder
            if len(query):
                ratio = len(remainder) / len(query)
                ratio = ratio * 0.1

                # normalize score
                conf = max(0.0, conf - ratio)
            conf = min(1.0, conf)

            if conf > 0:
                yield {"keywords": matches,
                       "conf": conf,
                       "utterance_remainder": remainder,
                       "utterance": query,
                       "name": intent_name}

    def calc_intent(self, query: str) -> dict:
        """Return the single best-matching intent result for *query*.

        Args:
            query: The utterance to match.

        Returns:
            The highest-confidence match dict (keys: ``name``, ``conf``,
            ``keywords``, ``utterance``, ``utterance_remainder``).  When no
            intent matches, returns a result dict with ``name=None`` and
            ``conf=0``.
        """
        return max(
            self.calc_intents(query),
            key=lambda x: x["conf"],
            default={'name': None, 'keywords': {}, "conf": 0,
                     "utterance": query, "utterance_remainder": query}
        )
