# pid_tag_ocr

**Neuro-symbolic P&ID tag decoding.** A hierarchical grammar
(ISA-5.1 standard → vendor → project → drawing) is applied to OCR detections, with a
Never-Fabricate confidence router. CPU-only, pure standard library at runtime.

This package does **not** run OCR or grammar induction. Detection happens upstream
(EasyOCR, GPU) and produces cache CSVs. Grammar is induced **offline** and stored as
CSV dictionaries. Here we **read** the dictionaries and **apply** them to a new
drawing to measure generalization — fast, on a laptop.

---

## Why hierarchical

Pure data-induced grammar fails on unseen vendors (a completely new shipyard scored
~30% in holdout, because tag formats differ per vendor). Real P&IDs follow published
standards, so we layer standard knowledge under the induced grammar:

```
L1  Standard dictionary      ISA-5.1-2024 / ISO 10628 / IEC 62424   (soft prior)
L2  Vendor tag grammar        induced per vendor            (data/grammar/)
L3  Project emergent grammar  induced across vendors        (data/grammar/)
L4  Drawing repetition        within-drawing self-supervision (runtime)
```

Priority: exact vocab (L4/L3/L2) → slot repair → ISA prior (L1) → **reject**.
The standard is a *soft prior*, never a hard gate: company abbreviations, project
rules, and OCR-preserved typos all occur. If no layer resolves a token confidently,
the raw string is kept and flagged for human review. **Never Fabricate.**

---

## Install

```bash
pip install -e .          # editable, for development in VS Code
```

No GPU, no heavy deps. `data/isa_5_1.json` (ISA-5.1-2024 Table 4) and
`data/grammar/*.csv` ship with the package.

---

## Use

### Validate a new drawing (generalization test)

```bash
python -m pid_tag_ocr.validate --cache path/to/new_drawing.csv
# optional ground truth for full accuracy metrics:
python -m pid_tag_ocr.validate --cache new.csv --gold gold.csv --vendor V03 --out result.json
```

Cache CSV schema (from the detection stage): `x,y,w,h,rot,conf,raw`
Gold CSV schema (optional): `raw,gold`

### As a library

```python
from pid_tag_ocr import HierarchicalGrammar, classify

G = HierarchicalGrammar()
G.decode("MKIWWM-841679").decoded   # -> "MK9WWM-841679"  (cross-mask repair)
G.decode("LL").decoded              # -> "LI"             (ISA snap)
G.decode("NOTE1").confident         # -> False            (flagged, not invented)
classify("12\"-VA-MQIEX-510275").type   # -> "line_number"
```

---

## Rebuild the grammar dictionaries

When you have new detection caches, rebuild offline (mask competition runs here):

```bash
python build_grammar.py --cache path/to/cache_dir --out data/grammar
```

Mask competition encodes the project's key finding: OCR misreads digits as letters
(`9→I`, `0→O`), rarely the reverse. When two masks differ only in letter↔digit, the
one with **more digits** is the true one — so `AA#AAA-######` (MK9WWM) beats
`AAAAAA-######` (MKIWWM), even when the misread is more frequent. Rejected masks
never enter the shipped dictionary.

---

## Token types

Strings are classified by **structure** (not a hand vocabulary) before decoding, so
each type gets its own slot grammar:

| type | example | slots |
|------|---------|-------|
| `instrument_tag` | `PIT-384220` | `[Measured Var][Function][Modifier]-[Loop][Suffix]` |
| `line_number` | `12"-VA-MQIEX-510275` | `[Pipe Size]-[Service]-[Area]-[Sequence]-[Spec]` |
| `equipment_tag` | `P-384210` | `[Letter(s)]-[Number]` |
| `drawing_reference` | `F4787-03` | `[Ref]-[Sheet]` |
| `nominal_pipe_size` | `50A` | `[Size][Unit]` |
| `annotation` | `NOTE1` | (not a tag) |

Instrument slots follow ISA-5.1-2024 Table 4 (`parse_instrument`):

```
PIT-384220
│││  └──── Loop number
││└────── Transmit   (T)
│└─────── Indicate   (I)
└──────── Pressure   (P, first letter)
```

---

## Metrics

Six metrics (`pid_tag_ocr.metrics`):

1. **Raw OCR Character Accuracy** — OCR output vs GT (char level)
2. **Grammar-constrained Character Accuracy** — decoded output vs GT
3. **Exact Tag Match** — whole-tag equality
4. **Auto-approval Precision** — of auto-approved tokens, fraction correct
5. **Rule-violation Detection Rate** — of GT-wrong tokens, fraction corrected or flagged
6. **Human Review Rate** — fraction routed to a human

Accuracy metrics require ground truth; without it they report `N/A` (never
fabricated). The operational metrics (auto-approval, review rate) work without GT.

The key claim is metric 1 vs 2: the neural OCR classifier does **not** improve, but
domain constraints raise the **final decoded** accuracy — what matters industrially.

---

## Standards (truth-based)

- **ANSI/ISA-5.1-2024**, *Instrumentation and Control – Symbols and Identification*
  — Table 4 identification letters → `data/isa_5_1.json` (L1 for instrument tags).
- **ISO 10628**, PFD/P&ID diagram rules — motivates the line-number slot model.
- **IEC 62424**, P&ID control-function representation / data exchange — justifies
  structured extraction toward machine-readable output.

See `src/pid_tag_ocr/standards/references.py`. All three are soft priors.

---

## Layout

```
pid_tag_ocr/
├── pyproject.toml
├── build_grammar.py            # offline: caches -> grammar CSVs (mask competition)
├── data/
│   ├── isa_5_1.json            # ISA-5.1-2024 Table 4
│   └── grammar/                # induced dictionaries (read at runtime)
│       ├── grammar_masks.csv
│       ├── grammar_slots.csv
│       ├── grammar_vocab.csv
│       └── grammar_conf.csv
├── src/pid_tag_ocr/
│   ├── token_types.py          # structural token classifier
│   ├── grammar.py              # 4-layer hierarchical decoder
│   ├── metrics.py              # six metrics + confidence
│   ├── validate.py             # CLI: apply to a new drawing
│   └── standards/
│       ├── isa.py              # ISA-5.1 loader + instrument slot parser
│       └── references.py       # ISO 10628 / IEC 62424 documentation
└── tests/test_core.py
```
