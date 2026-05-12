# OVOS Pipeline Plugin

palavreado ships `PalavreadoPipeline` — an OVOS pipeline plugin that replaces Adapt as the keyword intent engine.  It responds to the same message-bus events as the Adapt plugin, so existing skills require no changes.

Source: `palavreado/opm.py`

---

## Architecture

```
OVOS skill                         PalavreadoPipeline
    │                                      │
    │─── register_vocab ─────────────────►│  _vocab[lang][entity_type] += [entity_value]
    │─── register_intent ────────────────►│  IntentCreator built + IntentContainer.add_intent
    │─── detach_intent ──────────────────►│  IntentContainer.remove_intent
    │─── detach_skill ───────────────────►│  remove all intents + vocab for skill_id prefix
    │                                      │
OVOS pipeline                              │
    │─── utterance ───────────────────────►│  _match_intent (utterances, lang, message)
    │                                      │    └─ per-lang IntentContainer.calc_intent
    │◄── IntentHandlerMatch ───────────────│
```

Per-language `IntentContainer` instances are created at startup for each language in `lang` + `secondary_langs`.  Vocab and intents are segregated by language.

---

## Entry point

`pyproject.toml:38`

```toml
[project.entry-points."ovos.pipeline"]
palavreado = "palavreado.opm:PalavreadoPipeline"
```

OVOS loads this automatically when the package is installed with `pip install "palavreado[ovos]"`.

---

## Class: `PalavreadoPipeline`

`palavreado/opm.py:22`

Inherits from `ConfidenceMatcherPipeline` (ovos-plugin-manager).  The three abstract methods (`match_high`, `match_medium`, `match_low`) are implemented using configurable confidence thresholds.

### Constructor

```python
PalavreadoPipeline(
    bus: MessageBusClient | FakeBus | None = None,
    config: dict | None = None,
)
```

Configuration is read from `mycroft.conf` via `ovos_config.config.Configuration()` under the key `"palavreado"`.  If `config` is passed explicitly, it takes priority.

At startup:
- `lang` and `secondary_langs` are read from the core OVOS config and standardised to BCP-47 tags.
- One `IntentContainer` and one vocab dict are created per resolved language.
- All seven bus event handlers are registered.

---

## Bus events handled

### `register_vocab`

`palavreado/opm.py:74`

Registers a keyword sample or regex entity.

**Message data fields:**

| Field | Type | Description |
|---|---|---|
| `entity_value` | `str` | The natural-language word or phrase |
| `entity_type` | `str` | Slot name the value belongs to |
| `alias_of` | `str \| None` | If set, the value is registered under this entity type instead |
| `regex` | `str \| None` | Raw regex string; if present, `entity_value` is ignored |
| `lang` | `str` | BCP-47 language tag |

When `regex` is present: stored in `self._regexes[lang][entity_type]`.
Otherwise: stored in `self._vocab[lang][entity_type]`.

### `register_intent`

`palavreado/opm.py:108`

Builds a palavreado `IntentCreator` from an Adapt intent envelope and registers it.

The intent envelope (created by `ovos_workshop.intents.open_intent_envelope`) carries:
- `requires` — list of `(entity_type, entity_alias)` tuples for required slots
- `optional` — list of `(entity_type, entity_alias)` tuples for optional slots
- `at_least_one` — list of groups; each group is a list of entity types, at least one of which must match

**Mapping to palavreado:**
- `requires` → `creator.require(kw_type, vocab_samples)` + `creator.require_regex` if regexes exist
- `optional` → `creator.optionally(kw_type, vocab_samples)` + `creator.optional_regex` if regexes exist
- `at_least_one` → each group member added as optional (best-effort; exact group semantics are not enforced)

If the intent name is already registered (e.g. on skill reload), the `RuntimeError` from `add_intent` is caught and the registration is silently skipped.

### `detach_intent`

`palavreado/opm.py:154`

Removes a single intent by name from all language containers.

**Message data:** `intent_name` (str)

### `detach_skill`

`palavreado/opm.py:163`

Removes all intents and vocabulary belonging to a skill.  Skill ownership is determined by the `skill_id` prefix convention: `intent_name.startswith(skill_id)` and `entity_type.startswith(skill_id)`.

**Message data:** `skill_id` (str)

### `intent.service.palavreado.get`

`palavreado/opm.py:182`

Debug/introspection endpoint.  Calculates the best intent for a single utterance and emits the result.

**Request data:** `utterance` (str), `lang` (str)

