# Home Assistant insights and actions (0.3.0)

This release adds HA functionality only. Add/remove/re-register appliances in LG ThinQ. No Android app or custom enrollment API is included. Existing entity unique IDs remain unchanged.

## New entities

| Entities | Behavior |
|---|---|
| Remote action eligibility | Reports unavailable state, missing remote flag, remote enabled or remote disabled. This is a readiness hint, not a guarantee LG will accept a command. |
| Last command outcome/time/error | Observes actual control POSTs from existing entity platforms and the new start-in-mode action. Sending, failed, accepted, state_confirmed, accepted_unconfirmed, or unconfirmed_after_restart. Errors contain codes rather than vendor messages. |
| MQTT certificate expiry | Public certificate expiration timestamp only. No certificate, CSR, token, or private key is exposed. |
| Cloud subscription status/check time | Tracks subscribe results; an explicit action audits current subscriptions against current LG inventory. A removed appliance is excluded from expected subscriptions. |
| Observed cycles since maintenance / reminder due | Local observed completed cycles since reset. Set your own interval; 0 disables the reminder. This is not LG's factory tub-clean counter. Gaps/restarts do not invent completions. |
| Reported laundry mode | Created only if a readable MAIN mode is advertised. Recognizes both documented `washerOperationMode` and retained SDK `washerMode` paths; ambiguous profiles are rejected. |
| Reported delay timer components | Separate advertised relative start/stop hours and minutes. No claim that a timer is active merely because a component is present. |
| Previous 7/30-day energy, 30-day daily average, estimated 30-day cost | Completed days only. Missing days or fetch errors yield unknown rather than an incomplete total presented as complete. Uses the integration's existing Wh mapping; tariff is per kWh in HA's configured currency. |
| Energy history fetch status | Attributes include up to 30 daily values and 12 monthly values, attempt/success timestamps, and sanitized error. Current month may be provisional. Prior successful history remains inspectable after a failure. |
| MAC address | Only created if LG explicitly supplies a validated, unambiguous appliance MAC in device metadata. Also exposed through the query action and as an HA network-MAC connection for a main appliance. |

Historical energy requests are opt-in (`configure_monitoring`, history_enabled). Once enabled, the local 30-second clock schedules one daily batch: two GETs per advertised energy property. `refresh_energy_history` performs a deliberate batch on demand. Concurrent history batches are serialized. It does not increase ordinary device-state polling. Existing current-day/month energy sensors retain their schedules. Flat-tariff costs cannot accurately model time-of-use tariffs. Do not sum combined and component energy properties together.

Command confirmation requires a subsequent report/GET containing the exact requested values. Write-only START and other commands without matching readable fields may remain accepted_unconfirmed after 120 seconds even if they worked. There are no automatic control retries. Confirmation means matching reported state, not proof of physical operation or causation. A new command replaces the previous command's diagnostic state.

## Actions for scripts

All device-targeted actions accept `device_id`, the **Home Assistant device registry ID**, selected through the UI. It is not LG's cloud ID. Response data is optional and can be assigned with `response_variable`.

| Action (`lg_thinq_extended.` prefix) | Inputs beyond device_id | Result |
|---|---|---|
| `get_device_data` | `refresh: false` by default | Mapped state, flattened capabilities (including extension properties), observed raw field paths, command result, history, settings, maintenance and MAC if reported. Refresh performs one state GET. |
| `refresh_capabilities` | None | Fresh profile; changed/reload_scheduled flags. Reload discovers newly advertised entities. |
| `configure_monitoring` | Optional `history_enabled`, `tariff_per_kwh`, `maintenance_interval` | Persisted settings. Interval 0 disables reminder. |
| `reset_maintenance` | None | Reset local observed-cycle baseline after performing maintenance. |
| `refresh_energy_history` | None | Bounded daily/monthly history per advertised energy property. |
| `refresh_subscription_health` | None | Subscription audit status and timestamp; failed check does not claim a broken appliance. |
| `start_laundry_mode` | `mode: WASHING/DRYING/WASHING_DRYING`; `location: MAIN/MINI` | **Starts a cycle**, after a fresh profile and remote-ready check. No POST if permission/mode/remote flag is missing. API acceptance is not confirmation. |
| `refresh_devices` | `config_entry_id` instead of device_id | Schedules account inventory reconciliation, including when no appliance is loaded. Does not add/remove anything in LG. |

User device still classified DEVICE_WASHER without a writable mode: dry-only action remains unavailable/rejected. No model-name override or guessed control payload is used. Existing mappings remain unchanged; the new mode action resolves the exact path from the fresh profile.

## Automation events

- `lg_thinq_extended_inventory_changed`: config_entry_id, added/removed/renamed lists of LG IDs, and managed_in = LG ThinQ app. Inventory signals are coalesced; one event may describe several changes.
- `lg_thinq_extended_capabilities_changed`: HA device_id and device_ref when the explicit profile refresh detects a change.
- `lg_thinq_extended_command_result`: config_entry_id, device_ref, status, timestamp, sanitized payload and error; confirmation may add confirmed_at. Device_ref here is the integration's local unique ID, also returned by get_device_data.

These events/data stay in HA and may appear in automation traces. Downloaded diagnostics continue to redact MAC/account/network identifiers. New errors and connection failures are not hidden.

## Device inventory and UniFi

Inventory notifications trigger an authoritative GET, followed by a reload for changes. Unknown/late messages from unloaded devices use debug logging. Expected missing-device/missing-subscription errors during teardown are idempotent cleanup. An empty account is normal. Malformed/failed inventory does not authorize removal. Registry cleanup is scoped to this config entry and current LG inventory, not to whichever profiles happened to load. HA 2026.9 has per-config-entry devices; removing this integration's appliance does not remove UniFi's device. A reload can briefly make entities unavailable.

No MAC was present in the supplied OpenAPI or owner captures. The implementation accepts explicit mac/macAddress/mac_address/wifiMacAddress metadata, normalizes separators, and rejects multicast, zero, malformed, or conflicting values. It never derives a MAC from an LG device ID or assumes a gateway/AP MAC is the appliance. HA's network-MAC connection can link matching physical devices across integrations; it does not rename, adopt, or configure clients in the UniFi controller. No manual MAC association is fabricated. WashTower subdevices do not each claim the same MAC connection.

References: [HA device registry](https://developers.home-assistant.io/docs/device_registry_index/), [HA registry changes](https://developers.home-assistant.io/blog/2026/08/19/device-registry-websocket-api-changes/), [HA response actions](https://developers.home-assistant.io/docs/dev_101_services/).

## Examples and acceptance

`examples/lg_insights_package.yaml` contains scripts with device selectors and passive inventory/command notifications. It can be included as an HA package; review names and notifications before enabling. Other useful automations: fridge door-open duration threshold; filter replacement needed; maintenance reminder due; energy budget exceeded; cloud certificate expiry approaching. Select the relevant generated sensor in HA's automation editor because entity IDs depend on the user's device names.

Offline tests exercise aliases/permissions, no POST when remote-disabled, state confirmation boundaries, energy gaps/failures, inventory bursts/late messages, registry removal and MAC validation. Real HA runtime tests mock LG calls. Live acceptance still requires owner testing: setup/reload, add/remove in the LG app, maintenance reset, energy history availability and one supervised mode start only if LG advertises support. No live device commands were sent during development.
