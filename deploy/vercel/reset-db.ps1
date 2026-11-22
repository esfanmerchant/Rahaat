# Migrate and seed the Vercel database (Supabase) from this PC. With -Reset it empties every table first and
# re-seeds the demo accounts: the clean demo state. Reads SUPABASE_URL_OWNER from .live/secrets.env (never committed).
# Usage: powershell -ExecutionPolicy Bypass -File deploy/vercel/reset-db.ps1 -Reset   (about 5 minutes)
# Run migrations and a clean seed against the Supabase database named in .live\secrets.env. Prints no secret.
param([switch]$Reset)
$ErrorActionPreference = 'Continue'  # native tools log to stderr; failures are read from exit codes
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
foreach ($line in Get-Content -LiteralPath (Join-Path $repo '.live\secrets.env')) {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $k, $v = $line -split '=', 2
    $k = $k.Trim()
    if ($k -in @('VERCEL_TOKEN', 'DATABASE_URL_OWNER')) { continue }
    Set-Item -Path ("Env:" + $k) -Value $v.Trim()
}
$env:DATABASE_URL_OWNER = $env:SUPABASE_URL_OWNER
$env:APP_ENV = 'demo'
$env:PYTHONUTF8 = '1'
$env:DB_POOL_SIZE = '2'
$env:DB_MAX_OVERFLOW = '2'
Set-Location (Join-Path $repo 'backend')
$t = Get-Date
& uv run --frozen alembic upgrade head 2>&1 | Where-Object { $_ -notmatch '^\{"ts"' } | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { throw "migrate failed ($LASTEXITCODE)" }
Write-Host ("migrated in {0:n0}s" -f ((Get-Date) - $t).TotalSeconds)
$t = Get-Date
$seedArgs = @('run', '--frozen', 'python', '-m', 'app.seed')
if ($Reset) { $seedArgs += '--reset' }
& uv @seedArgs 2>&1 | Where-Object { $_ -notmatch '^\{"ts"' } | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { throw "seed failed ($LASTEXITCODE)" }
Write-Host ("seeded in {0:n0}s" -f ((Get-Date) - $t).TotalSeconds)
