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

