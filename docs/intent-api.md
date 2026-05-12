# Intent API Reference

Full reference for `IntentCreator` (`palavreado/builder.py`) and `IntentContainer` (`palavreado/__init__.py`).

---

## `IntentCreator`

`palavreado/builder.py:48`

Fluent builder for palavreado intents.  All methods return `self` for chaining.  Pass the creator object (or its `.build()` output) to `IntentContainer.add_intent`.

### Constructor

```python
IntentCreator(name: str)
```

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | Unique intent name.  Must be unique across the container it will be registered in. |

### `require`

`palavreado/builder.py:68`

```python
.require(keyword_name: str, keyword_samples: str | list[str]) -> IntentCreator
```

Add a required keyword slot.  The intent will not fire unless at least one sample in this slot matches the utterance.

| Parameter | Type | Description |
|---|---|---|
| `keyword_name` | `str` | Slot/entity name used as the key in `result["keywords"]`. |
| `keyword_samples` | `str \| list[str]` | One or more sample strings.  Bracket/pipe notation is expanded. |

**Returns:** `self`

**Example:**

```python
IntentCreator("lights_off") \
    .require("off",   ["off", "disable", "shutdown"]) \
    .require("light", ["(the |)(lights|light|lamp)"])
```

### `optionally`

`palavreado/builder.py:86`

```python
.optionally(keyword_name: str, keyword_samples: str | list[str]) -> IntentCreator
```

Add an optional keyword slot.  The intent fires without this slot; a match increases confidence.

| Parameter | Type | Description |
|---|---|---|
| `keyword_name` | `str` | Slot/entity name. |
| `keyword_samples` | `str \| list[str]` | One or more sample strings.  Bracket/pipe notation is expanded. |

**Returns:** `self`

**Example:**

```python
IntentCreator("lights_off") \
    .require("off",   ["off", "disable"]) \
    .require("light", ["light", "lights"]) \
    .optionally("room", ["kitchen", "bedroom", "bathroom"])
```

### `require_regex`

`palavreado/builder.py:102`

```python
.require_regex(keyword_name: str, keyword_samples: str | list[str]) -> IntentCreator
```

Add a required slot matched with raw regular expression strings.  Named capture groups (`(?P<name>...)`) populate `result["keywords"]` as additional sub-slot values.

| Parameter | Type | Description |
|---|---|---|
| `keyword_name` | `str` | Slot name.  Also used as a key in the `required` dict so the required-slots check knows this slot must match. |
| `keyword_samples` | `str \| list[str]` | One or more raw Python regex strings. |

**Returns:** `self`

**Matching behaviour (`palavreado/__init__.py:334`):**
Patterns are tried longest-first.  The engine attempts `re.match` then `re.search`; if a named-group match succeeds, group values enter `keywords`.  Patterns are compiled once at `add_intent` time with `re.IGNORECASE`.

**Example:**

```python
rx = r'\b(at|in|for) (?P<Location>.*)'
IntentCreator("time_in_location") \
    .require_regex("Location", rx) \
    .require("time", ["time"])
```

### `optional_regex`

`palavreado/builder.py:123`

```python
.optional_regex(keyword_name: str, keyword_samples: str | list[str]) -> IntentCreator
```

Same as `require_regex` but the slot is optional.

**Returns:** `self`

### `require_autoregex`

`palavreado/builder.py:143`

```python
.require_autoregex(
    keyword_name: str,
    keyword_samples: str | list[str],
    case_sensitive: bool = False,
) -> IntentCreator
```

