#requires -Version 5.1
<#
.SYNOPSIS
Collects redacted ThinQ Connect API evidence on Windows.
.DESCRIPTION
Reads device lists, profiles, states, subscriptions, and optional energy data.
No control is sent unless -ExecuteControl, -DeviceId, and -ControlPayloadPath
are all supplied and the operator types CONTROL at the prompt.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidatePattern('^[A-Z]{2}$')][string]$Country = 'US',
    [ValidateSet('America', 'Europe', 'Asia')][string]$Region = 'America',
    [string]$DeviceId,
    [int]$ControlDeviceNumber,
    [ValidateRange(1, 50)][int]$MaxDevices = 8,
    [string]$OutputDirectory,
    [switch]$IncludeEnergyUsage,
    [string]$EnergyProperty,
    [string]$ControlPayloadPath,
    [switch]$ExecuteControl,
    [switch]$SelfTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot 'diagnostics' }

# LG documents this as a fixed, public API key; it is not the user's PAT.
$script:ApiKey = 'v6GFvkweNo7DK7yD3ylIZ9w52aKBU0eJ7wLXkSR3'
$script:BaseUrl = @{
    America = 'https://api-aic.lgthinq.com'
    Europe  = 'https://api-eic.lgthinq.com'
    Asia    = 'https://api-kic.lgthinq.com'
}[$Region]
$script:ClientId = 'ha-int-lgthinq-probe-' + [guid]::NewGuid().ToString('N')
$script:Pat = $null
$script:Sequence = 0
$script:Results = New-Object System.Collections.Generic.List[object]
$script:DeviceRefs = @{}
$script:SensitiveKeys = '^(?i:authorization|access.?token|refresh.?token|token|secret|password|csr|certificate|private.?key|public.?key|mac.?address|mac|ssid|alias|nick.?name|email|user.?number|user.?list|account.?id|serial(?:no|number)?|ip.?address|client.?id|service.?id)$'

function Get-ShortHash {
    param([string]$Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text))
        return ([BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()).Substring(0, 16)
    }
    finally {
        $sha.Dispose()
    }
}

function Protect-String {
    param([string]$Value)
    if ($script:Pat -and $Value.Contains($script:Pat)) {
        $Value = $Value.Replace($script:Pat, '[REDACTED PAT]')
    }
    if ($Value -match '[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}' -or
        $Value -match '(?i)\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b' -or
        $Value -match '\b(?:\d{1,3}\.){3}\d{1,3}\b') {
        return '[REDACTED STRING]'
    }
    return $Value
}

function Protect-Value {
    param($Value, [string]$Key = '')
    if ($null -eq $Value) { return $null }
    if ($Key -match '^(?i:device.?id|group.?id)$') {
        $prefix = if ($Key -match '^(?i:group.?id)$') { 'group-' } else { 'device-' }
        return $prefix + (Get-ShortHash ([string]$Value))
    }
    if ($Key -match $script:SensitiveKeys) { return '[REDACTED]' }
    if ($Value -is [System.Collections.IDictionary]) {
        $safe = [ordered]@{}
        foreach ($keyName in $Value.Keys) {
            $safe[[string]$keyName] = Protect-Value $Value[$keyName] ([string]$keyName)
        }
        return $safe
    }
    if ($Value -is [pscustomobject]) {
        $safe = [ordered]@{}
        foreach ($property in $Value.PSObject.Properties) {
            $safe[$property.Name] = Protect-Value $property.Value $property.Name
        }
        return $safe
    }
    if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
        $items = New-Object System.Collections.Generic.List[object]
        foreach ($item in $Value) {
            $items.Add((Protect-Value $item ''))
        }
        return ,$items.ToArray()
    }
    if ($Value -is [string]) { return Protect-String $Value }
    return $Value
}

