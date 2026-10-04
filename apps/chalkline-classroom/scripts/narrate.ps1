param([Parameter(Mandatory=$true)][string]$TextFile,[Parameter(Mandatory=$true)][string]$OutputFile)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Speech
$voice=New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $voice.Rate=-1
  $voice.SetOutputToWaveFile($OutputFile)
  $voice.Speak([System.IO.File]::ReadAllText($TextFile))
} finally { $voice.Dispose() }
