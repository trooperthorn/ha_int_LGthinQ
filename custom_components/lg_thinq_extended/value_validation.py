"""Validate profile-bounded appliance values before display or control."""

from numbers import Real


def value_in_profile_range(
    value: object, minimum: Real | None, maximum: Real | None
) -> bool:
    """Check only bounds explicitly supplied by the LG device profile."""
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    if minimum is not None and value < minimum:
        return False
    if maximum is not None and value > maximum:
        return False
    return True

