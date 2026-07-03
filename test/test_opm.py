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


class TestPalavreadoIntent4(unittest.TestCase):
    """OVOS-INTENT-4 keyword registration consumed alongside legacy topics."""

    def setUp(self):
        from ovos_spec_tools import SpecMessage
        self.SpecMessage = SpecMessage
        self.bus = mock.Mock()
        self.pipeline = PalavreadoPipeline(bus=self.bus, config={})

    def _register_lights(self):
        # OVOS-INTENT-4 §5.2 keyword payload, all four roles present
        msg = Message(str(self.SpecMessage.INTENT_REGISTER_KEYWORD), {
            "skill_id": "lighting.skill",
            "intent_name": "set_brightness",
            "lang": "en-US",
            "required": [
                {"name": "set", "samples": ["set", "change", "adjust"]},
                {"name": "brightness", "samples": ["brightness", "light level"]},
            ],
            "optional": [],
            "one_of": [
                [
                    {"name": "up", "samples": ["up", "higher", "brighter"]},
                    {"name": "down", "samples": ["down", "lower", "dimmer"]},
                ]
            ],
            "excluded": [
                {"name": "question", "samples": ["what is", "how"]},
            ],
        }, context={"skill_id": "lighting.skill"})
        self.pipeline.handle_register_keyword_intent(msg)

    def test_register_keyword_intent_and_match(self):
        self._register_lights()
        msg = Message("recognizer_loop:utterance",
                      {"utterances": ["set brightness higher"], "lang": "en-US"})
        result = self.pipeline.match_low(["set brightness higher"], "en-US", msg)
        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, "lighting.skill:set_brightness")
        self.assertEqual(result.skill_id, "lighting.skill")

    def test_excluded_suppresses_match(self):
        self._register_lights()
        msg = Message("recognizer_loop:utterance",
                      {"utterances": ["what is the brightness"], "lang": "en-US"})
        result = self.pipeline.match_low(["what is the brightness"], "en-US", msg)
        self.assertIsNone(result)

    def test_missing_role_key_rejected(self):
        msg = Message(str(self.SpecMessage.INTENT_REGISTER_KEYWORD), {
            "skill_id": "skill.x", "intent_name": "bad", "lang": "en-US",
            "required": [{"name": "kw", "samples": ["foo"]}],
            # missing optional / one_of / excluded
        })
        self.pipeline.handle_register_keyword_intent(msg)
        names = [i["name"] for i in self.pipeline._registered_intents]
        self.assertNotIn("skill.x:bad", names)

    def test_required_and_one_of_empty_rejected(self):
        msg = Message(str(self.SpecMessage.INTENT_REGISTER_KEYWORD), {
            "skill_id": "skill.x", "intent_name": "empty", "lang": "en-US",
            "required": [], "optional": [{"name": "o", "samples": ["x"]}],
            "one_of": [], "excluded": [],
        })
        self.pipeline.handle_register_keyword_intent(msg)
        names = [i["name"] for i in self.pipeline._registered_intents]
        self.assertNotIn("skill.x:empty", names)

    def test_empty_samples_rejected(self):
        msg = Message(str(self.SpecMessage.INTENT_REGISTER_KEYWORD), {
            "skill_id": "skill.x", "intent_name": "nosamples", "lang": "en-US",
            "required": [{"name": "kw", "samples": []}],
            "optional": [], "one_of": [], "excluded": [],
        })
        self.pipeline.handle_register_keyword_intent(msg)
        names = [i["name"] for i in self.pipeline._registered_intents]
        self.assertNotIn("skill.x:nosamples", names)

    def test_duplicate_role_rejected(self):
        msg = Message(str(self.SpecMessage.INTENT_REGISTER_KEYWORD), {
            "skill_id": "skill.x", "intent_name": "dup", "lang": "en-US",
            "required": [{"name": "kw", "samples": ["a"]}],
            "optional": [{"name": "kw", "samples": ["b"]}],
            "one_of": [], "excluded": [],
        })
        self.pipeline.handle_register_keyword_intent(msg)
        names = [i["name"] for i in self.pipeline._registered_intents]
        self.assertNotIn("skill.x:dup", names)

    def test_disable_then_enable(self):
        self._register_lights()
        utt = ["set brightness higher"]
        msg = Message("recognizer_loop:utterance", {"utterances": utt, "lang": "en-US"})

        self.pipeline.handle_intent_disable(Message(
            str(self.SpecMessage.INTENT_DISABLE),
            {"skill_id": "lighting.skill", "intent_name": "set_brightness"}))
        self.assertIsNone(self.pipeline.match_low(utt, "en-US", msg))

        self.pipeline.handle_intent_enable(Message(
            str(self.SpecMessage.INTENT_ENABLE),
            {"skill_id": "lighting.skill", "intent_name": "set_brightness"}))
        self.assertIsNotNone(self.pipeline.match_low(utt, "en-US", msg))

    def test_deregister_removes_intent(self):
        self._register_lights()
        self.pipeline.handle_intent_deregister(Message(
            str(self.SpecMessage.INTENT_DEREGISTER),
            {"skill_id": "lighting.skill", "intent_name": "set_brightness"}))
        msg = Message("recognizer_loop:utterance",
                      {"utterances": ["set brightness higher"], "lang": "en-US"})
        self.assertIsNone(self.pipeline.match_low(["set brightness higher"], "en-US", msg))

    def test_skill_deregister_removes_all(self):
        self._register_lights()
        self.pipeline.handle_skill_deregister(Message(
            str(self.SpecMessage.SKILL_DEREGISTER), {"skill_id": "lighting.skill"}))
        msg = Message("recognizer_loop:utterance",
                      {"utterances": ["set brightness higher"], "lang": "en-US"})
        self.assertIsNone(self.pipeline.match_low(["set brightness higher"], "en-US", msg))
        self.assertEqual(self.pipeline._registered_intents, [])

    def test_register_entity_stored(self):
        self.pipeline.handle_register_entity(Message(
            str(self.SpecMessage.ENTITY_REGISTER), {
                "skill_id": "music.skill", "entity_name": "engine", "lang": "en-US",
                "samples": ["spotify", "youtube music"],
            }))
        self.assertIn("spotify", self.pipeline._vocab["en-US"]["engine"])

    def test_register_entity_empty_samples_rejected(self):
        self.pipeline.handle_register_entity(Message(
            str(self.SpecMessage.ENTITY_REGISTER), {
                "skill_id": "music.skill", "entity_name": "engine", "lang": "en-US",
                "samples": [],
            }))
        self.assertNotIn("engine", self.pipeline._vocab["en-US"])

    def test_re_registration_replaces(self):
        self._register_lights()
        # re-register with different required vocab — must replace, not raise
        self._register_lights()
        count = len([i for i in self.pipeline._registered_intents
                     if i["name"] == "lighting.skill:set_brightness"])
        self.assertEqual(count, 1)

    def test_legacy_topics_still_work(self):
        # back-compat: legacy register_vocab + register_intent path unaffected
        from ovos_workshop.intents import IntentBuilder
        self.pipeline.handle_register_vocab(_vocab_msg("Hi", "hello"))
        builder = IntentBuilder("legacy:HiIntent").require("Hi")
        self.pipeline.handle_register_intent(_intent_msg(builder))
        msg = Message("recognizer_loop:utterance", {"utterances": ["hello"], "lang": "en-US"})
        result = self.pipeline.match_high(["hello"], "en-US", msg)
        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, "legacy:HiIntent")


