"""
Standards references used by this package, documented truth-based.

These three standards define the "L1 standard dictionary" layer. Only ISA-5.1 gives
a machine-usable letter table (see isa.py / data/isa_5_1.json); ISO 10628 and
IEC 62424 are cited for scope and to justify the line-number slot model. None of
them is applied as a hard constraint -- see the Never-Fabricate note below.
"""

STANDARDS = {
    "ANSI/ISA-5.1-2024": {
        "title": "Instrumentation and Control - Symbols and Identification",
        "scope": "Graphical symbols and instrument tag identification letters for "
                 "P&IDs. Table 4 defines first letters (measured variable), "
                 "succeeding letters (readout/output function), and function "
                 "modifiers (High/Low). This is the source of data/isa_5_1.json.",
        "used_for": "Instrument-tag letter validation and expansion (L1 prior).",
    },
    "ISO 10628": {
        "title": "Diagrams for the chemical and petrochemical industry "
                 "(PFD / P&ID)",
        "scope": "Rules for drawing PFDs and P&IDs: equipment, piping, valves, "
                 "connections, line symbols. Defines that a line is described by a "
                 "structured line number, motivating the line-number slot model "
                 "[Pipe Size]-[Service]-[Area/System]-[Sequence]-[Spec/Class].",
        "used_for": "Line-number slot structure (L1 prior for line tags).",
    },
    "IEC 62424": {
        "title": "Representation of process control engineering requests in P&IDs "
                 "and data exchange (CAEX)",
        "scope": "How control functions and process-control requests are represented "
                 "in P&IDs and exchanged as data. Confirms that instrument tags carry "
                 "machine-interpretable structure (function id + loop id).",
        "used_for": "Justifies structured extraction toward machine-readable output.",
    },
}

# Line-number conceptual slots, per ISO 10628 practice. Vendors reorder/rename
# these fields, so the induced vendor grammar (L2) refines the actual order; this
# is only the conceptual prior.
LINE_NUMBER_SLOTS = ["pipe_size", "service", "area_system", "sequence", "spec_class"]

NEVER_FABRICATE = (
    "Standards are soft priors. When the standard and the observed data disagree "
    "and no confident resolution exists, keep the raw OCR string and route to human "
    "review. Never invent a tag to satisfy a rule."
)
