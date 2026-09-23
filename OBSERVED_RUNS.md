# Owner probe observations (2026-09-23)

The owner captured four appliance conditions and one intentionally invalid-PAT run with the Windows probe. This is a compact, identifier-free summary. The original diagnostic files remain local and are excluded from Git.

| Run | Standard washer | Washer/dryer combo | Oven |
| --- | --- | --- | --- |
| 1: devices off | `POWER_OFF`, remote disabled | `POWER_OFF`, remote disabled | `INITIAL`, remote disabled |
| 2: combo drying | `POWER_OFF` | `DRYING`, remote enabled, 1 h 18 min remaining | `INITIAL` |
| 3: washer running; combo and oven remote | `RUNNING`, remote enabled, 2 h 13 min remaining | `INITIAL`, remote enabled, 1 h 30 min delay to start | `INITIAL`, remote enabled |
| 4: both washing; oven on | `RUNNING`, remote enabled, 2 h 9 min remaining | `PREWASH`, remote enabled, 4 h 15 min remaining | `PREHEATING`, remote disabled, `BAKE`, 350 °F target |
| Invalid PAT | No device calls | No device calls | No device calls |

The invalid-PAT probe received HTTP 401 with no JSON body on its first `GET /devices`; it made no later calls. The pinned SDK parses a JSON body before checking HTTP status. `ThinQGuardedApi` maps an HTTP 401 to the SDK's invalid-token exception before body parsing. Home Assistant setup treats that code as an authentication failure, avoiding repeated setup attempts with a rejected credential.

Across the four valid runs, every device profile was unchanged after ignoring response timestamps, message IDs, and array order. All device profile and state GETs returned HTTP 200. The oven energy-profile GET returned HTTP 406 without a body in every run; the other three energy profiles returned HTTP 200 with `energyUsage`. Energy usage itself was not queried.

## Interpretation and remaining checks

- LG reports both laundry appliances as `DEVICE_WASHER`. The owner-labeled combo is the one that entered `DRYING` and `PREWASH`; its profile also advertises `DRYING_IS_COMPLETE`. Identify behavior from per-device capabilities and state, not the type string alone.
- `remoteControlEnabled` changes with appliance condition. It was true during washer operation and combo drying, but false for the oven while preheating. It must not be treated as an appliance power or run-state sensor.
- Writable profile modes indicate possible commands. No control POST was tested, so accepted transitions and remote-enable requirements still need device-specific validation.
- The oven state exposed target temperature, but no measured cavity temperature in these runs. Do not label the target as current temperature.

