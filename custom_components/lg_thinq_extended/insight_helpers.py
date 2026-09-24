"""Pure validation and aggregation helpers for HA visibility and actions."""
import re
from copy import deepcopy
from datetime import datetime, timedelta
from .client.energy import energy_total


def reported_mac(info):
    """Only explicit appliance MAC fields; never infer from IDs or network SSIDs."""
    found = set()
    for key in ("mac", "macAddress", "mac_address", "wifiMacAddress"):
        value = info.get(key)
        if not isinstance(value, str):
            continue
        compact = re.sub(r"[:-]", "", value.strip()).lower()
        if not re.fullmatch(r"[0-9a-f]{12}", compact):
            continue
        if int(compact[:2], 16) & 1 or compact == "000000000000":
            continue
        found.add(":".join(compact[i:i+2] for i in range(0, 12, 2)))
    return next(iter(found)) if len(found) == 1 else None


def energy_records(response, prop, period):
    """Validate amount AND date; duplicates/missing dates cannot become zero."""
    energy_total(response, prop)
    result = response["result"]
    if len(result["dataList"]) > (31 if period == "DAILY" else 12):
        raise ValueError("Energy history exceeds the requested window")
    records = {}
    for row in result["dataList"]:
        day = row.get("usedDate")
        fmt = "%Y%m%d" if period == "DAILY" else "%Y%m"
        if not isinstance(day, str) or len(day) != (8 if period == "DAILY" else 6):
            raise ValueError("Missing energy date")
        datetime.strptime(day, fmt)
        if day in records:
            raise ValueError("Duplicate energy date")
        records[day] = energy_total({"result": {"property": result.get("property"), "dataList": [row]}}, prop)
    return records


def rolling(records, today, days):
    """Sum completed days only, requiring every day in the window."""
    keys = [(today-timedelta(days=i)).strftime("%Y%m%d") for i in range(1, days+1)]
    return sum(records[k] for k in keys) if all(k in records for k in keys) else None


def combo_mode(profile, location="MAIN"):
    """Resolve a single advertised mode alias, with its exact permissions."""
    blocks = profile.get("property", []) if isinstance(profile, dict) else []
    if isinstance(blocks, dict):
        blocks = [blocks]
    if not isinstance(blocks, list):
        raise ValueError("Invalid mode profile")
    found = []
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("Invalid location profile")
        if block.get("location", {}).get("locationName") != location:
            continue
        modes = block.get("mode", {})
        for key in ("washerMode", "washerOperationMode"):
            spec = modes.get(key)
            if isinstance(spec, dict):
                found.append((key, spec, block.get("operation", {}).get("washerOperationMode", {})))
    if len(found) != 1:
        raise ValueError("No unambiguous advertised laundry mode")
    return found[0]


def combo_start_payload(profile, mode, location="MAIN"):
    key, spec, operation = combo_mode(profile, location)
    if ("w" not in spec.get("mode", []) or mode not in spec.get("value", {}).get("w", [])
            or mode not in {"WASHING", "DRYING", "WASHING_DRYING"}
            or "w" not in operation.get("mode", []) or "START" not in operation.get("value", {}).get("w", [])):
        raise ValueError("Requested mode/start is not writable in the LG profile")
    return {"location": {"locationName": location}, "mode": {key: mode},
            "operation": {"washerOperationMode": "START"}}


def location_state(state, location):
    if isinstance(state, list):
        return next((x for x in state if isinstance(x, dict) and x.get("location", {}).get("locationName") == location), {})
    return state if isinstance(state, dict) else {}


def payload_confirmed(payload, state):
    """Confirm only exact subsequent readable values, never a write-only START."""
    state = location_state(state, payload.get("location", {}).get("locationName"))
    fields = {k: v for k, v in payload.items() if k != "location"}
    def matches(expected, actual):
        if isinstance(expected, dict):
            return isinstance(actual, dict) and all(k in actual and matches(v, actual[k]) for k,v in expected.items())
        return expected == actual
    return bool(fields) and matches(fields, state)


def merge_report(state, report):
    """Keep location-tagged cached state current without mixing cavities."""
    result = deepcopy(state)
    if not isinstance(report, dict):
        return result
    if isinstance(result, list):
        location = report.get("location", {}).get("locationName")
        if location is None:
            return result
        for item in result:
            if item.get("location", {}).get("locationName") == location:
                item.update(merge_report(item, report))
        return result
    if not isinstance(result, dict):
        result = {}
    for key, value in report.items():
        result[key] = merge_report(result.get(key), value) if isinstance(value, dict) else deepcopy(value)
    return result
