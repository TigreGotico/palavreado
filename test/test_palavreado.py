from palavreado import IntentContainer, IntentCreator
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
                          'keywords': {'hello': 'hello', 'world': 'world'},
                          'name': 'hello',
                          'utterance': 'hello world',
                          'utterance_remainder': ''})
        self.assertEqual(container.calc_intent('hello bob'),
                         {'conf': 0.9666666666666667,
                          'keywords': {'hello': 'hello'},
                          'name': 'hello',
                          'utterance': 'hello bob',
                          'utterance_remainder': 'bob'})
        self.assertEqual(container.calc_intent('hello'),
                         {'conf': 1.0,
                          'keywords': {'hello': 'hello'},
                          'name': 'hello',
                          'utterance': 'hello',
                          'utterance_remainder': ''})

        self.assertEqual(container.calc_intent('buy milk'),
                         {'conf': 0.8625,
                          'keywords': {'item': 'milk'},
                          'name': 'buy',
                          'utterance': 'buy milk',
                          'utterance_remainder': 'buy'})
        self.assertEqual(container.calc_intent('buy beer'),
                         {'conf': 0.8625,
                          'keywords': {'item': 'beer'},
                          'name': 'buy',
                          'utterance': 'buy beer',
                          'utterance_remainder': 'buy'})
        self.assertEqual(container.calc_intent('eat some bananas'),
                         {'conf': 0.85,
                          'keywords': {'fruit': 'bananas'},
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
             'keywords': {'Location': 'London', 'time': 'time'},
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
             'keywords': {'thing': 'a bin'},
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
             'keywords': {'thing': 'a bin'},
             'name': 'test',
             'utterance': 'I see a bin',
             'utterance_remainder': 'I see'}
        )
        self.assertEqual(
            container.calc_intent('I see a bin in there'),
            {'conf': 1.0,
             'keywords': {'place': 'there', 'thing': 'a bin'},
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
             'keywords': {'number': '3'},
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
             'keywords': {'number': '3.5'},
             'name': 'test_float',
             'utterance': 'i want float 3.5',
             'utterance_remainder': 'i want float'})
