"""OVOS-INTENT-4 *consumer* end-to-end tests for the Palavreado pipeline.

``test/test_ovoscope_e2e.py`` proves palavreado matches intents registered via
the legacy ``register_vocab`` / ``register_intent`` events. This suite proves
palavreado *consumes the INTENT-4 spec registration topics* (``ovos-intent-4.md``)
and then matches.

Palavreado is a **keyword** engine: it consumes ``ovos.intent.register.keyword``
(§5) and not ``ovos.intent.register.template`` (§11). Each test boots a real
``MiniCroft`` pinned to the palavreado pipeline, emits the spec registration on
the wire, sends a matching utterance, and asserts the intent dispatches
``<skill_id>:<intent_name>`` — proving spec-topic consumption.
"""
import time
import unittest

import pytest

ovoscope = pytest.importorskip(
    "ovoscope", reason="ovoscope not installed; skipping E2E tests"
)

from ovoscope import E2EPipelineHarness  # noqa: E402
from ovos_bus_client.message import Message  # noqa: E402
from ovos_spec_tools import SpecMessage  # noqa: E402

from palavreado.opm import PalavreadoPipeline  # noqa: E402

PIPELINE_ID = "palavreado"
CONFIG_KEY = "palavreado"

REGISTER_KEYWORD = str(SpecMessage.INTENT_REGISTER_KEYWORD)
REGISTER_TEMPLATE = str(SpecMessage.INTENT_REGISTER_TEMPLATE)
INTENT_DEREGISTER = str(SpecMessage.INTENT_DEREGISTER)
SKILL_DEREGISTER = str(SpecMessage.SKILL_DEREGISTER)
INTENT_DISABLE = str(SpecMessage.INTENT_DISABLE)
INTENT_ENABLE = str(SpecMessage.INTENT_ENABLE)


class _Intent4PalavreadoHarness(E2EPipelineHarness):
    PIPELINE_ID = PIPELINE_ID
    CONFIG_KEY = CONFIG_KEY
    PLUGIN_CONFIG = {}
    SKILL_ID = "intent4_palavreado.skill"

    pipeline: PalavreadoPipeline  # type: ignore[assignment]

    def _register_keyword(self, intent_name, required, *, optional=None,
                          one_of=None, excluded=None, lang="en-US", settle=0.6):
        def _descs(d):
            return [{"name": n, "samples": s} for n, s in (d or {}).items()]

        payload = {
            "skill_id": self.SKILL_ID,
            "intent_name": intent_name,
            "lang": lang,
            "required": _descs(required),
            "optional": _descs(optional),
            "one_of": [_descs(g) for g in (one_of or [])],
            "excluded": _descs(excluded),
        }
        self.bus.emit(Message(REGISTER_KEYWORD, payload,
                              {"skill_id": self.SKILL_ID}))
        time.sleep(settle)

    def _emit(self, topic, intent_name=None, settle=0.6, **extra):
        data = {"skill_id": self.SKILL_ID, "lang": "en-US"}
        if intent_name is not None:
            data["intent_name"] = intent_name
        data.update(extra)
        self.bus.emit(Message(topic, data, {"skill_id": self.SKILL_ID}))
        time.sleep(settle)


class TestSpecKeywordConsumed(_Intent4PalavreadoHarness):
    """§5: a keyword intent registered on the spec topic becomes matchable."""

    def test_spec_keyword_registration_is_matchable(self):
        self._register_keyword(
            "lights_off",
            required={"TurnOff": ["off", "disable", "shutdown"],
                      "Light": ["light", "lights", "lamp"]},
        )
        msg = self.send_and_capture(
            "turn off the lights",
            expected_types=[f"{self.SKILL_ID}:lights_off"],
        )
        self.assertIsNotNone(msg, "expected intent match from spec registration")
        self.assertEqual(msg.msg_type, f"{self.SKILL_ID}:lights_off")

    def test_spec_excluded_suppresses_match(self):
        """An ``excluded`` keyword blocks the match (§5.4)."""
        self._register_keyword(
            "lights_off",
            required={"TurnOff": ["off"], "Light": ["lights"]},
            excluded={"Question": ["what", "how"]},
        )
        self.expect_no_match("what turns off the lights", timeout=3.0)


