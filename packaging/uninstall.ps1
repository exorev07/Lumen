<#
.SYNOPSIS
    Remove a Lumen installation made by install.ps1.

.DESCRIPTION
    Deletes the installed folder and takes it off your PATH.

    Your settings are NOT removed - they live in %APPDATA%\lumen and hold
    your device key. Delete that folder by hand if you want them gone.
#>
[CmdletBinding()]
param(
    [string] $Destination = (Join-Path $env:LOCALAPPDATA 'Programs\Lumen')
)

$ErrorActionPreference = 'Stop'

Write-Host ''
Write-Host "Removing $Destination" -ForegroundColor Cyan

$running = Get-Process lumen -ErrorAction SilentlyContinue
if ($running) {
    throw 'Lumen is running. Close it and try again.'
}

if (Test-Path $Destination) {
    Remove-Item $Destination -Recurse -Force
    Write-Host '  Files removed.' -ForegroundColor Green
} else {
    Write-Host '  Nothing installed there.'
}

# Same registry-not-$env:PATH reasoning as install.ps1.
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$entries = @($userPath -split ';' | Where-Object { $_ -ne '' })
if ($entries -contains $Destination) {
    $new = ($entries | Where-Object { $_ -ne $Destination }) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $new, 'User')
    Write-Host '  Removed from your PATH.' -ForegroundColor Green
}

$settings = Join-Path $env:APPDATA 'lumen'
if (Test-Path $settings) {
    Write-Host ''
    Write-Host "Your settings are still in $settings"
    Write-Host 'They hold your device key. Delete that folder to remove them.'
}
Write-Host ''
