<#
  Flightdeck uninstaller - removes shortcuts, firewall rules and the "Installed apps" entry,
  then (if you agree) the Flightdeck folder. Python itself is left installed.
#>
$ErrorActionPreference = 'Stop'

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$InstallDir = Split-Path -Parent $PSScriptRoot
$RegKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Flightdeck'

Write-Host ""
Write-Host "  Uninstall Flightdeck from $InstallDir" -ForegroundColor Cyan
$a = Read-Host "  Continue? [y/N]"
if ($a -notmatch '^(y|yes)$') { exit }

Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -like "*$InstallDir*server.py*" -or $_.CommandLine -like "*$InstallDir*flightdeck.py*") } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

$links = @(
    (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'Flightdeck.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Startup')) 'Flightdeck.lnk')
)
foreach ($l in $links) { if (Test-Path $l) { Remove-Item $l -Force } }
$programs = Join-Path ([Environment]::GetFolderPath('CommonPrograms')) 'Flightdeck'
if (Test-Path $programs) { Remove-Item $programs -Recurse -Force }
Write-Host "  Shortcuts removed" -ForegroundColor Green

Get-NetFirewallRule -DisplayName 'ShipDeck', 'Flightdeck', 'Flightdeck (Python)' -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule
Write-Host "  Firewall rules removed" -ForegroundColor Green

if (Test-Path $RegKey) { Remove-Item $RegKey -Recurse -Force }
Write-Host "  Removed from Installed apps" -ForegroundColor Green

$a = Read-Host "  Also delete the folder $InstallDir (including your settings in mydata)? [y/N]"
if ($a -match '^(y|yes)$') {
    Set-Location $env:TEMP
    Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $InstallDir) { Write-Host "  Some files were in use - delete $InstallDir by hand." -ForegroundColor Yellow }
    else { Write-Host "  Folder deleted" -ForegroundColor Green }
}
Write-Host ""
Write-Host "  Flightdeck has been uninstalled. Python was left installed (remove it from Installed apps if you like)."
Read-Host "  Press Enter to close"
