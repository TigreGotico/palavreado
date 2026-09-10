# Quick Start

This guide takes you from zero to a working intent parser in five minutes.

---

## 1. Install

```bash
pip install palavreado
```

---

## 2. Keyword intent (required slots only)

Register vocabulary words for each slot, build an intent, and match utterances.

```python
from palavreado import IntentContainer, IntentCreator

container = IntentContainer()

intent = (
    IntentCreator("lights_off")
    .require("off",   ["off", "disable", "shutdown"])
    .require("light", ["light", "lights", "lamp"])
)
container.add_intent(intent)

result = container.calc_intent("turn off the lights")
print(result["name"])               # lights_off
print(result["conf"])               # 0.9438
print(result["keywords"])           # {'off': ['off'], 'light': ['light']}
print(result["utterance_remainder"]) # 'turn the'
```

An intent only fires when **every required slot** has at least one matching keyword in the utterance.  Unmatched required slots cause the intent to be skipped entirely.

---

## 3. Optional slots

Optional slots contribute to confidence when present but do not gate the intent.

```python
intent = (
    IntentCreator("lights_off")
    .require("off",   ["off", "disable"])
    .require("light", ["light", "lights"])
    .optionally("room", ["kitchen", "bedroom", "bathroom"])
)
container.add_intent(intent)

result = container.calc_intent("turn off the bedroom lights")
print(result["keywords"]["room"])   # ['bedroom']
print(result["conf"])               # higher than without room match
```

---

## 4. Bracket/pipe expansion

All sample strings support `(a|b)` alternation and `[optional]` syntax, which are expanded at registration time.

```python
IntentCreator("lights_on") \
    .require("action", ["(turn|switch|flick) on"]) \
    .require("light",  ["(the |)(lights|light|lamp)"])
```

`(turn|switch|flick) on` expands to `["turn on", "switch on", "flick on"]` before any matching occurs.  `[word]` is equivalent to `(word|)`.

---

## 5. Autoregex: entity extraction via simplematch patterns

simplematch `{entity}` patterns are compiled to regular expressions automatically.  Matched capture groups are returned as slot values.

```python
intent = (
    IntentCreator("buy")
    .require_autoregex("item", ["buy {item}", "purchase {item}", "get {item}"])
)
container.add_intent(intent)

result = container.calc_intent("buy some milk")
print(result["keywords"]["item"])   # ['some milk']
```

The `{item}` placeholder captures everything that fills that position in the pattern.

---

## 6. Raw regex slots

When simplematch is not expressive enough, supply raw regex strings directly.  Named groups become slot values.

```python
rx = r'\b(at|in|for) (?P<Location>.*)'
intent = (
    IntentCreator("time_in_location")
    .require_regex("Location", rx)
    .require("time", ["time", "what time"])
)
container.add_intent(intent)

result = container.calc_intent("what time is it in London")
print(result["keywords"]["Location"])   # ['London']
```

---

## 7. Calling `calc_intent`

`calc_intent` always returns a dict.  When nothing matches, `name` is `None` and `conf` is `0`.

```python
result = container.calc_intent("some random utterance")
if result["name"]:
    skill_handler(result)
else:
    fallback_handler(result["utterance"])
```

To see every intent that scored above zero (not just the best):

```python
for result in container.calc_intents("turn off the lights"):
    print(result["name"], result["conf"])
```

---

## 8. Removing an intent

Registering the same intent name twice raises `RuntimeError`.  Remove the old registration first.

```python
container.remove_intent("lights_off")   # silent no-op if not present
container.add_intent(new_intent)
```

---

## Result dict fields

| Field | Type | Description |
|---|---|---|
| `name` | `str \| None` | Matched intent name, or `None` |
| `conf` | `float` | Confidence in `[0.0, 1.0]`, 4 decimal places |
| `keywords` | `dict[str, list[str]]` | Matched values keyed by slot name |
| `utterance` | `str` | Normalised query |
| `utterance_remainder` | `str` | Portion of the utterance not consumed by any slot |

---
[← Installation](installation.md) · [Home](index.md) · [Intent API →](intent-api.md)