function New-MessageId {
    # Match canonical uuid4 bytes rather than Guid.ToByteArray's Windows order.
    $hex = [guid]::NewGuid().ToString('N')
    $bytes = New-Object byte[] 16
    for ($i = 0; $i -lt 16; $i++) {
        $bytes[$i] = [Convert]::ToByte($hex.Substring($i * 2, 2), 16)
    }
    $base64 = [Convert]::ToBase64String($bytes)
    return $base64.TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Test-PriorityDeviceType {
    param([string]$Type)
    if ($Type -eq 'DEVICE_DISH_WASHER') { return $false }
    return $Type -match '^DEVICE_.*(?:REFRIGERATOR|OVEN|WASH|DRY|COMBO)'
}

function Save-DeviceTypeInventory {
    param([object[]]$Entries)
    $items = New-Object System.Collections.Generic.List[object]
    $counts = [ordered]@{}
    for ($i = 0; $i -lt $Entries.Count; $i++) {
        $entry = $Entries[$i]
        if ($null -eq $entry) { continue }
        $info = $entry.deviceInfo
        $type = if ($info -and $info.deviceType) { [string]$info.deviceType } else { 'UNKNOWN' }
        $model = if ($info -and $info.PSObject.Properties['modelName']) { Protect-Value ([string]$info.modelName) 'modelName' } else { $null }
        if (-not $counts.Contains($type)) { $counts[$type] = 0 }
        $counts[$type]++
        $rawId = [string]$entry.deviceId
        $script:DeviceRefs[$rawId] = Protect-Value $rawId 'deviceId'
        $item = [ordered]@{
            number = $i + 1
            device_type = $type
            model_name = $model
            device_ref = Protect-Value $entry.deviceId 'deviceId'
            group_ref = if ($info -and $info.PSObject.Properties['groupId']) { Protect-Value $info.groupId 'groupId' } else { $null }
            priority_diagnostics = [bool](Test-PriorityDeviceType $type)
        }
        $items.Add($item)
        Write-Host ('[{0}] {1} - {2}' -f ($i + 1), $type, $model)
    }
    $typeList = @($counts.Keys | Sort-Object | ForEach-Object {
        [ordered]@{ device_type = $_; count = $counts[$_] }
    })
    $inventory = [ordered]@{
        source = 'GET /devices (types registered on this LG account)'
        observed_device_types = $typeList
        devices = $items.ToArray()
    }
    [System.IO.File]::WriteAllText(
        (Join-Path $OutputDirectory '00_device_type_inventory.json'),
        ($inventory | ConvertTo-Json -Depth 20),
        (New-Object System.Text.UTF8Encoding($false))
    )
    Write-Host 'Saved complete device type inventory to 00_device_type_inventory.json'
}

function Save-Record {
    param([string]$Label, [string]$Method, [string]$Path, [int]$Status, $Response, $RequestBody)
    $script:Sequence++
    $safePath = $Path
    foreach ($rawId in $script:DeviceRefs.Keys) {
        $reference = $script:DeviceRefs[$rawId]
        $safePath = $safePath.Replace(([uri]::EscapeDataString($rawId)), $reference)
        $safePath = $safePath.Replace($rawId, $reference)
    }
    $record = [ordered]@{
        timestamp_utc = [DateTime]::UtcNow.ToString('o')
        method = $Method
        path = $safePath
        http_status = $Status
        request_body = Protect-Value $RequestBody
        response = Protect-Value $Response
    }
    $json = $record | ConvertTo-Json -Depth 100
    if ($script:Pat) { $json = $json.Replace($script:Pat, '[REDACTED PAT]') }
    $safeLabel = $Label -replace '[^A-Za-z0-9_-]', '_'
    $name = '{0:D2}_{1}.json' -f $script:Sequence, $safeLabel
    [System.IO.File]::WriteAllText(
        (Join-Path $OutputDirectory $name),
        $json,
        (New-Object System.Text.UTF8Encoding($false))
    )
    $script:Results.Add([ordered]@{
        file = $name
        method = $Method
        path = $safePath
        http_status = $Status
    })
    Write-Host ('{0} {1}: HTTP {2} -> {3}' -f $Method, $safePath, $Status, $name)
}

function Invoke-ThinQ {
    param(
        [ValidateSet('GET', 'POST')][string]$Method,
        [string]$Path,
        [string]$Label,
        [string]$Body
    )
    $headers = @{
        Authorization = 'Bearer ' + $script:Pat
        'x-api-key' = $script:ApiKey
        'x-country' = $Country
        'x-client-id' = $script:ClientId
        'x-message-id' = New-MessageId
        'x-service-phase' = 'OP'
    }
    if ($Method -eq 'POST') { $headers['x-conditional-control'] = 'true' }
    $uri = $script:BaseUrl + '/' + $Path
    $request = @{
        Uri = $uri
        Method = $Method
        Headers = $headers
        TimeoutSec = 30
        UseBasicParsing = $true
    }
    if ($Method -eq 'POST') {
        $request.ContentType = 'application/json'
        $request.Body = $Body
    }
    $status = 0
    $parsed = $null
    try {
        $reply = Invoke-WebRequest @request
        $status = [int]$reply.StatusCode
        if ($reply.Content) { $parsed = $reply.Content | ConvertFrom-Json }
    }
    catch {
        $response = $_.Exception.Response
        if ($response -and $response.StatusCode) {
            $status = [int]$response.StatusCode
            try {
                $stream = $response.GetResponseStream()
                if ($stream) {
                    $reader = New-Object System.IO.StreamReader($stream)
                    try { $parsed = $reader.ReadToEnd() | ConvertFrom-Json }
                    finally { $reader.Dispose() }
                }
            }
            catch { $parsed = @{ error = 'Response could not be parsed as JSON' } }
        }
        else {
            $parsed = @{ error = $_.Exception.GetType().Name }
        }
    }
    $requestData = $null
    if ($Method -eq 'POST') { $requestData = $Body | ConvertFrom-Json }
    Save-Record $Label $Method $Path $status $parsed $requestData
    return [pscustomobject]@{ Status = $status; Data = $parsed }
}

if ($SelfTest) {
    $messageId = New-MessageId
    $decoded = [Convert]::FromBase64String(($messageId.Replace('-', '+').Replace('_', '/') + '=='))
    if ($messageId.Length -ne 22 -or $decoded.Length -ne 16 -or
        (($decoded[6] -band 0xF0) -ne 0x40)) {
        throw 'Message ID self-test failed.'
    }
    $script:Pat = 'synthetic-secret-pat'
    $sample = [pscustomobject]@{
        deviceId = 'example-device'
        alias = 'Private kitchen'
        state = 'RUNNING'
        note = 'synthetic-secret-pat'
        userList = @('person@example.com')
        temperature = 4
    }
    $safe = Protect-Value $sample | ConvertTo-Json -Depth 10
    if ($safe.Contains('synthetic-secret-pat') -or $safe.Contains('Private kitchen') -or
        $safe.Contains('person@example.com') -or -not $safe.Contains('RUNNING') -or
        -not $safe.Contains('device-')) {
        throw 'Redaction self-test failed.'
    }
    if (-not (Test-PriorityDeviceType 'DEVICE_WASHER') -or
        -not (Test-PriorityDeviceType 'DEVICE_WASHCOMBO_MAIN') -or
        -not (Test-PriorityDeviceType 'DEVICE_WASHER_DRYER_COMBO') -or
        (Test-PriorityDeviceType 'DEVICE_DISH_WASHER')) {
        throw 'Device type recognition self-test failed.'
    }
    Write-Host 'Redaction self-test passed.'
    exit 0
}

if ($ExecuteControl -and ((-not $DeviceId -and $ControlDeviceNumber -le 0) -or -not $ControlPayloadPath)) {
    throw 'POST requires -ControlPayloadPath and either -DeviceId or -ControlDeviceNumber.'
}
if ($ControlPayloadPath -and -not $ExecuteControl) {
    throw 'ControlPayloadPath was supplied without -ExecuteControl; no POST sent.'
}
if ($IncludeEnergyUsage -and -not $EnergyProperty) {
    throw 'Daily energy usage requires -EnergyProperty from that device energy profile.'
}

$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$securePat = Read-Host 'Enter your LG ThinQ Personal Access Token (never written to the log)' -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePat)
try {
    $script:Pat = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $securePat.Dispose()
}
if (-not $script:Pat) { throw 'A PAT is required.' }

