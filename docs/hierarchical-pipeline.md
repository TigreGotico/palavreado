# Hierarchical OVOS Pipeline Plugin

palavreado ships a second OVOS pipeline plugin, `HierarchicalPalavreadoPipeline`, exposed under its own OPM entry point. It behaves exactly like the flat `PalavreadoPipeline` from a skill's point of view — same `register_vocab` / `register_intent` / `detach_intent` / `detach_skill` bus surface — but internally uses a `HierarchicalIntentContainer` to group intents by skill and resolve them with **two-stage routing**.

Source: `palavreado/opm.py` (`HierarchicalPalavreadoPipeline`)

---

## Hierarchical vs domain routing

Intents can be grouped into **domains** (here, one per `skill_id`) and matched in
two ways:

- **Domain (parallel)** — every domain's sub-container is scored and the global
  argmax wins. No routing decision, so nothing can be misrouted.
- **Hierarchical (two-stage)** — a classifier picks **one** domain first, then
  only that domain resolves the intent. Cheaper at scale and it rejects
  off-topic utterances at stage one, but a misclassified domain is
  unrecoverable.

palavreado's variant is **hierarchical**. A parallel-domain container would be
pointless here: palavreado scores every intent independently of which container
it lives in (there is no shared vocabulary state to isolate), so grouping the
same intents into per-domain containers and taking the global argmax produces
exactly the same result as the flat `PalavreadoPipeline`. The two-stage router
is the only grouping that changes behaviour — it adds the stage-one rejection
gate.

This mirrors `ovos-adapt-pipeline-plugin`, which exposes both a
`DomainAdaptPipeline` (parallel) and a `HierarchicalAdaptPipeline` (two-stage):
adapt keeps a shared trie, so isolating it per domain genuinely matters there.
palavreado does not, so it ships only the hierarchical variant.

---

## Entry point

`pyproject.toml`:

```toml
[project.entry-points."opm.pipeline"]
palavreado                      = "palavreado.opm:PalavreadoPipeline"
ovos-palavreado-hierarchical-pipeline = "palavreado.opm:HierarchicalPalavreadoPipeline"
```

This is a **separate** entry point — not a config flag on the flat plugin — so it can be selected in `mycroft.conf` like any other pipeline.

To activate it, add the entry-point id to your `default_pipeline`:

```json
{
    "intents": {
        "pipeline": ["ovos-palavreado-hierarchical-pipeline", "fallback_high"]
    }
}
```

The flat `palavreado` entry point remains unchanged.

---

## Config block

Configuration is read from `intents.palavreado_hierarchical` (with `palavreado_hierarchical` at top level as a legacy fallback) so the hierarchical plugin can coexist with the flat plugin in the same OVOS instance.

```json
{
    "intents": {
        "palavreado_hierarchical": {
            "conf_high": 0.65,
            "conf_med":  0.45,
            "conf_low":  0.25,
            "max_words": 50
        }
    }
}
```

Every key understood by the flat plugin is also understood here.

---

## Two-stage routing

Each registered intent label is of the form `skill_id:intent_name`. The plugin treats the `skill_id` prefix as the **domain**.

```
register_intent skill_a:lights_off ──►  domain = "skill_a"
                                        intent  = "skill_a:lights_off"
register_intent skill_b:play_music ──►  domain = "skill_b"
                                        intent  = "skill_b:play_music"
```

At match time the `HierarchicalIntentContainer` runs two stages:

1. **Domain classification** — a top-level `domain_engine` classifies the utterance into a domain. Its per-domain entry is the union of every keyword sample registered under that domain, so a domain fires when the utterance contains any of its keywords.
2. **Intent resolution** — only the winning domain's sub-container is evaluated to pick the concrete intent.

An utterance that matches no domain is rejected at stage one, before any sub-container is evaluated — unrelated chitchat does not reach a skill.

The domain classifier is maintained automatically; registering an intent folds its keywords into the classifier, so no separate seeding step is required:

```python
d = HierarchicalIntentContainer()
d.register_domain_intent("home", lights_intent)
d.register_domain_intent("media", play_intent)

result = d.calc_intent("play some jazz")
top5  = d.calc_intents("play some jazz", top_k=5)
```

Routing rules:

| Bus event           | Behaviour                                                |
|---------------------|----------------------------------------------------------|
| `register_intent`   | `register_domain_intent(skill_id, creator)`              |
| `detach_intent`     | `remove_domain_intent(domain, name)`                     |
| `detach_skill`      | `remove_domain(skill_id)` (drops the whole sub-container)|

If a label has no `:` prefix (legacy skills) it is treated as its own domain.

---

## Class layout (hooks)

`PalavreadoPipeline` is structured around four small overrideable hooks so the hierarchical subclass only differs where it must:

| Hook                                       | Purpose                              |
|--------------------------------------------|--------------------------------------|
| `_build_container()`                       | Create the per-language container    |
| `_add_intent(container, name, creator)`    | Register an intent                   |
| `_remove_intent(container, name)`          | Drop a single intent                 |
| `_remove_skill(container, skill_id)`       | Drop all intents for a skill         |

`HierarchicalPalavreadoPipeline` overrides all four. Everything else — vocab handling, confidence tiers, session blacklists, manifest queries — is inherited unchanged.

---

## See also

- [HierarchicalIntentContainer API](../palavreado/hierarchical.py) — the underlying engine
- [`ovos-plugin.md`](ovos-plugin.md) — the flat pipeline plugin
