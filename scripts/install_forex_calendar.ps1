param(
    [Parameter(Mandatory=$true)][string]$BindingPath,
    [Parameter(Mandatory=$true)][string]$ClockPolicyPath,
    [Parameter(Mandatory=$true)][string]$ClockEvidencePath,
    [Parameter(Mandatory=$true)][string]$BuildResultPath,
    [Parameter(Mandatory=$true)][string]$PythonPath,
    [Parameter(Mandatory=$true)][string]$DeploymentPath,
    [Parameter(Mandatory=$true)][long]$ServerFrom,
    [Parameter(Mandatory=$true)][long]$ServerUntil
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$binding = Get-Content -LiteralPath $BindingPath -Raw | ConvertFrom-Json
$policy = Get-Content -LiteralPath $ClockPolicyPath -Raw | ConvertFrom-Json
$build = Get-Content -LiteralPath $BuildResultPath -Raw | ConvertFrom-Json
$terminal = [IO.Path]::GetFullPath($binding.terminal_path)
$data = [IO.Path]::GetFullPath($binding.data_path)
if ((Split-Path -Leaf (Split-Path -Parent $terminal)) -ne 'FOREX.com CA MT5 Terminal' -or
    $binding.account.server -notlike 'FOREX.comCA-Demo *') { throw 'FOREX demo binding required' }
$origin = (Get-Content -LiteralPath (Join-Path $data 'origin.txt') -Raw).Trim()
if ([IO.Path]::GetFullPath($origin) -ne (Split-Path -Parent $terminal)) { throw 'Terminal data origin mismatch' }
if ($build.Program -ne 'CalendarService' -or $policy.terminal_build -ne $binding.expected_build -or
    $policy.evidence_type -ne 'INDEPENDENT_CALENDAR_CHECK' -or
    $policy.evidence_hash -ne (Get-FileHash -LiteralPath $ClockEvidencePath -Algorithm SHA256).Hash.ToLowerInvariant()) {
    throw 'Build or independent clock evidence mismatch'
}
if ((Get-FileHash -LiteralPath $build.Artifact -Algorithm SHA256).Hash -ne $build.BinarySHA256 -or
    (Get-FileHash -LiteralPath (Join-Path $projectRoot 'bridges/mt5/CalendarService.mq5') -Algorithm SHA256).Hash -ne $build.SourceSHA256 -or
    (Get-FileHash -LiteralPath (Join-Path $projectRoot 'bridges/mt5/CalendarExport.mq5') -Algorithm SHA256).Hash -ne $build.ExportSourceSHA256) {
    throw 'Reviewed source or binary hash mismatch'
}
$deployment = [IO.Path]::GetFullPath($DeploymentPath)
if (Test-Path -LiteralPath $deployment) { throw 'Existing deployment refused; preserve its evidence' }
# Unique paths avoid replacing another service or a historical capture.
$instance = 'FXCalendar_' + [guid]::NewGuid().ToString('N')
$inbox = Join-Path $data ('MQL5/Files/' + $instance)
$serviceDir = Join-Path $data ('MQL5/Services/' + $instance)
New-Item -ItemType Directory -Path $deployment | Out-Null
$policy | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $deployment 'clock-policy.json') -Encoding UTF8
Copy-Item -LiteralPath $ClockEvidencePath -Destination (Join-Path $deployment 'clock-evidence.json')
# Use the Python validator and UTC decoder, never the host timezone or quote clock.
$env:PYTHONPATH = Join-Path $projectRoot 'src'
@'
import json,sys
from datetime import UTC,datetime
from pathlib import Path
from fx_talanta.calendar_collector import Deployment
from fx_talanta.mt5_calendar import ClockPolicy
root,inbox,start,end=sys.argv[1:]
root=Path(root); clock=ClockPolicy.model_validate_json((root/'clock-policy.json').read_text(encoding='utf-8-sig'))
config=Deployment(inbox=Path(inbox),installed_at=datetime.now(UTC),expires_at=clock.decode(int(end)),server_from=int(start),server_until=int(end),clock_policy=clock)
(root/'deployment.json').write_text(config.model_dump_json(indent=2)+'\n',encoding='utf-8')
'@ | & $PythonPath - $deployment $inbox $ServerFrom $ServerUntil
if ($LASTEXITCODE -ne 0) { throw 'Deployment validation failed; no terminal files installed' }
$config = Get-Content -LiteralPath (Join-Path $deployment 'deployment.json') -Raw | ConvertFrom-Json
$expires = ([DateTimeOffset]$config.expires_at).ToUnixTimeSeconds()
New-Item -ItemType Directory -Path $inbox,$serviceDir | Out-Null
Copy-Item -LiteralPath $build.Artifact -Destination (Join-Path $serviceDir 'CalendarService.ex5')
$preset = @("BridgeId=$($policy.bridge_id)", "ExpectedServer=$($binding.account.server)",
    "ServerFrom=$ServerFrom", "ServerUntil=$ServerUntil", "ExportDirectory=$instance",
    'RefreshSeconds=60', "ExpectedBuild=$($policy.terminal_build)", "StopAtUTC=$expires")
$preset | Set-Content -LiteralPath (Join-Path $deployment 'service-inputs.set') -Encoding Unicode
# A private runtime copy prevents later provider-checkout edits changing a running collector.
$runtime = Join-Path $deployment 'runtime'
New-Item -ItemType Directory -Path $runtime | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'src/fx_talanta') -Destination $runtime -Recurse
function Quote-PS([string]$value) { return "'" + $value.Replace("'", "''") + "'" }
$runner = @(
    '$ErrorActionPreference = ''Stop''',
    ('$env:PYTHONPATH = ' + (Quote-PS $runtime)),
    ('& ' + (Quote-PS ([IO.Path]::GetFullPath($PythonPath))) + ' -m fx_talanta.calendar_collector --deployment ' + (Quote-PS $deployment)),
    'exit $LASTEXITCODE'
)
$runner | Set-Content -LiteralPath (Join-Path $deployment 'collect.ps1') -Encoding UTF8
[ordered]@{instance=$instance;service_directory=$serviceDir;binary_sha256=$build.BinarySHA256;
    expires_at=$config.expires_at;installed_at=$config.installed_at;terminal_launched=$false;
    execution_enabled=$false} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $deployment 'installation.json') -Encoding UTF8
Write-Output 'Installed FOREX-only calendar service and isolated importer. Activate service in Navigator using service-inputs.set; keep Allow Algo Trading unchecked.'
