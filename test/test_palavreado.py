"""Comprehensive test suite for palavreado."""
from palavreado import IntentContainer, IntentCreator
from palavreado.bracket_expansion import expand_parentheses
import unittest


class TestIntentContainer(unittest.TestCase):

    def test_intent_registering(self):
        container = IntentContainer()
        intent = IntentCreator("hello_world"). \
            require('hello', ["(hello|hi|hey) world"])
        container.add_intent(intent)
        self.assertEqual(container.intents["hello_world"],
                         {'intent_name': 'hello_world',
                          'required': {'hello': ['hello world', 'hi world',
                                                 'hey world']},
                          'optional': {},
                          'regex': {}})

        intent = IntentCreator("hello"). \
            require('hello', ["hello (world|)"])
        container.add_intent(intent)
        self.assertEqual(container.intents["hello"],
                         {'intent_name': 'hello',
                          'required': {'hello': ['hello world', 'hello']},
                          'optional': {}, 'regex': {}})

        intent = IntentCreator("hey"). \
            require('hello', ["hey [world]"])
        container.add_intent(intent)
        self.assertEqual(container.intents["hey"],
                         {'intent_name': 'hey',
                          'required': {'hello': ['hey world', 'hey']},
                          'optional': {}, 'regex': {}})

    # test intent parsing
    def test_intents(self):
        container = IntentContainer()
        intent = IntentCreator("hello"). \
            require('hello',
                    ['hello', 'hi', 'how are you', "what's up"]).\
            optionally("world", ["world"])
        container.add_intent(intent)

        intent = IntentCreator("buy"). \
            require_autoregex('item',
                              ['buy {item}', 'purchase {item}', 'get {item}',
                               'get {item} for me'])
        container.add_intent(intent)

        intent = IntentCreator("eat"). \
            require_autoregex('fruit', ['eat {fruit}', 'eat some {fruit}'])
        container.add_intent(intent)

        self.assertEqual(container.calc_intent('hello')['name'], 'hello')
        self.assertEqual(container.calc_intent('bye')['name'], None)

        self.assertEqual(container.calc_intent('hello world'),
                         {'conf': 1.0,
                          'keywords': {'hello': ['hello'], 'world': ['world']},
                          'name': 'hello',
                          'utterance': 'hello world',
                          'utterance_remainder': ''})
        self.assertEqual(container.calc_intent('hello bob'),
                         {'conf': 0.9666666666666667,
                          'keywords': {'hello': ['hello']},
                          'name': 'hello',
                          'utterance': 'hello bob',
                          'utterance_remainder': 'bob'})
        self.assertEqual(container.calc_intent('hello'),
                         {'conf': 1.0,
                          'keywords': {'hello': ['hello']},
                          'name': 'hello',
                          'utterance': 'hello',
                          'utterance_remainder': ''})

        self.assertEqual(container.calc_intent('buy milk'),
                         {'conf': 0.8625,
                          'keywords': {'item': ['milk']},
                          'name': 'buy',
                          'utterance': 'buy milk',
                          'utterance_remainder': 'buy'})
        self.assertEqual(container.calc_intent('buy beer'),
                         {'conf': 0.8625,
                          'keywords': {'item': ['beer']},
                          'name': 'buy',
                          'utterance': 'buy beer',
                          'utterance_remainder': 'buy'})
        self.assertEqual(container.calc_intent('eat some bananas'),
                         {'conf': 0.85,
                          'keywords': {'fruit': ['bananas']},
                          'name': 'eat',
                          'utterance': 'eat some bananas',
                          'utterance_remainder': 'eat some'})

    def test_regex(self):
        container = IntentContainer()

        rx = r'\b(at|in|for) (?P<Location>.*)'
        intent = IntentCreator("time_in_location"). \
            require_regex("Location", rx)\
            .require("time", ["time"])
        container.add_intent(intent)

        self.assertEqual(
            container.calc_intent('what time is it in London'),
            {'conf': 0.8979999999999999,
             'keywords': {'Location': ['London'], 'time': ['time']},
             'name': 'time_in_location',
             'utterance': 'what time is it in London',
             'utterance_remainder': 'what is it in'}
        )

    def test_wildcards(self):
        container = IntentContainer()
        intent = IntentCreator("test"). \
            require_autoregex('thing',
                              ['I see {thing} (in|on) *'])
        container.add_intent(intent)

        self.assertEqual(
            container.calc_intent('I see a bin in there'),
            {'conf': 0.8300000000000001,
             'keywords': {'thing': ['a bin']},
             'name': 'test',
             'utterance': 'I see a bin in there',
             'utterance_remainder': 'I see in there'}
        )

    def test_multiple_keywords(self):
        container = IntentContainer()
        intent = IntentCreator("test"). \
            require_autoregex('thing', ['I see {thing} (in|on) {place}',
                                        'I see {thing}'])
        container.add_intent(intent)
        self.assertEqual(
            container.calc_intent('I see a bin'),
            {'conf': 0.8545454545454546,
             'keywords': {'thing': ['a bin']},
             'name': 'test',
             'utterance': 'I see a bin',
             'utterance_remainder': 'I see'}
        )
        self.assertEqual(
            container.calc_intent('I see a bin in there'),
            {'conf': 1.0,
             'keywords': {'place': ['there'], 'thing': ['a bin']},
             'name': 'test',
             'utterance': 'I see a bin in there',
             'utterance_remainder': 'I see in'}
        )

    def test_typed_keywords(self):
        container = IntentContainer()
        intent = IntentCreator("test_int"). \
            require_autoregex('number',
                              ['* number {number:int}'])
        container.add_intent(intent)

        self.assertEqual(
            container.calc_intent('i want nuMBer 3'),
            {'conf': 0.8133333333333334,
             'keywords': {'number': ['3']},
             'name': 'test_int',
             'utterance': 'i want nuMBer 3',
             'utterance_remainder': 'i want nuMBer'})

        intent = IntentCreator("test_float"). \
            require_autoregex('number',
                              ['* float {number:float}'])
        container.add_intent(intent)
        self.assertEqual(
            container.calc_intent('i want float 3.5'),
            {'conf': 0.825,
             'keywords': {'number': ['3.5']},
             'name': 'test_float',
             'utterance': 'i want float 3.5',
             'utterance_remainder': 'i want float'})

    def test_multiple_matches(self):
        container = IntentContainer()
        intent = IntentCreator("lights_off"). \
            require('off', ['close', "off", "disable", "shutdown"]).\
            require("light", ["light", "lights"])

        container.add_intent(intent)
        self.assertEqual(
            container.calc_intent('turn off the light and close the door'),
            {'conf': 0.9432432432432433,
             'keywords': {'light': ['light'], 'off': ['off', 'close']},
             'name': 'lights_off',
             'utterance': 'turn off the light and close the door',
             'utterance_remainder': 'turn the and the door'}
        )
        self.assertEqual(
            container.calc_intent('turn off the lights and close the door'),
            {'conf': 0.9447368421052631,
             'keywords': {'light': ['lights'], 'off': ['off', 'close']},
             'name': 'lights_off',
             'utterance': 'turn off the lights and close the door',
             'utterance_remainder': 'turn the and the door'}
        )

    # --- new tests ---

    def test_no_match_returns_none_name(self):
        container = IntentContainer()
        intent = IntentCreator("greet").require("hello", ["hello"])
        container.add_intent(intent)
        result = container.calc_intent("goodbye")
        self.assertIsNone(result["name"])

    def test_no_match_has_all_keys(self):
        container = IntentContainer()
        intent = IntentCreator("greet").require("hello", ["hello"])
        container.add_intent(intent)
        result = container.calc_intent("goodbye")
        for key in ("name", "conf", "keywords", "utterance", "utterance_remainder"):
            self.assertIn(key, result, f"Key '{key}' missing from no-match result")

    def test_remove_intent(self):
        container = IntentContainer()
        intent = IntentCreator("greet").require("hello", ["hello"])
        container.add_intent(intent)
        self.assertIn("greet", container.intents)
        container.remove_intent("greet")
        self.assertNotIn("greet", container.intents)

    def test_remove_nonexistent_no_error(self):
        container = IntentContainer()
        # Should not raise
        container.remove_intent("nonexistent")

    def test_duplicate_registration_raises(self):
        container = IntentContainer()
        intent = IntentCreator("greet").require("hello", ["hello"])
        container.add_intent(intent)
        with self.assertRaises(RuntimeError):
            container.add_intent(IntentCreator("greet").require("hello", ["hi"]))

    def test_remove_then_re_add_ok(self):
        container = IntentContainer()
        intent = IntentCreator("greet").require("hello", ["hello"])
        container.add_intent(intent)
        container.remove_intent("greet")
        # Should not raise after removal
        container.add_intent(IntentCreator("greet").require("hello", ["hi"]))
        self.assertIn("greet", container.intents)

    def test_add_intent_dict_directly(self):
        container = IntentContainer()
        built = IntentCreator("greet").require("hello", ["hello"]).build()
        container.add_intent(built)
        self.assertIn("greet", container.intents)

    def test_remove_intent_via_dict(self):
        container = IntentContainer()
        container.add_intent(IntentCreator("greet").require("hello", ["hello"]))
        built = {"intent_name": "greet"}
        container.remove_intent(built)
        self.assertNotIn("greet", container.intents)

    def test_optional_keyword_boosts_conf(self):
        container = IntentContainer()
        intent = IntentCreator("greet") \
            .require("hello", ["hello"]) \
            .optionally("world", ["world"])
        container.add_intent(intent)
        without_optional = container.calc_intent("hello")
        with_optional = container.calc_intent("hello world")
        self.assertGreaterEqual(with_optional["conf"], without_optional["conf"])

    def test_conf_clamped_to_1(self):
        container = IntentContainer()
        intent = IntentCreator("greet").require("hello", ["hello"])
        container.add_intent(intent)
        result = container.calc_intent("hello")
        self.assertLessEqual(result["conf"], 1.0)

    def test_conf_non_negative(self):
        container = IntentContainer()
        intent = IntentCreator("greet").require("hello", ["hello"])
        container.add_intent(intent)
        for utterance in ["hello", "hello world how are you today extra words"]:
            for r in container.calc_intents(utterance):
                self.assertGreaterEqual(r["conf"], 0.0)

    def test_empty_query_no_crash(self):
        container = IntentContainer()
        intent = IntentCreator("greet").require("hello", ["hello"])
        container.add_intent(intent)
        result = container.calc_intent("")
        self.assertIsNotNone(result)

    def test_calc_intents_yields_multiple(self):
        container = IntentContainer()
        container.add_intent(IntentCreator("a").require("kw", ["hello"]))
        container.add_intent(IntentCreator("b").require("kw", ["hello"]))
        results = list(container.calc_intents("hello"))
        self.assertGreaterEqual(len(results), 2)


