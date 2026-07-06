"""
Deterministic sizing calculator.

Converts raw body measurements (as collected by the frontend's measurement
form: formHeight, formWeight, formWaist) into a shirt size and a pant size.

Deliberately NOT an LLM call — small local models are unreliable at numeric
mapping, so this stays plain, testable Python. The Qualification Agent should
call `calculate_size(...)` directly and store the result on
`UserPreference.computed_shirt_size` / `computed_pant_size`.

Shirt size -> BMI-based bands (height + weight), nudged by a height
adjustment since two people with the same BMI but very different heights
don't always wear the same shirt size (a tall, lean frame often runs a
size up from a short frame at the same BMI).

Pant size -> waist size is used near-directly, snapped to the nearest
standard retail pant size (even numbers, 28-44), since that's how pants
are actually sized on shelves.
"""

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Shirt sizing — BMI bands
# ---------------------------------------------------------------------------

# (upper BMI bound, base size). Traversed in order; first match wins.
_BMI_BANDS = [
    (18.5, "S"),
    (23.0, "M"),
    (27.5, "L"),
    (32.0, "XL"),
    (float("inf"), "XXL"),
]

_SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL", "XXXL"]

# Height thresholds (cm) used to nudge the BMI-based size up/down by one band.
_SHORT_HEIGHT_CM = 165
_TALL_HEIGHT_CM = 183


def _bmi(height_cm: float, weight_kg: float) -> float:
    height_m = height_cm / 100
    return weight_kg / (height_m ** 2)


def _shift_size(size: str, steps: int) -> str:
    """Move `size` up/down the size order by `steps`, clamped to valid range."""
    idx = _SIZE_ORDER.index(size)
    new_idx = max(0, min(len(_SIZE_ORDER) - 1, idx + steps))
    return _SIZE_ORDER[new_idx]


def calculate_shirt_size(height_cm: float, weight_kg: float) -> str:
    """
    Returns a shirt size label (S, M, L, XL, XXL, ...) from height + weight.

    Approach:
      1. Compute BMI and map to a base size via fixed bands.
      2. Nudge up one size if the person is notably tall (frame tends to be
         longer even at the same BMI); nudge down one size if notably short.
    """
    if height_cm <= 0 or weight_kg <= 0:
        raise ValueError("height_cm and weight_kg must be positive numbers")

    bmi = _bmi(height_cm, weight_kg)

    base_size = next(size for upper_bound, size in _BMI_BANDS if bmi < upper_bound)

    if height_cm >= _TALL_HEIGHT_CM:
        return _shift_size(base_size, +1)
    if height_cm <= _SHORT_HEIGHT_CM:
        return _shift_size(base_size, -1)
    return base_size


# ---------------------------------------------------------------------------
# Pant sizing — waist-based
# ---------------------------------------------------------------------------

_MIN_PANT_SIZE = 28
_MAX_PANT_SIZE = 44


def calculate_pant_size(waist_in: float) -> str:
    """
    Returns a standard retail pant size (waist inches, snapped to the nearest
    even number, clamped to the 28-44 range most stores stock).
    """
    if waist_in <= 0:
        raise ValueError("waist_in must be a positive number")

    # Snap to nearest even number (standard pant sizing convention).
    snapped = round(waist_in / 2) * 2
    clamped = max(_MIN_PANT_SIZE, min(_MAX_PANT_SIZE, snapped))
    return str(clamped)


# ---------------------------------------------------------------------------
# Combined result used by the Qualification Agent
# ---------------------------------------------------------------------------

@dataclass
class SizeResult:
    shirt_size: str
    pant_size: str
    bmi: float
    notes: Optional[str] = None


def calculate_size(
    height_cm: float,
    weight_kg: float,
    waist_in: float,
    age: Optional[int] = None,
) -> SizeResult:
    """
    Main entry point. Computes both shirt and pant size from raw
    measurements. `age` is accepted but currently unused in the sizing
    formula itself — it's kept in the signature since it's collected
    alongside the other measurements and may factor into future fit
    logic (e.g. distinguishing youth vs adult cuts).

    Raises ValueError if any measurement is missing/invalid, so the caller
    (Qualification Agent) can catch it and ask the user to re-enter data
    rather than silently storing a wrong size.
    """
    shirt_size = calculate_shirt_size(height_cm, weight_kg)
    pant_size = calculate_pant_size(waist_in)
    bmi = round(_bmi(height_cm, weight_kg), 1)

    notes = None
    if bmi < 16 or bmi > 40:
        notes = "BMI is outside the typical range — recommend the user double-check their entered measurements."

    return SizeResult(shirt_size=shirt_size, pant_size=pant_size, bmi=bmi, notes=notes)


if __name__ == "__main__":
    # Quick manual sanity check — matches the example we used in the
    # roleplay earlier: 5'7" (~170cm), 65kg, 32" waist -> should land on M / 32.
    result = calculate_size(height_cm=170, weight_kg=65, waist_in=32, age=20)
    print(result)