**Reply:** `intent.service.palavreado.reply` with `{"intent": <match_data or None>}`

### `intent.service.palavreado.manifest.get`

`palavreado/opm.py:191`

Returns the list of all registered intents.

**Reply:** `intent.service.palavreado.manifest` with `{"intents": [...]}`

### `intent.service.palavreado.vocab.manifest.get`

`palavreado/opm.py:196`

Returns the list of all registered vocab items.

**Reply:** `intent.service.palavreado.vocab.manifest` with `{"vocab": [...]}`

---

## Confidence tiers

`palavreado/opm.py:203`

OVOS queries the pipeline at three confidence tiers in order of decreasing confidence.  Only the highest tier that returns a match is used.

| Method | Fires when | Default threshold |
|---|---|---|
| `match_high` | `conf >= conf_high` | 0.65 |
| `match_medium` | `conf >= conf_med` | 0.45 |
| `match_low` | `conf >= conf_low` | 0.25 |

Each method calls the same internal `_match_intent` and filters on the threshold.

---

## `_match_intent`

`palavreado/opm.py:229`

Internal method that drives actual matching.

```python
_match_intent(
    utterances: tuple[str, ...],
    lang: str | None = None,
    message: str | None = None,    # serialised Message
) -> IntentHandlerMatch | None
```

Steps:
1. Deserialise the message and look up the session via `SessionManager.get`.
2. Filter out utterances longer than `max_words`.
3. Resolve the language via `_resolve_lang` (BCP-47 closest-match with `langcodes`).
4. For each utterance, call `_calc_palavreado_intent` and keep the best result.
5. Check session blacklists (`sess.blacklisted_intents`, `sess.blacklisted_skills`).
6. Return `IntentHandlerMatch(match_type=name, match_data=result, skill_id=name.split(":")[0], utterance=...)`.

---

## Language resolution

`palavreado/opm.py:282`

```python
def _resolve_lang(self, lang: str) -> str | None:
```

Uses `langcodes.closest_match` to find the closest registered language container.  Returns `None` (skip matching) if the closest match distance is 10 or more (no reasonable language match).

---

## `mycroft.conf` configuration

palavreado reads its configuration from the `"palavreado"` section of `mycroft.conf` (or `ovos.conf`).  All keys are optional.

```json
{
  "intents": {
    "palavreado": {
      "conf_high": 0.65,
      "conf_med":  0.45,
      "conf_low":  0.25,
      "max_words": 50
    }
  }
}
```

See [Configuration](configuration.md) for the full key reference.

**Note:** `lang` and `secondary_langs` are read from the top-level OVOS config, not from the `palavreado` section.

---

## Comparison with Adapt

Both engines are keyword-based parsers.  They process the same `register_vocab` / `register_intent` bus messages.

| Feature | palavreado | Adapt |
|---|---|---|
| Required vocabulary slots | Yes | Yes |
| Optional vocabulary slots | Yes | Yes |
| Regex entity slots | Yes | Yes |
| `at_least_one` groups | Partial (treated as optional) | Full |
| Contiguous multi-word match | Yes (quality 1.0) | Yes |
| Non-contiguous multi-word match | Yes (quality 0.8) | Yes |
| Plural/apostrophe normalisation | Yes (lemmatizer) | Partial |
| Remainder penalty | Yes | No |
| Coverage/slot bonuses | Yes | No |
| Confidence range | 0.0 – 1.0 | 0.0 – 1.0 |
| Median match latency | ~0.58 ms | ~0.20 ms |
| Accuracy (benchmark) | 81.7% | 80.3% |
| Recall (benchmark) | 94.0% | 90.3% |

Adapt is approximately 3× faster on the benchmark dataset.  palavreado has higher recall and slightly better overall accuracy.

---

## Migration notes

**Skills written for Adapt work without modification.**  The bus event interface is identical.

If you are switching from Adapt to palavreado at the pipeline level:

1. Install: `pip install "palavreado[ovos]"`
2. Add to `mycroft.conf`:

```json
{
  "intents": {
    "pipeline": ["palavreado_high", "palavreado_medium", "palavreado_low", ...]
  }
}
```

3. Remove or reorder Adapt pipeline entries.

The `at_least_one` group semantics are not fully equivalent: palavreado treats each member as an optional slot rather than enforcing the group constraint.  Skills that rely on exact `at_least_one` behaviour may see different results.

---

## `shutdown`

`palavreado/opm.py:289`

Removes all bus event handlers registered in `__init__`.  Called automatically by the OVOS plugin lifecycle.
