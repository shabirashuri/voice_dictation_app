"""Check that model output only states what was dictated.

Prompts say "never invent" but that is not enforced. These checks catch the
high-risk cases in pathology: numbers and measurements, laterality, and
negations. They are deliberately narrow, so faithful paraphrase passes.

Messages never include the dictated text, so they are safe to log.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

# Spoken or written unit -> canonical unit.
_UNITS = {
    "mm": "mm", "millimeter": "mm", "millimeters": "mm", "millimetre": "mm", "millimetres": "mm",
    "cm": "cm", "centimeter": "cm", "centimeters": "cm", "centimetre": "cm", "centimetres": "cm",
    "µm": "um", "um": "um", "micron": "um", "microns": "um", "micrometer": "um",
    "micrometers": "um", "micrometre": "um", "micrometres": "um",
    "mg": "mg", "milligram": "mg", "milligrams": "mg",
    "g": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "%": "pct", "percent": "pct",
    "°": "deg", "degree": "deg", "degrees": "deg",
}

_LATERALITY = {"left", "right", "bilateral"}

# Any of these marks a negation. Presence is compared, not the exact word, so
# "negative for tumour" and "no tumour" count as the same thing.
_NEGATION = {"no", "not", "without", "negative", "absent", "nor", "neither"}

_TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-zµ]+|[%°]")


def _tokens(text: str) -> list[str]:
    """Lower-case tokens; number words become digits, 'x point y' becomes 'x.y'."""
    raw = _TOKEN.findall(text.lower().replace("μ", "µ"))
    out: list[str] = []
    i = 0
    while i < len(raw):
        tok = raw[i]
        value = _to_number(raw, i)
        if value is not None:
            number, consumed = value
            out.append(_norm(str(number)))
            i += consumed
            continue
        out.append(tok)
        i += 1
    return out


def _to_number(raw: list[str], i: int):
    """Read a number starting at raw[i]: digits, number words, or 'twenty five'.
    Returns (Decimal, tokens_consumed) or None."""
    tok = raw[i]
    if re.fullmatch(r"\d+(?:\.\d+)?", tok):
        number, consumed = Decimal(tok), 1
    elif tok in _NUMBER_WORDS:
        number, consumed = Decimal(_NUMBER_WORDS[tok]), 1
        # 'twenty five' -> 25
        if number >= 20 and number % 10 == 0 and i + 1 < len(raw) and raw[i + 1] in _NUMBER_WORDS:
            ones = _NUMBER_WORDS[raw[i + 1]]
            if 0 < ones < 10:
                number, consumed = number + ones, 2
    else:
        return None
    # 'two point five' -> 2.5 (only when a digit-like token follows 'point')
    if i + consumed + 1 < len(raw) and raw[i + consumed] == "point":
        nxt = raw[i + consumed + 1]
        if re.fullmatch(r"\d+", nxt) or nxt in _NUMBER_WORDS:
            digits = nxt if nxt.isdigit() else str(_NUMBER_WORDS[nxt])
            try:
                number = Decimal(f"{number}.{digits}")
                consumed += 2
            except InvalidOperation:
                pass
    return number, consumed


def _measurements(tokens: list[str]) -> tuple[set[str], set[tuple[str, str]]]:
    """Return (all numbers, number+unit pairs) found in tokens."""
    numbers: set[str] = set()
    measures: set[tuple[str, str]] = set()
    for i, tok in enumerate(tokens):
        if not re.fullmatch(r"\d+(?:\.\d+)?", tok):
            continue
        value = _norm(tok)
        numbers.add(value)
        if i + 1 < len(tokens) and tokens[i + 1] in _UNITS:
            measures.add((value, _UNITS[tokens[i + 1]]))
    return numbers, measures


def _norm(value: str) -> str:
    """'2.50' and '2.5' compare equal; '2' stays '2'."""
    try:
        return format(Decimal(value).normalize(), "f")
    except InvalidOperation:
        return value


def check_grounding(source: str, content: str, label: str = "update") -> list[str]:
    """Problems with `content` that the `source` text does not support.

    Every number (and every number-with-unit) in content must appear in source;
    every laterality word and every negation in content must too.
    """
    src_tokens = _tokens(source)
    out_tokens = _tokens(content)
    src_numbers, src_measures = _measurements(src_tokens)
    out_numbers, out_measures = _measurements(out_tokens)

    problems: list[str] = []
    for value, unit in sorted(out_measures):
        if (value, unit) not in src_measures:
            problems.append(f"{label}: measurement with unit '{unit}' is not in the dictation")
    covered = {value for value, _ in out_measures}
    for value in sorted(out_numbers - covered):
        if value not in src_numbers:
            problems.append(f"{label}: number '{value}' is not in the dictation")

    for word in sorted(_LATERALITY & set(out_tokens) - set(src_tokens)):
        problems.append(f"{label}: laterality '{word}' is not in the dictation")

    out_negated = bool(_NEGATION & set(out_tokens))
    src_negated = bool(_NEGATION & set(src_tokens))
    if out_negated and not src_negated:
        problems.append(f"{label}: a negation is not in the dictation")
    return problems


def check_dropped_negation(source: str, contents: list[str]) -> list[str]:
    """If the dictation negates something, at least one update must keep a negation."""
    if not (_NEGATION & set(_tokens(source))):
        return []
    if any(_NEGATION & set(_tokens(content)) for content in contents):
        return []
    return ["a negation in the dictation was not captured"]
