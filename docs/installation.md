# Installation

---

## Requirements

- Python 3.9 or later
- No native extensions; pure Python

---

## Stable release (PyPI)

```bash
pip install palavreado
```

This installs the core library only (`IntentContainer`, `IntentCreator`, normalisation utilities).  The OVOS pipeline plugin and its bus-client dependencies are **not** installed.

---

## With the OVOS pipeline plugin

```bash
pip install "palavreado[ovos]"
```

Pulls in the extra dependencies required by `PalavreadoPipeline`:

| Package | Purpose |
|---|---|
| `ovos-bus-client` | Message-bus client and `Message` type |
| `ovos-config` | Reads `mycroft.conf` / `ovos.conf` |
| `ovos-plugin-manager` | `ConfidenceMatcherPipeline` base class |
| `ovos-utils` | `FakeBus`, `flatten_list`, logging |
| `langcodes` | BCP-47 language tag resolution |

---

## From source

```bash
git clone https://github.com/TigreGotico/palavreado
cd palavreado
pip install -e .
# or with OVOS extras:
pip install -e ".[ovos]"
```

`setuptools-scm` is used for versioning; working from a git checkout gives an accurate version string.

---

## Development dependencies

```bash
pip install "palavreado[dev]"
```

Installs `pytest` and `pytest-cov` for running the test suite.

---

## Verifying the install

```python
from palavreado import IntentContainer, IntentCreator
c = IntentContainer()
intent = IntentCreator("hello").require("greeting", ["hello", "hi"])
c.add_intent(intent)
print(c.calc_intent("hello world"))
# {'name': 'hello', 'conf': 0.8, 'keywords': {'greeting': ['hello']}, ...}
```

---

## Core runtime dependencies

Installed automatically with `pip install palavreado`:

| Package | Purpose |
|---|---|
| `simplematch` | Pattern-to-regex conversion for autoregex slots (`palavreado/builder.py:14`) |
| `quebra_frases` | Tokenisation and chunk matching (`palavreado/__init__.py:14`) |
