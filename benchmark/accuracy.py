"""
Accuracy benchmark for palavreado.

Runs every labelled test case through IntentContainer and reports:
  - Per-intent precision / recall
  - Overall accuracy, false-positive rate, avg confidence
  - Confusion matrix for mismatches
  - Speed: median / p95 / max query latency

Usage:
    python -m benchmark.accuracy
    # or from repo root:
    uv run python benchmark/accuracy.py
"""
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from palavreado import IntentContainer
from palavreado.builder import IntentCreator
from benchmark.dataset import VOCAB, INTENTS, TEST_CASES, NO_MATCH_UTTERANCES


def build_container() -> IntentContainer:
    c = IntentContainer()
    for intent_name, slots in INTENTS.items():
        creator = IntentCreator(intent_name)
        for slot in slots["required"]:
            creator.require(slot, VOCAB.get(slot, []))
        for slot in slots["optional"]:
            creator.optionally(slot, VOCAB.get(slot, []))
        c.add_intent(creator)
    return c


def run():
    container = build_container()

    cases = list(TEST_CASES) + [(u, None) for u in NO_MATCH_UTTERANCES]
    match_n   = sum(1 for _, e in cases if e is not None)
    nomatch_n = len(cases) - match_n

    results, latencies = [], []
    for utt, expected in cases:
        t0 = time.perf_counter()
        r  = container.calc_intent(utt)
        latencies.append((time.perf_counter() - t0) * 1000)
        predicted = r.get("name") if r else None
        conf      = r.get("conf", 0.0) if r else 0.0
        results.append((utt, expected, predicted, conf))

    # ── aggregate ──────────────────────────────────────────────────────────
    total = len(cases)
    tp = fp = fn = tn = 0
    per_tp = defaultdict(int)
    per_fn = defaultdict(int)
    per_fp = defaultdict(int)
    wrong  = []

    for utt, expected, predicted, conf in results:
        if expected is not None:
            if predicted == expected:
                tp += 1; per_tp[expected] += 1
            else:
                fn += 1; per_fn[expected] += 1
                if predicted is not None:
                    fp += 1; per_fp[predicted] += 1
                wrong.append((utt, expected, predicted, conf))
        else:
            if predicted is not None:
                fp += 1; per_fp[predicted] += 1
                wrong.append((utt, expected, predicted, conf))
            else:
                tn += 1

    accuracy  = (tp + tn) / total
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / match_n   if match_n   else 0.0
    f1        = 2*precision*recall / (precision+recall) if (precision+recall) else 0.0
    fp_rate   = fp / nomatch_n if nomatch_n else 0.0

    lat_s = sorted(latencies)
    print(f"\n{'='*60}")
    print(f"  Accuracy benchmark  —  palavreado")
    print(f"{'='*60}")
    print(f"  Total cases     : {total}  ({match_n} match, {nomatch_n} no-match)")
    print(f"  Correct         : {tp+tn}/{total}  ({accuracy:.1%})")
    print(f"  Precision       : {precision:.1%}")
    print(f"  Recall          : {recall:.1%}")
    print(f"  F1              : {f1:.3f}")
    print(f"  True negatives  : {tn}/{nomatch_n}  ({tn/nomatch_n:.1%} of no-match cases correctly returned nothing)")
    print(f"  False positives : {fp}/{nomatch_n}  ({fp_rate:.1%} of no-match cases)")
    print(f"  False negatives : {fn}/{match_n}  ({fn/match_n:.1%} of match cases)")
    print(f"\n  Latency  median={statistics.median(latencies):.2f}ms  "
          f"p95={lat_s[int(len(lat_s)*.95)]:.2f}ms  "
          f"max={lat_s[-1]:.2f}ms")

    print(f"\n  {'Intent':<24} {'TP':>4} {'FN':>4} {'Recall':>8}  {'FP':>4}")
    print(f"  {'-'*50}")
    for name in sorted(INTENTS):
        tp_ = per_tp[name]; fn_ = per_fn[name]; fp_ = per_fp[name]
        rec = tp_ / (tp_ + fn_) if (tp_ + fn_) else 0.0
        flag = " !" if rec < 1.0 or fp_ > 0 else ""
        print(f"  {name:<24} {tp_:>4} {fn_:>4} {rec:>7.0%}  {fp_:>4}{flag}")

    if wrong:
        print(f"\n  Mismatches ({len(wrong)}):")
        for utt, exp, pred, conf in wrong:
            print(f"    [{exp or '—'} → {pred or '—'}] (conf={conf:.2f})  \"{utt}\"")


if __name__ == "__main__":
    run()
