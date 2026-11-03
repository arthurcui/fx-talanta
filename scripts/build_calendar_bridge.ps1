param([Parameter(Mandatory=$true)][string]$MetaEditorPath,
      [ValidateSet('CalendarExport','CalendarService')][string]$Program='CalendarExport')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildRoot = Join-Path $projectRoot ('.local/calendar-build-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $buildRoot | Out-Null
$compiler = Join-Path $buildRoot 'metaeditor64.exe'
$source = Join-Path $buildRoot ($Program + '.mq5')
Copy-Item -LiteralPath $MetaEditorPath -Destination $compiler
Copy-Item -LiteralPath (Join-Path $projectRoot 'bridges/mt5/CalendarExport.mq5') -Destination $source
if ($Program -eq 'CalendarService') {
    Copy-Item -LiteralPath (Join-Path $projectRoot 'bridges/mt5/CalendarExport.mq5') -Destination (Join-Path $buildRoot 'CalendarExport.mq5')
    Copy-Item -LiteralPath (Join-Path $projectRoot 'bridges/mt5/CalendarService.mq5') -Destination $source
}
$compileArgs = @('/portable', ('/compile:"' + $source + '"'), '/log')
$process = Start-Process -FilePath $compiler -ArgumentList $compileArgs -WorkingDirectory $buildRoot -WindowStyle Hidden -PassThru
if (-not $process.WaitForExit(45000)) {
    $process.Kill()
    throw 'Isolated compiler timed out; its build directory is preserved.'
}
$log = Get-Content -LiteralPath (Join-Path $buildRoot ($Program + '.log')) -Raw
$binary = Join-Path $buildRoot ($Program + '.ex5')
if ($log -notmatch 'Result: 0 errors, 0 warnings,' -or -not (Test-Path -LiteralPath $binary)) {
    throw 'Compilation did not pass; inspect the preserved isolated build log.'
}
[pscustomobject]@{
    SourceSHA256 = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
    ExportSourceSHA256 = (Get-FileHash -LiteralPath (Join-Path $buildRoot 'CalendarExport.mq5') -Algorithm SHA256).Hash
    Program = $Program
    BinarySHA256 = (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash
    CompilerVersion = (Get-Item -LiteralPath $compiler).VersionInfo.FileVersion
    Artifact = $binary
    TerminalStarted = $false
}
