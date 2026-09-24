"""Validate LG energy responses without turning absent data into zero."""
import math
from .transport import ThinQAPIException


def energy_total(response, property_name):
    if not isinstance(response, dict):
        raise ValueError("Missing energy response")
    code = str(response.get("resultCode", "0000"))
    if code != "0000":
        raise ThinQAPIException(code, "LG energy request failed", {})
    result = response.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("dataList"), list):
        raise ValueError("Missing energy records")
    rows = result["dataList"]
    if not rows:
        raise ValueError("No energy records returned")
    properties = result.get("property")
    unambiguous = properties == [property_name] or properties == property_name
    total = 0.0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid energy record")
        value = row.get(property_name)
        # LG's export names a single-property amount useAmount; deployed responses
        # also use the requested property itself as the numeric field name.
        if value is None and unambiguous:
            value = row.get("useAmount")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("Missing or invalid energy amount")
        total += value
    return total
