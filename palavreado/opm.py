"""OVOS pipeline plugin wrapping palavreado — keyword intent matching (adapt replacement)."""

from typing import Dict, List, Optional, Union

from langcodes import closest_match
from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ovos_bus_client.util import get_message_lang
from ovos_config.config import Configuration
from ovos_plugin_manager.templates.pipeline import ConfidenceMatcherPipeline, IntentHandlerMatch
from ovos_utils import flatten_list
from ovos_utils.fakebus import FakeBus
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG
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
        config = config or core_config.get("palavreado", {})
        super().__init__(bus=bus, config=config)

        self.lang = standardize_lang_tag(core_config.get("lang", "en-US"))
        langs = core_config.get("secondary_langs") or []
        if self.lang not in langs:
            langs.append(self.lang)
        langs = [standardize_lang_tag(lang) for lang in langs]

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

        self.bus.on("register_vocab", self.handle_register_vocab)
        self.bus.on("register_intent", self.handle_register_intent)
        self.bus.on("detach_intent", self.handle_detach_intent)
        self.bus.on("detach_skill", self.handle_detach_skill)

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
        lang = standardize_lang_tag(get_message_lang(message))
        lang = self._resolve_lang(lang)
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
        lang = standardize_lang_tag(get_message_lang(message))
        lang = self._resolve_lang(lang)
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

        self._registered_intents.append(intent.__dict__)

    def handle_detach_intent(self, message: Message) -> None:
        """Remove a single intent by name."""
        intent_name = message.data.get("intent_name")
        if not intent_name:
            return
        self._registered_intents = [i for i in self._registered_intents
                                     if i.get("name") != intent_name]
        for container in self.containers.values():
            container.remove_intent(intent_name)

    def handle_detach_skill(self, message: Message) -> None:
        """Remove all intents and vocab belonging to a skill."""
        skill_id = message.data.get("skill_id", "")
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
        best = None
        best_conf = -1.0

        for utt in utts:
            result = _calc_palavreado_intent(utt, container, sess)
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
        lang = standardize_lang_tag(lang)
        closest, score = closest_match(lang, list(self.containers.keys()))
        return closest if score < 10 else None

    def shutdown(self) -> None:
        self.bus.remove("register_vocab", self.handle_register_vocab)
        self.bus.remove("register_intent", self.handle_register_intent)
        self.bus.remove("detach_intent", self.handle_detach_intent)
        self.bus.remove("detach_skill", self.handle_detach_skill)
        self.bus.remove("intent.service.palavreado.get", self.handle_get_palavreado)
        self.bus.remove("intent.service.palavreado.manifest.get", self.handle_palavreado_manifest)
        self.bus.remove("intent.service.palavreado.vocab.manifest.get", self.handle_vocab_manifest)


def _calc_palavreado_intent(utt: str,
                             container: IntentContainer,
                             sess: Session) -> Optional[dict]:
    """Match *utt* against *container*, honouring session blacklists.

    Returns the raw result dict from :meth:`IntentContainer.calc_intent`,
    or ``None`` if nothing matched or the match is blacklisted.
    """
    try:
        result = container.calc_intent(utt)
        if not result.get("name"):
            return None
        if result["name"] in sess.blacklisted_intents:
            return None
        if result["name"].split(":")[0] in sess.blacklisted_skills:
            return None
        return result
    except Exception as e:
        LOG.error(e)
        return None
