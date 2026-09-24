"""Home Assistant response actions. Device enrollment stays in LG's app."""
import asyncio
import math
import voluptuous as vol
from aiohttp import ClientError
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util
from .const import DOMAIN
from .client import ThinQAPIException
from .capability_inventory import summarize_capabilities
from .diagnostic_redaction import redact_api_data
from .insight_helpers import combo_start_payload, location_state
from .metrics import capability_digest


def register_services(hass):
    """Register once; resolve loaded entries on every call to support reloads."""
    if hass.services.has_service(DOMAIN, "get_device_data"):
        return

    def resolve(device_id):
        device = dr.async_get(hass).async_get(device_id)
        if device:
            for entry_id in (device.config_entry_id,):
                entry = hass.config_entries.async_get_entry(entry_id)
                runtime = getattr(entry, "runtime_data", None)
                if entry and entry.domain == DOMAIN and runtime:
                    for coordinator in runtime.coordinators.values():
                        if (DOMAIN, coordinator.unique_id) in device.identifiers:
                            return entry, coordinator
        raise ServiceValidationError("Choose a loaded LG ThinQ Extended device")

    async def handle(call):
        entry, c = resolve(call.data["device_id"])
        insights = c.insights
        api = insights.api
        try:
            if call.service == "get_device_data":
                if call.data.get("refresh", False):
                    data = await c.api.fetch_data()
                    c.monitoring.observe(data, "fetch")
                    c.async_set_updated_data(data)
                # Raw IDs remain local to HA; downloaded diagnostics still redact them.
                return {"device_ref": c.unique_id, "device_type": str(c.api.device.device_type),
                    "mac_address": insights.mac,
                    "state": redact_api_data({k: v.value for k,v in c.data.items()}),
                    "capabilities": summarize_capabilities({"response": insights.profile},
                        {"response": api.states.get(c.device_id)}, {"response": c.api.device.energy_profile}),
                    "command": insights.command, "energy_history": insights.history,
                    "settings": insights.settings,
                    "maintenance": {"observed_cycles": insights.maintenance_cycles(), **insights.maintenance}}
            if call.service == "refresh_capabilities":
                old = capability_digest(insights.profile)
                profile = await api.async_get_device_profile(c.device_id)
                changed = capability_digest(profile) != old
                if changed:
                    hass.bus.async_fire(DOMAIN+"_capabilities_changed", {"device_id": call.data["device_id"], "device_ref": c.unique_id})
                    hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))
                return {"changed": changed, "reload_scheduled": changed}
            if call.service == "configure_monitoring":
                if "tariff_per_kwh" in call.data and not math.isfinite(call.data["tariff_per_kwh"]):
                    raise ServiceValidationError("Tariff must be finite")
                for key in ("history_enabled", "tariff_per_kwh", "maintenance_interval"):
                    if key in call.data:
                        insights.settings[key] = call.data[key]
                insights.maintenance.setdefault("baseline", insights.count())
                insights.changed()
                return {"settings": insights.settings, "currency": hass.config.currency}
            if call.service == "reset_maintenance":
                insights.maintenance = {"baseline": insights.count(), "reset_at": dt_util.now().isoformat()}
                insights.changed()
                return {"observed_cycles": 0}
            if call.service == "refresh_energy_history":
                await insights.refresh_history()
                return {"energy_history": insights.history}
            if call.service == "start_laundry_mode":
                # This action explicitly starts a cycle. No arbitrary POST payloads.
                async with insights.control_lock:
                    profile = await api.async_get_device_profile(c.device_id)
                    payload = combo_start_payload(profile, call.data["mode"], call.data["location"])
                    state = await api.async_get_device_status(c.device_id)
                    if location_state(state, call.data["location"]).get("remoteControlEnable", {}).get("remoteControlEnabled") is not True:
                        raise ServiceValidationError("Enable remote start at the appliance first")
                    await api.async_post_device_control(c.device_id, payload)
                return {"status": "accepted", "confirmed": False}
            if call.service == "refresh_subscription_health":
                mqtt = entry.runtime_data.mqtt_client
                await mqtt.async_check_subscription_health()
                return {"status": mqtt.subscription_status, "checked": mqtt.subscription_checked.isoformat()}
        except (ThinQAPIException, ClientError, TimeoutError, ValueError) as exc:
            raise ServiceValidationError("LG action failed: "+str(getattr(exc, "code", type(exc).__name__))) from exc

    base = {vol.Required("device_id"): cv.string}
    schemas = {
        "get_device_data": {vol.Optional("refresh", default=False): cv.boolean},
        "refresh_capabilities": {},
        "configure_monitoring": {vol.Optional("history_enabled"): cv.boolean,
            vol.Optional("tariff_per_kwh"): vol.All(vol.Coerce(float), vol.Range(min=0, max=1000)),
            vol.Optional("maintenance_interval"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100000))},
        "reset_maintenance": {}, "refresh_energy_history": {},
        "refresh_subscription_health": {},
        "start_laundry_mode": {vol.Required("mode"): vol.In(["WASHING", "DRYING", "WASHING_DRYING"]),
            vol.Optional("location", default="MAIN"): vol.In(["MAIN", "MINI"])},
    }
    async def dispatch(call):
        response = await handle(call)
        return response if call.return_response else None

    for name, fields in schemas.items():
        hass.services.async_register(DOMAIN, name, dispatch, schema=vol.Schema({**base, **fields}),
                                     supports_response=SupportsResponse.OPTIONAL)

    async def refresh_devices(call):
        entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
        runtime = getattr(entry, "runtime_data", None)
        if not entry or entry.domain != DOMAIN or runtime is None or runtime.mqtt_client is None:
            raise ServiceValidationError("Choose a loaded LG ThinQ Extended configuration entry")
        runtime.mqtt_client._schedule_inventory_check()
        return {"scheduled": True, "managed_in": "LG ThinQ app"} if call.return_response else None

    hass.services.async_register(DOMAIN, "refresh_devices", refresh_devices,
        schema=vol.Schema({vol.Required("config_entry_id"): cv.string}), supports_response=SupportsResponse.OPTIONAL)
