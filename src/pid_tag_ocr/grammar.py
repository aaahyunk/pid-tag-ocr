"""
Four-layer hierarchical grammar.

    L1  Standard dictionary      ISA-5.1 / ISO 10628 / IEC 62424   (standards/)
    L2  Vendor tag grammar       per-vendor induced grammar        (data/grammar/)
    L3  Project emergent grammar all-vendor induced grammar        (data/grammar/)
    L4  Drawing repetition       within-drawing self-supervision   (runtime, per file)

Grammar is NOT induced at runtime. It is read from CSV dictionaries produced offline
(build_grammar.py). At validation time we load the dictionaries and apply them to a
NEW drawing to measure generalization.

Decode priority (lower layer wins; standard is fallback):
    exact vocab (L4/L3/L2)  >  slot repair (L2/L3)  >  ISA prior (L1)  >  reject

Never Fabricate: if no layer resolves a token confidently, return the raw string
with confident=False so the router sends it to human review.
"""
from __future__ import annotations
import csv
import itertools
import collections
from dataclasses import dataclass, field
from importlib import resources
from difflib import SequenceMatcher

from .token_types import mask, classify
from .standards.isa import ISA, parse_instrument


# ----------------------------------------------------------------------------
def _open_data(name: str):
    """Open a CSV shipped under data/grammar/, with a dev-path fallback."""
    try:
        return resources.files("pid_tag_ocr.data.grammar").joinpath(name).open(
            encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError):
        import os
        here = os.path.dirname(__file__)
        p = os.path.join(here, "..", "..", "data", "grammar", name)
        return open(os.path.abspath(p), encoding="utf-8")


@dataclass
class Decoded:
    raw: str
    decoded: str
    layer: str            # isa | vocab | vendor | project | drawing | reject
    confident: bool
    token_type: str = ""
    note: str = ""


