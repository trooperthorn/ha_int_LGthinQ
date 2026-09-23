# Official API call coverage inventory

LG reference: [ThinQ API](https://smartsolution.developer.lge.com/en/apiManage/thinq_connect). SDK reference: [`thinq_api.py`](https://github.com/thinq-connect/pythinqconnect/blob/1.0.14/thinqconnect/thinq_api.py). The baseline integration pins `thinqconnect==1.0.14`. “SDK method” means a callable exists, not that this fork offers a user-facing Home Assistant action or that every model supports it.

| Official call family | SDK method in 1.0.14 | Baseline use and phased disposition |
|---|---|---|
| `GET /route` | `async_get_route` | SDK supports discovery; audit where bridge uses it in Phase 1. |
| `GET /devices` | `async_get_device_list` | Device discovery; retain. |
| `GET /devices/{id}/profile` | `async_get_device_profile` | Profile-aware entities; add redacted capability inventory. |
| `GET /devices/{id}/state` | `async_get_device_status` | Initial/refresh state; add device-specific state mapping. |
| `POST /devices/{id}/control` | `async_post_device_control` | Existing entity controls use SDK commands. Expand only with profile-validated, conditional, explicit controls. |
| `GET /push`, `POST /push/{id}/subscribe`, `DELETE /push/{id}/unsubscribe` | Push list/subscribe/unsubscribe methods | MQTT push lifecycle exists in SDK; audit cleanup and event mapping. |
| `GET /push/devices`, `POST /push/devices`, `DELETE /push/devices` | Device-list push methods | Audit device add/remove/rename handling; no separate user action planned. |
| `GET /event`, `POST /event/{id}/subscribe`, `DELETE /event/{id}/unsubscribe` | Event list/subscribe/unsubscribe methods | MQTT status lifecycle exists in SDK; audit expiry/renewal and stale-state behavior. |
| `POST /client`, `DELETE /client`, `POST /client/certificate` | Client registration/deletion/certificate methods | Transport plumbing, not appliance controls. Audit certificate storage and unload behavior. |
| `GET /devices/energy/{id}/profile` | `async_get_device_energy_profile` | Energy capability detection; verify by model/country. |
| `GET /devices/energy/{id}/usage` | `async_get_device_energy_usage` | Baseline energy sensors include today, yesterday, this month and last month when data exists; test daily/monthly limits and rollovers. |

## Invocation policy

“All API calls supported” means the integration's lifecycle or a deliberate feature can invoke each relevant documented call where authorized. It does **not** mean offering dangerous raw HTTP or arbitrary control-payload execution in Home Assistant. Read-only status/profile/energy access may be surfaced through diagnostics or sensors. Control calls are exposed as specific, model-checked entities or actions. Client, subscription and route calls remain transport lifecycle operations.

LG documents PAT scopes, country-specific endpoints, and model-specific property permissions. A call may return unsupported-model, unsupported-property, country, authority, state, or rate-limit errors. Tests must exercise those cases without treating a successful HTTP response as proof that the appliance changed state.

