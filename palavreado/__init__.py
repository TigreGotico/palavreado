"""
palavreado — dead-simple keyword-based intent parser for OVOS voice assistants.

Provides :class:`IntentContainer` for registering and matching intents built
with :class:`~palavreado.builder.IntentCreator`.
"""
import re
import logging
from functools import lru_cache
from typing import Dict, Iterator, List, Union

from palavreado.bracket_expansion import normalize_utterance, normalize_example, lemmatize  # noqa: F401 (lemmatize exported for callers)
from palavreado.builder import IntentCreator
from quebra_frases.chunks import chunk
from quebra_frases import word_tokenize, flatten

LOG = logging.getLogger('palavreado')

_tokenize = lru_cache(maxsize=512)(word_tokenize)


def _word_count(s: str) -> int:
    return len(s.split()) if s else 0


def get_utterance_remainder(utterance: str,
                            samples: List[str],
                            as_string: bool = True) -> Union[str, List[str]]:
    """Return the portion of *utterance* not covered by any sample token.

    Comparison is done on lemmatized forms so plural/apostrophe variants of
    already-matched keywords are also consumed from the remainder.

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
        consumed.update(lemmatize(t) for t in _tokenize(s))
    words = [t for t in _tokenize(utterance) if lemmatize(t) not in consumed]
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
        self._compiled: Dict[str, Dict[str, re.Pattern]] = {}
        # context gating
        self.available_contexts: Dict[str, Dict[str, object]] = {}
        self.required_contexts: Dict[str, List[str]] = {}
        self.excluded_contexts: Dict[str, List[str]] = {}
        # keyword exclusion
        self.excluded_keywords: Dict[str, List[str]] = {}

    # ── properties ──────────────────────────────────────────────────────────

    @property
    def intent_names(self) -> List[str]:
        """Names of all currently registered intents."""
        return list(self.intents)

    # ── registration ────────────────────────────────────────────────────────

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
        # normalise all training samples at registration time
        normalised = {}
        for slot, samples in intent["required"].items():
            normalised[slot] = [normalize_example(s) for s in samples]
        intent = dict(intent)
        intent["required"] = normalised
        norm_opt = {}
        for slot, samples in intent["optional"].items():
            norm_opt[slot] = [normalize_example(s) for s in samples]
        intent["optional"] = norm_opt

        self.intents[name] = intent
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

    # ── context gating ───────────────────────────────────────────────────────

    def set_context(self, intent_name: str, context_name: str,
                    context_val: object = None) -> None:
        """Mark *context_name* as active for *intent_name*."""
        self.available_contexts.setdefault(intent_name, {})[context_name] = context_val

    def unset_context(self, intent_name: str, context_name: str) -> None:
        """Remove an active context from *intent_name*."""
        if intent_name in self.available_contexts:
            self.available_contexts[intent_name].pop(context_name, None)

    def require_context(self, intent_name: str, context_name: str) -> None:
        """Gate *intent_name* so it only fires when *context_name* is active."""
        self.required_contexts.setdefault(intent_name, []).append(context_name)

    def unrequire_context(self, intent_name: str, context_name: str) -> None:
        """Lift a context requirement from *intent_name*."""
        if intent_name in self.required_contexts:
            self.required_contexts[intent_name] = [
                c for c in self.required_contexts[intent_name] if c != context_name
            ]

    def exclude_context(self, intent_name: str, context_name: str) -> None:
        """Suppress *intent_name* whenever *context_name* is active."""
        self.excluded_contexts.setdefault(intent_name, []).append(context_name)

    def unexclude_context(self, intent_name: str, context_name: str) -> None:
        """Lift a context-based suppression from *intent_name*."""
        if intent_name in self.excluded_contexts:
            self.excluded_contexts[intent_name] = [
                c for c in self.excluded_contexts[intent_name] if c != context_name
            ]

    # ── keyword exclusion ────────────────────────────────────────────────────

    def exclude_keywords(self, intent_name: str, samples: List[str]) -> None:
        """Suppress *intent_name* when any keyword in *samples* appears in the query.

        Single-word keywords use whole-word matching; multi-word keywords use a
        word-boundary regex, so ``"play"`` does not fire on ``"display"``.

        Args:
            intent_name: Intent to suppress.
            samples: Keywords that trigger suppression.
        """
        self.excluded_keywords.setdefault(intent_name, [])
        self.excluded_keywords[intent_name] += samples

    # ── internal filtering ───────────────────────────────────────────────────

    def _filter(self, query: str) -> List[str]:
        """Return intent names that should be excluded for this *query*."""
        excluded: List[str] = []
        query_words = set(query.lower().split())

        for intent_name, keywords in self.excluded_keywords.items():
            def _hit(kw: str, _qw=query_words, _q=query) -> bool:
                if " " not in kw:
                    return kw.lower() in _qw
                return bool(re.search(r"\b" + re.escape(kw.lower()) + r"\b", _q, re.IGNORECASE))
            if any(_hit(kw) for kw in keywords):
                excluded.append(intent_name)

        for intent_name, contexts in self.required_contexts.items():
            active = self.available_contexts.get(intent_name, {})
            if any(c not in active for c in contexts):
                excluded.append(intent_name)

        for intent_name, contexts in self.excluded_contexts.items():
            active = self.available_contexts.get(intent_name, {})
            if any(c in active for c in contexts):
                excluded.append(intent_name)

        return excluded

    # ── matching ────────────────────────────────────────────────────────────

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
        # normalise query the same way training data was normalised
        query = normalize_utterance(query)
        excluded = self._filter(query)

        # lemmatized query tokens for fast lookup
        query_lemmas = {lemmatize(t) for t in _tokenize(query)}

        def _match(kw_samples: List[str]) -> List[str]:
            # Build a mapping: lemmatized sample → original sample string.
            # If the lemma of a sample exists anywhere in the lemmatized query
            # tokens, we try chunk() on the original query with both the
            # original and (if different) the surface form found in the query.
            candidates: List[str] = []
            for w in kw_samples:
                lw = lemmatize(w)
                if lw in query_lemmas:
                    candidates.append(w)
                    continue
                # also try each token of w (multi-word samples)
                if all(lemmatize(t) in query_lemmas for t in _tokenize(w)):
                    candidates.append(w)

            if not candidates:
                return []

            # chunk() finds contiguous substrings; run it on the original query
            # with original-form candidates first, then lemmatized fallback.
            matched = [c for c in chunk(query, candidates) if c in candidates]
            if matched:
                return matched

            # lemmatized fallback: rebuild a lemma-normalised query string and
            # compare against lemmatized candidates, then return original forms.
            lemma_query = " ".join(lemmatize(t) for t in _tokenize(query))
            lemma_map = {lemmatize(w): w for w in candidates}
            lemma_cands = list(lemma_map.keys())
            matched_lemmas = [c for c in chunk(lemma_query, lemma_cands)
                              if c in lemma_map]
            return [lemma_map[lm] for lm in matched_lemmas]

        for intent_name, intent in self.intents.items():
            if intent_name in excluded:
                continue
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

            # penalise by word-count fraction of remainder
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
            norm = normalize_utterance(query)
            return {
                "name": None, "keywords": {}, "conf": 0,
                "utterance": norm, "utterance_remainder": norm,
            }
        return best
