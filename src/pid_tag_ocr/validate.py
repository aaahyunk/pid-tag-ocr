"""
Validate the grammar dictionaries against a NEW drawing's detection cache.

This is the generalization test: grammar was built offline from other drawings;
here we apply it (no re-induction) to a drawing it has not seen and report the six
metrics plus per-layer contribution.

    python -m pid_tag_ocr.validate --cache new_drawing.csv [--gold gold.csv] [--vendor V03]

Cache CSV schema (from the detection stage):  x,y,w,h,rot,conf,raw
Optional gold CSV schema:                     raw,gold   (ground-truth tag per raw)
"""
from __future__ import annotations
import os
import csv
import json
import argparse
import collections

from .grammar import HierarchicalGrammar
from .token_types import classify, mask
from .metrics import Item, evaluate


def load_cache(path: str):
    with open(path, encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f)]


def load_gold(path: str) -> dict:
    g = {}
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            g[r["raw"].strip().upper()] = r["gold"].strip().upper()
    return g


def run(cache_path: str, gold_path: str | None = None,
        vendor: str | None = None) -> dict:
    G = HierarchicalGrammar()
    rows = load_cache(cache_path)
    gold = load_gold(gold_path) if gold_path else {}

    # infer vendor from filename if not given (V01_..., V02_..., etc.)
    if vendor is None:
        base = os.path.basename(cache_path)
        if base[:1] == "V" and base[1:3].isdigit():
            vendor = base[:3]

    # L4: this drawing's own repeated tokens (self-supervision)
    draw_vocab = collections.Counter(
        r["raw"].strip().upper() for r in rows
        if classify(r["raw"]).is_tag)

    items, records = [], []
    layer_count = collections.Counter()
    type_count = collections.Counter()

    for r in rows:
        raw = r["raw"].strip().upper()
        tt = classify(raw)
        type_count[tt.type] += 1
        if not tt.is_tag:
            continue
        d = G.decode(raw, vendor=vendor, drawing_vocab=draw_vocab)
        layer_count[d.layer] += 1
        g = gold.get(raw)
        items.append(Item(raw=raw, decoded=d.decoded,
                          confident=d.confident, gold=g))
        records.append({
            "raw": raw, "decoded": d.decoded, "layer": d.layer,
            "type": d.token_type, "confident": int(d.confident),
            "note": d.note, "gold": g or "",
        })

    report = evaluate(items)

    # digit-direction sanity (project's key invariant): corrections should ADD digits
    def ndig(s):
        return sum(c.isdigit() for c in s)
    reps = [rec for rec in records if rec["raw"] != rec["decoded"]]
    up = sum(1 for rec in reps if ndig(rec["decoded"]) > ndig(rec["raw"]))
    down = sum(1 for rec in reps
               if ndig(rec["decoded"]) < ndig(rec["raw"])
               and not rec["decoded"].isalpha())

    return {
        "cache": os.path.basename(cache_path),
        "vendor": vendor,
        "n_detections": len(rows),
        "n_tag_candidates": len(items),
        "token_types": dict(type_count),
        "layer_contribution": dict(layer_count),
        "corrections": {"total": len(reps), "digits_up": up, "digits_down": down},
        "metrics": report.as_dict(),
        "metrics_pretty": report.pretty(),
        "records": records,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True, help="detection cache CSV of the NEW drawing")
    ap.add_argument("--gold", help="optional ground-truth CSV (raw,gold)")
    ap.add_argument("--vendor", help="vendor code (default: infer from filename)")
    ap.add_argument("--out", help="write full JSON result here")
    args = ap.parse_args()

    res = run(args.cache, args.gold, args.vendor)

    print(f"cache      : {res['cache']}")
    print(f"vendor     : {res['vendor']}")
    print(f"detections : {res['n_detections']}  tag candidates: {res['n_tag_candidates']}")
    print(f"types      : {res['token_types']}")
    print(f"layers     : {res['layer_contribution']}")
    c = res["corrections"]
    arrow = "OK" if c["digits_down"] == 0 else "CHECK"
    print(f"corrections: {c['total']}  (digits up {c['digits_up']} / down {c['digits_down']})  [{arrow}]")
    print("-" * 52)
    print(res["metrics_pretty"])

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print(f"\n[saved] {args.out}")


if __name__ == "__main__":
    main()
