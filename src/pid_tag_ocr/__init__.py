"""
pid_tag_ocr -- neuro-symbolic P&ID tag decoding.

Hierarchical grammar (ISA-5.1 standard -> vendor -> project -> drawing) applied to
OCR detections, with a Never-Fabricate confidence router. Grammar is built offline
from detection caches (build_grammar.py) and read from CSV dictionaries at runtime.
"""
from .grammar import HierarchicalGrammar, Decoded
from .token_types import classify, is_tag_candidate, TokenType, mask
from .standards.isa import ISA, parse_instrument, InstrumentTag
from .metrics import Item, Report, evaluate

__version__ = "0.1.0"

__all__ = [
    "HierarchicalGrammar", "Decoded",
    "classify", "is_tag_candidate", "TokenType", "mask",
    "ISA", "parse_instrument", "InstrumentTag",
    "Item", "Report", "evaluate",
]