class TestLegacyStillConsumed(_Intent4PalavreadoHarness):
    """Back-compat: legacy vocab/intent registration still matches."""

    def test_legacy_keyword_registration_still_matches(self):
        from ovoscope import register_adapt_intent, register_adapt_vocab
        from ovos_workshop.intents import IntentBuilder

        register_adapt_vocab(self.bus, f"{self.SKILL_ID}:TurnOff", ["off"], skill_id=self.SKILL_ID)
        register_adapt_vocab(self.bus, f"{self.SKILL_ID}:Light", ["lights"], skill_id=self.SKILL_ID)
        register_adapt_intent(
            self.bus,
            IntentBuilder(f"{self.SKILL_ID}:lights_off")
            .require(f"{self.SKILL_ID}:TurnOff")
            .require(f"{self.SKILL_ID}:Light"),
            skill_id=self.SKILL_ID,
        )
        time.sleep(0.4)
        msg = self.send_and_capture(
            "turn off the lights",
            expected_types=[f"{self.SKILL_ID}:lights_off"],
        )
        self.assertIsNotNone(msg, "legacy registration must still match")


class TestSpecDeregister(_Intent4PalavreadoHarness):
    """§8.2 / §8.4: spec deregistration removes a spec-registered intent."""

    def test_spec_deregister_removes_intent(self):
        self._register_keyword(
            "lights_off",
            required={"TurnOff": ["off"], "Light": ["lights"]},
        )
        self.assertIsNotNone(
            self.send_and_capture("turn off the lights",
                                  expected_types=[f"{self.SKILL_ID}:lights_off"]),
            "sanity: intent should match before deregister",
        )
        self._emit(INTENT_DEREGISTER, "lights_off")
        self.expect_no_match("turn off the lights", timeout=3.0)

    def test_spec_skill_deregister_removes_intent(self):
        self._register_keyword(
            "lights_off",
            required={"TurnOff": ["off"], "Light": ["lights"]},
        )
        self._emit(SKILL_DEREGISTER)
        self.expect_no_match("turn off the lights", timeout=3.0)


class TestSpecDisableEnable(_Intent4PalavreadoHarness):
    """§8.5: ``ovos.intent.disable`` suppresses, ``ovos.intent.enable`` re-arms.

    Palavreado keeps a global ``_disabled_intents`` set keyed on the
    registration (``match`` filters disabled names out), so disable is
    registration-scoped per §8.5 and observable regardless of session.
    """

    def test_spec_disable_suppresses_intent(self):
        self._register_keyword(
            "lights_off",
            required={"TurnOff": ["off"], "Light": ["lights"]},
        )
        self._emit(INTENT_DISABLE, "lights_off")
        self.expect_no_match("turn off the lights", timeout=3.0)

    def test_spec_enable_rearms_intent(self):
        self._register_keyword(
            "lights_off",
            required={"TurnOff": ["off"], "Light": ["lights"]},
        )
        self._emit(INTENT_DISABLE, "lights_off")
        self._emit(INTENT_ENABLE, "lights_off")
        msg = self.send_and_capture(
            "turn off the lights",
            expected_types=[f"{self.SKILL_ID}:lights_off"],
        )
        self.assertIsNotNone(msg, "intent should match again after enable")


class TestNegativeTemplateTopic(_Intent4PalavreadoHarness):
    """§11: a keyword engine MUST NOT consume the *template* topic."""

    def test_template_topic_does_not_match_on_keyword_engine(self):
        self.bus.emit(Message(REGISTER_TEMPLATE, {
            "skill_id": self.SKILL_ID,
            "intent_name": "play_music",
            "lang": "en-US",
            "samples": ["play {query}", "put on {query}"],
        }, {"skill_id": self.SKILL_ID}))
        time.sleep(0.5)
        self.expect_no_match("play the beatles", timeout=3.0)


if __name__ == "__main__":
    unittest.main()
