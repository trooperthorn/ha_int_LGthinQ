"""Profile-gated monitoring entities using existing reports and local history."""
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.core import callback
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .metrics import ACTIVE, OVEN_ACTIVE, Observations, minutes, progress, capability_digest


class Monitoring:
    """One local clock and storage record per device, no extra state polling."""

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.store = Store(coordinator.hass, 1, DOMAIN + ".monitoring." + coordinator.unique_id)
        self.history = Observations()
        self.energy = {}
        self.last_report = None
        self.last_fetch = None
        self.stop = None
        self.mqtt_connected = False
        self.ever_connected = False
        self.reconnects = 0
        self.last_disconnect = None
        self.listeners = set()

    async def load(self):
        saved = await self.store.async_load() or {}
        self.history = Observations(saved.get("history"))
        self.coordinator.insights.load(saved.get("insights", {}))
        self.energy = saved.get("energy", {})
        # Preserve timestamps without claiming a successful fetch in this session.
        for value in self.energy.values():
            value["error"] = "not_refreshed"
        profiles = {key: [h.profile for h in (value.holders or [])]
                    for key, value in self.coordinator.data.items()}
        digest = capability_digest(profiles)
        if self.history.values.get("profile_digest") != digest:
            self.history.values["profile_digest"] = digest
            self.history.values["profile_changed"] = dt_util.now().isoformat()

    def snapshot(self):
        return {"history": self.history.saved, "energy": self.energy, "insights": self.coordinator.insights.snapshot()}

    def save_later(self):
        self.store.async_delay_save(self.snapshot, 10)

    def observe(self, data, source):
        now = dt_util.now()
        if source == "report":
            self.last_report = now
        elif source == "fetch":
            self.last_fetch = now
        self.history.observe({k: v.value for k, v in data.items()}, now)
        self.save_later()

    def notification(self, message):
        self.history.notification(message, dt_util.now())
        self.save_later()

    def energy_result(self, key, error=None, value=None):
        now = dt_util.now().isoformat()
        status = self.energy.setdefault(key, {})
        status.update(last_attempt=now, error=error)
        if error is None:
            status.update(last_success=now, last_good_value=value)
        self.save_later()
        self.notify()

    def listen(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    def notify(self):
        for listener in tuple(self.listeners):
            listener()

    def start(self):
        self.stop = async_track_time_interval(self.coordinator.hass, self.tick, timedelta(seconds=30))

    @callback
    def tick(self, now):
        self.coordinator.insights.tick(dt_util.as_local(now))
        self.history.advance(dt_util.as_local(now))
        self.notify()
        self.save_later()

    async def close(self):
        await self.coordinator.insights.close()
        if self.stop:
            self.stop()
            self.stop = None
        await self.store.async_save(self.snapshot())


@dataclass(frozen=True)
class Metric:
    key: str
    name: str
    read: object
    unit: str | None = None
    kind: str | None = None
    diagnostic: bool = False


def definitions(coordinator):
    """Create entities only where the mapped profile supplies their source."""
    monitor = coordinator.monitoring
    history = monitor.history
    def raw(key):
        item = coordinator.data.get(key)
        return item.value if item else None
    def flat():
        return {k: v.value for k, v in coordinator.data.items()}
    def stored(key):
        return history.values.get(key)
    def daily(key, days=1):
        return history.total(dt_util.now(), key, days)
    sensors = [
        Metric("last_report", "Last device report", lambda: monitor.last_report, kind="timestamp", diagnostic=True),
        Metric("last_fetch", "Last successful state fetch", lambda: monitor.last_fetch, kind="timestamp", diagnostic=True),
        Metric("report_age", "Device report age", lambda: (dt_util.now()-monitor.last_report).total_seconds() if monitor.last_report else None, "s", "duration", True),
        Metric("profile_changed", "Capabilities last changed", lambda: stored("profile_changed"), kind="timestamp", diagnostic=True),
    ]
    sensors.extend([
        Metric("mqtt_reconnects", "MQTT reconnects this session", lambda: monitor.reconnects, diagnostic=True),
        Metric("mqtt_last_disconnect", "MQTT last disconnect", lambda: monitor.last_disconnect, kind="timestamp", diagnostic=True),
    ])
    binaries = [Metric("mqtt_connected", "Cloud MQTT connected", lambda: monitor.mqtt_connected, kind="connectivity", diagnostic=True)]
    event_keys = [k for k in coordinator.data if k.endswith("error") or k.endswith("notification")]
    if event_keys:
        for key, name in [("last_notification", "Last notification"), ("last_error", "Last error")]:
            sensors.append(Metric(key, name, lambda k=key: stored(k)))
            sensors.append(Metric(key+"_time", name+" received", lambda k=key: stored(k+"_time"), kind="timestamp"))
        sensors.append(Metric("errors_today", "Observed errors today", lambda: daily("errors")))
        options = {str(option).lower() for k in event_keys for option in (coordinator.data[k].options or [])}
        for code in ("washing", "drying", "preheating", "cooking"):
            if code+"_is_complete" in options:
                sensors.append(Metric("last_"+code+"_notification", "Last "+code+" completion notification",
                    lambda c=code: stored("last_"+c+"_notification"), kind="timestamp"))
    for key in coordinator.data:
        if key.endswith("current_state"):
            prefix = key.removesuffix("current_state")
            location = prefix.rstrip("_").replace("_", " ").title()
            options = set(coordinator.data[key].options or [])
            is_laundry = "power_off" in options and "running" in options
            is_oven = "preheating" in options
            if not (is_laundry or is_oven):
                continue
            if prefix+"remain_hour" in coordinator.data:
                sensors.append(Metric(prefix+"remaining_minutes", location+" remaining minutes",
                    lambda p=prefix, k=key: minutes(flat(), p, "remain") if raw(k) in ACTIVE | OVEN_ACTIVE | {"pause"} else None, "min", "duration"))
            if is_laundry:
                sensors.append(Metric(prefix+"progress", location+" estimated progress",
                    lambda p=prefix, k=key: progress(raw(k), minutes(flat(), p, "remain"), minutes(flat(), p, "total")), "%"))
                stages = {"running": ACTIVE, "paused": {"pause"}, "drying": {"drying"}}
                for stage, active in stages.items():
                    binaries.append(Metric(prefix+stage, location+" "+stage,
                        lambda k=key, a=active: raw(k) in a if raw(k) is not None else None))
                for stage in ("washing", "drying", "paused"):
                    sensors.append(Metric(prefix+stage+"_minutes_today", location+" observed "+stage+" time today",
                        lambda p=prefix, s=stage: daily(p+s+"_seconds")/60, "min", "duration"))
                for days, label in ((1, "today"), (7, "last 7 days")):
                    sensors.append(Metric(prefix+"completed_"+str(days), location+" observed completed cycles "+label,
                        lambda p=prefix, d=days: daily(p+"completed_cycles", d)))
                sensors.extend([
                    Metric(prefix+"last_cycle_seconds", location+" last fully observed cycle duration", lambda p=prefix: stored(p+"last_cycle_seconds"), "s", "duration"),
                    Metric(prefix+"last_cycle_complete", location+" last observed cycle completion", lambda p=prefix: stored(p+"last_cycle_complete"), kind="timestamp"),
                ])
            if is_oven:
                for stage in ("preheating", "cooking_in_progress", "cooling", "cleaning"):
                    binaries.append(Metric(prefix+stage, location+" "+stage.replace("_", " "),
                        lambda k=key, s=stage: raw(k) == s if raw(k) is not None else None))
                    sensors.append(Metric(prefix+stage+"_duration", location+" observed "+stage.replace("_", " ")+" duration",
                        lambda k=key, s=stage: history.duration(k, dt_util.now(), {s}), "s", "duration"))
                for stage in ("preheat", "cook"):
                    sensors.append(Metric(prefix+"last_"+stage+"_complete", location+" last observed "+stage+" completion",
                        lambda p=prefix, s=stage: stored(p+"last_"+s+"_complete"), kind="timestamp"))
                for stage in ("preheat", "cooking"):
                    sensors.append(Metric(prefix+"last_"+stage+"_seconds", location+" last completed "+stage+" duration",
                        lambda p=prefix, s=stage: stored(p+"last_"+s+"_seconds"), "s", "duration"))
        elif key.endswith("cycle_count"):
            sensors.append(Metric(key+"_increments", "Observed "+key.replace("_", " ")+" increase today",
                lambda k=key: daily(k+"_increments")))
            sensors.append(Metric(key+"_reset", "Last observed "+key.replace("_", " ")+" reset",
                lambda k=key: stored(k+"_reset"), kind="timestamp", diagnostic=True))
        elif key.endswith("door_state"):
            prefix = key.removesuffix("door_state")
            label = prefix.rstrip("_").replace("_", " ").title()+" door"
            sensors.extend([
                Metric(prefix+"open_duration", label+" observed open duration", lambda k=key: history.duration(k, dt_util.now(), {"open"}), "s", "duration"),
                Metric(prefix+"openings_today", label+" observed openings today", lambda p=prefix: daily(p+"openings")),
                Metric(prefix+"open_minutes_today", label+" observed open time today", lambda p=prefix: daily(p+"door_open_seconds")/60, "min", "duration"),
                Metric(prefix+"last_open_seconds", label+" last observed open duration", lambda p=prefix: stored(p+"last_open_seconds"), "s", "duration"),
                Metric(prefix+"last_opened", label+" last observed opening", lambda p=prefix: stored(p+"last_opened"), kind="timestamp"),
                Metric(prefix+"last_closed", label+" last observed closing", lambda p=prefix: stored(p+"last_closed"), kind="timestamp"),
            ])
        elif key == "water_filter_state":
            binaries.append(Metric("filter_replacement_needed", "Water filter replacement needed",
                lambda: raw("water_filter_state") == "replace" if raw("water_filter_state") in {"good", "replace"} else None, kind="problem"))
        elif key == "express_mode":
            sensors.append(Metric("express_minutes_today", "Observed express mode time today", lambda: daily("express_seconds")/60, "min", "duration"))
            sensors.append(Metric("last_express_activation", "Last observed express mode activation", lambda: stored("last_express_activation"), kind="timestamp"))
        elif key.endswith("cook_mode") or key in {"express_mode_name", "oven_type"} or key.endswith("detergent_setting"):
            def metadata(k=key):
                value = raw(k)
                if value is None and k.endswith("detergent_setting"):
                    holders = coordinator.data[k].holders or []
                    for holder in holders:
                        values = holder.profile.get("r")
                        if isinstance(values, list) and len(values) == 1:
                            return str(values[0]).lower()
                return value
            sensors.append(Metric(key+"_reported", "Reported "+key.replace("_", " "), metadata,
                                  diagnostic=not key.endswith("cook_mode")))
    from .insights import extra_definitions
    extra_sensors, extra_binaries = extra_definitions(coordinator)
    return sensors + extra_sensors, binaries + extra_binaries


class MonitoringEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, metric):
        super().__init__(coordinator)
        self.metric = metric
        self._attr_name = metric.name
        self._attr_unique_id = coordinator.unique_id + "_monitor_" + metric.key
        self._attr_device_info = {"identifiers": {(DOMAIN, coordinator.unique_id)}}
        if metric.diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.monitoring.listen(self._handle_coordinator_update))

    @property
    def available(self):
        return self.metric.diagnostic or (self.coordinator.last_update_success and self.coordinator.monitoring.history.connected)

    @property
    def extra_state_attributes(self):
        attrs = {"source": "LG reports and local observations", "coverage": "observed intervals only"}
        if self.metric.key.endswith("_history_status"):
            prop = self.metric.key.removesuffix("_history_status")
            attrs.update(self.coordinator.insights.history.get(prop, {}))
            attrs["unit"] = "Wh"
        if self.metric.key == "command_status":
            attrs.update(self.coordinator.insights.command)
        return attrs


