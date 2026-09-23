"""Compare LG account inventory with devices loaded in Home Assistant."""

from collections.abc import Mapping
from typing import Any


def device_inventory_changed(
    registered: list[dict[str, Any]] | None,
    loaded: Mapping[str, str],
) -> bool:
    """Return true for a device add/remove or alias change."""
    if not isinstance(registered, list):
        return False
    discovered: dict[str, str] = {}
    for item in registered:
        if not isinstance(item, dict):
            continue
        device_id = item.get("deviceId")
        info = item.get("deviceInfo")
        if isinstance(device_id, str) and isinstance(info, dict):
            discovered[device_id] = str(info.get("alias", ""))
    if registered and not discovered:
        return False
    return discovered != dict(loaded)

