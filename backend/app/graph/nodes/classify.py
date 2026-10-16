from __future__ import annotations

import re

KEYWORD_MAP = {
    "patient": ["patient", "name"],
    "specimen": ["specimen", "biopsy", "sample"],
    "gross_description": ["gross", "fragments", "tan-white", "measures"],
    "microscopic_description": ["microscopic", "histology", "cells", "gland"],
    "diagnosis": ["diagnosis", "diagnose", "impression"],
    "comments": ["recommend", "comment", "note", "clinical correlation"],
}


# Whole words (plural allowed), so "name" doesn't match "rename" or "note" "denote".
_PATTERNS = {
    section: [re.compile(rf"\b{re.escape(kw)}s?\b") for kw in keywords]
    for section, keywords in KEYWORD_MAP.items()
}


async def classify_sections(text: str) -> list:
    """Naive keyword-based classifier returning likely target sections.

    Returns a list of section names (may be empty). This is intentionally
    simple — the extraction node is expected to handle finer-grained parsing.
    """
    if not text:
        return []
    txt = text.lower()
    hits = []
    for section, keywords in KEYWORD_MAP.items():
        for pattern in _PATTERNS[section]:
            if pattern.search(txt):
                hits.append(section)
                break
    # preserve order of appearance if possible
    return hits


async def classify_chunk_node(state) -> dict:
    """Node: read `state.cleaned_chunk` and set `state.detected_fields`.

    Returns a dict with detected_fields (list). Only the six fields are valid.
    """
    text = getattr(state, "cleaned_chunk", "") or ""
    sections = await classify_sections(text)
    # ensure only valid fields and unique
    valid = [
        "patient",
        "specimen",
        "gross_description",
        "microscopic_description",
        "diagnosis",
        "comments",
    ]
    detected = []
    for s in sections:
        if s in valid and s not in detected:
            detected.append(s)
    state.detected_fields = detected
    return {"detected_fields": detected}
