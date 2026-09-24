"""Local appliance observations; no network calls or Home Assistant dependency."""
from datetime import datetime, timedelta, timezone
import hashlib
import json

ACTIVE = frozenset({"running", "soaking", "dispensing", "refreshing", "prewash",
    "drying", "spinning", "detergent_amount", "steam_softening", "add_drain",
    "rinsing", "detecting", "rinse_hold", "frozen_prevent_running"})
OVEN_ACTIVE = frozenset({"preheating", "cooking_in_progress", "cleaning", "cooling"})


def minutes(data, prefix, kind):
    """Use raw components, including durations beyond datetime.time's 23 hours."""
    hour, minute = data.get(prefix + kind + "_hour"), data.get(prefix + kind + "_minute")
    if not isinstance(hour, (int, float)) or not isinstance(minute, (int, float)):
        return None
    second = data.get(prefix + kind + "_second", 0) or 0
    return hour * 60 + minute + second / 60


def progress(state, remaining, total):
    if state not in ACTIVE or remaining is None or not total or remaining > total:
        return None
    return round(max(0, min(100, 100 * (total - remaining) / total)), 1)


class Observations:
    """Persist counters, but never bridge an unobserved restart/disconnect interval."""

    def __init__(self, saved=None):
        self.saved = saved or {"values": {}, "days": {}}
        self.saved.setdefault("values", {})
        self.saved.setdefault("days", {})
        self.previous = {}
        self.since = {}
        self.cycles = {}
        self.last_tick = None
        self.connected = True

    @property
    def values(self):
        return self.saved["values"]

    def add(self, day, key, amount):
        bucket = self.saved["days"].setdefault(day, {})
        bucket[key] = bucket.get(key, 0) + amount
        # A bounded observation history, not unlimited recorder data.
        for old in sorted(self.saved["days"])[:-35]:
            del self.saved["days"][old]

    def total(self, now, key, days=1):
        return sum(self.saved["days"].get((now.date()-timedelta(days=i)).isoformat(), {}).get(key, 0)
                   for i in range(days))

    def gap(self):
        self.previous.clear()
        self.since.clear()
        self.cycles.clear()
        self.last_tick = None
        self.connected = False

    def advance(self, now):
        if self.last_tick and self.connected:
            cursor = self.last_tick
            while cursor < now:
                end = min(now, (cursor + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
                seconds = max(0, (end.astimezone(timezone.utc) - cursor.astimezone(timezone.utc)).total_seconds())
                for key, value in self.previous.items():
                    stage = None
                    if key.endswith("current_state"):
                        prefix = key.removesuffix("current_state")
                        stage = ("drying" if value == "drying" else "washing" if value in ACTIVE
                                 else "paused" if value == "pause" else value if value in OVEN_ACTIVE else None)
                    elif key.endswith("door_state") and value == "open":
                        prefix, stage = key.removesuffix("door_state"), "door_open"
                    elif key == "express_mode" and value in (True, "true"):
                        prefix, stage = "", "express"
                    if stage:
                        self.add(cursor.date().isoformat(), prefix+stage+"_seconds", seconds)
                cursor = end
        self.last_tick = now

    def observe(self, data, now):
        self.advance(now)
        self.connected = True
        day = now.date().isoformat()
        for key, value in data.items():
            if key.endswith("error"):
                if value and value != self.previous.get(key):
                    self.notification(str(value), now)
                self.previous[key] = value
            if key.endswith("cycle_count") and isinstance(value, (int, float)):
                prior = self.values.get(key+"_previous")
                if isinstance(prior, (int, float)) and value > prior:
                    self.add(day, key+"_increments", value-prior)
                if isinstance(prior, (int, float)) and value < prior:
                    self.values[key+"_reset"] = now.isoformat()
                self.values[key+"_previous"] = value
            if not (key.endswith("current_state") or key.endswith("door_state") or key == "express_mode"):
                continue
            old = self.previous.get(key)
            if old == value:
                continue
            started = self.since.get(key)
            self.previous[key] = value
            self.since[key] = now
            if key.endswith("door_state"):
                prefix = key.removesuffix("door_state")
                if value == "open":
                    self.values[prefix+"last_opened"] = now.isoformat()
                    if old == "close":
                        self.add(day, prefix+"openings", 1)
                elif value == "close":
                    self.values[prefix+"last_closed"] = now.isoformat()
                    if old == "open" and started:
                        self.values[prefix+"last_open_seconds"] = (now-started).total_seconds()
            elif key == "express_mode":
                if value in (True, "true"):
                    self.values["last_express_activation"] = now.isoformat()
            else:
                prefix = key.removesuffix("current_state")
                if old == "preheating" and value == "cooking_in_progress" and started:
                    self.values[prefix+"last_preheat_seconds"] = (now-started).total_seconds()
                    self.values[prefix+"last_preheat_complete"] = now.isoformat()
                if old == "cooking_in_progress" and value == "done" and started:
                    self.values[prefix+"last_cooking_seconds"] = (now-started).total_seconds()
                    self.values[prefix+"last_cook_complete"] = now.isoformat()
                if value in ACTIVE and old not in ACTIVE and old != "pause":
                    # If first seen mid-cycle, duration is deliberately not asserted.
                    self.cycles[prefix] = {"start": now if old in {"initial", "power_off", "end", "reserved"} else None,
                                           "dry": value == "drying"}
                if value == "drying" and prefix in self.cycles:
                    self.cycles[prefix]["dry"] = True
                if value == "end" and prefix in self.cycles:
                    cycle = self.cycles.pop(prefix)
                    self.add(day, prefix+"completed_cycles", 1)
                    self.values[prefix+"_maintenance_observed"] = self.values.get(prefix+"_maintenance_observed", 0) + 1
                    self.values[prefix+"last_cycle_complete"] = now.isoformat()
                    if cycle["start"]:
                        self.values[prefix+"last_cycle_seconds"] = (now-cycle["start"]).total_seconds()
                    else:
                        self.values.pop(prefix+"last_cycle_seconds", None)
                elif value in {"power_off", "error"}:
                    self.cycles.pop(prefix, None)

    def duration(self, key, now, active):
        if not self.connected or self.previous.get(key) is None:
            return None
        if self.previous[key] not in active:
            return 0
        return max(0, (now-self.since[key]).total_seconds())

    def notification(self, message, now):
        """Record delivered messages, independently from sticky entity fields."""
        if not isinstance(message, str) or not message:
            return
        message = message.lower()
        prior = self.values.get("last_notification_time")
        if self.values.get("last_notification") == message and prior:
            if (now-datetime.fromisoformat(prior)).total_seconds() < 60:
                return
        self.values["last_notification"] = message
        self.values["last_notification_time"] = now.isoformat()
        if "error" in message or "failed" in message:
            self.values["last_error"] = message
            self.values["last_error_time"] = now.isoformat()
            self.add(now.date().isoformat(), "errors", 1)
        if message in {"washing_is_complete", "drying_is_complete", "preheating_is_complete", "cooking_is_complete"}:
            self.values["last_"+message.removesuffix("_is_complete")+"_notification"] = now.isoformat()


def capability_digest(profiles):
    """LG can reorder enum values without changing a device capability."""
    def normalize(value):
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return sorted((normalize(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, default=str))
        return value
    return hashlib.sha256(json.dumps(normalize(profiles), sort_keys=True, default=str).encode()).hexdigest()
