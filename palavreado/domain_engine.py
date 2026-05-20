"""Domain-aware intent container for hierarchical intent organisation.

Intents are grouped into *domains*, each backed by its own
:class:`~palavreado.IntentContainer`. At match time every sub-container is
evaluated in parallel and the global argmax across all domains wins — no
top-level router is involved. This mirrors the parallel-argmax pattern used
by the adapt pipeline.

Because palavreado is keyword/rule-based and per-domain evaluation is very
cheap, parallel evaluation across hundreds of small containers costs
essentially nothing. A configurable short-circuit threshold (default 1.0,
i.e. exact match) lets a single sharp hit skip the remaining domains.
"""

from typing import Dict, List, Optional, Union

from palavreado import IntentContainer
from palavreado.builder import IntentCreator


class DomainIntentContainer:
    """Flat-routing intent engine grouped by *domain*.

    Intents are organised into per-domain :class:`IntentContainer`\\ s. The
    :meth:`calc_intent` method evaluates every domain's container and
    returns the global argmax. A specific domain can be forced via the
    ``domain`` argument.

    Example::

        from palavreado import DomainIntentContainer
        from palavreado.builder import IntentCreator

        d = DomainIntentContainer()

        play = IntentCreator("play")
        play.require("PlayKw", ["play", "put on"])
        d.register_domain_intent("media", play)

        lights = IntentCreator("lights_on")
        lights.require("OnKw", ["turn on", "switch on"])
        lights.require("LightKw", ["lights", "lamp"])
        d.register_domain_intent("home", lights)

        result = d.calc_intent("play some jazz")
        # result["name"] == "play"
    """

    #: Short-circuit threshold: stop iterating sub-engines as soon as one
    #: returns a confidence >= this value. ``1.0`` means only an exact
    #: match aborts the scan, which is the safe default — set lower if you
    #: trust your confidence scoring and want maximum throughput.
    DEFAULT_SHORTCIRCUIT_CONF: float = 1.0

    def __init__(self, shortcircuit_conf: Optional[float] = None) -> None:
        #: Per-domain intent containers, keyed by domain name.
        self.domains: Dict[str, IntentContainer] = {}
        #: Confidence threshold at which parallel evaluation stops early.
        self.shortcircuit_conf: float = (
            self.DEFAULT_SHORTCIRCUIT_CONF if shortcircuit_conf is None
            else shortcircuit_conf
        )

    # ── domain management ──────────────────────────────────────────────────

    def remove_domain(self, domain_name: str) -> None:
        """Remove a domain and all its intents.

        Args:
            domain_name: Domain to remove.
        """
        self.domains.pop(domain_name, None)

    # ── intent management ──────────────────────────────────────────────────

    def register_domain_intent(self, domain_name: str,
                                intent: Union[IntentCreator, dict]) -> None:
        """Register an intent inside a domain.

        Creates the domain's :class:`IntentContainer` on first use.

        Args:
            domain_name: Target domain (created if it does not exist).
            intent: An :class:`IntentCreator` or its serialised dict form.
        """
        if domain_name not in self.domains:
            self.domains[domain_name] = IntentContainer()
        self.domains[domain_name].add_intent(intent)

    def remove_domain_intent(self, domain_name: str,
                              intent_name: Union[str, IntentCreator, dict]) -> None:
        """Remove an intent from a domain.

        Args:
            domain_name: The domain that owns the intent.
            intent_name: Name of the intent to remove (or the original
                :class:`IntentCreator` / dict used to register it).
        """
        if domain_name in self.domains:
            self.domains[domain_name].remove_intent(intent_name)

    # ── query API ──────────────────────────────────────────────────────────

    def _empty_result(self, query: str) -> dict:
        return {"name": None, "keywords": {}, "conf": 0.0,
                "utterance": query, "utterance_remainder": query}

    def calc_intent(self, query: str,
                     domain: Optional[str] = None) -> dict:
        """Return the best intent match for *query*.

        Args:
            query: The utterance to match.
            domain: If given, route directly to this domain's sub-container
                and skip the parallel scan.

        Returns:
            The best match dict from any domain. When no intent matches,
            returns a ``name=None`` dict.
        """
        if domain is not None:
            if domain in self.domains:
                return self.domains[domain].calc_intent(query)
            return self._empty_result(query)

        best: Optional[dict] = None
        best_conf: float = -1.0
        for sub in self.domains.values():
            result = sub.calc_intent(query)
            if not result or not result.get("name"):
                continue
            conf = result.get("conf", 0.0)
            if conf > best_conf:
                best_conf = conf
                best = result
                # Short-circuit on a sharp match — skips remaining domains.
                if conf >= self.shortcircuit_conf:
                    break

        if best is None:
            return self._empty_result(query)
        return best

    def calc_intents(self, query: str, top_k: int = 5) -> List[dict]:
        """Return the global top-*k* intent matches across all domains.

        Args:
            query: The utterance to match.
            top_k: Maximum number of results to return, sorted by
                descending confidence.

        Returns:
            A list of match dicts (possibly empty), sorted best-first.
        """
        results: List[dict] = []
        for sub in self.domains.values():
            best = sub.calc_intent(query)
            if best and best.get("name"):
                results.append(best)
        results.sort(key=lambda r: r.get("conf", 0.0), reverse=True)
        if top_k and top_k > 0:
            return results[:top_k]
        return results
