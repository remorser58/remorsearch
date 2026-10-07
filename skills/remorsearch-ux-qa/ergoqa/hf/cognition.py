"""Decision, reading, memory and response-time models.

References: REF-hick1952/REF-hyman1953 (choice RT), REF-card1983 (KLM), REF-miller1968
and REF-nielsen1993 (response-time limits), REF-wcag22 (2.2.1 Timing Adjustable).
"""

from __future__ import annotations

import math
import re

from .. import params

_HANGUL = re.compile(r"[가-힣]")
_WORD = re.compile(r"[A-Za-z0-9]+")


def hick_hyman_ms(n_choices: int, a_ms: float | None = None, b_ms_per_bit: float | None = None) -> float:
    """Choice decision time for n equally likely alternatives: a + b*log2(n+1)."""
    if n_choices < 1:
        raise ValueError("n_choices must be >= 1")
    a = params.HICK_A_MS if a_ms is None else a_ms
    b = params.HICK_B_MS_PER_BIT if b_ms_per_bit is None else b_ms_per_bit
    return a + b * math.log2(n_choices + 1)


def reading_units(text: str) -> tuple[int, int]:
    """Count Hangul syllables and latin/number words in text."""
    return len(_HANGUL.findall(text or "")), len(_WORD.findall(text or ""))


def reading_time_ms(text: str, syllables_per_min: float, words_per_min: float | None = None) -> float:
    """Time to read text once at the given rates (plus a fixed orientation cost)."""
    syllables, words = reading_units(text)
    wpm = words_per_min or params.READING_LATIN_WPM
    minutes = syllables / max(1.0, syllables_per_min) + words / max(1.0, wpm)
    return params.READING_ORIENT_MS + minutes * 60_000


def min_display_ms(text: str, syllables_per_min: float) -> float:
    """Minimum on-screen time for transient text (toast/snackbar) to be read.

    Reading time at the profile's rate multiplied by a safety factor, never
    below the platform short-toast floor used in params.
    """
    return max(params.TOAST_FLOOR_MS, reading_time_ms(text, syllables_per_min) * params.TOAST_SAFETY_FACTOR)


def latency_band(latency_ms: float | None) -> str:
    """Classify system response latency against classic response-time limits."""
    if latency_ms is None:
        return "no_feedback"
    if latency_ms <= params.LATENCY_INSTANT_MS:
        return "instant"
    if latency_ms <= params.LATENCY_FLOW_MS:
        return "noticeable"
    if latency_ms <= params.LATENCY_ATTENTION_MS:
        return "needs_progress_indicator"
    return "attention_lost"


def klm_estimate_ms(operators: str, touch: bool = True) -> float:
    """Keystroke-Level Model estimate for an operator string such as 'MPKPK'.

    Operators: K keystroke/tap, P point, B button press/release, H home hands,
    M mental preparation. Touch devices use params.KLM_TOUCH where available.
    """
    table = dict(params.KLM_MS)
    if touch:
        table.update(params.KLM_TOUCH_MS)
    total = 0.0
    for op in operators:
        if op not in table:
            raise ValueError(f"unknown KLM operator {op!r}")
        total += table[op]
    return total
