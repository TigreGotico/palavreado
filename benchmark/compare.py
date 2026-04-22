"""
Comparative accuracy + speed benchmark: palavreado vs Adapt.

Both engines are keyword-based parsers — they match utterances against
registered vocabulary (lists of words/phrases per slot) rather than
regex templates or neural patterns.  This benchmark uses the same keyword
vocabulary and intent definitions for both engines.

Usage
-----
    uv run python benchmark/compare.py
    # or, if adapt is on sys.path:
    PYTHONPATH=/path/to/ovos-adapt-pipeline-plugin python benchmark/compare.py
"""
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

# ensure palavreado's benchmark package is found before any installed one
sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmark.dataset import VOCAB, INTENTS, TEST_CASES, NO_MATCH_UTTERANCES


# ── shared helpers ─────────────────────────────────────────────────────────

def all_cases():
    return list(TEST_CASES) + [(u, None) for u in NO_MATCH_UTTERANCES]


def compute_metrics(results, cases):
    total     = len(cases)
    match_n   = sum(1 for _, e in cases if e is not None)
    nomatch_n = total - match_n
    tp = fp = fn = tn = 0
    per_tp = defaultdict(int); per_fn = defaultdict(int); per_fp = defaultdict(int)
    wrong = []
    for (predicted, conf), (utt, expected) in zip(results, cases):
        if expected is not None:
            if predicted == expected:
                tp += 1; per_tp[expected] += 1
            else:
                fn += 1; per_fn[expected] += 1
                wrong.append((utt, expected, predicted, conf))
        else:
            if predicted is not None:
                fp += 1; per_fp[predicted] += 1
                wrong.append((utt, expected, predicted, conf))
            else:
                tn += 1
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec  = tp / match_n   if match_n   else 0.0
    f1   = 2*prec*rec / (prec+rec) if (prec+rec) else 0.0
    return dict(
        accuracy=(tp+tn)/total, precision=prec, recall=rec, f1=f1,
        tp=tp, fp=fp, fn=fn, tn=tn,
        match_n=match_n, nomatch_n=nomatch_n,
        per_tp=per_tp, per_fn=per_fn, per_fp=per_fp, wrong=wrong,
    )


def print_report(label, m, latencies):
    s = sorted(latencies)
    print(f"\n{'='*66}")
    print(f"  {label}")
    print(f"{'='*66}")
    total = m["match_n"] + m["nomatch_n"]
    print(f"  Accuracy  : {m['accuracy']:.1%}  ({int(m['accuracy']*total)}/{total})")
    print(f"  Precision : {m['precision']:.1%}")
    print(f"  Recall    : {m['recall']:.1%}")
    print(f"  F1        : {m['f1']:.3f}")
    print(f"  FP        : {m['fp']} / {m['nomatch_n']}  ({m['fp']/m['nomatch_n']:.0%} of no-match)")
    print(f"  FN        : {m['fn']} / {m['match_n']}  ({m['fn']/m['match_n']:.0%} of match)")
    print(f"  Latency   : median={statistics.median(latencies):.2f}ms  "
          f"p95={s[int(len(s)*.95)]:.2f}ms  max={s[-1]:.2f}ms")

    issues = sorted(set(m["per_fn"]) | set(m["per_fp"]))
    if issues:
        print(f"\n  Per-intent (issues only):")
        for name in sorted(INTENTS):
            fn = m["per_fn"].get(name, 0)
            fp = m["per_fp"].get(name, 0)
            tp = m["per_tp"].get(name, 0)
            if fn or fp:
                rec = tp / (tp + fn) if (tp + fn) else 0.0
                print(f"    {name:<26}  recall={rec:.0%}  fn={fn}  fp={fp}")

    if m["wrong"]:
        print(f"\n  Mismatches ({len(m['wrong'])}):")
        for utt, exp, pred, conf in m["wrong"]:
            print(f"    [{exp or '—'} → {pred or '—'}] ({conf:.2f})  \"{utt}\"")


# ── engine runners ─────────────────────────────────────────────────────────

