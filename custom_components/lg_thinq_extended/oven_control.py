"""Read the oven's per-cavity run and remote-start states."""

from collections.abc import Mapping
from typing import Any

from .client.devices.const import Property as ThinQProperty


def oven_control_state(data: Mapping[str, Any], location: str | None) -> tuple[str | None, bool]:
    """Return run state and current remote-start permission, failing closed."""
    if not location:
        return None, False
    run = data.get(f"{location}_{ThinQProperty.CURRENT_STATE}")
    remote = data.get(f"{location}_{ThinQProperty.REMOTE_CONTROL_ENABLED}")
    run_value = getattr(run, "value", None)
    return (
        run_value if isinstance(run_value, str) else None,
        bool(getattr(remote, "is_on", False)),
    )


def oven_display_state(run_state: str | None, remote_enabled: bool) -> str | None:
    """Use observed run state for an informative command-select placeholder."""
    if run_state == "initial":
        return "off_remote_ready" if remote_enabled else "off"
    if run_state:
        return "on"
    return None


def oven_command_allowed(run_state: str | None, remote_enabled: bool) -> bool:
    """Permit an active cavity or a remotely armed idle cavity."""
    return run_state is not None and (remote_enabled or run_state != "initial")

