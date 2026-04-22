"""OVOS pipeline plugin wrapping palavreado."""

from functools import lru_cache
from os.path import isfile
from typing import Dict, List, Optional, Union

from langcodes import closest_match
from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ovos_config.config import Configuration
from ovos_plugin_manager.templates.pipeline import ConfidenceMatcherPipeline, IntentHandlerMatch
from ovos_utils import flatten_list
from ovos_utils.fakebus import FakeBus
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG

from palavreado import IntentContainer


class PalavreadoIntent:
    """A matched intent result with dict-like access to extracted keywords.

    Attributes:
        name: Intent identifier (``"skill_id:intent_name"``).
        sent: The original utterance.
        conf: Confidence score in ``[0.0, 1.0]``.
        matches: Extracted keyword/entity values keyed by slot name.
    """

    def __init__(self, name: str, sent: str,
                 matches: Optional[dict] = None, conf: float = 0.0) -> None:
        self.name = name
        self.sent = sent
        self.matches = matches or {}
        self.conf = conf

    def __getitem__(self, item):
        return self.matches[item]

    def __contains__(self, item):
        return item in self.matches

    def get(self, key, default=None):
        return self.matches.get(key, default)

    def __repr__(self) -> str:
        return repr(self.__dict__)


class PalavreadoPipeline(ConfidenceMatcherPipeline):
    """OVOS pipeline plugin for palavreado keyword intent matching."""

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None) -> None:
        super().__init__(config=config or {}, bus=bus)

        core_config = Configuration()
        self.lang = standardize_lang_tag(core_config.get("lang", "en-US"))
        langs = core_config.get("secondary_langs") or []
        if self.lang not in langs:
            langs.append(self.lang)
        langs = [standardize_lang_tag(lang) for lang in langs]

        self.conf_high = self.config.get("conf_high") or 0.95
        self.conf_med = self.config.get("conf_med") or 0.8
        self.conf_low = self.config.get("conf_low") or 0.5
        self.max_words = self.config.get("max_words") or 50

        self.containers: Dict[str, IntentContainer] = {
            lang: IntentContainer() for lang in langs
        }

        self.bus.on("padatious:register_intent", self.register_intent)
        self.bus.on("padatious:register_entity", self.register_entity)
        self.bus.on("detach_intent", self.handle_detach_intent)
        self.bus.on("detach_skill", self.handle_detach_skill)
        self.bus.on("mycroft.skills.train", self.train)

        self.registered_intents: List[str] = []
        self.registered_entities: List[dict] = []
        LOG.debug("Loaded Palavreado pipeline")

    def train(self, message=None) -> None:
        """No offline training required — emit trained signal immediately."""
        self.bus.emit(Message("mycroft.skills.trained"))

    # ── confidence-level matchers ────────────────────────────────────────────

    def _match_level(self, utterances, limit, lang=None,
                     message: Optional[Message] = None) -> Optional[IntentHandlerMatch]:
        LOG.debug(f"Palavreado matching confidence > {limit}")
        utterances = flatten_list(utterances)
        lang = standardize_lang_tag(lang or self.lang)
        intent = self.calc_intent(utterances, lang, message)
        if intent is not None and intent.conf > limit:
            skill_id = intent.name.split(":")[0]
            return IntentHandlerMatch(
                match_type=intent.name,
                match_data=intent.matches,
                skill_id=skill_id,
                utterance=intent.sent,
            )

    def match_high(self, utterances: List[str], lang: str,
                   message: Message) -> Optional[IntentHandlerMatch]:
        return self._match_level(utterances, self.conf_high, lang, message)

    def match_medium(self, utterances: List[str], lang: str,
                     message: Message) -> Optional[IntentHandlerMatch]:
        return self._match_level(utterances, self.conf_med, lang, message)

    def match_low(self, utterances: List[str], lang: str,
                  message: Message) -> Optional[IntentHandlerMatch]:
        return self._match_level(utterances, self.conf_low, lang, message)

    # ── registration ─────────────────────────────────────────────────────────

    def _register_object(self, message: Message, object_name: str,
                         register_func) -> None:
        file_name = message.data.get("file_name")
        samples = message.data.get("samples")
        name = message.data["name"]
        LOG.debug(f"Registering Palavreado {object_name}: {name}")

        if (not file_name or not isfile(file_name)) and not samples:
            LOG.error(f"Could not find file {file_name!r}")
            return

        if not samples and isfile(file_name):
            with open(file_name) as f:
                samples = [line.strip() for line in f if line.strip()]

        register_func(name, samples)

    def register_intent(self, message: Message) -> None:
        """Messagebus handler for ``padatious:register_intent``."""
        lang = standardize_lang_tag(message.data.get("lang", self.lang))
        if lang not in self.containers:
            return
        name = message.data["name"]
        self.registered_intents.append(name)
        try:
            self._register_object(message, "intent",
                                  self.containers[lang].add_intent)
        except RuntimeError:
            # skill reload — intent already registered, skip silently
            if name not in self.containers[lang].intent_names:
                raise

    def register_entity(self, message: Message) -> None:
        """Messagebus handler for ``padatious:register_entity``."""
        lang = standardize_lang_tag(message.data.get("lang", self.lang))
        if lang not in self.containers:
            return
        self.registered_entities.append(message.data)

    # ── detach ───────────────────────────────────────────────────────────────

    def _detach_intent(self, intent_name: str) -> None:
        if intent_name in self.registered_intents:
            self.registered_intents.remove(intent_name)
            for container in self.containers.values():
                container.remove_intent(intent_name)

    def handle_detach_intent(self, message: Message) -> None:
        """Messagebus handler for ``detach_intent``."""
        self._detach_intent(message.data.get("intent_name"))

    def handle_detach_skill(self, message: Message) -> None:
        """Messagebus handler for ``detach_skill``."""
        skill_id = message.data["skill_id"]
        for intent_name in [i for i in self.registered_intents if i.startswith(skill_id)]:
            self._detach_intent(intent_name)

    # ── intent calculation ───────────────────────────────────────────────────

    def calc_intent(self, utterances: List[str], lang: str = None,
                    message: Optional[Message] = None) -> Optional[PalavreadoIntent]:
        """Return the best-matching intent across all *utterances*.

        Args:
            utterances: One or more ASR hypotheses.
            lang: BCP-47 language tag; defaults to the configured primary lang.
            message: OVOS bus message (used to read session blacklists).

        Returns:
            A :class:`PalavreadoIntent` or ``None`` when nothing matches.
        """
        if isinstance(utterances, str):
            utterances = [utterances]
        utterances = [u for u in utterances if len(u.split()) < self.max_words]
        if not utterances:
            LOG.error(f"All utterances exceed max_words={self.max_words}, skipping")
            return None

        lang = self._get_closest_lang(lang or self.lang)
        if lang is None:
            return None

        sess = SessionManager.get(message)
        container = self.containers[lang]

        results = [_calc_palavreado_intent(utt, container, sess) for utt in utterances]
        results = [r for r in results if r is not None]
        return max(results, key=lambda r: r.conf) if results else None

    def _get_closest_lang(self, lang: str) -> Optional[str]:
        if not self.containers:
            return None
        lang = standardize_lang_tag(lang)
        closest, score = closest_match(lang, list(self.containers.keys()))
        return closest if score < 10 else None

    def shutdown(self) -> None:
        self.bus.remove("padatious:register_intent", self.register_intent)
        self.bus.remove("padatious:register_entity", self.register_entity)
        self.bus.remove("detach_intent", self.handle_detach_intent)
        self.bus.remove("detach_skill", self.handle_detach_skill)
        self.bus.remove("mycroft.skills.train", self.train)


@lru_cache(maxsize=128)
def _calc_palavreado_intent(utt: str,
                             container: IntentContainer,
                             sess: Session) -> Optional[PalavreadoIntent]:
    """Match one utterance against *container*, honouring session blacklists."""
    try:
        result = container.calc_intent(utt)
        if not result.get("name"):
            return None
        if result["name"] in sess.blacklisted_intents:
            return None
        if result["name"].split(":")[0] in sess.blacklisted_skills:
            return None
        return PalavreadoIntent(
            name=result["name"],
            sent=utt,
            conf=result["conf"],
            matches=result.get("keywords", {}),
        )
    except Exception as e:
        LOG.error(e)
        return None
