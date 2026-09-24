"""Bounded historical energy, command outcomes and maintenance for HA."""
import asyncio
from datetime import timedelta
from aiohttp import ClientError
from homeassistant.util import dt as dt_util
from .client import ThinQAPIException
from .const import DOMAIN
from .insight_helpers import energy_records, rolling, reported_mac, payload_confirmed
from .diagnostic_redaction import redact_api_data


class Insights:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.api = coordinator.api.device.thinq_api
        self.settings = {}
        self.history = {}
        self.command = {}
        self.maintenance = {}
        self.lock = asyncio.Lock()
        self.control_lock = asyncio.Lock()
        self.task = None
        self.confirm_cancel = None
        self.refresh_day = None

    def load(self, saved):
        self.settings = saved.get("settings", {})
        self.history = saved.get("history", {})
        self.maintenance = saved.get("maintenance", {})
        self.maintenance.setdefault("baseline", 0)
        self.command = saved.get("command", {})
        if self.command.get("status") in {"sending", "accepted"}:
            self.command["status"] = "unconfirmed_after_restart"
        for record in self.history.values():
            record["error"] = "not_refreshed"
        listeners = getattr(self.api, "command_listeners", None)
        if isinstance(listeners, dict):
            listeners.setdefault(self.coordinator.device_id, []).append(self.on_command)

    def snapshot(self):
        return {"settings": self.settings, "history": self.history,
                "maintenance": self.maintenance, "command": self.command}

    @property
    def profile(self):
        return getattr(self.api, "profiles", {}).get(self.coordinator.device_id, {})

    @property
    def mac(self):
        return reported_mac(getattr(self.api, "device_metadata", {}).get(self.coordinator.device_id, {}))

    def changed(self):
        self.coordinator.monitoring.save_later()
        self.coordinator.monitoring.notify()

    def on_command(self, status, payload, error):
        if self.confirm_cancel:
            self.confirm_cancel.cancel()
            self.confirm_cancel = None
        self.command = {"status": status, "timestamp": dt_util.now().isoformat(),
                        "payload": redact_api_data(payload), "error": error}
        if status == "accepted":
            self.confirm_cancel = self.coordinator.hass.loop.call_later(120, self.unconfirmed)
        self.emit_command()

    def emit_command(self):
        self.coordinator.hass.bus.async_fire(DOMAIN + "_command_result", {
            "config_entry_id": self.coordinator.config_entry.entry_id,
            "device_ref": self.coordinator.unique_id, **self.command})
        self.changed()

    def unconfirmed(self):
        self.confirm_cancel = None
        if self.command.get("status") == "accepted":
            self.command["status"] = "accepted_unconfirmed"
            self.emit_command()

    def observe(self, raw):
        if self.command.get("status") == "accepted" and payload_confirmed(self.command["payload"], raw):
            if self.confirm_cancel:
                self.confirm_cancel.cancel()
                self.confirm_cancel = None
            self.command.update(status="state_confirmed", confirmed_at=dt_util.now().isoformat())
            self.emit_command()

    def count(self):
        return sum(v for k,v in self.coordinator.monitoring.history.values.items()
                   if k.endswith("_maintenance_observed") and isinstance(v, int))

    def maintenance_cycles(self):
        return max(0, self.count()-self.maintenance.get("baseline", self.count()))

    def tick(self, now):
        if self.settings.get("history_enabled") and self.refresh_day != now.date() and self.task is None:
            self.refresh_day = now.date()
            self.task = self.coordinator.hass.async_create_task(self.refresh_history())
            self.task.add_done_callback(lambda _: setattr(self, "task", None))

    async def refresh_history(self):
        async with self.lock:
            today = dt_util.now().date()
            # Two bounded calls per advertised property. Never retry controls.
            month = today.year*12 + today.month-1
            start_month = month-11
            for prop in self.coordinator.api.device.energy_properties:
                record = self.history.setdefault(prop, {})
                record["attempt"] = dt_util.now().isoformat()
                try:
                    daily = await self.api.async_get_device_energy_usage(self.coordinator.device_id, prop,
                        "DAILY", (today-timedelta(days=30)).strftime("%Y%m%d"), (today-timedelta(days=1)).strftime("%Y%m%d"))
                    daily = energy_records(daily, prop, "DAILY")
                    monthly = await self.api.async_get_device_energy_usage(self.coordinator.device_id, prop,
                        "MONTHLY", f"{start_month//12:04}{start_month%12+1:02}", today.strftime("%Y%m"))
                    monthly = energy_records(monthly, prop, "MONTHLY")
                    record.update(daily=daily, monthly=monthly, error=None, success=dt_util.now().isoformat())
                except (ThinQAPIException, ClientError, TimeoutError, ValueError) as exc:
                    record["error"] = str(getattr(exc, "code", type(exc).__name__))
                self.changed()

    def total(self, prop, days):
        record = self.history.get(prop, {})
        return None if record.get("error") else rolling(record.get("daily", {}), dt_util.now().date(), days)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.confirm_cancel:
            self.confirm_cancel.cancel()
        listeners = getattr(self.api, "command_listeners", {}).get(self.coordinator.device_id, [])
        if self.on_command in listeners:
            listeners.remove(self.on_command)


