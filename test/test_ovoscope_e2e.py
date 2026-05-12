"""End-to-end tests for PalavreadoPipeline using ovoscope.

We drive a MiniCroft directly and capture the intent-dispatch Message emitted
by IntentService._emit_match_message when our pipeline returns a match — the
same signal ovoscope itself uses.  No model patching is needed; Palavreado is
pure Python.

Palavreado uses the standard Adapt bus API:
  - `register_vocab`  — register keyword samples for a slot type
  - `register_intent` — register an intent envelope (IntentBuilder)
  - `detach_intent`   — remove one intent by name
  - `detach_skill`    — remove all intents and vocab for a skill
"""
import threading
import time
import unittest

import pytest

ovoscope = pytest.importorskip("ovoscope", reason="ovoscope not installed; skipping E2E tests")

from ovos_bus_client.message import Message  # noqa: E402
from ovos_bus_client.session import Session  # noqa: E402
from ovos_config.config import Configuration  # noqa: E402
from ovoscope import get_minicroft  # noqa: E402
from ovos_workshop.intents import IntentBuilder  # noqa: E402

from palavreado.opm import PalavreadoPipeline  # noqa: E402

PIPELINE_ID = "palavreado"
CONFIG_KEY = "palavreado"

# Unique skill id prefix avoids cross-test pollution
_SKILL = "test_skill_palavreado"


class _E2EBase(unittest.TestCase):
    """Shared setup: spin up MiniCroft with the Palavreado pipeline."""

    extra_config: dict | None = None

    @classmethod
    def setUpClass(cls):
        cfg = Configuration()
        intents_cfg = cfg.setdefault("intents", {})
        cls._orig_intents_cfg = intents_cfg.get(CONFIG_KEY)
        plugin_cfg = {}
        if cls.extra_config:
            plugin_cfg.update(cls.extra_config)
        intents_cfg[CONFIG_KEY] = plugin_cfg

        cls.mc = get_minicroft(
            skill_ids=[],
            lang="en-US",
            default_pipeline=[PIPELINE_ID],
            max_wait=60,
        )
        cls.pipeline: PalavreadoPipeline = cls.mc.intents.pipeline_plugins[PIPELINE_ID]

    @classmethod
    def tearDownClass(cls):
        try:
            cls.mc.stop()
        finally:
            cfg = Configuration()
            intents_cfg = cfg.get("intents", {})
            if cls._orig_intents_cfg is None:
                intents_cfg.pop(CONFIG_KEY, None)
            else:
                intents_cfg[CONFIG_KEY] = cls._orig_intents_cfg

    def setUp(self):
        self.mc.bus.emit(Message("detach_skill", {"skill_id": _SKILL}))
        time.sleep(0.1)

    def _register_vocab(self, entity_type: str, words: list, lang: str = "en-US"):
        for word in words:
            self.mc.bus.emit(Message("register_vocab", {
                "entity_value": word,
                "entity_type": f"{_SKILL}:{entity_type}",
                "lang": lang,
            }))
        time.sleep(0.1)

    def _register_intent(self, builder: IntentBuilder, lang: str = "en-US"):
        intent = builder.build()
        msg = Message("register_intent", intent.__dict__)
        msg.context["lang"] = lang
        self.mc.bus.emit(msg)
        time.sleep(0.1)

    def _utterance_msg(self, utterance: str,
                       session_pipeline: list[str] | None = None) -> Message:
        ctx = {}
        if session_pipeline is not None:
            sess = Session(session_id="ovoscope-test", pipeline=session_pipeline)
            ctx["session"] = sess.serialize()
        return Message(
            "recognizer_loop:utterance",
            data={"utterances": [utterance], "lang": "en-US"},
            context=ctx,
        )

    def _send_and_capture(self, utterance: str, expected_types: list[str],
                          timeout: float = 5.0,
                          session_pipeline: list[str] | None = None) -> Message | None:
        got: list[Message] = []
        done = threading.Event()
        failed = threading.Event()

        def _capture_match(msg):
            got.append(msg)
            done.set()

        def _capture_fail(msg):
            failed.set()
            done.set()

        for t in expected_types:
            self.mc.bus.on(t, _capture_match)
        self.mc.bus.on("complete_intent_failure", _capture_fail)
        try:
            self.mc.bus.emit(self._utterance_msg(utterance, session_pipeline))
            done.wait(timeout=timeout)
        finally:
            for t in expected_types:
                self.mc.bus.remove(t, _capture_match)
            self.mc.bus.remove("complete_intent_failure", _capture_fail)
        if failed.is_set() and not got:
            return None
        return got[0] if got else None

    def _expect_no_match(self, utterance: str, timeout: float = 2.0,
                         session_pipeline: list[str] | None = None):
        failed = threading.Event()

        def _on_fail(_msg):
            failed.set()

        self.mc.bus.on("complete_intent_failure", _on_fail)
        try:
            self.mc.bus.emit(self._utterance_msg(utterance, session_pipeline))
            failed.wait(timeout=timeout)
        finally:
            self.mc.bus.remove("complete_intent_failure", _on_fail)
        self.assertTrue(
            failed.is_set(),
            f"Expected no match for {utterance!r} but got no complete_intent_failure.",
        )