class TestPalavreadoContext1Injection(unittest.TestCase):
    """OVOS-CONTEXT-1 §7 pre-match context injection for the keyword engine.

    A live non-null string entry in ``session.intent_context`` is injected as a
    candidate value for the intent keyword of the same name **before** matching,
    so an intent requiring that keyword matches even when the utterance lacks it.
    An utterance-provided value for the same keyword wins over the injected one;
    a null-valued (flag) or dead entry is never injected -- it only gates.
    """

    SKILL_ID = "bio.skill"
    INTENT = f"{SKILL_ID}:height_query"

    def setUp(self):
        from ovos_spec_tools import SpecMessage
        self.SpecMessage = SpecMessage
        self.bus = mock.Mock()
        self.pipeline = PalavreadoPipeline(bus=self.bus, config={})
        self._register(self.SKILL_ID)

    def _register(self, skill_id):
        # a keyword intent requiring a `tall_query` phrase and a `person`
        # keyword; the utterance "how tall is he" never fills `person`.
        data = {
            "skill_id": skill_id,
            "intent_name": "height_query",
            "lang": "en-US",
            "required": [
                {"name": "tall_query", "samples": ["how tall is"]},
                {"name": "person", "samples": ["bob", "alice"]},
            ],
            "optional": [],
            "one_of": [],
            "excluded": [],
        }
        self.pipeline.handle_register_keyword_intent(
            Message(str(self.SpecMessage.INTENT_REGISTER_KEYWORD), data,
                    context={"skill_id": skill_id}))

    def _match(self, utterance, intent_context=None):
        from ovos_bus_client.session import Session, SessionManager
        sess = Session("ctx-session")
        sess.intent_context = intent_context or {}
        msg = Message("recognizer_loop:utterance",
                      {"utterances": [utterance], "lang": "en-US"})
        with mock.patch.object(SessionManager, "get", return_value=sess):
            return self.pipeline.match_low([utterance], "en-US", msg)

    def test_no_context_no_match(self):
        """Without a live `person` entry the person keyword stays unfilled."""
        self.assertIsNone(self._match("how tall is he"))

    def test_shared_context_injected_as_keyword(self):
        """A live shared {person: Bob} fills the person keyword and slot."""
        ctx = {"person": {"value": "Bob"}}
        result = self._match("how tall is he", intent_context=ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, self.INTENT)
        self.assertEqual(result.match_data["keywords"]["person"], ["Bob"])

    def test_private_owner_context_injected(self):
        """A live private <skill_id>:person entry fills the owner's keyword."""
        ctx = {f"{self.SKILL_ID}:person": {"value": "Bob"}}
        result = self._match("how tall is he", intent_context=ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.match_data["keywords"]["person"], ["Bob"])

    def test_private_other_skill_not_visible(self):
        """A private entry owned by another skill is not injected here."""
        ctx = {"other.skill:person": {"value": "Bob"}}
        self.assertIsNone(self._match("how tall is he", intent_context=ctx))

    def test_utterance_value_wins_over_context(self):
        """A person value in the utterance beats the injected candidate."""
        ctx = {"person": {"value": "Alice"}}
        result = self._match("how tall is bob", intent_context=ctx)
        self.assertIsNotNone(result)
        self.assertEqual(result.match_data["keywords"]["person"], ["bob"])

    def test_flag_entry_not_injected(self):
        """A null-valued (flag) entry gates only -- it is never injected."""
        ctx = {"person": {"value": None}}
        self.assertIsNone(self._match("how tall is he", intent_context=ctx))

    def test_expired_entry_not_injected(self):
        """A dead entry (turns_remaining<=0) is not injected."""
        ctx = {"person": {"value": "Bob", "turns_remaining": 0}}
        self.assertIsNone(self._match("how tall is he", intent_context=ctx))


