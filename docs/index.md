# palavreado

Dead-simple keyword-based intent parser for [OpenVoiceOS (OVOS)](https://openvoiceos.org) voice assistants. It is a drop-in replacement for [Adapt](https://github.com/MycroftAI/adapt).

---

## Overview

palavreado matches natural-language utterances against named intents built from **required** and **optional** keyword slots. Each slot holds a vocabulary list. When the right words are present in the utterance, the intent fires. Optional regex and simplematch autoregex patterns enable structured entity extraction.

The library ships two things:

- A standalone Python library (`IntentContainer` + `IntentCreator`) usable without any OVOS dependency.
- An OVOS pipeline plugin (`PalavreadoPipeline`) that responds to the same message-bus events as Adapt, making it a zero-change drop-in for skills.

---

## Key classes

| Class | Purpose | Source |
|---|---|---|
| `IntentCreator` | Fluent builder for slot definitions | `palavreado/builder.py:48` |
| `IntentContainer` | Holds registered intents and performs keyword matching | `palavreado/__init__.py:80` |
| `PalavreadoPipeline` | OVOS pipeline plugin wrapping `IntentContainer` | `palavreado/opm.py:22` |

### Helper functions

| Function | Purpose | Source |
|---|---|---|
| `expand_samples` | Expand `(a|b)` / `[optional]` notation into flat string lists | `palavreado/builder.py:29` |
| `pattern2regex` | Convert simplematch patterns to regex strings | `palavreado/builder.py:14` |
| `normalize_utterance` | Normalise a query at inference time | `palavreado/bracket_expansion.py:115` |

| Function | Purpose | Source |
|---|---|---|
| `normalize_example` | Normalise a training sample at registration time | `palavreado/bracket_expansion.py:125` |
| `lemmatize` | Language-agnostic singular/apostrophe stem for matching | `palavreado/bracket_expansion.py:137` |
| `get_utterance_remainder` | Return the portion of an utterance not consumed by matched slots | `palavreado/__init__.py:54` |

---

## Quick facts

- **Languages:** any (normalisation and lemmatizer are language-agnostic. Multi-language OVOS is handled by per-language `IntentContainer` instances)
- **Matching strategy:** keyword lookup, contiguous + non-contiguous multi-word, optional regex / autoregex entity extraction

- **Dependencies:** `simplematch`, `quebra_frases` (core). The OVOS stack is only required for the pipeline plugin
- **Python:** 3.9 to 3.13
- **License:** Apache 2.0

---

## Contents

| Document | Audience | Summary |
|---|---|---|
| [Installation](installation.md) | Users | pip, from source, optional deps |
| [Quick Start](quickstart.md) | Users | 5-minute guide to building and matching intents |
| [Intent API](intent-api.md) | Developers | Full `IntentCreator` and `IntentContainer` reference |
| [Confidence Scoring](confidence.md) | Developers | Formula, multipliers, penalties, and clamping |

| Document | Audience | Summary |
|---|---|---|
| [Normalisation](normalisation.md) | Developers | Apostrophe handling, whitespace, lemmatizer |
| [Context Gating](context-gating.md) | Developers | `require_context` / `exclude_context` system |
| [OVOS Plugin](ovos-plugin.md) | Integrators | Pipeline plugin, bus events, mycroft.conf |
| [Hierarchical Pipeline](hierarchical-pipeline.md) | Integrators | Hierarchical two-level routing via `HierarchicalIntentContainer` |
| [Configuration](configuration.md) | Integrators | All config keys for the OVOS plugin |

| Document | Audience | Summary |
|---|---|---|
| [Benchmark](benchmark.md) | Everyone | 284-case accuracy comparison vs Adapt |
| [Troubleshooting](troubleshooting.md) | Everyone | Common problems and fixes |
