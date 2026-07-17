"""
ISA-5.1-2024 standard, loaded as a SOFT PRIOR.

Truth-based: letter tables come from ANSI/ISA-5.1-2024 Table 4 (Identification
Letters), stored in data/isa_5_1.json. See ISO 10628 (PFD/P&ID diagram rules)
and IEC 62424 (P&ID data / control-function representation) for the broader
standards this fits into -- documented in standards/references.py.

CRITICAL -- this is a prior, not a gate:
    Real P&IDs deviate from ISA. Company abbreviations, project rules, custom
    suffixes, and OCR-preserved typos all occur. The standard is used to RANK and
    REPAIR candidates, never to reject a raw reading outright. Never Fabricate:
    if the standard and the data disagree and we cannot resolve confidently, we
    keep the raw string and flag it for human review.
"""
from __future__ import annotations
import json
import re
from functools import lru_cache
from importlib import resources
from dataclasses import dataclass, field


@lru_cache(maxsize=1)
def _load() -> dict:
    # data/isa_5_1.json ships with the package
    try:
        with resources.files("pid_tag_ocr.data").joinpath("isa_5_1.json").open(encoding="utf-8") as f:
            return json.load(f)
    except (ModuleNotFoundError, FileNotFoundError):
        # dev fallback: repo-relative path
        import os
        here = os.path.dirname(__file__)
        p = os.path.join(here, "..", "..", "..", "data", "isa_5_1.json")
        with open(os.path.abspath(p), encoding="utf-8") as f:
            return json.load(f)


class ISA:
    """Accessor over the ISA-5.1-2024 letter tables."""

    def __init__(self) -> None:
        d = _load()
        self.first_letter: dict = d["first_letter"]
        self.first_modifier: dict = d["first_letter_modifier"]
        self.readout: dict = d["succeeding_readout_passive"]
        self.output: dict = d["succeeding_output_active"]
        self.func_modifier: dict = d["function_modifier"]
        self.common_tags: dict = d["common_tags"]
        # combined succeeding-letter set (readout + output)
        self.succeeding = set(self.readout) | set(self.output)
        # letters that carry a project-defined ("User's Choice") meaning
        self.users_choice = {k for k, v in self.first_letter.items()
                             if v == "User's Choice"}

    # ---- membership tests (soft) ----
    def is_first_letter(self, c: str) -> bool:
        return c in self.first_letter

    def is_succeeding(self, c: str) -> bool:
        return c in self.succeeding

    def is_known_tag(self, code: str) -> bool:
        return code in self.common_tags

    def valid_instrument_code(self, code: str) -> bool:
        """
        Does `code` (the letter part, e.g. 'PDI', 'LSHH') follow ISA-5.1 structure?
        Soft check: first letter valid, optional modifier, succeeding letters valid,
        optional trailing function-modifier (H/L/HH/LL). User's Choice letters pass.
        """
        if not code or not code.isalpha() or not (1 <= len(code) <= 5):
            return False
        if code[0] not in self.first_letter:
            return False
        body = code[1:]
        # strip a trailing function modifier if present (HH, LL, H, L, ...)
        for suf in ("HH", "LL", "H", "L", "M", "C", "D", "O"):
            if body.endswith(suf) and len(body) > len(suf):
                body = body[: -len(suf)]
                break
        # optional first-letter modifier immediately after first letter
        if body and body[0] in self.first_modifier:
            body = body[1:]
        return all(c in self.succeeding or c in self.users_choice for c in body)

    def expand(self, code: str) -> list[str]:
        """Human-readable expansion of a tag code, e.g. 'PIT' -> ['Pressure','Indicate','Transmit']."""
        if code in self.common_tags:
            return [self.common_tags[code]]
        out = []
        if code and code[0] in self.first_letter:
            out.append(self.first_letter[code[0]])
        for c in code[1:]:
            if c in self.readout:
                out.append(self.readout[c])
            elif c in self.output:
                out.append(self.output[c])
            elif c in self.func_modifier:
                out.append(self.func_modifier[c])
        return out


# ---- Instrument slot grammar --------------------------------------------
# Conceptual structure (project spec):
#   [Measured Variable][Function][Modifier]-[Loop Number][Suffix]
#   PIT-384220
#   ||| └──── Loop number
#   ||└────── Transmitter
#   |└─────── Indicator
#   └──────── Pressure
_INSTR_RE = re.compile(
    r'^(?P<prefix>\d+-)?'
    r'(?P<letters>[A-Z]{1,5})'
    r'-?'
    r'(?P<loop>\d{1,6})'
    r'(?P<suffix>[A-Z])?$'
)


@dataclass
class InstrumentTag:
    raw: str
    prefix: str | None
    letters: str          # measured variable + function + modifier
    loop: str
    suffix: str | None
    first_letter: str
    succeeding: str
    expansion: list = field(default_factory=list)
    isa_valid: bool = False


def parse_instrument(token: str, isa: ISA | None = None) -> InstrumentTag | None:
    """Parse an instrument tag into ISA slots. Returns None if structure doesn't fit."""
    isa = isa or ISA()
    m = _INSTR_RE.match(token.strip().upper())
    if not m:
        return None
    letters = m.group("letters")
    return InstrumentTag(
        raw=token,
        prefix=(m.group("prefix") or None),
        letters=letters,
        loop=m.group("loop"),
        suffix=m.group("suffix"),
        first_letter=letters[0] if letters else "",
        succeeding=letters[1:],
        expansion=isa.expand(letters),
        isa_valid=isa.valid_instrument_code(letters),
    )
