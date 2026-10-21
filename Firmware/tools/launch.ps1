param(
    [ValidateSet('menu','setup','build','flash','build-flash','usb-update','configure','check','record','report','backup','restore')][string]$Action='menu',
    [string]$Image='', [string]$Port='', [string]$Drive='',
    [ValidateSet('auto','cube','openocd')][string]$Backend='auto',
    [ValidateSet(40,80,160,240,320,400,480)][int]$CpuMHz=80,
    [ValidateSet('under-reset','normal')][string]$Connect='under-reset',
    [switch]$DryRun,
    [string]$SettingsFile='', [string]$Output='', [double]$Seconds=10,
    [switch]$Advanced, [switch]$Yes, [switch]$Save
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$repo = Test-Path -LiteralPath (Join-Path $root 'Beta')
if ($repo) { $root = Split-Path -Parent $root }
if ($Action -eq 'menu') {
    Write-Host 'FreeEEG32 beta - build and update'
    Write-Host '1  Install/check all tools (Python, Arm compiler, OpenOCD, USB helper)'
    Write-Host '2  Build firmware + UF2 from edited source'
    Write-Host '3  Flash existing compiled firmware + UF2 loader with ST-Link'
    Write-Host '4  Build edited source, then flash firmware + UF2 loader with ST-Link'
    Write-Host '5  USB update (loader already installed)'
    Write-Host '6  Configure board (sample rate, gain, presets, saved settings)'
    Write-Host '7  Check my board'
    Write-Host '8  Test recording (10 seconds)'
    Write-Host '9  Save a support report'
    Write-Host '10 Back up settings to a file'
    Write-Host '11 Restore settings from a file'
    Write-Host '0  Exit'
    switch (Read-Host 'Select') {
        '1' { $Action='setup' }; '2' { $Action='build' }; '3' { $Action='flash' }
        '4' { $Action='build-flash' }; '5' { $Action='usb-update' }; '6' { $Action='configure' }
        '7' { $Action='check' }; '8' { $Action='record' }; '9' { $Action='report' }
        '10' { $Action='backup' }; '11' { $Action='restore' }; '0' { exit 0 }
        default { throw 'Invalid selection.' }
    }
    if ($Action -in @('build','build-flash') -and !$PSBoundParameters.ContainsKey('CpuMHz')) {
        $clock = Read-Host 'Application CPU MHz: 40/80/160/240/320/400/480 [80]'
        if ($clock) {
            if ($clock -notin @('40','80','160','240','320','400','480')) { throw 'Choose 40, 80, 160, 240, 320, 400 or 480 MHz.' }
            $CpuMHz = [int]$clock
        }
    }
}
if ($PSBoundParameters.ContainsKey('CpuMHz') -and $Action -notin @('build','build-flash')) { throw '-CpuMHz applies to source builds only; precompiled images already contain their clock profile.' }
if ($Action -in @('build','build-flash') -and !$repo) { throw 'Source build needs the repository checkout, not only the precompiled release bundle.' }
if ($DryRun -and $Action -notin @('flash','build-flash')) { throw '-DryRun applies to SWD flash/build-flash actions only.' }
if ($Action -in @('usb-update','configure','check','record','report','backup','restore')) { & (Join-Path $PSScriptRoot 'setup-windows.ps1') -SerialOnly }
elseif ($Action -eq 'flash') { & (Join-Path $PSScriptRoot 'setup-windows.ps1') -FlashOnly -NoSerialTools }
elseif ($Action -eq 'setup') { & (Join-Path $PSScriptRoot 'setup-windows.ps1') }
else { & (Join-Path $PSScriptRoot 'setup-windows.ps1') -NoSerialTools }
$pythonPath = Join-Path $root '.tools/python-path.txt'
$python = (Get-Content -LiteralPath $pythonPath -Raw).Trim([char]0xFEFF).Trim()
function Invoke-Python([string[]]$Arguments) {
    & $python -u @Arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if ($Action -eq 'setup') { exit 0 }
if ($Action -in @('build','build-flash')) { Invoke-Python -Arguments @((Join-Path $root 'Firmware/UF2/build.py'), '--cpu-mhz', "$CpuMHz") }
if ($Action -in @('flash','build-flash')) {
    $flash = if ($repo) { Join-Path $root 'Firmware/Beta/flash.py' } else { Join-Path $root 'flash.py' }
    $arguments = @($flash, '--backend', $Backend, '--connect', $Connect)
    if ($Image) { $arguments += $Image }
    if ($DryRun) { $arguments += '--dry-run' }
    Invoke-Python -Arguments $arguments
}
if ($Action -eq 'usb-update') {
    $python = Join-Path $root '.venv/Scripts/python.exe'
    $device = if ($repo) { Join-Path $root 'Firmware/Beta/device.py' } else { Join-Path $root 'device.py' }
    if (!$Image) {
        $Image = if ($repo) { Join-Path $root 'Firmware/build/uf2/freeeeg32-application.uf2' } else { Join-Path $root 'freeeeg32-application.uf2' }
        $precompiled = Join-Path $root 'Precompiled/freeeeg32-application.uf2'
        if ($repo -and !(Test-Path -LiteralPath $Image) -and (Test-Path -LiteralPath $precompiled)) { $Image = $precompiled }
    }
    $arguments = @($device,'update','--image',$Image)
    if ($Port) { $arguments += @('--port',$Port) }
    if ($Drive) { $arguments += @('--drive',$Drive) }
    Invoke-Python -Arguments $arguments
}
if ($Action -eq 'configure') {
    $python = Join-Path $root '.venv/Scripts/python.exe'
    $device = if ($repo) { Join-Path $root 'Firmware/Beta/device.py' } else { Join-Path $root 'device.py' }
    $arguments = @($device,'configure')
    if ($Port) { $arguments += @('--port',$Port) }
    if ($Advanced) { $arguments += '--advanced' }
    Invoke-Python -Arguments $arguments
}
if ($Action -in @('check','record','report','backup','restore')) {
    $python = Join-Path $root '.venv/Scripts/python.exe'
    $device = if ($repo) { Join-Path $root 'Firmware/Beta/device.py' } else { Join-Path $root 'device.py' }
    $arguments = @($device,$Action)
    if ($Port) { $arguments += @('--port',$Port) }
    if ($Output) { $arguments += @('--output',$Output) }
    if ($SettingsFile) { $arguments += @('--file',$SettingsFile) }
    if ($Advanced) { $arguments += '--advanced' }
    if ($Yes) { $arguments += '--yes' }
    if ($Save) { $arguments += '--save' }
    if ($Action -eq 'record') { $arguments += @('--seconds',$Seconds.ToString([Globalization.CultureInfo]::InvariantCulture)) }
    Invoke-Python -Arguments $arguments
}
