# Observed model support and validation

This matrix describes the owner's four devices captured on 2026-09-23. LG reported both laundry units as `DEVICE_WASHER`; the combo label comes from observed `DRYING` behavior, not a distinct device type. A profile advertises possible commands, but no control POST has yet been tested.

| Function | Refrigerator | Oven | Standard washer | Washer/dryer combo |
| --- | --- | --- | --- | --- |
| Type discovery and state GET | Observed | Observed | Observed | Observed |
| Event notifications | Profile lists events | Profile lists events | Profile lists events | Includes `DRYING_IS_COMPLETE` |
| Temperature set point | Fridge 33–43 °F, freezer −7–5 °F; writable profile and local range guard | Writable profile; idle remote-start guard | N/A | N/A |
| Door/remote state | Door profile state | Remote-start state, varies by cavity state | Remote state | Remote state |
| Operation commands | Express mode advertised writable | Bake, temperature and start observed by owner; integration POST retest pending | START/STOP/POWER_ON/POWER_OFF advertised | Same commands advertised |
| Energy profile | HTTP 200 | HTTP 406, unavailable on tested model | HTTP 200 | HTTP 200 |
| Hardware validation of integration command | Pending | Pending after revised guard | Pending | Pending |

The integration creates entities only from each device's profile permissions. Read-only `powerSaveEnabled` and `sabbathMode` are reported as binary sensors for this refrigerator and are not presented as writable switches. Target temperature is a requested setting, not a measured interior temperature.

## Final live control sequence

After installing the new PR build, verify displayed states and diagnostics first. Then use the owner's selected safe appliance conditions to test one control at a time: refrigerator set point within the profile range and an invalid range rejection; oven idle with remote dial disabled, idle with remote dial enabled, and running with remote flag false; washer START/STOP on each device only when physically safe. Record before/after entity states and redacted API status/error codes. Do not run these controls automatically from the test suite.