try {
    # LG requires the device list before any per-device API use.
    $devices = Invoke-ThinQ GET 'devices' 'devices'
    if ($devices.Status -ne 200) {
        throw ('GET /devices failed with HTTP {0}; inspect the redacted log.' -f $devices.Status)
    }
    $null = Invoke-ThinQ GET 'push' 'push_subscriptions'
    $null = Invoke-ThinQ GET 'push/devices' 'device_change_subscriptions'
    $null = Invoke-ThinQ GET 'event' 'event_subscriptions'

    $entries = @($devices.Data.response)
    Save-DeviceTypeInventory $entries
    $priorityEntries = @($entries | Where-Object {
        $_ -and $_.deviceId -and $_.deviceInfo -and
        (Test-PriorityDeviceType ([string]$_.deviceInfo.deviceType))
    })
    if ($ExecuteControl -and -not $DeviceId) {
        if ($ControlDeviceNumber -gt $entries.Count) { throw 'ControlDeviceNumber is not in the displayed device list.' }
        $selected = $entries[$ControlDeviceNumber - 1]
        if (-not $selected -or -not (Test-PriorityDeviceType ([string]$selected.deviceInfo.deviceType))) {
            throw 'Selected device is outside the Refrigerator/Oven/Washer/Dryer probe scope.'
        }
        $DeviceId = [string]$selected.deviceId
    }
    $collected = 0
    foreach ($entry in $priorityEntries) {
        if ($null -eq $entry -or -not $entry.deviceId) { continue }
        $id = [string]$entry.deviceId
        if ($DeviceId -and $id -ne $DeviceId) { continue }
        if ($collected -ge $MaxDevices) { break }
        $collected++
        $encodedId = [uri]::EscapeDataString($id)
        $prefix = 'devices/' + $encodedId
        $label = Get-ShortHash $id
        $null = Invoke-ThinQ GET ($prefix + '/profile') ('profile_' + $label)
        $null = Invoke-ThinQ GET ($prefix + '/state') ('state_' + $label)
        $energy = Invoke-ThinQ GET ('devices/energy/' + $encodedId + '/profile') ('energy_profile_' + $label)
        if ($IncludeEnergyUsage -and $energy.Status -eq 200) {
            $day = [DateTime]::Now.ToString('yyyyMMdd')
            $null = Invoke-ThinQ GET ('devices/energy/' + $encodedId + '/usage?property=' + [uri]::EscapeDataString($EnergyProperty) + '&period=DAILY&startDate=' + $day + '&endDate=' + $day) ('energy_daily_' + $label)
        }
        Start-Sleep -Milliseconds 250
    }

    if ($ExecuteControl) {
        $known = @($entries | Where-Object { $_.deviceId -eq $DeviceId })
        if ($known.Count -ne 1) { throw 'Selected DeviceId is absent from GET /devices.' }
        $payload = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $ControlPayloadPath))
        $null = $payload | ConvertFrom-Json
        Write-Warning 'The next action sends an appliance control command to LG. Confirm that the payload and device state are safe.'
        $confirmation = Read-Host ('Type CONTROL to POST to device-' + (Get-ShortHash $DeviceId))
        if ($confirmation -eq 'CONTROL' -and $PSCmdlet.ShouldProcess(('device-' + (Get-ShortHash $DeviceId)), 'Send LG control POST')) {
            $encodedId = [uri]::EscapeDataString($DeviceId)
            $null = Invoke-ThinQ POST ('devices/' + $encodedId + '/control') ('control_' + (Get-ShortHash $DeviceId)) $payload
            $null = Invoke-ThinQ GET ('devices/' + $encodedId + '/state') ('post_control_state_' + (Get-ShortHash $DeviceId))
        }
    }
}
finally {
    $script:Pat = $null
    $summary = [ordered]@{
        generated_utc = [DateTime]::UtcNow.ToString('o')
        country = $Country
        region = $Region
        calls = $script:Results.ToArray()
        note = 'Review all files before sharing. No PAT is intentionally stored.'
    }
    [System.IO.File]::WriteAllText(
        (Join-Path $OutputDirectory '00_summary.json'),
        ($summary | ConvertTo-Json -Depth 10),
        (New-Object System.Text.UTF8Encoding($false))
    )
    Write-Host ('Saved redacted diagnostics to ' + (Resolve-Path -LiteralPath $OutputDirectory))
}