class TestIntentCreator(unittest.TestCase):

    def test_build(self):
        intent = IntentCreator("test"). \
            require('hello', ["hello"]). \
            optionally("world", ["world"])
        self.assertEqual(intent.build(), {
            "intent_name": "test",
            "required": {"hello": ["hello"]},
            "optional": {"world": ["world"]},
            "regex": {}
        })

    def test_autoregex(self):
        intent = IntentCreator("buy"). \
            require_autoregex('item', ['buy {item}'])
        built = intent.build()
        self.assertIn("item", built["regex"])
        self.assertTrue(len(built["regex"]["item"]) > 0)

    def test_regex(self):
        rx = r'(?P<City>\w+)'
        intent = IntentCreator("location").require_regex("City", rx)
        built = intent.build()
        self.assertIn("City", built["regex"])
        self.assertIn(rx, built["regex"]["City"])

    def test_fluent_chain_returns_self(self):
        creator = IntentCreator("chain")
        result = creator.require("a", ["a"])
        self.assertIs(result, creator)
        result = creator.optionally("b", ["b"])
        self.assertIs(result, creator)
        result = creator.require_regex("c", [r"\w+"])
        self.assertIs(result, creator)

    def test_require_regex_raw(self):
        intent = IntentCreator("test").require_regex("slot", [r"(?P<slot>\d+)"])
        built = intent.build()
        self.assertIn("slot", built["regex"])

    def test_optional_regex(self):
        intent = IntentCreator("test") \
            .require("kw", ["hello"]) \
            .optional_regex("slot", [r"(?P<slot>\d+)"])
        built = intent.build()
        self.assertIn("slot", built["regex"])
        self.assertIn("slot", built["optional"])

    def test_optional_autoregex(self):
        intent = IntentCreator("test") \
            .require("kw", ["hello"]) \
            .optional_autoregex("thing", ["with {thing}"])
        built = intent.build()
        self.assertIn("thing", built["regex"])
        self.assertIn("thing", built["optional"])

    def test_require_multiple_keywords_same_slot(self):
        intent = IntentCreator("test") \
            .require("kw", ["foo"]) \
            .require("kw", ["bar"])
        built = intent.build()
        self.assertIn("foo", built["required"]["kw"])
        self.assertIn("bar", built["required"]["kw"])

    def test_optionally_multiple(self):
        intent = IntentCreator("test") \
            .require("kw", ["hello"]) \
            .optionally("extra", ["please"]) \
            .optionally("extra", ["kindly"])
        built = intent.build()
        self.assertIn("please", built["optional"]["extra"])
        self.assertIn("kindly", built["optional"]["extra"])


class TestBracketExpansion(unittest.TestCase):

    def test_alternation(self):
        result = expand_parentheses("(hello|hi) world")
        self.assertIn("hello world", result)
        self.assertIn("hi world", result)
        self.assertEqual(len(result), 2)

    def test_optional(self):
        result = expand_parentheses("hey [world]")
        self.assertIn("hey world", result)
        self.assertIn("hey", result)

    def test_nested(self):
        result = expand_parentheses("(a|b) (c|d)")
        self.assertIn("a c", result)
        self.assertIn("a d", result)
        self.assertIn("b c", result)
        self.assertIn("b d", result)

    def test_plain_string(self):
        result = expand_parentheses("hello world")
        self.assertEqual(result, ["hello world"])

    def test_empty_alternative(self):
        result = expand_parentheses("hello (world|)")
        self.assertIn("hello world", result)
        self.assertIn("hello", result)


if __name__ == "__main__":
    unittest.main()
