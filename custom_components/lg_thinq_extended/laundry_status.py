"""Display state for write-only laundry operation selects."""

from collections.abc import Mapping
from typing import Any

from thinqconnect.devices.const import Property as ThinQProperty


def laundry_operation_display(data: Mapping[str, Any], location: str | None) -> str | None:
    """Summarize a readable run state without presenting it as a command."""
    if not location:
        return None
    property_state = data.get(f"{location}_{ThinQProperty.CURRENT_STATE}")
    state = getattr(property_state, "value", None)
    if not isinstance(state, str):
        return None
    if state == "power_off":
        return "off"
    if state == "initial":
        return "ready"
    if state == "end":
        return "finished"
    if state in ("pause", "paused"):
        return "paused"
    if state == "reserved":
        return "delayed"
    if state == "error":
        return "error"
    return "running"


def laundry_remote_ready(data: Mapping[str, Any], location: str | None) -> bool:
    """Require an explicit remote-enable state before starting laundry."""
    if not location:
        return False
    property_state = data.get(f"{location}_{ThinQProperty.REMOTE_CONTROL_ENABLED}")
    return getattr(property_state, "value", None) is True

