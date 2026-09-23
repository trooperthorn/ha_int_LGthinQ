# Live control POST test

This build sends LG ThinQ Connect control POSTs when a supported Home Assistant number, select, or switch control is used. The Windows probe also supports an explicit `-ExecuteControl` POST and saves a before/after state GET. No POST runs during installation, setup, diagnostics, or the automated tests.

Use a PAT with device-control permission. Install the PR build, restart Home Assistant, and confirm all four devices load before testing. Test one appliance and one control at a time, with someone present at the appliance. Record the starting value, the selected command, the state 10–30 seconds later, and whether the physical appliance changed. Preserve any Home Assistant service error text and share only redacted logs.

| Appliance | First control test | Expected local guard | Result to record |
| --- | --- | --- | --- |
| Refrigerator | Change the fridge or freezer target by one supported step in its Home Assistant number entity; return it to the original value afterward. | Out-of-range or fractional settings must be rejected locally, before POST. Fridge profile: 33–43 °F. Freezer profile: −7–5 °F. | Requested and reported target, LG app value, physical display value, error code if any. |
| Oven | With the remote dial armed and the cavity idle, select a mode or target temperature that you intend to run. Then turn the oven off and check whether controls become unavailable until the dial is reset. | Idle plus remote disabled blocks POST. An active cavity remains controllable even when LG reports remote-start disabled, as observed during preheating. | Remote-ready sensor, operation select, target temperature, before/after run state and physical heat state. |
| Standard washer | With a safe load and remote start prepared at the machine, choose START from its operation select. Test STOP only when safe. | Only profile-advertised operation options appear; the current display state is not sent as a command. | Current state, remote flag, selected command, actual machine action. |
| Washer/dryer combo | Repeat the washer test on the second `DEVICE_WASHER`; observe the dry phase separately. | Do not infer combo capability from `DEVICE_WASHER` alone. | Current state through wash/dry transition, completion event, actual machine action. |

Known entity IDs from the owner: `select.oven`, `select.oven_2`, `select.top_load_washer`, and `select.utility_room_washer`. Select options and refrigerator number entity IDs should be confirmed in the live Home Assistant UI because they depend on the reported device profile and entity registry.

The Windows probe instructions are in [tools/README.md](tools/README.md). It requires an explicit device selection, a control payload file, and an interactive confirmation. The probe does not validate arbitrary payloads against all LG profile rules; use the Home Assistant entities for the first live control tests.

