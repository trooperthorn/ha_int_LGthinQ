"""User-initiated, redacted LG ThinQ Connect capability diagnostics."""

from typing import Any
from aiohttp import ClientError

from thinqconnect import ThinQAPIException

from homeassistant.const import CONF_ACCESS_TOKEN, CONF_COUNTRY
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import ThinqConfigEntry
from .api import ThinQGuardedApi
from .const import CONF_CONNECT_CLIENT_ID
from .diagnostic_redaction import device_ref, redact_api_data

_MAX_DEVICES = 8


def _is_priority_device_type(device_type: str) -> bool:
    """Include new washer/dryer/combo variants without treating dishwashers as washers."""
    return device_type.startswith("DEVICE_") and device_type != "DEVICE_DISH_WASHER" and any(
        name in device_type for name in ("REFRIGERATOR", "OVEN", "WASH", "DRY", "COMBO")
    )


async def _capture(call: Any) -> dict[str, Any]:
    """Capture one GET result without exposing exception text or credentials."""
    try:
        return {"response": redact_api_data(await call)}
    except ThinQAPIException as exc:
        return {"error_code": exc.code}
    except (ClientError, OSError, TimeoutError):
        return {"error": "network_or_timeout"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ThinqConfigEntry
) -> dict[str, Any]:
    """Fetch current profiles and states for priority appliance families."""
    api = ThinQGuardedApi(
        session=async_get_clientsession(hass),
        access_token=entry.data[CONF_ACCESS_TOKEN],
        country_code=entry.data[CONF_COUNTRY],
        client_id=entry.data[CONF_CONNECT_CLIENT_ID],
    )

    # LG requires GET /devices before per-device GETs for this API client.
    try:
        registered = await api.async_get_device_list()
    except ThinQAPIException as exc:
        return {"country": entry.data[CONF_COUNTRY], "device_list_error_code": exc.code}
    except (ClientError, OSError, TimeoutError):
        return {"country": entry.data[CONF_COUNTRY], "device_list_error": "network_or_timeout"}

    devices: list[dict[str, Any]] = []
    seen: set[str] = set()
    matched = 0
    for item in registered or []:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("deviceId")
        info = item.get("deviceInfo", {})
        if not isinstance(raw_id, str) or not isinstance(info, dict):
            continue
        device_type = str(info.get("deviceType", ""))
        if not _is_priority_device_type(device_type) or raw_id in seen:
            continue
        matched += 1
        if len(devices) >= _MAX_DEVICES:
            continue
        seen.add(raw_id)
        devices.append(
            {
                "device_ref": device_ref(raw_id),
                "device_type": device_type,
                "model_name": redact_api_data(info.get("modelName"), "modelName"),
                "profile": await _capture(api.async_get_device_profile(raw_id)),
                "state": await _capture(api.async_get_device_status(raw_id)),
                "energy_profile": await _capture(
                    api.async_get_device_energy_profile(raw_id)
                ),
            }
        )

    return {
        "country": entry.data[CONF_COUNTRY],
        "priority_devices_found": matched,
        "max_devices_captured": _MAX_DEVICES,
        "devices": devices,
        "note": "Review before sharing; arbitrary vendor fields can contain private data.",
    }

