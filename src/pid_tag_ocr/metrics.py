"""
Evaluation metrics.

The project distinguishes RAW OCR accuracy from GRAMMAR-CONSTRAINED accuracy: the
neural OCR character classifier does not improve, but applying domain constraints
raises the final decoded accuracy -- which is what matters industrially.

Six metrics (project spec):
    1. Raw OCR Character Accuracy          char-level, OCR output vs ground truth
    2. Grammar-constrained Char Accuracy   char-level, decoded output vs ground truth
    3. Exact Tag Match                      whole-tag equality, decoded vs GT
    4. Auto-approval Precision              of tokens auto-approved, fraction correct
    5. Rule-violation Detection Rate        of GT-wrong tokens, fraction flagged
    6. Human Review Rate                    fraction of tokens routed to a human

Ground truth is optional. Without GT we still report auto-approval and review rates
(the operational metrics); accuracy metrics require GT and are reported as N/A
otherwise -- never fabricated.
"""
from __future__ import annotations
from dataclasses import dataclass
from difflib import SequenceMatcher


def char_accuracy(pred: str, gold: str) -> float:
    """Character-level similarity via longest matching blocks / gold length."""
    if not gold:
        return 1.0 if not pred else 0.0
    sm = SequenceMatcher(None, pred, gold)
    matched = sum(b.size for b in sm.get_matching_blocks())
    return matched / max(len(gold), 1)


@dataclass
class Item:
    raw: str                 # OCR output
    decoded: str             # after grammar decoding
    confident: bool          # auto-approved (True) or flagged for review (False)
    gold: str | None = None  # ground truth, if available


@dataclass
class Report:
    n: int
    raw_char_acc: float | None
    grammar_char_acc: float | None
    exact_tag_match: float | None
    auto_approval_precision: float | None
    rule_violation_detection: float | None
    human_review_rate: float

    def as_dict(self) -> dict:
        return {
            "n": self.n,
            "raw_ocr_char_accuracy": self.raw_char_acc,
            "grammar_constrained_char_accuracy": self.grammar_char_acc,
            "exact_tag_match": self.exact_tag_match,
            "auto_approval_precision": self.auto_approval_precision,
            "rule_violation_detection_rate": self.rule_violation_detection,
            "human_review_rate": self.human_review_rate,
        }

    def pretty(self) -> str:
        def pct(x):
            return "  N/A " if x is None else f"{x*100:5.1f}%"
        return (
            f"n = {self.n}\n"
            f"  Raw OCR Character Accuracy          {pct(self.raw_char_acc)}\n"
            f"  Grammar-constrained Char Accuracy   {pct(self.grammar_char_acc)}\n"
            f"  Exact Tag Match                     {pct(self.exact_tag_match)}\n"
            f"  Auto-approval Precision             {pct(self.auto_approval_precision)}\n"
            f"  Rule-violation Detection Rate       {pct(self.rule_violation_detection)}\n"
            f"  Human Review Rate                   {pct(self.human_review_rate)}"
        )


def evaluate(items: list[Item]) -> Report:
    n = len(items)
    if n == 0:
        return Report(0, None, None, None, None, None, 0.0)

    has_gold = all(it.gold is not None for it in items)
    review_rate = sum(1 for it in items if not it.confident) / n

    if not has_gold:
        # operational metrics only
        return Report(n, None, None, None, None, None, review_rate)

    raw_acc = sum(char_accuracy(it.raw, it.gold) for it in items) / n
    dec_acc = sum(char_accuracy(it.decoded, it.gold) for it in items) / n
    exact = sum(1 for it in items if it.decoded == it.gold) / n

    approved = [it for it in items if it.confident]
    ap = (sum(1 for it in approved if it.decoded == it.gold) / len(approved)
          if approved else None)

    wrong = [it for it in items if it.raw != it.gold]  # OCR got it wrong
    # detection = of the truly-wrong tokens, how many were either corrected OR flagged
    detected = sum(1 for it in wrong
                   if it.decoded == it.gold or not it.confident)
    dr = detected / len(wrong) if wrong else None

    return Report(n, raw_acc, dec_acc, exact, ap, dr, review_rate)
