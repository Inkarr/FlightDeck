<#
  Flightdeck installer.
  Run "Install Flightdeck.bat" (it asks for admin rights and runs this script).

  What it does:
    1. Finds Python 3.9+, or installs Python 3.13 (winget, else python.org - signature checked)
    2. Installs the Python packages Flightdeck uses (zstandard, qrcode)
    3. Copies Flightdeck to the install folder (your own files in mydata\ are never touched)
    4. Finds Star Citizen and saves its folder in mydata\config.local.json
    5. Opens the firewall port for your home network (and offers to mark the network Private)
    6. Creates Desktop / Start menu shortcuts (optionally start with Windows)
    7. Adds Flightdeck to Windows "Installed apps" so it can be uninstalled normally
    8. Reads the default keybinds from Star Citizen and shows the iPad address + QR code
#>
param(
    [string]$InstallDir = "",
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$AppName  = 'Flightdeck'
$Source   = Split-Path -Parent $PSScriptRoot
$PyMin    = [version]'3.9'
$PyWinget = 'Python.Python.3.13'
$PyUrl    = 'https://www.python.org/ftp/python/3.13.17/python-3.13.17-amd64.exe'
$RegKey   = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$AppName"

function Step($m) { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    $m" -ForegroundColor Green }
function Info($m) { Write-Host "    $m" }
function Warn($m) { Write-Host "    $m" -ForegroundColor Yellow }
function Ask([string]$q, [bool]$default = $true) {
    if ($Quiet) { return $default }
    $hint = if ($default) { '[Y/n]' } else { '[y/N]' }
    $a = Read-Host "    $q $hint"
    if ([string]::IsNullOrWhiteSpace($a)) { return $default }
    return ($a.Trim() -match '^(y|yes)$')
}

# ---------------------------------------------------------------- admin check
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Administrator rights are needed. Run 'Install Flightdeck.bat' instead of this script."
}

Write-Host ""
Write-Host "  FLIGHTDECK INSTALLER" -ForegroundColor Cyan
Write-Host "  Tablet control panel for Star Citizen" -ForegroundColor DarkGray

# ---------------------------------------------------------------- 1. Python
function Get-PyVersion([string]$exe) {
    try {
        $v = & $exe -c "import sys;print('%d.%d.%d' % sys.version_info[:3])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) { return [version]("$v".Trim()) }
    } catch { }
    return $null
}

function Find-Python {
    $cands = New-Object System.Collections.Generic.List[string]
    foreach ($root in 'HKLM:\SOFTWARE\Python\PythonCore', 'HKCU:\SOFTWARE\Python\PythonCore',
                      'HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore') {
        if (-not (Test-Path $root)) { continue }
        foreach ($ver in Get-ChildItem $root -ErrorAction SilentlyContinue) {
            $ipKey = Join-Path $ver.PSPath 'InstallPath'
            if (-not (Test-Path $ipKey)) { continue }
            $ip = Get-ItemProperty $ipKey
            $exe = $ip.ExecutablePath
            if (-not $exe -and $ip.'(default)') { $exe = Join-Path $ip.'(default)' 'python.exe' }
            if ($exe) { $cands.Add($exe) }
        }
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        try { $e = & py -3 -c "import sys;print(sys.executable)" 2>$null; if ($e) { $cands.Add("$e".Trim()) } } catch { }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and $python.Source -notmatch 'WindowsApps') { $cands.Add($python.Source) }   # skip the Store stub

    $best = $null; $bestV = $null
    foreach ($exe in ($cands | Select-Object -Unique)) {
        if (-not (Test-Path $exe)) { continue }
        $v = Get-PyVersion $exe
        if ($v -and $v -ge $PyMin -and (-not $bestV -or $v -gt $bestV)) { $best = $exe; $bestV = $v }
    }
    if ($best) { return [pscustomobject]@{ Exe = $best; Version = $bestV } }
    return $null
}

function Update-PathFromRegistry {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Install-Python {
    $done = $false
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Info "Installing Python 3.13 with winget (this can take a minute)..."
        & winget install --id $PyWinget -e --scope machine --silent `
            --accept-package-agreements --accept-source-agreements `
            --override "/quiet InstallAllUsers=1 PrependPath=1 Include_launcher=1 Include_test=0"
        $done = ($LASTEXITCODE -eq 0)
        if (-not $done) { Warn "winget didn't finish (code $LASTEXITCODE) - downloading from python.org instead." }
    }
    if (-not $done) {
        $tmp = Join-Path $env:TEMP 'flightdeck-python-setup.exe'
        Info "Downloading $PyUrl"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $PyUrl -OutFile $tmp -UseBasicParsing
        $sig = Get-AuthenticodeSignature $tmp
        if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
            Remove-Item $tmp -Force -ErrorAction SilentlyContinue
            throw "The downloaded Python installer isn't signed by the Python Software Foundation - stopping."
        }
        Info "Running the Python installer..."
        $p = Start-Process -FilePath $tmp -Wait -PassThru -ArgumentList `
            '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_launcher=1', 'Include_test=0'
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
        if ($p.ExitCode -ne 0) { throw "The Python installer failed (exit code $($p.ExitCode))." }
    }
    Update-PathFromRegistry
}

Step "Checking for Python"
$Py = Find-Python
if ($Py) {
    Ok "Found Python $($Py.Version) at $($Py.Exe)"
} else {
    Info "Python $PyMin or newer isn't installed."
    Install-Python
    $Py = Find-Python
    if (-not $Py) { throw "Python was installed but can't be found. Restart the PC and run the installer again." }
    Ok "Installed Python $($Py.Version)"
}
$PyExe = $Py.Exe

# ---------------------------------------------------------------- 2. packages
Step "Installing Python packages"
& $PyExe -m pip install --upgrade --quiet --disable-pip-version-check zstandard qrcode
if ($LASTEXITCODE -ne 0) {
    Warn "pip couldn't install the packages. Flightdeck still runs, but can't re-read keybinds after a patch"
    Warn "until 'zstandard' is installed. Check the internet connection and run the installer again."
} else {
    Ok "zstandard (reads Star Citizen's data) and qrcode (iPad QR code) are ready"
}

# ---------------------------------------------------------------- 3. copy files
Step "Installing Flightdeck"
if (-not $InstallDir) {
    $InstallDir = 'C:\Flightdeck'
    $existing = Get-ItemProperty $RegKey -ErrorAction SilentlyContinue
    if ($existing -and $existing.InstallLocation) { $InstallDir = $existing.InstallLocation }
    if (-not $Quiet) {
        $a = Read-Host "    Install folder [$InstallDir]"
        if (-not [string]::IsNullOrWhiteSpace($a)) { $InstallDir = $a.Trim().Trim('"') }
    }
}
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$sameFolder = ($InstallDir.TrimEnd('\') -ieq $Source.TrimEnd('\'))

# stop a running copy so files aren't locked
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -like "*$InstallDir*server.py*" -or $_.CommandLine -like "*$InstallDir*flightdeck.py*") } |
    ForEach-Object { Info "Stopping the running Flightdeck..."; Stop-Process -Id $_.ProcessId -Force }

if ($sameFolder) {
    Ok "Using Flightdeck where it is: $InstallDir"
} else {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $isUpgrade = Test-Path (Join-Path $InstallDir 'server.py')
    $oldCfg = Join-Path $InstallDir 'config.json'
    if ($isUpgrade -and (Test-Path $oldCfg)) {
        # older versions kept scPath/pin in config.json: save them to mydata\config.local.json first
        # (my_*.json files are left alone here and moved into mydata\ when Flightdeck next starts)
        $keepCfg = "import json,os,sys;h=sys.argv[1];c=json.load(open(os.path.join(h,'config.json'),encoding='utf-8'));" +
                   "d=os.path.join(h,'mydata');os.makedirs(d,exist_ok=True);p=os.path.join(d,'config.local.json');" +
                   "l=json.load(open(p,encoding='utf-8')) if os.path.exists(p) else {};" +
                   "l.update({k:c[k] for k in ('scPath','pin') if c.get(k) and k not in l});" +
                   "json.dump(l,open(p,'w',encoding='utf-8'),indent=2,ensure_ascii=False)"
        & $PyExe -c $keepCfg $InstallDir
    }
    & robocopy $Source $InstallDir /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 `
        /XD __pycache__ dist .git mydata /XF *.pyc 'index.backup-*.html' 'Flightdeck-Setup*.zip' | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copying files failed (robocopy code $LASTEXITCODE)." }
    if ($isUpgrade) {
        Ok "Upgraded $InstallDir (your settings in mydata\ were kept)"
    } else {
        Ok "Copied to $InstallDir"
    }
}
# let the normal (non-admin) user write settings, emote choices and the keybind cache
& icacls $InstallDir /grant '*S-1-5-32-545:(OI)(CI)M' /T /Q | Out-Null

# ---------------------------------------------------------------- 4. Star Citizen
Step "Finding Star Citizen"
$userdataPy = Join-Path $InstallDir 'userdata.py'
$current = "$(& $PyExe $userdataPy get scPath)".Trim()

$roots = New-Object System.Collections.Generic.List[string]
$launcherDir = Join-Path $env:APPDATA 'rsilauncher'
if (Test-Path $launcherDir) {   # the RSI launcher remembers where the library is
    Get-ChildItem $launcherDir -Filter *.json -ErrorAction SilentlyContinue | ForEach-Object {
        $txt = Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue
        if ($txt) {
            foreach ($m in [regex]::Matches($txt, '[A-Za-z]:(?:\\\\|\\|/)[^"]*?Roberts Space Industries')) {
                $roots.Add(($m.Value -replace '\\\\', '\' -replace '/', '\'))
            }
        }
    }
}
foreach ($d in (Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Root -match '^[A-Z]:\\$' -and $_.Used -ne $null })) {
    foreach ($sub in '', 'Program Files\', 'Program Files (x86)\', 'Games\', 'Program Files\Games\') {
        $roots.Add("$($d.Root)$($sub)Roberts Space Industries")
    }
}
$found = @()
foreach ($r in ($roots | Select-Object -Unique)) {
    foreach ($ch in 'LIVE', 'PTU', 'EPTU', 'TECH-PREVIEW') {
        $p = Join-Path $r "StarCitizen\$ch"
        if ((Test-Path (Join-Path $p 'Data.p4k')) -and ($found -notcontains $p)) { $found += $p }
    }
}

$scPath = $null
if ($current -and (Test-Path (Join-Path $current 'Data.p4k'))) {
    $scPath = $current
    Ok "Star Citizen: $scPath"
} elseif ($found.Count -gt 0) {
    $scPath = ($found | Where-Object { $_ -like '*\LIVE' } | Select-Object -First 1)
    if (-not $scPath) { $scPath = $found[0] }
    Ok "Found Star Citizen: $scPath"
    if ($found.Count -gt 1) { Info "(also found: $(($found | Where-Object { $_ -ne $scPath }) -join ', '))" }
} else {
    Warn "Couldn't find Star Citizen automatically."
    if (-not $Quiet) {
        while (-not $scPath) {
            $a = Read-Host "    Paste your StarCitizen\LIVE folder (or press Enter to skip)"
            if ([string]::IsNullOrWhiteSpace($a)) { break }
            $a = $a.Trim().Trim('"')
            if (Test-Path (Join-Path $a 'Data.p4k')) { $scPath = $a }
            elseif (Test-Path (Join-Path $a 'StarCitizen\LIVE\Data.p4k')) { $scPath = Join-Path $a 'StarCitizen\LIVE' }
            elseif (Test-Path (Join-Path $a 'LIVE\Data.p4k')) { $scPath = Join-Path $a 'LIVE' }
            else { Warn "No Data.p4k there - try again." }
        }
    }
    if (-not $scPath) { Warn "Skipped. Set scPath in mydata\config.local.json later." }
}
if ($scPath -and $scPath -ne $current) {
    & $PyExe $userdataPy set scPath $scPath
    Ok "Saved to mydata\config.local.json"
}

# ---------------------------------------------------------------- 5. network
Step "Network access for the iPad"
$port = [int]"$(& $PyExe $userdataPy get port)".Trim()
if (-not $port) { $port = 8765 }

Get-NetFirewallRule -DisplayName 'ShipDeck', 'Flightdeck', 'Flightdeck (Python)' -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule
New-NetFirewallRule -DisplayName 'Flightdeck' -Description 'Lets the iPad reach Flightdeck' `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -Profile Private, Domain | Out-Null
New-NetFirewallRule -DisplayName 'Flightdeck (Python)' -Description 'Lets the iPad reach Flightdeck' `
    -Direction Inbound -Action Allow -Program $PyExe -Profile Private, Domain | Out-Null
Ok "Firewall open on port $port for Private networks"

# a "Block" answer to an earlier Windows Firewall pop-up for Python overrides allow rules
$blocks = Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue |
    Where-Object { $_.Program -ieq $PyExe } | Get-NetFirewallRule -ErrorAction SilentlyContinue |
    Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' -and $_.Enabled -eq 'True' }
if ($blocks) {
    Warn "Windows Firewall has $(@($blocks).Count) rule(s) BLOCKING this Python, which would stop the iPad connecting."
    if (Ask "Remove those block rules?") { $blocks | Remove-NetFirewallRule; Ok "Removed" }
}

$public = Get-NetConnectionProfile -ErrorAction SilentlyContinue | Where-Object { $_.NetworkCategory -eq 'Public' }
foreach ($n in $public) {
    Warn "Your network '$($n.Name)' is set to Public, so the iPad can't connect."
    if (Ask "Set '$($n.Name)' to Private? (right for a home network)") {
        Set-NetConnectionProfile -InterfaceIndex $n.InterfaceIndex -NetworkCategory Private
        Ok "'$($n.Name)' is now Private"
    }
}

# ---------------------------------------------------------------- 6. launcher + shortcuts
Step "Shortcuts"
$launcher = Join-Path $InstallDir 'Flightdeck.cmd'
$cmd = @"
@echo off
title Flightdeck
cd /d "%~dp0"
"$PyExe" tools\show_qr.py
"$PyExe" server.py
pause
"@
Set-Content -Path $launcher -Value $cmd -Encoding ASCII
Set-Content -Path (Join-Path $InstallDir 'start.bat') -Value $cmd -Encoding ASCII

$icon = Join-Path $InstallDir 'installer\flightdeck.ico'
function New-Shortcut([string]$path, [string]$target, [string]$arguments, [int]$windowStyle = 1) {
    $ws = New-Object -ComObject WScript.Shell
    $s = $ws.CreateShortcut($path)
    $s.TargetPath = $target
    $s.Arguments = $arguments
    $s.WorkingDirectory = $InstallDir
    if (Test-Path $icon) { $s.IconLocation = "$icon,0" }
    $s.Description = 'Flightdeck - tablet control panel for Star Citizen'
    $s.WindowStyle = $windowStyle
    $s.Save()
}
$desktop  = [Environment]::GetFolderPath('CommonDesktopDirectory')
$programs = Join-Path ([Environment]::GetFolderPath('CommonPrograms')) $AppName
New-Item -ItemType Directory -Force -Path $programs | Out-Null
New-Shortcut (Join-Path $desktop 'Flightdeck.lnk') $launcher ''
New-Shortcut (Join-Path $programs 'Flightdeck.lnk') $launcher ''
$uninstallArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$InstallDir\installer\uninstall.ps1`""
New-Shortcut (Join-Path $programs 'Uninstall Flightdeck.lnk') 'powershell.exe' $uninstallArgs
Ok "Desktop and Start menu shortcuts created"

$startup = Join-Path ([Environment]::GetFolderPath('Startup')) 'Flightdeck.lnk'
if (Ask "Start Flightdeck automatically when Windows starts?" $false) {
    New-Shortcut $startup $launcher '' 7   # 7 = start minimised
    Ok "Flightdeck will start (minimised) when you log in"
} elseif (Test-Path $startup) {
    Remove-Item $startup -Force
}

# ---------------------------------------------------------------- 7. Installed apps entry
New-Item -Path $RegKey -Force | Out-Null
$ver = (Get-Date).ToString('yyyy.MM.dd')
$props = @{
    DisplayName = 'Flightdeck'; DisplayVersion = $ver; Publisher = 'Flightdeck'
    InstallLocation = $InstallDir; DisplayIcon = $icon
    UninstallString = "powershell.exe $uninstallArgs"
}
foreach ($k in $props.Keys) { Set-ItemProperty -Path $RegKey -Name $k -Value $props[$k] }
Set-ItemProperty -Path $RegKey -Name NoModify -Value 1 -Type DWord
Set-ItemProperty -Path $RegKey -Name NoRepair -Value 1 -Type DWord
Ok "Added to Windows 'Installed apps'"

# ---------------------------------------------------------------- 8. keybinds + finish
if ($scPath) {
    Step "Reading Star Citizen's default keybinds"
    Push-Location $InstallDir
    & $PyExe sc_bindings.py $scPath
    Pop-Location
    if ($LASTEXITCODE -eq 0) { Ok "Done" } else { Warn "Couldn't read them now - Flightdeck will try again when it starts." }
}

Step "All done"
& $PyExe (Join-Path $InstallDir 'tools\show_qr.py')
Info "On the iPad: open that address in Safari, then Share > Add to Home Screen."
Info "Start Flightdeck any time from the Desktop or Start menu."
if (Ask "Start Flightdeck now?") {
    # explorer starts it as your normal user rather than as administrator
    Start-Process explorer.exe -ArgumentList "`"$launcher`""
}
