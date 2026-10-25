$ErrorActionPreference='Stop'
$ProjectRoot=Split-Path $PSScriptRoot -Parent
Set-Location $ProjectRoot
$env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')+';'+$env:LOCALAPPDATA+'\Programs\Ollama;'+$env:LOCALAPPDATA+'\Microsoft\WinGet\Links'
$Py=Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) { Write-Host 'Executer INSTALLER.cmd en premier.';exit 1 }
try { $null=Invoke-RestMethod 'http://127.0.0.1:8765/api/session' -TimeoutSec 2;Start-Process 'http://127.0.0.1:8765';exit 0 } catch {}
try { $null=Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 } catch {
  Start-Process 'ollama' -ArgumentList 'serve' -WindowStyle Hidden
  for ($i=0;$i -lt 30;$i++) {
    Start-Sleep -Seconds 1
    try {$null=Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2;break} catch {}
  }
}
Write-Host 'Interface : http://127.0.0.1:8765 - garder cette fenetre ouverte.'
& $Py -m autoshort.cli serve
exit $LASTEXITCODE
