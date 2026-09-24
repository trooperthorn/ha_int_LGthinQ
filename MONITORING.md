# Monitoring added from the owner captures (0.2.1)

These additions build on the direct client in PR11. Existing entity unique IDs are preserved. All new entities use a separate `_monitor_` unique-ID namespace and are created only when their source exists in the device profile/mapping.

## Added entities

| Device | New monitoring |
|---|---|
| Both laundry devices | Numeric remaining minutes; estimated progress; running, paused, drying indicators; observed washing/drying/paused minutes today; completed cycles today and last seven days; last observed completion; duration of the last fully observed cycle; cycle-counter increases today and last observed reset; reported detergent configuration (NORMAL/AUTO). |
| Refrigerator | Current and previous observed door-open duration; observed openings and open minutes today; last observed door opening/closing; water-filter replacement-needed flag; express-mode observed runtime and last activation; reported express-mode type. Existing filter age and GOOD/REPLACE status remain. |
| Oven | Preheating/cooking/cooling/cleaning indicators and observed durations; last completed preheat/cooking duration; numeric remaining minutes; read-only reported cook mode; reported cavity type. Existing remote-ready and target-temperature entities remain. |
| Event-capable devices | Persistent last notification/error and received timestamp; observed error count today; completion notification timestamps for the codes each profile advertises. |
| Every device | Last state fetch, last device report, report age, capability-change timestamp, cloud MQTT connection, session reconnect count and last disconnect. |
| Each existing energy property and period | Last fetch attempt, last successful fetch, fetch age, fetch status and failure flag. The energy value becomes unavailable on error; attributes retain last good value, timestamps and sanitized error code. |

## Meaning and limitations

- Remaining time is calculated from numeric components, including hour values above 23. Existing estimated completion timestamps remain.
- Progress is an estimate from total and remaining duration, not a measured percentage. Invalid/zero totals, revised remaining time exceeding total and idle states yield unknown.
- Durations and counts describe observed intervals. They exclude known MQTT disconnects and do not bridge restarts. Counters and event history persist locally. Daily counters follow Home Assistant's configured timezone; seven-day cycle totals include today.
- A cycle completion requires an observed active cycle followed by END. Repeated END reports and duplicate notifications do not create extra completed cycles. POWER_OFF/STOP is not a completion. Push completion timestamps are separate from cycle counts, because a wash-and-dry load can have multiple completion messages.
- If tracking starts mid-cycle, the integration does not claim a fully observed cycle duration. Historical counters are not lifetime appliance statistics. Counter reset timestamps do not assert a tub-clean cycle occurred.
- A notification/error field that is empty can still show OK in the existing companion sensor. The new last-message entities retain history; a past message is not proof of an active fault. Identical pushes within 60 seconds are deduplicated for local message history.
- Door intervals use cloud receipt times. Only the reported MAIN door is monitored. The log's `usedTime=6` retains the existing months unit, not minutes.
- NORMAL/AUTO is profile metadata, not detergent quantity. Refrigerator/oven temperature targets remain targets, not measured temperatures.
- An old report alone does not prove the appliance is offline. The connection indicator describes the shared LG MQTT connection, not appliance Wi-Fi connectivity.
- Fetch age describes successful retrieval, not the age of LG's underlying aggregated energy measurement. In particular, error 1212 does not produce a false zero or a fresh reading.
- Metrics update locally every 30 seconds. This creates no additional cloud requests and does not re-fire appliance event entities. Local history retains 35 daily buckets.

## Scope

This change adds monitoring supported by the actual captured fields and notifications. Historical energy windows, tariff-dependent costs, configurable maintenance thresholds and unsupported sensor hardware values are not inferred from the logs. Separate wash/dry energy categories remain unavailable unless LG advertises them. No new POSTs or controls are added.

## Verification

- Offline tests cover the captured 17.999-second refrigerator opening, duplicates, midnight rollover, reconnect/restart gaps, combined wash/dry completion, STOP vs END, cycle-counter reset, invalid estimates, and durations above 23 hours.
- CI instantiates the monitoring entities from the four device fixtures against Home Assistant 2026.9 and exercises successful energy refresh followed by error 1212. It verifies the last good reading survives while availability becomes false.
- Live acceptance: install 0.2.1 and restart; inspect new entities under each device. Open/close the refrigerator, let a normal laundry cycle complete, and verify the displayed counters/times. Restart to check retained history. MQTT outage tests should leave a gap, not count the disconnected interval. No live appliance commands were sent during development.
