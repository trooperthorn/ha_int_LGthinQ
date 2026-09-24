"""Compare LG account inventory with devices loaded in Home Assistant."""

from collections.abc import Mapping
from typing import Any


def device_inventory_changed(
    registered: list[dict[str, Any]] | None,
    loaded: Mapping[str, str],
) -> bool:
    """Return true for a device add/remove or alias change."""
    discovered = parse_device_inventory(registered)
    return discovered is not None and discovered != dict(loaded)


def parse_device_inventory(registered):
    """Require a complete valid snapshot before inferring removal."""
    if not isinstance(registered, list):
        return None
    discovered = {}
    for item in registered:
        if not isinstance(item, dict):
            return None
        device_id = item.get("deviceId")
        info = item.get("deviceInfo")
        if (not isinstance(device_id, str) or not device_id
                or not isinstance(info, dict) or device_id in discovered):
            return None
        discovered[device_id] = str(info.get("alias", ""))
    return discovered
