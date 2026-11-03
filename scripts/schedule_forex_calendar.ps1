param([Parameter(Mandatory=$true)][string]$DeploymentPath)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $DeploymentPath).Path
$installation = Get-Content -LiteralPath (Join-Path $root 'installation.json') -Raw | ConvertFrom-Json
$config = Get-Content -LiteralPath (Join-Path $root 'deployment.json') -Raw | ConvertFrom-Json
$expiry = [DateTimeOffset]$config.expires_at
$duration = $expiry - [DateTimeOffset]::UtcNow
if ($duration.TotalMinutes -lt 2) { throw 'Clock scope expired or too short; no task registered' }
$taskName = 'FXTalanta-' + $installation.instance
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'Existing task refused' }
$runner = Join-Path $root 'collect.ps1'
if ($runner.Contains('"')) { throw 'Invalid runner path' }
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $runner + '"')
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(10) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration $duration
$finalCheck = New-ScheduledTaskTrigger -Once -At $expiry.LocalDateTime.AddSeconds(5)
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 45) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($trigger,$finalCheck) -Principal $principal -Settings $settings -Description 'FOREX read-only calendar import; expires with verified clock scope; no terminal control or trading.' | Out-Null
$taskName | Set-Content -LiteralPath (Join-Path $root 'scheduled-task.txt') -Encoding UTF8
Write-Output 'Registered limited-user, one-minute import task with bounded expiry. No credentials stored.'
