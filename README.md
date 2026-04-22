# palavreado

Dead-simple keyword-based intent parser for [OVOS](https://openvoiceos.org/) voice assistants.

Palavreado matches natural-language utterances against named intents made of required and optional keyword slots, with optional regex and [simplematch](https://github.com/tfeldmann/simplematch) autoregex patterns for entity extraction.

---

## Install

```bash
pip install palavreado
```

---

## Quick start

### Keyword intent

```python
from palavreado import IntentContainer, IntentCreator

container = IntentContainer()

intent = (
    IntentCreator("lights_off")
    .require("off", ["off", "disable", "shutdown"])
    .require("light", ["light", "lights"])
)
container.add_intent(intent)

result = container.calc_intent("turn off the lights")
print(result["name"])      # lights_off
print(result["conf"])      # 0.944…
print(result["keywords"])  # {'off': ['off'], 'light': ['lights']}
```

### Regex intent

```python
rx = r'\b(at|in|for) (?P<Location>.*)'
intent = (
    IntentCreator("time_in_location")
    .require_regex("Location", rx)
    .require("time", ["time"])
)
container.add_intent(intent)

result = container.calc_intent("what time is it in London")
print(result["keywords"]["Location"])  # ['London']
```

### Autoregex / entity extraction

```python
intent = (
    IntentCreator("buy")
    .require_autoregex("item", ["buy {item}", "purchase {item}", "get {item}"])
)
container.add_intent(intent)

result = container.calc_intent("buy some milk")
print(result["keywords"]["item"])  # ['some milk']
```

---

## API — `IntentCreator` methods

| Method | Description |
|---|---|
| `require(name, samples)` | Add a **required** keyword slot (plain strings, bracket/pipe notation supported) |
| `optionally(name, samples)` | Add an **optional** keyword slot |
| `require_regex(name, patterns)` | Add a required slot matched with a **raw regex** |
| `optional_regex(name, patterns)` | Add an optional slot matched with a raw regex |
| `require_autoregex(name, patterns)` | Add a required slot using **simplematch** patterns (`{entity}`) |
| `optional_autoregex(name, patterns)` | Add an optional slot using simplematch patterns |
| `build()` | Serialise to a plain `dict` (passed directly to `IntentContainer.add_intent`) |

All builder methods return `self` for fluent chaining.

---

## Result fields

Every dict returned by `calc_intent` / yielded by `calc_intents` contains:

| Field | Type | Description |
|---|---|---|
| `name` | `str \| None` | Name of the matched intent, or `None` on no match |
| `conf` | `float` | Confidence score in `[0.0, 1.0]` |
| `keywords` | `dict[str, list]` | Matched slot values keyed by slot name |
| `utterance` | `str` | The original query string |
| `utterance_remainder` | `str` | Part of the utterance not consumed by any slot |

---

## Confidence scoring

Confidence starts at `1 / num_required_slots` per matched required slot and adds a small fraction (`0.15 / num_optional_slots`) for each matched optional slot.  It is then penalised proportionally to the length of `utterance_remainder` relative to the full utterance, and clamped to `[0.0, 1.0]`.

A score of `1.0` means every slot was satisfied and nothing was left over.
