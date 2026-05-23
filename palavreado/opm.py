"""OVOS pipeline plugin wrapping palavreado — keyword intent matching (adapt replacement)."""

import time
from typing import Dict, List, Optional, Union

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ovos_bus_client.util import get_message_lang
from ovos_config.config import Configuration
from ovos_plugin_manager.templates.pipeline import ConfidenceMatcherPipeline, IntentHandlerMatch
from ovos_spec_tools import closest_lang, standardize_lang
from ovos_utils import flatten_list
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG
from ovos_spec_tools import SpecMessage, gate_satisfied, is_live
from ovos_workshop.intents import open_intent_envelope

from palavreado import IntentContainer
from palavreado.builder import IntentCreator


class PalavreadoPipeline(ConfidenceMatcherPipeline):
    """OVOS pipeline plugin for palavreado keyword intent matching.

    Drop-in replacement for the Adapt pipeline.  Skills register vocabulary
    and intents via the standard ``register_vocab`` / ``register_intent`` bus
    messages; no padatious ``.intent`` file loading is involved.
    """

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None) -> None:
        core_config = Configuration()
        config = config or core_config.get("intents", {}).get("palavreado", {}) or core_config.get("palavreado", {})
        super().__init__(bus=bus, config=config)

        self.lang = standardize_lang(core_config.get("lang", "en-US"))
        langs = core_config.get("secondary_langs") or []
        if self.lang not in langs:
            langs.append(self.lang)
        langs = [standardize_lang(lang) for lang in langs]

        self.conf_high = self.config.get("conf_high") or 0.65
        self.conf_med = self.config.get("conf_med") or 0.45
        self.conf_low = self.config.get("conf_low") or 0.25
        self.max_words = self.config.get("max_words") or 50

        # per-lang intent containers
        self.containers: Dict[str, IntentContainer] = {
            lang: IntentContainer() for lang in langs
        }
        # per-lang vocab store: entity_type → [entity_value, ...]
        self._vocab: Dict[str, Dict[str, List[str]]] = {
            lang: {} for lang in langs
        }
        # per-lang per-entity_type regex store
        self._regexes: Dict[str, Dict[str, List[str]]] = {lang: {} for lang in langs}

        self.registered_vocab: List[dict] = []
        self._registered_intents: List[dict] = []  # raw intent dicts for manifest

        # disabled intents (OVOS-INTENT-4 §8.5) — excluded from matching but kept
        self._disabled_intents: set = set()

        # OVOS-CONTEXT-1 gating declarations, keyed by internal intent name →
        # {"requires": [...], "excludes": [...]}.  Enforced at match time via
        # ovos_spec_tools.gate_satisfied (separate/additive to excluded_keywords).
        self._context_gates: Dict[str, dict] = {}

        # OVOS-CONTEXT-1 §7 injection index, keyed by internal intent name →
        # the intent's declared keyword names (required + optional + one_of).
        # A live context entry named for one of these keywords is injected as a
        # candidate keyword value before matching.  Kept in step with the
        # container's intents through the same register/detach paths.
        self._intent_keywords: Dict[str, List[str]] = {}

        # ── legacy registration topics (back-compat) ──────────────────────────
        self.bus.on("register_vocab", self.handle_register_vocab)
        self.bus.on("register_intent", self.handle_register_intent)
        self.bus.on("detach_intent", self.handle_detach_intent)
        self.bus.on("detach_skill", self.handle_detach_skill)

        # ── OVOS-INTENT-4 registration topics ─────────────────────────────────
        # palavreado is keyword/slot based → primary topic is register.keyword.
        self.bus.on(str(SpecMessage.INTENT_REGISTER_KEYWORD), self.handle_register_keyword_intent)
        self.bus.on(str(SpecMessage.ENTITY_REGISTER), self.handle_register_entity)
        self.bus.on(str(SpecMessage.INTENT_DEREGISTER), self.handle_intent_deregister)
        self.bus.on(str(SpecMessage.ENTITY_DEREGISTER), self.handle_entity_deregister)
        self.bus.on(str(SpecMessage.SKILL_DEREGISTER), self.handle_skill_deregister)
        self.bus.on(str(SpecMessage.INTENT_ENABLE), self.handle_intent_enable)
        self.bus.on(str(SpecMessage.INTENT_DISABLE), self.handle_intent_disable)

        self.bus.on("intent.service.palavreado.get", self.handle_get_palavreado)
        self.bus.on("intent.service.palavreado.manifest.get", self.handle_palavreado_manifest)
        self.bus.on("intent.service.palavreado.vocab.manifest.get", self.handle_vocab_manifest)

        LOG.debug("Loaded Palavreado pipeline")

    # ── bus event handlers ────────────────────────────────────────────────────

    def handle_register_vocab(self, message: Message) -> None:
        """Register a keyword sample or regex entity from a skill.

        Mirrors adapt's ``handle_register_vocab``.  Message data fields:
        - ``entity_value``: the natural-language word/phrase
        - ``entity_type``:  slot name the word belongs to
        - ``alias_of``:     (optional) another entity type this aliases
        - ``regex``:        (optional) raw regex string instead of a keyword
        - ``lang``:         BCP-47 language tag
        """
        lang = self._resolve_lang(get_message_lang(message))
        if lang is None:
            return

        self.registered_vocab.append(message.data)

        regex_str = message.data.get("regex")
        if regex_str:
            entity_type = message.data.get("entity_type", "")
            self._regexes[lang].setdefault(entity_type, []).append(regex_str)
            return

        entity_value = message.data.get("entity_value")
        entity_type = message.data.get("entity_type")
        alias_of = message.data.get("alias_of")
        if not entity_value or not entity_type:
            return

        target_type = alias_of or entity_type
        self._vocab[lang].setdefault(target_type, [])
        if entity_value not in self._vocab[lang][target_type]:
            self._vocab[lang][target_type].append(entity_value)

    def handle_register_intent(self, message: Message) -> None:
        """Build and register a palavreado intent from an adapt intent envelope.

        Mirrors adapt's ``handle_register_intent``.  The intent envelope
        (created with ``IntentBuilder``) carries ``requires``, ``optional``,
        and ``at_least_one`` keyword-type lists that are resolved against the
        accumulated vocab store.
        """
        intent = open_intent_envelope(message)
        lang = self._resolve_lang(get_message_lang(message))
        if lang is None:
            return

        creator = IntentCreator(intent.name)

        for kw_type, _ in (intent.requires or []):
            samples = self._vocab[lang].get(kw_type, [])
            creator.require(kw_type, samples)
            regexes = self._regexes[lang].get(kw_type, [])
            if regexes:
                creator.require_regex(kw_type, regexes)

        for kw_type, _ in (intent.optional or []):
            samples = self._vocab[lang].get(kw_type, [])
            creator.optionally(kw_type, samples)
            regexes = self._regexes[lang].get(kw_type, [])
            if regexes:
                creator.optional_regex(kw_type, regexes)

        # at_least_one: treat each group as optional slots (best-effort)
        for group in (intent.at_least_one or []):
            for kw_type in group:
                if kw_type not in creator.required and kw_type not in creator.optional:
                    samples = self._vocab[lang].get(kw_type, [])
                    creator.optionally(kw_type, samples)

        container = self.containers[lang]
        try:
            container.add_intent(creator)
        except RuntimeError:
            # already registered (e.g. skill reload); skip silently
            pass

        # OVOS-CONTEXT-1: legacy envelopes MAY also carry gating declarations
        self._context_gates.pop(intent.name, None)
        gate = self._context_gate(message.data)
        if gate is not None:
            self._context_gates[intent.name] = gate

        # OVOS-CONTEXT-1 §7 — index declared keywords for candidate injection.
        keywords = [kw for kw, _ in (intent.requires or [])]
        keywords += [kw for kw, _ in (intent.optional or [])]
        keywords += [kw for group in (intent.at_least_one or []) for kw in group]
        self._intent_keywords[intent.name] = keywords

        self._registered_intents.append(intent.__dict__)

    # ── OVOS-INTENT-4 handlers ────────────────────────────────────────────────

    @staticmethod
    def _spec_intent_name(skill_id: str, intent_name: str) -> str:
        """Build palavreado's internal intent name from INTENT-4 identity.

        palavreado names intents ``<skill_id>:<intent_name>`` so the
        ``skill_id`` can be recovered with ``name.split(":")[0]`` (the same
        convention the legacy adapt envelope uses).
        """
        if intent_name.startswith(f"{skill_id}:"):
            return intent_name
        return f"{skill_id}:{intent_name}"

    @staticmethod
    def _context_gate(data: dict) -> Optional[dict]:
        """Extract OVOS-CONTEXT-1 ``requires_context``/``excludes_context``.

        Each field is an optional list of bare-string keys or
        ``{"key", "scope"}`` mappings (default private).  The declarations are
        stored verbatim and handed to :func:`gate_satisfied` at match time,
        which owns normalization, scope resolution, liveness and decay — so no
        interpretation happens here.  Returns ``None`` when neither field is
        present (nothing to gate).
        """
        requires = data.get("requires_context")
        excludes = data.get("excludes_context")
        if not requires and not excludes:
            return None
        return {"requires": list(requires or []), "excludes": list(excludes or [])}

    @staticmethod
    def _descriptor_samples(descriptor: dict) -> List[str]:
        """Extract the inline ``samples`` of a §5.1 vocabulary descriptor."""
        if not isinstance(descriptor, dict):
            return []
        samples = descriptor.get("samples") or []
        if isinstance(samples, str):
            samples = [samples]
        return [s for s in samples if isinstance(s, str) and s.strip()]

    def handle_register_keyword_intent(self, message: Message) -> None:
        """Register a keyword intent from an OVOS-INTENT-4 §5 payload.

        Maps the spec's ``required`` / ``optional`` / ``one_of`` / ``excluded``
        vocabulary descriptors (with inline ``samples``) onto palavreado's
        keyword/slot model:

        - ``required`` descriptor  → :meth:`IntentCreator.require`
        - ``optional`` descriptor  → :meth:`IntentCreator.optionally`
        - ``one_of`` group member  → :meth:`IntentCreator.optionally`
          (palavreado has no native "at least one of" slot; each group member
          becomes an optional slot, mirroring the legacy ``at_least_one``
          handling in :meth:`handle_register_intent`)
        - ``excluded`` descriptor  → :meth:`IntentContainer.exclude_keywords`
          (the §5.4 suppression mechanism)

        Malformed payloads (§5.3) are rejected and logged at WARN; they are
        the producer's only debugging signal since the bus is fire-and-forget.
        """
        data = message.data
        skill_id = data.get("skill_id") or message.context.get("skill_id", "")
        intent_name = data.get("intent_name", "")
        lang = standardize_lang_tag(data.get("lang") or get_message_lang(message))
        topic = str(SpecMessage.INTENT_REGISTER_KEYWORD)

        def _reject(reason: str) -> None:
            LOG.warning(f"rejected registration topic={topic} "
                        f"skill_id={skill_id!r} intent_name={intent_name!r} "
                        f"lang={lang!r}: {reason}")

        if not skill_id or not intent_name:
            _reject("missing skill_id or intent_name")
            return

        # §5.3 / §5.2: all four role keys MUST be present
        for key in ("required", "optional", "one_of", "excluded"):
            if key not in data:
                _reject(f"missing required key '{key}'")
                return

        resolved_lang = self._resolve_lang(lang)
        if resolved_lang is None:
            _reject(f"no container for lang {lang!r}")
            return

        required = data.get("required") or []
        optional = data.get("optional") or []
        one_of = data.get("one_of") or []
        excluded = data.get("excluded") or []

        # §5.3: required + one_of MUST NOT both be empty
        if not required and not one_of:
            _reject("required and one_of are both empty")
            return

        # §5.3: every descriptor MUST carry a non-empty samples list that
        # expands to at least one non-empty sample.
        flat_descriptors = list(required) + list(optional) + list(excluded)
        for group in one_of:
            flat_descriptors += list(group or [])
        # §5.3: a vocabulary name MUST NOT appear under more than one role.
        seen_names: Dict[str, str] = {}
        for descriptor in flat_descriptors:
            if not isinstance(descriptor, dict) or not descriptor.get("name"):
                _reject("vocabulary descriptor missing 'name'")
                return
            if not self._descriptor_samples(descriptor):
                _reject(f"vocabulary {descriptor.get('name')!r} has no non-empty samples")
                return
        for role, descriptors in (("required", required), ("optional", optional)):
            for descriptor in descriptors:
                name = descriptor["name"]
                if name in seen_names:
                    _reject(f"vocabulary {name!r} appears under multiple roles")
                    return
                seen_names[name] = role
        for group in one_of:
            for descriptor in (group or []):
                name = descriptor["name"]
                if name in seen_names and seen_names[name] != "one_of":
                    _reject(f"vocabulary {name!r} appears under multiple roles")
                    return
                seen_names[name] = "one_of"

        internal_name = self._spec_intent_name(skill_id, intent_name)

        # §8.1: re-registration replaces the existing intent (per language)
        container = self.containers[resolved_lang]
        container.remove_intent(internal_name)
        self._registered_intents = [i for i in self._registered_intents
                                    if i.get("name") != internal_name]
        self._context_gates.pop(internal_name, None)
        self._intent_keywords.pop(internal_name, None)

        # OVOS-CONTEXT-1: store optional context gating for this intent
        gate = self._context_gate(data)
        if gate is not None:
            self._context_gates[internal_name] = gate

        creator = IntentCreator(internal_name)
        for descriptor in required:
            creator.require(descriptor["name"], self._descriptor_samples(descriptor))
        for descriptor in optional:
            creator.optionally(descriptor["name"], self._descriptor_samples(descriptor))
        for group in one_of:
            for descriptor in (group or []):
                creator.optionally(descriptor["name"], self._descriptor_samples(descriptor))

        container.add_intent(creator)

        # §5.4: excluded role → keyword suppression
        excluded_samples: List[str] = []
        for descriptor in excluded:
            excluded_samples += self._descriptor_samples(descriptor)
        if excluded_samples:
            container.exclude_keywords(internal_name, excluded_samples)

        # OVOS-CONTEXT-1 §7 — index this intent's keyword names (the bare
        # vocabulary names) so a context entry of the same name injects a
        # candidate for the intent's keyword.
        keyword_names = [d["name"] for d in required]
        keyword_names += [d["name"] for d in optional]
        keyword_names += [d["name"] for group in one_of for d in (group or [])]
        self._intent_keywords[internal_name] = keyword_names

        self._registered_intents.append({"name": internal_name,
                                         "skill_id": skill_id,
                                         "lang": resolved_lang,
                                         "method": "keyword"})
        LOG.debug(f"registered keyword intent {internal_name} ({resolved_lang})")

    def handle_register_entity(self, message: Message) -> None:
        """Register an OVOS-INTENT-4 §7 entity value-set hint.

        Stores the entity's inline ``samples`` in the per-lang vocab store
        keyed by ``entity_name`` so keyword intents that reference the slot by
        name can pick them up (a value-set hint, never a precondition; §7).
        Rejects payloads with empty ``samples`` (§7.2).
        """
        data = message.data
        skill_id = data.get("skill_id") or message.context.get("skill_id", "")
        entity_name = data.get("entity_name", "")
        lang = standardize_lang_tag(data.get("lang") or get_message_lang(message))
        topic = str(SpecMessage.ENTITY_REGISTER)

        samples = data.get("samples") or []
        if isinstance(samples, str):
            samples = [samples]
        samples = [s for s in samples if isinstance(s, str) and s.strip()]

        if not entity_name or not samples:
            LOG.warning(f"rejected registration topic={topic} "
                        f"skill_id={skill_id!r} entity_name={entity_name!r} "
                        f"lang={lang!r}: missing entity_name or non-empty samples")
            return

        resolved_lang = self._resolve_lang(lang)
        if resolved_lang is None:
            LOG.warning(f"rejected registration topic={topic} "
                        f"skill_id={skill_id!r} entity_name={entity_name!r} "
                        f"lang={lang!r}: no container for lang")
            return

        # §8.1: replacement keyed on (skill_id, entity_name, lang)
        store = self._vocab[resolved_lang].setdefault(entity_name, [])
        for sample in samples:
            if sample not in store:
                store.append(sample)
        self.registered_vocab.append({"entity_type": entity_name,
                                      "entity_value": samples,
                                      "skill_id": skill_id,
                                      "lang": resolved_lang})

    def handle_intent_deregister(self, message: Message) -> None:
        """Remove one intent (OVOS-INTENT-4 §8.2).

        Targets the ``(skill_id, intent_name)`` identity; when ``lang`` is
        omitted, removes the intent for every registered language.
        """
        data = message.data
        skill_id = data.get("skill_id") or message.context.get("skill_id", "")
        intent_name = data.get("intent_name", "")
        if not skill_id or not intent_name:
            return
        internal_name = self._spec_intent_name(skill_id, intent_name)
        self._disabled_intents.discard(internal_name)
        self._context_gates.pop(internal_name, None)
        self._intent_keywords.pop(internal_name, None)
        self._registered_intents = [i for i in self._registered_intents
                                    if i.get("name") != internal_name]
        for container in self.containers.values():
            container.remove_intent(internal_name)

    def handle_entity_deregister(self, message: Message) -> None:
        """Remove one entity value-set (OVOS-INTENT-4 §8.3)."""
        data = message.data
        skill_id = data.get("skill_id") or message.context.get("skill_id", "")
        entity_name = data.get("entity_name", "")
        if not entity_name:
            return
        for vocab in self._vocab.values():
            vocab.pop(entity_name, None)
        self.registered_vocab = [v for v in self.registered_vocab
                                 if v.get("entity_type") != entity_name]

    def handle_skill_deregister(self, message: Message) -> None:
        """Remove every intent and entity owned by a skill (OVOS-INTENT-4 §8.4)."""
        skill_id = message.data.get("skill_id") or message.context.get("skill_id", "")
        if not skill_id:
            return
        prefix = f"{skill_id}:"
        self._disabled_intents = {n for n in self._disabled_intents
                                  if not n.startswith(prefix)}
        self._context_gates = {n: g for n, g in self._context_gates.items()
                               if not n.startswith(prefix)}
        self._intent_keywords = {n: k for n, k in self._intent_keywords.items()
                                 if not n.startswith(prefix)}
        self._registered_intents = [i for i in self._registered_intents
                                    if i.get("skill_id") != skill_id
                                    and not i.get("name", "").startswith(prefix)]
        self.registered_vocab = [v for v in self.registered_vocab
                                 if v.get("skill_id") != skill_id]
        for container in self.containers.values():
            for intent_name in list(container.intent_names):
                if intent_name.startswith(prefix):
                    container.remove_intent(intent_name)

    def handle_intent_disable(self, message: Message) -> None:
        """Suppress an intent without removing it (OVOS-INTENT-4 §8.5)."""
        data = message.data
        skill_id = data.get("skill_id") or message.context.get("skill_id", "")
        intent_name = data.get("intent_name", "")
        if not skill_id or not intent_name:
            return
        self._disabled_intents.add(self._spec_intent_name(skill_id, intent_name))

    def handle_intent_enable(self, message: Message) -> None:
        """Re-arm a previously disabled intent (OVOS-INTENT-4 §8.5)."""
        data = message.data
        skill_id = data.get("skill_id") or message.context.get("skill_id", "")
        intent_name = data.get("intent_name", "")
        if not skill_id or not intent_name:
            return
        self._disabled_intents.discard(self._spec_intent_name(skill_id, intent_name))

    def handle_detach_intent(self, message: Message) -> None:
        """Remove a single intent by name."""
        intent_name = message.data.get("intent_name")
        if not intent_name:
            return
        self._context_gates.pop(intent_name, None)
        self._intent_keywords.pop(intent_name, None)
        self._registered_intents = [i for i in self._registered_intents
                                     if i.get("name") != intent_name]
        for container in self.containers.values():
            container.remove_intent(intent_name)

    def handle_detach_skill(self, message: Message) -> None:
        """Remove all intents and vocab belonging to a skill."""
        skill_id = message.data.get("skill_id", "")
        self._context_gates = {n: g for n, g in self._context_gates.items()
                               if not n.startswith(skill_id)}
        self._intent_keywords = {n: k for n, k in self._intent_keywords.items()
                                 if not n.startswith(skill_id)}
        self._registered_intents = [i for i in self._registered_intents
                                     if not i.get("name", "").startswith(skill_id)]
        self.registered_vocab = [v for v in self.registered_vocab
                                  if not v.get("entity_type", "").startswith(skill_id)]
        for lang, vocab in self._vocab.items():
            self._vocab[lang] = {k: v for k, v in vocab.items()
                                 if not k.startswith(skill_id)}
        for lang, regexes in self._regexes.items():
            self._regexes[lang] = {k: v for k, v in regexes.items()
                                   if not k.startswith(skill_id)}
        for container in self.containers.values():
            for intent_name in list(container.intent_names):
                if intent_name.startswith(skill_id):
                    container.remove_intent(intent_name)

    def handle_get_palavreado(self, message: Message) -> None:
        """Return the best intent match for a single utterance (debug/introspection)."""
        utterance = message.data["utterance"]
        lang = get_message_lang(message)
        result = self.calc_intent([utterance], lang, message)
        intent_data = result.match_data if result else None
        self.bus.emit(message.reply("intent.service.palavreado.reply",
                                    {"intent": intent_data}))

    def handle_palavreado_manifest(self, message: Message) -> None:
        """Send list of registered intents to caller."""
        self.bus.emit(message.reply("intent.service.palavreado.manifest",
                                    {"intents": self._registered_intents}))

    def handle_vocab_manifest(self, message: Message) -> None:
        """Send registered vocabulary list to caller."""
        self.bus.emit(message.reply("intent.service.palavreado.vocab.manifest",
                                    {"vocab": self.registered_vocab}))

    # ── confidence-level matchers ─────────────────────────────────────────────

    def match_high(self, utterances: List[str], lang: str,
                   message: Message) -> Optional[IntentHandlerMatch]:
        match = self._match_intent(tuple(flatten_list(utterances)), lang,
                                   message.serialize())
        if match and match.match_data.get("conf", 0) >= self.conf_high:
            return match
        return None

    def match_medium(self, utterances: List[str], lang: str,
                     message: Message) -> Optional[IntentHandlerMatch]:
        match = self._match_intent(tuple(flatten_list(utterances)), lang,
                                   message.serialize())
        if match and match.match_data.get("conf", 0) >= self.conf_med:
            return match
        return None

    def match_low(self, utterances: List[str], lang: str,
                  message: Message) -> Optional[IntentHandlerMatch]:
        match = self._match_intent(tuple(flatten_list(utterances)), lang,
                                   message.serialize())
        if match and match.match_data.get("conf", 0) >= self.conf_low:
            return match
        return None

    # ── intent calculation ────────────────────────────────────────────────────

    def _context_gate_ok(self, name: str, sess: Session) -> bool:
        """Return True if *name* passes its OVOS-CONTEXT-1 gating contract.

        Intents with no ``requires_context``/``excludes_context`` declarations
        are always permitted.  Otherwise delegate the whole decision (scope
        resolution, liveness, decay) to :func:`gate_satisfied`, evaluated
        against the session's ``intent_context`` snapshot with the intent's
        ``skill_id`` as the private-scope owner.
        """
        gate = self._context_gates.get(name)
        if not gate:
            return True
        owner_id = name.split(":")[0]
        intent_context = getattr(sess, "intent_context", None) or {}
        return gate_satisfied(intent_context, gate.get("requires"),
                              gate.get("excludes"), owner_id=owner_id)

    @staticmethod
    def _live_context_value(entries: Dict, name: str, skill_id: str,
                            now: float) -> Optional[str]:
        """Resolve a live non-null string context value for a keyword name.

        Scope is read from the key (OVOS-CONTEXT-1 §3): the owner's private
        entry ``<skill_id>:<name>`` is consulted first, then the shared bare
        ``<name>``.  Flag entries (``value`` null / non-string) and dead
        entries are ignored — those only gate, they never inject.
        """
        for key in (f"{skill_id}:{name}", name):
            entry = entries.get(key)
            if not isinstance(entry, dict):
                continue
            value = entry.get("value")
            if not isinstance(value, str) or not value:
                continue
            if not is_live(entry, now):
                continue
            return value
        return None

    def _context_candidates(self, sess: Session) -> Dict[str, Dict[str, str]]:
        """Build OVOS-CONTEXT-1 §7 pre-match candidates from ``intent_context``.

        For every registered intent keyword that has a live non-null string
        entry in ``session.intent_context`` (scope-resolved from the key using
        the intent's ``skill_id``), emit ``{intent_name: {keyword: value}}``.
        The matcher fills an otherwise-unmatched keyword from that value, so an
        intent requiring the keyword matches without the utterance carrying it;
        a value the utterance itself produces for the keyword wins over it.
        """
        entries = getattr(sess, "intent_context", None) or {}
        if not entries or not self._intent_keywords:
            return {}
        now = time.time()
        candidates: Dict[str, Dict[str, str]] = {}
        for name, keywords in self._intent_keywords.items():
            skill_id = name.split(":")[0]
            for kw in keywords:
                value = self._live_context_value(entries, kw, skill_id, now)
                if value is not None:
                    candidates.setdefault(name, {})[kw] = value
        return candidates

    def _match_intent(self, utterances: tuple, lang: Optional[str] = None,
                      message: Optional[str] = None) -> Optional[IntentHandlerMatch]:
        """Match utterances against registered intents, honouring session blacklists.

        Args:
            utterances: Tuple of ASR hypotheses.
            lang: BCP-47 language tag.
            message: Serialised :class:`Message` string (for session lookup).

        Returns:
            Best-matching :class:`IntentHandlerMatch` or ``None``.
        """
        if message:
            message = Message.deserialize(message)
        sess = SessionManager.get(message)

        utts = [u for u in utterances if len(u.split()) < self.max_words]
        if not utts:
            LOG.error(f"All utterances exceed max_words={self.max_words}, skipping")
            return None

        lang = self._resolve_lang(lang or self.lang)
        if lang is None:
            return None

        container = self.containers[lang]
        # OVOS-CONTEXT-1 §7 pre-match candidates, scope-resolved per intent.
        context_candidates = self._context_candidates(sess)
        best = None
        best_conf = -1.0

        for utt in utts:
            result = _calc_palavreado_intent(utt, container, sess,
                                             context_candidates)
            if result and result["name"] in self._disabled_intents:
                continue  # OVOS-INTENT-4 §8.5: disabled intents are not candidates
            if result and not self._context_gate_ok(result["name"], sess):
                continue  # OVOS-CONTEXT-1 §6: gating contract not satisfied
            if result and result["conf"] > best_conf:
                best_conf = result["conf"]
                best = result

        if not best:
            return None

        skill_id = best["name"].split(":")[0]
        return IntentHandlerMatch(
            match_type=best["name"],
            match_data=best,
            skill_id=skill_id,
            utterance=best["utterance"],
        )

    def calc_intent(self, utterances: List[str], lang: str = None,
                    message: Optional[Message] = None) -> Optional[IntentHandlerMatch]:
        """Public helper returning the best match for *utterances*."""
        return self._match_intent(tuple(flatten_list(utterances)),
                                  lang or self.lang,
                                  message.serialize() if message else None)

    def _resolve_lang(self, lang: str) -> Optional[str]:
        if not self.containers:
            return None
        return closest_lang(standardize_lang(lang), list(self.containers.keys()))

    def shutdown(self) -> None:
        self.bus.remove("register_vocab", self.handle_register_vocab)
        self.bus.remove("register_intent", self.handle_register_intent)
        self.bus.remove("detach_intent", self.handle_detach_intent)
        self.bus.remove("detach_skill", self.handle_detach_skill)
        self.bus.remove(str(SpecMessage.INTENT_REGISTER_KEYWORD), self.handle_register_keyword_intent)
        self.bus.remove(str(SpecMessage.ENTITY_REGISTER), self.handle_register_entity)
        self.bus.remove(str(SpecMessage.INTENT_DEREGISTER), self.handle_intent_deregister)
        self.bus.remove(str(SpecMessage.ENTITY_DEREGISTER), self.handle_entity_deregister)
        self.bus.remove(str(SpecMessage.SKILL_DEREGISTER), self.handle_skill_deregister)
        self.bus.remove(str(SpecMessage.INTENT_ENABLE), self.handle_intent_enable)
        self.bus.remove(str(SpecMessage.INTENT_DISABLE), self.handle_intent_disable)
        self.bus.remove("intent.service.palavreado.get", self.handle_get_palavreado)
        self.bus.remove("intent.service.palavreado.manifest.get", self.handle_palavreado_manifest)
        self.bus.remove("intent.service.palavreado.vocab.manifest.get", self.handle_vocab_manifest)


def _calc_palavreado_intent(utt: str,
                             container: IntentContainer,
                             sess: Session,
                             context_candidates: Optional[Dict[str, Dict[str, str]]] = None
                             ) -> Optional[dict]:
    """Match *utt* against *container*, honouring session blacklists.

    *context_candidates* carries the OVOS-CONTEXT-1 §7 pre-match injection map
    (``{intent_name: {keyword: value}}``) forwarded to the matcher.

    Returns the raw result dict from :meth:`IntentContainer.calc_intent`,
    or ``None`` if nothing matched or the match is blacklisted.
    """
    try:
        result = container.calc_intent(utt, context_candidates)
        if not result.get("name"):
            return None
        if result["name"] in (sess.blacklisted_intents or []):
            return None
        if result["name"].split(":")[0] in (sess.blacklisted_skills or []):
            return None
        return result
    except Exception as e:
        LOG.error(e)
        return None
