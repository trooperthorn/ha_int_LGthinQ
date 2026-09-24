# First Home Assistant setup and reload (2026-09-23)

The owner supplied setup and reload debug logs after changing the SDK dependency to `thinqconnect==1.0.13`. The original logs are private and are not committed.

| Check | Observed result |
| --- | --- |
| Dependency installation | Setup progressed past the previous `cryptography` resolver failure. |
| Device discovery | Four devices were found: refrigerator, oven, washer, and washer/dryer combo (both laundry devices report `DEVICE_WASHER`). |
| Initial state | Four coordinators fetched data successfully; matching entities were created. |
| MQTT setup | Client certificate request, push/event subscriptions, MQTT connection, and topic subscription completed. Three subsequent washer status pushes were processed in each log. |
| Reload teardown and reconnect | The reload log shows push/event unsubscription and client deletion, then successful setup and MQTT resubscription. A later teardown also completed. |
| Oven energy | Energy-profile GET returned LG code `1221` (`NOT_SUPPORTED_PRODUCT`); the SDK handled it as no energy profile, and oven setup continued. |

The reload log also contains Shelly and Cast errors unrelated to `lg_thinq_extended`. Neither log contains an LG integration ERROR or WARNING line. These observations establish one successful runtime setup and reload path; they do not validate appliance control POSTs or every entity's semantics.

## Debug-log privacy

The pinned SDK logs raw device IDs in request URLs, profile contents, MQTT client identifiers, and certificate response data at DEBUG level. The owner removed certificate text before sharing, but other identifiers remained in the private logs. This fork now redacts its own MQTT event debug line. SDK logs still require manual review before sharing; avoid publishing raw setup/reload logs.



## LG app re-addition test and 0.3.1 fixes (September 23 local / September 24 UTC)

Owner report: the physical WM6998HBA was added using the Dryer choice in LG ThinQ, but LG displayed it as a washer; Home Assistant discovered it automatically.

The private log records an absent appliance detached at 22:20:48, LG inventory reconciliation at 22:44:17, coordinator setup as Washer/FAFXU23001 at 22:44:21, another inventory reconciliation at 22:44:26, and setup under the alias Washer/Dryer at 22:44:32. This validates discovery and alias reconciliation for this attempt. It does not prove the earlier detach was triggered live rather than detected at startup. The newly returned profile advertises DRYING_IS_COMPLETE but no mode property. Re-onboarding therefore did not expose dry-only mode control. Renaming the alias does not change the cloud capability profile.

The same log reveals a genuine monitoring regression: the 30-second callback ran in HA's executor because it lacked the callback annotation, then attempted async_write_ha_state. Version 0.3.1 marks that callback for event-loop execution. A regression test invokes the actual HA interval scheduler and verifies the listener thread, rather than calling tick directly.

Eleven MQTT status messages were rejected by the dict-only report check. The discarded payloads were not logged, so their exact shapes cannot be reconstructed. The handler now accepts location-tagged lists supported by the existing appliance mapper, preserves dictionary reports, and accepts the documented event envelope. Tests show a washer list report updates run state, remaining time and the response-action cache. Unsupported shapes still log only their type, not private payloads. Multi-component devices dispatch to their loaded coordinators. Paho message delivery no longer waits synchronously for HA processing, avoiding an unload/network-thread wait cycle.

Verification: 50 offline tests, existing HA monitoring/action checks, and the new real-scheduler/location-report regression pass locally. Live acceptance after installation: verify no async_write_ha_state thread warnings over several 30-second intervals, and confirm washer power/state changes update without rejected-report warnings. No live control calls were sent by development tools. Original logs remain private.
