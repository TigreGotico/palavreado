"""
palavreado — dead-simple keyword-based intent parser for OVOS voice assistants.

Provides :class:`IntentContainer` for registering and matching intents built
with :class:`~palavreado.builder.IntentCreator`.
"""
import re
import logging
from functools import lru_cache
from typing import Dict, Iterator, List, Union

from palavreado.builder import IntentCreator
from quebra_frases.chunks import chunk
from quebra_frases import word_tokenize, flatten

LOG = logging.getLogger('palavreado')

# cached so repeated calls within one query evaluation are free
_tokenize = lru_cache(maxsize=512)(word_tokenize)


def _word_count(s: str) -> int:
    return len(s.split()) if s else 0


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
    consumed: set = set()
    for s in samples:
        consumed.update(_tokenize(s))
    words = [t for t in _tokenize(utterance) if t not in consumed]
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
        # compiled regex cache: intent_name -> {pattern_str -> compiled}
        self._compiled: Dict[str, Dict[str, re.Pattern]] = {}

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
        name = intent["intent_name"]
        if name in self.intents:
            raise RuntimeError(
                f"Intent '{name}' is already registered. "
                "Remove it first before re-adding."
            )
        self.intents[name] = intent
        # pre-compile all regexes at registration time
        self._compiled[name] = {
            rx: re.compile(rx, flags=re.IGNORECASE)
            for patterns in intent["regex"].values()
            for rx in patterns
        }

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
        self.intents.pop(name, None)
        self._compiled.pop(name, None)

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
        query_words = set(_tokenize(query))

        def _match(kw_samples: List[str]) -> List[str]:
            # Separate plural candidates from singular ones.
            # Use word-boundary check so "status" is not wrongly dropped
            # when the query contains "statuses".
            singles: List[str] = []
            plurals: List[str] = []
            for w in kw_samples:
                if w.endswith("s"):
                    # only treat as plural candidate if the singular form
                    # appears as a whole word in the query
                    singular = w[:-1]
                    if singular and re.search(
                        r'\b' + re.escape(singular) + r'\b', query, re.IGNORECASE
                    ):
                        continue  # covered by singular path below
                    plurals.append(w)
                else:
                    # drop singular if its plural is already a whole word in query
                    if re.search(
                        r'\b' + re.escape(w + "s") + r'\b', query, re.IGNORECASE
                    ):
                        plurals.append(w + "s")
                    else:
                        singles.append(w)

            results: List[str] = []
            if singles:
                results += [c for c in chunk(query, singles) if c in singles]
            if not results and plurals:
                results += [c for c in chunk(query, plurals) if c in plurals]
            return results

        for intent_name, intent in self.intents.items():
            if not intent["required"]:
                continue
            remainder = query
            conf = 0.0
            n_req = len(intent["required"])
            n_opt = len(intent["optional"])
            partial_conf = 1.0 / n_req
            partial_opt_conf = 0.15 / (n_opt or 1)
            matches: dict = {}
            compiled = self._compiled[intent_name]

            # match regex keywords
            for kw, kw_patterns in intent["regex"].items():
                if not kw_patterns:
                    continue
                # try longest pattern first
                for rx in sorted(kw_patterns, key=len, reverse=True):
                    regex_compiled = compiled[rx]
                    m = regex_compiled.match(query)
                    if m:
                        result = m.groupdict()
                        remainder = get_utterance_remainder(
                            remainder, [kw] + list(result.values())
                        )
                        for k, v in result.items():
                            matches.setdefault(k, []).append(v)
                            if k not in intent["required"] and k not in intent["optional"]:
                                conf += partial_opt_conf * 0.2
                        break
                    kws = re.findall(rx, query)
                    if kws:
                        matches[kw] = kws
                        remainder = get_utterance_remainder(remainder, kws)
                        break

                if kw in intent["required"] and kw in matches:
                    conf += partial_conf * 0.9
                elif kw in intent["optional"] and kw in matches:
                    conf += partial_opt_conf * 0.9

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
                        remainder = get_utterance_remainder(remainder, kws)
                        if remainder in kws:
                            remainder = ""

            # penalise by word-count fraction of remainder, not character length
            if query:
                q_words = _word_count(query)
                r_words = _word_count(remainder)
                ratio = (r_words / q_words) * 0.1
                conf = max(0.0, conf - ratio)
            conf = min(1.0, conf)

            if conf > 0:
                yield {
                    "keywords": matches,
                    "conf": conf,
                    "utterance_remainder": remainder,
                    "utterance": query,
                    "name": intent_name,
                }

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
        best = None
        best_conf = -1.0
        for result in self.calc_intents(query):
            c = result["conf"]
            if c > best_conf or (
                c == best_conf and best is not None and (
                    _word_count(result["utterance_remainder"]) <
                    _word_count(best["utterance_remainder"]) or (
                        _word_count(result["utterance_remainder"]) ==
                        _word_count(best["utterance_remainder"]) and
                        result["name"] < best["name"]
                    )
                )
            ):
                best_conf = c
                best = result
        if best is None:
            return {
                "name": None, "keywords": {}, "conf": 0,
                "utterance": query, "utterance_remainder": query,
            }
        return best
