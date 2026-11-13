# Download a .ovpn profile from your VPS into your Windows Downloads folder.
#
# Usage (PowerShell):
#   .\download-ovpn.ps1 -Server root@203.0.113.10 -Profile MHH06-01
#   .\download-ovpn.ps1 -Server root@vpn.example.com -Profile MHH06-01 -Destination C:\Users\me\Downloads
#
# Uses the OpenSSH client that ships with Windows 10/11 (scp.exe).

param(
    [Parameter(Mandatory = $true)][string]$Server,
    [Parameter(Mandatory = $true)][string]$Profile,
    [string]$Destination = (Join-Path $env:USERPROFILE 'Downloads')
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command scp.exe -ErrorAction SilentlyContinue)) {
    Write-Error "scp.exe not found. Install the OpenSSH Client optional feature."
    exit 1
}

if ($Profile -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
    Write-Error "Invalid profile name."
    exit 1
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$target = Join-Path $Destination "$Profile.ovpn"
if (Test-Path $target) {
    Write-Error "$target already exists. Move it away first."
    exit 1
}

$remote = "/etc/openvpn/clients/$Profile.ovpn"
Write-Host "Downloading $Profile from $Server ..."
& scp.exe -q -o StrictHostKeyChecking=accept-new "${Server}:${remote}" $target
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$content = Get-Content -Raw -Path $target
if ($content -notmatch '(?m)^<ca>' -or $content -notmatch '(?m)^<key>') {
    Remove-Item $target -Force
    Write-Error "Downloaded file is not a valid .ovpn profile."
    exit 1
}

Write-Host "Saved: $target"
Write-Host "Import it into OpenVPN Connect or OpenVPN GUI."
