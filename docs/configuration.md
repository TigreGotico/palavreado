# Configuration Reference

This page documents all configuration keys for the `PalavreadoPipeline` OVOS plugin.  Configuration is read from the `"palavreado"` section of `mycroft.conf` (or `ovos.conf`).

Source: `palavreado/opm.py:42`

---

## Configuration location

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

The `"palavreado"` dict is fetched via:

```python
core_config = Configuration()
config = config or core_config.get("palavreado", {})
```

---

## Keys

### `conf_high`

| Property | Value |
|---|---|
| Type | `float` |
| Default | `0.65` |
| Range | `0.0` to `1.0` |

Minimum confidence required for `match_high` to return a result. OVOS tries high-confidence pipelines first. A result at this tier suppresses the medium and low tier checks.

Raise this value to make palavreado more conservative at the high tier. Fewer false positives result, but more utterances fall through to the medium tier or other pipeline stages. Lower the value to make more intents fire at the high tier.

---

### `conf_med`

| Property | Value |
|---|---|
| Type | `float` |
| Default | `0.45` |
| Range | `0.0` to `1.0` |

Minimum confidence for `match_medium`.  Only evaluated if `match_high` returns `None`.

---

### `conf_low`

| Property | Value |
|---|---|
| Type | `float` |
| Default | `0.25` |
| Range | `0.0` to `1.0` |

Minimum confidence for `match_low`.  Only evaluated if both high and medium tiers return `None`.  Setting this very low may cause spurious keyword hits to fire when a single vocabulary word appears incidentally in an unrelated utterance.

---

### `max_words`

| Property | Value |
|---|---|
| Type | `int` |
| Default | `50` |
| Unit | Words (tokens split by whitespace) |

Utterances longer than `max_words` are silently discarded before matching.  This prevents pathological-length inputs from consuming disproportionate matching time.

If all utterances in a batch exceed this limit, `_match_intent` logs an error and returns `None`.

---

## Language configuration

Language settings are **not** read from the `"palavreado"` section.  They come from the top-level OVOS config:

| Key | Where | Description |
|---|---|---|
| `lang` | top-level `mycroft.conf` | Primary language tag (BCP-47). Defaults to `"en-US"` if not set. |
| `secondary_langs` | top-level `mycroft.conf` | List of additional BCP-47 language tags. One `IntentContainer` is created per language. |

```json
{
  "lang": "en-US",
  "secondary_langs": ["pt-PT", "es-ES"]
}
```

Source: `palavreado/opm.py:36`

```python
self.lang = standardize_lang_tag(core_config.get("lang", "en-US"))
langs = core_config.get("secondary_langs") or []
if self.lang not in langs:
    langs.append(self.lang)
```

The primary language is always included in the language set even if not listed in `secondary_langs`.

---

## Summary table

| Key | Type | Default | Section | Description |
|---|---|---|---|---|
| `conf_high` | `float` | `0.65` | `palavreado` | High-confidence match threshold |
| `conf_med` | `float` | `0.45` | `palavreado` | Medium-confidence match threshold |
| `conf_low` | `float` | `0.25` | `palavreado` | Low-confidence match threshold |

| Key | Type | Default | Section | Description |
|---|---|---|---|---|
| `max_words` | `int` | `50` | `palavreado` | Maximum utterance word count |
| `lang` | `str` | `"en-US"` | top-level | Primary language BCP-47 tag |
| `secondary_langs` | `list[str]` | `[]` | top-level | Additional language BCP-47 tags |

---

## Tuning guidance

### Reducing false positives

Raise `conf_low` and `conf_med`. At the default `conf_low` of `0.25`, an intent with a single matched required slot and no remainder penalty can score around `0.25` to `0.3`. This may be too permissive for some skill domains.

### Improving recall for short utterances

Short utterances (1 to 3 words) often score lower than medium utterances. There is less total vocabulary to match against, and the remainder ratio is less favourable. If short commands like `"play"` or `"timer"` are not firing, lower `conf_low` or check that the relevant vocabulary slots have single-word entries.

### Multi-language deployments

Make sure `secondary_langs` is populated in `mycroft.conf`. If a language is not listed, no `IntentContainer` is created for it, and all utterances in that language return `None`. `_resolve_lang` uses BCP-47 closest-match (via `langcodes`). For this reason, `"en-GB"` matches an `"en-US"` container with a small distance penalty.

---
[← OVOS Pipeline Plugin](ovos-plugin.md) · [Home](index.md) · [Benchmark →](benchmark.md)