Add a required slot using [simplematch](https://github.com/tfeldmann/simplematch) `{entity}` patterns.  Each pattern is converted to a regex via `pattern2regex` (`palavreado/builder.py:14`) before storage; the resulting regex is treated identically to a raw regex slot.

| Parameter | Type | Description |
|---|---|---|
| `keyword_name` | `str` | Slot name. |
| `keyword_samples` | `str \| list[str]` | simplematch patterns, e.g. `"buy {item}"`.  Bracket/pipe expansion is applied first. |
| `case_sensitive` | `bool` | Default `False`.  Passed to `simplematch.Matcher`. |

**Returns:** `self`

**Example:**

```python
IntentCreator("buy") \
    .require_autoregex("item", ["buy {item}", "purchase {item}", "get {item}"])
```

Result: `result["keywords"]["item"] == ['some milk']` for query `"buy some milk"`.

### `optional_autoregex`

`palavreado/builder.py:168`

```python
.optional_autoregex(
    keyword_name: str,
    keyword_samples: str | list[str],
    case_sensitive: bool = False,
) -> IntentCreator
```

Same as `require_autoregex` but the slot is optional.

**Returns:** `self`

### `build`

`palavreado/builder.py:192`

```python
.build() -> dict
```

Serialise the intent definition to a plain dict.

**Returns:**

```python
{
    "intent_name": str,          # the name passed to the constructor
    "required":    dict[str, list[str]],   # slot → expanded samples
    "optional":    dict[str, list[str]],
    "regex":       dict[str, list[str]],   # slot → regex strings
}
```

The dict can be passed directly to `IntentContainer.add_intent`.  `IntentCreator` instances can also be passed directly — `add_intent` calls `.build()` internally.

---

## `IntentContainer`

`palavreado/__init__.py:80`

Container that holds registered intents and performs keyword matching.

### Constructor

```python
IntentContainer()
```

No arguments.  Initialises empty intent, context, and exclusion stores.

### Properties

#### `intent_names`

`palavreado/__init__.py:105`

```python
@property
intent_names -> list[str]
```

Names of all currently registered intents.

---

### Registration

#### `add_intent`

`palavreado/__init__.py:112`

```python
add_intent(intent: IntentCreator | dict) -> None
```

Register a new intent.

| Parameter | Type | Description |
|---|---|---|
| `intent` | `IntentCreator \| dict` | An `IntentCreator` instance or the dict from `IntentCreator.build()`. |

**Raises:** `RuntimeError` if an intent with the same name is already registered.

**Side effects at registration time:**
- All training samples in `required` and `optional` are normalised via `normalize_example` (apostrophe dropping, whitespace collapsing).
- All regex patterns are compiled with `re.IGNORECASE` and stored in `self._compiled[name]`.
- Regex patterns per slot are sorted by length (longest first) in `self._sorted_regex[name]`.

**Example:**

```python
container = IntentContainer()
creator = IntentCreator("lights_off") \
    .require("off", ["off", "disable"]) \
    .require("light", ["light", "lights"])
container.add_intent(creator)
```

#### `remove_intent`

`palavreado/__init__.py:154`

```python
remove_intent(name: str | IntentCreator | dict) -> None
```

Unregister an intent.  Silently does nothing when the intent is not found.

| Parameter | Type | Description |
|---|---|---|
| `name` | `str \| IntentCreator \| dict` | Intent name string, an `IntentCreator` (`.name` attribute is read), or a dict with `"intent_name"` or `"name"` key. |

---

### Matching

#### `calc_intents`

`palavreado/__init__.py:253`

```python
calc_intents(query: str) -> Iterator[dict]
```

Yield scored match results for every intent that has confidence > 0 for `query`.

| Parameter | Type | Description |
|---|---|---|
| `query` | `str` | The utterance to match.  Normalised internally via `normalize_utterance`. |

**Yields:** match result dicts (see Result fields below).

Results are yielded in registration order, not sorted by confidence.  To get the single best match use `calc_intent`.

#### `calc_intent`

`palavreado/__init__.py:398`

```python
calc_intent(query: str) -> dict
```

Return the single best-matching intent result for `query`.

| Parameter | Type | Description |
|---|---|---|
| `query` | `str` | The utterance to match. |

**Returns:** The highest-confidence match dict.  When no intent matches, returns:

```python
{"name": None, "keywords": {}, "conf": 0, "utterance": <normalised query>, "utterance_remainder": <normalised query>}
```

**Tie-breaking** (`palavreado/__init__.py:414`): When two intents produce equal confidence scores, the tie is broken by:
1. More query words matched (higher specificity).
2. Shorter utterance remainder (less leftover).
3. Lexicographic intent name order (determinism).

#### Result fields

| Field | Type | Description |
|---|---|---|
| `name` | `str \| None` | Matched intent name, or `None` on no match |
| `conf` | `float` | Confidence in `[0.0, 1.0]`, rounded to 4 decimal places |
| `keywords` | `dict[str, list[str]]` | Matched slot values keyed by slot name |
| `utterance` | `str` | The normalised query string |
| `utterance_remainder` | `str` | Portion of the utterance not consumed by any matched slot |

---

### Context gating

Context gating controls intent availability based on named boolean flags.  See [Context Gating](context-gating.md) for a full explanation.

#### `set_context`

`palavreado/__init__.py:173`

```python
set_context(intent_name: str, context_name: str, context_val: object = None) -> None
```

Mark `context_name` as active for `intent_name`.  The optional `context_val` is stored but not used in matching logic — only presence/absence matters.

#### `unset_context`

`palavreado/__init__.py:178`

```python
unset_context(intent_name: str, context_name: str) -> None
```

Remove an active context from `intent_name`.  Silent no-op if not set.

#### `require_context`

`palavreado/__init__.py:183`

```python
require_context(intent_name: str, context_name: str) -> None
```

Gate `intent_name` so it only fires when `context_name` is active.  Multiple requirements can be added; all must be active.

#### `unrequire_context`

`palavreado/__init__.py:188`

```python
unrequire_context(intent_name: str, context_name: str) -> None
```

Lift a context requirement.

#### `exclude_context`

`palavreado/__init__.py:194`

```python
exclude_context(intent_name: str, context_name: str) -> None
```

Suppress `intent_name` whenever `context_name` is active.

#### `unexclude_context`

`palavreado/__init__.py:199`

```python
unexclude_context(intent_name: str, context_name: str) -> None
```

Lift a context-based suppression.

---

### Keyword exclusion

#### `exclude_keywords`

`palavreado/__init__.py:207`

```python
exclude_keywords(intent_name: str, samples: list[str]) -> None
```

Suppress `intent_name` when any keyword in `samples` appears in the query.

| Parameter | Type | Description |
|---|---|---|
| `intent_name` | `str` | Intent to suppress. |
| `samples` | `list[str]` | Keywords that trigger suppression. |

**Matching rules (`palavreado/__init__.py:221`):**
- Single-word keywords: whole-word match (the keyword must appear as a standalone token in the query's word set).
- Multi-word keywords: a `\b`-anchored word-boundary regex, compiled at call time, is used so `"play"` does not fire on `"display"`.

**Example:**

```python
container.exclude_keywords("play_music", ["stop", "pause"])
result = container.calc_intent("stop the music")
# play_music is suppressed; result["name"] may be None or another intent
```

---

### Internal: `_filter`

`palavreado/__init__.py:227`

```python
_filter(query: str) -> list[str]
```

Returns a list of intent names that should be excluded for this `query`.  Called automatically at the start of `calc_intents`; not part of the public API but documented here for completeness.

Three exclusion passes run in order:
1. Keyword exclusions (`self._compiled_exclusions`).
2. Required-context failures (any required context not present in `available_contexts`).
3. Excluded-context hits (any excluded context currently present in `available_contexts`).

---

### Helper: `get_utterance_remainder`

`palavreado/__init__.py:54`

```python
get_utterance_remainder(
    utterance: str,
    samples: list[str],
    as_string: bool = True,
) -> str | list[str]
```

Return the portion of `utterance` not covered by any token in `samples`.

Comparison is done on lemmatized forms so plural/apostrophe variants of already-matched keywords are also consumed.

| Parameter | Type | Description |
|---|---|---|
| `utterance` | `str` | Full utterance string. |
| `samples` | `list[str]` | Matched keyword/entity samples. |
| `as_string` | `bool` | Return a space-joined string (default) or a list of token strings. |

**Returns:** Remainder string or list.

---

## `expand_samples`

`palavreado/builder.py:29`

```python
expand_samples(samples: str | list[str]) -> list[str]
```

Expand bracket/pipe notation into a flat list of strings.

```python
expand_samples("(hello|hi) world")
# → ["hello world", "hi world"]

expand_samples(["lights [please]"])
# → ["lights", "lights please"]
```

Called internally by `require`, `optionally`, `require_autoregex`, and `optional_autoregex`.

---

## `pattern2regex`

`palavreado/builder.py:14`

```python
pattern2regex(pattern: str, case_sensitive: bool = False) -> str
```

Convert a simplematch pattern string to a regular expression string.

```python
pattern2regex("buy {item}")
# → some regex with a capture group for {item}
```

Uses `simplematch.Matcher` internally.
