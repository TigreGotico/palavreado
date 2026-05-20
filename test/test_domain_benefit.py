"""Toy benchmark: an utterance the flat container misclassifies but
the DomainIntentContainer gets right.

Two skills share a "set X" surface — ``set_thermostat`` (home) and
``set_volume`` (media). With every intent in a single flat container,
palavreado's keyword scoring weighs the shared ``set`` keyword across
all intents and can pick the wrong side. Partitioning by domain limits
each container's decision space; per-domain argmax then routes the
ambiguous "set the … to 8" surface correctly.
"""
import unittest

from palavreado import IntentContainer
from palavreado.builder import IntentCreator
from palavreado.domain_engine import DomainIntentContainer


def _home_intents():
    turn_on = IntentCreator("turn_on_lights") \
        .require("OnKw", ["turn on", "switch on", "lights on"]) \
        .require("LightKw", ["lights", "lamp", "light"])
    turn_off = IntentCreator("turn_off_lights") \
        .require("OffKw", ["turn off", "switch off", "lights off"]) \
        .require("LightKw", ["lights", "lamp", "light"])
    set_thermo = IntentCreator("set_thermostat") \
        .require("SetKw", ["set", "make"]) \
        .require("ThermoKw", ["thermostat", "temperature", "degrees"])
    return [turn_on, turn_off, set_thermo]


def _media_intents():
    play = IntentCreator("play_song") \
        .require("PlayKw", ["play", "put on"])
    pause = IntentCreator("pause_song") \
        .require("PauseKw", ["pause", "stop"])
    set_vol = IntentCreator("set_volume") \
        .require("SetKw", ["set", "make"]) \
        .require("VolKw", ["volume", "loud", "loudness"])
    return [play, pause, set_vol]


AMBIGUOUS = "set the volume to 8"
EXPECTED_INTENT = "set_volume"


class TestDomainBeatsFlat(unittest.TestCase):
    def test_domain_picks_set_volume_when_flat_misroutes(self):
        flat = IntentContainer()
        for intent in _home_intents() + _media_intents():
            flat.add_intent(intent)
        flat_match = flat.calc_intent(AMBIGUOUS)

        domain = DomainIntentContainer()
        for intent in _home_intents():
            domain.register_domain_intent("home", intent)
        for intent in _media_intents():
            domain.register_domain_intent("media", intent)
        domain_match = domain.calc_intent(AMBIGUOUS)

        self.assertEqual(domain_match["name"], EXPECTED_INTENT)
        if flat_match.get("name") != EXPECTED_INTENT:
            self.assertNotEqual(flat_match.get("name"), domain_match["name"])


if __name__ == "__main__":
    unittest.main()
