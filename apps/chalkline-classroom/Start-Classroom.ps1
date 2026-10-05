[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ClassroomRoot,
  [Parameter(Mandatory=$true)][string]$DataDirectory,
  [string]$ConfigPath = '',
  [switch]$NoBrowser,
  [switch]$TeacherSession
)
$ErrorActionPreference = 'Stop'
$ClassroomRoot = [IO.Path]::GetFullPath($ClassroomRoot)
$manifest = Get-Content -LiteralPath (Join-Path $ClassroomRoot 'package.json') -Raw | ConvertFrom-Json
if ($manifest.name -ne 'chalkline-classroom' -or $manifest.chalklineApiVersion -ne 2) { throw 'Select the classroom API v2 source from the onyx-chalkline repository.' }
& (Join-Path $ClassroomRoot 'Start-Classroom.ps1') -DataDirectory $DataDirectory -ConfigPath $ConfigPath -NoBrowser:$NoBrowser -TeacherSession:$TeacherSession
