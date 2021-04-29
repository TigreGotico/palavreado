from palavreado import IntentCreator
import unittest


class TestIntentCreator(unittest.TestCase):
    # test intent creation
    def test_build(self):
        intent = IntentCreator("greeting"). \
            require("hello", ["hello", "hi", "hey"])
        self.assertEqual(intent.build(),
                         {'intent_name': 'greeting',
                          'optional': {},
                          'regex': {},
                          'required': {'hello': ['hello', 'hi', 'hey']}})

        intent = IntentCreator("hello world") \
            .require("hello", ["hello", "hi", "hey"]) \
            .optionally("world", ["world"])
        self.assertEqual(intent.build(),
                         {'intent_name': 'hello world',
                          'optional': {'world': ['world']},
                          'regex': {},
                          'required': {'hello': ['hello', 'hi', 'hey']}})

    def test_autoregex(self):
        intent = IntentCreator("buy"). \
            require_autoregex("item",
                              ['buy {item}', 'purchase {item}', 'get {item}',
                               'get {item} for me'])
        self.assertEqual(intent.build(),
                         {'intent_name': 'buy',
                          'optional': {},
                          'regex': {
                              'item': ['^buy\\ (?P<item>.*)$',
                                       '^purchase\\ (?P<item>.*)$',
                                       '^get\\ (?P<item>.*)$',
                                       '^get\\ (?P<item>.*)\\ for\\ me$']},
                          'required': {'item': []}})

        intent = IntentCreator("drive"). \
            require_autoregex("place",
                              ['drive me to {place}', 'take me to {place}',
                               'navigate to {place}'])
        self.assertEqual(intent.build(),
                         {'intent_name': 'drive',
                          'optional': {},
                          'regex': {
                              'place': ['^drive\\ me\\ to\\ (?P<place>.*)$',
                                        '^take\\ me\\ to\\ (?P<place>.*)$',
                                        '^navigate\\ to\\ (?P<place>.*)$']},
                          'required': {'place': []}})

        intent = IntentCreator("eat"). \
            require("eat", ['eat', 'munch on']).\
            optional_autoregex("fruit",
                              ['eat {fruit}', 'eat some {fruit}',
                               'munch on (some|) {fruit}'])
        self.assertEqual(intent.build(),
                         {'intent_name': 'eat',
                          'optional': {'fruit': []},
                          'regex': {'fruit': ['^eat\\ (?P<fruit>.*)$',
                                              '^eat\\ some\\ (?P<fruit>.*)$',
                                              '^munch\\ on\\ some\\ (?P<fruit>.*)$',
                                              '^munch\\ on\\ \\ (?P<fruit>.*)$']},
                          'required': {'eat': ['eat', 'munch on']}})

    def test_regex(self):
        rx = r'*\b(at|in|for) (?P<Location>.*)'
        intent = IntentCreator("time_in_location"). \
            require_regex("Location", rx).require("time", ["time"])
        self.assertEqual(intent.build(),
                         {'intent_name': 'time_in_location',
                          'optional': {},
                          'regex': {'Location': [r'*\bat (?P<Location>.*)',
                                                 r'*\bin (?P<Location>.*)',
                                                 r'*\bfor (?P<Location>.*)']},
                          'required': {'Location': [], 'time': ['time']}})


