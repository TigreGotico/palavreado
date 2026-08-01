# Context Gating

Context gating lets you make intents conditional on named boolean flags.  An intent can be required to have certain contexts active before it fires, or suppressed whenever certain contexts are active.

All context state lives inside the `IntentContainer` instance.  Contexts are per-intent. The same context name on different intents is tracked independently.

---

## Concepts

| Concept | Stored in | Meaning |
|---|---|---|
| **Active context** | `container.available_contexts[intent][context]` | A named flag that is currently set for an intent |
| **Required context** | `container.required_contexts[intent]` | The intent will not fire if this context is not active |
| **Excluded context** | `container.excluded_contexts[intent]` | The intent will not fire if this context is active |

The gating check runs in `_filter` (`palavreado/__init__.py:227`) at the start of every `calc_intents` call.

---

## `set_context` / `unset_context`

Manage the active state of a context for an intent.

```python
container.set_context(intent_name: str, context_name: str, context_val: object = None)
container.unset_context(intent_name: str, context_name: str)
```

`context_val` is stored (`available_contexts[intent_name][context_name] = context_val`) but the matching logic only checks **presence or absence** of the key. The value is not evaluated.

---

## `require_context` / `unrequire_context`

Gate an intent so it only fires when a context is active.

```python
container.require_context(intent_name: str, context_name: str)
container.unrequire_context(intent_name: str, context_name: str)
```

Multiple requirements can be added.  All required contexts must be active simultaneously for the intent to fire.

**Check (`palavreado/__init__.py:239`):**

```python
if any(c not in active for c in contexts):
    excluded.append(intent_name)
```

---

## `exclude_context` / `unexclude_context`

Suppress an intent while a context is active.

```python
container.exclude_context(intent_name: str, context_name: str)
container.unexclude_context(intent_name: str, context_name: str)
```

Multiple excluded contexts can be added.  The intent is suppressed if **any** excluded context is currently active.

**Check (`palavreado/__init__.py:244`):**

```python
if any(c in active for c in contexts):
    excluded.append(intent_name)
```

---

## Worked examples

### Example 1: Intent that only fires in a specific mode

A `"lights_off"` intent should only be available when the lights system reports that lights are available.

```python
from palavreado import IntentContainer, IntentCreator

c = IntentContainer()
c.add_intent(
    IntentCreator("lights_off")
    .require("off",   ["off", "disable"])
    .require("light", ["light", "lights"])
)

# Gate the intent on lights_active context
c.require_context("lights_off", "lights_active")

# Without setting the context, intent is suppressed
result = c.calc_intent("turn off the lights")
print(result["name"])   # None

# Activate the context
c.set_context("lights_off", "lights_active")

result = c.calc_intent("turn off the lights")
print(result["name"])   # lights_off

# Deactivate again
c.unset_context("lights_off", "lights_active")

result = c.calc_intent("turn off the lights")
print(result["name"])   # None
```

### Example 2: Intent suppressed when already in a state

A `"lights_off"` intent should not fire if the lights are already off.

```python
c.exclude_context("lights_off", "lights_already_off")

# Lights are on, intent can fire
result = c.calc_intent("turn off the lights")
print(result["name"])   # lights_off

# Lights have just been turned off, suppress the intent
c.set_context("lights_off", "lights_already_off")

result = c.calc_intent("turn off the lights")
print(result["name"])   # None (suppressed by excluded context)

# Lights are turned on again
c.unset_context("lights_off", "lights_already_off")
```

### Example 3: Multiple required contexts (all must be active)

```python
c.require_context("secure_command", "authenticated")
c.require_context("secure_command", "admin_mode")

c.set_context("secure_command", "authenticated")
# admin_mode not set → intent still suppressed

c.set_context("secure_command", "admin_mode")
# Both set → intent can now fire
result = c.calc_intent("run the secure command")
```

### Example 4: Required and excluded together

An intent that should fire only during a shopping session but not if the user is in checkout:

```python
c.require_context("add_item", "shopping_session")
c.exclude_context("add_item", "checkout_active")

c.set_context("add_item", "shopping_session")
# checkout_active is not set → intent fires
result = c.calc_intent("add milk to the list")
print(result["name"])   # add_item

c.set_context("add_item", "checkout_active")
# Now excluded
result = c.calc_intent("add milk to the list")
print(result["name"])   # None
```

---

## Interaction with `calc_intents`

Context filtering happens before any keyword matching.  Excluded intents are not evaluated at all. They do not appear in `calc_intents` results and do not affect `calc_intent` tie-breaking.

The filter result is a list of intent names to skip:

```python
excluded = self._filter(query)
# ...
for intent_name, intent in self.intents.items():
    if intent_name in excluded or not intent["required"]:
        continue
    # ... keyword matching
```

`palavreado/__init__.py:321`

---

## Notes

- Contexts are stored per intent, not globally.  Setting `"lights_active"` for `"lights_off"` has no effect on `"lights_on"`.
- Context values (the third argument to `set_context`) are stored but have no effect on matching.  They are available to the caller via `container.available_contexts[intent_name][context_name]` if needed.
- There is no persistence. All context state is in-memory and resets when the container is garbage-collected.
- In the OVOS plugin (`PalavreadoPipeline`), session blacklisting is handled separately via `sess.blacklisted_intents` / `sess.blacklisted_skills` in `_calc_palavreado_intent` (`palavreado/opm.py:299`), not via this context system.

---
[← Normalisation](normalisation.md) · [Home](index.md) · [OVOS Plugin →](ovos-plugin.md)
