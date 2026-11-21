<#
  Push the production environment variables of the Rahat Vercel project.

  Reads KEY=value lines from .live\secrets.env (never printed), and sets each variable for the production
  environment with the Vercel CLI, sending the value on standard input so it never appears in a command line,
  a log or this script's output. The Supabase URL is stored there as SUPABASE_URL_OWNER and becomes
  DATABASE_URL_OWNER on Vercel. VERCEL_TOKEN is read from the same file.

  Usage (from the repository root, after `vercel link`):
    npm run vercel:push-env
    npm run vercel:push-env -- -DryRun        # list the names that would be set, change nothing
    npm run vercel:push-env -- -SecretsFile D:\path\secrets.env

  Re-running replaces existing values. CRON_SECRET is generated fresh each run: redeploy afterwards.
#>
[CmdletBinding()]
param(
  [string]$SecretsFile,
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$VercelCli = 'vercel@66.6.0'   # pinned: a floating version could change flags under us

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $SecretsFile) {
  $candidates = @((Join-Path $repo '.live\secrets.env'))
  # In a git worktree the live folder sits in the main checkout.
  $common = (& git -C $repo rev-parse --path-format=absolute --git-common-dir 2>$null)
  if ($common) { $candidates += (Join-Path (Split-Path $common -Parent) '.live\secrets.env') }
  $SecretsFile = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $SecretsFile -or -not (Test-Path $SecretsFile)) { throw 'secrets file not found: pass -SecretsFile or create .live\secrets.env' }

$secrets = @{}
foreach ($line in Get-Content -LiteralPath $SecretsFile -Encoding UTF8) {
  if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
  $k, $v = $line -split '=', 2
  $secrets[$k.Trim()] = $v.Trim().Trim('"').Trim("'")
}

$token = $secrets['VERCEL_TOKEN']
if (-not $DryRun -and -not $token) { throw 'VERCEL_TOKEN is missing from the secrets file' }
if (-not $DryRun -and -not (Test-Path (Join-Path $repo '.vercel\project.json'))) { throw 'this folder is not linked: run `npx vercel@66.6.0 link` first (see deploy/vercel/README.md)' }

# Secrets: copied from the file because the Supabase data was seeded with these exact values.
$sensitive = [ordered]@{}
foreach ($name in 'SECRET_KEY', 'MASTER_KEY', 'APP_DB_PASSWORD', 'MOCK_IDENTITY_KEY', 'MOCK_REGISTRY_KEY', 'MOCK_PAYMENT_KEY', 'MOCK_SMS_KEY', 'MOCK_CONTROL_KEY') {
  if (-not $secrets[$name]) { throw "$name is missing from the secrets file" }
  $sensitive[$name] = $secrets[$name]
}
if (-not $secrets['SUPABASE_URL_OWNER']) { throw 'SUPABASE_URL_OWNER is missing from the secrets file' }
$sensitive['DATABASE_URL_OWNER'] = $secrets['SUPABASE_URL_OWNER']
if ($secrets['GEMINI_API_KEY']) { $sensitive['GEMINI_API_KEY'] = $secrets['GEMINI_API_KEY'] }
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$sensitive['CRON_SECRET'] = ([Convert]::ToBase64String($bytes) -replace '[^A-Za-z0-9]', '')   # letters and digits only: it travels in a header

# Plain settings.
$plain = [ordered]@{
  APP_ENV             = 'demo'
  JOBS_MODE           = 'inline'
  MOCKS_IN_PROCESS    = 'true'
  CLIENT_IP_HEADER    = 'x-vercel-forwarded-for'
  STARTUP_WARMUP      = 'false'
  DB_POOL_SIZE        = '2'
  DB_MAX_OVERFLOW     = '1'
  UPLOAD_DIR          = '/tmp/rahat-uploads'
  DOCUMENT_STORE      = 'db'
}

function Set-VercelEnv([string]$Name, [string]$Value, [bool]$IsSecret) {
  if ($DryRun) { Write-Host ("[dry run] {0,-20} {1}" -f $Name, $(if ($IsSecret) { '(secret)' } else { 'plain' })); return }
  $cliArgs = @('--yes', $VercelCli, 'env', 'add', $Name, 'production', '--force')
  if ($IsSecret) { $cliArgs += '--sensitive' }
  $env:VERCEL_TOKEN = $token   # the CLI reads the token from the environment, so it is not on a command line
  # The value goes in on standard input and is never echoed.
  $Value | & npx @args 2>&1 | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "could not set $Name (exit code $LASTEXITCODE)" }
  Write-Host ("set {0,-20} {1}" -f $Name, $(if ($IsSecret) { '(secret)' } else { 'plain' }))
}

Push-Location $repo
try {
  foreach ($name in $sensitive.Keys) { Set-VercelEnv $name $sensitive[$name] $true }
  foreach ($name in $plain.Keys) { Set-VercelEnv $name $plain[$name] $false }
}
finally {
  Pop-Location
  Remove-Item Env:\VERCEL_TOKEN -ErrorAction SilentlyContinue
}
Write-Host 'Done. Redeploy for the new values to take effect: npx vercel@66.6.0 deploy --prod'
