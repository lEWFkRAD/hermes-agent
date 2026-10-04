[CmdletBinding()]
param(
  [string]$DataDirectory = (Join-Path $PSScriptRoot 'data'),
  [string]$ConfigPath = '',
  [ValidateRange(1024,65535)][int]$Port = 5195,
  [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$DataDirectory = [IO.Path]::GetFullPath($DataDirectory)
New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
if (-not $ConfigPath) { $ConfigPath = Join-Path $DataDirectory 'config.json' }
$ConfigPath = [IO.Path]::GetFullPath($ConfigPath)
$origin = "http://127.0.0.1:$Port"
$ready = $false
try { $health = Invoke-RestMethod "$origin/health" -TimeoutSec 2; $ready = $health.service -eq 'chalkline-classroom' } catch {}
if (-not $ready) {
  $node = (Get-Command node -ErrorAction Stop).Source
  $server = Join-Path $PSScriptRoot 'server.mjs'
  $arguments = @('"' + $server + '"', '--data', '"' + $DataDirectory + '"', '--config', '"' + $ConfigPath + '"', '--port', $Port)
  Start-Process -FilePath $node -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $DataDirectory 'service.log') -RedirectStandardError (Join-Path $DataDirectory 'service-errors.log') | Out-Null
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Milliseconds 250
    try { $health = Invoke-RestMethod "$origin/health" -TimeoutSec 1; if ($health.service -eq 'chalkline-classroom') { $ready = $true; break } } catch {}
  }
}
if (-not $ready) { throw "Classroom did not start. See $DataDirectory/service-errors.log" }
$launchPath = Join-Path $DataDirectory 'launch.json'
if (-not (Test-Path -LiteralPath $launchPath)) { throw 'This port is already serving a different classroom. Use its data directory or another port.' }
$launch = Get-Content -LiteralPath $launchPath -Raw | ConvertFrom-Json
if ($launch.origin -ne $origin) { throw 'Classroom launch address mismatch.' }
if (-not $NoBrowser) { Start-Process -FilePath $launch.teacherUrl }
Write-Output 'Chalkline classroom is ready on this computer.'
