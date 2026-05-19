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
from quebra_frases import word_tokenize

LOG = logging.getLogger('palavreado')

_tokenize = lru_cache(maxsize=512)(word_tokenize)


def _word_count(s: str) -> int:
    return len(s.split()) if s else 0


def _score(raw_conf: float, remainder: str, q_words: int,
           n_matched_slots: int, n_total_slots: int) -> float:
    """Compute final confidence from raw slot score plus contextual adjustments.

    Adjustments (all in [0, 1] space):
    - **Remainder penalty**: words not consumed by any slot reduce confidence.
      Higher weight (0.2×) than a naive character ratio so precise matches
      clearly outrank accidental single-keyword hits in long utterances.
    - **Coverage bonus**: fraction of query words that *were* matched gives a
      small upward nudge (0.05×), rewarding intents that explain more of the
      query.
    - **Slot bonus**: more matched slots → more evidence → higher score
      (0.05 × matched/total).  This ensures ``lights_off`` (two required slots
      matched) beats a single-slot intent when both would otherwise tie.

    The result is clamped to [0, 1] and rounded to 4 decimal places.
    """
    if not q_words:
        return 0.0
    r_words = _word_count(remainder)
    matched_words = q_words - r_words
    coverage = matched_words / q_words
    remainder_penalty = (r_words / q_words) * 0.2
    slot_bonus = (n_matched_slots / max(n_total_slots, 1)) * 0.05
    conf = raw_conf - remainder_penalty + coverage * 0.05 + slot_bonus
    return round(min(1.0, max(0.0, conf)), 4)


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
        self._sorted_regex: Dict[str, Dict[str, list]] = {}
        # context gating
        self.available_contexts: Dict[str, Dict[str, object]] = {}
        self.required_contexts: Dict[str, List[str]] = {}
        self.excluded_contexts: Dict[str, List[str]] = {}
        # keyword exclusion — raw lists and pre-compiled regexes
        self.excluded_keywords: Dict[str, List[str]] = {}
        # pre-compiled exclusion patterns: {intent: [(kw_lower, compiled|None), ...]}
        self._compiled_exclusions: Dict[str, list] = {}

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
        # pre-sort regex patterns by length (longest first) once at registration
        self._sorted_regex[name] = {
            slot: sorted(patterns, key=len, reverse=True)
            for slot, patterns in intent["regex"].items()
        }

    def remove_intent(self, name: Union[str, IntentCreator, dict]) -> None:
        """Unregister an intent by name, creator object, or built dict.

        Silently does nothing when the intent is not found.

        Args:
            name: The intent name string, an :class:`~palavreado.builder.IntentCreator`,
                or a dict with an ``"intent_name"`` or ``"name"`` key.
        """
        if isinstance(name, IntentCreator):
            name = name.name  # read the name directly — avoids a wasteful .build() call
        elif isinstance(name, dict):
            name = name.get("intent_name") or name.get("name")
        self.intents.pop(name, None)
        self._compiled.pop(name, None)
        self._sorted_regex.pop(name, None)

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
        compiled = self._compiled_exclusions.setdefault(intent_name, [])
        for kw in samples:
            kw_lower = kw.lower()
            rx = re.compile(r"\b" + re.escape(kw_lower) + r"\b", re.IGNORECASE) if " " in kw else None
            compiled.append((kw_lower, rx))

    # ── internal filtering ───────────────────────────────────────────────────

    def _filter(self, query: str) -> List[str]:
        """Return intent names that should be excluded for this *query*."""
        excluded: List[str] = []
        query_words = set(query.lower().split())

        for intent_name, kw_patterns in self._compiled_exclusions.items():
            for kw_lower, rx in kw_patterns:
                hit = rx.search(query) if rx else kw_lower in query_words
                if hit:
                    excluded.append(intent_name)
                    break

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

    def calc_intents(self, query: str,
                     context_candidates: Dict[str, Dict[str, str]] = None
                     ) -> Iterator[dict]:
        """Yield scored match results for every intent that matches *query*.

        Only intents with confidence > 0 are yielded.  Each result is a dict
        with keys ``name``, ``conf``, ``keywords``, ``utterance``, and
        ``utterance_remainder``.

        Args:
            query: The utterance to match against all registered intents.
            context_candidates: OVOS-CONTEXT-1 §7 pre-match injection map,
                ``{intent_name: {keyword_name: value}}``.  A keyword the
                utterance does not fill is filled from its candidate value
                (a live context entry of the same name), letting an intent
                requiring that keyword match without the utterance carrying it.
                An utterance-matched keyword always wins over its candidate.

        Yields:
            Match result dicts ordered by registration, not by confidence.
            Use :meth:`calc_intent` to obtain the single best match.
        """
        query = normalize_utterance(query)
        excluded = self._filter(query)
        q_words = _word_count(query)
        _query_lemma_list = [lemmatize(t) for t in _tokenize(query)]
        query_lemmas = set(_query_lemma_list)
        lemma_query = " ".join(_query_lemma_list)

        def _match(kw_samples: List[str]) -> tuple:
            """Return ``(matched_keywords, quality)`` where quality ∈ (0, 1].

            Quality:
            - 1.0 — contiguous (exact surface or lemma-normalised)
            - 0.8 — non-contiguous token-subset (all tokens present, any order)

            Non-contiguous matches get lower quality so a direct single-word
            hit beats a generic multi-word keyword matched out of sequence.
            """
            single_cands: List[str] = []
            multi_cands: List[str] = []
            _w_lemma: Dict[str, str] = {}  # cache: w → lemmatized form
            for w in kw_samples:
                toks = _tokenize(w)
                lemmas = [lemmatize(t) for t in toks]
                _w_lemma[w] = " ".join(lemmas)
                if len(toks) == 1:
                    if lemmas[0] in query_lemmas:
                        single_cands.append(w)
                elif all(lem in query_lemmas for lem in lemmas):
                    multi_cands.append(w)

            candidates = single_cands + multi_cands
            if not candidates:
                return [], 1.0

            cand_set = set(candidates)
            # Pass 1: contiguous match on original surface form.
            matched = [c for c in chunk(query, candidates) if c in cand_set]
            if matched:
                return sorted(matched, key=lambda x: len(x.split()), reverse=True), 1.0

            # Pass 2: contiguous match on lemma-normalised query (reuse cached lemmas).
            lemma_map = {_w_lemma[w]: w for w in candidates}
            matched_lemmas = [c for c in chunk(lemma_query, list(lemma_map)) if c in lemma_map]
            if matched_lemmas:
                result = sorted([lemma_map[lm] for lm in matched_lemmas],
                                key=lambda x: len(x.split()), reverse=True)
                return result, 1.0

            # Pass 3: non-contiguous — multi-word only.
            if multi_cands:
                return sorted(multi_cands, key=lambda x: len(x.split()), reverse=True), 0.8

            return [], 1.0

        for intent_name, intent in self.intents.items():
            if intent_name in excluded or not intent["required"]:
                continue

            # OVOS-CONTEXT-1 §7 candidate values for this intent's keywords.
            injected = (context_candidates or {}).get(intent_name, {})

            n_req = len(intent["required"])
            n_opt = len(intent["optional"])
            partial_conf = 1.0 / n_req
            partial_opt_conf = 0.15 / (n_opt or 1)
            matches: dict = {}
            remainder = query
            conf = 0.0
            compiled = self._compiled[intent_name]

            # ── regex slots ───────────────────────────────────────────────────
            for kw, kw_patterns in self._sorted_regex[intent_name].items():
                if not kw_patterns:
                    continue
                for rx in kw_patterns:
                    m = compiled[rx].match(query) or compiled[rx].search(query)
                    if m:
                        result = {k: v for k, v in m.groupdict().items() if v is not None}
                        remainder = get_utterance_remainder(remainder, [kw] + list(result.values()))
                        for k, v in result.items():
                            matches.setdefault(k, []).append(v)
                            if k not in intent["required"] and k not in intent["optional"]:
                                conf += partial_opt_conf * 0.2
                        # Always mark the slot itself as matched so the required
                        # check passes and conf credit fires below.
                        matches.setdefault(kw, list(result.values()) or [m.group(0)])
                        break
                    kws = [k for k in re.findall(rx, query) if k and isinstance(k, str)]
                    if kws:
                        matches[kw] = kws
                        remainder = get_utterance_remainder(remainder, kws)
                        break
                if kw in intent["required"] and kw in matches:
                    conf += partial_conf * 0.9
                elif kw in intent["optional"] and kw in matches:
                    conf += partial_opt_conf * 0.9

            # ── keyword slots (required + optional in one pass) ───────────────
            for kw_dict, weight in ((intent["required"], partial_conf),
                                    (intent["optional"], partial_opt_conf)):
                for kw, kw_samples in kw_dict.items():
                    if kw_samples and kw not in matches:
                        if query in kw_samples:
                            matches[kw] = [query]
                            conf += weight
                            remainder = ""
                        else:
                            kws, quality = _match(kw_samples)
                            if kws:
                                matches[kw] = kws
                                conf += weight * quality
                                remainder = get_utterance_remainder(remainder, kws)
                                if remainder in kws:
                                    remainder = ""
                    # OVOS-CONTEXT-1 §7: fill an unmatched keyword from its live
                    # context candidate.  Only when the utterance itself did not
                    # produce it, so an utterance-matched value always wins; the
                    # value is context-supplied and so leaves the remainder as-is.
                    if kw not in matches and kw in injected:
                        matches[kw] = [injected[kw]]
                        conf += weight

            # All required slots must be present in matches.
            if not intent["required"].keys() <= matches.keys():
                continue

            conf = _score(conf, remainder, q_words, len(matches), n_req + n_opt)
            if conf > 0:
                _mw = sum(_word_count(kw) for kws in matches.values() for kw in kws)
                _rw = _word_count(remainder)
                yield {
                    "keywords": matches,
                    "conf": conf,
                    "utterance_remainder": remainder,
                    "utterance": query,
                    "name": intent_name,
                    "_mw": _mw,
                    "_rw": _rw,
                }

    def calc_intent(self, query: str,
                    context_candidates: Dict[str, Dict[str, str]] = None
                    ) -> dict:
        """Return the single best-matching intent result for *query*.

        Args:
            query: The utterance to match.
            context_candidates: OVOS-CONTEXT-1 §7 pre-match injection map
                (see :meth:`calc_intents`).

        Returns:
            The highest-confidence match dict (keys: ``name``, ``conf``,
            ``keywords``, ``utterance``, ``utterance_remainder``).  When no
            intent matches, returns a result dict with ``name=None`` and
            ``conf=0``.
        """
        best = None
        best_conf = -1.0
        best_matched = -1
        for result in self.calc_intents(query, context_candidates):
            c = result["conf"]
            mw = result["_mw"]
            rem = result["_rw"]
            if best is None:
                better = True
            elif c > best_conf:
                better = True
            elif c == best_conf:
                # prefer more query words matched (more specific)
                if mw > best_matched:
                    better = True
                elif mw == best_matched:
                    # prefer shorter remainder (less leftover)
                    better = rem < best["_rw"] or (
                        rem == best["_rw"] and result["name"] < best["name"]
                    )
                else:
                    better = False
            else:
                better = False

            if better:
                best_conf = c
                best_matched = mw
                best = result
        if best is None:
            norm = normalize_utterance(query)
            return {
                "name": None, "keywords": {}, "conf": 0,
                "utterance": norm, "utterance_remainder": norm,
            }
        best.pop("_mw", None)
        best.pop("_rw", None)
        return best


# Re-export DomainIntentContainer at the package root for parity with
# nebulento and ovos-padatious.
from palavreado.domain_engine import DomainIntentContainer  # noqa: E402, F401
