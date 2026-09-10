# Confidence Scoring

This document explains how palavreado computes confidence scores.  All relevant logic is in `palavreado/__init__.py`.

---

## Overview

Confidence is a float in `[0.0, 1.0]`, rounded to 4 decimal places.  It is computed in two phases:

1. **Raw slot accumulation**: confidence is built up as each required or optional slot matches.
2. **Final adjustment**: three corrections (remainder penalty, coverage bonus, slot bonus) are applied, then the result is clamped and rounded.

---

## Phase 1: Raw slot accumulation

`palavreado/__init__.py:321`

### Required slots

Each required slot contributes an equal share of `1.0`:

```
partial_conf = 1.0 / n_required
```

When slot `kw` matches with quality `q`:

```
conf += partial_conf * q
```

With `n_required` required slots all matching at quality 1.0, `conf` reaches exactly `1.0` before any adjustment.

### Optional slots

Each optional slot contributes an equal share of `0.15`:

```
partial_opt_conf = 0.15 / max(n_optional, 1)
```

When an optional slot matches with quality `q`:

```
conf += partial_opt_conf * q
```

Optional slots cannot alone make an intent fire. They are only evaluated after the required-slot check passes.

### Quality multipliers

`palavreado/__init__.py:274`

Quality is determined by *how* a keyword matched:

| Quality | Condition |
|---|---|
| `1.0` | Contiguous match: keyword appears as a contiguous token span in the utterance (exact surface or after lemma normalisation) |
| `0.8` | Non-contiguous match: all tokens of a multi-word keyword appear in the utterance but not as a contiguous span |

Single-word keywords always produce contiguous matches (quality `1.0`).  Non-contiguous matches are only possible for multi-word keywords.

**Example:**
- Keyword `"put on"`, utterance `"put on some music"` → contiguous, quality `1.0`
- Keyword `"turn down"`, utterance `"turn it down a bit"` → non-contiguous, quality `0.8`

### Regex slots

`palavreado/__init__.py:335`

Regex slots are evaluated before keyword slots.  When a regex pattern matches:

- If the matched slot belongs to `required`: `conf += partial_conf * 0.9`
- If the matched slot belongs to `optional`: `conf += partial_opt_conf * 0.9`
- Named capture groups not declared as explicit slots contribute a smaller increment: `conf += partial_opt_conf * 0.2` each

The factor `0.9` (rather than `1.0`) reflects that regex matches are less discriminative than exact keyword vocabulary matches.

---

## Phase 2: Final adjustment

`palavreado/__init__.py:26`

```python
def _score(raw_conf, remainder, q_words, n_matched_slots, n_total_slots):
```

All adjustments operate in `[0, 1]` space.

### Remainder penalty

```
remainder_penalty = (r_words / q_words) * 0.2
conf -= remainder_penalty
```

Where:
- `r_words` = number of words in the utterance remainder (not consumed by any matched slot)
- `q_words` = total number of words in the normalised query

**Effect:** An utterance where half the words are left over loses `0.2 × 0.5 = 0.1` confidence.  This ensures a short, precise utterance like `"lights off"` (all words consumed) ranks clearly above a long utterance where only one keyword matched.

The weight of `0.2` was chosen so that unmatched filler words reduce confidence measurably but do not overwhelm the primary slot signal.

### Coverage bonus

```
matched_words = q_words - r_words
coverage = matched_words / q_words
conf += coverage * 0.05
```

A small upward nudge for intents that explain more of the query.  Maximum bonus: `+0.05` (all words consumed).

### Slot bonus

```
slot_bonus = (n_matched_slots / max(n_total_slots, 1)) * 0.05
conf += slot_bonus
```

Where `n_total_slots = n_required + n_optional`.

**Effect:** An intent that matched more slots (required + optional) scores slightly higher than one that matched fewer.  This ensures a two-slot intent (`lights_off` needing both `light` and `off`) beats a single-slot intent when both would otherwise tie.

---

## Full formula

```
conf_raw = sum(partial_conf_i * quality_i   for each matched required slot i)
         + sum(partial_opt_i  * quality_j   for each matched optional slot j)

r_words      = word_count(utterance_remainder)
q_words      = word_count(normalised_query)
matched_words = q_words - r_words

conf_final = conf_raw
           - (r_words / q_words) * 0.2         # remainder penalty
           + (matched_words / q_words) * 0.05   # coverage bonus
           + (n_matched_slots / n_total_slots) * 0.05  # slot bonus

conf = round(clamp(conf_final, 0.0, 1.0), 4)
```

---

## Clamping and rounding

`palavreado/__init__.py:51`

```python
return round(min(1.0, max(0.0, conf)), 4)
```

- Values above `1.0` (theoretically possible when optional bonuses stack) are clamped to `1.0`.
- Values below `0.0` are clamped to `0.0`.
- 4 decimal places allow fine-grained ranking while avoiding floating-point noise.

---

## Score of `1.0`

A perfect score of `1.0` is achievable when:
- Every required slot matches at quality `1.0`.
- No words remain in the utterance remainder.
- Optional slots also match (pushing toward and possibly slightly above `1.0`, which is then clamped).

**Example:** `"lights off"` against an intent requiring `light` and `off`. Both slots match, with zero remainder.

---

## Worked example

Intent: `lights_off` with two required slots (`light`, `off`).
Query: `"turn off the lights"` (4 words)

```
n_required   = 2
partial_conf = 1.0 / 2 = 0.5

slot "off"   → matches "off"   (1 word consumed), quality 1.0 → conf += 0.5
slot "light" → matches "light" (1 word consumed, lemma of "lights"), quality 1.0 → conf += 0.5

conf_raw = 1.0

remainder = "turn the"  →  r_words = 2
q_words   = 4
matched_words = 2

remainder_penalty = (2 / 4) * 0.2 = 0.1
coverage_bonus    = (2 / 4) * 0.05 = 0.025
slot_bonus        = (2 / 2) * 0.05 = 0.05   (n_matched=2, n_total=2)

conf = 1.0 - 0.1 + 0.025 + 0.05 = 0.975 → rounded: 0.975
```

(Actual output may differ slightly due to word tokenisation details from `quebra_frases`.)

---

## Confidence thresholds in the OVOS plugin

When used as a pipeline plugin, `PalavreadoPipeline` maps confidence values to three tiers:

| Tier | Default threshold | Config key |
|---|---|---|
| High | `conf >= 0.65` | `conf_high` |
| Medium | `conf >= 0.45` | `conf_med` |
| Low | `conf >= 0.25` | `conf_low` |

See [Configuration](configuration.md) for how to tune these.

---
[← Intent API](intent-api.md) · [Home](index.md) · [Normalisation →](normalisation.md)
