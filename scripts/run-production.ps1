<#
.SYNOPSIS
  Run qopt in production mode on this machine without Docker, using the same runtime layout as the Docker image:
  the backend installed as a regular package (outside the source tree), the built SPA, production settings.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\run-production.ps1            # http://localhost:8080
  powershell -ExecutionPolicy Bypass -File scripts\run-production.ps1 -Port 9000
#>
param([int]$Port = 8080, [switch]$Rebuild)

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path "$PSScriptRoot\..").Path
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
$Run = Join-Path $Repo ".run"
if (-not (Test-Path $Py)) { throw "Python venv not found at $Py - create it first (see README Quick start)" }

# 1. Secrets: create .env from .env.example with strong random values if it does not exist (never committed).
$EnvFile = Join-Path $Repo ".env"
if (-not (Test-Path $EnvFile)) {
  $rand = { param($n) & $Py -c "import secrets;print(secrets.token_urlsafe($n))" }
  $text = Get-Content (Join-Path $Repo ".env.example") -Raw
  $text = $text -replace "(?m)^QOPT_JWT_SECRET=.*$", ("QOPT_JWT_SECRET=" + (& $rand 48))
  $text = $text -replace "(?m)^POSTGRES_PASSWORD=.*$", ("POSTGRES_PASSWORD=" + (& $rand 24).Replace("-", "").Replace("_", ""))
  [IO.File]::WriteAllText($EnvFile, $text, [Text.UTF8Encoding]::new($false))
  Write-Host "Created .env with generated secrets (keep it private; it is git-ignored)."
}
# The one-time admin setup token (required in production); add it to an existing .env that predates it.
if (-not (Select-String -Path $EnvFile -Pattern "^QOPT_BOOTSTRAP_TOKEN=\S" -Quiet)) {
  $tok = & $Py -c "import secrets;print(secrets.token_urlsafe(24))"
  $text = Get-Content $EnvFile -Raw
  if ($text -match "(?m)^QOPT_BOOTSTRAP_TOKEN=") { $text = $text -replace "(?m)^QOPT_BOOTSTRAP_TOKEN=.*$", "QOPT_BOOTSTRAP_TOKEN=$tok" }
  else { $text = $text.TrimEnd() + "`nQOPT_BOOTSTRAP_TOKEN=$tok`n" }
  [IO.File]::WriteAllText($EnvFile, $text, [Text.UTF8Encoding]::new($false))
}
Write-Host "First visit: create the administrator with the setup token = QOPT_BOOTSTRAP_TOKEN in $EnvFile"
foreach ($line in Get-Content $EnvFile) {
  if ($line -match "^\s*([A-Z0-9_]+)=(.*)$" -and $Matches[2] -ne "") { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2] }
}

# 2. Frontend build (the SPA served by the backend).
$Dist = Join-Path $Repo "frontend\dist"
if ($Rebuild -or -not (Test-Path (Join-Path $Dist "index.html"))) {
  Push-Location (Join-Path $Repo "frontend"); try { npm run build } finally { Pop-Location }
}

# 3. Install the backend as a package (like `pip install .` in the image) - migrations are package data.
New-Item -ItemType Directory -Force $Run | Out-Null
$Site = Join-Path $Run "site"
if ($Rebuild -or -not (Test-Path (Join-Path $Site "qopt"))) {
  if (Test-Path $Site) { Remove-Item -Recurse -Force $Site }
  & $Py -m pip install --no-deps -q --target $Site (Join-Path $Repo "backend")
  Get-ChildItem (Join-Path $Repo "backend") -Directory -Filter "build" | Remove-Item -Recurse -Force
  Get-ChildItem (Join-Path $Repo "backend") -Directory -Filter "*.egg-info" | Remove-Item -Recurse -Force
}

# 4. Production settings (same variables the Docker image sets).
$env:PYTHONPATH = $Site
$env:QOPT_ENVIRONMENT = "production"
$env:QOPT_DATABASE_URL = "sqlite:///" + ((Join-Path $Run "qopt.db") -replace "\\", "/")
$env:QOPT_FRONTEND_DIST = $Dist
$env:QOPT_DOCS_DIR = Join-Path $Repo "docs"
$env:QOPT_CORS_ORIGINS = "[`"http://localhost:$Port`",`"http://127.0.0.1:$Port`"]"

Write-Host "qopt (production mode) -> http://localhost:$Port   (first visit creates the administrator)"
Set-Location $Run       # run outside the source tree so the installed package is what gets imported
& $Py -m uvicorn qopt.api.app:app --host 127.0.0.1 --port $Port --workers 1
