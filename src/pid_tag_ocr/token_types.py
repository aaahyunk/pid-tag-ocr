"""
Token type classification.

Before decoding a string character-by-character, classify WHAT KIND of token it is.
Each type has its own slot grammar, so knowing the type shrinks the candidate space
dramatically -- far more robust than a single "digit ratio >= 15%" cutoff.

Types (per the project spec):
    instrument_tag    PIT-384220            ISA-5.1 functional identification + loop
    line_number       12"-VA-MQIEX-510275   pipe size + service + area + sequence
    equipment_tag     P-384210              equipment letter(s) + number
    drawing_reference  F4787-03             drawing / sheet reference
    nominal_pipe_size  50A, 15A             size designator
    annotation        NOTE 1, TYPE 1        free text (not a tag)

Classification uses STRUCTURE (mask + separators), not a hand-listed vocabulary,
so it generalizes across vendors. The mask abstracts a string to its letter/digit
shape:  MK9WWM-841679 -> AA#AAA-######.
"""
from __future__ import annotations
import re
from dataclasses import dataclass


def mask(t: str) -> str:
    """Abstract a token to letter/digit shape. 'PIT-384220' -> 'AAA-######'."""
    return "".join("#" if c.isdigit() else ("A" if c.isalpha() else c) for c in t)


# Structural signatures. Order matters: first match wins.
# Each entry: (type_name, predicate). Predicates read the raw token and its mask.
def _is_nominal_pipe_size(t: str, m: str) -> bool:
    # 50A, 15A, 100A, 2" -- number followed by a size unit letter or inch mark
    return bool(re.fullmatch(r'\d{1,4}[A-Z]', t)) or bool(re.fullmatch(r'\d{1,3}"', t))


def _is_line_number(t: str, m: str) -> bool:
    # size - service - area/system - sequence [- spec]
    # e.g. 12"-VA-MQIEX-510275, 50A-JN203-CW-841-527, 30-674-DW535-A1SEO-N
    # Signature: >= 3 hyphen-separated fields AND contains a long numeric run.
    if t.count("-") < 2:
        return False
    fields = t.split("-")
    if len(fields) < 3:
        return False
    has_size = bool(re.match(r'^\d{1,3}("|[A-Z])?$', fields[0]))
    has_long_num = any(len(re.sub(r'\D', '', f)) >= 3 for f in fields)
    return has_size and has_long_num


def _is_instrument_tag(t: str, m: str) -> bool:
    # 3-4 ISA functional letters + loop number, e.g. PIT-384220, PIT384220, FCV-101.
    # 3+ letters is the discriminator from equipment (which uses 1-2).
    return bool(re.fullmatch(r'[A-Z]{3,4}-?\d{2,6}[A-Z]?', t))


def _is_equipment_tag(t: str, m: str) -> bool:
    # [1-2 letters][-][digits], e.g. P-384210, TK-201, E-101.
    # Short letter prefix + hyphen = equipment/vessel/pump tag.
    return bool(re.fullmatch(r'[A-Z]{1,2}-\d{2,6}[A-Z]?', t))


def _is_drawing_reference(t: str, m: str) -> bool:
    # F4787-03, PID-341-0002, D-12345
    # letter(s)+digits then -digits, OR starts with known ref prefix
    if re.match(r'^(PID|DWG|DRG|REF)', t):
        return True
    return bool(re.fullmatch(r'[A-Z]\d{3,5}-\d{1,3}', t))


def _is_annotation(t: str, m: str) -> bool:
    # NOTE1, TYPE1, NOTE 1 -- 3+ letters then 1-2 trailing digits, no hyphen
    if "-" not in t and re.fullmatch(r'[A-Z]{3,}\d{1,2}', t):
        return True
    # slashes or stray quotes in the middle => prose/notation (but not a clean size like 2")
    if "/" in t:
        return True
    if '"' in t and not re.fullmatch(r'\d{1,3}"', t) and not _is_line_number(t, m):
        return True
    return False


# Ordered so the most specific structural signatures are tested first.
# line_number is tested before annotation so 12"-VA-MQIEX-510275 (which contains
# a quote) is recognized as a tag, not dropped as notation.
_RULES = [
    ("line_number",       _is_line_number),
    ("annotation",        _is_annotation),
    ("nominal_pipe_size", _is_nominal_pipe_size),
    ("drawing_reference", _is_drawing_reference),
    ("equipment_tag",     _is_equipment_tag),
    ("instrument_tag",    _is_instrument_tag),
]

# Types that are real tags (worth decoding). 'annotation' is not.
TAG_TYPES = {"instrument_tag", "instrument_code", "line_number", "equipment_tag",
             "drawing_reference", "nominal_pipe_size"}


@dataclass
class TokenType:
    token: str
    type: str            # one of the type names, or 'unknown'
    is_tag: bool         # True if worth decoding as a tag
    mask: str


def classify(token: str) -> TokenType:
    """Classify a raw OCR token by structure. Never raises."""
    t = token.strip().upper()
    m = mask(t)
    if len(t) < 2:
        return TokenType(t, "unknown", False, m)
    for name, pred in _RULES:
        try:
            if pred(t, m):
                return TokenType(t, name, name in TAG_TYPES, m)
        except re.error:
            continue
    # Pure-letter 2-4 char code sitting in an instrument bubble (LI, PDI, LSHH).
    # These carry no digits but are real instrument codes -> let ISA prior decode.
    if t.isalpha() and 2 <= len(t) <= 4:
        return TokenType(t, "instrument_code", True, m)

    # Fallback: has a digit and isn't pure prose -> unknown tag candidate
    d = sum(c.isdigit() for c in t)
    if d and not t.isalpha() and d / len(t) >= 0.15:
        return TokenType(t, "unknown", True, m)
    return TokenType(t, "unknown", False, m)


def is_tag_candidate(token: str) -> bool:
    """Convenience: should this token be decoded as a tag?"""
    return classify(token).is_tag
