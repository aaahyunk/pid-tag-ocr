"""
Offline grammar builder.

Reads detection-cache CSVs (x,y,w,h,rot,conf,raw) and writes the four grammar
dictionaries under data/grammar/. Run this ONCE when you have new cached drawings;
the package then reads the dictionaries at validation time without re-inducing.

    python build_grammar.py --cache path/to/cache_dir --out data/grammar

Mask competition (the project's key finding) is applied HERE, at build time, so the
shipped dictionaries do not encode OCR misreads as valid grammar:
    OCR misreads digits as letters (9->I, 0->O), rarely the reverse.
    When two masks differ only in A<->#, the one with MORE digits is the true one.
"""
from __future__ import annotations
import os
import csv
import glob
import argparse
import collections

# allow running from repo root without install
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from pid_tag_ocr.token_types import mask, is_tag_candidate   # noqa: E402

CONF_SEED = {"I": "1", "1": "I", "O": "0", "0": "O", "S": "5", "5": "S",
             "Z": "2", "2": "Z", "B": "8", "8": "B", "G": "6", "6": "G",
             "L": "1", "D": "0", "A": "4", "4": "A"}
MIN_COMPETE_LEN = 5


def load_cache(cache_dir: str):
    """Return list of (vendor, raw) tag candidates from all cache CSVs."""
    rows = []
    for p in sorted(glob.glob(os.path.join(cache_dir, "*.csv"))):
        vendor = os.path.basename(p)[:3]
        with open(p, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                raw = r.get("raw", "").strip().upper()
                if is_tag_candidate(raw):
                    rows.append((vendor, raw))
    return rows


def compete(masks_freq: dict) -> dict:
    """Return {rejected_mask: winner_mask}. Digit-count decides; freq breaks ties."""
    def competes(m1, m2):
        if len(m1) != len(m2) or len(m1) < MIN_COMPETE_LEN:
            return None
        diff = [i for i in range(len(m1)) if m1[i] != m2[i]]
        if not diff:
            return None
        return diff if all({m1[i], m2[i]} == {"A", "#"} for i in diff) else None

    ndig = lambda m: m.count("#")
    rejected = {}
    ms = list(masks_freq)
    for i in range(len(ms)):
        for j in range(i + 1, len(ms)):
            if not competes(ms[i], ms[j]):
                continue
            a, b = ms[i], ms[j]
            if ndig(a) > ndig(b):
                win, lose = a, b
            elif ndig(b) > ndig(a):
                win, lose = b, a
            else:
                win, lose = (a, b) if masks_freq[a] >= masks_freq[b] else (b, a)
            rejected[lose] = win
    return rejected


def build(cache_dir: str, out_dir: str, min_support: int = 4) -> None:
    rows = load_cache(cache_dir)
    vtot = collections.Counter(v for v, _ in rows)
    big = max(vtot.values()) if vtot else 1
    print(f"[build] tag candidates: {len(rows)}  vendors: {dict(vtot)}")

    # per-vendor mask frequency
    mv = collections.Counter((v, mask(t)) for v, t in rows)

    # global mask competition (reject misread-derived masks)
    global_masks = collections.Counter(mask(t) for _, t in rows)
    rejected = compete(dict(global_masks))
    print(f"[build] rejected {len(rejected)} misread masks "
          f"(e.g. {list(rejected.items())[:3]})")

    os.makedirs(out_dir, exist_ok=True)

    # grammar_masks.csv
    with open(os.path.join(out_dir, "grammar_masks.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["mask", "vendor", "freq", "n_digits", "status", "beaten_by"])
        for (v, m), n in sorted(mv.items(), key=lambda z: -z[1]):
            if m in rejected:
                w.writerow([m, v, n, m.count("#"), "REJECTED", rejected[m]])
            else:
                w.writerow([m, v, n, m.count("#"), "ACCEPTED", ""])

    # grammar_slots.csv  (vendor-adaptive support; skip rejected masks)
    slots = collections.defaultdict(lambda: collections.defaultdict(set))
    for v, t in rows:
        m = mask(t)
        if m in rejected:
            continue
        thr = max(2, int(min_support * vtot[v] / big))
        if mv[(v, m)] >= thr:
            for i, ch in enumerate(t):
                slots[(v, m)][i].add(ch)
    with open(os.path.join(out_dir, "grammar_slots.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["vendor", "mask", "slot_index", "allowed_chars"])
        for (v, m), idx in sorted(slots.items()):
            for i in sorted(idx):
                w.writerow([v, m, i, "".join(sorted(idx[i]))])

    # grammar_vocab.csv  (only tokens whose mask survived)
    kept = {(v, m) for (v, m) in slots}
    vocab = collections.Counter((v, t) for v, t in rows if (v, mask(t)) in kept)
    with open(os.path.join(out_dir, "grammar_vocab.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["vendor", "tag", "freq"])
        for (v, t), n in vocab.most_common():
            w.writerow([v, t, n])

    # grammar_conf.csv  (learn direction from rejected<->winner alignment; seed fallback)
    conf = collections.defaultdict(set)
    for a, b in CONF_SEED.items():
        conf[a] |= set(b)
    by_mask = collections.defaultdict(list)
    for _, t in rows:
        by_mask[mask(t)].append(t)
    for lose, win in rejected.items():
        diff = [i for i in range(len(lose)) if lose[i] != win[i]]
        for lt in by_mask.get(lose, []):
            for wt in by_mask.get(win, []):
                if len(wt) == len(lt) and all(
                        wt[i] == lt[i] for i in range(len(lt)) if i not in diff):
                    for i in diff:
                        conf[lt[i]].add(wt[i])
                    break
    with open(os.path.join(out_dir, "grammar_conf.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["misread_char", "true_chars"])
        for a, b in sorted(conf.items()):
            w.writerow([a, "".join(sorted(b))])

    for fn in ("grammar_masks", "grammar_slots", "grammar_vocab", "grammar_conf"):
        n = sum(1 for _ in open(os.path.join(out_dir, f"{fn}.csv"))) - 1
        print(f"[save] {fn}.csv  ({n} rows)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True, help="directory of detection-cache CSVs")
    ap.add_argument("--out", default="data/grammar", help="output dir for dictionaries")
    ap.add_argument("--min-support", type=int, default=4)
    args = ap.parse_args()
    build(args.cache, args.out, args.min_support)