def run_palavreado(cases):
    from palavreado import IntentContainer
    from palavreado.builder import IntentCreator

    c = IntentContainer()
    for intent_name, slots in INTENTS.items():
        creator = IntentCreator(intent_name)
        for slot in slots["required"]:
            creator.require(slot, VOCAB.get(slot, []))
        for slot in slots["optional"]:
            creator.optionally(slot, VOCAB.get(slot, []))
        c.add_intent(creator)

    results, latencies = [], []
    for utt, _ in cases:
        t0 = time.perf_counter()
        r  = c.calc_intent(utt)
        latencies.append((time.perf_counter() - t0) * 1000)
        results.append((r.get("name") if r else None, r.get("conf", 0.0) if r else 0.0))

    m = compute_metrics(results, cases)
    print_report("palavreado  (keyword, no fuzz)", m, latencies)
    return m, statistics.median(latencies), statistics.mean(latencies)


def run_adapt(cases):
    adapt_path = "/home/miro/AgentWorkspaces/OpenVoiceOS/plugins-pipeline/ovos-adapt-pipeline-plugin"
    if adapt_path not in sys.path:
        sys.path.insert(0, adapt_path)

    try:
        from ovos_adapt.engine import IntentDeterminationEngine
        from ovos_adapt.intent import IntentBuilder
    except ImportError:
        print("\n  [SKIP] adapt not available — install ovos-adapt-pipeline-plugin")
        return None, None, None

    engine = IntentDeterminationEngine()

    # register vocabulary
    for entity_type, values in VOCAB.items():
        for value in values:
            engine.register_entity(value, entity_type)

    # register intents
    for intent_name, slots in INTENTS.items():
        builder = IntentBuilder(intent_name)
        for slot in slots["required"]:
            builder.require(slot)
        for slot in slots["optional"]:
            builder.optionally(slot)
        engine.register_intent_parser(builder.build())

    results, latencies = [], []
    for utt, _ in cases:
        t0 = time.perf_counter()
        intents = list(engine.determine_intent(utt, 100))
        latencies.append((time.perf_counter() - t0) * 1000)
        if intents:
            best = max(intents, key=lambda x: x.get("confidence", 0))
            conf = best.get("confidence", 0)
            name = best.get("intent_type") if conf > 0 else None
        else:
            name, conf = None, 0.0
        results.append((name, conf))

    m = compute_metrics(results, cases)
    print_report("adapt  (keyword, exact)", m, latencies)
    return m, statistics.median(latencies), statistics.mean(latencies)


# ── summary table ──────────────────────────────────────────────────────────

def summary(rows):
    print(f"\n\n{'─'*90}")
    print(f"  {'Engine':<32} {'Acc':>6} {'Prec':>6} {'Recall':>7} {'F1':>6}  {'TN/NM':>8}  {'FP':>4}  {'Median':>8}")
    print(f"{'─'*90}")
    for label, m, median_lat, mean_lat in rows:
        if m is None:
            print(f"  {label:<32}  (skipped)")
            continue
        tn_frac = f"{m['tn']}/{m['nomatch_n']}"
        print(f"  {label:<32} {m['accuracy']:>5.1%} {m['precision']:>5.1%} "
              f"{m['recall']:>6.1%} {m['f1']:>5.3f}  {tn_frac:>8}  {m['fp']:>4}  {median_lat:>6.2f}ms")
    print(f"{'─'*90}")
    print(f"  TN/NM = true negatives / total no-match cases (correctly returned nothing)")


# ── main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cases   = all_cases()
    match_n = sum(1 for _, e in cases if e is not None)
    print(f"\nDataset : {len(cases)} cases  ({match_n} match, {len(cases)-match_n} no-match)")
    print(f"Intents : {len(INTENTS)}")
    print(f"Vocab   : {sum(len(v) for v in VOCAB.values())} keyword samples across {len(VOCAB)} entity types")
    print(f"Note    : keyword parsers require the vocabulary word to appear in the utterance.")

    rows = []

    m, lat, mean_lat = run_palavreado(cases)
    rows.append(("palavreado", m, lat, mean_lat))

    m, lat, mean_lat = run_adapt(cases)
    rows.append(("adapt", m, lat, mean_lat))

    summary(rows)
