"""Validate requested controls against the active LG device profile."""

import math


def validate_profile_number(
    value: float, minimum: float | None, maximum: float | None,
    step: float | None,
) -> float:
    """Reject values outside the profile's writable range or increment."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("The requested value must be a finite number")
    if minimum is None or maximum is None or step is None or step <= 0:
        raise ValueError("The device did not provide a valid writable range")
    if value < minimum or value > maximum:
        raise ValueError(f"The supported range is {minimum} to {maximum}")
    if not math.isclose((value - minimum) / step, round((value - minimum) / step), abs_tol=1e-7):
        raise ValueError(f"The supported increment is {step} from {minimum}")
    return value

