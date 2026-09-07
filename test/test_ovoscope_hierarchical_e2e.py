"""End-to-end tests for HierarchicalPalavreadoPipeline using ovoscope.

Drives a `MiniCroft` instance with the standalone domain entry point
(`ovos-palavreado-hierarchical-pipeline`) and exercises the
``register_vocab`` / ``register_intent`` -> hierarchical routing path
against a :class:`HierarchicalIntentContainer`.

The harness only differs from ``test_ovoscope_e2e`` in pipeline id /
config key. Skill ids appear as the routed domain.
"""
import unittest

import pytest

ovoscope = pytest.importorskip("ovoscope", reason="ovoscope not installed; skipping E2E tests")

from ovoscope import (  # noqa: E402
    E2EPipelineHarness,
    detach_skill,
    register_adapt_intent,
    register_adapt_vocab,
)
from ovos_workshop.intents import IntentBuilder  # noqa: E402

from palavreado.opm import HierarchicalPalavreadoPipeline  # noqa: E402
from palavreado.hierarchical import HierarchicalIntentContainer  # noqa: E402

PIPELINE_ID = "ovos-palavreado-hierarchical-pipeline"
CONFIG_KEY = "palavreado_hierarchical"


class _HierarchicalHarness(E2EPipelineHarness):
    """Project-specific harness binding for HierarchicalPalavreadoPipeline."""

    PIPELINE_ID = PIPELINE_ID
    CONFIG_KEY = CONFIG_KEY
    PLUGIN_CONFIG = {}
    SKILL_ID = "test_skill_palavreado_hierarchical"

    pipeline: HierarchicalPalavreadoPipeline  # type: ignore[assignment]

    def _vocab(self, skill_id, name, words):
        register_adapt_vocab(self.bus, f"{skill_id}:{name}", words, skill_id=skill_id)

    def _intent(self, builder):
        skill_id = builder.name.split(":", 1)[0]
        register_adapt_intent(self.bus, builder, skill_id=skill_id)


class TestDomainRouting(_HierarchicalHarness):
    def test_intent_routed_through_domain(self):
        # skill_a covers lights
        self._vocab(self.SKILL_ID, "TurnOff", ["off", "disable"])
        self._vocab(self.SKILL_ID, "Light", ["light", "lights", "lamp"])
        self._intent(
            IntentBuilder(f"{self.SKILL_ID}:lights_off")
            .require(f"{self.SKILL_ID}:TurnOff")
            .require(f"{self.SKILL_ID}:Light")
        )
        msg = self.send_and_capture(
            "turn off the lights",
            expected_types=[f"{self.SKILL_ID}:lights_off"],
        )
        self.assertIsNotNone(msg, "expected intent match on bus")
        self.assertEqual(msg.msg_type, f"{self.SKILL_ID}:lights_off")

        # Verify the container is actually domain-shaped
        for container in self.pipeline.containers.values():
            self.assertIsInstance(container, HierarchicalIntentContainer)
            self.assertIn(self.SKILL_ID, container.domains)

    def test_two_skills_routed_independently(self):
        self._vocab(self.SKILL_ID, "TurnOff", ["off"])
        self._vocab(self.SKILL_ID, "Light", ["lights"])
        self._intent(
            IntentBuilder(f"{self.SKILL_ID}:lights_off")
            .require(f"{self.SKILL_ID}:TurnOff")
            .require(f"{self.SKILL_ID}:Light")
        )

        other = "skill_b_palavreado_hierarchical"
        self._vocab(other, "Play", ["play"])
        self._vocab(other, "Music", ["music"])
        self._intent(
            IntentBuilder(f"{other}:play_music")
            .require(f"{other}:Play")
            .require(f"{other}:Music")
        )

        msg_a = self.send_and_capture(
            "turn off the lights",
            expected_types=[f"{self.SKILL_ID}:lights_off"],
        )
        self.assertIsNotNone(msg_a)

        msg_b = self.send_and_capture(
            "play music", expected_types=[f"{other}:play_music"]
        )
        self.assertIsNotNone(msg_b)

        # Containers know about both domains
        for container in self.pipeline.containers.values():
            self.assertIn(self.SKILL_ID, container.domains)
            self.assertIn(other, container.domains)

        detach_skill(self.bus, other)

    def test_detach_skill_drops_whole_domain(self):
        self._vocab(self.SKILL_ID, "TurnOff", ["off"])
        self._vocab(self.SKILL_ID, "Light", ["lights"])
        self._intent(
            IntentBuilder(f"{self.SKILL_ID}:lights_off")
            .require(f"{self.SKILL_ID}:TurnOff")
            .require(f"{self.SKILL_ID}:Light")
        )
        msg = self.send_and_capture(
            "turn off the lights",
            expected_types=[f"{self.SKILL_ID}:lights_off"],
        )
        self.assertIsNotNone(msg)

        detach_skill(self.bus, self.SKILL_ID)

        for container in self.pipeline.containers.values():
            self.assertNotIn(self.SKILL_ID, container.domains)

        self.expect_no_match("turn off the lights")


if __name__ == "__main__":
    unittest.main()
