# Troubleshooting

---

## Intent not firing

### All required slots present but `calc_intent` returns `name: None`

**Check 1 — Required-slot check (`palavreado/__init__.py:381`):**

```python
if not intent["required"].keys() <= matches.keys():
    continue
```

Every slot name in `required` must appear as a key in `matches`.  If a slot has no samples, it cannot match.

Debug:

```python
intent_dict = container.intents["my_intent"]
print("required slots:", list(intent_dict["required"].keys()))
for slot, samples in intent_dict["required"].items():
    print(f"  {slot}: {samples}")
```

An empty sample list (`[]`) for a required slot means no keyword can ever match — the intent will never fire.  Ensure `require()` is called with at least one non-empty string.

**Check 2 — Normalisation mismatch:**

Training samples are normalised via `normalize_example` at registration time.  The query is normalised via `normalize_utterance`.  Both strip apostrophes and collapse whitespace.  A sample like `"don't"` becomes `"don t"` — the corresponding query token must also normalise to `"don t"`.

Print the stored normalised samples:

```python
print(container.intents["my_intent"]["required"])
```

**Check 3 — Lemmatization edge case:**

The lemmatizer strips a trailing `s` from words longer than 2 characters (unless they end in `ss`).  For example, `"bus"` becomes `"bu"`.  If your training vocabulary contains a word that over-reduces, add the exact form that appears in queries.

**Check 4 — Context gating:**

If `require_context` has been called for an intent, the context must be active.

```python
print(container.required_contexts.get("my_intent", []))
print(container.available_contexts.get("my_intent", {}))
```

If required contexts are listed but not present in `available_contexts`, the intent is excluded before matching.

**Check 5 — Keyword exclusion:**

If `exclude_keywords` has been called and the query contains an excluded keyword, the intent is suppressed.

```python
print(container.excluded_keywords.get("my_intent", []))
```

---

## `RuntimeError` on `add_intent`

```
RuntimeError: Intent 'my_intent' is already registered. Remove it first before re-adding.
```

`palavreado/__init__.py:128`

palavreado raises `RuntimeError` if you try to register the same intent name twice.  This was a deliberate change from silent overwrite behaviour.

**Fix:** Remove the intent before re-registering it.

```python
container.remove_intent("my_intent")   # silent no-op if not present
container.add_intent(new_creator)
```

In the OVOS plugin (`palavreado/opm.py:148`), duplicate registration during skill reloads is silently ignored:

```python
try:
    container.add_intent(creator)
except RuntimeError:
    pass   # already registered — skip
```

If you are managing `IntentContainer` directly, add a similar guard or always call `remove_intent` before `add_intent`.

---

## Low confidence on valid utterances

### Symptom: correct intent matches but confidence is below `conf_low` (0.25)

**Cause 1 — Long utterance, few keywords matched:**

The remainder penalty is `(r_words / q_words) * 0.2`.  For a 20-word utterance where only 1 word matched, `r_words = 19`, penalty = `0.19`.  A single required slot contributes `1.0 / 1 * quality`, but after penalty and with a small coverage bonus, the result can be near `0.85 - 0.19 + 0.05 * 0.05 ≈ 0.66`.  For a 2-slot intent where only 1 slot fires this is worse.

Check `result["utterance_remainder"]` to see how many words are unaccounted for.

**Cause 2 — Non-contiguous multi-word match (quality 0.8):**

Multi-word keywords matched out of order (e.g. `"turn down"` found in `"turn it down"`) apply a `0.8` quality multiplier.  Add the exact phrasing as a separate vocabulary entry to get quality `1.0`.

**Cause 3 — Regex slot match penalty:**

Regex-matched slots receive a `0.9` multiplier rather than `1.0` (`palavreado/__init__.py:357`).  If all slots are regex-matched, the raw confidence is `0.9` before adjustments.

**Fix:** Lower `conf_low` in configuration, or add more specific vocabulary entries to raise match quality.

---

## Language mismatch (OVOS plugin)

### Symptom: intent never fires; `_resolve_lang` returns `None`

`palavreado/opm.py:282`

```python
def _resolve_lang(self, lang: str) -> str | None:
    closest, score = closest_match(lang, list(self.containers.keys()))
    return closest if score < 10 else None
```

If the closest BCP-47 match score is 10 or more, no container is selected and `None` is returned.

**Check:** Print the registered language containers:

```python
print(list(pipeline.containers.keys()))
```

If the query language (e.g. `"en-AU"`) is not close enough to a registered language (e.g. only `"pt-PT"` is registered), no match is possible.

**Fix:** Add the relevant language to `secondary_langs` in `mycroft.conf`:

```json
{
  "secondary_langs": ["en-US", "pt-PT"]
}
```

---

## Intent matches wrong intent

### Symptom: two intents share vocabulary; the wrong one fires

**Check tie-breaking order (`palavreado/__init__.py:414`):**

1. Highest confidence score wins.
2. If tied: more matched words wins.
3. If still tied: shorter remainder wins.
4. If still tied: lexicographic name order.

Add more required slots to the more specific intent so its raw confidence is higher, or add distinct vocabulary that appears only in one intent's context.

**Multi-word keywords help:**  A 2-word keyword like `"play music"` at quality `1.0` beats two 1-word keywords at quality `0.8` from a competing intent.

---

## `calc_intents` yields nothing

### Symptom: no results at all from `calc_intents`

**Check 1 — No intents registered:**

```python
print(container.intent_names)
```

**Check 2 — All intents excluded by context or keyword exclusion:**

```python
excluded = container._filter("your query here")
print(excluded)
```

**Check 3 — Empty required slots:**

Any intent where at least one required slot has an empty sample list will be skipped (no samples → no match possible → `matches.keys()` cannot satisfy `required.keys()`).

---

## OVOS plugin not loading

### Symptom: `PalavreadoPipeline` not available in OVOS

**Check the entry point is installed:**

```bash
pip show palavreado
python -c "from palavreado.opm import PalavreadoPipeline; print('OK')"
```

If the import fails, the `[ovos]` extras are missing:

```bash
pip install "palavreado[ovos]"
```

**Check `mycroft.conf` pipeline order:**

palavreado pipeline names are `palavreado_high`, `palavreado_medium`, `palavreado_low`.  They must be present in the `intents.pipeline` list in `mycroft.conf`.

```json
{
  "intents": {
    "pipeline": [
      "palavreado_high",
      "...other pipeline stages...",
      "palavreado_medium",
      "palavreado_low"
    ]
  }
}
```
