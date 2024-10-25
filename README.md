# Palavreado

*A dead-simple keyword based intent parser*

## Example

```python
from palavreado import IntentContainer, IntentCreator

container = IntentContainer()

# keywords
intent = IntentCreator("hello"). \
    require('hello', ['hello', 'hi', 'how are you', "what's up"]).\
    optionally("world", ["world"])
container.add_intent(intent)

# regex
rx = r'\b(at|in|for) (?P<Location>.*)'
intent = IntentCreator("time_in_location"). \
    require_regex("Location", rx)\
    .require("time", ["time"])
container.add_intent(intent)

# keyword extraction patterns
intent = IntentCreator("buy"). \
    require_autoregex('item',
                      ['buy {item}', 
                       'purchase {item}', 
                       'get {item}',
                       'get {item} for me'])
container.add_intent(intent)


container.calc_intent('hello world')
# {'conf': 1.0,
#  'keywords': {'hello': 'hello', 'world': 'world'},
#  'name': 'hello',
#  'utterance': 'hello world',
#  'utterance_remainder': ''}
                 
container.calc_intent('hello bob')
# {'conf': 0.9666666666666667,
#  'keywords': {'hello': 'hello'},
#  'name': 'hello',
#  'utterance': 'hello bob',
#  'utterance_remainder': 'bob'}
                 
container.calc_intent('hello')
# {'conf': 1.0,
#  'keywords': {'hello': 'hello'},
#  'name': 'hello',
#  'utterance': 'hello',
#  'utterance_remainder': ''}

container.calc_intent('buy milk')
# {'conf': 0.8625,
#  'keywords': {'item': 'milk'},
#  'name': 'buy',
#  'utterance': 'buy milk',
#  'utterance_remainder': 'buy'}

container.calc_intent('what time is it in London')
#{'conf': 0.8979999999999999,
# 'keywords': {'Location': 'London', 'time': 'time'},
# 'name': 'time_in_location',
# 'utterance': 'what time is it in London',
# 'utterance_remainder': 'what is it in'}

```