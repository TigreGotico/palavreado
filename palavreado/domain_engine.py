"""Domain-aware intent container for hierarchical intent organisation.

Mirrors the design of :class:`nebulento.DomainIntentContainer` and
:class:`ovos_padatious.DomainIntentContainer`: intents are grouped into
*domains*, a top-level :class:`~palavreado.IntentContainer` first picks
the domain, and the domain's sub-container resolves the intent.

This typically reduces both intent-search cost (per-domain containers are
smaller) and false-positive rate on out-of-domain utterances (the
top-level classifier rejects them before they reach any sub-container).
"""

from collections import defaultdict
from typing import Dict, List, Optional, Union

from palavreado import IntentContainer
from palavreado.builder import IntentCreator


class DomainIntentContainer:
    """Two-level intent engine: domain classification followed by intent matching.

    Intents are grouped into *domains*. At query time the engine first
    selects the most likely domain via :attr:`domain_engine`, then runs the
    domain-specific container to find the best intent within that domain.

    Domains can also be selected explicitly, bypassing the top-level
    classifier.

    Example::

        from palavreado import DomainIntentContainer
        from palavreado.builder import IntentCreator

        d = DomainIntentContainer()

        # Register intents inside their domains.
        play = IntentCreator("play")
        play.require("PlayKw", ["play", "put on"])
        d.register_domain_intent("media", play)

        lights = IntentCreator("lights_on")
        lights.require("OnKw", ["turn on", "switch on"])
        lights.require("LightKw", ["lights", "lamp"])
        d.register_domain_intent("home", lights)

        # Teach the domain classifier with representative utterances.
        media_seed = IntentCreator("media")
        media_seed.require("MediaKw", ["play", "song", "music", "next track"])
        d.domain_engine.add_intent(media_seed)

        home_seed = IntentCreator("home")
        home_seed.require("HomeKw", ["lights", "thermostat", "lamp"])
        d.domain_engine.add_intent(home_seed)

        result = d.calc_intent("play some jazz")
        # result["name"] == "play"
    """

    def __init__(self) -> None:
        #: Top-level classifier that maps queries to a domain name.
        self.domain_engine: IntentContainer = IntentContainer()
        #: Per-domain intent containers, keyed by domain name.
        self.domains: Dict[str, IntentContainer] = {}
        #: Raw IntentCreators accumulated per domain (for inspection /
        #: re-registration). Each value is a list of creators registered
        #: under that domain.
        self.training_data: Dict[str, List[Union[IntentCreator, dict]]] = defaultdict(list)

    # ── domain management ──────────────────────────────────────────────────

    def remove_domain(self, domain_name: str) -> None:
        """Remove a domain and all its intents and training data.

        Args:
            domain_name: Domain to remove.
        """
        self.training_data.pop(domain_name, None)
        self.domains.pop(domain_name, None)
        try:
            self.domain_engine.remove_intent(domain_name)
        except Exception:
            pass

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
        self.training_data[domain_name].append(intent)

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

    def calc_domain(self, query: str) -> dict:
        """Run the top-level classifier and return the best matching domain.

        Returns the raw match dict produced by the top-level
        :class:`IntentContainer` — ``name`` is the chosen domain.
        """
        return self.domain_engine.calc_intent(query)

    def calc_intent(self, query: str,
                     domain: Optional[str] = None) -> dict:
        """Return the best intent match for *query*.

        Args:
            query: The utterance to match.
            domain: If given, skip the top-level classifier and resolve the
                intent inside this domain directly.

        Returns:
            The match dict from the resolved domain's container, or a
            ``name=None`` dict if no domain matched.
        """
        resolved_domain: Optional[str] = domain
        if resolved_domain is None:
            top = self.domain_engine.calc_intent(query)
            resolved_domain = top.get("name") if top else None
        if resolved_domain and resolved_domain in self.domains:
            return self.domains[resolved_domain].calc_intent(query)
        return {"name": None, "keywords": {}, "conf": 0.0,
                "utterance": query, "utterance_remainder": query}