class HierarchicalGrammar:
    """
    Loads the CSV grammar dictionaries and decodes tokens against the 4 layers.

    The heavy lifting (mask competition, confusion learning) already happened
    offline. Here we only READ the resulting slot/vocab tables and apply them.
    """

    def __init__(self, isa: ISA | None = None):
        self.isa = isa or ISA()
        # L2/L3: per-vendor slot tables and vocab
        self.slots: dict[tuple[str, str], list[set]] = {}   # (vendor, mask) -> [chars]
        self.vocab: dict[str, collections.Counter] = collections.defaultdict(
            collections.Counter)                            # vendor -> Counter(tag)
        self.masks_by_vendor: dict[str, set] = collections.defaultdict(set)
        self.conf: dict[str, str] = {}                      # misread -> true chars
        self._load()

    def _load(self) -> None:
        # slots
        with _open_data("grammar_slots.csv") as f:
            for r in csv.DictReader(f):
                v, m, i = r["vendor"], r["mask"], int(r["slot_index"])
                key = (v, m)
                if key not in self.slots:
                    self.slots[key] = [set() for _ in range(len(m))]
                self.slots[key][i] = set(r["allowed_chars"])
                self.masks_by_vendor[v].add(m)
        # vocab
        with _open_data("grammar_vocab.csv") as f:
            for r in csv.DictReader(f):
                self.vocab[r["vendor"]][r["tag"]] = int(r["freq"])
        # confusion (font-physics seed)
        with _open_data("grammar_conf.csv") as f:
            for r in csv.DictReader(f):
                self.conf[r["misread_char"]] = r["true_chars"]

    # ---- vendor scope ----
    @property
    def vendors(self) -> list[str]:
        return sorted(self.masks_by_vendor)

    def _vocab_all(self) -> collections.Counter:
        out = collections.Counter()
        for c in self.vocab.values():
            out.update(c)
        return out

    # ---- L2/L3 slot validity ----
    def _valid_in(self, t: str, vendor: str) -> bool:
        key = (vendor, mask(t))
        sl = self.slots.get(key)
        if not sl or len(sl) != len(t):
            return False
        return all(t[i] in sl[i] for i in range(len(t)))

    def valid(self, t: str, vendor: str | None = None) -> bool:
        vends = [vendor] if vendor else self.vendors
        return any(self._valid_in(t, v) for v in vends)

    # ---- slot repair against a known mask ----
    def _repair_slots(self, raw: str, vendor: str, max_edits: int = 3):
        key = (vendor, mask(raw))
        sl = self.slots.get(key)
        if not sl or len(sl) != len(raw):
            return None
        bad = [i for i in range(len(raw)) if raw[i] not in sl[i]]
        if not bad or len(bad) > max_edits:
            return None if bad else raw
        opts = []
        for i in bad:
            reach = set(self.conf.get(raw[i], "")) | {raw[i]}
            ok = [c for c in reach if c in sl[i]]
            if not ok:
                return None
            opts.append((i, ok))
        cands = set()
        for pick in itertools.product(*[o for _, o in opts]):
            s = list(raw)
            for (i, _), c in zip(opts, pick):
                s[i] = c
            cands.add("".join(s))
        vall = self._vocab_all()
        hits = [c for c in cands if vall.get(c, 0) >= 2]
        if len(hits) == 1:
            return hits[0]
        if len(cands) == 1:
            return cands.pop()
        return None

    def _repair_cross_mask(self, raw: str, vendor: str, max_edits: int = 3):
        """
        raw's mask isn't a known grammar mask (likely a misread, e.g. AAAAAA-######
        for MKIWWM-...). Align to each known mask of this vendor that has the same
        length, substituting only confusable chars, and keep a candidate that:
          - matches the target mask, and
          - is slot-valid, and
          - is supported by observed vocab / context.
        """
        m = mask(raw)
        cands = set()
        for (v, gm), sl in self.slots.items():
            if v != vendor or len(gm) != len(raw) or gm == m:
                continue
            diff = [i for i in range(len(gm)) if gm[i] != m[i]]
            if not diff or len(diff) > max_edits:
                continue
            opts, feasible = [], True
            for i in diff:
                reach = set(self.conf.get(raw[i], "")) | {raw[i]}
                ok = [c for c in reach if c in sl[i]]
                if not ok:
                    feasible = False
                    break
                opts.append((i, ok))
            if not feasible:
                continue
            if any(raw[i] not in sl[i] for i in range(len(raw)) if i not in diff):
                continue
            for pick in itertools.product(*[o for _, o in opts]):
                s = list(raw)
                for (i, _), c in zip(opts, pick):
                    s[i] = c
                cd = "".join(s)
                if mask(cd) == gm:
                    cands.add(cd)
        if not cands:
            return None
        vall = self._vocab_all()
        # prefer a candidate that exists in vocab; else unique candidate
        hits = [c for c in cands if vall.get(c, 0) >= 1]
        if len(hits) == 1:
            return hits[0]
        if len(cands) == 1:
            return cands.pop()
        # tie-break by vocab frequency then string similarity
        best = max(cands, key=lambda c: (vall.get(c, 0),
                                         SequenceMatcher(None, c, raw).ratio()))
        return best if vall.get(best, 0) >= 1 else None

    # ---- decode one token through the hierarchy ----
    def decode(self, raw: str, vendor: str | None = None,
               drawing_vocab: collections.Counter | None = None) -> Decoded:
        raw = raw.strip().upper()
        tt = classify(raw)

        # L1 for bare instrument CODES (pure letters, e.g. 'LI', 'PDI', 'LSHH').
        # These sit inside instrument bubbles; ISA prior can snap OCR misreads
        # (LL->LI, PDL->PDI) even when the data never saw the correct code.
        if raw.isalpha() and 2 <= len(raw) <= 5:
            if raw in self.isa.common_tags:
                return Decoded(raw, raw, "isa", True, "instrument_code", "ISA known")
            for alt in self._confuse(raw, maxsub=2):
                if alt in self.isa.common_tags:
                    return Decoded(raw, alt, "isa", True, "instrument_code",
                                   "ISA snap")
            if self.isa.valid_instrument_code(raw):
                return Decoded(raw, raw, "isa", True, "instrument_code", "ISA form")

        # L1 for instrument tags: ISA prior can resolve letters the data never saw.
        if tt.type == "instrument_tag":
            parsed = parse_instrument(raw, self.isa)
            if parsed and parsed.isa_valid and parsed.letters in self.isa.common_tags:
                return Decoded(raw, raw, "isa", True, tt.type, "ISA known tag")
            # try snapping the letter part to a known ISA tag via confusion
            if parsed:
                for alt in self._confuse(parsed.letters, maxsub=2):
                    if alt in self.isa.common_tags:
                        fixed = raw.replace(parsed.letters, alt, 1)
                        return Decoded(raw, fixed, "isa", True, tt.type, "ISA snap")

        # L4: exact match in this drawing's own repeated tokens
        if drawing_vocab and drawing_vocab.get(raw, 0) >= 2:
            return Decoded(raw, raw, "drawing", True, tt.type, "drawing repeat")

        # L2/L3: exact vocab hit
        vends = [vendor] if vendor else self.vendors
        for v in vends:
            if self.vocab[v].get(raw, 0) >= 2:
                layer = "vendor" if vendor else "project"
                return Decoded(raw, raw, layer, True, tt.type, "vocab exact")

        # L2/L3: slot-valid as-is
        if self.valid(raw, vendor):
            return Decoded(raw, raw, "project" if not vendor else "vendor",
                           True, tt.type, "slot valid")

        # L2/L3: slot repair (raw's own mask is known)
        for v in vends:
            fixed = self._repair_slots(raw, v)
            if fixed and fixed != raw:
                return Decoded(raw, fixed, "vendor" if vendor else "project",
                               True, tt.type, "slot repair")

        # L2/L3: cross-mask repair (raw's mask was rejected as a misread;
        # align it to a known winner mask by substituting confusable chars).
        for v in vends:
            fixed = self._repair_cross_mask(raw, v)
            if fixed and fixed != raw:
                return Decoded(raw, fixed, "vendor" if vendor else "project",
                               True, tt.type, "cross-mask repair")

        # L1 fallback for instrument letters that at least follow ISA form
        if tt.type == "instrument_tag":
            parsed = parse_instrument(raw, self.isa)
            if parsed and parsed.isa_valid:
                return Decoded(raw, raw, "isa", True, tt.type, "ISA form ok")

        # Never Fabricate
        return Decoded(raw, raw, "reject", False, tt.type, "no confident resolution")

    def _confuse(self, s: str, maxsub: int = 2, cap: int = 1500) -> set:
        out = {s}
        for _ in range(maxsub):
            new = set()
            for v in out:
                for i, ch in enumerate(v):
                    for a in self.conf.get(ch, ""):
                        new.add(v[:i] + a + v[i + 1:])
                if len(new) + len(out) > cap:
                    break
            out |= new
            if len(out) > cap:
                break
        return out
