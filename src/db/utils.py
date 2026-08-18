from __future__ import annotations
import re
from typing import Any
import numpy as np
import pandas as pd

_RANGE = re.compile(r"\s*(?:–|—|-{1,2}|\btot en met\b|\btot\b|\bt/m\b)\s*")
_NUM = re.compile(r"\d[\d.\s\u00a0]*(?:,\d+)?")

_QUALIFIERS = [
    ("circa", "circa"), ("ca.", "circa"), ("ongeveer", "circa"),
    ("±", "circa"), ("~", "circa"), ("about", "circa"), ("approx", "circa"),
    ("ruim", "minimaal"), ("minimaal", "minimaal"), ("minstens", "minimaal"),
    ("ten minste", "minimaal"), ("at least", "minimaal"),
    ("maximaal", "maximaal"), ("hooguit", "maximaal"), ("at most", "maximaal"),
]

_ABSENT = (
    "niet vermeld", "not stated", "not mentioned", "onbekend",
    "n.v.t", "nvt", "geen ", "none", "null",
)

_TRUE = ("ja", "yes", "true", "wel", "1")
_FALSE = ("nee", "no", "false", "niet", "0")

_WONINGEN = ("woning", "dwelling", "residential", "huishouden")
_UTILITEIT = ("utilit", "utiliteit", "non-residential", "bedrijf", "commercial")


def clean(v: Any) -> Any:
    """numpy/pandas scalars -> plain Python; NaN/NaT/NA -> None."""
    if v is None:
        return None
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and np.isnan(v):
        return None
    if v is pd.NaT or v is pd.NA:
        return None
    return v


def _to_float(tok: str) -> float | None:
    tok = tok.strip().replace(" ", "").replace("\u00a0", "")
    if "," in tok:                                    # 19,6 | 1.200,5
        tok = tok.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", tok):     # 1.200 | 12.345.678
        tok = tok.replace(".", "")
    try:
        return float(tok)
    except ValueError:
        return None


def _is_absent(low: str) -> bool:
    return any(w in low for w in _ABSENT)


def parse_number(s: Any) -> tuple[float | None, str | None]:
    """(value, qualifier). Ranges become their midpoint, flagged 'range'."""
    s = clean(s)
    if s is None:
        return None, None
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return float(s), None

    s = str(s).strip()
    if not s:
        return None, None

    low = s.lower()
    if _is_absent(low):
        return None, "niet_vermeld"

    qual = next((tag for word, tag in _QUALIFIERS if word in low), None)
    if "%" in s or "procent" in low or "percent" in low:
        qual = "percentage"

    parts = _RANGE.split(s)
    if len(parts) > 1:
        ends = [v for p in parts[:2]
                for v in (_to_float(m) for m in _NUM.findall(p)[:1])
                if v is not None]
        if len(ends) == 2:
            return sum(ends) / 2, "range" if qual in (None, "circa") else qual

    nums = [v for v in (_to_float(m) for m in _NUM.findall(s)) if v is not None]
    return (nums[0], qual) if nums else (None, qual)


def parse_bool(s: Any) -> bool | None:
    s = clean(s)
    if s is None:
        return None
    if isinstance(s, bool):
        return s

    low = str(s).strip().lower().lstrip("*-• ")
    if not low or _is_absent(low):
        return None

    first = re.split(r"[\s,.;:]", low, maxsplit=1)[0]
    if first in _TRUE:
        return True
    if first in _FALSE:
        return False
    if low.startswith(("er is een", "there is a", "opgesteld", "uitgevoerd")):
        return True
    if low.startswith(("er is geen", "there is no", "niet opgesteld")):
        return False
    return None


def parse_split(s: Any) -> tuple[float | None, float | None, str | None]:
    """
    (woningen, utiliteit, qualifier) for `type: split` answers.

    Handles 'woningen: 1.200, utiliteit: 300', '1200 woningen en 300 utiliteit',
    and a bare number (attributed to woningen, flagged 'ongesplitst').
    """
    s = clean(s)
    if s is None:
        return None, None, None
    text = str(s).strip()
    if not text or _is_absent(text.lower()):
        return None, None, "niet_vermeld"

    won = uti = None
    for chunk in re.split(r"[;,\n]|\ben\b", text):
        low = chunk.lower()
        val, _ = parse_number(chunk)
        if val is None:
            continue
        if any(w in low for w in _WONINGEN) and won is None:
            won = val
        elif any(w in low for w in _UTILITEIT) and uti is None:
            uti = val

    if won is None and uti is None:
        val, qual = parse_number(text)
        return val, None, qual or "ongesplitst"

    return won, uti, None


def parse_response(raw: Any, question_type: str) -> dict[str, Any]:
    """
    Typed columns for one answer, dispatched on the question's type.

    Returns keys: value_num, value_bool, value_qualifier
    (plus value_woningen / value_utiliteit for `split`, if those columns exist).
    """
    raw = clean(raw)

    if question_type == "bool":
        return {"value_num": None,
                "value_bool": parse_bool(raw),
                "value_qualifier": None}

    if question_type == "split":
        won, uti, qual = parse_split(raw)
        total = None if won is None and uti is None else (won or 0) + (uti or 0)
        return {"value_num": total,
                "value_bool": None,
                "value_qualifier": qual,
                "value_woningen": won,
                "value_utiliteit": uti}

    if question_type == "count":
        num, qual = parse_number(raw)
        return {"value_num": num, "value_bool": None, "value_qualifier": qual}

    if question_type in ("enum", "status", "text"):
        # A number may still be embedded ('9 fte, waarvan 4 gedekt'); keep it
        # if one is there, but never force it.
        num, qual = parse_number(raw)
        return {"value_num": num,
                "value_bool": parse_bool(raw),
                "value_qualifier": qual}

    return {"value_num": None, "value_bool": None, "value_qualifier": None}

