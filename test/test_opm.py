"""Pipeline plugin tests for PalavreadoPipeline using a mock bus."""
import unittest
from unittest import mock

from ovos_bus_client.message import Message
from ovos_workshop.intents import IntentBuilder

from palavreado.opm import PalavreadoPipeline


def _vocab_msg(entity_type, entity_value, lang="en-US"):
    return Message("register_vocab", {
        "entity_type": entity_type,
        "entity_value": entity_value,
        "lang": lang,
    })


def _intent_msg(builder, lang="en-US"):
    data = builder.__dict__.copy()
    data["lang"] = lang
    return Message("register_intent", data)


def _get_last_reply(bus):
    return bus.emit.call_args[0][0]


class TestPalavreadoPipeline(unittest.TestCase):
    def setUp(self):
        self.bus = mock.Mock()
        self.pipeline = PalavreadoPipeline(bus=self.bus, config={
            "conf_high": 0.65, "conf_med": 0.45, "conf_low": 0.25
        })
        # Register a simple intent
        self.pipeline.handle_register_vocab(_vocab_msg("HelloKeyword", "hello"))
        self.pipeline.handle_register_vocab(_vocab_msg("HelloKeyword", "hi"))
        builder = IntentBuilder("test_skill:HelloIntent").require("HelloKeyword")
        self.pipeline.handle_register_intent(_intent_msg(builder))

    def test_match_high_fires_on_confident_utterance(self):
        msg = Message("recognizer_loop:utterance", {"utterances": ["hello"], "lang": "en-US"})
        result = self.pipeline.match_high(["hello"], "en-US", msg)
        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, "test_skill:HelloIntent")

    def test_match_high_none_on_no_match(self):
        msg = Message("recognizer_loop:utterance", {"utterances": ["goodbye"], "lang": "en-US"})
        result = self.pipeline.match_high(["goodbye"], "en-US", msg)
        self.assertIsNone(result)

    def test_match_medium_fires(self):
        msg = Message("recognizer_loop:utterance", {"utterances": ["hello"], "lang": "en-US"})
        result = self.pipeline.match_medium(["hello"], "en-US", msg)
        self.assertIsNotNone(result)

    def test_match_low_fires(self):
        msg = Message("recognizer_loop:utterance", {"utterances": ["hello"], "lang": "en-US"})
        result = self.pipeline.match_low(["hello"], "en-US", msg)
        self.assertIsNotNone(result)

    def test_detach_intent_removes_match(self):
        self.pipeline.handle_detach_intent(
            Message("detach_intent", {"intent_name": "test_skill:HelloIntent"})
        )
        msg = Message("recognizer_loop:utterance", {"utterances": ["hello"], "lang": "en-US"})
        result = self.pipeline.match_high(["hello"], "en-US", msg)
        self.assertIsNone(result)

    def test_detach_skill_removes_all_intents(self):
        self.pipeline.handle_detach_skill(
            Message("detach_skill", {"skill_id": "test_skill"})
        )
        msg = Message("recognizer_loop:utterance", {"utterances": ["hello"], "lang": "en-US"})
        result = self.pipeline.match_high(["hello"], "en-US", msg)
        self.assertIsNone(result)

    def test_handle_get_palavreado_match(self):
        msg = Message("intent.service.palavreado.get", {"utterance": "hello", "lang": "en-US"})
        self.pipeline.handle_get_palavreado(msg)
        reply = _get_last_reply(self.bus)
        self.assertIsNotNone(reply.data["intent"])
        self.assertEqual(reply.data["intent"]["name"], "test_skill:HelloIntent")

    def test_handle_get_palavreado_no_match(self):
        msg = Message("intent.service.palavreado.get", {"utterance": "goodbye", "lang": "en-US"})
        self.pipeline.handle_get_palavreado(msg)
        reply = _get_last_reply(self.bus)
        self.assertIsNone(reply.data["intent"])

    def test_manifest_contains_registered_intent(self):
        msg = Message("intent.service.palavreado.manifest.get")
        self.pipeline.handle_palavreado_manifest(msg)
        reply = _get_last_reply(self.bus)
        names = [i.get("name") for i in reply.data["intents"]]
        self.assertIn("test_skill:HelloIntent", names)

    def test_vocab_manifest_contains_registered_vocab(self):
        msg = Message("intent.service.palavreado.vocab.manifest.get")
        self.pipeline.handle_vocab_manifest(msg)
        reply = _get_last_reply(self.bus)
        types = [v["entity_type"] for v in reply.data["vocab"]]
        self.assertIn("HelloKeyword", types)

    def test_regex_vocab_registration(self):
        self.pipeline.handle_register_vocab(Message("register_vocab", {
            "entity_type": "TimeSlot",
            "regex": r"at (?P<TimeSlot>\d+:\d+)",
            "lang": "en-US",
        }))
        self.assertIn("TimeSlot", self.pipeline._regexes["en-US"])

    def test_alias_of_maps_to_target_type(self):
        self.pipeline.handle_register_vocab(Message("register_vocab", {
            "entity_type": "GreetAlias",
            "entity_value": "hey",
            "alias_of": "HelloKeyword",
            "lang": "en-US",
        }))
        self.assertIn("hey", self.pipeline._vocab["en-US"]["HelloKeyword"])

    def test_shutdown_removes_bus_handlers(self):
        self.pipeline.shutdown()
        self.bus.remove.assert_called()

    def test_match_result_has_utterance(self):
        msg = Message("recognizer_loop:utterance", {"utterances": ["hello"], "lang": "en-US"})
        result = self.pipeline.match_high(["hello"], "en-US", msg)
        self.assertIsNotNone(result)
        self.assertEqual(result.utterance, "hello")

    def test_multiple_utterance_hypotheses_best_wins(self):
        # "hello" should match; "garbage xyzzy" should not
        msg = Message("recognizer_loop:utterance",
                      {"utterances": ["garbage xyzzy", "hello"], "lang": "en-US"})
        result = self.pipeline.match_high(["garbage xyzzy", "hello"], "en-US", msg)
        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, "test_skill:HelloIntent")

    def test_blacklisted_intent_not_returned(self):
        from ovos_bus_client.session import Session, SessionManager
        sess = Session("test-session")
        sess.blacklisted_intents = ["test_skill:HelloIntent"]
        with mock.patch.object(SessionManager, "get", return_value=sess):
            msg = Message("recognizer_loop:utterance",
                          {"utterances": ["hello"], "lang": "en-US"},
                          context={"session": sess.serialize()})
            result = self.pipeline.match_high(["hello"], "en-US", msg)
        self.assertIsNone(result)

    def test_blacklisted_skill_not_returned(self):
        from ovos_bus_client.session import Session, SessionManager
        sess = Session("test-session-2")
        sess.blacklisted_skills = ["test_skill"]
        with mock.patch.object(SessionManager, "get", return_value=sess):
            msg = Message("recognizer_loop:utterance",
                          {"utterances": ["hello"], "lang": "en-US"},
                          context={"session": sess.serialize()})
            result = self.pipeline.match_high(["hello"], "en-US", msg)
        self.assertIsNone(result)


