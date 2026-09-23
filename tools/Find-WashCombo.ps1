#requires -Version 5.1
<#
.SYNOPSIS
Check whether LG ThinQ Connect reports DEVICE_WASHCOMBO_MAIN on this account.
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[A-Z]{2}$')][string]$Country = 'US',
    [ValidateSet('America', 'Europe', 'Asia')][string]$Region = 'America',
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $PSScriptRoot ('diagnostics\washcombo-type-check-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
& (Join-Path $PSScriptRoot 'ThinQ-Probe.ps1') -Country $Country -Region $Region `
    -DeviceTypeFilter 'DEVICE_WASHCOMBO_MAIN' -OutputDirectory $OutputDirectory

