# Windows ThinQ Connect probe

`ThinQ-Probe.ps1` collects evidence for **Refrigerator, Oven, Washer, Dryer, WashTower, and WashCombo** development on a Windows PC. It uses LG's official ThinQ Connect API. The script asks for your Personal Access Token (PAT) in a secure prompt, uses it only for the current process, and writes redacted JSON files to `tools/diagnostics`. Nothing is uploaded by the script.

## Before running

1. Generate a PAT at [LG's PAT site](https://connect-pat.lgthinq.com/) with device-list, status, and energy inquiry permissions. For a POST test, also select device-control permission.
2. Install no Python packages: the script uses Windows PowerShell 5.1 or later.
3. Review the script and output before sharing diagnostics. Redaction covers common account, network, and device identifiers, but an unexpected vendor field could still contain private data.
4. Run `powershell.exe -NoProfile -File .\tools\ThinQ-Probe.ps1 -SelfTest` from the repository root to check the redaction path without contacting LG.

## Read-only collection

From a PowerShell prompt in the repository root:

```powershell
powershell.exe -NoProfile -File .\tools\ThinQ-Probe.ps1 -Country US -Region America
```

Use `Europe` or `Asia` for the corresponding LG regional API endpoint. The tool calls `GET /devices` first and saves **every device and its reported type** in `00_device_type_inventory.json`. This is the list observed on your LG account, not a global catalog of every type LG supports. The console prints every device number, type, and LG's `modelName` value. That value may be an opaque internal identifier; do not assume it is the retail model number. The tool then calls `GET /push`, `GET /push/devices`, `GET /event`, and profile, state, and energy-profile GETs for priority devices. Use `-IncludeEnergyUsage -EnergyProperty PROPERTY_NAME` to try today's daily energy GET after identifying a property in the energy profile. API errors are recorded with HTTP status and LG's redacted JSON error body.

The detailed probe includes refrigerator, oven, washer, dryer, tower, and combo type names, including previously unseen names containing WASH, DRY, or COMBO. It excludes `DEVICE_DISH_WASHER`. Both of your washers will appear in the complete inventory even if LG assigns the combo a different type. `group_ref` helps identify linked tower parts without exposing the raw group ID. The probe collects detailed responses for up to eight priority devices by default; use `-MaxDevices 50` to include more or `-DeviceId` to focus on one known device. Each output filename and device reference uses a shortened hash. A run summary is saved as `00_summary.json`.

## Exact WashCombo device-type check

Run `tools\Find-WashCombo.ps1` from Windows PowerShell. It filters the reported type exactly to `DEVICE_WASHCOMBO_MAIN` and saves profile/state/energy-profile GETs only for matching devices. It never sends a control POST.

```powershell
powershell.exe -NoProfile -File .\tools\Find-WashCombo.ps1 -Country US -Region America
```

The output folder is printed at the end and defaults to a timestamped `tools\diagnostics\washcombo-type-check-*` directory. `00_device_type_inventory.json` records the requested type, match count, and counts for all observed types; its device detail list contains only matches. The initial `GET /devices` response file still contains the redacted complete account device list because LG returns all devices in that call. If the match count is zero, the script does not query any device profile or state. This is meaningful: the owner's earlier ThinQ Connect inventory labeled both physical laundry appliances `DEVICE_WASHER`, even though one is a washer/dryer combo. LG's retail WM6998HBA designation does not itself determine the API type.

## Optional control POST

Only perform this with a payload you have checked against **your device's** LG profile and current state. A control can start an appliance, including an oven. The script will never send a POST in its default read-only mode.

```powershell
powershell.exe -NoProfile -File .\tools\ThinQ-Probe.ps1 -Country US -Region America -ExecuteControl -ControlDeviceNumber 2 -ControlPayloadPath .\my-control.json
```

The selected device number comes from the displayed list. The tool checks that the device exists, requires you to type `CONTROL`, then uses PowerShell's confirmation prompt before `POST /devices/{deviceId}/control`. It records the redacted request and response and performs a follow-up state GET. `-WhatIf` can be added to inspect the sequence without sending the POST.

The script does **not** validate a control payload against every LG profile rule. A POST result is evidence of API acceptance or rejection; compare the follow-up state and physical appliance before concluding the operation succeeded. Never put a PAT in a payload file, issue, or shared diagnostic bundle.

## Log handling

`tools/diagnostics` is ignored by Git. Before sharing, inspect every JSON file for account names, network data, precise location, or anything you consider private. Send only the redacted files needed to explain a specific API behavior; keep the PAT private.

