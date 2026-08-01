# Benchmark

palavreado ships a comparative accuracy and speed benchmark (`benchmark/compare.py`) that tests it against Adapt on a shared keyword-intent dataset.

---

## Dataset

Source: `benchmark/dataset.py`

### Size

| Metric | Value |
|---|---|
| Total test cases | 284 |
| Match utterances | 217 (across 22 intents) |
| No-match utterances | 67 |
| Vocabulary entries | ~130 keyword samples across 28 entity types |

### Intents covered

The 22 intents span common voice assistant domains:

| Intent | Required slots | Optional slots |
|---|---|---|
| `play_music` | `PlayKeyword` | `MusicKeyword` |
| `pause_music` | `StopKeyword`, `MusicKeyword` | none |
| `next_track` | `NextKeyword` | `MusicKeyword` |
| `set_volume` | `VolumeKeyword` | none |

| Intent | Required slots | Optional slots |
|---|---|---|
| `set_timer` | `SetKeyword`, `TimerKeyword` | none |
| `set_alarm` | `AlarmKeyword` | `SetKeyword` |
| `cancel_timer` | `CancelKeyword`, `TimerKeyword` | none |
| `weather_query` | `WeatherKeyword` | none |

| Intent | Required slots | Optional slots |
|---|---|---|
| `lights_on` | `LightKeyword`, `OnKeyword` | none |
| `lights_off` | `LightKeyword`, `OffKeyword` | none |
| `thermostat_set` | `ThermostatKeyword` | `HeatKeyword`, `CoolKeyword` |
| `call_contact` | `CallKeyword` | none |

| Intent | Required slots | Optional slots |
|---|---|---|
| `send_message` | `MessageKeyword` | none |
| `add_note` | `NoteKeyword` | none |
| `add_shopping` | `ShoppingKeyword` | none |
| `time_query` | `TimeKeyword` | none |

| Intent | Required slots | Optional slots |
|---|---|---|
| `date_query` | `DateKeyword` | none |
| `search_query` | `SearchKeyword` | none |
| `navigate_to` | `NavigateKeyword` | none |
| `help` | `HelpKeyword` | none |

| Intent | Required slots | Optional slots |
|---|---|---|
| `stop` | `StopCancelKeyword` | none |
| `add_reminder` | `RemindKeyword` | none |

### Utterance categories

Match utterances (`benchmark/dataset.py:199`):

| Category | Description | Count |
|---|---|---|
| Short (1 to 3 words) | e.g. `"play"`, `"lights on"` | ~19 |
| Medium (4 to 8 words) | e.g. `"skip this song"` | ~16 |
| Long (9 to 14 words) | e.g. `"could you get directions to the nearest petrol station"` | ~15 |
| Very long (15+ words) | e.g. full natural requests embedded in conversational speech | ~8 |

| Category | Description | Count |
|---|---|---|
| Multi-intent | Two intents' keywords both present, one is labelled as correct | ~10 |
| Harder cases | Keyword embedded in longer natural phrasing | ~20 |
| Ambiguous | Correct intent requires keyword disambiguation | ~6 |
| Standard | Direct keyword utterances | ~123 |

No-match utterances (`benchmark/dataset.py:491`):

| Category | Count |
|---|---|
| Conversational / off-topic (no keyword overlap) | ~16 |
| Single keyword present but not a command (past tense, noun use, idiom) | ~20 |
| Multiple keywords present, still not a command | ~15 |

| Category | Count |
|---|---|
| Rhetorical / hypothetical | ~7 |
| Third-person / reported speech | ~4 |
| Nonsense | ~5 |

---

## Results

Evaluated on the 284-case dataset.

| Engine | Accuracy | Precision | Recall | F1 | TN / no-match | FP | Median latency |
|---|---|---|---|---|---|---|---|
| **palavreado** | **81.7%** | 80.6% | **94.0%** | **0.868** | 28 / 67 | 49 | 0.58 ms |
| adapt | 80.3% | **81.0%** | 90.3% | 0.854 | **32 / 67** | **46** | **0.20 ms** |

**TN / no-match** = utterances that correctly returned no intent out of the 67 no-match cases.

---

## Interpreting the results

### Accuracy

Overall fraction of correct decisions (both correct matches and correct no-matches).  palavreado is 1.4 percentage points above Adapt.

### Precision vs Recall trade-off

palavreado has higher recall (94.0% vs 90.3%): it correctly identifies more true intent utterances.  Adapt has marginally higher precision (81.0% vs 80.6%) and fewer false positives on no-match utterances (46 vs 49).  The difference reflects palavreado's remainder penalty and multi-word quality multipliers. These let it match more loosely phrased utterances, at the cost of occasionally firing on non-command speech.

### False positives

Both engines share the same fundamental limitation of keyword-based matching. A vocabulary word appearing incidentally in an off-topic sentence triggers a false positive. The high FP rate (49 for palavreado, 46 for Adapt) reflects genuine dataset hardness. Past-tense, rhetorical, and third-person uses of vocabulary words are indistinguishable from commands without grammatical or pragmatic context.

### Latency

Adapt is approximately 3× faster at median latency (0.20 ms vs 0.58 ms).  Both figures are well within acceptable bounds for real-time voice interaction.  The additional cost in palavreado comes from lemmatization, the multi-pass contiguous/non-contiguous matching, and the scoring adjustments.

---

## Running the benchmark

### Prerequisites

palavreado must be installed. Adapt is optional. If Adapt is not available, the Adapt section is skipped with a `[SKIP]` message.

```bash
pip install "palavreado[dev]"
# To also run adapt:
pip install ovos-adapt-pipeline-plugin
```

### Command

```bash
python benchmark/compare.py
```

Or with uv:

```bash
uv run python benchmark/compare.py
```

### Output format

```
Dataset : 284 cases  (217 match, 67 no-match)
Intents : 22
Vocab   : N keyword samples across 28 entity types
==================================================================
  palavreado  (keyword, no fuzz)
==================================================================
  Accuracy  : 81.7%  (232/284)
  Precision : 80.6%
  Recall    : 94.0%
  F1        : 0.868
  FP        : 49 / 67  (73% of no-match)
  FN        : 13 / 217  (6% of match)
  Latency   : median=0.58ms  p95=X.XXms  max=X.XXms
  Per-intent (issues only):
    <intent_name>          recall=XX%  fn=N  fp=N
  Mismatches (N):
    [expected → predicted] (conf)  "utterance"
```

The summary table at the end shows both engines side by side.

### Reproducing specific mismatches

The benchmark prints every mismatch in the format:

```
[expected → predicted] (conf)  "utterance"
```

Where `expected` is the labelled intent (`None` for no-match cases) and `predicted` is what the engine returned.  Use these to identify which utterance categories or intents have the most errors.

---

## Dataset design notes

The dataset intentionally includes hard cases that keyword parsers struggle with:

1. **Incidental keyword use**: `"the timer on the oven is broken"` contains `"timer"` but is not a set-timer command.
2. **Idioms**: `"call it a day"`, `"buy some time"`, `"next time I'll remember"`.
3. **Past tense / reported speech**: `"she sent a text"`, `"they called an emergency meeting"`.
4. **Multi-intent utterances**: `"stop the music and cancel my alarm"` contains keywords from two intents. The dataset labels the one that should win.

These hard cases produce the bulk of false positives.  Any keyword parser without grammatical parsing will share this limitation.

---
[← Configuration](configuration.md) · [Home](index.md) · [Troubleshooting →](troubleshooting.md)
