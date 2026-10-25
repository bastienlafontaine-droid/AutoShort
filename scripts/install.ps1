param([switch]$SkipModels)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectRoot
New-Item -ItemType Directory -Force -Path 'data' | Out-Null
Start-Transcript -Path 'data\installation.log' -Append
function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:USERPROFILE + '\.local\bin;' + $env:LOCALAPPDATA + '\Microsoft\WinGet\Links;' + $env:LOCALAPPDATA + '\Programs\Ollama'
}
function Run-Checked {
  param([string]$Exe, [string[]]$Arguments)
  & $Exe @Arguments
  if ($LASTEXITCODE -ne 0) { throw "Echec de $Exe (code $LASTEXITCODE). Voir data\installation.log." }
}
function Ensure-Tool {
  param([string]$Command,[string]$Package)
  Refresh-Path
  if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'Installer App Installer depuis Microsoft Store pour obtenir winget, puis relancer.' }
    Run-Checked 'winget' @('install','--id',$Package,'--exact','--source','winget','--accept-package-agreements','--accept-source-agreements','--disable-interactivity')
    Refresh-Path
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) { throw "$Command introuvable. Fermer cette fenetre et relancer INSTALLER.cmd." }
  }
}
try {
  Write-Host 'AutoShort : installation locale Windows (Python, Ollama, FFmpeg, modeles).'
  Write-Host 'Prevoir environ 35 a 50 Go libres. Les telechargements peuvent prendre du temps.'
  Ensure-Tool 'uv' 'astral-sh.uv'
  Ensure-Tool 'ollama' 'Ollama.Ollama'
  Ensure-Tool 'ffmpeg' 'Gyan.FFmpeg'
  if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue)) { throw 'ffprobe absent : reinstaller le paquet Gyan.FFmpeg.' }
  Run-Checked 'uv' @('python','install','3.11')
  if (-not (Test-Path '.venv\Scripts\python.exe')) { Run-Checked 'uv' @('venv','--python','3.11','.venv') }
  $Py = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
  Run-Checked 'uv' @('pip','install','--python',$Py,'-r','requirements-windows.lock','--extra-index-url','https://download.pytorch.org/whl/cu128','--index-strategy','unsafe-best-match')
  Run-Checked 'uv' @('pip','install','--python',$Py,'--no-deps','-e','.')
  # Deux distributions fournissent le module phonemizer. Le fork est requis pour le chemin eSpeak Windows.
  & uv pip uninstall --python $Py phonemizer
  Run-Checked 'uv' @('pip','install','--python',$Py,'--reinstall','phonemizer-fork==3.3.2')
  Run-Checked $Py @('-m','pytest','-q')
  if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
  $Ready = $false
  try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3; $Ready = $true } catch {}
  if (-not $Ready) {
    Start-Process 'ollama' -ArgumentList 'serve' -WindowStyle Hidden
    for ($i=0;$i -lt 30;$i++) {
      Start-Sleep -Seconds 1
      try { $null=Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2; $Ready=$true; break } catch {}
    }
  }
  if (-not $Ready) { throw 'Ollama ne repond pas. Le demarrer puis relancer INSTALLER.cmd.' }
  if (-not $SkipModels) {
    $Models = & $Py -c "from autoshort.core import config; c=config(); print(c['models']['text']); print(c['models']['vision'])"
    if ($LASTEXITCODE -ne 0) { throw 'Lecture configuration impossible' }
    foreach ($Model in $Models) { Run-Checked 'ollama' @('pull',$Model.Trim()) }
    Run-Checked $Py @('-m','autoshort.cli','prefetch')
  }
  & uv pip freeze --python $Py | Out-File 'installation-lock.txt' -Encoding utf8
  & $Py -m autoshort.cli doctor
  Write-Host ''
  Write-Host 'Installation terminee. Si la cle Brave manque, la saisir dans l interface.'
  Write-Host 'Le diagnostic CUDA doit etre vert avant une production. Fermer les autres applications GPU.'
} catch {
  Write-Host $_ -ForegroundColor Red
  Stop-Transcript
  exit 1
}
Stop-Transcript
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'start.ps1')
