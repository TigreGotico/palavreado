# palavreado

Keyword-based intent parser for [OVOS](https://openvoiceos.org/) voice assistants — the drop-in replacement for [Adapt](https://github.com/MycroftAI/adapt).

Palavreado matches natural-language utterances against named intents built from **required** and **optional** keyword slots. Each slot holds a list of vocabulary words; if the right words are present in the utterance, the intent fires. Optional regex and [simplematch](https://github.com/tfeldmann/simplematch) autoregex patterns enable entity extraction.

---

## Install

```bash
pip install palavreado
```

For the OVOS pipeline plugin:

```bash
pip install "palavreado[ovos]"
```

---

## Quick start

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

## OVOS pipeline plugin

Palavreado ships an OVOS pipeline plugin that replaces Adapt as the keyword intent engine. It responds to the same bus events (`register_vocab`, `register_intent`, `detach_intent`, `detach_skill`) so existing skills need no changes.

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

## Documentation

| Page | Description |
|---|---|
| [Quickstart](docs/quickstart.md) | 5-minute guide: keyword intents, optional slots, autoregex |
| [Intent API](docs/intent-api.md) | Full `IntentCreator` and `IntentContainer` reference |
| [Confidence Scoring](docs/confidence.md) | How scores are calculated: formula, penalties, bonuses |
| [Normalisation](docs/normalisation.md) | Apostrophe handling, whitespace, plural/singular lemmatizer |
| [Context Gating](docs/context-gating.md) | Require / exclude contexts, worked examples |
| [OVOS Pipeline Plugin](docs/ovos-plugin.md) | Bus events, confidence tiers, migration from Adapt |
| [Configuration](docs/configuration.md) | All config keys with types, defaults, and effect |
| [Benchmark](docs/benchmark.md) | Accuracy results and how to reproduce them |
| [Troubleshooting](docs/troubleshooting.md) | Common issues and fixes |

---

## Benchmark

Evaluated on a keyword-intent dataset of **284 cases** (217 match utterances across 22 intents, 67 no-match utterances).

| Engine | Accuracy | Precision | Recall | F1 | TN / no-match | FP | Median latency |
|---|---|---|---|---|---|---|---|
| **palavreado** | **81.7%** | 80.6% | **94.0%** | **0.868** | 28 / 67 | 49 | 0.58 ms |
| adapt | 80.3% | **81.0%** | 90.3% | 0.854 | **32 / 67** | **46** | **0.20 ms** |

```bash
python benchmark/compare.py
```

---

## Credits

Originally an experimental research project by
[**TigreGóticoLda**](https://tigregotico.pt), polished and donated to
[OpenVoiceOS](https://openvoiceos.org). Its modernization, integration into
OpenVoiceOS, and intent benchmarking were funded by the NGI0 Commons Fund.

[![NGI0 Commons Fund](./ngi.png)](https://nlnet.nl/project/OpenVoiceOS)

This project was funded through the [NGI0 Commons Fund](https://nlnet.nl/commonsfund),
a fund established by [NLnet](https://nlnet.nl) with financial support from the
European Commission's [Next Generation Internet](https://ngi.eu) programme, under
the aegis of [DG Communications Networks, Content and Technology](https://commission.europa.eu/about-european-commission/departments-and-executive-agencies/communications-networks-content-and-technology_en)
under grant agreement No [101135429](https://cordis.europa.eu/project/id/101135429).

---

## License

Apache 2.0
