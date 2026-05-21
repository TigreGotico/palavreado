"""Domain-aware intent container for hierarchical intent matching.

Intents are grouped into *domains*. A top-level classifier
(:attr:`DomainIntentContainer.domain_engine`) maps an utterance to a domain,
then that domain's :class:`~palavreado.IntentContainer` resolves the concrete
intent. Utterances that match no domain are rejected before any sub-container
runs, so unrelated chitchat does not trigger a skill.

The domain classifier is maintained automatically: every keyword sample
registered under a domain is pooled into that domain's classifier entry, so
callers only ever register intents.
"""

from collections import defaultdict
from typing import Dict, List, Optional, Union

from palavreado import IntentContainer
from palavreado.builder import IntentCreator


def _intent_name(intent: Union[str, IntentCreator, dict]) -> Optional[str]:
    """Resolve an intent label from a name, creator, or built dict."""
    if isinstance(intent, IntentCreator):
        return intent.name
    if isinstance(intent, dict):
        return intent.get("intent_name") or intent.get("name")
    return intent


class DomainIntentContainer:
    """Two-stage intent engine: domain classification, then intent matching.

    Intents are organised into per-domain :class:`IntentContainer`\\ s. A
    query is first classified into a domain by :attr:`domain_engine`, then
    resolved against that domain's container only. A query that matches no
    domain is rejected without any sub-container being evaluated.

    Example::

        from palavreado import DomainIntentContainer
        from palavreado.builder import IntentCreator

        d = DomainIntentContainer()

        play = IntentCreator("play").require("PlayKw", ["play", "put on"])
        d.register_domain_intent("media", play)

        lights = IntentCreator("lights_on")
        lights.require("OnKw", ["turn on", "switch on"])
        lights.require("LightKw", ["lights", "lamp"])
        d.register_domain_intent("home", lights)

        d.calc_intent("play some jazz")["name"]      # -> "play"
        d.calc_intent("nice weather today")["name"]  # -> None
    """

    def __init__(self) -> None:
        #: Top-level classifier mapping an utterance to a domain name.
        self.domain_engine: IntentContainer = IntentContainer()
        #: Per-domain intent containers, keyed by domain name.
        self.domains: Dict[str, IntentContainer] = {}
        #: Keyword samples pooled per domain per intent, used to (re)build
        #: the domain classifier when intents are added or removed.
        self._domain_keywords: Dict[str, Dict[str, List[str]]] = defaultdict(dict)

    # ── domain management ──────────────────────────────────────────────────

    def remove_domain(self, domain_name: str) -> None:
        """Remove a domain, all its intents, and its classifier entry.

        Args:
            domain_name: Domain to remove.
        """
        self.domains.pop(domain_name, None)
        self._domain_keywords.pop(domain_name, None)
        if domain_name in self.domain_engine.intent_names:
            self.domain_engine.remove_intent(domain_name)

    # ── intent management ──────────────────────────────────────────────────

    def register_domain_intent(self, domain_name: str,
                               intent: Union[IntentCreator, dict]) -> None:
        """Register an intent inside a domain.

        Creates the domain's :class:`IntentContainer` on first use and folds
        the intent's keyword samples into the domain classifier.

        Args:
            domain_name: Target domain (created if it does not exist).
            intent: An :class:`IntentCreator` or its serialised dict form.
        """
        if isinstance(intent, IntentCreator):
            intent = intent.build()
        if domain_name not in self.domains:
            self.domains[domain_name] = IntentContainer()
        self.domains[domain_name].add_intent(intent)

        samples: List[str] = []
        for slots in (intent["required"], intent["optional"]):
            for slot_samples in slots.values():
                samples += slot_samples
        self._domain_keywords[domain_name][intent["intent_name"]] = samples
        self._rebuild_domain_classifier(domain_name)

    def remove_domain_intent(self, domain_name: str,
                             intent_name: Union[str, IntentCreator, dict]) -> None:
        """Remove an intent from a domain and refresh the classifier.

        Args:
            domain_name: The domain that owns the intent.
            intent_name: Name of the intent to remove (or the original
                :class:`IntentCreator` / dict used to register it).
        """
        if domain_name not in self.domains:
            return
        name = _intent_name(intent_name)
        self.domains[domain_name].remove_intent(name)
        self._domain_keywords.get(domain_name, {}).pop(name, None)
        self._rebuild_domain_classifier(domain_name)

    def _rebuild_domain_classifier(self, domain_name: str) -> None:
        """(Re)register *domain_name* in the top-level classifier.

        The classifier entry for a domain is a single required slot holding
        every keyword sample pooled across the domain's intents, so the
        domain fires whenever the utterance contains any of its keywords.
        """
        if domain_name in self.domain_engine.intent_names:
            self.domain_engine.remove_intent(domain_name)
        pooled = sorted({sample
                         for samples in self._domain_keywords.get(domain_name, {}).values()
                         for sample in samples})
        if not pooled:
            return
        self.domain_engine.add_intent(
            IntentCreator(domain_name).require("keyword", pooled))

    # ── query API ──────────────────────────────────────────────────────────

    def _empty_result(self, query: str) -> dict:
        return {"name": None, "keywords": {}, "conf": 0.0,
                "utterance": query, "utterance_remainder": query}

    def calc_domain(self, query: str) -> dict:
        """Classify *query* into its most likely domain.

        Args:
            query: The utterance to classify.

        Returns:
            The classifier match dict; ``name`` is the domain (or ``None``).
        """
        return self.domain_engine.calc_intent(query)

    def calc_intent(self, query: str, domain: Optional[str] = None) -> dict:
        """Return the best intent match for *query*.

        Args:
            query: The utterance to match.
            domain: If given, skip the classifier and resolve directly
                against this domain's sub-container.

        Returns:
            The best match dict from the resolved domain. When no domain or
            intent matches, returns a ``name=None`` dict.
        """
        resolved = domain or self.domain_engine.calc_intent(query).get("name")
        if resolved in self.domains:
            return self.domains[resolved].calc_intent(query)
        return self._empty_result(query)

    def calc_intents(self, query: str, top_k: int = 5,
                     domain: Optional[str] = None) -> List[dict]:
        """Return the top-*k* intent matches within the resolved domain.

        Args:
            query: The utterance to match.
            top_k: Maximum number of results, sorted by descending confidence.
            domain: If given, skip the classifier and resolve directly
                against this domain's sub-container.

        Returns:
            A list of match dicts (possibly empty), sorted best-first.
        """
        resolved = domain or self.domain_engine.calc_intent(query).get("name")
        if resolved not in self.domains:
            return []
        results = list(self.domains[resolved].calc_intents(query))
        for result in results:
            result.pop("_mw", None)
            result.pop("_rw", None)
        results.sort(key=lambda r: r.get("conf", 0.0), reverse=True)
        if top_k and top_k > 0:
            return results[:top_k]
        return results