class TestPalavreadoPipelineOptional(unittest.TestCase):
    """Test optional keyword slots via the pipeline."""

    def setUp(self):
        self.bus = mock.Mock()
        self.pipeline = PalavreadoPipeline(bus=self.bus, config={})
        self.pipeline.handle_register_vocab(_vocab_msg("Action", "play"))
        self.pipeline.handle_register_vocab(_vocab_msg("Action", "start"))
        self.pipeline.handle_register_vocab(_vocab_msg("Room", "kitchen"))
        self.pipeline.handle_register_vocab(_vocab_msg("Room", "bedroom"))
        builder = (IntentBuilder("skill:PlayIntent")
                   .require("Action")
                   .optionally("Room"))
        self.pipeline.handle_register_intent(_intent_msg(builder))

    def test_required_slot_only_fires(self):
        msg = Message("recognizer_loop:utterance", {"utterances": ["play music"], "lang": "en-US"})
        result = self.pipeline.calc_intent(["play music"], "en-US", msg)
        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, "skill:PlayIntent")

    def test_optional_slot_increases_confidence(self):
        msg_without = Message("recognizer_loop:utterance",
                              {"utterances": ["play music"], "lang": "en-US"})
        msg_with = Message("recognizer_loop:utterance",
                           {"utterances": ["play music in the kitchen"], "lang": "en-US"})
        r_without = self.pipeline.calc_intent(["play music"], "en-US", msg_without)
        r_with = self.pipeline.calc_intent(["play music in the kitchen"], "en-US", msg_with)
        self.assertIsNotNone(r_without)
        self.assertIsNotNone(r_with)
        self.assertGreaterEqual(r_with.match_data["conf"], r_without.match_data["conf"])


if __name__ == "__main__":
    unittest.main()
