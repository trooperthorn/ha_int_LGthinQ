"""Summarize ThinQ profile permissions without making additional API calls."""

from typing import Any


def _property_specs(node: Any, path: str = "") -> list[dict[str, Any]]:
    """Flatten profile descriptors, retaining appliance location and unit."""
    if isinstance(node, list):
        result: list[dict[str, Any]] = []
        for index, item in enumerate(node):
            suffix = ""
            if isinstance(item, dict):
                labels = [
                    str(item[key])
                    for key in ("locationName", "unit")
                    if isinstance(item.get(key), str)
                ]
                suffix = f"[{','.join(labels)}]" if labels else f"[{index}]"
            result.extend(_property_specs(item, f"{path}{suffix}"))
        return result
    if not isinstance(node, dict):
        return []
    if isinstance(node.get("mode"), list) and isinstance(node.get("type"), str):
        spec: dict[str, Any] = {
            "path": path,
            "type": node["type"],
            "readable": "r" in node["mode"],
            "writable": "w" in node["mode"],
        }
        constraints = node.get("value")
        if isinstance(constraints, dict):
            spec["read_constraints"] = constraints.get("r")
            spec["write_constraints"] = constraints.get("w")
        return [spec]
    result = []
    for key, value in node.items():
        if key in ("locationName",) and isinstance(value, str):
            continue
        result.extend(_property_specs(value, f"{path}.{key}" if path else key))
    return result


def _state_paths(node: Any, path: str = "") -> set[str]:
    """List observed state paths, omitting changing state values."""
    if isinstance(node, list):
        result: set[str] = set()
        for item in node:
            result.update(_state_paths(item, path))
        return result
    if isinstance(node, dict):
        result = set()
        for key, value in node.items():
            result.update(_state_paths(value, f"{path}.{key}" if path else key))
        return result
    return {path} if path else set()


def summarize_capabilities(
    profile_result: dict[str, Any],
    state_result: dict[str, Any],
    energy_result: dict[str, Any],
) -> dict[str, Any]:
    """Create a concise view from already redacted diagnostic GET results."""
    profile = profile_result.get("response")
    profile = profile if isinstance(profile, dict) else {}
    state = state_result.get("response")
    energy = energy_result.get("response")
    energy = energy if isinstance(energy, dict) else {}
    notifications = profile.get("notification")
    notifications = notifications if isinstance(notifications, dict) else {}
    push_codes = notifications.get("push")
    push_codes = push_codes if isinstance(push_codes, list) else []
    energy_properties = energy.get("result")
    energy_properties = energy_properties if isinstance(energy_properties, dict) else {}
    property_names = energy_properties.get("property")
    property_names = property_names if isinstance(property_names, list) else []
    if "error_code" in energy_result:
        energy_status = "unsupported" if str(energy_result["error_code"]) in {
            "1219", "1220", "1221", "2201", "2202"
        } else "error"
    elif "error" in energy_result:
        energy_status = "unavailable"
    else:
        energy_status = "available" if property_names else "not_advertised"
    return {
        "properties": sorted(_property_specs(profile.get("property"), "property"), key=lambda p: p["path"]),
        "extension_properties": sorted(_property_specs(profile.get("extensionProperty"), "extensionProperty"), key=lambda p: p["path"]),
        "observed_state_paths": sorted(_state_paths(state)),
        "notifications": sorted(str(code) for code in push_codes),
        "energy_status": energy_status,
        "energy_properties": property_names,
    }