class MonitoringSensor(MonitoringEntity, SensorEntity):
    def __init__(self, coordinator, metric):
        super().__init__(coordinator, metric)
        self._attr_native_unit_of_measurement = metric.unit
        if metric.kind:
            self._attr_device_class = SensorDeviceClass(metric.kind)
        if metric.name.endswith("today") and not metric.diagnostic:
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        elif metric.unit and metric.kind not in {"timestamp", "energy"}:
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_suggested_display_precision = 1

    @property
    def native_value(self):
        value = self.metric.read()
        if self.metric.kind == "timestamp" and isinstance(value, str):
            return dt_util.parse_datetime(value)
        return value


class MonitoringBinarySensor(MonitoringEntity, BinarySensorEntity):
    def __init__(self, coordinator, metric):
        super().__init__(coordinator, metric)
        if metric.kind:
            self._attr_device_class = BinarySensorDeviceClass(metric.kind)

    @property
    def is_on(self):
        return self.metric.read()


def energy_definitions(coordinator):
    """Track each existing period independently; no synthetic zero on failure."""
    from .client.integration import ActiveMode, ThinQPropertyEx
    property_name = (ThinQPropertyEx.ENERGY_USAGE if coordinator.sub_id is None
                     else f"{ThinQPropertyEx.ENERGY_USAGE}_{coordinator.sub_id}")
    properties = coordinator.api.get_active_idx(property_name, ActiveMode.READ_ONLY)
    sensors, binaries = [], []
    for prop in properties:
        for period in ("today", "yesterday", "this_month", "last_month"):
            key = prop + "_" + period
            label = prop.replace("_", " ") + " " + period.replace("_", " ")
            def status(k=key):
                return coordinator.monitoring.energy.get(k, {})
            for field, name, kind in (("last_success", "last successful fetch", "timestamp"),
                                       ("last_attempt", "last fetch attempt", "timestamp"),
                                       ("error", "fetch status", None)):
                sensors.append(Metric(key+"_"+field, label+" "+name,
                    lambda f=field, read=status: (read().get(f) or "OK") if f == "error" and read().get("last_success") else read().get(f),
                    kind=kind, diagnostic=True))
            sensors.append(Metric(key+"_age", label+" fetch age",
                lambda read=status: (dt_util.now()-dt_util.parse_datetime(read()["last_success"])).total_seconds() if read().get("last_success") else None,
                "s", "duration", True))
            binaries.append(Metric(key+"_failed", label+" fetch failed",
                lambda read=status: bool(read().get("error")) if read() else None, kind="problem", diagnostic=True))
    return sensors, binaries
