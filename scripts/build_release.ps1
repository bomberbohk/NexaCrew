# =============================================================================
# NexaCrew release builder — packages the platform for the one-line Linux
# installer (mapstudiousa.com/nexacrew-install.sh).
#
#   powershell -File scripts\build_release.ps1
#
# Steps:
#   1. Reads VERSION.
#   2. Stages platform/ (app, static, tests, requirements) — EXCLUDES all
#      runtime data (platform/data), venvs, caches and secrets.
#   3. Builds nexacrew-<version>.tar.gz + latest.json (sha256, size) into
#      the MAP site's uploads/nexacrew/ folder.
#   4. Deploy with the site's ftp-sync.ps1 afterwards.
# =============================================================================
$ErrorActionPreference = "Stop"

$Root    = Split-Path -Parent $PSScriptRoot
$SiteDir = "C:\Users\peter\Desktop\MAP_STUDIO_USA_WEB_SITE"
$OutDir  = Join-Path $SiteDir "uploads\nexacrew"

$Version = (Get-Content (Join-Path $Root "VERSION") -Raw).Trim()
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "VERSION file is malformed: '$Version'" }

Write-Host "[build] NexaCrew v$Version" -ForegroundColor Cyan

$Stage = Join-Path $env:TEMP "nexacrew-release-$Version"
$Pkg   = "nexacrew-$Version"
$StagePkg = Join-Path $Stage $Pkg
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Path $StagePkg | Out-Null

# ---- stage program files (never runtime data / secrets / caches) ----
$include = @("platform\app", "platform\static", "platform\tests")
foreach ($rel in $include) {
    $src = Join-Path $Root $rel
    $dst = Join-Path $StagePkg $rel
    New-Item -ItemType Directory -Path (Split-Path $dst) -Force | Out-Null
    Copy-Item $src $dst -Recurse -Force
}
Copy-Item (Join-Path $Root "platform\requirements.txt") (Join-Path $StagePkg "platform\requirements.txt")
Copy-Item (Join-Path $Root "VERSION") (Join-Path $StagePkg "VERSION")
Copy-Item (Join-Path $Root "README.md") (Join-Path $StagePkg "README.md") -ErrorAction SilentlyContinue
# root launcher scripts — servers updated from the portal must receive tray /
# watchdog / installer fixes too, not just platform/ code
$rootScripts = @("start.py", "client_start.py", "tray_widget.py", "action_prompt.py",
                 "console_manager.py", "console_setup.py", "install_wizard.py",
                 "orchestrator.py", "agent_gui.py", "requirements.txt")
foreach ($f in $rootScripts) {
    $src = Join-Path $Root $f
    if (Test-Path $src) { Copy-Item $src (Join-Path $StagePkg $f) }
}

# strip caches — deterministic, smaller archives
Get-ChildItem $StagePkg -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
# create the empty data skeleton the server expects on first boot
New-Item -ItemType Directory -Path (Join-Path $StagePkg "platform\data") -Force | Out-Null

# ---- tar.gz (bsdtar ships with Windows 10+) ----
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$TarFile = Join-Path $OutDir "nexacrew-$Version.tar.gz"
if (Test-Path $TarFile) { Remove-Item $TarFile -Force }
Push-Location $Stage
try { tar -czf $TarFile $Pkg } finally { Pop-Location }
if (-not (Test-Path $TarFile)) { throw "tar failed - package not created" }

$Sha  = (Get-FileHash $TarFile -Algorithm SHA256).Hash.ToLower()
$Size = (Get-Item $TarFile).Length

# ---- manifest ----
$manifest = @{ version = $Version; file = "nexacrew-$Version.tar.gz"; sha256 = $Sha; size = $Size } |
    ConvertTo-Json -Compress
Set-Content -Path (Join-Path $OutDir "latest.json") -Value $manifest -Encoding ascii

Remove-Item $Stage -Recurse -Force

Write-Host "[build] Package : $TarFile ($([math]::Round($Size/1MB,1)) MB)" -ForegroundColor Green
Write-Host "[build] SHA-256 : $Sha" -ForegroundColor Green
Write-Host "[build] Manifest: $(Join-Path $OutDir 'latest.json')" -ForegroundColor Green
Write-Host "[build] Now deploy the site (uploads/nexacrew + nexacrew-install.sh + backend/nexacrew-package-api.php) with ftp-sync.ps1" -ForegroundColor Yellow
