# palavreado

Keyword-based intent parser for [OVOS](https://openvoiceos.org/) voice assistants — the drop-in replacement for [Adapt](https://github.com/MycroftAI/adapt).

Palavreado matches natural-language utterances against named intents built from **required** and **optional** keyword slots.  Each slot holds a list of vocabulary words; if the right words are present in the utterance, the intent fires.  Optional regex and [simplematch](https://github.com/tfeldmann/simplematch) autoregex patterns enable entity extraction.

---

## Install

```bash
pip install palavreado
```

---

## Quick start

### Keyword intent

Register vocabulary words for each slot, then build an intent from slots:

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
print(result["name"])      # lights_off
print(result["conf"])      # 0.9438
print(result["keywords"])  # {'off': ['off'], 'light': ['light']}
print(result["utterance_remainder"])  # 'turn the'
```

An intent only fires when **every required slot** has at least one keyword match in the utterance.

### Optional slots

Optional slots increase confidence when matched but do not gate the intent:

```python
intent = (
    IntentCreator("lights_off")
    .require("off",   ["off", "disable"])
    .require("light", ["light", "lights"])
    .optionally("room", ["kitchen", "bedroom", "bathroom"])
)
container.add_intent(intent)

result = container.calc_intent("turn off the bedroom lights")
print(result["keywords"]["room"])  # ['bedroom']
```

### Raw regex intent

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

Simplematch `{entity}` patterns are compiled to regexes automatically:

```python
intent = (
    IntentCreator("buy")
    .require_autoregex("item", ["buy {item}", "purchase {item}", "get {item}"])
)
container.add_intent(intent)

result = container.calc_intent("buy some milk")
print(result["keywords"]["item"])  # ['some milk']
```

Bracket/pipe expansion is supported in all sample strings:

```python
IntentCreator("lights_on") \
    .require("action", ["turn on", "switch on", "flick on"]) \
    .require("light",  ["(the |)(lights|light|lamp)"])
```

---

## `IntentCreator` API

| Method | Description |
|---|---|
| `require(name, samples)` | Required keyword slot — plain strings, bracket/pipe notation |
| `optionally(name, samples)` | Optional keyword slot |
| `require_regex(name, patterns)` | Required slot matched with a raw regex string |
| `optional_regex(name, patterns)` | Optional slot matched with a raw regex string |
| `require_autoregex(name, patterns)` | Required slot using simplematch `{entity}` patterns |
| `optional_autoregex(name, patterns)` | Optional slot using simplematch patterns |
| `build()` | Serialise to a plain `dict` |

All builder methods return `self` for fluent chaining.  The result of `build()` can be passed directly to `IntentContainer.add_intent()`.

---

## Breaking changes

**`add_intent` raises `RuntimeError` on duplicate names.**  
Previously, registering the same intent name twice silently overwrote the first entry.
Now a `RuntimeError` is raised so accidental double-registration is caught early.

Callers that re-register intents (e.g. on skill reload) must call
`remove_intent` first:

```python
container.remove_intent("my_intent")   # no-op if not present
container.add_intent(new_creator)
```

---

## `IntentContainer` API

| Method / property | Description |
|---|---|
| `add_intent(intent)` | Register an `IntentCreator` or built dict |
| `remove_intent(name)` | Unregister by name, creator, or dict |
| `calc_intent(query)` | Return the single best-matching result dict |
| `calc_intents(query)` | Yield all matching result dicts (conf > 0) |
| `intent_names` | List of registered intent name strings |
| `set_context(intent, context)` | Mark a context as active for an intent |
| `unset_context(intent, context)` | Remove an active context |
| `require_context(intent, context)` | Gate intent on context being active |
| `exclude_context(intent, context)` | Suppress intent when context is active |
| `exclude_keywords(intent, words)` | Suppress intent when any word appears in the query |

---

## Result fields

Every dict returned by `calc_intent` / yielded by `calc_intents`:

| Field | Type | Description |
|---|---|---|
| `name` | `str \| None` | Matched intent name, or `None` on no match |
| `conf` | `float` | Confidence score in `[0.0, 1.0]`, rounded to 4 decimal places |
| `keywords` | `dict[str, list]` | Matched slot values keyed by slot name |
| `utterance` | `str` | The normalised query string |
| `utterance_remainder` | `str` | Part of the utterance not consumed by any slot |

---

## Confidence scoring

Raw confidence is built up as:

- **+1 / n_required** per matched required slot  
- **+0.15 / n_optional** per matched optional slot  
- **×quality** multiplier per slot: `1.0` for contiguous matches, `0.8` for non-contiguous multi-word matches (e.g. `"turn down"` found in `"turn it down"`)

Then adjusted by:

- **Remainder penalty** `−0.2 × (unmatched_words / query_words)` — more leftover words = lower confidence  
- **Coverage bonus** `+0.05 × (matched_words / query_words)` — reward intents that explain more of the query  
- **Slot bonus** `+0.05 × (matched_slots / total_slots)` — more matched slots = stronger signal  

Result is clamped to `[0.0, 1.0]` and rounded to 4 decimal places.

A score of `1.0` means every slot was satisfied and nothing was left over.

---

## Normalisation

Queries and training samples are normalised at match time:

- **Apostrophes** (all Unicode variants including `'`, `'`, `ʼ`, `` ` ``) are replaced with a space — `"it's"` → `"it s"`.
- **Whitespace** is collapsed to a single space.
- **Plural/singular** matching uses a language-agnostic lemmatizer that strips a trailing `"s"` (not `"ss"`) so `"lights"` matches the training sample `"light"` and vice versa.

---

## Multi-word keyword matching

Palavreado supports both contiguous and non-contiguous multi-word keyword matching:

- **Contiguous** (quality 1.0): `"put on"` matches `"put on some music"` exactly.
- **Non-contiguous** (quality 0.8): `"turn down"` matches `"turn it down a bit"` even though `"it"` intervenes.

Non-contiguous matches carry a lower quality multiplier so they never override a precise contiguous match when both are present.

---

## Context gating

Intents can be gated on named session contexts:

```python
container.require_context("lights_off", "lights_active")
container.set_context("lights_off", "lights_active")
result = container.calc_intent("turn off the lights")  # fires

container.unset_context("lights_off", "lights_active")
result = container.calc_intent("turn off the lights")  # suppressed (context missing)
```

`exclude_context` suppresses an intent while a specific context is active:

```python
container.exclude_context("lights_off", "lights_already_off")
container.set_context("lights_off", "lights_already_off")
result = container.calc_intent("turn off the lights")  # suppressed
```

---

## Keyword exclusion

Suppress an intent when specific words appear in the query:

```python
container.exclude_keywords("play_music", ["stop", "pause"])
result = container.calc_intent("stop the music")  # play_music suppressed
```

Single-word exclusions use whole-word matching; multi-word exclusions use `\b` word-boundary regex so `"play"` does not fire on `"display"`.

---

## OVOS pipeline plugin

Palavreado ships an OVOS pipeline plugin that replaces Adapt as the keyword intent engine.  It responds to the same bus events (`register_vocab`, `register_intent`, `detach_intent`, `detach_skill`) so existing skills need no changes.

Configure in `mycroft.conf`:

```json
{
  "intents": {
    "palavreado": {
      "conf_high": 0.65,
      "conf_med":  0.45,
      "conf_low":  0.25
    }
  }
}
```

Entry point: `palavreado.opm:PalavreadoPipeline`

---

## Benchmark

Evaluated on a keyword-intent dataset of **284 cases** (217 match utterances across 22 intents, 67 no-match utterances).  The dataset spans short (1–3 words), medium (4–8), long (9–14), and very long (15+ word) utterances, plus multi-intent queries where two intents' keywords are both present.  No-match cases cover easy off-topic utterances, single keyword in incidental context (past tense, reported speech, third-person, rhetorical), and harder traps with multiple keywords that are still not commands.

| Engine | Accuracy | Precision | Recall | F1 | TN / no-match | FP | Median latency |
|---|---|---|---|---|---|---|---|
| **palavreado** | **81.7%** | 80.6% | **94.0%** | **0.868** | 28 / 67 | 49 | 0.58 ms |
| adapt | 80.3% | **81.0%** | 90.3% | 0.854 | **32 / 67** | **46** | **0.20 ms** |

**TN / no-match** = utterances that correctly returned *no intent* out of the 67 no-match cases.

Palavreado beats Adapt on accuracy, recall, and F1, but Adapt bails out more conservatively (32 vs 28 correct no-matches).  Both engines share the same fundamental limitation of keyword-based matching: a vocabulary word appearing incidentally in an off-topic sentence triggers a false positive.  The high FP rate reflects real hardness in the dataset — keyword parsers have no grammatical or pragmatic context, so past-tense, rhetorical, and third-person uses of vocabulary words are indistinguishable from commands.

Run the benchmark yourself:

```bash
python benchmark/compare.py
```

---

## Credits

Originally an experimental research project by [**TigreGoticoLda**](https://tigregotico.pt), polished
and donated to OpenVoiceOS as part of the NLnet
[NGI0 Commons Fund](https://nlnet.nl/project/OpenVoiceOS) under grant
agreement No [101135429](https://cordis.europa.eu/project/id/101135429).

![NGI0 / NLnet](./ngi.png)

---

## License

Apache 2.0
