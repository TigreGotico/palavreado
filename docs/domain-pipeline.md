# Domain-aware OVOS Pipeline Plugin

palavreado ships a second OVOS pipeline plugin, `DomainPalavreadoPipeline`, exposed under its own OPM entry point. It behaves exactly like the flat `PalavreadoPipeline` from a skill's point of view — same `register_vocab` / `register_intent` / `detach_intent` / `detach_skill` bus surface — but internally uses a `DomainIntentContainer` to group intents by skill and evaluate them with a **parallel-argmax** strategy.

Source: `palavreado/opm.py` (`DomainPalavreadoPipeline`)

---

## Entry point

`pyproject.toml`:

```toml
[project.entry-points."opm.pipeline"]
palavreado                      = "palavreado.opm:PalavreadoPipeline"
ovos-palavreado-domain-pipeline = "palavreado.opm:DomainPalavreadoPipeline"
```

This is a **separate** entry point — not a config flag on the flat plugin — so it can be selected in `mycroft.conf` like any other pipeline.

To activate it, add the entry-point id to your `default_pipeline`:

```json
{
    "intents": {
        "pipeline": ["ovos-palavreado-domain-pipeline", "fallback_high"]
    }
}
```

The flat `palavreado` entry point remains unchanged.

---

## Config block

Configuration is read from `intents.palavreado_domain` (with `palavreado_domain` at top level as a legacy fallback) so the domain plugin can coexist with the flat plugin in the same OVOS instance.

```json
{
    "intents": {
        "palavreado_domain": {
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

## Parallel-argmax routing

Each registered intent label is of the form `skill_id:intent_name`. The plugin treats the `skill_id` prefix as the **domain**.

```
register_intent skill_a:lights_off ──►  domain = "skill_a"
                                        intent  = "skill_a:lights_off"
register_intent skill_b:play_music ──►  domain = "skill_b"
                                        intent  = "skill_b:play_music"
```

At match time, every domain sub-container is evaluated against the utterance and the **global argmax** by confidence wins. There is no top-level router, no seed step, and no two-stage gating — the per-domain containers are small and keyword-rule-based, so parallel evaluation is essentially free.

A configurable short-circuit threshold (default `1.0`, i.e. exact match) on `DomainIntentContainer.shortcircuit_conf` lets a single sharp hit skip the remaining domains. For 100 domains, an exact match on the first one skips 99 evaluations.

Registration is now just:

```python
d = DomainIntentContainer()
d.register_domain_intent("home", lights_intent)
d.register_domain_intent("media", play_intent)

# no seeding needed
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

`PalavreadoPipeline` is structured around four small overrideable hooks so the domain subclass only differs where it must:

| Hook                                       | Purpose                              |
|--------------------------------------------|--------------------------------------|
| `_build_container()`                       | Create the per-language container    |
| `_add_intent(container, name, creator)`    | Register an intent                   |
| `_remove_intent(container, name)`          | Drop a single intent                 |
| `_remove_skill(container, skill_id)`       | Drop all intents for a skill         |

`DomainPalavreadoPipeline` overrides all four. Everything else — vocab handling, confidence tiers, session blacklists, manifest queries — is inherited unchanged.

---

## See also

- [DomainIntentContainer API](../palavreado/domain_engine.py) — the underlying engine
- [`ovos-plugin.md`](ovos-plugin.md) — the flat pipeline plugin