class TestRegisteredIntentMatch(_E2EBase):
    def test_all_required_keywords_present_fires_intent(self):
        self._register_vocab("TurnOff", ["off", "disable", "shutdown"])
        self._register_vocab("Light", ["light", "lights", "lamp"])
        self._register_intent(
            IntentBuilder(f"{_SKILL}:lights_off")
            .require(f"{_SKILL}:TurnOff")
            .require(f"{_SKILL}:Light")
        )
        msg = self._send_and_capture(
            "turn off the lights", expected_types=[f"{_SKILL}:lights_off"]
        )
        self.assertIsNotNone(msg, "expected intent match on bus")
        self.assertEqual(msg.msg_type, f"{_SKILL}:lights_off")
        self.assertEqual(msg.data.get("utterance"), "turn off the lights")

    def test_missing_required_keyword_no_match(self):
        self._register_vocab("TurnOff", ["off", "disable"])
        self._register_vocab("Light", ["light", "lights"])
        self._register_intent(
            IntentBuilder(f"{_SKILL}:lights_off")
            .require(f"{_SKILL}:TurnOff")
            .require(f"{_SKILL}:Light")
        )
        self._expect_no_match("turn on the lights")

    def test_no_match_when_no_intents_registered(self):
        self._expect_no_match("turn off the lights")

    def test_utterance_field_preserved(self):
        self._register_vocab("TurnOn", ["on", "enable"])
        self._register_vocab("Light", ["light", "lights"])
        self._register_intent(
            IntentBuilder(f"{_SKILL}:lights_on")
            .require(f"{_SKILL}:TurnOn")
            .require(f"{_SKILL}:Light")
        )
        utterance = "turn on the lights"
        msg = self._send_and_capture(utterance, expected_types=[f"{_SKILL}:lights_on"])
        self.assertIsNotNone(msg)
        self.assertEqual(msg.data.get("utterance"), utterance)

    def test_best_intent_selected_among_multiple(self):
        self._register_vocab("TurnOff", ["off", "disable"])
        self._register_vocab("TurnOn", ["on", "enable"])
        self._register_vocab("Light", ["light", "lights"])
        self._register_intent(
            IntentBuilder(f"{_SKILL}:lights_off")
            .require(f"{_SKILL}:TurnOff")
            .require(f"{_SKILL}:Light")
        )
        self._register_intent(
            IntentBuilder(f"{_SKILL}:lights_on")
            .require(f"{_SKILL}:TurnOn")
            .require(f"{_SKILL}:Light")
        )
        msg = self._send_and_capture(
            "turn on the lights", expected_types=[f"{_SKILL}:lights_on"]
        )
        self.assertIsNotNone(msg)
        self.assertEqual(msg.msg_type, f"{_SKILL}:lights_on")


class TestOptionalSlots(_E2EBase):
    def test_optional_slot_captured_when_present(self):
        self._register_vocab("TurnOff", ["off"])
        self._register_vocab("Light", ["lights"])
        self._register_vocab("Room", ["kitchen", "bedroom", "bathroom"])
        self._register_intent(
            IntentBuilder(f"{_SKILL}:lights_off")
            .require(f"{_SKILL}:TurnOff")
            .require(f"{_SKILL}:Light")
            .optionally(f"{_SKILL}:Room")
        )
        msg = self._send_and_capture(
            "turn off the bedroom lights", expected_types=[f"{_SKILL}:lights_off"]
        )
        self.assertIsNotNone(msg)
        self.assertEqual(msg.msg_type, f"{_SKILL}:lights_off")
        keywords = msg.data.get("keywords", {})
        self.assertIn(f"{_SKILL}:Room", keywords)
        self.assertIn("bedroom", keywords[f"{_SKILL}:Room"])

    def test_optional_slot_absent_still_fires(self):
        self._register_vocab("TurnOff", ["off"])
        self._register_vocab("Light", ["lights"])
        self._register_vocab("Room", ["kitchen", "bedroom"])
        self._register_intent(
            IntentBuilder(f"{_SKILL}:lights_off")
            .require(f"{_SKILL}:TurnOff")
            .require(f"{_SKILL}:Light")
            .optionally(f"{_SKILL}:Room")
        )
        msg = self._send_and_capture(
            "turn off the lights", expected_types=[f"{_SKILL}:lights_off"]
        )
        self.assertIsNotNone(msg)
        self.assertEqual(msg.msg_type, f"{_SKILL}:lights_off")