def extra_definitions(coordinator):
    from .monitoring import Metric
    from .insight_helpers import combo_mode, location_state
    c = coordinator
    insights = c.insights
    def mqtt():
        return getattr(getattr(c.config_entry, "runtime_data", None), "mqtt_client", None)
    def remote():
        values = [v.is_on for k,v in c.data.items() if k.endswith("remote_control_enabled")]
        if not c.last_update_success:
            return "state_unavailable"
        if not values:
            return "not_advertised"
        return "remote_enabled" if any(v is True for v in values) else "remote_disabled"
    sensors = [
        Metric("remote_eligibility", "Remote action eligibility", remote, diagnostic=True),
        Metric("command_status", "Last command outcome", lambda: insights.command.get("status", "none"), diagnostic=True),
        Metric("command_time", "Last command time", lambda: insights.command.get("timestamp"), kind="timestamp", diagnostic=True),
        Metric("command_error", "Last command error", lambda: insights.command.get("error"), diagnostic=True),
        Metric("mqtt_certificate_expiry", "MQTT certificate expiry", lambda: getattr(getattr(mqtt(), "client", None), "certificate_expiry", None), kind="timestamp", diagnostic=True),
        Metric("subscription_status", "Cloud subscription status", lambda: getattr(mqtt(), "subscription_status", "not_checked"), diagnostic=True),
        Metric("subscription_checked", "Cloud subscription last checked", lambda: getattr(mqtt(), "subscription_checked", None), kind="timestamp", diagnostic=True),
    ]
    binaries = []
    if insights.mac:
        sensors.append(Metric("mac_address", "MAC address", lambda: insights.mac, diagnostic=True))
    if any(k.endswith("cycle_count") for k in c.data):
        sensors.append(Metric("maintenance_cycles", "Observed cycles since maintenance", insights.maintenance_cycles))
        binaries.append(Metric("maintenance_due", "Maintenance reminder due",
            lambda: insights.maintenance_cycles() >= insights.settings["maintenance_interval"] if insights.settings.get("maintenance_interval") else None, kind="problem"))
    try:
        key, spec, _ = combo_mode(insights.profile)
    except ValueError:
        pass
    else:
        if "r" in spec.get("mode", []):
            sensors.append(Metric("laundry_mode", "Reported laundry mode",
                lambda k=key: location_state(getattr(insights.api, "states", {}).get(c.device_id), "MAIN").get("mode", {}).get(k)))
    for prop in c.api.device.energy_properties:
        for days in (7, 30):
            sensors.append(Metric(prop+f"_rolling_{days}", prop+f" previous {days} days", lambda p=prop,d=days: insights.total(p,d), "Wh", "energy"))
        sensors.append(Metric(prop+"_daily_average", prop+" 30 day daily average", lambda p=prop: insights.total(p,30)/30 if insights.total(p,30) is not None else None, "Wh", "energy"))
        sensors.append(Metric(prop+"_history_status", prop+" history fetch status", lambda p=prop: insights.history.get(p,{}).get("error") or ("OK" if insights.history.get(p,{}).get("success") else "not_requested"), diagnostic=True))
        sensors.append(Metric(prop+"_cost_30", prop+" estimated 30 day cost", lambda p=prop: insights.total(p,30)/1000*insights.settings["tariff_per_kwh"] if insights.total(p,30) is not None and "tariff_per_kwh" in insights.settings else None, c.hass.config.currency))
    # Timer components are kept distinct; no inferred selected course or delay intent.
    for key in c.data:
        if "relative_" in key and any(s in key for s in ("hour_to_", "minute_to_")):
            sensors.append(Metric(key+"_reported", "Reported "+key.replace("_", " "), lambda k=key: c.data[k].value,
                "h" if "hour" in key else "min", "duration"))
    return sensors, binaries
