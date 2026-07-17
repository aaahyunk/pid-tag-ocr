"""Core tests. Run: python -m pytest tests/  (or python tests/test_core.py)"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pid_tag_ocr import classify, HierarchicalGrammar, ISA, parse_instrument, evaluate, Item


def test_token_types():
    assert classify("PIT-384220").type == "instrument_tag"
    assert classify("50A-JN203-CW-841-527").type == "line_number"
    assert classify("P-384210").type == "equipment_tag"
    assert classify("50A").type == "nominal_pipe_size"
    assert classify("NOTE1").type == "annotation"
    assert classify("NOTE1").is_tag is False


def test_isa_soft_prior():
    isa = ISA()
    assert isa.valid_instrument_code("PIT")
    assert isa.valid_instrument_code("LSHH")
    assert isa.valid_instrument_code("PDI")
    # user's choice letters pass (project-defined meaning)
    assert isa.valid_instrument_code("MI")   # M = user's choice first letter
    p = parse_instrument("10-PIC-101A")
    assert p.first_letter == "P" and p.succeeding == "IC"
    assert p.loop == "101" and p.suffix == "A"


def test_isa_snap():
    G = HierarchicalGrammar()
    assert G.decode("LL").decoded == "LI"      # OCR misread of LI
    assert G.decode("PDL").decoded == "PDI"    # OCR misread of PDI
    assert G.decode("PIT-384220").confident


def test_never_fabricate():
    G = HierarchicalGrammar()
    d = G.decode("NOTE1")
    assert d.confident is False and d.layer == "reject"
    # unseen exotic token is not invented into a tag
    d2 = G.decode("QZXKW-999999")
    assert d2.confident is False


def test_reject_reason():
    G = HierarchicalGrammar()
    valid_reasons = {"sparse", "truncated", "variant_conflict", "unknown"}
    d = G.decode("QZXKW-999999")
    assert d.layer == "reject" and d.confident is False
    assert d.reject_reason in valid_reasons
    # confident decodes never carry a reject reason
    d2 = G.decode("PIT-384220")
    assert d2.confident and d2.reject_reason == ""


def test_mask_competition_direction():
    G = HierarchicalGrammar()
    # a misread with fewer digits must not be validated as-is
    d = G.decode("MKIWWM-841679")
    # either corrected toward more digits, or flagged; never silently accepted wrong
    assert d.decoded != "MKIWWM-841679" or not d.confident


def test_metrics_without_gold():
    items = [Item(raw="50A", decoded="50A", confident=True, gold=None)]
    r = evaluate(items)
    assert r.raw_char_acc is None          # no GT -> not fabricated
    assert r.human_review_rate == 0.0


def test_metrics_with_gold():
    items = [
        Item(raw="MKIWWM-841679", decoded="MK9WWM-841679", confident=True, gold="MK9WWM-841679"),
        Item(raw="NOTE1", decoded="NOTE1", confident=False, gold="NOTE1"),
    ]
    r = evaluate(items)
    assert r.exact_tag_match == 1.0
    assert r.human_review_rate == 0.5


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn(); print(f"  PASS {fn.__name__}"); passed += 1
        except AssertionError as e:
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
