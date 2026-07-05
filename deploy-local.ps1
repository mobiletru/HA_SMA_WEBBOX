<#
Deploy the WebBox Dashboard add-on to a Home Assistant host as a LOCAL add-on.

Copies the webbox/ folder to the HA /addons share (Samba add-on must be
running on the HA host). After copying, open Settings -> Add-ons ->
Add-on Store -> three-dot menu -> "Check for updates", then install
"WebBox Dashboard" from the "Local add-ons" section.

Usage:
  .\deploy-local.ps1                          # uses \\homeassistant\addons
  .\deploy-local.ps1 -HaHost 192.168.1.10     # use IP instead of hostname
#>
param(
    [string]$HaHost = "homeassistant"
)

$src = Join-Path $PSScriptRoot "webbox"
$dst = "\\$HaHost\addons\webbox"

if (-not (Test-Path $src)) {
    Write-Error "Source folder not found: $src"
    exit 1
}

Write-Host "Deploying $src -> $dst"

robocopy $src $dst /MIR /XD __pycache__ .venv /XF *.pyc /NFL /NDL /NP
$code = $LASTEXITCODE
# robocopy exit codes 0-7 indicate success
if ($code -ge 8) {
    Write-Error "robocopy failed with exit code $code. Is the Samba add-on running on '$HaHost' and the 'addons' share reachable?"
    exit 1
}

Write-Host ""
Write-Host "Done. In Home Assistant: Settings -> Add-ons -> Add-on Store -> (three-dot menu) Check for updates."
Write-Host "Then install/update 'WebBox Dashboard' under 'Local add-ons'."
Write-Host "Tip: if the add-on is already installed and you didn't bump 'version:' in config.yaml, use its 'Rebuild' button."