class TestPalavreadoContext1(unittest.TestCase):
    """OVOS-CONTEXT-1 requires_context / excludes_context gating at match time."""

    def setUp(self):
        from ovos_spec_tools import SpecMessage
        self.SpecMessage = SpecMessage
        self.bus = mock.Mock()
        self.pipeline = PalavreadoPipeline(bus=self.bus, config={})

    def _register(self, requires=None, excludes=None):
        data = {
            "skill_id": "lighting.skill",
            "intent_name": "set_brightness",
            "lang": "en-US",
            "required": [{"name": "set", "samples": ["set brightness"]}],
            "optional": [],
            "one_of": [],
            "excluded": [],
        }
        if requires is not None:
            data["requires_context"] = requires
        if excludes is not None:
            data["excludes_context"] = excludes
        self.pipeline.handle_register_keyword_intent(
            Message(str(self.SpecMessage.INTENT_REGISTER_KEYWORD), data,
                    context={"skill_id": "lighting.skill"}))

    def _match(self, sess):
        from ovos_bus_client.session import SessionManager
        msg = Message("recognizer_loop:utterance",
                      {"utterances": ["set brightness"], "lang": "en-US"})
        with mock.patch.object(SessionManager, "get", return_value=sess):
            return self.pipeline.match_low(["set brightness"], "en-US", msg)

    @staticmethod
    def _live_context(**entries):
        # a live OVOS-CONTEXT-1 entry: no expiry → always live
        from ovos_bus_client.session import Session
        sess = Session("ctx-session")
        sess.intent_context = {k: {"value": v} for k, v in entries.items()}
        return sess

    def test_no_gate_matches(self):
        # a registration without gating declarations is unaffected
        self._register()
        self.assertNotIn("lighting.skill:set_brightness",
                         self.pipeline._context_gates)  # gate NOT stored
        result = self._match(self._live_context())
        self.assertIsNotNone(result)

    def test_requires_context_present_matches(self):
        self._register(requires=["lights_on"])
        # private-scope key stored as "<owner>:<key>"
        result = self._match(self._live_context(**{"lighting.skill:lights_on": True}))
        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, "lighting.skill:set_brightness")

    def test_requires_context_absent_dropped(self):
        self._register(requires=["lights_on"])
        result = self._match(self._live_context())  # no context active
        self.assertIsNone(result)

    def test_requires_context_mapping_scope(self):
        # explicit shared scope stores under the bare key (no owner prefix)
        self._register(requires=[{"key": "away_mode", "scope": "shared"}])
        self.assertIsNone(self._match(self._live_context()))
        self.assertIsNotNone(self._match(self._live_context(away_mode=True)))

    def test_excludes_context_present_dropped(self):
        self._register(excludes=["do_not_disturb"])
        result = self._match(
            self._live_context(**{"lighting.skill:do_not_disturb": True}))
        self.assertIsNone(result)

    def test_excludes_context_absent_matches(self):
        self._register(excludes=["do_not_disturb"])
        result = self._match(self._live_context())
        self.assertIsNotNone(result)

    def test_gate_cleared_on_deregister(self):
        self._register(requires=["lights_on"])
        self.pipeline.handle_intent_deregister(Message(
            str(self.SpecMessage.INTENT_DEREGISTER),
            {"skill_id": "lighting.skill", "intent_name": "set_brightness"}))
        self.assertNotIn("lighting.skill:set_brightness", self.pipeline._context_gates)


if __name__ == "__main__":
    unittest.main()
