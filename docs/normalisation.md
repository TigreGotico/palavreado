# Normalisation

All text in palavreado, both training samples and inference queries, goes through a normalisation pipeline before any comparison is made. This lets matching tolerate common surface variations and removes the need for the caller to pre-clean strings.

The normalisation code lives in `palavreado/bracket_expansion.py`.

---

## When normalisation runs

| Point | Function | Applied to |
|---|---|---|
| Intent registration | `normalize_example` (`bracket_expansion.py:125`) | Each sample in `required` and `optional` slots |
| Inference (matching) | `normalize_utterance` (`bracket_expansion.py:115`) | The query string at the start of `calc_intents` |
| Lemmatization at match time | `lemmatize` (`bracket_expansion.py:137`) | Individual tokens during `_match` and `get_utterance_remainder` |

As a result, the caller and the skill developer do not need to worry about apostrophe styles, extra whitespace, or plural forms. Palavreado resolves all of them to the same canonical form on both ends of the comparison.

---

## Step 1: Apostrophe normalisation

`palavreado/bracket_expansion.py:85`

```python
def drop_apostrophes(text: str) -> str:
```

Replaces apostrophes and apostrophe-like Unicode characters with a **space** (not an empty string).  Using a space rather than deletion preserves word boundaries so that `"it's"` → `"it s"` and both sides of a match decompose the same way.

### Covered Unicode code points

| Glyph | Code point | Name |
|---|---|---|
| `'` | U+0027 | ASCII apostrophe |
| `'` | U+2019 | RIGHT SINGLE QUOTATION MARK |
| `'` | U+2018 | LEFT SINGLE QUOTATION MARK |
| `ʼ` | U+02BC | MODIFIER LETTER APOSTROPHE |
| `ʹ` | U+02B9 | MODIFIER LETTER PRIME |
| grave accent | U+0060 | GRAVE ACCENT (backtick) |
| `´` | U+00B4 | ACUTE ACCENT |
| `＇` | U+FF07 | FULLWIDTH APOSTROPHE |

**Effect on contractions:**

| Input | After `drop_apostrophes` |
|---|---|
| `"it's"` | `"it s"` |
| `"don't"` | `"don t"` |
| `"I'm"` | `"I m"` |
| `"what's"` | `"what s"` |

---

## Step 2: Whitespace collapsing

`palavreado/bracket_expansion.py:80`

```python
def normalize_whitespace(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()
```

All runs of whitespace characters (including `\t`, `\n`, `\r`, multiple spaces, and the spaces introduced by apostrophe replacement) are collapsed to a single space, and leading/trailing whitespace is stripped.

---

## `normalize_utterance` vs `normalize_example`

```python
def normalize_utterance(text: str) -> str:
    text = drop_apostrophes(text)
    text = normalize_whitespace(text)
    return text

def normalize_example(example: str) -> str:
    text = clean_braces(translate_padatious(example))
    text = drop_apostrophes(text)
    text = normalize_whitespace(text)
    return text
```

`normalize_example` additionally:

1. **Cleans double braces** (`clean_braces`, `bracket_expansion.py:61`): `{{entity}}` → `{entity}`.
2. **Translates Padatious `:0` wildcards** (`translate_padatious`, `bracket_expansion.py:67`): `:0` tokens become `{word0:word}` placeholders for compatibility with Padatious-style training data.

`normalize_utterance` skips these steps because inference queries are plain text with no template syntax.

---

## Step 3: Lemmatization

`palavreado/bracket_expansion.py:137`

```python
def lemmatize(word: str) -> str:
```

Produces a canonical stem of a word for matching only. Palavreado never returns the stemmed form to the caller. It uses the stem internally during token-level comparison.

### Algorithm

1. Replace all apostrophe variants (same set as above, using a compiled regex `_APOS_RE`) with a space, strip, and lowercase.
2. If the resulting word is longer than 2 characters, ends with `"s"`, and does **not** end with `"ss"`: strip the trailing `"s"`.

```python
_APOS_RE = re.compile(r"['’‘ʼʹ`´＇]")

def lemmatize(word: str) -> str:
    word = _APOS_RE.sub(" ", word).strip().lower()
    if len(word) > 2 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word
```

### Examples

| Input | `lemmatize` output |
|---|---|
| `"lights"` | `"light"` |
| `"songs"` | `"song"` |
| `"it's"` | `"it"` (apostrophe split → `"it"` after strip) |
| `"class"` | `"class"` (ends in `"ss"`, not stripped) |
| `"bus"` | `"bu"` (3 chars, ends in `s` not `ss`, **stripped**) |
| `"as"` | `"as"` (2 chars, not stripped) |

### Language-agnostic design

The lemmatizer intentionally uses no language model or dictionary. The single rule (strip trailing `s`) works as a heuristic for English plurals and gives acceptable results for many European languages. False positive stems (for example `"bus"` to `"bu"`) do not cause incorrect matches. Both the training sample and the query token are stemmed the same way, so the same stem appears on both sides of the comparison.

---

## Matching flow diagram

```
Training sample: "lights"
  normalize_example → "lights"
  (stored)

Query: "turn off the lights"
  normalize_utterance → "turn off the lights"
  word_tokenize       → ["turn", "off", "the", "lights"]
  lemmatize each      → ["turn", "off", "the", "light"]
  query_lemmas (set)  → {"turn", "off", "the", "light"}

Keyword sample: "light"
  lemmatize → "light"

  "light" ∈ query_lemmas → MATCH
```

The same lemmatization runs on both sides, so `"lights"` (query) and `"light"` (training sample) both reduce to `"light"` and match.

---

## Bracket/pipe expansion (training time only)

`palavreado/bracket_expansion.py:17`

```python
def expand_parentheses(sent: str) -> list[str]:
```

Called during `expand_samples` (and therefore during `IntentCreator.require` / `optionally`), this expands template strings into all possible combinations before they are stored.

| Syntax | Meaning | Example |
|---|---|---|
| `(a\|b)` | Alternation | `"(turn\|switch) on"` → `["turn on", "switch on"]` |
| `[word]` | Optional | `"lights [please]"` → `["lights", "lights please"]` |
| Nested | Both combined | `"(turn\|switch) [the] lights"` → 4 expansions |

**Implementation:** `[optional]` sections are first rewritten to `(optional|)` (empty branch = absent), then the recursive Cartesian product of all `(a|b)` groups is computed.  Internal multiple spaces left by the empty branch are collapsed.

Expansion happens at registration time, not at match time.  The expanded list is what gets normalised and stored.

---
[← Confidence Scoring](confidence.md) · [Home](index.md) · [Context Gating →](context-gating.md)