class TestDetach(_E2EBase):
    def test_detach_intent_prevents_match(self):
        self._register_vocab("TurnOff", ["off"])
        self._register_vocab("Light", ["lights"])
        self._register_intent(
            IntentBuilder(f"{_SKILL}:lights_off")
            .require(f"{_SKILL}:TurnOff")
            .require(f"{_SKILL}:Light")
        )
        msg = self._send_and_capture(
            "turn off the lights", expected_types=[f"{_SKILL}:lights_off"]
        )
        self.assertIsNotNone(msg)

        self.mc.bus.emit(Message("detach_intent", {"intent_name": f"{_SKILL}:lights_off"}))
        time.sleep(0.1)
        self._expect_no_match("turn off the lights")

    def test_detach_skill_removes_all_its_intents(self):
        self._register_vocab("TurnOff", ["off"])
        self._register_vocab("TurnOn", ["on"])
        self._register_vocab("Light", ["lights"])
        self._register_intent(
            IntentBuilder(f"{_SKILL}:lights_off")
            .require(f"{_SKILL}:TurnOff")
            .require(f"{_SKILL}:Light")
        )
        self._register_intent(
            IntentBuilder(f"{_SKILL}:lights_on")
            .require(f"{_SKILL}:TurnOn")
            .require(f"{_SKILL}:Light")
        )
        # Register a second skill that should survive the detach
        self.mc.bus.emit(Message("register_vocab", {
            "entity_value": "play", "entity_type": "skill_b_palavreado:Play", "lang": "en-US"
        }))
        self.mc.bus.emit(Message("register_vocab", {
            "entity_value": "music", "entity_type": "skill_b_palavreado:Music", "lang": "en-US"
        }))
        intent = IntentBuilder("skill_b_palavreado:play_music").require("skill_b_palavreado:Play").require("skill_b_palavreado:Music").build()
        msg = Message("register_intent", intent.__dict__)
        msg.context["lang"] = "en-US"
        self.mc.bus.emit(msg)
        time.sleep(0.1)

        self.mc.bus.emit(Message("detach_skill", {"skill_id": _SKILL}))
        time.sleep(0.1)

        self._expect_no_match("turn off the lights")
        self._expect_no_match("turn on the lights")
        msg = self._send_and_capture("play music", expected_types=["skill_b_palavreado:play_music"])
        self.assertIsNotNone(msg, "skill_b intent should survive skill_a detach")
        self.mc.bus.emit(Message("detach_skill", {"skill_id": "skill_b_palavreado"}))


class TestSessionBlacklist(_E2EBase):
    def test_blacklisted_intent_is_skipped(self):
        self._register_vocab("TurnOff", ["off"])
        self._register_vocab("Light", ["lights"])
        self._register_intent(
            IntentBuilder(f"{_SKILL}:lights_off")
            .require(f"{_SKILL}:TurnOff")
            .require(f"{_SKILL}:Light")
        )
        sess = Session(
            session_id="bl-intent-test",
            blacklisted_intents=[f"{_SKILL}:lights_off"],
        )
        msg = self._utterance_msg("turn off the lights")
        msg.context["session"] = sess.serialize()

        failed = threading.Event()
        self.mc.bus.on("complete_intent_failure", lambda _: failed.set())
        try:
            self.mc.bus.emit(msg)
            failed.wait(timeout=3.0)
        finally:
            self.mc.bus.remove("complete_intent_failure", lambda _: failed.set())
        self.assertTrue(failed.is_set(), "blacklisted intent should yield intent_failure")

    def test_blacklisted_skill_is_skipped(self):
        self._register_vocab("TurnOff", ["off"])
        self._register_vocab("Light", ["lights"])
        self._register_intent(
            IntentBuilder(f"{_SKILL}:lights_off")
            .require(f"{_SKILL}:TurnOff")
            .require(f"{_SKILL}:Light")
        )
        sess = Session(
            session_id="bl-skill-test",
            blacklisted_skills=[_SKILL],
        )
        msg = self._utterance_msg("turn off the lights")
        msg.context["session"] = sess.serialize()

        failed = threading.Event()
        self.mc.bus.on("complete_intent_failure", lambda _: failed.set())
        try:
            self.mc.bus.emit(msg)
            failed.wait(timeout=3.0)
        finally:
            self.mc.bus.remove("complete_intent_failure", lambda _: failed.set())
        self.assertTrue(failed.is_set(), "blacklisted skill should yield intent_failure")


if __name__ == "__main__":
    unittest.main()
