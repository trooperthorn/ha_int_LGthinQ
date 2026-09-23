# Phased implementation plan

Status: first Phase 1 diagnostic and Windows probe work started on 2026-09-23. No appliance control changes are claimed as implemented.

Install blocker found on the owner's Home Assistant: `thinqconnect==1.0.14` requires `cryptography>=50.0.1`, conflicting with Home Assistant's `cryptography==48.0.1` pin. The fork now pins SDK 1.0.13 pending a Home Assistant runtime retest. SDK 1.0.13 has the device, profile, state, energy, and authentication methods used by this fork. This is a dependency compatibility change, not proof that setup succeeds end to end.

See [OBSERVED_RUNS.md](OBSERVED_RUNS.md) for the four captured appliance conditions and the invalid-PAT run. The invalid-key response drove the authentication guard; the changing washer, combo, and oven states define initial acceptance fixtures.

## First owner-account probe (2026-09-23)

- `GET /devices` returned four devices: two `DEVICE_WASHER`, one `DEVICE_REFRIGERATOR`, and one `DEVICE_OVEN`. LG does not distinguish the washer/dryer combo by device type on this account. The returned `modelName` strings are opaque identifiers here, not confirmed retail model numbers. The two washers must be evaluated by their individual profiles and observed behavior.
- Both washer profiles advertise writable `washerOperationMode` (`START`, `STOP`, `POWER_OFF`, `POWER_ON`) and writable `relativeHourToStart`; neither snapshot had remote control enabled. One washer profile also advertises `DRYING_IS_COMPLETE`. The owner considers this the likely combo, but the physical mapping remains unverified. No control POST was tested.
- The refrigerator profile advertises writable fridge/freezer target temperatures and `expressMode`. Its `powerSaveEnabled` and `sabbathMode` are read-only for this model. The state includes water-filter replacement status.
- The oven profile advertises writable oven operation, cook mode, target temperature, and timer fields. Its energy-profile GET returned HTTP 406 with no response body; treat energy as unavailable for this model until further evidence.
- The other three energy-profile GETs returned HTTP 200 with `energyUsage` in the response. Daily usage was not queried. All device profile and state GETs returned HTTP 200.

These findings are from one owner's redacted diagnostic run, not a general LG model-support guarantee. Keep the original diagnostic files local and out of Git.

## Principles

1. Use only LG ThinQ Connect PAT endpoints for this fork. A legacy WideQ property is a lead to investigate, not proof that Connect exposes it.
2. Model profiles govern every entity and command. Check read/write permission, allowed values, current state, and model-specific location before invoking a command.
3. Keep event state, current state, daily/monthly energy, and instantaneous power distinct.
4. Preserve LG cloud error codes and avoid automatically retrying rejected control commands.
5. Do not log PATs, client certificates, raw personal data, or unredacted device IDs in diagnostics.

## Phase 0 — Baseline and reproducibility

- Pin an upstream Home Assistant commit and `thinqconnect` release; retain file hashes and Apache-2.0 attribution.
- Confirm the renamed domain loads on the target Home Assistant release. Validate config flow, entity creation, reload, MQTT reconnect, unload, and diagnostics without a live control call.
- Add a small profile/state fixture set for each priority family, with IDs and account data removed.
- Establish static checks and an isolated HA test environment. Record upstream parity gaps caused by the domain rename.

**Gate:** clean setup/unload and no collision with built-in `lg_thinq`; tests pass on the pinned HA version.

## Phase 1 — Official API coverage and capability inventory

- Inventory the pinned 1.0.13 SDK calls against every documented route (see `API_COVERAGE.md`). Record which are used directly, by the SDK bridge, or unused.
- Add a redacted diagnostic report containing device type, profile property paths, read/write flags, enum/range constraints, notification codes, state path presence, and energy profile availability. No PAT or MQTT certificate output.
- Check event subscription expiry and renewal against current LG documentation. The SDK source and displayed LG documentation appear to disagree on the expiry value; resolve with a safe, read-only source audit before changing subscription timing.
- Expose a read-only capability view for unsupported properties, rather than silently claiming support.

**Gate:** an owner can determine what each actual model advertises without exposing secrets.

## Phase 2 — Refrigerator

- Audit current mappings for compartment target temperatures, door status, express cooling/freezing, energy saving, Sabbath mode, fresh-air filter, and water-filter usage/notifications.
- Add missing read-only states first. Map writable compartment settings using the exact `locationName`, accepted unit, and profile range. Do not treat a target temperature as a measured internal temperature.
- Map additional writable toggles only when the profile advertises them. Verify multi-compartment models independently.
- Invoke controls through `thinqconnect`'s profile-aware device methods and its conditional-control request path; refresh state after a successful command.

**Gate:** each command is absent when unsupported; a test refrigerator returns the expected target/state after a command; invalid range/location never reaches LG.

## Phase 3 — Oven

- Audit cavity-level current status, measured/target temperature, mode, door/remote-start state, errors, preheat and cook-completion pushes.
- Add missing read-only entities and event mappings first. For writable operation, mode and temperature, verify cavity/location, remote-enable state, bounds, and allowed transitions.
- Provide explicit actions for supported start/stop/pause or mode changes rather than an unrestricted JSON command service. Do not send a start command when the profile or current status rejects it.
- Distinguish cooktop elements from oven cavities, including appliances that combine both.

**Gate:** model-specific commands pass fixture tests and real-device tests; unsupported and remote-disabled operations are rejected locally.

## Phase 4 — Washer and dryer

- Audit run state, stage, remaining/total/delay time, remote-enable, operation controls, cycle counts, detergent and completion/error notifications across washer, dryer, WashTower and WashCombo variants.
- Compare redacted official profile, snapshot and event payloads with the missing current-course, selected water-temperature, spin-speed, rinse and dry-level fields. Implement each as a sensor only when verified in ThinQ Connect for that model. Document a confirmed API gap otherwise.
- Map available start/pause/stop and delay controls. Require the profile's writable permission and remote-enable/state preconditions; treat course selection as unsupported until a writable official property is verified.
- Handle notifications as events so repeat completion messages are observable even when state text is unchanged.

**Gate:** stage/time and completion behavior match one real washer and dryer; no claim of course or option support without profile evidence.

## Phase 5 — Release and upkeep

- Validate PAT scopes, rate limits, country support, reconnect and backoff, certificate/subscription lifecycle, and energy daily/monthly rollovers.
- Publish a per-model support matrix that separates observed behavior from profile-only predictions.
- Add migration guidance from built-in `lg_thinq` and legacy `ha-smartthinq-sensors`, including duplicate-entity and automation implications.
- Tag a prerelease only after tests and pilot hardware validation; later release after issue feedback.

## Inputs needed for hardware validation

For each priority device: exact model, country, Home Assistant version, redacted ThinQ Connect profile and state diagnostics, entity list, and which LG-app actions the owner wants. Never request a PAT in an issue or diagnostic bundle.

