<#
.SYNOPSIS
    Install Lumen for the current user.

.DESCRIPTION
    Copies this folder to %LOCALAPPDATA%\Programs\Lumen and puts it on
    your PATH, so `lumen` works from any terminal.

    Per-user on purpose: no administrator rights, nothing written to
    Program Files, and nothing touched outside your own profile. Undo it
    with uninstall.ps1.

    You do not have to run this at all - lumen.exe works fine from the
    folder you unzipped. This only saves you typing the full path.
#>
[CmdletBinding()]
param(
    # Where to install. The default needs no admin rights.
    [string] $Destination = (Join-Path $env:LOCALAPPDATA 'Programs\Lumen'),
    # Install without adding to PATH.
    [switch] $NoPath
)

$ErrorActionPreference = 'Stop'

$source = Join-Path $PSScriptRoot 'lumen'
if (-not (Test-Path (Join-Path $source 'lumen.exe'))) {
    throw "lumen.exe not found in '$source'. Run this from the folder you unzipped, with the lumen folder next to it."
}

Write-Host ''
Write-Host 'Installing Lumen' -ForegroundColor Cyan
Write-Host "  from $source"
Write-Host "  to   $Destination"
Write-Host ''

# A running copy holds its own files open, and the copy would half-finish.
$running = Get-Process lumen -ErrorAction SilentlyContinue
if ($running) {
    throw 'Lumen is running. Close it and try again.'
}

# Replace rather than merge: a stale DLL from an older version left behind
# in _internal is exactly the kind of thing that fails confusingly later.
if (Test-Path $Destination) {
    Write-Host '  Removing the previous installation...'
    Remove-Item $Destination -Recurse -Force
}

New-Item -ItemType Directory -Path $Destination -Force | Out-Null
Copy-Item (Join-Path $source '*') $Destination -Recurse -Force

# The licences travel with the install, not just with the zip.
foreach ($f in 'LICENSE', 'THIRD-PARTY-LICENSES.txt') {
    $p = Join-Path $PSScriptRoot $f
    if (Test-Path $p) { Copy-Item $p $Destination -Force }
}

Write-Host '  Files copied.' -ForegroundColor Green

if (-not $NoPath) {
    # The USER PATH, read from the registry rather than $env:PATH - the
    # latter is the merged machine+user value, and writing it back would
    # copy every machine entry into the user's own PATH.
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $entries = @($userPath -split ';' | Where-Object { $_ -ne '' })

    if ($entries -contains $Destination) {
        Write-Host '  Already on your PATH.'
    } else {
        $new = (@($entries) + $Destination) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $new, 'User')
        Write-Host '  Added to your PATH.' -ForegroundColor Green
        Write-Host ''
        Write-Host '  Open a NEW terminal for this to take effect -' -ForegroundColor Yellow
        Write-Host '  a running one cannot see a PATH change.' -ForegroundColor Yellow
    }
}

Write-Host ''
Write-Host 'Done. Run:  lumen' -ForegroundColor Cyan
Write-Host 'First run opens Settings and walks you through the setup.'
Write-Host ''
